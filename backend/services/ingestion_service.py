"""
Ingestion orchestrator — parses uploaded files, upserts data, triggers risk computation.

Two entry points:
  ingest_nav_file()         — Parse NAV .xlsx, upsert to DB, fetch benchmark, run risk engine
  ingest_transaction_file() — Parse transaction .xlsx, upsert to DB, recompute holdings

DB helper functions live in ingestion_helpers.py.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.ingestion_helpers import (
    find_or_create_client,
    find_or_create_portfolio,
    log_upload,
    recompute_holdings,
    update_benchmark_values,
    upsert_cash_flows,
    upsert_nav_rows,
    upsert_transactions,
)
from backend.services.nav_parser import parse_nav_file
from backend.services.risk_engine import run_risk_engine
from backend.services.txn_parser import parse_transaction_file

logger = logging.getLogger(__name__)


@dataclass
class UploadResult:
    """Summary of an upload/ingestion operation."""

    file_type: str
    filename: str
    rows_processed: int = 0
    rows_failed: int = 0
    clients_affected: int = 0
    errors: list[dict] = field(default_factory=list)
    client_codes: list[str] = field(default_factory=list)


def _group_by_client(records: list[dict]) -> dict[str, list[dict]]:
    """Group parsed records by client_code."""
    clients: dict[str, list[dict]] = {}
    for rec in records:
        code = rec["client_code"]
        if code not in clients:
            clients[code] = []
        clients[code].append(rec)
    return clients


async def _log(db: AsyncSession, upload: UploadResult, uploaded_by: int) -> None:
    """Convenience wrapper around log_upload."""
    await log_upload(
        db,
        file_type=upload.file_type,
        filename=upload.filename,
        rows_processed=upload.rows_processed,
        rows_failed=upload.rows_failed,
        clients_affected=upload.clients_affected,
        errors=upload.errors,
        uploaded_by=uploaded_by,
    )


async def ingest_nav_file(
    filepath: str | Path,
    uploaded_by: int,
    db: AsyncSession,
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> UploadResult:
    """
    Full NAV ingestion pipeline:
      1. Parse .xlsx with nav_parser
      2. For each client: find-or-create client + portfolio
      3. Upsert NAV rows
      4. Fetch + align benchmark data
      5. Run risk engine per client
      6. Log upload in cpp_upload_log
    """
    filepath = Path(filepath)
    upload = UploadResult(file_type="NAV", filename=filepath.name)

    # 1. Parse
    logger.info("Starting NAV ingestion: %s", filepath.name)
    try:
        records = parse_nav_file(filepath)
    except Exception as exc:
        upload.errors.append({"stage": "parse", "error": str(exc)})
        logger.error("NAV parse failed: %s", exc)
        await _log(db, upload, uploaded_by)
        return upload

    if not records:
        upload.errors.append({"stage": "parse", "error": "No records parsed from file"})
        await _log(db, upload, uploaded_by)
        return upload

    clients = _group_by_client(records)
    upload.clients_affected = len(clients)
    upload.client_codes = list(clients.keys())

    # 2-5. Process each client
    total_clients = len(clients)
    for idx, (client_code, client_records) in enumerate(clients.items()):
        client_name = client_records[0]["client_name"]
        logger.info("Processing NAV for %s (%d of %d)", client_code, idx + 1, total_clients)

        if progress_callback is not None:
            progress_callback(idx, total_clients, client_code)

        try:
            client_id = await find_or_create_client(db, client_code, client_name)
            inception = min(r["date"] for r in client_records)
            portfolio_id = await find_or_create_portfolio(db, client_id, inception)

            nav_count = await upsert_nav_rows(db, client_id, portfolio_id, client_records)
            upload.rows_processed += nav_count

            bench_count = await update_benchmark_values(db, client_id, portfolio_id)
            logger.debug("Updated %d benchmark values for %s", bench_count, client_code)

            # Commit before risk engine so it can read the data
            await db.commit()

            await run_risk_engine(client_id, portfolio_id, db)
            await db.commit()

        except Exception as exc:
            upload.rows_failed += len(client_records)
            upload.errors.append({
                "stage": "client_processing",
                "client_code": client_code,
                "error": str(exc),
            })
            logger.error("Failed processing client %s: %s", client_code, exc, exc_info=True)
            await db.rollback()

    # 6. Log upload
    await _log(db, upload, uploaded_by)
    await db.commit()

    logger.info(
        "NAV ingestion complete: %d rows processed, %d failed, %d clients",
        upload.rows_processed, upload.rows_failed, upload.clients_affected,
    )
    return upload


async def ingest_transaction_file(
    filepath: str | Path,
    uploaded_by: int,
    db: AsyncSession,
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> UploadResult:
    """
    Full transaction ingestion pipeline:
      1. Parse .xlsx with txn_parser
      2. For each client: find-or-create client + portfolio
      3. Insert transactions
      4. Recompute holdings per client
      5. Log upload
    """
    filepath = Path(filepath)
    upload = UploadResult(file_type="TRANSACTIONS", filename=filepath.name)

    # 1. Parse
    logger.info("Starting transaction ingestion: %s", filepath.name)
    try:
        records = parse_transaction_file(filepath)
    except Exception as exc:
        upload.errors.append({"stage": "parse", "error": str(exc)})
        logger.error("Transaction parse failed: %s", exc)
        await _log(db, upload, uploaded_by)
        return upload

    if not records:
        upload.errors.append({"stage": "parse", "error": "No records parsed from file"})
        await _log(db, upload, uploaded_by)
        return upload

    clients = _group_by_client(records)
    upload.clients_affected = len(clients)
    upload.client_codes = list(clients.keys())

    # 2-4. Process each client
    total_clients = len(clients)
    for idx, (client_code, client_records) in enumerate(clients.items()):
        client_name = client_records[0]["client_name"]
        logger.info("Processing txns for %s (%d of %d)", client_code, idx + 1, total_clients)

        if progress_callback is not None:
            progress_callback(idx, total_clients, client_code)

        try:
            client_id = await find_or_create_client(db, client_code, client_name)
            inception = min(r["date"] for r in client_records)
            portfolio_id = await find_or_create_portfolio(db, client_id, inception)

            txn_count = await upsert_transactions(db, client_id, portfolio_id, client_records)
            upload.rows_processed += txn_count

            holdings_count = await recompute_holdings(db, client_id, portfolio_id)
            logger.debug("Recomputed %d holdings for %s", holdings_count, client_code)

            await db.commit()

        except Exception as exc:
            upload.rows_failed += len(client_records)
            upload.errors.append({
                "stage": "client_processing",
                "client_code": client_code,
                "error": str(exc),
            })
            logger.error("Failed processing client %s: %s", client_code, exc, exc_info=True)
            await db.rollback()

    # 5. Log upload
    await _log(db, upload, uploaded_by)
    await db.commit()

    logger.info(
        "Transaction ingestion complete: %d rows, %d failed, %d clients",
        upload.rows_processed, upload.rows_failed, upload.clients_affected,
    )
    return upload


async def ingest_cashflow_file(
    filepath: str | Path,
    uploaded_by: int,
    db: AsyncSession,
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> UploadResult:
    """
    Cash flow ingestion pipeline:
      1. Parse .xlsx with cashflow_parser
      2. For each client: find-or-create client + portfolio
      3. Upsert cash flow records
      4. Log upload
    """
    filepath = Path(filepath)
    upload = UploadResult(file_type="CASHFLOWS", filename=filepath.name)

    logger.info("Starting cash flow ingestion: %s", filepath.name)
    try:
        from backend.services.cashflow_parser import parse_cashflow_file
        records = parse_cashflow_file(filepath)
    except Exception as exc:
        upload.errors.append({"stage": "parse", "error": str(exc)})
        logger.error("Cash flow parse failed: %s", exc)
        await _log(db, upload, uploaded_by)
        return upload

    if not records:
        upload.errors.append({"stage": "parse", "error": "No records parsed from file"})
        await _log(db, upload, uploaded_by)
        return upload

    clients = _group_by_client(records)
    upload.clients_affected = len(clients)
    upload.client_codes = list(clients.keys())

    total_clients = len(clients)
    for idx, (client_code, client_records) in enumerate(clients.items()):
        client_name = client_records[0]["client_name"]
        logger.info("Processing cash flows for %s (%d of %d)", client_code, idx + 1, total_clients)

        if progress_callback is not None:
            progress_callback(idx, total_clients, client_code)

        try:
            client_id = await find_or_create_client(db, client_code, client_name)
            inception = min(r["date"] for r in client_records)
            portfolio_id = await find_or_create_portfolio(db, client_id, inception)

            cf_count = await upsert_cash_flows(db, client_id, portfolio_id, client_records)
            upload.rows_processed += cf_count
            await db.commit()

        except Exception as exc:
            upload.rows_failed += len(client_records)
            upload.errors.append({
                "stage": "client_processing",
                "client_code": client_code,
                "error": str(exc),
            })
            logger.error("Failed processing cash flows for %s: %s", client_code, exc, exc_info=True)
            await db.rollback()

    await _log(db, upload, uploaded_by)
    await db.commit()

    logger.info(
        "Cash flow ingestion complete: %d rows processed, %d failed, %d clients",
        upload.rows_processed, upload.rows_failed, upload.clients_affected,
    )
    return upload
