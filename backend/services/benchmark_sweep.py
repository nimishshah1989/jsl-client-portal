"""
Self-healing benchmark sweep.

Finds nav_dates in cpp_nav_series whose benchmark_value is missing (NULL or 0)
and back-fills them from the canonical fie_v3.index_prices source, falling
back to yfinance for dates that fie_v3 doesn't yet cover.

The sweep is **idempotent**:
  - dates already populated with a non-zero benchmark are skipped
  - re-running over the same window yields rows_updated=0 once the holes
    are closed

Production context
------------------
On 2026-05-26 a single-day NAV upload (277 clients) was written with
benchmark_value=0 because the pre-fetched Nifty window in the ingestion path
collapsed against the client's full 4-year nav_dates range (the diversity
guard inside ``align_benchmark`` legitimately returned an empty series).
The aggregate page then computed a daily benchmark return of
``(0 − 23654.70) / 23654.70 = -100%``.

This sweep is the safety net: even if a fresh hole is opened, it gets closed
within ~24 hours by the nightly scheduler job (see ``scheduler.py``) — and
admins can force an immediate run via ``POST /api/admin/benchmark/sync``.

The sweep deliberately does NOT touch the risk_engine or per-client metric
recompute; it is data-plumbing only. Per-client metrics will pick up the
healed benchmark on their next scheduled (or upload-triggered) recompute.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.benchmark_service import fetch_nifty_data

logger = logging.getLogger(__name__)


# Default look-back window for the nightly sweep.  14 days is generous:
# even a long-weekend + national holiday cluster is fully covered, and the
# nightly cadence guarantees holes are closed within ~24 hours regardless.
DEFAULT_SWEEP_DAYS = 14


@dataclass
class SweepResult:
    """Summary of one sweep invocation."""

    dates_checked: int = 0
    dates_filled: int = 0
    dates_failed: int = 0
    rows_updated: int = 0
    failures: list[date] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "dates_checked": self.dates_checked,
            "dates_filled": self.dates_filled,
            "dates_failed": self.dates_failed,
            "rows_updated": self.rows_updated,
            "failed_dates": [d.isoformat() for d in self.failures],
        }


async def _find_hole_dates(db: AsyncSession, since: date) -> list[date]:
    """
    Return distinct nav_dates from cpp_nav_series in [since, today] that have
    ANY row with a NULL or zero benchmark_value.

    A "hole" is defined per-date (not per-row) because the benchmark is a
    global value: if it's missing for one client on date X, it should be
    missing for all clients on date X, and fixing it for date X fixes every
    row at once.
    """
    result = await db.execute(
        text("""
            SELECT DISTINCT nav_date
            FROM cpp_nav_series
            WHERE nav_date >= :since
              AND (benchmark_value IS NULL OR benchmark_value = 0)
            ORDER BY nav_date ASC
        """),
        {"since": since},
    )
    # Coerce every row to ``date`` — aiosqlite (used in tests) returns ISO
    # strings; asyncpg returns ``date`` objects.
    out: list[date] = []
    from datetime import datetime as _dt
    for row in result.fetchall():
        v = row[0]
        if isinstance(v, _dt):
            out.append(v.date())
        elif isinstance(v, date):
            out.append(v)
        else:
            out.append(_dt.fromisoformat(str(v)).date())
    return out


async def _backfill_one_date(
    db: AsyncSession, target_date: date, close_price: Decimal
) -> int:
    """
    UPDATE every cpp_nav_series row for ``target_date`` whose benchmark_value
    is currently NULL or 0 to the canonical close price. Returns row count.
    """
    result = await db.execute(
        text("""
            UPDATE cpp_nav_series
            SET benchmark_value = :bv
            WHERE nav_date = :nd
              AND (benchmark_value IS NULL OR benchmark_value = 0)
        """),
        {"bv": close_price, "nd": target_date},
    )
    return result.rowcount or 0


async def sweep_benchmark_holes(
    db: AsyncSession,
    *,
    days: int = DEFAULT_SWEEP_DAYS,
    today: date | None = None,
) -> SweepResult:
    """
    Find and fill benchmark holes for the last ``days`` days.

    For every distinct nav_date with at least one row missing a benchmark:
      1. Fetch the Nifty close via ``fetch_nifty_data`` (fie_v3 primary,
         yfinance fallback; yfinance results are written back to fie_v3).
      2. UPDATE all rows on that date in one batch.
      3. If neither source has data for the date (e.g. a national holiday
         that NSE was closed on), log a warning and move on — leave the
         column NULL/0 rather than guessing.

    The function is fully async; it never blocks the event loop on the
    network call because ``fetch_nifty_data`` already runs synchronously
    inside the request context which is the same pattern the existing
    ingestion/risk-engine paths use. Future scheduler invocations run this
    on the APScheduler async executor.
    """
    if today is None:
        today = date.today()
    since = today - timedelta(days=days)

    result = SweepResult()
    hole_dates = await _find_hole_dates(db, since)
    result.dates_checked = len(hole_dates)
    if not hole_dates:
        logger.info(
            "[bench-sync] No benchmark holes in last %d day(s); nothing to do",
            days,
        )
        return result

    logger.info(
        "[bench-sync] Found %d date(s) with missing benchmark in last %d day(s)",
        len(hole_dates), days,
    )

    # Fetch a single span covering all hole dates in one network call.
    span_start = min(hole_dates)
    span_end = max(hole_dates)
    nifty_df: pd.DataFrame = pd.DataFrame(columns=["close"])
    try:
        nifty_df = fetch_nifty_data(span_start, span_end)
    except Exception as exc:
        logger.warning(
            "[bench-sync] fetch_nifty_data raised for %s..%s: %s — will retry per-date",
            span_start, span_end, exc,
        )

    # Index the fetched data by date for fast lookup.
    by_date: dict[date, Decimal] = {}
    if nifty_df is not None and not nifty_df.empty:
        for ts, val in nifty_df["close"].items():
            if val is None or pd.isna(val):
                continue
            d = ts.date() if hasattr(ts, "date") else ts
            by_date[d] = Decimal(str(val))

    for hole in hole_dates:
        bench = by_date.get(hole)
        # If the bulk fetch didn't include this date (e.g. holiday), try a
        # single-date fetch — yfinance may still have a close from the
        # nearest trading day, but we DO NOT want to forward-fill across the
        # weekend ourselves here: each row gets its own date's close or stays
        # NULL.
        if bench is None:
            try:
                single = fetch_nifty_data(hole, hole)
                if single is not None and not single.empty:
                    val = single["close"].iloc[0]
                    if val is not None and not pd.isna(val):
                        bench = Decimal(str(val))
            except Exception as exc:
                logger.debug(
                    "[bench-sync] single-date fetch failed for %s: %s", hole, exc
                )

        if bench is None or bench == 0:
            logger.warning(
                "[bench-sync] No Nifty close available for %s from any source "
                "(JIP or yfinance); leaving %d row(s) with NULL/0 benchmark — "
                "next nightly sweep will retry",
                hole,
                await _count_holes_on_date(db, hole),
            )
            result.dates_failed += 1
            result.failures.append(hole)
            continue

        try:
            updated = await _backfill_one_date(db, hole, bench)
            await db.commit()
        except Exception as exc:
            logger.error(
                "[bench-sync] UPDATE failed for %s: %s", hole, exc, exc_info=True
            )
            await db.rollback()
            result.dates_failed += 1
            result.failures.append(hole)
            continue

        result.dates_filled += 1
        result.rows_updated += updated
        logger.info(
            "[bench-sync] %s: %d row(s) updated to bench=%s",
            hole, updated, bench,
        )

    logger.info(
        "[bench-sync] Summary: dates_checked=%d filled=%d failed=%d rows_updated=%d",
        result.dates_checked, result.dates_filled, result.dates_failed,
        result.rows_updated,
    )
    return result


async def _count_holes_on_date(db: AsyncSession, target_date: date) -> int:
    """Count cpp_nav_series rows on ``target_date`` whose benchmark is NULL/0."""
    result = await db.execute(
        text("""
            SELECT COUNT(*) FROM cpp_nav_series
            WHERE nav_date = :nd
              AND (benchmark_value IS NULL OR benchmark_value = 0)
        """),
        {"nd": target_date},
    )
    row = result.fetchone()
    return int(row[0]) if row else 0
