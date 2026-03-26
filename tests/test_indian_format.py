"""Tests for Indian number formatting utilities — INR currency and percentages."""

from __future__ import annotations

import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "a" * 64)

from decimal import Decimal

import pytest

from backend.utils.indian_format import (
    _indian_grouping,
    format_inr,
    format_inr_short,
    format_pct,
)


# ── _indian_grouping ──


class TestIndianGrouping:
    def test_three_digits_no_grouping(self):
        assert _indian_grouping("999") == "999"

    def test_four_digits(self):
        assert _indian_grouping("1234") == "1,234"

    def test_five_digits(self):
        assert _indian_grouping("12345") == "12,345"

    def test_six_digits(self):
        assert _indian_grouping("123456") == "1,23,456"

    def test_seven_digits(self):
        assert _indian_grouping("1234567") == "12,34,567"

    def test_eight_digits(self):
        assert _indian_grouping("12345678") == "1,23,45,678"

    def test_single_digit(self):
        assert _indian_grouping("5") == "5"

    def test_two_digits(self):
        assert _indian_grouping("42") == "42"


# ── format_inr ──


class TestFormatINR:
    def test_basic_amount(self):
        assert format_inr(Decimal("123456")) == "₹1,23,456"

    def test_large_amount(self):
        assert format_inr(Decimal("12345678")) == "₹1,23,45,678"

    def test_decimal_places(self):
        assert format_inr(Decimal("50000.50")) == "₹50,000.50"

    def test_negative_amount(self):
        result = format_inr(Decimal("-50000.50"))
        assert result == "-₹50,000.50"

    def test_small_amount(self):
        assert format_inr(Decimal("999.99")) == "₹999.99"

    def test_zero(self):
        assert format_inr(Decimal("0")) == "₹0"

    def test_rounds_to_two_decimals(self):
        result = format_inr(Decimal("1234.567"))
        assert result == "₹1,234.57"

    def test_accepts_non_decimal_input(self):
        """Should auto-convert float/int to Decimal."""
        result = format_inr(1234)
        assert "₹1,234" in result

    def test_whole_number_no_decimal(self):
        """Whole numbers should not show .00 suffix."""
        result = format_inr(Decimal("50000.00"))
        assert result == "₹50,000"


# ── format_inr_short ──


class TestFormatINRShort:
    def test_crore_value(self):
        result = format_inr_short(Decimal("67450000"))
        assert result == "₹6.75 Cr"

    def test_large_crore(self):
        result = format_inr_short(Decimal("6745000000"))
        assert result == "₹674.50 Cr"

    def test_lakh_value(self):
        result = format_inr_short(Decimal("4850000"))
        assert result == "₹48.50L"

    def test_below_lakh_uses_full_format(self):
        result = format_inr_short(Decimal("99999"))
        assert result == "₹99,999"

    def test_negative_crore(self):
        result = format_inr_short(Decimal("-25000000"))
        assert result == "-₹2.50 Cr"

    def test_negative_lakh(self):
        result = format_inr_short(Decimal("-500000"))
        assert result == "-₹5.00L"

    def test_zero(self):
        result = format_inr_short(Decimal("0"))
        assert "₹0" in result

    def test_exactly_one_crore(self):
        result = format_inr_short(Decimal("10000000"))
        assert "Cr" in result

    def test_exactly_one_lakh(self):
        result = format_inr_short(Decimal("100000"))
        assert "L" in result


# ── format_pct ──


class TestFormatPct:
    def test_positive_pct(self):
        assert format_pct(35.64) == "+35.64%"

    def test_negative_pct(self):
        assert format_pct(-12.07) == "-12.07%"

    def test_zero(self):
        assert format_pct(0.0) == "0.00%"

    def test_decimal_input(self):
        assert format_pct(Decimal("25.123")) == "+25.12%"

    def test_rounds_correctly(self):
        assert format_pct(Decimal("1.555")) == "+1.56%"

    def test_very_small_positive(self):
        result = format_pct(Decimal("0.01"))
        assert result == "+0.01%"
