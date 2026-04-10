"""Admin reconciliation router — upload holding report and compare against our data."""

import csv
import io
import logging
import tempfile
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/reconciliation", tags=["admin-reconciliation"])

# In-memory store for latest reconciliation result (single-tenant admin tool)
_latest_result: dict = {}


def _match_to_response(m) -> HoldingMatchResponse:
    return HoldingMatchResponse(
        client_code=m.client_code,
        symbol=m.symbol,
        status=m.status,
        family_group=m.family_group,
        bo_quantity=m.bo_quantity,
        bo_avg_cost=m.bo_avg_cost,
        bo_total_cost=m.bo_total_cost,
        bo_market_price=m.bo_market_price,
        bo_market_value=m.bo_market_value,
        bo_pnl=m.bo_pnl,
        bo_weight_pct=m.bo_weight_pct,
        bo_isin=m.bo_isin,
        our_quantity=m.our_quantity,
        our_avg_cost=m.our_avg_cost,
        our_total_cost=m.our_total_cost,
        our_market_price=m.our_market_price,
        our_market_value=m.our_market_value,
        our_pnl=m.our_pnl,
        our_weight_pct=m.our_weight_pct,
        qty_diff=m.qty_diff,
        cost_diff=m.cost_diff,
        value_diff=m.value_diff,
        pnl_diff=m.pnl_diff,
    )


def _client_to_response(c) -> ClientReconciliationResponse:
    return ClientReconciliationResponse(
        client_code=c.client_code,
        family_group=c.family_group,
        client_found=c.client_found,
        total_holdings_bo=c.total_holdings_bo,
        total_holdings_ours=c.total_holdings_ours,
        matched_count=c.matched_count,
        qty_mismatch_count=c.qty_mismatch_count,
        cost_mismatch_count=c.cost_mismatch_count,
        value_mismatch_count=c.value_mismatch_count,
        missing_in_ours_count=c.missing_in_ours_count,
        extra_in_ours_count=c.extra_in_ours_count,
        match_pct=c.match_pct,
        has_issues=c.has_issues,
        matches=[_match_to_response(m) for m in c.matches],
    )


@router.post("/upload", response_model=ReconciliationSummaryResponse)
async def upload_holding_report(
    file: UploadFile = File(...),
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationSummaryResponse:
    """Upload a PMS Holding Report .xlsx and run reconciliation against our holdings."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".xlsx", ".xls"):
        raise HTTPException(status_code=400, detail="Only .xlsx/.xls files accepted")

    # Save to temp file for openpyxl
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Parse
        records = parse_holding_report(tmp_path)
        if not records:
            raise HTTPException(status_code=400, detail="No holdings found in file")

        summary_info = holding_report_summary(records)

        # Reconcile
        result = await reconcile(records, db)

        # Store for subsequent queries
        _latest_result["summary"] = result
        _latest_result["market_date"] = summary_info.get("market_date")

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
            market_date=summary_info.get("market_date"),
            clients=[_client_to_response(c) for c in result.clients],
        )
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
) -> ReconciliationSummaryResponse:
    """Get the latest reconciliation summary (without re-uploading)."""
    result = _latest_result.get("summary")
    if result is None:
        raise HTTPException(status_code=404, detail="No reconciliation data. Upload a holding report first.")

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
        market_date=_latest_result.get("market_date"),
        clients=[
            _client_to_response(c)
            for c in result.clients
        ],
    )


@router.get("/detail", response_model=ClientReconciliationResponse)
async def get_client_detail(
    client_code: str = Query(..., description="UCC / client_code to look up"),
    admin: dict = Depends(get_admin_user),
) -> ClientReconciliationResponse:
    """Get reconciliation detail for a specific client."""
    result = _latest_result.get("summary")
    if result is None:
        raise HTTPException(status_code=404, detail="No reconciliation data. Upload a holding report first.")

    for c in result.clients:
        if c.client_code == client_code:
            return _client_to_response(c)

    raise HTTPException(status_code=404, detail=f"Client {client_code} not found in reconciliation")


@router.get("/export")
async def export_mismatches(
    status_filter: str | None = Query(None, description="Filter by status: QTY_MISMATCH, COST_MISMATCH, MISSING_IN_OURS, EXTRA_IN_OURS"),
    admin: dict = Depends(get_admin_user),
) -> StreamingResponse:
    """Export reconciliation mismatches as CSV."""
    result = _latest_result.get("summary")
    if result is None:
        raise HTTPException(status_code=404, detail="No reconciliation data. Upload a holding report first.")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Client Code", "Family Group", "Symbol", "Status", "ISIN",
        "BO Qty", "Our Qty", "Qty Diff",
        "BO Avg Cost", "Our Avg Cost", "Cost Diff",
        "BO Market Value", "Our Market Value", "Value Diff",
        "BO P&L", "Our P&L", "P&L Diff",
    ])

    for client in result.clients:
        for m in client.matches:
            if status_filter and m.status != status_filter:
                continue
            if not status_filter and m.status == "MATCH":
                continue  # Skip matches in export by default

            writer.writerow([
                m.client_code, m.family_group, m.symbol, m.status, m.bo_isin or "",
                m.bo_quantity, m.our_quantity, m.qty_diff,
                m.bo_avg_cost, m.our_avg_cost, m.cost_diff,
                m.bo_market_value, m.our_market_value, m.value_diff,
                m.bo_pnl, m.our_pnl, m.pnl_diff,
            ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=reconciliation_mismatches.csv"},
    )
