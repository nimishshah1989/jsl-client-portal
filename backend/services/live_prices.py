"""
Fetch live NSE stock prices via yfinance and update holdings.

Also enriches holdings with sector data from the stock reference mapping.

Price resolution chain (in order):
  1. yfinance batch download  — fast, covers most NSE equities and ETFs
  2. yfinance individual retry — catches symbols that break the batch URL
  3. ISIN → NSE ticker (Yahoo Finance search) → yfinance
     For symbols where the backoffice script name doesn't match the NSE
     ticker (e.g. "Mirae Smallcap ETF" → stored as MIRAESMALLCAP, but
     the actual ticker is something like MASMC250.NS). We use the ISIN
     stored in cpp_holdings to look up the real NSE ticker via Yahoo
     Finance's search endpoint, then fetch the price via yfinance.
     Results are cached in-process so the search only runs once per symbol.
"""

import logging
from decimal import Decimal

import httpx
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

# ISIN → resolved NSE ticker cache (populated lazily, lives for process lifetime)
_ISIN_TICKER_CACHE: dict[str, str | None] = {}

# Symbols confirmed to have no exchange listing (AMC name used as symbol in backoffice,
# not resolvable to any specific instrument without manual intervention).
_UNRESOLVABLE_SYMBOLS: frozenset[str] = frozenset({
    "ICICIPRUDENTIALMUTUALFUND",   # AMC name, not a specific fund/ETF
})


def _resolve_ticker(symbol: str) -> str | None:
    """Resolve a DB symbol to its yfinance-compatible NSE ticker.

    Returns None for confirmed-unresolvable symbols.
    Applies _SYMBOL_OVERRIDES (same map used in txn_parser) so that even
    old DB records with full company names get the right ticker.
    """
    if symbol in _UNRESOLVABLE_SYMBOLS:
        return None
    canonical = _SYMBOL_OVERRIDES.get(symbol, symbol)
    return f"{canonical}.NS"


def _isin_to_nse_ticker(isin: str) -> str | None:
    """
    Resolve an ISIN to an NSE-listed yfinance ticker via Yahoo Finance search API.

    Yahoo Finance's /v1/finance/search endpoint accepts ISINs and returns matching
    instruments with their exchange-qualified ticker (e.g. "MASMC250.NS"). This is
    how we find the real NSE ticker when the backoffice records a script name that
    doesn't match the NSE symbol (e.g. "Mirae Smallcap ETF" → "MASMC250").

    Results are cached in _ISIN_TICKER_CACHE for the process lifetime so each ISIN
    is searched at most once.

    Returns e.g. "MASMC250.NS" or None if not found on NSE/BSE.
    """
    if isin in _ISIN_TICKER_CACHE:
        return _ISIN_TICKER_CACHE[isin]

    ticker: str | None = None
    try:
        resp = httpx.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={
                "q": isin,
                "quotesCount": 5,
                "newsCount": 0,
                "enableFuzzyQuery": "false",
            },
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; portfolio-tracker/1.0)"},
            follow_redirects=True,
        )
        if resp.status_code == 200:
            quotes = resp.json().get("quotes", [])
            # Prefer NSE (.NS) over BSE (.BO) — NSE has higher liquidity
            for q in quotes:
                sym = q.get("symbol", "")
                if sym.endswith(".NS"):
                    ticker = sym
                    break
            if ticker is None:
                for q in quotes:
                    sym = q.get("symbol", "")
                    if sym.endswith(".BO"):
                        ticker = sym
                        break
    except Exception as exc:
        logger.debug("ISIN search failed for %s: %s", isin, exc)

    _ISIN_TICKER_CACHE[isin] = ticker
    if ticker:
        logger.info("ISIN→ticker resolved: %s → %s", isin, ticker)
    else:
        logger.debug("ISIN→ticker: no NSE/BSE result for %s", isin)
    return ticker


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    reraise=True,
)
def _download_prices(ticker_str: str) -> "pd.DataFrame":
    """Internal helper: yfinance download with retry (3 attempts, exponential backoff)."""
    import pandas as pd  # noqa: F811

    data = yf.download(
        ticker_str, period="5d", progress=False, auto_adjust=True,
        threads=True, timeout=30,
    )
    return data


def _extract_close(data, yf_ticker: str, n_symbols: int) -> float | None:
    try:
        close_col = data["Close"] if n_symbols == 1 else data["Close"][yf_ticker]
        val = close_col.dropna().iloc[-1]
        return float(val) if val > 0 else None
    except (KeyError, IndexError, TypeError):
        return None


def fetch_live_prices(symbols: list[str]) -> dict[str, Decimal]:
    """
    Fetch latest close prices for a list of NSE symbols.

    Resolves each symbol to its canonical NSE ticker via _resolve_ticker.
    Batch-downloads via yfinance, with individual retry fallback for any
    symbols the batch missed.

    Returns dict of {original_symbol: price_decimal}.
    Unresolvable or unlisted symbols are omitted (caller tries ISIN fallback).
    """
    if not symbols:
        return {}

    tickers: dict[str, str] = {}
    for sym in symbols:
        yf_ticker = _resolve_ticker(sym)
        if yf_ticker is not None:
            tickers[sym] = yf_ticker

    prices: dict[str, Decimal] = {}
    if not tickers:
        return prices

    # Batch download
    ticker_str = " ".join(tickers.values())
    batch_ok = False
    try:
        data = _download_prices(ticker_str)
        if not data.empty:
            batch_ok = True
            for sym, yf_ticker in tickers.items():
                price = _extract_close(data, yf_ticker, len(tickers))
                if price is not None:
                    prices[sym] = Decimal(str(round(price, 4)))
    except Exception as exc:
        logger.warning("yfinance batch download failed (%d symbols): %s", len(tickers), exc)

    # Individual retry for batch misses
    missed = {sym: ytk for sym, ytk in tickers.items() if sym not in prices}
    if missed and (not batch_ok or missed):
        for sym, yf_ticker in missed.items():
            try:
                data = _download_prices(yf_ticker)
                if not data.empty:
                    price = _extract_close(data, yf_ticker, 1)
                    if price is not None:
                        prices[sym] = Decimal(str(round(price, 4)))
            except Exception:
                continue

    return prices


async def update_holdings_prices(db: AsyncSession) -> dict[str, int]:
    """
    Fetch live prices for all held symbols and update cpp_holdings.

    Price resolution order:
      1. yfinance ticker-based (batch + individual retry)
         Covers NSE-listed equities and ETFs with known tickers.
      2. ISIN → NSE ticker via Yahoo Finance search → yfinance
         Handles ETFs recorded under script descriptions instead of NSE
         tickers (e.g. "MIRAESMALLCAP" → resolved to "MASMC250.NS" via ISIN).
         The resolved ticker is cached in-process and added to _SYMBOL_OVERRIDES
         log for future manual confirmation.

    Also fills in sector data from the stock reference mapping.
    Returns summary dict with counts.
    """
    result = await db.execute(
        text("SELECT DISTINCT symbol FROM cpp_holdings WHERE quantity > 0")
    )
    symbols = [row[0] for row in result.fetchall()]
    if not symbols:
        return {"symbols": 0, "prices_updated": 0, "sectors_updated": 0}

    logger.info("Fetching live prices for %d symbols", len(symbols))

    # ── Stage 1: yfinance (batch + individual retry) ──────────────────────────
    all_prices: dict[str, Decimal] = {}
    batch_size = 50
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        all_prices.update(fetch_live_prices(batch))

    # ── Stage 2: ISIN → NSE ticker via Yahoo Finance search → yfinance ───────
    still_unpriced = set(symbols) - set(all_prices.keys()) - _UNRESOLVABLE_SYMBOLS
    if still_unpriced:
        logger.info(
            "%d symbols still unpriced — trying ISIN→ticker resolution",
            len(still_unpriced),
        )
        # Fetch ISINs for these symbols
        isin_result = await db.execute(
            text("""
                SELECT DISTINCT ON (symbol) symbol, isin
                FROM cpp_holdings
                WHERE symbol = ANY(:syms)
                  AND isin IS NOT NULL AND isin != ''
                ORDER BY symbol
            """),
            {"syms": list(still_unpriced)},
        )
        symbol_isin: dict[str, str] = {
            row[0]: row[1]
            for row in isin_result.fetchall()
            if row[1] and row[1].strip()
        }

        if symbol_isin:
            # For each ISIN, resolve to an NSE ticker via Yahoo Finance search
            resolved_tickers: dict[str, str] = {}  # db_symbol → yf_ticker
            for sym, isin in symbol_isin.items():
                yf_ticker = _isin_to_nse_ticker(isin)
                if yf_ticker:
                    resolved_tickers[sym] = yf_ticker

            # Fetch prices for resolved tickers individually
            for sym, yf_ticker in resolved_tickers.items():
                try:
                    data = _download_prices(yf_ticker)
                    if not data.empty:
                        price = _extract_close(data, yf_ticker, 1)
                        if price is not None:
                            all_prices[sym] = Decimal(str(round(price, 4)))
                            logger.info(
                                "ISIN fallback priced %s via %s: %.4f",
                                sym, yf_ticker, float(all_prices[sym]),
                            )
                except Exception as exc:
                    logger.debug(
                        "ISIN fallback fetch failed for %s (%s): %s", sym, yf_ticker, exc
                    )

    # ── DB update: prices ─────────────────────────────────────────────────────
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

    # ── DB update: sectors ────────────────────────────────────────────────────
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
