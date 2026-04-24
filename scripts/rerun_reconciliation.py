"""One-off reconciliation rerun with source_bucket-aware snapshot union.

Loads the latest EQUITY + ETF snapshots from cpp_bo_holdings_snapshot (both
tagged with source_bucket by the loader), runs reconcile(), and persists the
result. Use after backend changes to the reconciliation engine.

Credentials come from DATABASE_URL (async) — never hardcode.
  export DATABASE_URL='postgresql+asyncpg://USER:PASS@HOST:PORT/DB'
  python3.11 scripts/rerun_reconciliation.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure project root on path so `backend.*` imports resolve
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.services.reconciliation_service import reconcile
from backend.services.reconciliation_store import (
    load_latest_bo_holdings,
    load_latest_reconciliation,
    save_reconciliation,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("rerun")


async def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL environment variable is required")
        return 2

    engine = create_async_engine(url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        equity = await load_latest_bo_holdings(db, "EQUITY")
        etf = await load_latest_bo_holdings(db, "ETF")
        log.info("Loaded snapshots: %d equity + %d ETF records", len(equity), len(etf))

        if not equity and not etf:
            log.error("No BO snapshots found — cannot rerun")
            return 3

        combined = list(equity) + list(etf)
        result = await reconcile(combined, db)

        stored = await load_latest_reconciliation(db)
        market_date = stored.get("market_date") if stored else None
        filename = f"rerun-{stored.get('filename', 'snapshot') if stored else 'snapshot'}"

        run_id = await save_reconciliation(db, result, market_date, filename)
        log.info(
            "Rerun complete: run #%d | clients=%d matched=%d | "
            "extras=%d structural=%d missing=%d | "
            "nav_equity_vs_bo=%s bo_vs_ours=%s etf_vs_ours=%s",
            run_id,
            result.total_clients_bo, result.total_clients_matched,
            result.total_extra_in_ours, result.total_structural_etf,
            result.total_missing_in_ours,
            result.total_nav_equity_vs_bo_diff,
            result.total_bo_vs_ours_diff,
            result.total_etf_vs_ours_diff,
        )

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
