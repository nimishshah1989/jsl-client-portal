"""
Database helper functions for the ingestion pipeline.

Handles client/portfolio find-or-create, NAV row upsert, benchmark alignment,
transaction insert, holdings recomputation, and upload logging.

Separated from ingestion_service.py to keep files under 400 lines.
"""

import json
import logging
from datetime import datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.benchmark_service import align_benchmark, fetch_and_align
from backend.services.holdings_service import compute_holdings
from backend.services.txn_parser import classify_sector

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


async def find_or_create_client(
    db: AsyncSession,
    client_code: str,
    client_name: str,
) -> int:
    """Find existing client by code or create a new one. Returns client_id."""
    result = await db.execute(
        text("SELECT id FROM cpp_clients WHERE client_code = :code"),
        {"code": client_code},
    )
    row = result.fetchone()
    if row:
        return row[0]

    username = client_code.lower().replace(" ", "")
    # Placeholder hash — admin must set real password via bulk-create or manual update
    placeholder_hash = "$2b$12$placeholder.hash.will.be.reset.by.admin.AAAAAAAAAAAAAAA"

    # Check if username already taken by different client
    existing = await db.execute(
        text("SELECT id FROM cpp_clients WHERE username = :uname AND client_code != :code"),
        {"uname": username, "code": client_code},
    )
    if existing.fetchone():
        username = f"{username}_{client_code.lower()}"

    result = await db.execute(
        text("""
            INSERT INTO cpp_clients (client_code, name, username, password_hash)
            VALUES (:code, :name, :username, :phash)
            ON CONFLICT (client_code) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
        """),
        {"code": client_code, "name": client_name, "username": username, "phash": placeholder_hash},
    )
    client_id = result.fetchone()[0]
    logger.info("Created client: %s (%s) id=%d", client_code, client_name, client_id)
    return client_id


async def find_or_create_portfolio(
    db: AsyncSession,
    client_id: int,
    inception_date: datetime,
    portfolio_name: str = "PMS Equity",
) -> int:
    """Find existing portfolio or create one. Returns portfolio_id."""
    result = await db.execute(
        text("SELECT id FROM cpp_portfolios WHERE client_id = :cid AND portfolio_name = :pname"),
        {"cid": client_id, "pname": portfolio_name},
    )
    row = result.fetchone()
    if row:
        return row[0]

    result = await db.execute(
        text("""
            INSERT INTO cpp_portfolios (client_id, portfolio_name, inception_date)
            VALUES (:cid, :pname, :idate)
            ON CONFLICT (client_id, portfolio_name) DO NOTHING
            RETURNING id
        """),
        {"cid": client_id, "pname": portfolio_name, "idate": inception_date.date() if hasattr(inception_date, 'hour') else inception_date},
    )
    row = result.fetchone()
    if row:
        return row[0]
    # ON CONFLICT hit — fetch existing
    result = await db.execute(
        text("SELECT id FROM cpp_portfolios WHERE client_id = :cid AND portfolio_name = :pname"),
        {"cid": client_id, "pname": portfolio_name},
    )
    return result.fetchone()[0]


_BULK_BATCH_SIZE = 500


async def upsert_nav_rows(
    db: AsyncSession,
    client_id: int,
    portfolio_id: int,
    records: list[dict],
) -> int:
    """Bulk upsert NAV records for a single client. Returns count inserted/updated.

    Uses a single INSERT ... ON CONFLICT per batch of 500 rows instead of one
    statement per row. For 1 000-row clients this reduces round-trips from 1 000
    to 2, cutting ingestion time by ~99 % for the NAV phase.
    """
    if not records:
        return 0

    # Pre-build all value placeholders and their params
    values_parts: list[str] = []
    all_params: dict = {}
    for i, rec in enumerate(records):
        nav_date = rec["date"].date() if isinstance(rec["date"], datetime) else rec["date"]
        values_parts.append(
            f"(:cid_{i}, :pid_{i}, :nd_{i}, :nv_{i}, :ia_{i}, :cv_{i},"
            f" :cp_{i}, :etf_{i}, :cash_{i}, :bank_{i})"
        )
        all_params.update({
            f"cid_{i}": client_id,
            f"pid_{i}": portfolio_id,
            f"nd_{i}": nav_date,
            f"nv_{i}": rec["nav"],
            f"ia_{i}": rec["corpus"],
            f"cv_{i}": rec["nav"],
            f"cp_{i}": rec["liquidity_pct"],
            f"etf_{i}": rec.get("etf_value", _ZERO),
            f"cash_{i}": rec.get("cash_value", _ZERO),
            f"bank_{i}": rec.get("bank_balance", _ZERO),
        })

    count = 0
    for start in range(0, len(records), _BULK_BATCH_SIZE):
        end = min(start + _BULK_BATCH_SIZE, len(records))
        batch_values = values_parts[start:end]

        # Collect only the params used by this batch
        batch_params: dict = {}
        for i in range(start, end):
            for key in (
                f"cid_{i}", f"pid_{i}", f"nd_{i}", f"nv_{i}", f"ia_{i}",
                f"cv_{i}", f"cp_{i}", f"etf_{i}", f"cash_{i}", f"bank_{i}",
            ):
                batch_params[key] = all_params[key]

        sql = text(f"""
            INSERT INTO cpp_nav_series
                (client_id, portfolio_id, nav_date, nav_value, invested_amount,
                 current_value, cash_pct, etf_value, cash_value, bank_balance)
            VALUES {', '.join(batch_values)}
            ON CONFLICT (client_id, portfolio_id, nav_date)
            DO UPDATE SET
                nav_value       = EXCLUDED.nav_value,
                invested_amount = EXCLUDED.invested_amount,
                current_value   = EXCLUDED.current_value,
                cash_pct        = EXCLUDED.cash_pct,
                etf_value       = EXCLUDED.etf_value,
                cash_value      = EXCLUDED.cash_value,
                bank_balance    = EXCLUDED.bank_balance
        """)
        await db.execute(sql, batch_params)
        count += end - start

    return count


async def update_benchmark_values(
    db: AsyncSession,
    client_id: int,
    portfolio_id: int,
    benchmark_data: "pd.DataFrame | None" = None,
) -> int:
    """Bulk-update benchmark_value in cpp_nav_series for a single client.

    Parameters
    ----------
    benchmark_data:
        Pre-fetched Nifty DataFrame (from ``fetch_nifty_data``).  If supplied
        the function calls ``align_benchmark`` locally and skips yfinance.
        If None, falls back to ``fetch_and_align`` (backward-compatible).

    Uses a single ``UPDATE … FROM (VALUES …)`` per batch of 500 dates instead
    of one UPDATE statement per date, reducing round-trips by ~99 %.
    """
    result = await db.execute(
        text("""
            SELECT nav_date FROM cpp_nav_series
            WHERE client_id = :cid AND portfolio_id = :pid
            ORDER BY nav_date ASC
        """),
        {"cid": client_id, "pid": portfolio_id},
    )
    dates = [row[0] for row in result.fetchall()]
    if len(dates) < 2:
        return 0

    nav_dates = pd.DatetimeIndex(dates)
    try:
        if benchmark_data is not None:
            benchmark = align_benchmark(nav_dates, benchmark_data)
        else:
            benchmark = fetch_and_align(nav_dates)
    except RuntimeError as exc:
        logger.error("Failed to align benchmark data: %s", exc)
        return 0

    if benchmark is None or len(benchmark) == 0:
        return 0

    # Pre-build all (date, value) pairs
    pairs: list[tuple] = []
    for dt, val in benchmark.items():
        nav_date = dt.date() if hasattr(dt, "date") else dt
        pairs.append((nav_date, Decimal(str(float(val)))))

    count = 0
    for start in range(0, len(pairs), _BULK_BATCH_SIZE):
        batch = pairs[start : start + _BULK_BATCH_SIZE]
        values_parts: list[str] = []
        batch_params: dict = {"cid": client_id, "pid": portfolio_id}
        for i, (nav_date, bv) in enumerate(batch):
            values_parts.append(f"(CAST(:d_{i} AS date), CAST(:v_{i} AS numeric))")
            batch_params[f"d_{i}"] = nav_date
            batch_params[f"v_{i}"] = bv

        sql = text(f"""
            UPDATE cpp_nav_series AS ns
            SET benchmark_value = v.bv
            FROM (VALUES {', '.join(values_parts)}) AS v(nd, bv)
            WHERE ns.client_id = :cid
              AND ns.portfolio_id = :pid
              AND ns.nav_date = v.nd
        """)
        await db.execute(sql, batch_params)
        count += len(batch)

    return count


async def upsert_transactions(
    db: AsyncSession,
    client_id: int,
    portfolio_id: int,
    records: list[dict],
) -> int:
    """Bulk insert transaction records (including ISIN). Returns count."""
    if not records:
        return 0

    # Deduplicate by unique constraint key before batching.
    # Prevents PostgreSQL "ON CONFLICT DO UPDATE command cannot affect row a
    # second time" error if the source file ever contains duplicate rows.
    seen_keys: set[tuple] = set()
    deduped: list[dict] = []
    for rec in records:
        txn_date = rec["date"].date() if isinstance(rec["date"], datetime) else rec["date"]
        key = (
            txn_date,
            rec["txn_type"],
            rec["symbol"],
            rec.get("quantity"),
            rec.get("price"),
            rec.get("settlement_no", ""),
        )
        if key in seen_keys:
            logger.warning(
                "Dedup: dropping duplicate txn client_id=%d %s %s %s qty=%s @ %s stno=%s",
                client_id, txn_date, rec["txn_type"], rec["symbol"],
                rec.get("quantity"), rec.get("price"), rec.get("settlement_no"),
            )
        else:
            seen_keys.add(key)
            deduped.append(rec)
    records = deduped

    count = 0
    for start in range(0, len(records), _BULK_BATCH_SIZE):
        batch = records[start : start + _BULK_BATCH_SIZE]
        values_parts: list[str] = []
        params: dict = {}

        for i, rec in enumerate(batch):
            idx = f"{start + i}"
            txn_date = rec["date"].date() if isinstance(rec["date"], datetime) else rec["date"]
            isin_val = rec.get("isin", "") or ""
            values_parts.append(
                f"(:cid_{idx}, :pid_{idx}, :td_{idx}, :tt_{idx}, :sym_{idx}, :isin_{idx},"
                f" :an_{idx}, :ac_{idx}, :it_{idx}, :ex_{idx},"
                f" :sn_{idx}, :qty_{idx}, :pr_{idx}, :cr_{idx}, :amt_{idx})"
            )
            params[f"cid_{idx}"] = client_id
            params[f"pid_{idx}"] = portfolio_id
            params[f"td_{idx}"] = txn_date
            params[f"tt_{idx}"] = rec["txn_type"]
            params[f"sym_{idx}"] = rec["symbol"]
            params[f"isin_{idx}"] = isin_val if isin_val else None
            params[f"an_{idx}"] = rec["symbol"]
            params[f"ac_{idx}"] = rec["asset_class"]
            params[f"it_{idx}"] = rec.get("instrument_type", "EQ")
            params[f"ex_{idx}"] = rec.get("exchange", "")
            params[f"sn_{idx}"] = rec.get("settlement_no", "")
            params[f"qty_{idx}"] = rec["quantity"]
            params[f"pr_{idx}"] = rec["price"]
            params[f"cr_{idx}"] = rec.get("cost_rate", _ZERO)
            params[f"amt_{idx}"] = rec["amount"]

        sql = text(f"""
            INSERT INTO cpp_transactions
                (client_id, portfolio_id, txn_date, txn_type, symbol, isin,
                 asset_name, asset_class, instrument_type, exchange,
                 settlement_no, quantity, price, cost_rate, amount)
            VALUES {', '.join(values_parts)}
            ON CONFLICT (client_id, portfolio_id, txn_date, txn_type, symbol,
                         quantity, price, settlement_no)
            DO UPDATE SET
                isin = COALESCE(EXCLUDED.isin, cpp_transactions.isin)
        """)
        try:
            await db.execute(sql, params)
        except Exception as exc:
            first = batch[0]
            last = batch[-1]
            first_date = first["date"].date() if isinstance(first["date"], datetime) else first["date"]
            last_date = last["date"].date() if isinstance(last["date"], datetime) else last["date"]
            logger.error(
                "Batch execute failed: client_id=%d batch=%d/%d rows=%d dates=[%s..%s] error=%s",
                client_id,
                start // _BULK_BATCH_SIZE + 1,
                (len(records) + _BULK_BATCH_SIZE - 1) // _BULK_BATCH_SIZE,
                len(batch),
                first_date,
                last_date,
                exc,
            )
            raise
        count += len(batch)

    return count


async def recompute_holdings(
    db: AsyncSession,
    client_id: int,
    portfolio_id: int,
) -> int:
    """Recompute holdings from transactions using FIFO and upsert to cpp_holdings.

    Fetches ISIN from transactions so holdings are keyed by both symbol and ISIN,
    enabling ISIN-based reconciliation against the backoffice holding report.
    """
    result = await db.execute(
        text("""
            SELECT symbol, isin, txn_type, quantity, price, amount, asset_class, txn_date
            FROM cpp_transactions
            WHERE client_id = :cid AND portfolio_id = :pid
            ORDER BY txn_date ASC
        """),
        {"cid": client_id, "pid": portfolio_id},
    )
    rows = result.fetchall()
    if not rows:
        return 0

    txn_df = pd.DataFrame(rows, columns=[
        "symbol", "isin", "txn_type", "quantity", "price", "amount", "asset_class", "date",
    ])
    holdings_df = compute_holdings(txn_df)
    if holdings_df.empty:
        return 0

    # Preserve existing sector mappings before deleting holdings
    existing_sectors: dict[str, str] = {}
    sector_result = await db.execute(
        text("""
            SELECT symbol, sector FROM cpp_holdings
            WHERE client_id = :cid AND portfolio_id = :pid AND sector IS NOT NULL AND sector != ''
        """),
        {"cid": client_id, "pid": portfolio_id},
    )
    for row in sector_result.fetchall():
        existing_sectors[row[0]] = row[1]

    await db.execute(
        text("DELETE FROM cpp_holdings WHERE client_id = :cid AND portfolio_id = :pid"),
        {"cid": client_id, "pid": portfolio_id},
    )

    count = 0
    for _, h in holdings_df.iterrows():
        symbol = h["symbol"]
        isin_val = h.get("isin", "") or ""
        # Sector priority: known ETF/LIQUID mapping → existing DB sector → None
        sector = classify_sector(symbol) or existing_sectors.get(symbol) or None
        await db.execute(
            text("""
                INSERT INTO cpp_holdings
                    (client_id, portfolio_id, symbol, isin, asset_class, sector, quantity,
                     avg_cost, current_price, current_value, unrealized_pnl, weight_pct)
                VALUES (:cid, :pid, :sym, :isin, :ac, :sec, :qty, :avgc, :cp, :cv, :pnl, :wt)
            """),
            {
                "cid": client_id,
                "pid": portfolio_id,
                "sym": symbol,
                "isin": isin_val if isin_val else None,
                "ac": h["asset_class"],
                "sec": sector,
                "qty": h["quantity"],
                "avgc": h["avg_cost"],
                "cp": h["current_price"],
                "cv": h["current_value"],
                "pnl": h["unrealized_pnl"],
                "wt": h["weight_pct"],
            },
        )
        count += 1
    return count


async def upsert_cash_flows(
    db: AsyncSession,
    client_id: int,
    portfolio_id: int,
    records: list[dict],
) -> int:
    """Upsert cash flow records for a single client. Returns count."""
    if not records:
        return 0

    count = 0
    for rec in records:
        flow_date = rec["date"]
        await db.execute(
            text("""
                INSERT INTO cpp_cash_flows
                    (client_id, portfolio_id, flow_date, flow_type, amount,
                     description, source_ucc)
                VALUES (:cid, :pid, :fd, :ft, :amt, :desc, :ucc)
                ON CONFLICT (client_id, portfolio_id, flow_date, flow_type, amount)
                DO UPDATE SET
                    description = EXCLUDED.description,
                    source_ucc = EXCLUDED.source_ucc
            """),
            {
                "cid": client_id,
                "pid": portfolio_id,
                "fd": flow_date,
                "ft": rec["flow_type"],
                "amt": rec["amount"],
                "desc": rec.get("description", ""),
                "ucc": rec.get("client_code", ""),
            },
        )
        count += 1
    return count


async def log_upload(
    db: AsyncSession,
    file_type: str,
    filename: str,
    rows_processed: int,
    rows_failed: int,
    clients_affected: int,
    errors: list[dict],
    uploaded_by: int,
) -> None:
    """Write upload summary to cpp_upload_log."""
    try:
        await db.execute(
            text("""
                INSERT INTO cpp_upload_log
                    (uploaded_by, file_type, filename, rows_processed,
                     rows_failed, clients_affected, errors)
                VALUES (:ub, :ft, :fn, :rp, :rf, :ca, CAST(:err AS jsonb))
            """),
            {
                "ub": uploaded_by,
                "ft": file_type,
                "fn": filename,
                "rp": rows_processed,
                "rf": rows_failed,
                "ca": clients_affected,
                "err": json.dumps(errors),
            },
        )
    except Exception as exc:
        logger.error("Failed to log upload: %s", exc)
