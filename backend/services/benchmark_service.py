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
    reuse the existing credentials and just swap the database name. We also
    layer in the same TLS posture the main app uses (see backend/database.py):
    when the RDS CA bundle is present on disk and we're connecting to RDS,
    require sslmode=verify-full with the bundle pinned as sslrootcert.
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
        query = ""

    # Layer SSL params for psycopg2. psycopg2 doesn't accept an ssl.SSLContext
    # directly (unlike asyncpg), so we mirror database.py's policy via libpq
    # connection parameters.
    ca_bundle = os.getenv("RDS_CA_BUNDLE", "/app/rds-combined-ca-bundle.pem")
    is_rds = "rds.amazonaws.com" in dsn
    has_bundle = ca_bundle and os.path.exists(ca_bundle)

    existing_lower = query.lower() if query else ""
    extra_params: list[str] = []
    if "sslmode=" not in existing_lower:
        if is_rds and has_bundle:
            extra_params.append("sslmode=verify-full")
        else:
            # Encrypt the wire even in dev; skip CA verification when no bundle.
            extra_params.append("sslmode=require")
    if is_rds and has_bundle and "sslrootcert=" not in existing_lower:
        extra_params.append(f"sslrootcert={ca_bundle}")

    if extra_params:
        sep = "&" if "?" in dsn else "?"
        dsn = f"{dsn}{sep}{'&'.join(extra_params)}"
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


# Max number of calendar days a single benchmark close may be forward-filled
# to cover an unobserved nav date. NSE has at most ~4 consecutive non-trading
# days (long weekends + national holiday). A 7-day cap absorbs that without
# allowing a single survived value to propagate across months or years —
# which previously turned a sparsely-fetched benchmark into a near-flat
# series (Vol ≈ 0.5%, Abs Return ≈ +0.05% across ALL periods).
_BENCHMARK_FFILL_LIMIT_DAYS = 7


def align_benchmark(
    nav_dates: pd.DatetimeIndex | pd.Series,
    nifty_df: pd.DataFrame,
) -> pd.Series:
    """
    Align Nifty close prices to the portfolio's NAV dates.

    For dates where the market was closed (weekends, holidays), the last
    available close price is forward-filled — but only for up to
    ``_BENCHMARK_FFILL_LIMIT_DAYS`` calendar days. Beyond that the value is
    left NaN so the caller can detect gaps and not silently propagate a stale
    quote across months/years.

    A small ``bfill`` (also capped) covers the very-first nav dates that may
    fall before the first available benchmark observation.

    Args:
        nav_dates: Portfolio NAV dates (DatetimeIndex or Series of dates).
        nifty_df: DataFrame from fetch_nifty_data() with DatetimeIndex and 'close' column.

    Returns:
        pd.Series of benchmark close prices indexed by nav_dates. Cells that
        could not be filled within the cap remain NaN.
    """
    if isinstance(nav_dates, pd.Series):
        nav_dates = pd.DatetimeIndex(nav_dates)

    # Ensure both sides are tz-naive before reindex.
    # tz_convert(None) is the correct pandas 2.x approach for stripping timezone;
    # tz_localize(None) on a tz-aware index is deprecated and raises TypeError
    # in some pandas 2.2 builds when the index has a non-UTC timezone.
    nifty = nifty_df["close"].copy()
    if nifty.index.tz is not None:
        nifty = nifty.tz_convert(None)

    if nav_dates.tz is not None:
        nav_dates = nav_dates.tz_convert(None)

    # Build the union of benchmark dates and nav dates so we can apply a
    # *day-aware* forward-fill cap. pandas' ffill `limit=` counts ROWS, but on
    # the union index every consecutive day is one row, so the limit becomes
    # a calendar-day cap.
    union_idx = nifty.index.union(nav_dates).sort_values()
    # Densify to daily frequency between min/max so the row-count == day-count
    if len(union_idx) > 0:
        union_idx = pd.date_range(union_idx.min(), union_idx.max(), freq="D")
    densified = nifty.reindex(union_idx)

    filled = densified.ffill(limit=_BENCHMARK_FFILL_LIMIT_DAYS)
    # Limited bfill for nav dates before first observation (long-weekend gap only).
    filled = filled.bfill(limit=_BENCHMARK_FFILL_LIMIT_DAYS)

    # Now select only the nav dates we actually need.
    aligned = filled.reindex(nav_dates)

    # Sanity-check the result. If after ffill+bfill we end up with fewer than
    # 2 distinct values, OR with at least 30% of cells still NaN, the source
    # data was too sparse to produce a meaningful benchmark — return an empty
    # series so the caller logs a clear "benchmark unavailable" rather than
    # writing a flat constant.
    non_na = aligned.dropna()
    if len(non_na) == 0:
        return pd.Series(dtype=float, index=nav_dates, name="close")

    distinct_vals = non_na.nunique()
    nan_ratio = aligned.isna().mean() if len(aligned) else 0.0

    if distinct_vals < 2 or nan_ratio > 0.30:
        # Suspiciously sparse — refuse to publish a flat/near-flat series.
        logger.warning(
            "Benchmark data too sparse to align: %d distinct values, "
            "%.0f%% NaN cells across %d nav dates. Returning empty so "
            "benchmark cells stay NULL rather than flat.",
            distinct_vals,
            nan_ratio * 100,
            len(aligned),
        )
        return pd.Series(dtype=float, index=nav_dates, name="close")

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
