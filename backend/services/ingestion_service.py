"""
Ingestion orchestrator — parses uploaded files, upserts data, triggers risk computation.

Entry points:
  ingest_nav_file()              — Parse NAV .xlsx, upsert to DB, fetch benchmark, run risk engine
  ingest_transaction_file()      — Parse transaction .xlsx, upsert to DB, recompute holdings
  ingest_equity_holdings_file()  — Parse equity holding report, update prices, run reconciliation
  ingest_etf_holdings_file()     — Parse ETF holding report, update ETF/MF prices in cpp_holdings

DB helper functions live in ingestion_helpers.py.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import AsyncSessionLocal
from backend.services.benchmark_service import fetch_nifty_data
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
from backend.services.risk_engine import run_risk_engine, run_risk_engine_batch
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


def _derive_cash_flows_from_nav(client_code: str, records: list[dict]) -> list[dict]:
    """Derive INFLOW/OUTFLOW records from corpus changes in parsed NAV records.

    Called during NAV ingestion so cpp_cash_flows stays current without needing
    a separate cashflow file upload.  XIRR then always uses current corpus data.
    """
    sorted_recs = sorted(records, key=lambda r: r["date"])
    prev_corpus = Decimal("0")
    cf_records: list[dict] = []
    for rec in sorted_recs:
        corpus = Decimal(str(rec["corpus"])) if rec["corpus"] is not None else Decimal("0")
        if corpus != prev_corpus:
            delta = corpus - prev_corpus
            nav_date = rec["date"].date() if isinstance(rec["date"], datetime) else rec["date"]
            cf_records.append({
                "date": nav_date,
                "flow_type": "INFLOW" if delta > 0 else "OUTFLOW",
                "amount": abs(delta),
                "description": "Derived from corpus change in NAV file",
                "client_code": client_code,
            })
            prev_corpus = corpus
    return cf_records


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
    """Write upload log using a fresh session — guaranteed to succeed even if main session is dirty."""
    try:
        async with AsyncSessionLocal() as log_db:
            await log_upload(
                log_db,
                file_type=upload.file_type,
                filename=upload.filename,
                rows_processed=upload.rows_processed,
                rows_failed=upload.rows_failed,
                clients_affected=upload.clients_affected,
                errors=upload.errors,
                uploaded_by=uploaded_by,
            )
            await log_db.commit()
    except Exception as exc:
        logger.error("Failed to write upload log: %s", exc, exc_info=True)


async def ingest_nav_file(
    filepath: str | Path,
    uploaded_by: int,
    db: AsyncSession,
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> UploadResult:
    """
    Full NAV ingestion pipeline (optimised):
      1. Parse .xlsx with nav_parser
      2. Pre-fetch benchmark data ONCE for the entire date range of the file
      3. Phase A — For each client: find-or-create, bulk upsert NAV + benchmark, commit
      4. Phase B — Run risk engine for every successfully ingested client
      5. Log upload in cpp_upload_log

    Pre-fetching benchmark once (step 2) eliminates N×yfinance calls (one per
    client) and replaces them with a single network request.  Bulk upserts in
    steps 3 reduce SQL round-trips from O(rows) to O(rows/500).
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

    # 2. Determine global date range and pre-fetch benchmark once
    all_dates: set = set()
    for client_records in clients.values():
        for rec in client_records:
            d = rec["date"].date() if isinstance(rec["date"], datetime) else rec["date"]
            all_dates.add(d)

    nifty_df: pd.DataFrame = pd.DataFrame(columns=["close"])
    if all_dates:
        min_date = min(all_dates)
        max_date = max(all_dates)
        logger.info("Pre-fetching benchmark data: %s to %s", min_date, max_date)
        try:
            nifty_df = fetch_nifty_data(min_date, max_date)
            logger.info("Benchmark pre-fetch: %d rows", len(nifty_df))
        except Exception as exc:
            logger.warning("Benchmark pre-fetch failed (%s); will retry per-client", exc)

    # Phase A: bulk upsert NAV + benchmark for every client
    total_clients = len(clients)
    processed_clients: list[tuple[int, int, str]] = []  # (client_id, portfolio_id, client_code)

    for idx, (client_code, client_records) in enumerate(clients.items()):
        client_name = client_records[0]["client_name"]
        logger.info(
            "Phase A — upserting NAV for %s (%d of %d)", client_code, idx + 1, total_clients
        )

        if progress_callback is not None:
            progress_callback(idx, total_clients, client_code)

        try:
            client_id = await find_or_create_client(db, client_code, client_name)
            inception = min(r["date"] for r in client_records)
            portfolio_id = await find_or_create_portfolio(db, client_id, inception)

            nav_count = await upsert_nav_rows(db, client_id, portfolio_id, client_records)
            upload.rows_processed += nav_count

            # Derive cash flows from corpus changes and upsert — keeps cpp_cash_flows
            # current after every NAV upload so XIRR is always accurate.
            cf_records = _derive_cash_flows_from_nav(client_code, client_records)
            if cf_records:
                cf_count = await upsert_cash_flows(db, client_id, portfolio_id, cf_records)
                logger.debug("Upserted %d corpus-derived cash flows for %s", cf_count, client_code)

            # Pass the pre-fetched nifty_df; falls back to per-client fetch if empty
            bench_data = nifty_df if not nifty_df.empty else None
            bench_count = await update_benchmark_values(
                db, client_id, portfolio_id, benchmark_data=bench_data
            )
            logger.debug("Updated %d benchmark values for %s", bench_count, client_code)

            await db.commit()
            processed_clients.append((client_id, portfolio_id, client_code))

        except Exception as exc:
            upload.rows_failed += len(client_records)
            upload.errors.append({
                "stage": "upsert",
                "client_code": client_code,
                "error": str(exc),
            })
            logger.error("Phase A failed for %s: %s", client_code, exc, exc_info=True)
            await db.rollback()

    # Phase B: run risk engine in parallel (5 concurrent, skip up-to-date)
    if processed_clients:
        logger.info("Phase B — running risk engine for %d clients (parallel)", len(processed_clients))
        batch_result = await run_risk_engine_batch(
            processed_clients, AsyncSessionLocal, concurrency=5, force=True,
        )
        if batch_result["failed"] > 0:
            for err_msg in batch_result["errors"]:
                upload.errors.append({"stage": "risk_engine", "error": err_msg})

    # 5. Log upload — uses its own session so it always succeeds
    await _log(db, upload, uploaded_by)

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

    # 5. Update live prices for all holdings
    try:
        from backend.services.live_prices import update_holdings_prices
        logger.info("Updating live prices after transaction ingestion...")
        price_result = await update_holdings_prices(db)
        await db.commit()
        logger.info("Price update: %s", price_result)
    except Exception as exc:
        logger.warning("Price update failed (non-critical): %s", exc)
        await db.rollback()

    # 6. Log upload — uses its own session so it always succeeds
    await _log(db, upload, uploaded_by)

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

    await _log(db, upload, uploaded_by)  # uses its own session

    logger.info(
        "Cash flow ingestion complete: %d rows processed, %d failed, %d clients",
        upload.rows_processed, upload.rows_failed, upload.clients_affected,
    )
    return upload


async def _update_holdings_prices_from_report(
    db: AsyncSession,
    records: list[dict],
) -> int:
    """Update current_price, current_value, unrealized_pnl in cpp_holdings
    from holding report records. Matches by ISIN first, symbol fallback.

    Returns count of updated rows.
    """
    from sqlalchemy import text

    updated = 0
    for rec in records:
        ucc = rec["ucc"]
        isin = (rec.get("isin") or "").strip()
        symbol = (rec.get("symbol") or "").strip()
        market_price = rec.get("market_price")

        if not market_price or not ucc:
            continue

        if isin:
            r = await db.execute(text("""
                UPDATE cpp_holdings h
                SET current_price = :price,
                    current_value = h.quantity * :price,
                    unrealized_pnl = (h.quantity * :price) - (h.quantity * h.avg_cost),
                    updated_at = NOW()
                FROM cpp_clients c
                WHERE c.id = h.client_id
                  AND c.client_code = :ucc
                  AND h.isin = :isin
                  AND h.quantity > 0
            """), {"price": market_price, "ucc": ucc, "isin": isin})
        else:
            r = await db.execute(text("""
                UPDATE cpp_holdings h
                SET current_price = :price,
                    current_value = h.quantity * :price,
                    unrealized_pnl = (h.quantity * :price) - (h.quantity * h.avg_cost),
                    updated_at = NOW()
                FROM cpp_clients c
                WHERE c.id = h.client_id
                  AND c.client_code = :ucc
                  AND h.symbol = :sym
                  AND h.quantity > 0
            """), {"price": market_price, "ucc": ucc, "sym": symbol})

        updated += r.rowcount

    return updated


async def ingest_equity_holdings_file(
    filepath: str | Path,
    uploaded_by: int,
    db: AsyncSession,
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> UploadResult:
    """
    Equity holding file ingestion pipeline:
      1. Parse BO holding report (.xlsx)
      2. Update current_price / current_value in cpp_holdings for all matched positions
      3. Run 3-way reconciliation and persist results to DB
      4. Log upload

    The reconciliation result is saved so it's visible on the Reconciliation page
    without needing a separate upload there.
    """
    filepath = Path(filepath)
    upload = UploadResult(file_type="EQUITY_HOLDINGS", filename=filepath.name)

    logger.info("Starting equity holdings ingestion: %s", filepath.name)
    try:
        from backend.services.holding_report_parser import (
            holding_report_summary,
            parse_holding_report,
        )
        records = parse_holding_report(filepath)
    except Exception as exc:
        upload.errors.append({"stage": "parse", "error": str(exc)})
        logger.error("Equity holdings parse failed: %s", exc)
        await _log(db, upload, uploaded_by)
        return upload

    if not records:
        upload.errors.append({"stage": "parse", "error": "No holdings found in file"})
        await _log(db, upload, uploaded_by)
        return upload

    uccs = list({r["ucc"] for r in records})
    upload.clients_affected = len(uccs)
    upload.client_codes = uccs

    # Update holding prices
    try:
        updated = await _update_holdings_prices_from_report(db, records)
        await db.commit()
        upload.rows_processed = updated
        logger.info("Updated %d holding prices from equity report", updated)
    except Exception as exc:
        upload.errors.append({"stage": "price_update", "error": str(exc)})
        logger.error("Holdings price update failed: %s", exc, exc_info=True)
        await db.rollback()

    # Run reconciliation and persist so it's visible on the Reconciliation page
    try:
        from backend.services.holding_report_parser import holding_report_summary
        from backend.services.reconciliation_service import reconcile
        from backend.services.reconciliation_store import (
            load_latest_bo_holdings,
            save_bo_holdings_snapshot,
            save_reconciliation,
        )

        summary_info = holding_report_summary(records)
        market_date = summary_info.get("market_date")

        # Persist this equity snapshot, then union with the latest ETF snapshot
        # (if any) so EXTRA_IN_OURS flags on ETF positions clear once the BO
        # exports both files. Tag records with source_bucket so reconcile()
        # routes ETF rows against etf_component_nav (loader already tags ETFs).
        await save_bo_holdings_snapshot(db, "EQUITY", market_date, filepath.name, records)
        for r in records:
            r["source_bucket"] = "EQUITY"
        etf_records = await load_latest_bo_holdings(db, "ETF")
        combined = list(records) + list(etf_records)
        logger.info(
            "Reconciliation input: %d equity records + %d ETF records (from latest ETF snapshot)",
            len(records), len(etf_records),
        )

        reco_result = await reconcile(combined, db)
        await save_reconciliation(db, reco_result, market_date, filepath.name)
        logger.info(
            "Reconciliation saved: %d/%d clients matched",
            reco_result.total_clients_matched, reco_result.total_clients_bo,
        )
    except Exception as exc:
        logger.warning("Reconciliation step failed (non-critical): %s", exc)
        upload.errors.append({"stage": "reconciliation", "error": str(exc)})

    await _log(db, upload, uploaded_by)
    logger.info(
        "Equity holdings ingestion complete: %d prices updated, %d clients",
        upload.rows_processed, upload.clients_affected,
    )
    return upload


async def ingest_etf_holdings_file(
    filepath: str | Path,
    uploaded_by: int,
    db: AsyncSession,
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> UploadResult:
    """
    ETF holding file ingestion pipeline:
      1. Parse ETF/MF holding report (.xlsx)
      2. Update current_price / current_value in cpp_holdings for all matched positions
      3. Log upload

    Uses the same holding_report_parser as equity holdings. The ETF holding file
    from the backoffice lists Mutual Fund / ETF positions per client. Uploading it
    populates prices for STRUCTURAL_ETF positions in the reconciliation view.
    """
    filepath = Path(filepath)
    upload = UploadResult(file_type="ETF_HOLDINGS", filename=filepath.name)

    logger.info("Starting ETF holdings ingestion: %s", filepath.name)
    try:
        from backend.services.holding_report_parser import parse_holding_report
        records = parse_holding_report(filepath)
    except Exception as exc:
        upload.errors.append({"stage": "parse", "error": str(exc)})
        logger.error("ETF holdings parse failed: %s", exc)
        await _log(db, upload, uploaded_by)
        return upload

    if not records:
        upload.errors.append({"stage": "parse", "error": "No ETF holdings found in file"})
        await _log(db, upload, uploaded_by)
        return upload

    uccs = list({r["ucc"] for r in records})
    upload.clients_affected = len(uccs)
    upload.client_codes = uccs

    try:
        updated = await _update_holdings_prices_from_report(db, records)
        await db.commit()
        upload.rows_processed = updated
        logger.info("Updated %d ETF holding prices", updated)
    except Exception as exc:
        upload.errors.append({"stage": "price_update", "error": str(exc)})
        logger.error("ETF holdings price update failed: %s", exc, exc_info=True)
        await db.rollback()

    # Persist the ETF snapshot and re-run reconciliation against the latest
    # EQUITY snapshot unioned with these ETF records, so the ETF positions
    # stop flagging as EXTRA_IN_OURS on the reconciliation page.
    try:
        from backend.services.holding_report_parser import holding_report_summary
        from backend.services.reconciliation_service import reconcile
        from backend.services.reconciliation_store import (
            load_latest_bo_holdings,
            save_bo_holdings_snapshot,
            save_reconciliation,
        )

        summary_info = holding_report_summary(records)
        market_date = summary_info.get("market_date")

        await save_bo_holdings_snapshot(db, "ETF", market_date, filepath.name, records)
        for r in records:
            r["source_bucket"] = "ETF"
        equity_records = await load_latest_bo_holdings(db, "EQUITY")
        if equity_records:
            combined = list(equity_records) + list(records)
            logger.info(
                "Reconciliation input: %d ETF records + %d equity records (from latest EQUITY snapshot)",
                len(records), len(equity_records),
            )
            reco_result = await reconcile(combined, db)
            await save_reconciliation(db, reco_result, market_date, filepath.name)
            logger.info(
                "Reconciliation saved: %d/%d clients matched",
                reco_result.total_clients_matched, reco_result.total_clients_bo,
            )
        else:
            logger.info(
                "ETF snapshot stored but reconciliation skipped — no EQUITY snapshot yet"
            )
    except Exception as exc:
        logger.warning("Reconciliation step failed (non-critical): %s", exc)
        upload.errors.append({"stage": "reconciliation", "error": str(exc)})

    await _log(db, upload, uploaded_by)
    logger.info(
        "ETF holdings ingestion complete: %d prices updated, %d clients",
        upload.rows_processed, upload.clients_affected,
    )
    return upload
