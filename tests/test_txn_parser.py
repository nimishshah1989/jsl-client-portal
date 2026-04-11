"""Tests for transaction parser — symbol parsing, sector classification, Decimal safety."""

from decimal import Decimal

import pytest

from backend.services.txn_parser import (
    _safe_decimal,
    classify_sector,
    parse_script,
)


class TestParseScript:
    def test_standard_equity(self):
        symbol, inst = parse_script("RELIANCE     EQ")
        assert symbol == "RELIANCE"
        assert inst == "EQ"

    def test_single_word(self):
        symbol, inst = parse_script("LIQUIDBEES")
        assert symbol == "LIQUIDBEES"
        assert inst == "EQ"  # Single word defaults instrument to EQ

    def test_whitespace_handling(self):
        symbol, inst = parse_script("  TCS   EQ  ")
        assert symbol == "TCS"
        assert inst == "EQ"

    def test_multi_segment(self):
        symbol, inst = parse_script("HDFC BANK   EQ")
        assert symbol == "HDFCBANK"
        assert inst == "EQ"


class TestClassifySector:
    def test_liquid_instruments(self):
        assert classify_sector("LIQUIDBEES") == "Cash"
        assert classify_sector("LIQUIDETF") == "Cash"
        assert classify_sector("LIQUIDCASE") == "Cash"

    def test_case_insensitive_liquid(self):
        assert classify_sector("liquidbees") == "Cash"

    def test_gold_etf(self):
        assert classify_sector("GOLDBEES") == "Metals"
        assert classify_sector("SILVERBEES") == "Metals"

    def test_banking_etf(self):
        assert classify_sector("BANKBEES") == "Banking"

    def test_unknown_symbol(self):
        assert classify_sector("RELIANCE") == ""

    def test_nifty_etf(self):
        assert classify_sector("NIFTYBEES") == "Diversified"


class TestSafeDecimal:
    def test_integer(self):
        assert _safe_decimal(100) == Decimal("100")

    def test_none(self):
        assert _safe_decimal(None) == Decimal("0")

    def test_nan(self):
        assert _safe_decimal(float("nan")) == Decimal("0")

    def test_string(self):
        assert _safe_decimal("250.50") == Decimal("250.50")

    def test_invalid_string(self):
        assert _safe_decimal("abc") == Decimal("0")

    def test_negative(self):
        assert _safe_decimal(-1000) == Decimal("-1000")

    def test_comparison_with_zero(self):
        """Decimal comparison used for buy_qty > 0 check."""
        assert _safe_decimal(10) > 0
        assert not (_safe_decimal(0) > 0)
        assert not (_safe_decimal(None) > 0)
