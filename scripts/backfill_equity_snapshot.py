"""One-off: rehydrate a missing EQUITY BO snapshot from a stored reconciliation run.

The cpp_bo_holdings_snapshot table was introduced after some reconciliation runs
were already persisted. This script rebuilds the EQUITY snapshot from the per-
match BO fields of a prior run so that /rerun and /upload (which union EQUITY +
ETF snapshots) work correctly.

Usage:
  export DATABASE_URL='postgresql+asyncpg://USER:PASS@HOST:PORT/DB'
  python3.11 scripts/backfill_equity_snapshot.py [RUN_ID]

If RUN_ID is omitted, uses the most recent run that has matches with bo_quantity
set (i.e. the last "real" equity-file-driven reconciliation).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.services.reconciliation_store import save_bo_holdings_snapshot

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("backfill")


async def _fetch_run(db, run_id: int | None) -> dict:
    if run_id is not None:
        q = text("""
            SELECT id, market_date, filename, summary_json
            FROM cpp_reconciliation_runs WHERE id = :id
        """)
        r = await db.execute(q, {"id": run_id})
    else:
        q = text("""
            SELECT id, market_date, filename, summary_json
            FROM cpp_reconciliation_runs
            ORDER BY run_at DESC
        """)
        r = await db.execute(q)

    rows = r.fetchall()
    if not rows:
        raise RuntimeError("No reconciliation runs found")

    for row in rows:
        raw_summary = row[3]
        summary = json.loads(raw_summary) if isinstance(raw_summary, str) else raw_summary
        clients = summary.get("clients", [])
        has_bo = any(
            m.get("bo_quantity") is not None
            for c in clients
            for m in c.get("matches", [])
        )
        if has_bo:
            return {
                "id": row[0], "market_date": row[1],
                "filename": row[2], "summary": summary,
            }
    raise RuntimeError("No run found with bo_quantity data")


def _row_from_match(ucc: str, family_group: str, m: dict) -> dict:
    return {
        "ucc": ucc,
        "symbol": m["symbol"],
        "isin": m.get("bo_isin") or "",
        "quantity": m["bo_quantity"],
        "avg_cost": m.get("bo_avg_cost"),
        "total_cost": m.get("bo_total_cost"),
        "market_price": m.get("bo_market_price"),
        "market_value": m.get("bo_market_value"),
        "notional_pnl": m.get("bo_pnl"),
        "holding_market_pct": m.get("bo_weight_pct"),
        "family_group": family_group,
        "holding_cost_pct": None,
        "roi_pct": None,
        "market_date": None,
    }


async def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL is required")
        return 2

    run_id = int(sys.argv[1]) if len(sys.argv) > 1 else None

    engine = create_async_engine(url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        run = await _fetch_run(db, run_id)
        log.info(
            "Using run #%d (market_date=%s, file=%s)",
            run["id"], run["market_date"], run["filename"],
        )

        records: list[dict] = []
        for c in run["summary"].get("clients", []):
            ucc = c["client_code"]
            fam = c.get("family_group", "")
            for m in c.get("matches", []):
                if m.get("bo_quantity") is None:
                    continue
                records.append(_row_from_match(ucc, fam, m))

        if not records:
            log.error("No BO rows to snapshot")
            return 3

        snap_id = await save_bo_holdings_snapshot(
            db, "EQUITY", run["market_date"],
            f"backfill-from-run-{run['id']}-{run['filename']}", records,
        )
        log.info("Saved EQUITY snapshot #%d with %d records", snap_id, len(records))

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
