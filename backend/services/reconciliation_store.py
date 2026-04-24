"""
Persist and retrieve reconciliation results in the database.

Stores the full reconciliation summary as JSONB in cpp_reconciliation_runs.
Creates the table on first use if it doesn't exist.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class _DecimalEncoder(json.JSONEncoder):
    """JSON encoder that converts Decimal to string and date to ISO string."""

    def default(self, o: object) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, (date, datetime)):
            return o.isoformat()
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
        "total_structural_etf": result.total_structural_etf,
        "match_pct": result.match_pct,
        "client_match_pct": result.client_match_pct,
        "clients_fully_matched": result.clients_fully_matched,
        # 4-component aggregate totals
        "total_nav_value": str(result.total_nav_value),
        "total_nav_equity_value": str(result.total_nav_equity_value),
        "total_etf_value": str(result.total_etf_value),
        "total_cash_value": str(result.total_cash_value),
        "total_bo_holdings_value": str(result.total_bo_holdings_value),
        "total_our_holdings_value": str(result.total_our_holdings_value),
        "total_our_etf_holdings_value": str(result.total_our_etf_holdings_value),
        "total_bo_etf_holdings_value": str(result.total_bo_etf_holdings_value),
        "total_nav_equity_vs_bo_diff": str(result.total_nav_equity_vs_bo_diff),
        "total_nav_vs_bo_diff": str(result.total_nav_vs_bo_diff),
        "total_bo_vs_ours_diff": str(result.total_bo_vs_ours_diff),
        "total_etf_vs_ours_diff": str(result.total_etf_vs_ours_diff),
        "clients_with_nav": result.clients_with_nav,
    }

    # Build per-client summary (without individual match rows)
    def _s(v):
        return str(v) if v is not None else None

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
            "structural_etf_count": c.structural_etf_count,
            "match_pct": c.match_pct,
            "has_issues": c.has_issues,
            # 4-component value totals
            "nav_total": _s(c.nav_total),
            "nav_equity_component": _s(c.nav_equity_component),
            "etf_component_nav": _s(c.etf_component_nav),
            "cash_component_nav": _s(c.cash_component_nav),
            "bo_holdings_total": _s(c.bo_holdings_total),
            "our_holdings_total": _s(c.our_holdings_total),
            "our_etf_holdings_total": _s(c.our_etf_holdings_total),
            "bo_etf_holdings_total": _s(c.bo_etf_holdings_total),
            "nav_equity_vs_bo_diff": _s(c.nav_equity_vs_bo_diff),
            "nav_vs_bo_diff": _s(c.nav_vs_bo_diff),
            "bo_vs_ours_diff": _s(c.bo_vs_ours_diff),
            "etf_vs_ours_diff": _s(c.etf_vs_ours_diff),
            "nav_date": str(c.nav_date) if c.nav_date else None,
            "matches": [
                {
                    "symbol": m.symbol, "status": m.status,
                    "matched_by": m.matched_by,
                    "family_group": m.family_group,
                    "bo_quantity": _s(m.bo_quantity), "bo_avg_cost": _s(m.bo_avg_cost),
                    "bo_total_cost": _s(m.bo_total_cost),
                    "bo_market_price": _s(m.bo_market_price),
                    "bo_market_value": _s(m.bo_market_value),
                    "bo_pnl": _s(m.bo_pnl), "bo_weight_pct": _s(m.bo_weight_pct),
                    "bo_isin": m.bo_isin,
                    "our_quantity": _s(m.our_quantity), "our_avg_cost": _s(m.our_avg_cost),
                    "our_total_cost": _s(m.our_total_cost),
                    "our_market_price": _s(m.our_market_price),
                    "our_market_value": _s(m.our_market_value),
                    "our_pnl": _s(m.our_pnl), "our_weight_pct": _s(m.our_weight_pct),
                    "our_asset_class": m.our_asset_class,
                    "qty_diff": _s(m.qty_diff), "cost_diff": _s(m.cost_diff),
                    "value_diff": _s(m.value_diff), "pnl_diff": _s(m.pnl_diff),
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


async def ensure_snapshot_table(db: AsyncSession) -> None:
    """Create cpp_bo_holdings_snapshot table if it doesn't exist."""
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS cpp_bo_holdings_snapshot (
            id              SERIAL PRIMARY KEY,
            snapshot_type   VARCHAR(20) NOT NULL,
            market_date     DATE,
            filename        TEXT,
            uploaded_at     TIMESTAMP NOT NULL DEFAULT NOW(),
            records         JSONB NOT NULL
        )
    """))
    await db.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_cpp_bo_snapshot_type_uploaded "
        "ON cpp_bo_holdings_snapshot(snapshot_type, uploaded_at DESC)"
    ))
    await db.commit()


async def save_bo_holdings_snapshot(
    db: AsyncSession,
    snapshot_type: str,
    market_date,
    filename: str,
    records: list[dict],
) -> int:
    """Persist a parsed BO holdings list (equity or ETF) for later reconciliation.

    snapshot_type: "EQUITY" or "ETF".
    The latest snapshot per type is used when reconciling — the reconciliation
    run unions the latest EQUITY + ETF snapshots before matching.
    """
    await ensure_snapshot_table(db)
    records_json = json.dumps(records, cls=_DecimalEncoder)
    r = await db.execute(
        text("""
            INSERT INTO cpp_bo_holdings_snapshot
                (snapshot_type, market_date, filename, uploaded_at, records)
            VALUES (:st, :md, :fn, :ua, CAST(:rj AS jsonb))
            RETURNING id
        """),
        {
            "st": snapshot_type,
            "md": market_date,
            "fn": filename,
            "ua": datetime.now(timezone.utc).replace(tzinfo=None),
            "rj": records_json,
        },
    )
    snapshot_id = r.scalar()
    await db.commit()
    logger.info(
        "Saved %s BO holdings snapshot #%d (%d records, market_date=%s)",
        snapshot_type, snapshot_id, len(records), market_date,
    )
    return snapshot_id


def _rehydrate_snapshot_records(records: list[dict]) -> list[dict]:
    """Convert stringified Decimals and ISO dates back to native types.

    Mirror of the shape produced by holding_report_parser.parse_holding_report —
    numeric columns become Decimal, market_date becomes date.
    """
    decimal_keys = (
        "quantity", "avg_cost", "total_cost", "holding_cost_pct",
        "market_price", "market_value", "notional_pnl",
        "roi_pct", "holding_market_pct",
    )
    out: list[dict] = []
    for rec in records:
        r = dict(rec)
        for k in decimal_keys:
            v = r.get(k)
            if v is None or isinstance(v, Decimal):
                continue
            try:
                r[k] = Decimal(str(v))
            except Exception:
                r[k] = None
        md = r.get("market_date")
        if isinstance(md, str) and md:
            try:
                r["market_date"] = date.fromisoformat(md[:10])
            except ValueError:
                r["market_date"] = None
        out.append(r)
    return out


async def load_latest_bo_holdings(
    db: AsyncSession,
    snapshot_type: str,
) -> list[dict]:
    """Load the most recent BO holdings snapshot of the given type.

    Returns a list of holding-record dicts (same shape as parse_holding_report),
    or an empty list if no snapshot of that type has been uploaded.

    Each returned record is tagged with source_bucket = snapshot_type so
    downstream reconcile() can route ETF-bucket rows against etf_component_nav
    and equity-bucket rows against nav_equity_component.
    """
    await ensure_snapshot_table(db)
    r = await db.execute(
        text("""
            SELECT records
            FROM cpp_bo_holdings_snapshot
            WHERE snapshot_type = :st
            ORDER BY uploaded_at DESC
            LIMIT 1
        """),
        {"st": snapshot_type},
    )
    row = r.fetchone()
    if row is None or row[0] is None:
        return []
    raw = row[0]  # asyncpg returns JSONB as list/dict already
    if isinstance(raw, str):
        raw = json.loads(raw)
    records = _rehydrate_snapshot_records(raw)
    for rec in records:
        rec["source_bucket"] = snapshot_type
    return records


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
