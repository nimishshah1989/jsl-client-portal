"""
Fetch live NSE stock prices via yfinance and update holdings.

Also enriches holdings with sector data from the stock reference mapping.
"""

import logging
from decimal import Decimal, ROUND_HALF_UP

import yfinance as yf
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.services.stock_reference import SECTOR_MAP
from backend.services.txn_parser import _SYMBOL_OVERRIDES

logger = logging.getLogger(__name__)

_TWO = Decimal("0.01")

# Symbols that have no exchange-listed price (MF units, NAV-only instruments).
# These are expected to be unpriced and should not be retried.
_MF_SYMBOLS: frozenset[str] = frozenset({
    "MIRAESMALLCAP",
    "ICICIPRUDENTIALMUTUALFUND",
})


def _resolve_ticker(symbol: str) -> str | None:
    """Resolve a DB symbol to its yfinance-compatible NSE ticker.

    Returns None for MF units that have no exchange listing.
    Applies _SYMBOL_OVERRIDES (same map used in txn_parser) so that
    even old DB records with full company names get the right ticker.
    """
    if symbol in _MF_SYMBOLS:
        return None
    canonical = _SYMBOL_OVERRIDES.get(symbol, symbol)
    return f"{canonical}.NS"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    reraise=True,
)
def _download_prices(ticker_str: str) -> "pd.DataFrame":
    """Internal helper: yfinance download with retry (3 attempts, exponential backoff)."""
    import pandas as pd  # noqa: F811 — local import to avoid circular at module level

    data = yf.download(
        ticker_str, period="5d", progress=False, auto_adjust=True,
        threads=True, timeout=30,
    )
    return data


def fetch_live_prices(symbols: list[str]) -> dict[str, Decimal]:
    """
    Fetch latest close prices for a list of NSE symbols.

    Resolves each symbol to its canonical NSE ticker via _resolve_ticker
    (handles company-name aliases, mergers, ETF overrides). MF units that
    have no exchange listing are skipped silently.

    Batch-downloads via yfinance. If the batch fails (e.g. due to a symbol
    with special characters breaking the URL), falls back to fetching each
    symbol individually so the rest of the batch is not lost.

    Returns dict of {original_symbol: price_decimal}. Unresolvable or truly
    unlisted symbols are omitted.
    """
    if not symbols:
        return {}

    # Resolve each symbol to its yfinance ticker, skipping MF units
    tickers: dict[str, str] = {}  # original_symbol → yf_ticker
    for sym in symbols:
        yf_ticker = _resolve_ticker(sym)
        if yf_ticker is not None:
            tickers[sym] = yf_ticker

    prices: dict[str, Decimal] = {}
    if not tickers:
        return prices

    def _extract_price(data, yf_ticker: str, n_symbols: int) -> float | None:
        try:
            close_col = data["Close"] if n_symbols == 1 else data["Close"][yf_ticker]
            val = close_col.dropna().iloc[-1]
            return float(val) if val > 0 else None
        except (KeyError, IndexError, TypeError):
            return None

    # Attempt batch download first
    ticker_str = " ".join(tickers.values())
    batch_ok = False
    try:
        data = _download_prices(ticker_str)
        if not data.empty:
            batch_ok = True
            for sym, yf_ticker in tickers.items():
                price = _extract_price(data, yf_ticker, len(tickers))
                if price is not None:
                    prices[sym] = Decimal(str(round(price, 4)))
    except Exception as exc:
        logger.warning("yfinance batch download failed (%d symbols): %s", len(tickers), exc)

    # Fall back: fetch individually any that the batch missed
    missed = {sym: ytk for sym, ytk in tickers.items() if sym not in prices}
    if missed and (not batch_ok or missed):
        for sym, yf_ticker in missed.items():
            try:
                data = _download_prices(yf_ticker)
                if not data.empty:
                    price = _extract_price(data, yf_ticker, 1)
                    if price is not None:
                        prices[sym] = Decimal(str(round(price, 4)))
            except Exception:
                continue  # truly not found — stays unpriced

    return prices


def fetch_prices_by_isin(isin_map: dict[str, str]) -> dict[str, Decimal]:
    """
    Fetch prices using ISINs as fallback for symbols that couldn't be priced by ticker.

    yfinance accepts ISINs directly as Ticker identifiers for most NSE-listed securities.
    This is robust against symbol name changes, mergers, and ETF renames.

    Args:
        isin_map: {symbol: isin} — only symbols still needing prices

    Returns:
        {symbol: price_decimal} for those successfully priced via ISIN
    """
    prices: dict[str, Decimal] = {}
    for sym, isin in isin_map.items():
        if not isin or len(isin) < 10:  # ISINs are 12 chars; skip empty/garbage
            continue
        try:
            ticker_obj = yf.Ticker(isin)
            hist = ticker_obj.history(period="5d")
            if hist.empty:
                logger.debug("ISIN fallback: empty history for %s (%s)", sym, isin)
                continue
            close_vals = hist["Close"].dropna()
            if len(close_vals) == 0:
                continue
            val = float(close_vals.iloc[-1])
            if val > 0:
                prices[sym] = Decimal(str(round(val, 4)))
                logger.info("ISIN fallback priced %s via %s: %.4f", sym, isin, val)
        except Exception as exc:
            logger.debug("ISIN fallback failed for %s (%s): %s", sym, isin, exc)
    return prices


async def update_holdings_prices(db: AsyncSession) -> dict[str, int]:
    """
    Fetch live prices for all held symbols and update cpp_holdings.

    Price resolution order:
      1. Ticker-based batch download (fast, covers 95%+ of symbols)
      2. Ticker-based individual retry (catches symbols that broke the batch)
      3. ISIN-based lookup (fallback for renamed/merged/special-char symbols)

    Also fills in sector data from the stock reference mapping.

    Returns summary dict with counts.
    """
    # Get all distinct symbols with positive holdings
    result = await db.execute(
        text("SELECT DISTINCT symbol FROM cpp_holdings WHERE quantity > 0")
    )
    symbols = [row[0] for row in result.fetchall()]
    if not symbols:
        return {"symbols": 0, "prices_updated": 0, "sectors_updated": 0}

    logger.info("Fetching live prices for %d symbols", len(symbols))

    # Fetch prices in batches of 50 (yfinance limit)
    all_prices: dict[str, Decimal] = {}
    batch_size = 50
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        batch_prices = fetch_live_prices(batch)
        all_prices.update(batch_prices)

    # ISIN-based fallback for symbols still unpriced after ticker lookup
    still_unpriced = (set(symbols) - set(all_prices.keys())) - _MF_SYMBOLS
    if still_unpriced:
        logger.info(
            "%d symbols still unpriced after ticker lookup — trying ISIN fallback",
            len(still_unpriced),
        )
        isin_result = await db.execute(
            text("""
                SELECT DISTINCT ON (symbol) symbol, isin
                FROM cpp_holdings
                WHERE symbol = ANY(:syms)
                  AND isin IS NOT NULL AND isin != ''
                ORDER BY symbol, updated_at DESC NULLS LAST
            """),
            {"syms": list(still_unpriced)},
        )
        isin_map = {
            row[0]: row[1]
            for row in isin_result.fetchall()
            if row[1] and row[1].strip()
        }
        if isin_map:
            isin_prices = fetch_prices_by_isin(isin_map)
            all_prices.update(isin_prices)
            if isin_prices:
                logger.info(
                    "ISIN fallback resolved %d additional symbols: %s",
                    len(isin_prices),
                    sorted(isin_prices.keys()),
                )

    # Update prices in DB
    price_count = 0
    for symbol, price in all_prices.items():
        await db.execute(
            text("""
                UPDATE cpp_holdings
                SET current_price = :price,
                    current_value = quantity * :price,
                    unrealized_pnl = (quantity * :price) - (quantity * avg_cost),
                    updated_at = NOW()
                WHERE symbol = :sym AND quantity > 0
            """),
            {"price": price, "sym": symbol},
        )
        price_count += 1

    # Recompute weight_pct per portfolio after price updates
    await db.execute(text("""
        UPDATE cpp_holdings h
        SET weight_pct = CASE
            WHEN totals.total_value > 0
            THEN (h.current_value / totals.total_value * 100)
            ELSE 0
        END
        FROM (
            SELECT client_id, portfolio_id, SUM(current_value) as total_value
            FROM cpp_holdings
            WHERE quantity > 0 AND current_value > 0
            GROUP BY client_id, portfolio_id
        ) totals
        WHERE h.client_id = totals.client_id
          AND h.portfolio_id = totals.portfolio_id
          AND h.quantity > 0
    """))

    # Update sector data from reference mapping
    sector_count = 0
    for symbol in symbols:
        sector = SECTOR_MAP.get(symbol)
        if sector:
            await db.execute(
                text("""
                    UPDATE cpp_holdings
                    SET sector = :sector
                    WHERE symbol = :sym AND quantity > 0
                """),
                {"sector": sector, "sym": symbol},
            )
            sector_count += 1

    await db.commit()
    not_found = sorted(set(symbols) - set(all_prices.keys()))
    logger.info(
        "Updated %d prices, %d sectors for %d symbols; not found: %s",
        price_count, sector_count, len(symbols), not_found,
    )
    return {
        "symbols": len(symbols),
        "prices_updated": price_count,
        "sectors_updated": sector_count,
        "prices_not_found": len(not_found),
        "unpriced_symbols": not_found,
    }
