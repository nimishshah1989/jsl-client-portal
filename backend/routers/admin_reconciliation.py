"""Admin reconciliation router — upload holding report and compare against our data.

Results are persisted in cpp_reconciliation_runs so they survive restarts
and are visible to any admin who logs in.
"""

import csv
import io
import logging
import tempfile
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import get_admin_user
from backend.schemas.reconciliation import (
    ClientReconciliationResponse,
    HoldingMatchResponse,
    ReconciliationSummaryResponse,
)
from backend.services.holding_report_parser import (
    holding_report_summary,
    parse_holding_report,
)
from backend.services.reconciliation_service import reconcile
from backend.services.reconciliation_store import (
    load_latest_reconciliation,
    save_reconciliation,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/reconciliation", tags=["admin-reconciliation"])

_cache: dict = {}


def _match_to_response(m) -> HoldingMatchResponse:
    """Convert a HoldingMatch dataclass to response schema."""
    return HoldingMatchResponse(
        client_code=m.client_code, symbol=m.symbol, status=m.status,
        family_group=m.family_group,
        bo_quantity=m.bo_quantity, bo_avg_cost=m.bo_avg_cost,
        bo_total_cost=m.bo_total_cost, bo_market_price=m.bo_market_price,
        bo_market_value=m.bo_market_value, bo_pnl=m.bo_pnl,
        bo_weight_pct=m.bo_weight_pct, bo_isin=m.bo_isin,
        our_quantity=m.our_quantity, our_avg_cost=m.our_avg_cost,
        our_total_cost=m.our_total_cost, our_market_price=m.our_market_price,
        our_market_value=m.our_market_value, our_pnl=m.our_pnl,
        our_weight_pct=m.our_weight_pct,
        qty_diff=m.qty_diff, cost_diff=m.cost_diff,
        value_diff=m.value_diff, pnl_diff=m.pnl_diff,
    )


def _client_to_response(c) -> ClientReconciliationResponse:
    """Convert a ClientReconciliation dataclass to response schema."""
    return ClientReconciliationResponse(
        client_code=c.client_code, client_name=c.client_name,
        family_group=c.family_group, client_found=c.client_found,
        total_holdings_bo=c.total_holdings_bo,
        total_holdings_ours=c.total_holdings_ours,
        matched_count=c.matched_count,
        qty_mismatch_count=c.qty_mismatch_count,
        cost_mismatch_count=c.cost_mismatch_count,
        value_mismatch_count=c.value_mismatch_count,
        missing_in_ours_count=c.missing_in_ours_count,
        extra_in_ours_count=c.extra_in_ours_count,
        match_pct=c.match_pct, has_issues=c.has_issues,
        matches=[_match_to_response(m) for m in c.matches],
        # 4-component NAV breakdown
        nav_total=c.nav_total,
        nav_equity_component=c.nav_equity_component,
        etf_component_nav=c.etf_component_nav,
        cash_component_nav=c.cash_component_nav,
        nav_date=c.nav_date,
        # Equity 3-way
        bo_holdings_total=c.bo_holdings_total,
        our_holdings_total=c.our_holdings_total,
        nav_equity_vs_bo_diff=c.nav_equity_vs_bo_diff,
        bo_vs_ours_diff=c.bo_vs_ours_diff,
        nav_vs_bo_diff=c.nav_vs_bo_diff,
        # ETF reconciliation
        our_etf_holdings_total=c.our_etf_holdings_total,
        etf_vs_ours_diff=c.etf_vs_ours_diff,
    )


def _summary_to_response(result, market_date=None) -> ReconciliationSummaryResponse:
    """Convert a ReconciliationSummary to response schema."""
    return ReconciliationSummaryResponse(
        total_clients_bo=result.total_clients_bo,
        total_clients_matched=result.total_clients_matched,
        total_clients_missing=result.total_clients_missing,
        total_holdings_bo=result.total_holdings_bo,
        total_holdings_matched=result.total_holdings_matched,
        total_qty_mismatches=result.total_qty_mismatches,
        total_cost_mismatches=result.total_cost_mismatches,
        total_value_mismatches=result.total_value_mismatches,
        total_missing_in_ours=result.total_missing_in_ours,
        total_extra_in_ours=result.total_extra_in_ours,
        match_pct=result.match_pct,
        client_match_pct=result.client_match_pct,
        clients_fully_matched=result.clients_fully_matched,
        # 4-component NAV aggregate breakdown
        total_nav_value=result.total_nav_value,
        total_nav_equity_value=result.total_nav_equity_value,
        total_etf_value=result.total_etf_value,
        total_cash_value=result.total_cash_value,
        total_bo_holdings_value=result.total_bo_holdings_value,
        total_our_holdings_value=result.total_our_holdings_value,
        total_our_etf_holdings_value=result.total_our_etf_holdings_value,
        total_nav_equity_vs_bo_diff=result.total_nav_equity_vs_bo_diff,
        total_nav_vs_bo_diff=result.total_nav_vs_bo_diff,
        total_bo_vs_ours_diff=result.total_bo_vs_ours_diff,
        total_etf_vs_ours_diff=result.total_etf_vs_ours_diff,
        clients_with_nav=result.clients_with_nav,
        market_date=market_date,
        commentary=result.commentary,
        clients=[_client_to_response(c) for c in result.clients],
    )


def _db_row_to_client_response(c: dict) -> ClientReconciliationResponse:
    """Convert a DB-stored client dict to response schema."""
    matches = []
    for m in c.get("matches", []):
        def _dec(key):
            v = m.get(key)
            return Decimal(str(v)) if v is not None else None

        matches.append(HoldingMatchResponse(
            client_code=c["client_code"], symbol=m["symbol"], status=m["status"],
            family_group=m.get("family_group", ""),
            bo_quantity=_dec("bo_quantity"), bo_avg_cost=_dec("bo_avg_cost"),
            bo_total_cost=_dec("bo_total_cost"), bo_market_price=_dec("bo_market_price"),
            bo_market_value=_dec("bo_market_value"), bo_pnl=_dec("bo_pnl"),
            bo_weight_pct=_dec("bo_weight_pct"), bo_isin=m.get("bo_isin"),
            our_quantity=_dec("our_quantity"), our_avg_cost=_dec("our_avg_cost"),
            our_total_cost=_dec("our_total_cost"), our_market_price=_dec("our_market_price"),
            our_market_value=_dec("our_market_value"), our_pnl=_dec("our_pnl"),
            our_weight_pct=_dec("our_weight_pct"),
            qty_diff=_dec("qty_diff"), cost_diff=_dec("cost_diff"),
            value_diff=_dec("value_diff"), pnl_diff=_dec("pnl_diff"),
        ))

    def _dec_field(key):
        v = c.get(key)
        return Decimal(str(v)) if v is not None else None

    return ClientReconciliationResponse(
        client_code=c["client_code"], client_name=c.get("client_name", ""),
        family_group=c.get("family_group", ""),
        client_found=c.get("client_found", True),
        total_holdings_bo=c.get("total_holdings_bo", 0),
        total_holdings_ours=c.get("total_holdings_ours", 0),
        matched_count=c.get("matched_count", 0),
        qty_mismatch_count=c.get("qty_mismatch_count", 0),
        cost_mismatch_count=c.get("cost_mismatch_count", 0),
        value_mismatch_count=c.get("value_mismatch_count", 0),
        missing_in_ours_count=c.get("missing_in_ours_count", 0),
        extra_in_ours_count=c.get("extra_in_ours_count", 0),
        match_pct=c.get("match_pct", 100.0),
        has_issues=c.get("has_issues", False),
        matches=matches,
        # 4-component NAV breakdown
        nav_total=_dec_field("nav_total"),
        nav_equity_component=_dec_field("nav_equity_component"),
        etf_component_nav=_dec_field("etf_component_nav"),
        cash_component_nav=_dec_field("cash_component_nav"),
        nav_date=c.get("nav_date"),
        # Equity 3-way
        bo_holdings_total=Decimal(str(c.get("bo_holdings_total", "0"))),
        our_holdings_total=Decimal(str(c.get("our_holdings_total", "0"))),
        nav_equity_vs_bo_diff=_dec_field("nav_equity_vs_bo_diff"),
        bo_vs_ours_diff=Decimal(str(c.get("bo_vs_ours_diff", "0"))),
        nav_vs_bo_diff=_dec_field("nav_vs_bo_diff"),
        # ETF reconciliation
        our_etf_holdings_total=Decimal(str(c.get("our_etf_holdings_total", "0"))),
        etf_vs_ours_diff=_dec_field("etf_vs_ours_diff"),
    )


@router.post("/upload", response_model=ReconciliationSummaryResponse)
async def upload_holding_report(
    file: UploadFile = File(...),
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationSummaryResponse:
    """Upload a PMS Holding Report .xlsx, reconcile, and persist results."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".xlsx", ".xls"):
        raise HTTPException(status_code=400, detail="Only .xlsx/.xls files accepted")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        records = parse_holding_report(tmp_path)
        if not records:
            raise HTTPException(status_code=400, detail="No holdings found in file")

        summary_info = holding_report_summary(records)
        result = await reconcile(records, db)

        market_date = summary_info.get("market_date")
        await save_reconciliation(db, result, market_date, file.filename)

        _cache["result"] = result
        _cache["market_date"] = market_date

        return _summary_to_response(result, market_date)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Reconciliation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Reconciliation failed: {exc}") from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.get("/summary", response_model=ReconciliationSummaryResponse)
async def get_summary(
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationSummaryResponse:
    """Get the latest reconciliation summary. Loads from DB if not in memory."""
    if _cache.get("result"):
        return _summary_to_response(_cache["result"], _cache.get("market_date"))

    stored = await load_latest_reconciliation(db)
    if stored is None:
        raise HTTPException(status_code=404, detail="No reconciliation data. Upload a holding report first.")

    stats = stored["stats"]
    clients_data = stored["summary"].get("clients", [])
    client_responses = [_db_row_to_client_response(c) for c in clients_data]

    return ReconciliationSummaryResponse(
        total_clients_bo=stats.get("total_clients_bo", 0),
        total_clients_matched=stats.get("total_clients_matched", 0),
        total_clients_missing=stats.get("total_clients_missing", 0),
        total_holdings_bo=stats.get("total_holdings_bo", 0),
        total_holdings_matched=stats.get("total_holdings_matched", 0),
        total_qty_mismatches=stats.get("total_qty_mismatches", 0),
        total_cost_mismatches=stats.get("total_cost_mismatches", 0),
        total_value_mismatches=stats.get("total_value_mismatches", 0),
        total_missing_in_ours=stats.get("total_missing_in_ours", 0),
        total_extra_in_ours=stats.get("total_extra_in_ours", 0),
        match_pct=stats.get("match_pct", 0),
        client_match_pct=stats.get("client_match_pct", 0),
        clients_fully_matched=stats.get("clients_fully_matched", 0),
        # 4-component NAV aggregate breakdown
        total_nav_value=Decimal(str(stats.get("total_nav_value", "0"))),
        total_nav_equity_value=Decimal(str(stats.get("total_nav_equity_value", "0"))),
        total_etf_value=Decimal(str(stats.get("total_etf_value", "0"))),
        total_cash_value=Decimal(str(stats.get("total_cash_value", "0"))),
        total_bo_holdings_value=Decimal(str(stats.get("total_bo_holdings_value", "0"))),
        total_our_holdings_value=Decimal(str(stats.get("total_our_holdings_value", "0"))),
        total_our_etf_holdings_value=Decimal(str(stats.get("total_our_etf_holdings_value", "0"))),
        total_nav_equity_vs_bo_diff=Decimal(str(stats.get("total_nav_equity_vs_bo_diff", "0"))),
        total_nav_vs_bo_diff=Decimal(str(stats.get("total_nav_vs_bo_diff", "0"))),
        total_bo_vs_ours_diff=Decimal(str(stats.get("total_bo_vs_ours_diff", "0"))),
        total_etf_vs_ours_diff=Decimal(str(stats.get("total_etf_vs_ours_diff", "0"))),
        clients_with_nav=stats.get("clients_with_nav", 0),
        market_date=stored.get("market_date"),
        commentary=stored.get("commentary", []),
        clients=client_responses,
    )


@router.get("/detail", response_model=ClientReconciliationResponse)
async def get_client_detail(
    client_code: str = Query(..., description="UCC / client_code to look up"),
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ClientReconciliationResponse:
    """Get reconciliation detail for a specific client."""
    if _cache.get("result"):
        for c in _cache["result"].clients:
            if c.client_code == client_code:
                return _client_to_response(c)

    stored = await load_latest_reconciliation(db)
    if stored:
        for c in stored["summary"].get("clients", []):
            if c["client_code"] == client_code:
                return _db_row_to_client_response(c)

    raise HTTPException(status_code=404, detail=f"Client {client_code} not found in reconciliation")


@router.get("/export")
async def export_mismatches(
    status_filter: str | None = Query(None, description="Filter by status"),
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export reconciliation mismatches as CSV."""
    clients_data = None
    if _cache.get("result"):
        clients_data = [
            {
                "client_code": c.client_code, "family_group": c.family_group,
                "matches": [
                    {
                        "symbol": m.symbol, "status": m.status, "bo_isin": m.bo_isin,
                        "bo_quantity": m.bo_quantity, "our_quantity": m.our_quantity, "qty_diff": m.qty_diff,
                        "bo_avg_cost": m.bo_avg_cost, "our_avg_cost": m.our_avg_cost, "cost_diff": m.cost_diff,
                        "bo_market_value": m.bo_market_value, "our_market_value": m.our_market_value,
                        "value_diff": m.value_diff,
                    }
                    for m in c.matches
                ],
            }
            for c in _cache["result"].clients
        ]
    else:
        stored = await load_latest_reconciliation(db)
        if stored:
            clients_data = stored["summary"].get("clients", [])

    if not clients_data:
        raise HTTPException(status_code=404, detail="No reconciliation data.")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Client Code", "Family Group", "Symbol", "Status", "ISIN",
        "BO Qty", "Our Qty", "Qty Diff",
        "BO Avg Cost", "Our Avg Cost", "Cost Diff",
        "BO Market Value", "Our Market Value", "Value Diff",
    ])

    for client in clients_data:
        for m in client.get("matches", []):
            status = m.get("status", "")
            if status_filter and status != status_filter:
                continue
            if not status_filter and status == "MATCH":
                continue
            writer.writerow([
                client.get("client_code", ""), client.get("family_group", ""),
                m.get("symbol", ""), status, m.get("bo_isin", ""),
                m.get("bo_quantity"), m.get("our_quantity"), m.get("qty_diff"),
                m.get("bo_avg_cost"), m.get("our_avg_cost"), m.get("cost_diff"),
                m.get("bo_market_value"), m.get("our_market_value"), m.get("value_diff"),
            ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=reconciliation_mismatches.csv"},
    )


@router.post("/sync-costs")
async def sync_costs_from_backoffice(
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sync avg_cost from backoffice for COST_MISMATCH holdings."""
    from sqlalchemy import text as sa_text

    result = _cache.get("result")
    if result is None:
        stored = await load_latest_reconciliation(db)
        if stored is None:
            raise HTTPException(status_code=404, detail="No reconciliation data.")
        updates = []
        for c in stored["summary"].get("clients", []):
            for m in c.get("matches", []):
                if m.get("status") == "COST_MISMATCH" and m.get("bo_avg_cost"):
                    updates.append((c["client_code"], m["symbol"], Decimal(m["bo_avg_cost"])))
    else:
        updates = [
            (c.client_code, m.symbol, m.bo_avg_cost)
            for c in result.clients for m in c.matches
            if m.status == "COST_MISMATCH" and m.bo_avg_cost is not None
        ]

    if not updates:
        return {"message": "No cost mismatches to sync", "updated": 0}

    updated = 0
    for client_code, symbol, bo_cost in updates:
        await db.execute(sa_text("""
            UPDATE cpp_holdings h
            SET avg_cost = :cost,
                unrealized_pnl = (h.current_price - :cost) * h.quantity,
                current_value = h.current_price * h.quantity
            FROM cpp_clients c
            WHERE c.id = h.client_id
              AND c.client_code = :code AND h.symbol = :sym
        """), {"cost": bo_cost, "code": client_code, "sym": symbol})
        updated += 1

    await db.commit()
    return {"message": f"Synced avg_cost for {updated} holdings from backoffice", "updated": updated}
