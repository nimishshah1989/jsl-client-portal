"""
Persist and retrieve reconciliation results in the database.

Stores the full reconciliation summary as JSONB in cpp_reconciliation_runs.
Creates the table on first use if it doesn't exist.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class _DecimalEncoder(json.JSONEncoder):
    """JSON encoder that converts Decimal to string."""

    def default(self, o: object) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        return super().default(o)


async def ensure_table(db: AsyncSession) -> None:
    """Create cpp_reconciliation_runs table if it doesn't exist."""
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS cpp_reconciliation_runs (
            id SERIAL PRIMARY KEY,
            run_at TIMESTAMP NOT NULL DEFAULT NOW(),
            market_date DATE,
            filename TEXT,
            summary_json JSONB NOT NULL,
            commentary_json JSONB,
            stats JSONB
        )
    """))
    await db.commit()


async def save_reconciliation(
    db: AsyncSession,
    result,
    market_date,
    filename: str,
) -> int:
    """Save reconciliation result to DB. Returns the run ID."""
    await ensure_table(db)

    # Build a serialisable summary (without full match details to keep size manageable)
    stats = {
        "total_clients_bo": result.total_clients_bo,
        "total_clients_matched": result.total_clients_matched,
        "total_clients_missing": result.total_clients_missing,
        "total_holdings_bo": result.total_holdings_bo,
        "total_holdings_matched": result.total_holdings_matched,
        "total_qty_mismatches": result.total_qty_mismatches,
        "total_cost_mismatches": result.total_cost_mismatches,
        "total_value_mismatches": result.total_value_mismatches,
        "total_missing_in_ours": result.total_missing_in_ours,
        "total_extra_in_ours": result.total_extra_in_ours,
        "match_pct": result.match_pct,
        "client_match_pct": result.client_match_pct,
        "clients_fully_matched": result.clients_fully_matched,
    }

    # Build per-client summary (without individual match rows)
    client_summaries = []
    for c in result.clients:
        client_summaries.append({
            "client_code": c.client_code,
            "client_name": c.client_name,
            "family_group": c.family_group,
            "client_found": c.client_found,
            "total_holdings_bo": c.total_holdings_bo,
            "total_holdings_ours": c.total_holdings_ours,
            "matched_count": c.matched_count,
            "qty_mismatch_count": c.qty_mismatch_count,
            "cost_mismatch_count": c.cost_mismatch_count,
            "value_mismatch_count": c.value_mismatch_count,
            "missing_in_ours_count": c.missing_in_ours_count,
            "extra_in_ours_count": c.extra_in_ours_count,
            "match_pct": c.match_pct,
            "has_issues": c.has_issues,
            "matches": [
                {
                    "symbol": m.symbol,
                    "status": m.status,
                    "bo_quantity": str(m.bo_quantity) if m.bo_quantity is not None else None,
                    "bo_avg_cost": str(m.bo_avg_cost) if m.bo_avg_cost is not None else None,
                    "bo_market_value": str(m.bo_market_value) if m.bo_market_value is not None else None,
                    "our_quantity": str(m.our_quantity) if m.our_quantity is not None else None,
                    "our_avg_cost": str(m.our_avg_cost) if m.our_avg_cost is not None else None,
                    "our_market_value": str(m.our_market_value) if m.our_market_value is not None else None,
                    "qty_diff": str(m.qty_diff) if m.qty_diff is not None else None,
                    "cost_diff": str(m.cost_diff) if m.cost_diff is not None else None,
                    "bo_isin": m.bo_isin,
                }
                for m in c.matches
            ],
        })

    summary_json = json.dumps({"clients": client_summaries}, cls=_DecimalEncoder)
    commentary_json = json.dumps(result.commentary, cls=_DecimalEncoder)
    stats_json = json.dumps(stats, cls=_DecimalEncoder)

    r = await db.execute(
        text("""
            INSERT INTO cpp_reconciliation_runs (run_at, market_date, filename, summary_json, commentary_json, stats)
            VALUES (:run_at, :md, :fn, CAST(:sj AS jsonb), CAST(:cj AS jsonb), CAST(:st AS jsonb))
            RETURNING id
        """),
        {
            "run_at": datetime.now(timezone.utc).replace(tzinfo=None),
            "md": market_date,
            "fn": filename,
            "sj": summary_json,
            "cj": commentary_json,
            "st": stats_json,
        },
    )
    run_id = r.scalar()
    await db.commit()
    logger.info("Saved reconciliation run #%d", run_id)
    return run_id


async def load_latest_reconciliation(db: AsyncSession) -> dict | None:
    """Load the most recent reconciliation run from DB.

    Returns dict with keys: run_at, market_date, filename, stats, commentary, clients
    or None if no runs exist.
    """
    await ensure_table(db)

    r = await db.execute(text("""
        SELECT id, run_at, market_date, filename, summary_json, commentary_json, stats
        FROM cpp_reconciliation_runs
        ORDER BY run_at DESC
        LIMIT 1
    """))
    row = r.fetchone()
    if row is None:
        return None

    return {
        "run_id": row[0],
        "run_at": row[1].isoformat() if row[1] else None,
        "market_date": row[2],
        "filename": row[3],
        "summary": row[4],  # already parsed as dict by asyncpg
        "commentary": row[5] or [],
        "stats": row[6] or {},
    }
