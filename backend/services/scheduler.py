"""
Background scheduler for periodic tasks.

Runs inside the FastAPI process via APScheduler.
- Live price refresh: every hour during NSE market hours (Mon-Fri, 9:15-16:00 IST)
- Post-market price update: once at 16:15 IST (final closing prices)
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

    scheduler.start()
    logger.info("Background scheduler started with %d jobs", len(scheduler.get_jobs()))


def stop_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Background scheduler stopped")
