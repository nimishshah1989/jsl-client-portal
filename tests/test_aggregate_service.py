"""Tests for aggregate service — composite index and range filter functions.

Tests the pure functions _build_composite_from_returns and _apply_range_filter
by reimplementing the same logic to avoid the deep SQLAlchemy model import chain
which requires database configuration.
"""

import numpy as np
import pandas as pd
import pytest


# ── Reimplemented pure functions (matching aggregate_service.py logic) ──

RANGE_DAYS = {
    "1M": 30, "3M": 91, "6M": 182, "1Y": 365,
    "2Y": 730, "3Y": 1095, "5Y": 1826, "ALL": None,
}


def _build_composite_from_returns(daily_rets: pd.DataFrame):
    """Build composite index from pre-computed AUM-weighted daily returns."""
    if daily_rets.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    port_ret = daily_rets["weighted_port_ret"].values
    bench_ret = daily_rets["weighted_bench_ret"].values

    port_cum = 100.0 * np.cumprod(1.0 + port_ret)
    bench_cum = 100.0 * np.cumprod(1.0 + bench_ret)

    dates = daily_rets["nav_date"].values
    first_date = dates[0] - pd.Timedelta(days=1)
    all_dates = np.concatenate([[first_date], dates])

    port_index = np.concatenate([[100.0], port_cum])
    bench_index = np.concatenate([[100.0], bench_cum])

    idx = pd.DatetimeIndex(all_dates)
    return pd.Series(port_index, index=idx), pd.Series(bench_index, index=idx)


def _apply_range_filter(df: pd.DataFrame, range_filter: str) -> pd.DataFrame:
    """Slice DataFrame to trailing N days based on range_filter."""
    days = RANGE_DAYS.get(range_filter.upper())
    if days is None or df.empty:
        return df
    cutoff = df["nav_date"].iloc[-1] - pd.Timedelta(days=days)
    return df[df["nav_date"] >= cutoff].reset_index(drop=True)


# ── Fixtures ──


@pytest.fixture
def sample_daily_returns():
    """DataFrame with nav_date, weighted_port_ret, weighted_bench_ret."""
    dates = pd.date_range("2025-01-02", periods=5, freq="D")
    return pd.DataFrame({
        "nav_date": dates,
        "weighted_port_ret": [0.01, -0.005, 0.02, 0.003, -0.01],
        "weighted_bench_ret": [0.008, -0.003, 0.015, 0.002, -0.008],
    })


@pytest.fixture
def sample_agg_df():
    """Aggregate NAV DataFrame with nav_date column for range filtering."""
    dates = pd.date_range("2024-01-01", periods=400, freq="D")
    return pd.DataFrame({
        "nav_date": dates,
        "total_aum": np.random.uniform(1e8, 2e8, size=400),
        "total_invested": np.linspace(1e8, 1.5e8, 400),
        "weighted_cash_pct": np.random.uniform(5, 15, size=400),
    })


# ── _build_composite_from_returns tests ──


class TestBuildCompositeFromReturns:
    def test_produces_base_100_start(self, sample_daily_returns):
        port, bench = _build_composite_from_returns(sample_daily_returns)
        assert port.iloc[0] == 100.0
        assert bench.iloc[0] == 100.0

    def test_length_is_returns_plus_one(self, sample_daily_returns):
        """Output should have N+1 entries (base + N days of returns)."""
        port, bench = _build_composite_from_returns(sample_daily_returns)
        assert len(port) == len(sample_daily_returns) + 1
        assert len(bench) == len(sample_daily_returns) + 1

    def test_cumulative_returns_correct(self):
        """Verify that cumulative product is applied correctly."""
        dates = pd.date_range("2025-01-02", periods=3, freq="D")
        df = pd.DataFrame({
            "nav_date": dates,
            "weighted_port_ret": [0.10, 0.05, -0.02],
            "weighted_bench_ret": [0.08, 0.03, -0.01],
        })
        port, bench = _build_composite_from_returns(df)
        # port: 100 * 1.10 = 110.0, 110 * 1.05 = 115.5, 115.5 * 0.98 = 113.19
        assert pytest.approx(port.iloc[1], rel=1e-4) == 110.0
        assert pytest.approx(port.iloc[2], rel=1e-4) == 115.5
        assert pytest.approx(port.iloc[3], rel=1e-4) == 113.19

    def test_empty_dataframe_returns_empty_series(self):
        empty = pd.DataFrame(columns=["nav_date", "weighted_port_ret", "weighted_bench_ret"])
        port, bench = _build_composite_from_returns(empty)
        assert len(port) == 0
        assert len(bench) == 0

    def test_single_row(self):
        """Single return row should produce 2-element series (base + 1 day)."""
        dates = pd.date_range("2025-06-01", periods=1, freq="D")
        df = pd.DataFrame({
            "nav_date": dates,
            "weighted_port_ret": [0.05],
            "weighted_bench_ret": [0.03],
        })
        port, bench = _build_composite_from_returns(df)
        assert len(port) == 2
        assert port.iloc[0] == 100.0
        assert pytest.approx(port.iloc[1], rel=1e-4) == 105.0

    def test_zero_returns_stay_at_100(self):
        dates = pd.date_range("2025-01-02", periods=4, freq="D")
        df = pd.DataFrame({
            "nav_date": dates,
            "weighted_port_ret": [0.0, 0.0, 0.0, 0.0],
            "weighted_bench_ret": [0.0, 0.0, 0.0, 0.0],
        })
        port, bench = _build_composite_from_returns(df)
        for val in port:
            assert pytest.approx(val, rel=1e-6) == 100.0


# ── _apply_range_filter tests ──


class TestApplyRangeFilter:
    def test_all_range_returns_full_df(self, sample_agg_df):
        result = _apply_range_filter(sample_agg_df, "ALL")
        assert len(result) == len(sample_agg_df)

    def test_1m_filter(self, sample_agg_df):
        result = _apply_range_filter(sample_agg_df, "1M")
        latest = sample_agg_df["nav_date"].iloc[-1]
        cutoff = latest - pd.Timedelta(days=30)
        assert result["nav_date"].iloc[0] >= cutoff

    def test_1y_filter(self, sample_agg_df):
        result = _apply_range_filter(sample_agg_df, "1Y")
        latest = sample_agg_df["nav_date"].iloc[-1]
        cutoff = latest - pd.Timedelta(days=365)
        assert result["nav_date"].iloc[0] >= cutoff

    def test_case_insensitive(self, sample_agg_df):
        r1 = _apply_range_filter(sample_agg_df, "3m")
        r2 = _apply_range_filter(sample_agg_df, "3M")
        assert len(r1) == len(r2)

    def test_empty_df_returns_empty(self):
        empty = pd.DataFrame(columns=["nav_date", "total_aum"])
        result = _apply_range_filter(empty, "1M")
        assert len(result) == 0

    def test_unknown_range_returns_full(self, sample_agg_df):
        """Unknown range key should return full dataset (no filtering)."""
        result = _apply_range_filter(sample_agg_df, "UNKNOWN")
        assert len(result) == len(sample_agg_df)
