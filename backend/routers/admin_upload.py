"""Admin router — file upload (background), preview, and upload status polling."""

import asyncio
import logging
import os
import tempfile
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

from backend.database import AsyncSessionLocal
from backend.middleware.auth_middleware import get_admin_user
from backend.schemas.admin import UploadPreviewResponse

router = APIRouter(prefix="/api/admin", tags=["admin-upload"])
limiter = Limiter(key_func=get_remote_address)

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB

# In-memory upload job tracker for background processing status
_upload_jobs: dict[str, dict[str, Any]] = {}


def _validate_upload(file: UploadFile) -> str:
    """Validate upload file extension. Returns the extension."""
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {ALLOWED_EXTENSIONS}",
        )
    return ext


async def _run_ingestion_background(
    tmp_path: str,
    ingest_func_name: str,
    file_type: str,
    filename: str,
    admin_id: int,
    job_id: str,
) -> None:
    """Run ingestion in background with its own DB session. Updates job status."""
    try:
        import backend.services.ingestion_service as svc
        ingest_fn = getattr(svc, ingest_func_name)

        def progress_callback(client_index: int, total_clients: int, client_code: str) -> None:
            _upload_jobs[job_id].update({
                "clients_processed": client_index,
                "clients_total": total_clients,
                "current_client": client_code,
            })

        async with AsyncSessionLocal() as db:
            result = await ingest_fn(tmp_path, admin_id, db, progress_callback=progress_callback)
            if hasattr(result, "__dataclass_fields__"):
                from dataclasses import asdict
                result = asdict(result)
            await db.commit()

        _upload_jobs[job_id].update({
            "status": "complete",
            "rows_processed": result.get("rows_processed", 0),
            "rows_failed": result.get("rows_failed", 0),
            "clients_affected": result.get("clients_affected", 0),
            "errors": result.get("errors", []),
        })

    except Exception as exc:
        logger.error("Background %s ingestion failed: %s", file_type, exc, exc_info=True)
        _upload_jobs[job_id].update({
            "status": "failed",
            "errors": [{"stage": "ingestion", "error": "File processing failed. Please check the file format and try again."}],
        })
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def _save_and_start_background(
    file: UploadFile,
    ingest_func_name: str,
    file_type: str,
    admin_id: int,
) -> dict[str, Any]:
    """Save upload to temp file and kick off background ingestion.

    Returns immediately with a job_id so the frontend can poll for status.
    """
    _validate_upload(file)
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 50MB limit")

    with tempfile.NamedTemporaryFile(
        delete=False, suffix=os.path.splitext(file.filename or "upload")[1]
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    job_id = f"{file_type}_{int(time.time() * 1000)}"
    _upload_jobs[job_id] = {
        "status": "processing",
        "file_type": file_type,
        "filename": file.filename,
        "rows_processed": 0,
        "rows_failed": 0,
        "clients_affected": 0,
        "errors": [],
        "started_at": time.time(),
        "clients_processed": 0,
        "clients_total": 0,
        "current_client": "",
    }

    asyncio.create_task(
        _run_ingestion_background(
            tmp_path, ingest_func_name, file_type,
            file.filename or "unknown", admin_id, job_id,
        )
    )

    return {"job_id": job_id, "status": "processing", "file_type": file_type}


@router.post("/upload-nav")
@limiter.limit("5/minute")
async def upload_nav(
    request: Request,
    file: UploadFile,
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Upload NAV file — returns immediately, processes in background."""
    return await _save_and_start_background(
        file, "ingest_nav_file", "NAV", admin["client_id"],
    )


@router.post("/upload-transactions")
@limiter.limit("5/minute")
async def upload_transactions(
    request: Request,
    file: UploadFile,
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Upload transaction file — returns immediately, processes in background."""
    return await _save_and_start_background(
        file, "ingest_transaction_file", "TRANSACTIONS", admin["client_id"],
    )


@router.post("/upload-cashflows")
@limiter.limit("5/minute")
async def upload_cashflows(
    request: Request,
    file: UploadFile,
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Upload cash flow file — returns immediately, processes in background."""
    return await _save_and_start_background(
        file, "ingest_cashflow_file", "CASHFLOWS", admin["client_id"],
    )


@router.get("/upload-status/{job_id}")
async def get_upload_status(
    job_id: str,
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Poll upload job status. Returns processing/complete/failed."""
    job = _upload_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    elapsed = time.time() - job.get("started_at", time.time())
    return {
        "job_id": job_id,
        "status": job["status"],
        "file_type": job["file_type"],
        "filename": job["filename"],
        "rows_processed": job["rows_processed"],
        "rows_failed": job["rows_failed"],
        "clients_affected": job["clients_affected"],
        "errors": job["errors"][:20],
        "elapsed_seconds": round(elapsed, 1),
        "clients_processed": job.get("clients_processed", 0),
        "clients_total": job.get("clients_total", 0),
        "current_client": job.get("current_client", ""),
    }


@router.post("/upload-preview", response_model=UploadPreviewResponse)
async def upload_preview(
    file: UploadFile,
    admin: dict = Depends(get_admin_user),
) -> UploadPreviewResponse:
    """Preview first 10 rows of an uploaded file with auto-column mapping."""
    import csv
    import io

    ext = _validate_upload(file)
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 50MB limit")

    columns: list[str] = []
    sample_rows: list[dict[str, Any]] = []
    row_count = 0

    if ext == ".csv":
        text_content = content.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text_content))
        columns = reader.fieldnames or []
        for i, row in enumerate(reader):
            row_count += 1
            if i < 10:
                sample_rows.append(dict(row))
    else:
        columns, sample_rows, row_count = _parse_xlsx_preview(content, ext)

    auto_mapped = _auto_map_columns(columns)
    return UploadPreviewResponse(
        columns=columns, sample_rows=sample_rows, row_count=row_count,
        auto_mapped=auto_mapped,
    )


def _parse_xlsx_preview(
    content: bytes, ext: str
) -> tuple[list[str], list[dict], int]:
    """Read first 10 data rows from xlsx file."""
    import openpyxl

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    columns: list[str] = []
    sample_rows: list[dict[str, Any]] = []
    row_count = 0

    try:
        wb = openpyxl.load_workbook(tmp_path, read_only=True, data_only=True)
        ws = wb.active
        if ws is not None:
            header_done = False
            for row_cells in ws.iter_rows(values_only=True):
                vals = [str(c) if c is not None else "" for c in row_cells]
                if not header_done:
                    columns = vals
                    header_done = True
                    continue
                row_count += 1
                if row_count <= 10:
                    sample_rows.append(
                        {columns[i]: vals[i] for i in range(min(len(columns), len(vals)))}
                    )
            wb.close()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return columns, sample_rows, row_count


def _auto_map_columns(columns: list[str]) -> dict[str, str]:
    """Auto-map known column names to internal field names."""
    known = {
        "ucc": "client_code", "date": "nav_date", "corpus": "invested_amount",
        "nav": "nav_value", "liquidity %": "cash_pct",
        "high water mark": "high_water_mark", "script": "symbol",
        "exch": "exchange", "stno": "settlement_no",
    }
    auto_mapped: dict[str, str] = {}
    for col in columns:
        col_lower = col.strip().lower()
        if col_lower in known:
            auto_mapped[col] = known[col_lower]
    return auto_mapped
