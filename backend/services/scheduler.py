"""
Background scheduler for periodic tasks.

Runs inside the FastAPI process via APScheduler.
- Live price refresh: every hour during NSE market hours (Mon-Fri, 9:15-16:00 IST)
- Post-market price update: once at 16:15 IST (final closing prices)
- Nightly benchmark sync: every day at 19:30 IST — back-fills any cpp_nav_series
  rows whose benchmark_value is missing (NULL/0). This is the safety net for
  the production incident 2026-05-26 where a single-day NAV upload left 277
  rows at benchmark=0 because the pre-fetched Nifty window collapsed against
  the client's full 4y nav_dates range.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


async def _refresh_prices() -> None:
    """Fetch live NSE prices and update holdings for all clients."""
    from backend.database import AsyncSessionLocal
    from backend.services.live_prices import update_holdings_prices

    logger.info("Scheduled price refresh starting at %s", datetime.now().isoformat())
    try:
        async with AsyncSessionLocal() as db:
            result = await update_holdings_prices(db)
            logger.info(
                "Scheduled price refresh done: %d symbols, %d updated, %d not found",
                result.get("symbols", 0),
                result.get("prices_updated", 0),
                result.get("prices_not_found", 0),
            )
    except Exception as exc:
        logger.error("Scheduled price refresh failed: %s", exc, exc_info=True)


async def _nightly_benchmark_sync() -> None:
    """
    Find any cpp_nav_series nav_date in the last 14 days with a NULL or 0
    benchmark_value and back-fill it from fie_v3.index_prices (primary) /
    yfinance (fallback, with write-back to fie_v3).

    This is the self-healing guarantee: even if a NAV file is uploaded 10 days
    late, the missing benchmark gets filled within ~24 hours automatically.

    Runs in the APScheduler async executor, so it shares the FastAPI event
    loop but does NOT block it on the synchronous network calls — those
    happen inside the same await chain ingestion already uses, and the
    sweep is bounded to ~14 dates per run.
    """
    from backend.database import AsyncSessionLocal
    from backend.services.benchmark_sweep import (
        DEFAULT_SWEEP_DAYS,
        sweep_benchmark_holes,
    )

    logger.info(
        "[bench-sync] nightly run starting at %s (window=%d days)",
        datetime.now().isoformat(), DEFAULT_SWEEP_DAYS,
    )
    try:
        async with AsyncSessionLocal() as db:
            result = await sweep_benchmark_holes(db, days=DEFAULT_SWEEP_DAYS)
        logger.info(
            "[bench-sync] nightly run done: dates_checked=%d filled=%d "
            "failed=%d rows_updated=%d",
            result.dates_checked, result.dates_filled,
            result.dates_failed, result.rows_updated,
        )
    except Exception as exc:
        logger.error(
            "[bench-sync] nightly run failed: %s", exc, exc_info=True
        )


def start_scheduler() -> None:
    """Register all scheduled jobs and start the scheduler."""
    # Hourly during market hours: Mon-Fri, every hour from 10:00 to 15:00 IST
    # (first run at 10 gives market 45 min to settle after 9:15 open)
    scheduler.add_job(
        _refresh_prices,
        CronTrigger(
            day_of_week="mon-fri",
            hour="10-15",
            minute=0,
            timezone="Asia/Kolkata",
        ),
        id="market_hours_price_refresh",
        name="Hourly price refresh during market hours",
        replace_existing=True,
    )

    # Post-market closing price update at 16:15 IST (market closes at 15:30)
    scheduler.add_job(
        _refresh_prices,
        CronTrigger(
            day_of_week="mon-fri",
            hour=16,
            minute=15,
            timezone="Asia/Kolkata",
        ),
        id="closing_price_refresh",
        name="Post-market closing price update",
        replace_existing=True,
    )

    # Nightly benchmark sync at 19:30 IST — 1.5h after market close so the
    # JIP data core has had time to ingest the day's closing prices; also
    # runs on weekends so a Friday-evening NAV upload still gets healed by
    # Saturday night.
    scheduler.add_job(
        _nightly_benchmark_sync,
        CronTrigger(
            hour=19,
            minute=30,
            timezone="Asia/Kolkata",
        ),
        id="nightly_benchmark_sync",
        name="Nightly benchmark sync",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Background scheduler started with %d jobs", len(scheduler.get_jobs()))


def stop_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Background scheduler stopped")
