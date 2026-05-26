"""Admin router — file upload (background), preview, and upload status polling.

Job state lives in cpp_upload_log (C7), not in memory, so polling
``/upload-status/{job_id}`` works under multi-worker uvicorn — the polling
request may land on a different worker from the one running the ingestion.
"""

import asyncio
import datetime as dt
import logging
import os
import tempfile
import uuid
import zipfile
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from backend.database import AsyncSessionLocal, get_db
from backend.middleware.auth_middleware import (
    ROLE_ADMIN_DATA_ENTRY,
    ROLE_ADMIN_READONLY,
    require_role,
)
from backend.models.upload_log import UploadLog
from backend.schemas.admin import UploadPreviewResponse
from backend.services.file_format_detector import (
    FileFormatMismatch,
    UploadSlot,
    assert_format,
)

router = APIRouter(prefix="/api/admin", tags=["admin-upload"])
limiter = Limiter(key_func=get_remote_address)

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB

# Upload directory — non-tmp, writable by appuser (C16)
UPLOAD_DIR: str = os.environ.get("UPLOAD_DIR", "/app/data/uploads")

# Zip-bomb guard: reject xlsx files whose uncompressed content exceeds this (C16)
_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 200 MB


def _check_xlsx_zip_bomb(path: str) -> None:
    """Raise HTTP 400 if the xlsx zip entries exceed the uncompressed size cap.

    An xlsx file is a ZIP archive. A malicious file can have tiny compressed
    content that expands to gigabytes (zip bomb). We iterate the central
    directory — which is O(number of entries), not O(file size) — and sum
    the declared uncompressed sizes before touching any data.
    """
    total = 0
    try:
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                total += info.file_size
                if total > _MAX_UNCOMPRESSED_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"File rejected: uncompressed content exceeds "
                            f"{_MAX_UNCOMPRESSED_BYTES // 1024 // 1024} MB "
                            "(possible zip bomb)"
                        ),
                    )
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is not a valid xlsx (bad zip structure)",
        ) from exc

# Throttle DB writes during long ingestions so we don't write on every single
# client row — only when the progress message actually changes or every N rows.
_PROGRESS_FLUSH_EVERY = 1  # progress callback is already client-coarse


async def _create_upload_job(
    *,
    job_id: str,
    file_type: str,
    filename: str,
    admin_id: int,
) -> None:
    """Insert a fresh cpp_upload_log row with status='processing' (C7).

    Uses its own AsyncSession so the row commits independently of any caller
    transaction — we want pollers to see the row even if the request that
    started the upload is still in flight.
    """
    async with AsyncSessionLocal() as db:
        row = UploadLog(
            uploaded_by=admin_id,
            file_type=file_type,
            filename=filename,
            rows_processed=0,
            rows_failed=0,
            clients_affected=0,
            errors=[],
            job_id=job_id,
            status="processing",
            progress_pct=0,
            progress_message="Queued",
            started_at=dt.datetime.utcnow(),
        )
        db.add(row)
        await db.commit()


async def _update_upload_progress(
    job_id: str,
    *,
    progress_pct: int | None = None,
    progress_message: str | None = None,
) -> None:
    """UPDATE the upload_log row's progress fields (C7).

    Uses a dedicated short-lived session so the write commits immediately and
    becomes visible to any worker polling for status.
    """
    values: dict[str, Any] = {}
    if progress_pct is not None:
        values["progress_pct"] = max(0, min(100, progress_pct))
    if progress_message is not None:
        # Truncate to keep the row reasonably bounded.
        values["progress_message"] = progress_message[:1000]
    if not values:
        return
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(UploadLog).where(UploadLog.job_id == job_id).values(**values)
            )
            await db.commit()
    except Exception as exc:
        # Progress writes are best-effort — never let a transient DB blip kill
        # the underlying ingestion task.
        logger.warning("Failed to update upload progress for job %s: %s", job_id, exc)


async def _finalize_upload_job(
    job_id: str,
    *,
    status_: str,
    rows_processed: int = 0,
    rows_failed: int = 0,
    clients_affected: int = 0,
    errors: list[dict[str, Any]] | None = None,
    progress_message: str | None = None,
) -> None:
    """Mark the upload_log row complete/failed and stamp finished_at (C7)."""
    values: dict[str, Any] = {
        "status": status_,
        "rows_processed": rows_processed,
        "rows_failed": rows_failed,
        "clients_affected": clients_affected,
        "errors": errors or [],
        "finished_at": dt.datetime.utcnow(),
        "progress_pct": 100 if status_ == "completed" else 0,
    }
    if progress_message is not None:
        values["progress_message"] = progress_message[:1000]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(UploadLog).where(UploadLog.job_id == job_id).values(**values)
        )
        await db.commit()


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
    """Run ingestion in background with its own DB session.

    Persists progress and final state to cpp_upload_log via dedicated short
    transactions (C7). The ingestion itself runs in its own AsyncSession that
    is committed once at the end; progress updates use separate sessions so
    they become visible to pollers immediately, without holding the ingestion
    transaction open for the whole upload.
    """
    try:
        import backend.services.ingestion_service as svc
        ingest_fn = getattr(svc, ingest_func_name)

        def progress_callback(client_index: int, total_clients: int, client_code: str) -> None:
            # The callback may fire from a sync context inside the ingestion;
            # schedule the DB update on the running loop without blocking it.
            pct = 0
            if total_clients > 0:
                pct = int(client_index / total_clients * 100)
            msg = f"Processing client {client_index} of {total_clients}: {client_code}"
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    _update_upload_progress(
                        job_id, progress_pct=pct, progress_message=msg,
                    )
                )
            except RuntimeError:
                # No running loop (defensive — shouldn't happen here). Skip.
                pass

        async with AsyncSessionLocal() as db:
            result = await ingest_fn(
                tmp_path, admin_id, db, progress_callback=progress_callback,
            )
            if hasattr(result, "__dataclass_fields__"):
                from dataclasses import asdict
                result = asdict(result)
            await db.commit()

        await _finalize_upload_job(
            job_id,
            status_="completed",
            rows_processed=result.get("rows_processed", 0),
            rows_failed=result.get("rows_failed", 0),
            clients_affected=result.get("clients_affected", 0),
            errors=result.get("errors", []),
            progress_message="Done",
        )

    except Exception as exc:
        logger.error("Background %s ingestion failed: %s", file_type, exc, exc_info=True)
        await _finalize_upload_job(
            job_id,
            status_="failed",
            errors=[{
                "stage": "ingestion",
                "error": "File processing failed. Please check the file format and try again.",
            }],
            progress_message="Failed",
        )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def _save_and_start_background(
    file: UploadFile,
    ingest_func_name: str,
    file_type: str,
    admin_id: int,
    expected_slot: UploadSlot,
) -> dict[str, Any]:
    """Save upload to temp file and kick off background ingestion.

    Returns immediately with a job_id so the frontend can poll for status.

    Before dispatching the background task, the file is sniffed against the
    expected upload slot's fingerprint — wrong-slot uploads (e.g. a
    Transaction file dropped into the Holdings slot) are rejected with a
    400 so the admin sees the error immediately and no upsert runs against
    a mis-shaped row set.
    """
    _validate_upload(file)
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 50MB limit")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=os.path.splitext(file.filename or "upload")[1],
        dir=UPLOAD_DIR,
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    # Zip-bomb guard: check before opening with openpyxl (C16)
    if tmp_path.lower().endswith((".xlsx", ".xls")):
        try:
            _check_xlsx_zip_bomb(tmp_path)
        except HTTPException:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    # Guard: fingerprint the header BEFORE kicking off ingestion.
    # CSV uploads skip the sniff (openpyxl is xlsx-only); upstream slots
    # are xlsx in practice, so CSV only hits the /upload-preview path.
    if tmp_path.lower().endswith((".xlsx", ".xls")):
        try:
            detection = assert_format(tmp_path, expected_slot)
            logger.info(
                "Upload accepted for slot=%s: detected=%s confidence=%.2f filename=%s",
                expected_slot,
                detection.detected,
                detection.confidence,
                file.filename,
            )
        except FileFormatMismatch as exc:
            # Clean up the temp file — no background task will claim it.
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            logger.warning(
                "Rejected upload for slot=%s filename=%s: %s",
                expected_slot,
                file.filename,
                exc.detail,
            )
            raise HTTPException(status_code=400, detail=exc.detail) from exc
        except Exception as exc:
            # Parsing/open failure is a separate problem — keep the temp file
            # around in case the background task path can handle it gracefully.
            logger.warning(
                "File format sniff failed (passing through to ingestion): %s",
                exc,
            )

    job_id = str(uuid.uuid4())
    # Persist the job row BEFORE kicking off the task so a status poll that
    # races the task start still finds the row.
    await _create_upload_job(
        job_id=job_id,
        file_type=file_type,
        filename=file.filename or "unknown",
        admin_id=admin_id,
    )

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
    admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
) -> dict[str, Any]:
    """Upload NAV file — returns immediately, processes in background."""
    return await _save_and_start_background(
        file, "ingest_nav_file", "NAV", admin["client_id"], expected_slot="NAV",
    )


@router.post("/upload-transactions")
@limiter.limit("5/minute")
async def upload_transactions(
    request: Request,
    file: UploadFile,
    admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
) -> dict[str, Any]:
    """Upload transaction file — returns immediately, processes in background."""
    return await _save_and_start_background(
        file, "ingest_transaction_file", "TRANSACTIONS", admin["client_id"],
        expected_slot="TRANSACTIONS",
    )


@router.post("/upload-equity-holdings")
@limiter.limit("5/minute")
async def upload_equity_holdings(
    request: Request,
    file: UploadFile,
    admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
) -> dict[str, Any]:
    """Upload equity holding report — updates holding prices + runs reconciliation."""
    return await _save_and_start_background(
        file, "ingest_equity_holdings_file", "EQUITY_HOLDINGS", admin["client_id"],
        expected_slot="EQUITY_HOLDINGS",
    )


@router.post("/upload-etf-holdings")
@limiter.limit("5/minute")
async def upload_etf_holdings(
    request: Request,
    file: UploadFile,
    admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
) -> dict[str, Any]:
    """Upload ETF/MF holding report — updates ETF position prices in cpp_holdings."""
    return await _save_and_start_background(
        file, "ingest_etf_holdings_file", "ETF_HOLDINGS", admin["client_id"],
        expected_slot="ETF_HOLDINGS",
    )


@router.post("/upload-cashflows")
@limiter.limit("5/minute")
async def upload_cashflows(
    request: Request,
    file: UploadFile,
    admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
) -> dict[str, Any]:
    """Upload cash flow file — returns immediately, processes in background."""
    return await _save_and_start_background(
        file, "ingest_cashflow_file", "CASHFLOWS", admin["client_id"],
        expected_slot="CASHFLOWS",
    )


@router.get("/upload-status/{job_id}")
async def get_upload_status(
    job_id: str,
    admin: dict = Depends(require_role(ROLE_ADMIN_READONLY)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Poll upload job status from cpp_upload_log (C7).

    Backed by a DB row, so the result is consistent across uvicorn workers —
    a poll routed to a different worker than the one running the ingestion
    still sees the latest committed progress.

    The legacy response shape (status='complete') is preserved by mapping the
    DB-side 'completed' value to 'complete' for the frontend that expects it.
    """
    row = (await db.execute(
        select(UploadLog).where(UploadLog.job_id == job_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    started = row.started_at or dt.datetime.utcnow()
    finished = row.finished_at or dt.datetime.utcnow()
    elapsed = (finished - started).total_seconds()

    # Map DB status → API status. We use 'completed' in the DB (matches the
    # natural English past tense and the column default), but the existing
    # frontend polls for 'complete' — keep the wire contract stable.
    api_status = "complete" if row.status == "completed" else row.status

    errors = row.errors if isinstance(row.errors, list) else []

    return {
        "job_id": job_id,
        "status": api_status,
        "file_type": row.file_type,
        "filename": row.filename,
        "rows_processed": row.rows_processed,
        "rows_failed": row.rows_failed,
        "clients_affected": row.clients_affected,
        "errors": errors[:20],
        "elapsed_seconds": round(elapsed, 1),
        "progress_pct": row.progress_pct,
        "progress_message": row.progress_message or "",
    }


@router.post("/upload-preview", response_model=UploadPreviewResponse)
async def upload_preview(
    file: UploadFile,
    admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
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

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=UPLOAD_DIR) as tmp:
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
