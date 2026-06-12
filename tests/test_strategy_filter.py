"""Tests for the admin-aggregate strategy scoping helper."""

import pytest

from backend.services.strategy_filter import (
    normalize_strategy,
    portfolio_clause,
    strategy_params,
)


class TestNormalize:
    @pytest.mark.parametrize("raw,expected", [
        ("LEADERS", "LEADERS"),
        ("passive", "PASSIVE"),
        ("ind11", "IND11"),
        ("Combined", "COMBINED"),
        ("  leaders  ", "LEADERS"),
    ])
    def test_valid(self, raw, expected):
        assert normalize_strategy(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "garbage", "leader", "all"])
    def test_invalid_defaults_to_combined(self, raw):
        assert normalize_strategy(raw) == "COMBINED"


class TestPortfolioClause:
    def test_join_uses_portfolio_id_not_client_id(self):
        join, _ = portfolio_clause("LEADERS")
        # Must join on portfolio_id so it stays correct when a client owns
        # several portfolios across strategies.
        assert "pstrat.id = n.portfolio_id" in join
        assert "client_id" not in join

    def test_closed_always_excluded(self):
        for strat in ("COMBINED", "LEADERS", "PASSIVE", "IND11"):
            _, where = portfolio_clause(strat)
            assert "pstrat.is_closed = false" in where

    def test_combined_has_no_strategy_predicate(self):
        _, where = portfolio_clause("COMBINED")
        assert ":strategy" not in where

    def test_single_strategy_adds_predicate(self):
        _, where = portfolio_clause("PASSIVE")
        assert "pstrat.strategy = :strategy" in where

    def test_alias_threads_through(self):
        join, _ = portfolio_clause("LEADERS", alias="h")
        assert "pstrat.id = h.portfolio_id" in join

    def test_garbage_strategy_is_combined(self):
        _, where = portfolio_clause("nonsense")
        assert ":strategy" not in where  # fell back to COMBINED


class TestStrategyParams:
    def test_combined_is_empty(self):
        assert strategy_params("COMBINED") == {}
        assert strategy_params(None) == {}

    def test_single_strategy_binds_normalized_value(self):
        assert strategy_params("passive") == {"strategy": "PASSIVE"}
        assert strategy_params("IND11") == {"strategy": "IND11"}
