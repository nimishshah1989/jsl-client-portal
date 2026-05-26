"""Tests for core risk metric computation functions."""

import numpy as np
import pandas as pd
import pytest

from backend.services.risk_metrics import (
    absolute_return,
    annualized_volatility,
    cagr,
    compute_daily_returns,
    compute_twr_index,
    compute_twr_series,
    compute_weighted_avg_corpus,
    compute_weighted_bench_return,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
)
from backend.services.risk_metrics_analysis import (
    alpha,
    beta,
    cash_metrics,
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
def nav_series():
    """Simple NAV series: 100 → 110 → 105 → 115 → 120."""
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    return pd.Series([100.0, 110.0, 105.0, 115.0, 120.0], index=dates)


@pytest.fixture
def daily_returns():
    """Pre-computed daily returns for the nav_series fixture."""
    return pd.Series([0.10, -0.04545, 0.09524, 0.04348])


@pytest.fixture
def bench_returns():
    """Benchmark daily returns (slightly different from portfolio)."""
    return pd.Series([0.08, -0.03, 0.07, 0.03])


# ── Core metric tests ──

class TestAbsoluteReturn:
    def test_inception_return(self, nav_series):
        result = absolute_return(nav_series)
        assert pytest.approx(result, rel=1e-3) == 20.0  # (120/100 - 1) * 100

    def test_trailing_return(self, nav_series):
        result = absolute_return(nav_series, days=2)
        # 2 days back from last date: start ~105, end 120
        assert result > 0

    def test_empty_series(self):
        s = pd.Series([100.0])
        assert absolute_return(s) == 0.0

    def test_zero_start(self):
        dates = pd.date_range("2025-01-01", periods=3, freq="D")
        s = pd.Series([0.0, 100.0, 110.0], index=dates)
        assert absolute_return(s) == 0.0


class TestCAGR:
    def test_one_year_doubling(self):
        result = cagr(100.0, 200.0, 365)
        assert pytest.approx(result, rel=1e-2) == 100.0

    def test_two_year_50pct(self):
        result = cagr(100.0, 150.0, 730)
        expected = ((1.5 ** (365.25 / 730)) - 1) * 100
        assert pytest.approx(result, rel=1e-3) == expected

    def test_zero_days(self):
        assert cagr(100.0, 200.0, 0) == 0.0

    def test_zero_start(self):
        assert cagr(0.0, 200.0, 365) == 0.0

    def test_negative_end(self):
        assert cagr(100.0, -50.0, 365) == 0.0


class TestVolatility:
    def test_constant_returns(self):
        rets = pd.Series([0.01] * 100)
        assert annualized_volatility(rets) < 1e-10

    def test_positive_volatility(self, daily_returns):
        vol = annualized_volatility(daily_returns)
        assert vol > 0

    def test_short_series(self):
        assert annualized_volatility(pd.Series([0.01])) == 0.0


class TestSharpeRatio:
    """Sharpe = (CAGR_pct - Rf) / Volatility_pct per CLAUDE.md spec."""

    def test_known_value(self):
        # CAGR 35.64%, Vol 15%, Rf 6.50% → (35.64 - 6.50) / 15 = 1.9427 (matches
        # the worked example in CLAUDE.md Section 13).
        result = sharpe_ratio(cagr_pct=35.64, volatility_pct=15.0, risk_free_rate=6.50)
        assert pytest.approx(result, rel=1e-4) == (35.64 - 6.50) / 15.0

    def test_returns_below_risk_free(self):
        # Negative excess return → negative Sharpe.
        result = sharpe_ratio(cagr_pct=4.0, volatility_pct=12.0, risk_free_rate=6.50)
        assert result < 0
        assert pytest.approx(result, rel=1e-4) == (4.0 - 6.50) / 12.0

    def test_zero_vol(self):
        assert sharpe_ratio(cagr_pct=10.0, volatility_pct=0.0, risk_free_rate=6.50) == 0.0


class TestSortinoRatio:
    """
    Sortino = (CAGR_pct - Rf) / σ_downside_pct, where
    σ_downside_pct = √252 × √(mean(min(R_daily, 0)²)) × 100.
    Downside threshold is ZERO, not the daily Rf.
    """

    def test_no_downside_returns_zero(self):
        # All-positive return series → no negative days → undefined → return 0.0
        rets = pd.Series([0.01, 0.02, 0.015, 0.005])
        assert sortino_ratio(cagr_pct=25.0, daily_returns=rets, risk_free_rate=6.50) == 0.0

    def test_known_value(self):
        # Hand-computed: returns = [-0.02, +0.01, -0.01, +0.03]
        # downside = [-0.02, -0.01]; mean(square) = (0.0004+0.0001)/2 = 0.00025
        # √0.00025 = 0.015811...; × √252 ≈ 0.250998; × 100 ≈ 25.0998 (%)
        # CAGR 30%, Rf 6.50 → (30 - 6.5) / 25.0998 ≈ 0.9363
        rets = pd.Series([-0.02, 0.01, -0.01, 0.03])
        result = sortino_ratio(cagr_pct=30.0, daily_returns=rets, risk_free_rate=6.50)
        expected_dd = (((-0.02) ** 2 + (-0.01) ** 2) / 2) ** 0.5
        expected_dd_pct = expected_dd * (252 ** 0.5) * 100
        assert pytest.approx(result, rel=1e-4) == (30.0 - 6.50) / expected_dd_pct

    def test_short_series(self):
        assert sortino_ratio(cagr_pct=10.0, daily_returns=pd.Series([0.01])) == 0.0


class TestMaxDrawdown:
    def test_simple_drawdown(self, nav_series):
        result = max_drawdown(nav_series)
        # Peak at 110, trough at 105 → DD = (105-110)/110 = -4.545%
        assert result["max_dd_pct"] < 0
        assert pytest.approx(result["max_dd_pct"], rel=1e-2) == -4.545

    def test_recovery_found(self, nav_series):
        result = max_drawdown(nav_series)
        assert result["dd_recovery"] is not None

    def test_no_drawdown(self):
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        s = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0], index=dates)
        result = max_drawdown(s)
        assert result["max_dd_pct"] == 0.0

    def test_short_series(self):
        result = max_drawdown(pd.Series([100.0]))
        assert result["max_dd_pct"] == 0.0


class TestTWR:
    def test_base_100_normalization(self, nav_series):
        result = compute_twr_index(nav_series)
        assert result.iloc[0] == 100.0
        assert pytest.approx(result.iloc[-1], rel=1e-3) == 120.0

    def test_corpus_adjusted_twr(self):
        df = pd.DataFrame({
            "nav_value": [100.0, 110.0, 125.0, 130.0],
            "invested_amount": [100.0, 100.0, 115.0, 115.0],
        })
        twr = compute_twr_series(df)
        assert twr[0] == 100.0
        # Day 2→3: corpus +15, adjusted_prev = 110+15=125, ret = 125/125-1 = 0%
        assert pytest.approx(twr[2], rel=1e-2) == twr[1]


# ── Analysis metric tests ──

class TestBeta:
    def test_identical_returns(self):
        rets = pd.Series([0.01, -0.02, 0.03, -0.01, 0.02])
        result = beta(rets, rets)
        assert pytest.approx(result, rel=1e-3) == 1.0

    def test_short_series(self):
        assert beta(pd.Series([0.01]), pd.Series([0.02])) == 0.0


class TestAlpha:
    def test_positive_alpha(self):
        result = alpha(port_cagr=20.0, bench_cagr=10.0, beta_val=1.0, risk_free_rate=6.5)
        assert result == 10.0  # 20 - [6.5 + 1*(10-6.5)] = 20 - 10 = 10

    def test_zero_beta(self):
        result = alpha(port_cagr=20.0, bench_cagr=10.0, beta_val=0.0, risk_free_rate=6.5)
        assert result == 13.5  # 20 - 6.5 = 13.5


class TestCaptureRatios:
    def test_up_capture_100(self):
        rets = pd.Series([0.01, -0.02, 0.03])
        result = up_capture(rets, rets)
        assert pytest.approx(result, rel=1e-2) == 100.0

    def test_down_capture_100(self):
        rets = pd.Series([0.01, -0.02, 0.03])
        result = down_capture(rets, rets)
        assert pytest.approx(result, rel=1e-2) == 100.0


class TestInfoRatio:
    def test_positive_ir(self):
        result = information_ratio(20.0, 10.0, 5.0)
        assert result == 2.0

    def test_zero_te(self):
        assert information_ratio(20.0, 10.0, 0.0) == 0.0


class TestTrackingError:
    def test_identical_returns(self):
        excess = pd.Series([0.0, 0.0, 0.0, 0.0])
        assert tracking_error(excess) == 0.0

    def test_short_series(self):
        assert tracking_error(pd.Series([0.01])) == 0.0


class TestUlcerIndex:
    def test_no_drawdown(self):
        s = pd.Series([100.0, 101.0, 102.0, 103.0])
        assert ulcer_index(s) == 0.0

    def test_with_drawdown(self, nav_series):
        result = ulcer_index(nav_series)
        assert result > 0


class TestMarketCorrelation:
    def test_perfect_correlation(self):
        rets = pd.Series([0.01, -0.02, 0.03, -0.01])
        result = market_correlation(rets, rets)
        assert pytest.approx(result, abs=0.01) == 1.0

    def test_short_series(self):
        assert market_correlation(pd.Series([0.01]), pd.Series([0.02])) == 0.0


class TestWeightedAvgCorpus:
    def test_constant_corpus(self):
        # Corpus held at 1,000,000 for full period → weighted avg = 1,000,000
        df = pd.DataFrame({
            "nav_date": pd.date_range("2024-01-01", periods=100, freq="D"),
            "invested_amount": [1_000_000.0] * 100,
        })
        result = compute_weighted_avg_corpus(df)
        assert pytest.approx(result, rel=1e-6) == 1_000_000.0

    def test_midway_doubling(self):
        # 100 days at 1,000,000 then 100 days at 2,000,000 → weighted avg ≈ 1.5M
        dates = pd.date_range("2024-01-01", periods=201, freq="D")
        corpus = [1_000_000.0] * 100 + [2_000_000.0] * 101
        df = pd.DataFrame({"nav_date": dates, "invested_amount": corpus})
        result = compute_weighted_avg_corpus(df)
        # 100 days at 1M + 100 days at 2M over 200-day span
        assert pytest.approx(result, rel=1e-3) == 1_500_000.0

    def test_single_row(self):
        df = pd.DataFrame({
            "nav_date": [pd.Timestamp("2024-01-01")],
            "invested_amount": [500_000.0],
        })
        assert compute_weighted_avg_corpus(df) == 500_000.0


class TestWeightedBenchReturn:
    def test_no_corpus_changes_returns_zero(self):
        # Single initial infusion, then no further events → our virtual-units
        # path needs at least one delta to compute a return.
        df = pd.DataFrame({
            "nav_date": pd.date_range("2024-01-01", periods=3, freq="D"),
            "benchmark_value": [10_000.0, 10_500.0, 11_000.0],
            "invested_amount": [1_000_000.0, 1_000_000.0, 1_000_000.0],
        })
        # First row is the only corpus delta; single-flow case should still compute
        # (delta=1M at bench=10000 → 100 units, terminal=11000 → 1.1M → 10% return).
        result = compute_weighted_bench_return(df)
        assert pytest.approx(result, rel=1e-2) == 10.0

    def test_empty_benchmark(self):
        df = pd.DataFrame({
            "nav_date": pd.date_range("2024-01-01", periods=3, freq="D"),
            "benchmark_value": [0.0, 0.0, 0.0],
            "invested_amount": [1_000_000.0, 1_000_000.0, 1_000_000.0],
        })
        assert compute_weighted_bench_return(df) == 0.0
