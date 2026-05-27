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


def _write_jip_index_history(index_name: str, df: pd.DataFrame) -> int:
    """
    Idempotently write (date, close_price) rows into fie_v3.public.index_prices
    for the given index_name. Used when yfinance is the source of truth for
    dates that fie_v3 hasn't ingested yet — we write back so subsequent reads
    hit the canonical source and we don't keep calling the external API.

    Uses ON CONFLICT (date, index_name) DO NOTHING. If the table is owned by
    another writer and the conflict target differs, the conflict still resolves
    safely (no rows inserted, no exception).

    Returns the number of rows the INSERT actually wrote (after conflict
    resolution). Returns 0 if no JIP DSN is configured or the table is not
    writable — write failures are logged at WARNING and never raised, because
    a write-back failure must not break ingestion.
    """
    if df is None or df.empty:
        return 0

    dsn = _jip_db_dsn()
    if not dsn:
        logger.debug("No JIP DSN configured; skipping write-back of %d rows", len(df))
        return 0

    # Materialise (date, close) tuples so we don't depend on the DataFrame's
    # exact dtype downstream. Drop NaN closes — they're useless.
    pairs: list[tuple] = []
    for ts, val in df["close"].items():
        if val is None or pd.isna(val):
            continue
        d = ts.date() if hasattr(ts, "date") else ts
        pairs.append((d, float(val)))

    if not pairs:
        return 0

    try:
        conn = psycopg2.connect(dsn)
        try:
            with conn.cursor() as cur:
                # ON CONFLICT target matches the natural key on the table
                # (date + index_name). If the deployed table uses a different
                # constraint name, fall back to a do-nothing INSERT path.
                try:
                    cur.executemany(
                        """
                        INSERT INTO public.index_prices (date, index_name, close_price)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (date, index_name) DO NOTHING
                        """,
                        [(d, index_name, c) for (d, c) in pairs],
                    )
                    written = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                except psycopg2.errors.InvalidColumnReference:
                    # Conflict target doesn't exist — fall back to a guarded insert.
                    conn.rollback()
                    written = 0
                    with conn.cursor() as cur2:
                        for d, c in pairs:
                            try:
                                cur2.execute(
                                    """
                                    INSERT INTO public.index_prices
                                        (date, index_name, close_price)
                                    SELECT %s, %s, %s
                                    WHERE NOT EXISTS (
                                        SELECT 1 FROM public.index_prices
                                        WHERE date = %s AND index_name = %s
                                    )
                                    """,
                                    (d, index_name, c, d, index_name),
                                )
                                if cur2.rowcount:
                                    written += cur2.rowcount
                            except Exception as inner:
                                logger.debug(
                                    "Write-back skipped for %s: %s", d, inner
                                )
            conn.commit()
        finally:
            conn.close()
        if written:
            logger.info(
                "Wrote back %d %s row(s) to fie_v3.index_prices "
                "(yfinance → JIP cache hydration)",
                written, index_name,
            )
        return written
    except Exception as exc:
        # Write-back failure is non-fatal: the in-memory data is still usable
        # for the current ingestion, we just won't have it cached for next time.
        logger.warning(
            "Failed to write back %d Nifty rows to fie_v3.index_prices: %s",
            len(pairs), exc,
        )
        return 0


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


def _trading_days_in_range(start: date, end: date) -> list[date]:
    """Return calendar weekdays in [start, end] inclusive — a cheap proxy for
    NSE trading days when checking whether fie_v3 has comprehensive coverage.

    We don't have the actual NSE holiday calendar at the data layer; weekday
    coverage is a sufficient gate to decide "do we need to call yfinance to
    fill a gap?". The price of an occasional unnecessary yfinance call on a
    holiday is bounded (the cache absorbs the result for the rest of the day).
    """
    out: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:  # Mon-Fri
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _missing_dates(have: pd.DataFrame, start: date, end: date) -> list[date]:
    """Compute the trading days in [start, end] that are NOT present in
    ``have``'s DatetimeIndex. Used to decide whether yfinance needs to be
    consulted to fill holes in the fie_v3 coverage."""
    if have is None or have.empty:
        return _trading_days_in_range(start, end)
    have_dates = {ts.date() for ts in have.index}
    return [d for d in _trading_days_in_range(start, end) if d not in have_dates]


def fetch_nifty_data(start_date: date, end_date: date) -> pd.DataFrame:
    """
    Fetch Nifty 50 daily close prices.

    Self-healing source order:
      1. JIP data core (`fie_v3.public.index_prices`, NIFTY) — canonical.
      2. yfinance `^NSEI` fills any TRADING-DAY gaps that the JIP source is
         missing (e.g. brand-new dates that fie_v3 hasn't ingested yet).
         Any rows pulled from yfinance are written BACK to fie_v3 so the
         next read hits the canonical cache and we don't keep calling the
         external API.

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

    # 1. Pull what fie_v3 has.
    jip_df = pd.DataFrame(columns=["close"])
    try:
        jip_df = _fetch_jip_index_history(_JIP_NIFTY_INDEX, fetch_start, fetch_end)
        if not jip_df.empty:
            logger.info(
                "JIP data core: fetched %d Nifty rows for %s to %s",
                len(jip_df), fetch_start, fetch_end,
            )
    except Exception as exc:
        logger.warning("JIP data core query failed (%s); will rely on yfinance", exc)

    # 2. Decide whether yfinance has to fill any trading-day gaps. We only
    #    consider holes IN THE REQUESTED RANGE [start_date, end_date] — the
    #    buffer days aren't critical to align navdates.
    missing = _missing_dates(jip_df, start_date, end_date)
    yf_df = pd.DataFrame(columns=["close"])
    if missing:
        logger.info(
            "JIP missing %d trading day(s) in [%s, %s]; calling yfinance to fill",
            len(missing), start_date, end_date,
        )
        try:
            # yfinance's `end` is exclusive — add a day to ensure we get end_date.
            hist = _fetch_yfinance_history(fetch_start, fetch_end + timedelta(days=1))
            yf_df = hist[["Close"]].copy()
            yf_df.columns = ["close"]
            yf_df.index.name = "date"
            yf_df = yf_df.sort_index()
            # Strip tz for consistency with JIP
            if yf_df.index.tz is not None:
                yf_df.index = yf_df.index.tz_convert(None)
        except Exception as exc:
            logger.warning(
                "yfinance fallback failed for Nifty %s to %s: %s",
                fetch_start, fetch_end, exc,
            )

    # 3. Combine: JIP wins on overlap, yfinance fills the rest.
    if jip_df.empty and yf_df.empty:
        logger.warning(
            "Both JIP and yfinance returned no Nifty data for %s to %s",
            fetch_start, fetch_end,
        )
        return pd.DataFrame(columns=["close"])

    if jip_df.empty:
        combined = yf_df
    elif yf_df.empty:
        combined = jip_df
    else:
        # Drop yfinance dates already covered by fie_v3 so JIP stays authoritative.
        jip_dates = set(jip_df.index)
        yf_only = yf_df.loc[~yf_df.index.isin(jip_dates)]
        combined = pd.concat([jip_df, yf_only]).sort_index()

    # 4. Write back to fie_v3 the dates that ONLY yfinance has, so the next
    #    read finds them in the canonical source.
    if not yf_df.empty:
        if jip_df.empty:
            writeback_df = yf_df
        else:
            writeback_df = yf_df.loc[~yf_df.index.isin(jip_df.index)]
        if not writeback_df.empty:
            _write_jip_index_history(_JIP_NIFTY_INDEX, writeback_df)

    BenchmarkCache.put(_NIFTY_TICKER, combined)
    mask = (combined.index.date >= start_date) & (combined.index.date <= end_date)
    result = combined.loc[mask].copy()
    logger.info(
        "Nifty fetch: %d rows from JIP + %d gap-fill from yfinance (range %s..%s)",
        len(jip_df), len(yf_df), start_date, end_date,
    )
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
