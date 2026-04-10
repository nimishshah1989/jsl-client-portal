"""Stateful .xlsx parser for PMS Holding Report files.

Uses openpyxl read_only mode for memory-efficient parsing.

Column layout (0-based indices, row 0 = headers):
  0:  UCC              — client code e.g. "ML08PASS  " (trailing whitespace)
  1:  Family Group     — portfolio name e.g. "Passive Portfolio"
  2:  Share (PMS)      — symbol with instrument suffix e.g. "CPSEETF EQ      "
  3:  ISIN             — e.g. "INF457M01133"
  4:  Stock (qty)      — integer quantity
  5:  Cost (Rs.)       — per-share average cost
  6:  Total Cost       — total cost basis
  7:  % Holding Cost   — portfolio weight by cost
  8:  % Holding Cost Cumul
  9:  Market Rate      — current market price
  10: Market Rate Date — date string "DD/MM/YYYY"
  11: Market Value (Rs.) — current market value
  12: Notional P/L     — unrealized P&L
  13: ROI [%]          — return on investment percentage
  14: % Holding Market — portfolio weight by market value
  15: % Cumul          — cumulative weight
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

logger = logging.getLogger(__name__)

# Column indices (0-based)
_COL_UCC = 0
_COL_FAMILY_GROUP = 1
_COL_SHARE = 2
_COL_ISIN = 3
_COL_QTY = 4
_COL_AVG_COST = 5
_COL_TOTAL_COST = 6
_COL_HOLDING_COST_PCT = 7
_COL_MARKET_PRICE = 9
_COL_MARKET_DATE = 10
_COL_MARKET_VALUE = 11
_COL_NOTIONAL_PNL = 12
_COL_ROI_PCT = 13
_COL_HOLDING_MARKET_PCT = 14

_MIN_COLUMNS = 15  # Minimum columns a valid data row must have

# Date format used in Market Rate Date column
_MARKET_DATE_FORMAT = "%d/%m/%Y"


def _safe_decimal(value: Any) -> Decimal | None:
    """Convert a cell value to Decimal.

    Returns None for None/empty values so callers can distinguish
    missing data from zero — critical for financial integrity.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw.lower() in ("nan", "none", "-", ""):
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        logger.debug("Non-numeric cell value: %r", raw)
        return None


def _parse_market_date(value: Any) -> date | None:
    """Parse the Market Rate Date cell.

    Accepts:
      - Python date/datetime objects (openpyxl may return these)
      - String in DD/MM/YYYY format
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw or raw.lower() in ("nan", "none"):
        return None
    try:
        return datetime.strptime(raw, _MARKET_DATE_FORMAT).date()
    except ValueError:
        logger.debug("Unparseable market date: %r", raw)
        return None


def _parse_share(raw: str) -> tuple[str, str]:
    """Extract symbol and instrument type from a Share (PMS) cell.

    Example: "CPSEETF EQ                    " → ("CPSEETF", "EQ")
    Example: "GLENMARK EQ                   " → ("GLENMARK", "EQ")
    Example: "LIQUIDCASE EQ                 " → ("LIQUIDCASE", "EQ")

    Returns:
        (symbol, instrument_type) — both uppercase.
        instrument_type is empty string if not present.
    """
    stripped = raw.strip()
    parts = stripped.split()
    if not parts:
        return ("", "")
    symbol = parts[0].upper()
    instrument_type = parts[1].upper() if len(parts) > 1 else ""
    return symbol, instrument_type


def _is_data_row(row: tuple[Any, ...]) -> bool:
    """Return True if this row looks like a holding data row.

    A valid data row has:
      - A non-empty UCC (col 0)
      - A non-empty Share/symbol (col 2)
      - A numeric quantity (col 4)
    Subtotal, header, and empty rows fail these checks.
    """
    if len(row) < _MIN_COLUMNS:
        return False
    ucc_raw = row[_COL_UCC]
    share_raw = row[_COL_SHARE]
    qty_raw = row[_COL_QTY]

    if ucc_raw is None or share_raw is None or qty_raw is None:
        return False

    ucc = str(ucc_raw).strip()
    share = str(share_raw).strip()
    if not ucc or not share:
        return False

    # Quantity must be numeric
    try:
        float(str(qty_raw).replace(",", ""))
    except ValueError:
        return False

    return True


def parse_holding_report(filepath: str | Path) -> list[dict]:
    """Parse a PMS Holding Report .xlsx file.

    Args:
        filepath: Path to the .xlsx file.

    Returns:
        List of dicts, one per holding row, with keys:
            ucc, family_group, symbol, share_raw, isin, instrument_type,
            quantity, avg_cost, total_cost, holding_cost_pct,
            market_price, market_date, market_value,
            notional_pnl, roi_pct, holding_market_pct

        Financial fields are Decimal | None.
        market_date is date | None.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the workbook has no active sheet.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Holding report file not found: {filepath}")

    wb = load_workbook(str(filepath), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        wb.close()
        raise ValueError("Holding report workbook has no active sheet")

    records: list[dict] = []
    row_count = 0
    skipped_count = 0
    header_skipped = False
    ucc_row_counts: dict[str, int] = {}

    for row in ws.iter_rows(values_only=True):
        row_count += 1

        # Skip the header row (row 0 in the file = row 1 in iter_rows)
        if not header_skipped:
            header_skipped = True
            continue

        if not _is_data_row(row):
            skipped_count += 1
            continue

        ucc = str(row[_COL_UCC]).strip()
        family_group = str(row[_COL_FAMILY_GROUP]).strip() if row[_COL_FAMILY_GROUP] is not None else ""
        share_raw_cell = str(row[_COL_SHARE]).strip() if row[_COL_SHARE] is not None else ""
        isin = str(row[_COL_ISIN]).strip() if row[_COL_ISIN] is not None else ""

        symbol, instrument_type = _parse_share(share_raw_cell)
        if not symbol:
            logger.debug("Row %d: empty symbol after parse, skipping", row_count)
            skipped_count += 1
            continue

        market_date = _parse_market_date(row[_COL_MARKET_DATE])

        quantity = _safe_decimal(row[_COL_QTY])
        avg_cost = _safe_decimal(row[_COL_AVG_COST])
        total_cost = _safe_decimal(row[_COL_TOTAL_COST])
        holding_cost_pct = _safe_decimal(row[_COL_HOLDING_COST_PCT])
        market_price = _safe_decimal(row[_COL_MARKET_PRICE])
        market_value = _safe_decimal(row[_COL_MARKET_VALUE])
        notional_pnl = _safe_decimal(row[_COL_NOTIONAL_PNL])
        roi_pct = _safe_decimal(row[_COL_ROI_PCT])
        holding_market_pct = _safe_decimal(row[_COL_HOLDING_MARKET_PCT])

        records.append(
            {
                "ucc": ucc,
                "family_group": family_group,
                "symbol": symbol,
                "share_raw": share_raw_cell,
                "isin": isin,
                "instrument_type": instrument_type,
                "quantity": quantity,
                "avg_cost": avg_cost,
                "total_cost": total_cost,
                "holding_cost_pct": holding_cost_pct,
                "market_price": market_price,
                "market_date": market_date,
                "market_value": market_value,
                "notional_pnl": notional_pnl,
                "roi_pct": roi_pct,
                "holding_market_pct": holding_market_pct,
            }
        )

        ucc_row_counts[ucc] = ucc_row_counts.get(ucc, 0) + 1

    wb.close()

    for ucc, count in sorted(ucc_row_counts.items()):
        logger.info("Holding parser: UCC %s — %d holding rows", ucc, count)

    logger.info(
        "Holding parser complete: %d records from %d UCCs (%d rows scanned, %d skipped)",
        len(records),
        len(ucc_row_counts),
        row_count,
        skipped_count,
    )
    return records


def holding_report_summary(records: list[dict]) -> dict:
    """Return summary statistics for a parsed holding report.

    Args:
        records: Output of parse_holding_report().

    Returns:
        Dict with keys:
            total_rows:      int — number of holding records
            unique_uccs:     int — number of distinct client codes
            unique_symbols:  int — number of distinct stock symbols
            market_date:     date | None — most common market date across all rows
            uccs:            list[str] — sorted list of UCC codes
    """
    if not records:
        return {
            "total_rows": 0,
            "unique_uccs": 0,
            "unique_symbols": 0,
            "market_date": None,
            "uccs": [],
        }

    unique_uccs: set[str] = set()
    unique_symbols: set[str] = set()
    date_counts: dict[date, int] = {}

    for rec in records:
        unique_uccs.add(rec["ucc"])
        unique_symbols.add(rec["symbol"])
        mdate = rec.get("market_date")
        if mdate is not None:
            date_counts[mdate] = date_counts.get(mdate, 0) + 1

    # Most common market date (typically all rows share the same date)
    market_date: date | None = max(date_counts, key=lambda d: date_counts[d]) if date_counts else None

    return {
        "total_rows": len(records),
        "unique_uccs": len(unique_uccs),
        "unique_symbols": len(unique_symbols),
        "market_date": market_date,
        "uccs": sorted(unique_uccs),
    }
