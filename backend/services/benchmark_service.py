"""
Benchmark data service — fetch Nifty 50 index history.

Primary source: JIP data core (`fie_v3.public.index_prices`, index_name='NIFTY').
The JIP OHLCV table is refreshed daily and covers full history back to 2020-09.

Fallback: yfinance `^NSEI` — used only if the JIP source is unreachable or
returns no rows for the requested range.
"""

import logging
import os
from datetime import date, datetime, timedelta
from typing import ClassVar

import pandas as pd
import psycopg2
import yfinance as yf
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Nifty 50 ticker on Yahoo Finance (fallback only)
_NIFTY_TICKER = "^NSEI"

# JIP data core index_name for Nifty 50 spot
_JIP_NIFTY_INDEX = "NIFTY"

# Extra days to fetch before start_date to ensure we have data for alignment
_BUFFER_DAYS = 10


class BenchmarkCache:
    """
    In-memory cache for benchmark data to avoid re-downloading the same range.
    Cleared when the process restarts (acceptable for a daily-batch workflow).
    """

    _cache: ClassVar[dict[str, pd.DataFrame]] = {}

    @classmethod
    def get(cls, ticker: str, start: date, end: date) -> pd.DataFrame | None:
        """Return cached DataFrame if the cached range covers the requested range."""
        key = ticker
        if key not in cls._cache:
            return None
        cached_df = cls._cache[key]
        if cached_df.empty:
            return None
        cached_start = cached_df.index.min().date()
        cached_end = cached_df.index.max().date()
        if cached_start <= start and cached_end >= end:
            mask = (cached_df.index.date >= start) & (cached_df.index.date <= end)
            return cached_df.loc[mask].copy()
        return None

    @classmethod
    def put(cls, ticker: str, df: pd.DataFrame) -> None:
        """Store or extend the cache for a ticker."""
        key = ticker
        if key in cls._cache and not cls._cache[key].empty:
            combined = pd.concat([cls._cache[key], df])
            combined = combined[~combined.index.duplicated(keep="last")]
            cls._cache[key] = combined.sort_index()
        else:
            cls._cache[key] = df.sort_index()

    @classmethod
    def clear(cls) -> None:
        """Clear all cached data."""
        cls._cache.clear()


def _jip_db_dsn() -> str | None:
    """
    Derive a sync DSN for the JIP data core (`fie_v3`) from DATABASE_URL_SYNC
    or DATABASE_URL. Returns None if no usable URL is configured.

    The JIP data core lives on the SAME RDS instance as `client_portal`, so we
    reuse the existing credentials and just swap the database name.
    """
    url = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "")
    if not url:
        return None
    # Strip async driver marker if present
    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    # Replace the path segment ("/client_portal") with "/fie_v3"
    if "?" in dsn:
        base, query = dsn.split("?", 1)
        base = base.rsplit("/", 1)[0] + "/fie_v3"
        dsn = f"{base}?{query}"
    else:
        dsn = dsn.rsplit("/", 1)[0] + "/fie_v3"
    return dsn


def _fetch_jip_index_history(
    index_name: str, start: date, end: date
) -> pd.DataFrame:
    """
    Query the JIP data core for a daily OHLCV series.

    Returns a DataFrame with a tz-naive DatetimeIndex and a 'close' column.
    Raises on connection error so the caller can decide to fall back.
    """
    dsn = _jip_db_dsn()
    if not dsn:
        raise RuntimeError("No DATABASE_URL configured for JIP data core lookup")

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT date, close_price
                FROM public.index_prices
                WHERE index_name = %s
                  AND date::date BETWEEN %s AND %s
                ORDER BY date ASC
                """,
                (index_name, start.isoformat(), end.isoformat()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return pd.DataFrame(columns=["close"])

    df = pd.DataFrame(rows, columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna()
    return df


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=8),
    retry=retry_if_exception_type((RuntimeError, ConnectionError, TimeoutError, Exception)),
    reraise=True,
)
def _fetch_yfinance_history(fetch_start: date, fetch_end: date) -> pd.DataFrame:
    """
    Fallback yfinance fetch with retry (used only if JIP core has no data).
    """
    ticker = yf.Ticker(_NIFTY_TICKER)
    hist = ticker.history(
        start=fetch_start.isoformat(),
        end=fetch_end.isoformat(),
        auto_adjust=True,
        timeout=30,
    )
    if hist.empty:
        raise RuntimeError(
            f"yfinance returned no data for {_NIFTY_TICKER} "
            f"from {fetch_start} to {fetch_end}"
        )
    return hist


def fetch_nifty_data(start_date: date, end_date: date) -> pd.DataFrame:
    """
    Fetch Nifty 50 daily close prices.

    Primary: JIP data core (`fie_v3.public.index_prices`, NIFTY).
    Fallback: yfinance `^NSEI` if JIP query returns empty.

    Args:
        start_date: First date needed (inclusive).
        end_date: Last date needed (inclusive).

    Returns:
        DataFrame with DatetimeIndex and a single column 'close'.
        Index name is 'date'. Sorted ascending by date.
        Returns empty DataFrame if both sources fail.
    """
    # Check cache first
    cached = BenchmarkCache.get(_NIFTY_TICKER, start_date, end_date)
    if cached is not None and not cached.empty:
        logger.info(
            "Benchmark cache hit: %s to %s (%d rows)",
            start_date,
            end_date,
            len(cached),
        )
        return cached

    fetch_start = start_date - timedelta(days=_BUFFER_DAYS)
    fetch_end = end_date

    # 1. Try JIP data core first.
    try:
        jip_df = _fetch_jip_index_history(_JIP_NIFTY_INDEX, fetch_start, fetch_end)
        if not jip_df.empty:
            logger.info(
                "JIP data core: fetched %d Nifty rows for %s to %s",
                len(jip_df), fetch_start, fetch_end,
            )
            BenchmarkCache.put(_NIFTY_TICKER, jip_df)
            mask = (jip_df.index.date >= start_date) & (jip_df.index.date <= end_date)
            return jip_df.loc[mask].copy()
        logger.warning(
            "JIP data core returned 0 rows for NIFTY %s to %s; falling back to yfinance",
            fetch_start, fetch_end,
        )
    except Exception as exc:
        logger.warning("JIP data core query failed (%s); falling back to yfinance", exc)

    # 2. Fallback to yfinance.
    try:
        hist = _fetch_yfinance_history(fetch_start, fetch_end + timedelta(days=1))
    except Exception as exc:
        logger.warning(
            "Both JIP and yfinance failed for Nifty %s to %s: %s",
            fetch_start, fetch_end, exc,
        )
        return pd.DataFrame(columns=["close"])

    df = hist[["Close"]].copy()
    df.columns = ["close"]
    df.index.name = "date"
    df = df.sort_index()
    BenchmarkCache.put(_NIFTY_TICKER, df)
    mask = (df.index.date >= start_date) & (df.index.date <= end_date)
    result = df.loc[mask].copy()
    logger.info("yfinance fallback: %d Nifty points", len(result))
    return result


def align_benchmark(
    nav_dates: pd.DatetimeIndex | pd.Series,
    nifty_df: pd.DataFrame,
) -> pd.Series:
    """
    Align Nifty close prices to the portfolio's NAV dates.

    For dates where the market was closed (weekends, holidays), the last
    available close price is forward-filled.

    Args:
        nav_dates: Portfolio NAV dates (DatetimeIndex or Series of dates).
        nifty_df: DataFrame from fetch_nifty_data() with DatetimeIndex and 'close' column.

    Returns:
        pd.Series of benchmark close prices indexed by nav_dates.
    """
    if isinstance(nav_dates, pd.Series):
        nav_dates = pd.DatetimeIndex(nav_dates)

    # Ensure nifty_df index is tz-naive to match nav_dates
    nifty = nifty_df["close"].copy()
    if nifty.index.tz is not None:
        nifty.index = nifty.index.tz_localize(None)

    # Reindex to nav_dates with forward-fill for holidays
    aligned = nifty.reindex(nav_dates, method="ffill")

    # If there are still NaN values at the start (nav starts before nifty data),
    # backfill those
    if aligned.isna().any():
        aligned = aligned.bfill()

    return aligned


def fetch_and_align(
    nav_dates: pd.DatetimeIndex | pd.Series,
) -> pd.Series:
    """
    Convenience function: fetch Nifty data for the date range of nav_dates
    and return aligned series.

    Args:
        nav_dates: Portfolio NAV dates.

    Returns:
        pd.Series of benchmark close prices aligned to nav_dates.
    """
    if isinstance(nav_dates, pd.Series):
        dates_idx = pd.DatetimeIndex(nav_dates)
    else:
        dates_idx = nav_dates

    start = dates_idx.min().date()
    end = dates_idx.max().date()

    nifty_df = fetch_nifty_data(start, end)
    if nifty_df.empty:
        logger.warning(
            "Benchmark data unavailable for %s to %s — returning empty series",
            start,
            end,
        )
        return pd.Series(dtype=float, index=dates_idx, name="close")
    return align_benchmark(dates_idx, nifty_df)
