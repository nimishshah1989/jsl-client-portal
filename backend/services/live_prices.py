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

logger = logging.getLogger(__name__)

_TWO = Decimal("0.01")


def _nse_ticker(symbol: str) -> str:
    """Convert NSE symbol to yfinance ticker (append .NS)."""
    return f"{symbol}.NS"


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

    Returns dict of {symbol: price_decimal}. Symbols that fail are omitted.
    On complete failure after retries, returns empty dict (does not crash).
    """
    if not symbols:
        return {}

    tickers = {sym: _nse_ticker(sym) for sym in symbols}
    prices: dict[str, Decimal] = {}

    # Batch download — yfinance supports multiple tickers at once
    ticker_str = " ".join(tickers.values())
    try:
        data = _download_prices(ticker_str)
        if data.empty:
            return prices

        # yf.download returns MultiIndex columns when multiple tickers
        for symbol, yf_ticker in tickers.items():
            try:
                if len(symbols) == 1:
                    close_col = data["Close"]
                else:
                    close_col = data["Close"][yf_ticker]

                last_price = close_col.dropna().iloc[-1]
                if last_price > 0:
                    prices[symbol] = Decimal(str(round(float(last_price), 4)))
            except (KeyError, IndexError):
                continue
    except Exception as exc:
        logger.warning(
            "yfinance batch download failed after retries for %d symbols: %s",
            len(symbols),
            exc,
        )

    return prices


async def update_holdings_prices(db: AsyncSession) -> dict[str, int]:
    """
    Fetch live prices for all held symbols and update cpp_holdings.

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
    logger.info(
        "Updated %d prices, %d sectors for %d symbols",
        price_count, sector_count, len(symbols),
    )
    return {
        "symbols": len(symbols),
        "prices_updated": price_count,
        "sectors_updated": sector_count,
        "prices_not_found": len(symbols) - price_count,
    }
