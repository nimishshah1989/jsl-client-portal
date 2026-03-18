"""
Benchmark data service — fetch Nifty 50 index data via yfinance.

Provides date-aligned benchmark values for portfolio comparison.
Caches downloaded data to avoid redundant API calls within a session.
"""

import logging
from datetime import date, datetime, timedelta
from typing import ClassVar

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Nifty 50 ticker on Yahoo Finance
_NIFTY_TICKER = "^NSEI"

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


def fetch_nifty_data(start_date: date, end_date: date) -> pd.DataFrame:
    """
    Fetch Nifty 50 daily close prices from Yahoo Finance.

    Args:
        start_date: First date needed (inclusive).
        end_date: Last date needed (inclusive).

    Returns:
        DataFrame with DatetimeIndex and a single column 'close'.
        Index name is 'date'. Sorted ascending by date.

    Raises:
        RuntimeError: If yfinance returns no data.
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

    # Fetch with buffer to handle holidays near start_date
    fetch_start = start_date - timedelta(days=_BUFFER_DAYS)
    # yfinance end date is exclusive, so add 1 day
    fetch_end = end_date + timedelta(days=1)

    logger.info(
        "Fetching Nifty 50 data from %s to %s via yfinance",
        fetch_start,
        fetch_end,
    )

    ticker = yf.Ticker(_NIFTY_TICKER)
    hist = ticker.history(
        start=fetch_start.isoformat(),
        end=fetch_end.isoformat(),
        auto_adjust=True,
    )

    if hist.empty:
        raise RuntimeError(
            f"yfinance returned no data for {_NIFTY_TICKER} "
            f"from {fetch_start} to {fetch_end}"
        )

    # Keep only the Close column, rename to 'close'
    df = hist[["Close"]].copy()
    df.columns = ["close"]
    df.index.name = "date"
    df = df.sort_index()

    # Cache the full fetched range
    BenchmarkCache.put(_NIFTY_TICKER, df)

    # Trim to requested range
    mask = (df.index.date >= start_date) & (df.index.date <= end_date)
    result = df.loc[mask].copy()

    logger.info("Fetched %d Nifty 50 data points", len(result))
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
    return align_benchmark(dates_idx, nifty_df)
