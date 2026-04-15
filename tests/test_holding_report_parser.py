"""Tests for PMS Holding Report parser — helpers, row detection, and summary."""

from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import openpyxl
import pytest

from backend.services.holding_report_parser import (
    _is_data_row,
    _parse_market_date,
    _parse_share,
    _safe_decimal,
    holding_report_summary,
    parse_holding_report,
)


# ── _safe_decimal ──


class TestSafeDecimal:
    def test_integer(self):
        assert _safe_decimal(757) == Decimal("757")

    def test_float_via_str(self):
        # str() path avoids float rounding
        assert _safe_decimal(99.3033) == Decimal("99.3033")

    def test_string_number(self):
        assert _safe_decimal("102.4") == Decimal("102.4")

    def test_negative(self):
        assert _safe_decimal(-591) == Decimal("-591")

    def test_negative_string(self):
        assert _safe_decimal("-2.22") == Decimal("-2.22")

    def test_none_returns_none(self):
        assert _safe_decimal(None) is None

    def test_empty_string_returns_none(self):
        assert _safe_decimal("") is None

    def test_dash_returns_none(self):
        assert _safe_decimal("-") is None

    def test_nan_returns_none(self):
        assert _safe_decimal("nan") is None

    def test_non_numeric_returns_none(self):
        assert _safe_decimal("N/A") is None

    def test_zero(self):
        assert _safe_decimal(0) == Decimal("0")

    def test_large_value(self):
        assert _safe_decimal("319139.365") == Decimal("319139.365")


# ── _parse_market_date ──


class TestParseMarketDate:
    def test_string_ddmmyyyy(self):
        assert _parse_market_date("08/04/2026") == date(2026, 4, 8)

    def test_date_passthrough(self):
        d = date(2026, 4, 8)
        assert _parse_market_date(d) == d

    def test_datetime_passthrough(self):
        from datetime import datetime
        dt = datetime(2026, 4, 8, 10, 30)
        assert _parse_market_date(dt) == date(2026, 4, 8)

    def test_none_returns_none(self):
        assert _parse_market_date(None) is None

    def test_nan_returns_none(self):
        assert _parse_market_date("nan") is None

    def test_empty_returns_none(self):
        assert _parse_market_date("") is None

    def test_wrong_format_returns_none(self):
        # YYYY-MM-DD is not the expected DD/MM/YYYY format
        assert _parse_market_date("2026-04-08") is None

    def test_first_of_month(self):
        assert _parse_market_date("01/01/2025") == date(2025, 1, 1)

    def test_end_of_month(self):
        assert _parse_market_date("31/12/2024") == date(2024, 12, 31)


# ── _parse_share ──


class TestParseShare:
    def test_standard_equity(self):
        symbol, instrument_type = _parse_share("CPSEETF EQ                    ")
        assert symbol == "CPSEETF"
        assert instrument_type == "EQ"

    def test_glenmark(self):
        symbol, instrument_type = _parse_share("GLENMARK EQ                   ")
        assert symbol == "GLENMARK"
        assert instrument_type == "EQ"

    def test_liquidcase(self):
        symbol, instrument_type = _parse_share("LIQUIDCASE EQ                 ")
        assert symbol == "LIQUIDCASE"
        assert instrument_type == "EQ"

    def test_no_instrument_type(self):
        symbol, instrument_type = _parse_share("RELIANCE")
        assert symbol == "RELIANCE"
        assert instrument_type == ""

    def test_uppercase_enforced(self):
        symbol, instrument_type = _parse_share("reliance eq")
        assert symbol == "RELIANCE"
        assert instrument_type == "EQ"

    def test_empty_string(self):
        symbol, instrument_type = _parse_share("  ")
        assert symbol == ""
        assert instrument_type == ""

    def test_only_whitespace(self):
        symbol, instrument_type = _parse_share("   ")
        assert symbol == ""
        assert instrument_type == ""


# ── _is_data_row ──


class TestIsDataRow:
    def _make_row(self, ucc="ML08PASS  ", family="Passive Portfolio",
                  share="CPSEETF EQ  ", isin="INF457M01133", qty=757,
                  avg_cost=99.3033, total_cost=75172.61,
                  holding_cost_pct=23.84, _col8=23.84,
                  market_price=102.4, market_date="08/04/2026",
                  market_value=77516.8, notional_pnl=2344.19,
                  roi_pct=3.12, holding_mkt_pct=23.83, pct_cumul=23.83):
        return (ucc, family, share, isin, qty, avg_cost, total_cost,
                holding_cost_pct, _col8, market_price, market_date,
                market_value, notional_pnl, roi_pct, holding_mkt_pct, pct_cumul)

    def test_valid_row(self):
        assert _is_data_row(self._make_row()) is True

    def test_none_ucc(self):
        row = self._make_row(ucc=None)
        assert _is_data_row(row) is False

    def test_none_share(self):
        row = self._make_row(share=None)
        assert _is_data_row(row) is False

    def test_none_qty(self):
        row = self._make_row(qty=None)
        assert _is_data_row(row) is False

    def test_too_short(self):
        assert _is_data_row(("ML08PASS", "Passive", "CPSEETF EQ")) is False

    def test_non_numeric_qty(self):
        row = self._make_row(qty="Total")
        assert _is_data_row(row) is False

    def test_empty_ucc(self):
        row = self._make_row(ucc="   ")
        assert _is_data_row(row) is False

    def test_empty_share(self):
        row = self._make_row(share="   ")
        assert _is_data_row(row) is False

    def test_negative_qty(self):
        # Negative quantities are numerically valid — should pass
        assert _is_data_row(self._make_row(qty=-10)) is True

    def test_zero_qty(self):
        # Zero is a valid numeric quantity
        assert _is_data_row(self._make_row(qty=0)) is True


# ── parse_holding_report integration (in-memory workbook) ──


def _build_xlsx(rows: list[tuple]) -> BytesIO:
    """Create an in-memory .xlsx file with given rows (row 0 = headers)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(list(row))
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class TestParseHoldingReport:
    HEADERS = (
        "UCC", "Family Group", "Share (PMS)", "ISIN",
        "Stock (qty)", "Cost (Rs.)", "Total Cost",
        "% Holding Cost", "% Holding Cost Cumul",
        "Market Rate", "Market Rate Date", "Market Value (Rs.)",
        "Notional P/L", "ROI [%]", "% Holding Market", "% Cumul",
    )

    ROW_1 = (
        "ML08PASS  ", "Passive Portfolio", "CPSEETF EQ                    ",
        "INF457M01133", 757, 99.3033, 75172.61, 23.8433, 23.84,
        102.4, "08/04/2026", 77516.8, 2344.19, 3.12, 23.83, 23.83,
    )
    ROW_2 = (
        "AT72      ", "Momentum Leaders", "GLENMARK EQ                   ",
        "INE935A01035", 12, 2222.75, 26673, 4.8381, 4.84,
        2173.5, "08/04/2026", 26082, -591, -2.22, 4.57, 4.57,
    )
    ROW_3 = (
        "AT72      ", "Momentum Leaders", "LIQUIDCASE EQ                 ",
        "INF0R8F01034", 2815, 113.371, 319139.365, 57.89, 76.04,
        113.52, "08/04/2026", 319558.8, 419.435, 0.13, 55.97, 76.66,
    )

    def _parse_bytes(self, rows: list[tuple]) -> list[dict]:
        """Write rows to a temp .xlsx file and parse it."""
        import tempfile, os
        buf = _build_xlsx(rows)
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(buf.read())
            tmp_path = f.name
        try:
            return parse_holding_report(tmp_path)
        finally:
            os.unlink(tmp_path)

    def test_single_row_basic_fields(self):
        records = self._parse_bytes([self.HEADERS, self.ROW_1])
        assert len(records) == 1
        r = records[0]
        assert r["ucc"] == "ML08PASS"
        assert r["family_group"] == "Passive Portfolio"
        assert r["symbol"] == "CPSEETF"
        assert r["instrument_type"] == "EQ"
        assert r["isin"] == "INF457M01133"

    def test_financial_values_are_decimal(self):
        records = self._parse_bytes([self.HEADERS, self.ROW_1])
        r = records[0]
        assert isinstance(r["quantity"], Decimal)
        assert isinstance(r["avg_cost"], Decimal)
        assert isinstance(r["total_cost"], Decimal)
        assert isinstance(r["market_price"], Decimal)
        assert isinstance(r["market_value"], Decimal)
        assert isinstance(r["notional_pnl"], Decimal)
        assert isinstance(r["roi_pct"], Decimal)

    def test_market_date_parsed(self):
        records = self._parse_bytes([self.HEADERS, self.ROW_1])
        assert records[0]["market_date"] == date(2026, 4, 8)

    def test_negative_pnl(self):
        records = self._parse_bytes([self.HEADERS, self.ROW_2])
        r = records[0]
        assert r["notional_pnl"] == Decimal("-591")
        assert r["roi_pct"] == Decimal("-2.22")

    def test_ucc_trailing_whitespace_stripped(self):
        records = self._parse_bytes([self.HEADERS, self.ROW_2])
        # "AT72      " becomes "AT72"
        assert records[0]["ucc"] == "AT72"

    def test_multiple_rows_multiple_uccs(self):
        records = self._parse_bytes([self.HEADERS, self.ROW_1, self.ROW_2, self.ROW_3])
        assert len(records) == 3
        uccs = {r["ucc"] for r in records}
        assert uccs == {"ML08PASS", "AT72"}

    def test_liquid_instrument(self):
        records = self._parse_bytes([self.HEADERS, self.ROW_3])
        r = records[0]
        assert r["symbol"] == "LIQUIDCASE"
        assert r["instrument_type"] == "EQ"

    def test_share_raw_preserved(self):
        records = self._parse_bytes([self.HEADERS, self.ROW_1])
        # share_raw should be stripped but not further split
        assert records[0]["share_raw"] == "CPSEETF EQ"

    def test_header_only_no_records(self):
        records = self._parse_bytes([self.HEADERS])
        assert records == []

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            parse_holding_report("/nonexistent/path/file.xlsx")

    def test_subtotal_row_skipped(self):
        """Rows with non-numeric qty (like 'Total') must be skipped."""
        subtotal_row = (
            "ML08PASS", "Passive Portfolio", "CPSEETF EQ",
            "INF457M01133", "Total", 99.3033, 75172.61, 23.84, 23.84,
            102.4, "08/04/2026", 77516.8, 2344.19, 3.12, 23.83, 23.83,
        )
        records = self._parse_bytes([self.HEADERS, subtotal_row])
        assert records == []

    def test_none_cells_handled(self):
        """Rows with None in optional financial fields should still parse."""
        row_with_nones = (
            "ML08PASS", "Passive Portfolio", "CPSEETF EQ",
            "INF457M01133", 757, None, None, None, None,
            102.4, "08/04/2026", None, None, None, None, None,
        )
        records = self._parse_bytes([self.HEADERS, row_with_nones])
        assert len(records) == 1
        r = records[0]
        assert r["avg_cost"] is None
        assert r["total_cost"] is None
        assert r["market_price"] == Decimal("102.4")


# ── holding_report_summary ──


class TestHoldingReportSummary:
    def _make_records(self, n_per_ucc: dict[str, int]) -> list[dict]:
        records = []
        for ucc, count in n_per_ucc.items():
            for i in range(count):
                records.append({
                    "ucc": ucc,
                    "symbol": f"STOCK{i}",
                    "market_date": date(2026, 4, 8),
                })
        return records

    def test_empty_input(self):
        result = holding_report_summary([])
        assert result["total_rows"] == 0
        assert result["unique_uccs"] == 0
        assert result["unique_symbols"] == 0
        assert result["market_date"] is None
        assert result["uccs"] == []

    def test_single_ucc(self):
        records = self._make_records({"ML08PASS": 3})
        result = holding_report_summary(records)
        assert result["total_rows"] == 3
        assert result["unique_uccs"] == 1
        assert result["unique_symbols"] == 3
        assert result["market_date"] == date(2026, 4, 8)

    def test_multiple_uccs(self):
        records = self._make_records({"ML08PASS": 2, "AT72": 3})
        result = holding_report_summary(records)
        assert result["total_rows"] == 5
        assert result["unique_uccs"] == 2
        assert result["uccs"] == ["AT72", "ML08PASS"]

    def test_most_common_date_returned(self):
        records = [
            {"ucc": "A1", "symbol": "X1", "market_date": date(2026, 4, 8)},
            {"ucc": "A1", "symbol": "X2", "market_date": date(2026, 4, 8)},
            {"ucc": "A1", "symbol": "X3", "market_date": date(2026, 4, 7)},
        ]
        result = holding_report_summary(records)
        assert result["market_date"] == date(2026, 4, 8)

    def test_no_market_dates(self):
        records = [{"ucc": "A1", "symbol": "X1", "market_date": None}]
        result = holding_report_summary(records)
        assert result["market_date"] is None
