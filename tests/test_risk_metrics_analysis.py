"""Tests for derived risk metric functions — beta, alpha, capture ratios, etc."""

import numpy as np
import pandas as pd
import pytest

from backend.services.risk_metrics_analysis import (
    alpha,
    beta,
    cash_metrics,
    compute_drawdown_series,
    down_capture,
    information_ratio,
    market_correlation,
    monthly_return_profile,
    tracking_error,
    ulcer_index,
    up_capture,
)


# ── Fixtures ──


@pytest.fixture
def port_returns():
    """Daily portfolio returns over 10 days."""
    return pd.Series([0.01, -0.005, 0.02, 0.003, -0.01, 0.015, -0.008, 0.012, 0.005, -0.003])


@pytest.fixture
def bench_returns():
    """Daily benchmark returns over 10 days (correlated but different)."""
    return pd.Series([0.008, -0.003, 0.015, 0.002, -0.008, 0.012, -0.006, 0.010, 0.004, -0.002])


@pytest.fixture
def nav_series():
    """Simple NAV series for ulcer index and drawdown tests."""
    dates = pd.date_range("2025-01-01", periods=10, freq="D")
    values = [100, 105, 103, 108, 106, 110, 107, 112, 115, 113]
    return pd.Series(values, index=dates, dtype=float)


@pytest.fixture
def nav_df_for_monthly():
    """6-month daily NAV DataFrame for monthly return profile testing."""
    dates = pd.date_range("2024-07-01", periods=180, freq="D")
    # Simulate upward trend with noise
    np.random.seed(42)
    prices = 100 * np.cumprod(1 + np.random.normal(0.0005, 0.01, 180))
    return pd.DataFrame({"nav_date": dates, "nav_value": prices})


# ── Beta ──


class TestBeta:
    def test_positive_correlated_returns(self, port_returns, bench_returns):
        result = beta(port_returns, bench_returns)
        assert result > 0

    def test_identical_returns_beta_one(self):
        rets = pd.Series([0.01, -0.005, 0.02, 0.003, -0.01])
        result = beta(rets, rets)
        assert pytest.approx(result, rel=1e-3) == 1.0

    def test_insufficient_data(self):
        assert beta(pd.Series([0.01]), pd.Series([0.02])) == 0.0

    def test_zero_volatility_returns_zero(self):
        flat = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0])
        bench = pd.Series([0.01, -0.005, 0.02, 0.003, -0.01])
        assert beta(flat, bench) == 0.0

    def test_zero_bench_variance_returns_zero(self):
        port = pd.Series([0.01, -0.005, 0.02])
        flat_bench = pd.Series([0.0, 0.0, 0.0])
        assert beta(port, flat_bench) == 0.0


# ── Alpha ──


class TestAlpha:
    def test_positive_alpha(self):
        # Port outperforms what beta predicts
        result = alpha(port_cagr=20.0, bench_cagr=12.0, beta_val=1.0, risk_free_rate=6.5)
        # expected = 6.5 + 1.0 * (12.0 - 6.5) = 12.0; alpha = 20.0 - 12.0 = 8.0
        assert pytest.approx(result, rel=1e-3) == 8.0

    def test_zero_beta_alpha_equals_excess_over_rf(self):
        result = alpha(port_cagr=15.0, bench_cagr=10.0, beta_val=0.0, risk_free_rate=6.5)
        # expected = 6.5 + 0 * (10 - 6.5) = 6.5; alpha = 15.0 - 6.5 = 8.5
        assert pytest.approx(result, rel=1e-3) == 8.5

    def test_negative_alpha(self):
        result = alpha(port_cagr=5.0, bench_cagr=12.0, beta_val=1.0, risk_free_rate=6.5)
        assert result < 0


# ── Up/Down Capture ──


class TestUpCapture:
    def test_perfect_tracking_is_100(self):
        rets = pd.Series([0.01, -0.005, 0.02, -0.01, 0.015])
        result = up_capture(rets, rets)
        assert pytest.approx(result, rel=1e-2) == 100.0

    def test_no_up_days(self):
        port = pd.Series([-0.01, -0.02, -0.005])
        bench = pd.Series([-0.008, -0.015, -0.003])
        assert up_capture(port, bench) == 0.0

    def test_outperforming_on_up_days(self, port_returns, bench_returns):
        result = up_capture(port_returns, bench_returns)
        # Portfolio has higher positive returns on up days
        assert result > 0


class TestDownCapture:
    def test_perfect_tracking_is_100(self):
        rets = pd.Series([0.01, -0.005, 0.02, -0.01, 0.015])
        result = down_capture(rets, rets)
        assert pytest.approx(result, rel=1e-2) == 100.0

    def test_no_down_days(self):
        port = pd.Series([0.01, 0.02, 0.005])
        bench = pd.Series([0.008, 0.015, 0.003])
        assert down_capture(port, bench) == 0.0

    def test_defensive_portfolio_lower_capture(self):
        """A portfolio that drops less on down days has < 100% down capture."""
        port = pd.Series([0.01, -0.002, 0.02, -0.003])
        bench = pd.Series([0.01, -0.01, 0.02, -0.015])
        result = down_capture(port, bench)
        assert result < 100.0


# ── Information Ratio & Tracking Error ──


class TestInformationRatio:
    def test_positive_ir(self):
        result = information_ratio(port_cagr=15.0, bench_cagr=10.0, tracking_error_val=5.0)
        assert pytest.approx(result, rel=1e-3) == 1.0

    def test_zero_te_returns_zero(self):
        assert information_ratio(15.0, 10.0, 0.0) == 0.0

    def test_negative_excess_return(self):
        result = information_ratio(port_cagr=8.0, bench_cagr=12.0, tracking_error_val=4.0)
        assert result < 0


class TestTrackingError:
    def test_positive_value(self, port_returns, bench_returns):
        excess = port_returns - bench_returns
        result = tracking_error(excess)
        assert result > 0

    def test_zero_excess_returns(self):
        excess = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0])
        assert tracking_error(excess) == 0.0

    def test_insufficient_data(self):
        assert tracking_error(pd.Series([0.01])) == 0.0


# ── Ulcer Index ──


class TestUlcerIndex:
    def test_positive_result(self, nav_series):
        result = ulcer_index(nav_series)
        assert result > 0

    def test_monotonically_increasing_is_zero(self):
        nav = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0])
        assert ulcer_index(nav) == 0.0

    def test_deep_drawdown_higher_ulcer(self):
        """Series with deeper drawdown should have higher ulcer index."""
        mild = pd.Series([100, 99, 100, 99, 100], dtype=float)
        deep = pd.Series([100, 80, 90, 70, 85], dtype=float)
        assert ulcer_index(deep) > ulcer_index(mild)

    def test_single_point_returns_zero(self):
        assert ulcer_index(pd.Series([100.0])) == 0.0


# ── Market Correlation ──


class TestMarketCorrelation:
    def test_identical_series_correlation_one(self):
        rets = pd.Series([0.01, -0.005, 0.02, 0.003, -0.01])
        result = market_correlation(rets, rets)
        assert pytest.approx(result, rel=1e-3) == 1.0

    def test_insufficient_data(self):
        assert market_correlation(pd.Series([0.01]), pd.Series([0.02])) == 0.0

    def test_zero_volatility_returns_zero(self):
        flat = pd.Series([0.0, 0.0, 0.0, 0.0])
        bench = pd.Series([0.01, -0.005, 0.02, 0.003])
        assert market_correlation(flat, bench) == 0.0

    def test_positive_correlation(self, port_returns, bench_returns):
        result = market_correlation(port_returns, bench_returns)
        assert result > 0


# ── Monthly Return Profile ──


class TestMonthlyReturnProfile:
    def test_basic_output_keys(self, nav_df_for_monthly):
        result = monthly_return_profile(nav_df_for_monthly)
        assert "hit_rate" in result
        assert "best_month" in result
        assert "worst_month" in result
        assert "win_count" in result
        assert "loss_count" in result
        assert "max_consecutive_loss" in result

    def test_too_few_days_returns_zeros(self):
        short_df = pd.DataFrame({
            "nav_date": pd.date_range("2025-01-01", periods=10, freq="D"),
            "nav_value": range(100, 110),
        })
        result = monthly_return_profile(short_df)
        assert result["hit_rate"] == 0.0
        assert result["win_count"] == 0

    def test_best_worst_ordering(self, nav_df_for_monthly):
        result = monthly_return_profile(nav_df_for_monthly)
        assert result["best_month"] >= result["worst_month"]

    def test_win_loss_counts_sum(self, nav_df_for_monthly):
        result = monthly_return_profile(nav_df_for_monthly)
        total = result["win_count"] + result["loss_count"]
        assert total > 0


# ── Cash Metrics ──


class TestCashMetrics:
    def test_empty_df(self):
        result = cash_metrics(pd.DataFrame())
        assert result == {"avg_cash_held": 0.0, "max_cash_held": 0.0, "current_cash": 0.0}

    def test_with_cash_pct(self):
        df = pd.DataFrame({
            "nav_value": [100, 105, 110],
            "cash_pct": [10.0, 12.0, 8.0],
        })
        result = cash_metrics(df)
        assert pytest.approx(result["avg_cash_held"], rel=1e-2) == 10.0
        assert result["max_cash_held"] == 12.0
        assert result["current_cash"] == 8.0

    def test_with_breakdown_columns(self):
        df = pd.DataFrame({
            "nav_value": [1000.0, 1000.0, 1000.0],
            "etf_value": [50.0, 60.0, 40.0],
            "cash_value": [20.0, 30.0, 25.0],
            "bank_balance": [10.0, 10.0, 15.0],
        })
        result = cash_metrics(df)
        # Day 1: (50+20+10)/1000 = 8%, Day 2: (60+30+10)/1000 = 10%, Day 3: (40+25+15)/1000 = 8%
        assert pytest.approx(result["current_cash"], rel=1e-2) == 8.0
        assert pytest.approx(result["max_cash_held"], rel=1e-2) == 10.0


# ── Drawdown Series ──


class TestComputeDrawdownSeries:
    def test_output_columns(self):
        df = pd.DataFrame({
            "nav_date": pd.date_range("2025-01-01", periods=5),
            "nav_value": [100, 105, 103, 108, 110],
        })
        result = compute_drawdown_series(df)
        assert "dd_date" in result.columns
        assert "drawdown_pct" in result.columns
        assert "peak_nav" in result.columns

    def test_no_drawdown_on_new_highs(self):
        df = pd.DataFrame({
            "nav_date": pd.date_range("2025-01-01", periods=4),
            "nav_value": [100, 101, 102, 103],
        })
        result = compute_drawdown_series(df)
        assert all(result["drawdown_pct"] == 0.0)

    def test_drawdown_is_negative(self):
        df = pd.DataFrame({
            "nav_date": pd.date_range("2025-01-01", periods=4),
            "nav_value": [100, 110, 90, 95],
        })
        result = compute_drawdown_series(df)
        # After peak of 110, 90 is a drawdown
        assert result["drawdown_pct"].iloc[2] < 0
