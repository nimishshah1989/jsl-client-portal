"""Stateful .xlsx parser for PMS NAV Report files.

Uses openpyxl read_only mode for memory-efficient parsing of 35MB files.
See FILE_FORMAT_SPEC.md for full format documentation.

Row types:
  1. Client name header — "FULL NAME [CODE]" in UCC column
  2. Data row — UCC matches current client code, has valid Date
  3. Grand total / subtotal — UCC is None, skip
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook

logger = logging.getLogger(__name__)

# Column indices after header row (0-based)
# Actual file has 10 columns:
# UCC, Date, Corpus, Equity Holding At Mkt, Investments in ETF,
# Cash And Cash Equivalent, Bank Balance, NAV, Liquidity %, High Water Mark
_COL_UCC = 0
_COL_DATE = 1
_COL_CORPUS = 2
_COL_EQUITY = 3
_COL_ETF = 4        # "Investments in ETF" — not in original spec
_COL_CASH = 5
_COL_BANK = 6
_COL_NAV = 7
_COL_LIQUIDITY = 8
_COL_HWM = 9

# Regex for client name header: "FULL NAME [CODE]"
_NAME_PATTERN = re.compile(r"^(.+?)\s*\[(\w+)\]$")

# Date format in NAV file: DD-MMM-YYYY e.g. "28-Sep-2020"
_DATE_FORMAT = "%d-%b-%Y"


def _safe_decimal(value: object) -> Decimal:
    """Convert a cell value to Decimal, returning Decimal('0') for non-numeric."""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _parse_nav_date(value: object) -> datetime | None:
    """Parse a NAV date cell (DD-MMM-YYYY string or datetime object)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    if not raw or raw.lower() == "nan":
        return None
    try:
        return datetime.strptime(raw, _DATE_FORMAT)
    except ValueError:
        logger.debug("Unparseable NAV date: %r", raw)
        return None


def parse_nav_file(filepath: str | Path) -> list[dict]:
    """
    Parse a PMS NAV Report .xlsx file.

    Args:
        filepath: Path to the .xlsx file.

    Returns:
        List of dicts with keys:
            client_code, client_name, date, corpus, equity_value,
            cash_value, bank_balance, nav, liquidity_pct, high_water_mark
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"NAV file not found: {filepath}")

    wb = load_workbook(str(filepath), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        wb.close()
        raise ValueError("NAV workbook has no active sheet")

    records: list[dict] = []
    current_client_code: str | None = None
    current_client_name: str | None = None
    row_count = 0
    header_skipped = False
    clients_seen: set[str] = set()

    for row in ws.iter_rows(values_only=True):
        row_count += 1

        # Skip the very first row (column headers)
        if not header_skipped:
            header_skipped = True
            continue

        # Ensure row has enough columns (10 in actual file)
        if len(row) < 8:
            continue

        ucc_raw = row[_COL_UCC]

        # Subtotal / grand total rows have None UCC — skip
        if ucc_raw is None:
            continue

        ucc = str(ucc_raw).strip()
        if not ucc or ucc.lower() == "nan":
            continue

        # Check for client name header: "FULL NAME [CODE]"
        name_match = _NAME_PATTERN.match(ucc)
        if name_match:
            current_client_name = name_match.group(1).strip()
            current_client_code = name_match.group(2).strip()
            if current_client_code not in clients_seen:
                clients_seen.add(current_client_code)
                logger.info(
                    "NAV parser: processing client %s (%s) — client #%d",
                    current_client_code,
                    current_client_name,
                    len(clients_seen),
                )
            continue

        # Data row: UCC matches current client code (with possible trailing spaces)
        if current_client_code is None:
            continue
        if ucc.rstrip() != current_client_code:
            continue

        nav_date = _parse_nav_date(row[_COL_DATE])
        if nav_date is None:
            continue

        nav_val = _safe_decimal(row[_COL_NAV])
        if nav_val == 0:
            logger.debug(
                "Skipping zero-NAV row for %s on %s",
                current_client_code,
                nav_date.date(),
            )
            continue

        records.append(
            {
                "client_code": current_client_code,
                "client_name": current_client_name,
                "date": nav_date,
                "corpus": _safe_decimal(row[_COL_CORPUS]),
                "equity_value": _safe_decimal(row[_COL_EQUITY]),
                "etf_value": _safe_decimal(row[_COL_ETF]),
                "cash_value": _safe_decimal(row[_COL_CASH]),
                "bank_balance": _safe_decimal(row[_COL_BANK]),
                "nav": nav_val,
                "liquidity_pct": _safe_decimal(row[_COL_LIQUIDITY]),
                "high_water_mark": _safe_decimal(row[_COL_HWM] if len(row) > _COL_HWM else None),
            }
        )

    wb.close()
    logger.info(
        "NAV parser complete: %d records from %d clients (%d rows scanned)",
        len(records),
        len(clients_seen),
        row_count,
    )
    return records
