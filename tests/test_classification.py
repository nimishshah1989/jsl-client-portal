"""Tests for portfolio strategy classification from PMS client codes.

This is the single source of truth used by both the one-time merge migration and
ongoing ingestion, so it is tested thoroughly against the real code patterns seen
in the pre-flight report.
"""

import pytest

from backend.services.classification import (
    STRATEGY_IND11,
    STRATEGY_LEADERS,
    STRATEGY_PASSIVE,
    classify_code,
)


class TestStrategy:
    @pytest.mark.parametrize("code", ["BJ53PASS", "DK88PASS", "ML08PASS", "RT79PASS", "rj309pass"])
    def test_pass_suffix_is_passive(self, code):
        assert classify_code(code).strategy == STRATEGY_PASSIVE

    @pytest.mark.parametrize("code", ["BJ53IND", "JJ54IND", "PS352IND", "pp688ind"])
    def test_ind_suffix_is_ind11(self, code):
        assert classify_code(code).strategy == STRATEGY_IND11

    @pytest.mark.parametrize(
        "code",
        ["BJ53", "BJ53MF", "BJ53NEW", "BJ53AML", "JJ54JFC", "1075SK02", "1075SK02AM", "1075SK02C", "AC04MF"],
    )
    def test_everything_else_is_leaders(self, code):
        assert classify_code(code).strategy == STRATEGY_LEADERS


class TestClosed:
    @pytest.mark.parametrize("code", ["JA59CLOSE", "YP79close", "990NS12CLO"])
    def test_close_suffix_is_closed(self, code):
        assert classify_code(code).is_closed is True

    @pytest.mark.parametrize("code", ["BJ53", "BJ53PASS", "BJ53IND", "JJ54MF", "1075SK02C"])
    def test_non_close_is_not_closed(self, code):
        # Note: a trailing 'C' (1075SK02C) must NOT be read as closed.
        assert classify_code(code).is_closed is False

    def test_closed_code_keeps_its_suffix_strategy(self):
        # The observed closed codes carry no PASS/IND suffix -> LEADERS.
        result = classify_code("990NS12CLO")
        assert result.strategy == STRATEGY_LEADERS
        assert result.is_closed is True


class TestRobustness:
    def test_case_insensitive(self):
        assert classify_code("bj53pass").strategy == STRATEGY_PASSIVE
        assert classify_code("Ja59Close").is_closed is True

    def test_whitespace_trimmed(self):
        assert classify_code("  BJ53PASS  ").strategy == STRATEGY_PASSIVE

    @pytest.mark.parametrize("code", [None, "", "   "])
    def test_empty_defaults_to_active_leaders(self, code):
        result = classify_code(code)
        assert result.strategy == STRATEGY_LEADERS
        assert result.is_closed is False

    def test_returns_named_fields(self):
        result = classify_code("BJ53PASS")
        assert result.strategy == STRATEGY_PASSIVE
        assert result.is_closed is False
