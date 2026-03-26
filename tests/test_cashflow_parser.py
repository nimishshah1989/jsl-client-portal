"""Tests for cashflow parser — verifies Decimal parsing of financial amounts."""

from decimal import Decimal

import pytest

from backend.services.cashflow_parser import _safe_decimal


class TestSafeDecimal:
    def test_integer(self):
        assert _safe_decimal(100) == Decimal("100")

    def test_float(self):
        result = _safe_decimal(123.45)
        assert isinstance(result, Decimal)
        assert float(result) == pytest.approx(123.45, rel=1e-6)

    def test_string_number(self):
        assert _safe_decimal("500000.50") == Decimal("500000.50")

    def test_none_returns_zero(self):
        assert _safe_decimal(None) == Decimal("0")

    def test_empty_string(self):
        assert _safe_decimal("") == Decimal("0")

    def test_non_numeric_string(self):
        assert _safe_decimal("N/A") == Decimal("0")

    def test_nan_returns_zero(self):
        assert _safe_decimal(float("nan")) == Decimal("0")

    def test_negative_value(self):
        assert _safe_decimal(-50000) == Decimal("-50000")

    def test_large_amount(self):
        """PMS cash flows can be in crores."""
        result = _safe_decimal(50000000.00)
        assert result > Decimal("0")
