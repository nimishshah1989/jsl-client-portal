"""
Fetch live NSE stock prices via yfinance and update holdings.

Price resolution — two paths, decided per symbol:

  Path A (ISIN-first):  symbol has an ISIN stored in cpp_holdings
    1. Resolve ISIN → NSE ticker via isin_resolver (DB cache or Yahoo Finance search)
    2. Fetch price via yfinance using the resolved ticker
    This is the authoritative path. ISINs are stable; script names are not.

  Path B (symbol-based): symbol has no ISIN (old records, pre-21-col format)
    1. Apply _SYMBOL_OVERRIDES to map known company-name variants to NSE tickers
    2. Fetch via yfinance
    This is the legacy fallback for data ingested before ISINs were captured.

Both paths use yfinance batch download first, then individual retry for misses.
"""

import logging
from decimal import Decimal

import yfinance as yf
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.services.isin_resolver import (
    isin_to_symbol,
    resolve_batch,
    seed_cache_from_db,
)
from backend.services.stock_reference import SECTOR_MAP
from backend.services.txn_parser import _SYMBOL_OVERRIDES

logger = logging.getLogger(__name__)

# Symbols confirmed to have no resolvable NSE/BSE listing.
# These are AMC names mistakenly recorded as instrument names in the backoffice.
_UNRESOLVABLE_SYMBOLS: frozenset[str] = frozenset({
    "ICICIPRUDENTIALMUTUALFUND",
    "GDL",          # Gateway Distriparks — delisted from NSE in June 2023 (Blackstone buyout)
    "TINPLATE",     # The Tinplate Company of India — merged into Tata Steel, delisted
})


def _symbol_to_ticker(symbol: str) -> str | None:
    """
    Resolve a plain DB symbol to a yfinance-compatible NSE ticker.
    Used for Path B (no ISIN available).

    Returns None for confirmed-unresolvable symbols.
    """
    if symbol in _UNRESOLVABLE_SYMBOLS:
        return None
    canonical = _SYMBOL_OVERRIDES.get(symbol, symbol)
    return f"{canonical}.NS"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    reraise=True,
)
def _yf_download(ticker_str: str) -> "pd.DataFrame":
    """yfinance download with retry."""
    import pandas as pd  # noqa: F811

    return yf.download(
        ticker_str, period="5d", progress=False, auto_adjust=True,
        threads=True, timeout=30,
    )


def _extract_close(data, yf_ticker: str, n_symbols: int) -> float | None:
    try:
        close_col = data["Close"] if n_symbols == 1 else data["Close"][yf_ticker]
        val = close_col.dropna().iloc[-1]
        return float(val) if val > 0 else None
    except (KeyError, IndexError, TypeError):
        return None


def _fetch_by_tickers(
    ticker_map: dict[str, str],
) -> dict[str, Decimal]:
    """
    Fetch prices for a {key: yf_ticker} map.
    Tries batch download first; falls back to individual fetches for misses.
    Returns {key: price}.
    """
    if not ticker_map:
        return {}

    prices: dict[str, Decimal] = {}

    # Batch attempt
    ticker_str = " ".join(ticker_map.values())
    batch_ok = False
    try:
        data = _yf_download(ticker_str)
        if not data.empty:
            batch_ok = True
            for key, yf_ticker in ticker_map.items():
                price = _extract_close(data, yf_ticker, len(ticker_map))
                if price is not None:
                    prices[key] = Decimal(str(round(price, 4)))
    except Exception as exc:
        logger.warning("yfinance batch failed (%d tickers): %s", len(ticker_map), exc)

    # Individual retry for misses
    missed = {k: t for k, t in ticker_map.items() if k not in prices}
    if missed and (not batch_ok or missed):
        for key, yf_ticker in missed.items():
            try:
                data = _yf_download(yf_ticker)
                if not data.empty:
                    price = _extract_close(data, yf_ticker, 1)
                    if price is not None:
                        prices[key] = Decimal(str(round(price, 4)))
            except Exception:
                continue

    return prices


async def update_holdings_prices(db: AsyncSession) -> dict[str, int]:
    """
    Fetch live prices for all held symbols and update cpp_holdings.

    Path A — ISIN-first (primary):
      For each symbol with an ISIN in cpp_holdings, the ISIN is resolved
      to the canonical NSE ticker via isin_resolver. Price is fetched using
      that ticker. This path is independent of how the backoffice named the
      instrument.

    Path B — symbol-based (fallback for no-ISIN records):
      Applies _SYMBOL_OVERRIDES to map known company-name variants, then
      fetches via yfinance. Used for data ingested before ISIN capture.

    Also fills in sector data from the stock reference mapping.
    Returns summary dict with counts.
    """
    # Load all held symbols with their ISINs
    result = await db.execute(
        text("""
            SELECT DISTINCT symbol, isin
            FROM cpp_holdings
            WHERE quantity > 0
        """)
    )
    rows = result.fetchall()
    if not rows:
        return {"symbols": 0, "prices_updated": 0, "sectors_updated": 0}

    symbols = [r[0] for r in rows]
    symbol_isin: dict[str, str] = {
        r[0]: r[1]
        for r in rows
        if r[1] and r[1].strip() and len(r[1].strip()) == 12
    }

    logger.info(
        "Fetching prices for %d symbols (%d with ISIN, %d symbol-only)",
        len(symbols),
        len(symbol_isin),
        len(symbols) - len(symbol_isin),
    )

    # ── Seed ISIN cache from DB (fast, no network) ────────────────────────────
    await seed_cache_from_db(db)

    # ── Path A: ISIN-first ─────────────────────────────────────────────────────
    # Resolve all ISINs to NSE tickers (batch — only unknown ones hit Yahoo Finance)
    isin_list = list(set(symbol_isin.values()))
    isin_ticker_map = await resolve_batch(isin_list)  # {isin: "TICKER.NS"}

    # Build {db_symbol: yf_ticker} for ISIN-resolved symbols
    isin_fetch_map: dict[str, str] = {}
    for sym, isin in symbol_isin.items():
        if sym in _UNRESOLVABLE_SYMBOLS:
            continue
        ticker = isin_ticker_map.get(isin)
        if ticker:
            isin_fetch_map[sym] = ticker

    all_prices: dict[str, Decimal] = {}

    if isin_fetch_map:
        isin_prices = _fetch_by_tickers(isin_fetch_map)
        all_prices.update(isin_prices)
        logger.info(
            "Path A (ISIN): priced %d / %d symbols",
            len(isin_prices),
            len(isin_fetch_map),
        )

    # ── Path B: symbol-based (no ISIN or unresolved ISIN) ────────────────────
    path_b_symbols = [
        s for s in symbols
        if s not in all_prices
        and s not in _UNRESOLVABLE_SYMBOLS
        # Path B: no ISIN, OR ISIN wasn't resolved by Yahoo Finance
    ]
    if path_b_symbols:
        sym_ticker_map: dict[str, str] = {}
        for sym in path_b_symbols:
            ticker = _symbol_to_ticker(sym)
            if ticker:
                sym_ticker_map[sym] = ticker

        if sym_ticker_map:
            # Batch in groups of 50
            batch_size = 50
            sym_items = list(sym_ticker_map.items())
            for i in range(0, len(sym_items), batch_size):
                chunk = dict(sym_items[i : i + batch_size])
                chunk_prices = _fetch_by_tickers(chunk)
                all_prices.update(chunk_prices)

            b_priced = sum(1 for s in path_b_symbols if s in all_prices)
            logger.info(
                "Path B (symbol): priced %d / %d symbols",
                b_priced,
                len(path_b_symbols),
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

    # Recompute weight_pct per portfolio
    await db.execute(text("""
        UPDATE cpp_holdings h
        SET weight_pct = CASE
            WHEN totals.total_value > 0
            THEN (h.current_value / totals.total_value * 100)
            ELSE 0
        END
        FROM (
            SELECT client_id, portfolio_id, SUM(current_value) AS total_value
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

    not_found = sorted(set(symbols) - set(all_prices.keys()) - _UNRESOLVABLE_SYMBOLS)
    logger.info(
        "Prices updated: %d priced, %d sectors, %d symbols total; still unpriced: %s",
        price_count, sector_count, len(symbols), not_found,
    )
    return {
        "symbols": len(symbols),
        "prices_updated": price_count,
        "sectors_updated": sector_count,
        "prices_not_found": len(not_found),
        "unpriced_symbols": not_found,
    }
