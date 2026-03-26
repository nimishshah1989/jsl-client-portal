"""Tests for NAV file parser — helper functions and row-type detection."""

from datetime import datetime
from decimal import Decimal

import pytest

from backend.services.nav_parser import (
    _NAME_PATTERN,
    _parse_nav_date,
    _safe_decimal,
)


# ── _safe_decimal ──


class TestSafeDecimal:
    def test_integer(self):
        assert _safe_decimal(12345) == Decimal("12345")

    def test_float(self):
        result = _safe_decimal(123.45)
        assert result == Decimal("123.45")

    def test_string_number(self):
        assert _safe_decimal("67890.12") == Decimal("67890.12")

    def test_none_returns_zero(self):
        assert _safe_decimal(None) == Decimal("0")

    def test_empty_string_returns_zero(self):
        assert _safe_decimal("") == Decimal("0")

    def test_non_numeric_returns_zero(self):
        assert _safe_decimal("not_a_number") == Decimal("0")

    def test_nan_string_returns_nan_decimal(self):
        """Decimal('nan') is a valid Decimal, so _safe_decimal passes it through."""
        result = _safe_decimal("nan")
        assert result.is_nan()

    def test_negative_value(self):
        assert _safe_decimal("-500.25") == Decimal("-500.25")

    def test_large_value(self):
        result = _safe_decimal("123456789.123456")
        assert result == Decimal("123456789.123456")


# ── _parse_nav_date ──


class TestParseNavDate:
    def test_standard_format(self):
        """DD-MMM-YYYY format used in PMS files."""
        result = _parse_nav_date("28-Sep-2020")
        assert result == datetime(2020, 9, 28)

    def test_datetime_passthrough(self):
        dt = datetime(2025, 3, 15)
        assert _parse_nav_date(dt) == dt

    def test_none_returns_none(self):
        assert _parse_nav_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_nav_date("") is None

    def test_nan_string_returns_none(self):
        assert _parse_nav_date("nan") is None

    def test_malformed_date_returns_none(self):
        assert _parse_nav_date("not-a-date") is None

    def test_wrong_format_returns_none(self):
        """MM/DD/YYYY is not the expected format."""
        assert _parse_nav_date("09/28/2020") is None

    def test_whitespace_stripped(self):
        result = _parse_nav_date("  15-Jan-2024  ")
        assert result == datetime(2024, 1, 15)

    def test_various_months(self):
        assert _parse_nav_date("01-Jan-2025") == datetime(2025, 1, 1)
        assert _parse_nav_date("15-Jun-2024") == datetime(2024, 6, 15)
        assert _parse_nav_date("31-Dec-2023") == datetime(2023, 12, 31)


# ── _NAME_PATTERN (client header detection) ──


class TestNamePattern:
    def test_standard_header(self):
        match = _NAME_PATTERN.match("BHARAT JHAVERI [BJ53]")
        assert match is not None
        assert match.group(1).strip() == "BHARAT JHAVERI"
        assert match.group(2) == "BJ53"

    def test_header_with_extra_spaces(self):
        match = _NAME_PATTERN.match("NIMISH SHAH   [NS01]")
        assert match is not None
        assert match.group(2) == "NS01"

    def test_long_name(self):
        match = _NAME_PATTERN.match("SOME VERY LONG CLIENT NAME [ABC123]")
        assert match is not None
        assert match.group(2) == "ABC123"

    def test_non_header_row(self):
        """Regular UCC code should not match."""
        assert _NAME_PATTERN.match("BJ53") is None

    def test_missing_brackets(self):
        assert _NAME_PATTERN.match("BHARAT JHAVERI BJ53") is None

    def test_empty_string(self):
        assert _NAME_PATTERN.match("") is None

    def test_numeric_code(self):
        match = _NAME_PATTERN.match("CLIENT NAME [12345]")
        assert match is not None
        assert match.group(2) == "12345"
