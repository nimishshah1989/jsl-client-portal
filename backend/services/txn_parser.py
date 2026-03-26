"""Stateful .xlsx parser for PMS Transaction Report files.

Uses openpyxl read_only mode for memory-efficient parsing of 35MB files.
See FILE_FORMAT_SPEC.md for full format documentation.

Row types:
  0. Sub-header row — skip
  1. Client name header — "FULL NAME [CODE]"
  2. Date separator — "     Date :DD/MM/YY"
  3. Transaction data — UCC = client code, Script present
  4. Daily subtotal — UCC is None, skip
  5. Grand total — UCC is None, skip
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook

logger = logging.getLogger(__name__)

# Column indices (0-based, 20 columns total)
_COL_UCC = 0
_COL_SCRIPT = 1
_COL_EXCH = 2
_COL_STNO = 3
# Buy side: 4-11
_COL_BUY_QTY = 4
_COL_BUY_RATE = 5
_COL_BUY_COST_RATE = 9
_COL_BUY_AMOUNT = 10
# Sale side: 12-19
_COL_SALE_QTY = 12
_COL_SALE_RATE = 13
_COL_SALE_COST_RATE = 17
_COL_SALE_AMOUNT = 18

# Regex patterns
_NAME_PATTERN = re.compile(r"^(.+?)\s*\[(\w+)\]$")
_DATE_PATTERN = re.compile(r"Date\s*:\s*(\d{2}/\d{2}/\d{2})")

# Sector mapping for instruments that can't be inferred from name alone.
# Anything containing "LIQUID" (case-insensitive) → "Cash"
# Gold/silver ETFs → "Metals"
# ETF-style instruments → their underlying sector
SYMBOL_SECTOR_MAP: dict[str, str] = {
    "GOLDBEES": "Metals",
    "GOLDCASE": "Metals",
    "GOLDSHARE": "Metals",
    "GOLDETF": "Metals",
    "SILVERBEES": "Metals",
    "SILVERETF": "Metals",
    "SILVERSHARE": "Metals",
    "GOLDHERA": "Metals",
    "GOLDPETAL": "Metals",
    "BANKBEES": "Banking",
    "PSUBNKBEES": "Banking",
    "NIFTYBEES": "Diversified",
    "JUNIORBEES": "Diversified",
    "CPSEETF": "Diversified",
    "PHARMABEES": "Pharma",
    "FMCGIETF": "FMCG",
    "HNGSNGBEES": "Diversified",
}


def classify_sector(symbol: str) -> str:
    """Determine sector from symbol name.

    - Any symbol containing 'liquid' (case-insensitive) → 'Cash'
    - Known ETFs/commodities → mapped sector
    - Everything else → empty string (filled during holdings ingestion from DB)
    """
    if "LIQUID" in symbol.upper():
        return "Cash"
    return SYMBOL_SECTOR_MAP.get(symbol, "")


def _safe_decimal(value: object) -> Decimal:
    """Convert a cell value to Decimal, returning Decimal('0') for non-numeric."""
    if value is None:
        return Decimal("0")
    try:
        d = Decimal(str(value))
        # openpyxl may yield NaN for blank cells in some edge cases
        if d.is_nan():
            return Decimal("0")
        return d
    except (InvalidOperation, ValueError):
        return Decimal("0")


def parse_script(script_raw: str) -> tuple[str, str]:
    """
    Parse script field like "RELIANCE     EQ" into (symbol, instrument_type).

    Returns:
        Tuple of (symbol, instrument_type). Defaults instrument to "EQ".
    """
    parts = script_raw.strip().split()
    symbol = parts[0].strip() if parts else script_raw.strip()
    instrument = parts[-1].strip() if len(parts) > 1 else "EQ"
    return symbol, instrument


def _determine_txn_type_buy(stno: str) -> str:
    """Determine transaction type for buy-side entry."""
    if stno.upper() == "BONUS":
        return "BONUS"
    return "BUY"


def _determine_txn_type_sell(stno: str) -> str:
    """Determine transaction type for sell-side entry."""
    if stno.lower() == "corpus":
        return "CORPUS_IN"
    return "SELL"


def parse_transaction_file(filepath: str | Path) -> list[dict]:
    """
    Parse a PMS Transaction Report .xlsx file.

    Args:
        filepath: Path to the .xlsx file.

    Returns:
        List of dicts with keys:
            client_code, client_name, date, txn_type, symbol,
            instrument_type, exchange, settlement_no, quantity,
            price, cost_rate, amount, asset_class
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Transaction file not found: {filepath}")

    wb = load_workbook(str(filepath), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        wb.close()
        raise ValueError("Transaction workbook has no active sheet")

    records: list[dict] = []
    current_client_code: str | None = None
    current_client_name: str | None = None
    current_date: datetime | None = None
    row_count = 0
    header_skipped = False
    clients_seen: set[str] = set()

    for row in ws.iter_rows(values_only=True):
        row_count += 1

        # Skip the first row (sub-header / column names)
        if not header_skipped:
            header_skipped = True
            continue

        # Pad row to 20 columns to avoid index errors
        cells = list(row) + [None] * max(0, 20 - len(row))

        ucc_raw = cells[_COL_UCC]

        # Subtotal / grand total rows — UCC is None
        if ucc_raw is None:
            continue

        ucc = str(ucc_raw).strip()
        if not ucc or ucc.lower() == "nan":
            continue

        # Type 1: Client name header — "FULL NAME [CODE]"
        name_match = _NAME_PATTERN.match(ucc)
        if name_match:
            current_client_name = name_match.group(1).strip()
            current_client_code = name_match.group(2).strip()
            current_date = None  # Reset date for new client
            if current_client_code not in clients_seen:
                clients_seen.add(current_client_code)
                logger.info(
                    "TXN parser: processing client %s (%s) — client #%d",
                    current_client_code,
                    current_client_name,
                    len(clients_seen),
                )
            continue

        # Type 2: Date separator — "     Date :DD/MM/YY"
        date_match = _DATE_PATTERN.search(ucc)
        if date_match:
            try:
                current_date = datetime.strptime(date_match.group(1), "%d/%m/%y")
            except ValueError:
                logger.warning("Unparseable date separator: %r", ucc)
            continue

        # Type 3: Transaction data — UCC matches client code and Script is present
        if current_client_code is None or current_date is None:
            continue
        if ucc.rstrip() != current_client_code:
            continue

        script_raw = cells[_COL_SCRIPT]
        if script_raw is None:
            continue
        script_str = str(script_raw).strip()
        if not script_str or script_str.lower() == "nan":
            continue

        symbol, inst_type = parse_script(script_str)
        stno = str(cells[_COL_STNO]).strip() if cells[_COL_STNO] is not None else ""
        exchange = str(cells[_COL_EXCH]).strip() if cells[_COL_EXCH] is not None else ""
        asset_class = "CASH" if "LIQUID" in symbol.upper() else "EQUITY"
        sector = classify_sector(symbol)

        buy_qty = _safe_decimal(cells[_COL_BUY_QTY])
        sale_qty = _safe_decimal(cells[_COL_SALE_QTY])

        # A single row can have BOTH buy and sell — check independently
        if buy_qty > 0:
            records.append(
                {
                    "client_code": current_client_code,
                    "client_name": current_client_name,
                    "date": current_date,
                    "txn_type": _determine_txn_type_buy(stno),
                    "symbol": symbol,
                    "instrument_type": inst_type,
                    "exchange": exchange,
                    "settlement_no": stno,
                    "quantity": _safe_decimal(cells[_COL_BUY_QTY]),
                    "price": _safe_decimal(cells[_COL_BUY_RATE]),
                    "cost_rate": _safe_decimal(cells[_COL_BUY_COST_RATE]),
                    "amount": _safe_decimal(cells[_COL_BUY_AMOUNT]),
                    "asset_class": asset_class,
                    "sector": sector,
                }
            )

        if sale_qty > 0:
            records.append(
                {
                    "client_code": current_client_code,
                    "client_name": current_client_name,
                    "date": current_date,
                    "txn_type": _determine_txn_type_sell(stno),
                    "symbol": symbol,
                    "instrument_type": inst_type,
                    "exchange": exchange,
                    "settlement_no": stno,
                    "quantity": _safe_decimal(cells[_COL_SALE_QTY]),
                    "price": _safe_decimal(cells[_COL_SALE_RATE]),
                    "cost_rate": _safe_decimal(cells[_COL_SALE_COST_RATE]),
                    "amount": _safe_decimal(cells[_COL_SALE_AMOUNT]),
                    "asset_class": asset_class,
                    "sector": sector,
                }
            )

    wb.close()
    logger.info(
        "TXN parser complete: %d records from %d clients (%d rows scanned)",
        len(records),
        len(clients_seen),
        row_count,
    )
    return records
