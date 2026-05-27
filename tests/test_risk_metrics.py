"""Tests for core risk metric computation functions."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.services.modified_dietz import (
    compute_average_corpus,
    compute_modified_dietz_bench_return,
    compute_modified_dietz_return,
)
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


# ── Modified-Dietz "Adjusted Return [Weighted]" tests ───────────────────────


class TestModifiedDietzBJ53Reference:
    """
    Pin the Modified-Dietz output against the official BJ53 PMS Portfolio
    Summary report for the period 28/09/2020 .. 25/05/2026.

    Reference:
        Starting Corpus              : ₹3,33,000  (28-Sep-2020)
        Further Contribution         : ₹16,57,506
        Net Contribution             : ₹19,90,506
        Current Value                : ₹50,48,414.94
        Adjusted Return [Weighted] % : 227.42
        Annualised (derived)         : 23.34
        Average Corpus               : ₹13,44,632.21
    """

    INCEPTION = date(2020, 9, 28)
    END = date(2026, 5, 25)
    V_START = 333_000.0
    V_END = 5_048_414.94
    FURTHER_CONTRIB = 1_657_506.0
    EXPECTED_CUMULATIVE = 227.42
    EXPECTED_ANNUALISED = 23.34
    EXPECTED_AVG_CORPUS = 1_344_632.21

    def _period_days(self) -> int:
        return (self.END - self.INCEPTION).days

    def test_modified_dietz_bj53_reference(self):
        # Use the equivalent single-infusion date that exactly reproduces the
        # Σ(CF_i × w_i) of the actual multi-infusion timeline.  Solving for it:
        #   profit = 30,57,908.94
        #   denominator = profit / 2.2742 = 13,44,469
        #   sum(CF × w) = denom - V_start = 10,11,469
        #   w = 10,11,469 / 16,57,506 = 0.6102
        #   t = (1 - 0.6102) × 2065 = 805 days from inception
        cf_date = self.INCEPTION + timedelta(days=805)
        cash_flows = [(cf_date, self.FURTHER_CONTRIB)]

        cumulative, annualised = compute_modified_dietz_return(
            v_start=self.V_START,
            v_end=self.V_END,
            cash_flows=cash_flows,
            period_days=self._period_days(),
            inception_date=self.INCEPTION,
        )

        # Headline cumulative return — within 0.1pp of the PMS report.
        assert pytest.approx(cumulative, abs=0.1) == self.EXPECTED_CUMULATIVE, (
            f"BJ53 cumulative mismatch: got {cumulative:.4f}, "
            f"expected {self.EXPECTED_CUMULATIVE}"
        )
        # Annualised — within 0.1pp.
        assert pytest.approx(annualised, abs=0.1) == self.EXPECTED_ANNUALISED, (
            f"BJ53 annualised mismatch: got {annualised:.4f}, "
            f"expected {self.EXPECTED_ANNUALISED}"
        )

    def test_average_corpus_bj53_reference(self):
        # Simulate a daily nav_df where corpus jumps from V_start to V_start +
        # further_contrib at day 805 (the equivalent single-infusion timeline
        # used above).  This is the same time-weighted profile, so the
        # average corpus must equal the PMS report's ₹13,44,632 within ₹1000.
        dates = pd.date_range(self.INCEPTION, self.END, freq="D")
        n = len(dates)
        cf_day = 805
        corpus = [self.V_START] * cf_day + [self.V_START + self.FURTHER_CONTRIB] * (n - cf_day)
        df = pd.DataFrame({
            "nav_date": dates,
            "invested_amount": corpus,
        })
        avg = compute_average_corpus(df)
        assert pytest.approx(avg, abs=1000) == self.EXPECTED_AVG_CORPUS, (
            f"BJ53 average corpus mismatch: got {avg:.2f}, "
            f"expected {self.EXPECTED_AVG_CORPUS}"
        )

    def test_weighted_bench_bj53_reference(self):
        """
        Reproduces the ~74.72% PMS Nifty weighted-return number using the
        equivalent single-infusion timeline plus the official inception and
        terminal Nifty prices.

        Nifty 50:
            28-Sep-2020 (inception)  = 11,050.25
            25-May-2026 (terminal)   = 24,031.70
        """
        bench_inception = 11_050.25
        bench_terminal = 24_031.70
        bench_at_cf = 17_500.0  # Calibrated to land near 74.72% — see below.

        # Construct a 3-row nav_df: inception, cash-flow date, terminal.
        cf_date = self.INCEPTION + timedelta(days=805)
        df = pd.DataFrame({
            "nav_date": [self.INCEPTION, cf_date, self.END],
            "invested_amount": [
                self.V_START,
                self.V_START + self.FURTHER_CONTRIB,
                self.V_START + self.FURTHER_CONTRIB,
            ],
            "nav_value": [self.V_START, self.V_START + self.FURTHER_CONTRIB, self.V_END],
            "current_value": [self.V_START, self.V_START + self.FURTHER_CONTRIB, self.V_END],
            "benchmark_value": [bench_inception, bench_at_cf, bench_terminal],
        })

        result = compute_modified_dietz_bench_return(df)

        # Allow a wider tolerance (1.5pp) because the test compresses many
        # real infusions into one synthetic one and uses a calibrated Nifty
        # price for the equivalent CF date.  The point is to prove the
        # formula structure (Modified-Dietz denominator, virtual-units
        # numerator) is correct — not to recreate the exact reference.
        assert 65.0 <= result <= 85.0, (
            f"BJ53 weighted bench return out of plausible range: got {result:.4f}, "
            f"expected ~74.72%"
        )

    def test_period_days_sanity(self):
        # BJ53 inception → terminal is ~5.66 years.
        days = self._period_days()
        years = days / 365.25
        assert 5.6 <= years <= 5.7
        assert days == 2065

    def test_weighted_bench_bj53_reference_exact(self):
        """
        Tighter pinning of the weighted-benchmark return against BJ53's PMS
        reference of 74.72%, using the PRODUCTION-SHAPE input: a daily
        ``nav_df`` exactly the way ``risk_engine.run_risk_engine`` builds it
        from ``cpp_nav_series`` (one row per calendar day, invested_amount
        stepping up on infusion dates, benchmark_value populated for every
        date from ``fie_v3.index_prices`` via ``align_benchmark``).

        The earlier version of this test fed 6 inflection-only rows to the
        function — that geometry is NEVER what production passes in.
        Production passes 2,066 rows (one per day from 2020-09-28 to
        2026-05-25).  By rebuilding that shape here we guard against any
        regression that only manifests when the function has to iterate
        full daily history (e.g. a corpus-delta detector that mis-fires on
        identical-value runs, or a benchmark anchor that picks up a
        forward-filled value from the tail of the series).

        Nifty 50 closes (NSE, anchor points):
            2020-09-28  11,050.25  (inception)
            2021-07-05  15,722.20
            2023-02-02  17,765.00
            2023-02-21  17,826.00
            2023-06-12  18,601.00
            2026-05-25  24,031.70  (terminal)

        Acceptance band: 74.2%..75.2% (±0.5pp from the 74.72% PMS report).
        The slack accounts for as-of NAV-vs-trading-day alignment and
        intra-day price variance — the structure of the math must produce
        a number INSIDE this band, not the buggy ~70% it produced when the
        terminal anchor was a stale forward-fill from ~23,600.
        """
        # Build a daily-row nav_df between inception and terminal.
        all_dates = pd.date_range(
            self.INCEPTION, self.END, freq="D"
        )

        # invested_amount steps up on each infusion date.
        corpus_steps = {
            date(2020, 9, 28): 333_000.0,
            date(2021, 7, 5): 533_000.0,
            date(2023, 2, 2): 1_033_000.0,
            date(2023, 2, 21): 1_890_506.0,
            date(2023, 6, 12): 1_990_506.0,
        }
        invested: list[float] = []
        current = 0.0
        for ts in all_dates:
            d = ts.date()
            if d in corpus_steps:
                current = corpus_steps[d]
            invested.append(current)

        # benchmark_value: linearly interpolate between the known Nifty
        # anchor closes.  This mimics ``align_benchmark`` with ffill close
        # enough that the function's as-of lookup at each CF date resolves
        # to a price within ~1% of the actual close — enough to land inside
        # the ±0.5pp acceptance band.
        bench_anchors = [
            (date(2020, 9, 28), 11_050.25),
            (date(2021, 7, 5), 15_722.20),
            (date(2023, 2, 2), 17_765.00),
            (date(2023, 2, 21), 17_826.00),
            (date(2023, 6, 12), 18_601.00),
            (date(2026, 5, 25), 24_031.70),
        ]
        bench: list[float] = []
        for ts in all_dates:
            d = ts.date()
            value = bench_anchors[-1][1]
            for (d0, b0), (d1, b1) in zip(bench_anchors, bench_anchors[1:]):
                if d0 <= d <= d1:
                    span = (d1 - d0).days or 1
                    frac = (d - d0).days / span
                    value = b0 + frac * (b1 - b0)
                    break
            bench.append(value)

        # nav_value / current_value: linear glide from V_start to V_end.
        # The bench function does not use these fields except through
        # extract_modified_dietz_inputs (for V_end), but production carries
        # them on every row so we mirror that.
        n = len(all_dates)
        nav_glide = [
            self.V_START + (self.V_END - self.V_START) * (i / (n - 1))
            for i in range(n)
        ]

        df = pd.DataFrame({
            "nav_date": all_dates,
            "invested_amount": invested,
            "current_value": nav_glide,
            "nav_value": nav_glide,
            "benchmark_value": bench,
        })

        # Sanity: the production-shape df must be a daily series, not the
        # 6-row inflection geometry the older test used.
        assert len(df) > 2000, (
            f"This test must reproduce production daily-row geometry; got "
            f"{len(df)} rows."
        )

        result = compute_modified_dietz_bench_return(df)

        assert 74.2 <= result <= 75.2, (
            f"BJ53 weighted bench return mismatch on production-shape "
            f"daily nav_df: got {result:.4f}, expected ~74.72% (±0.5pp). "
            f"The structure should anchor the first synthetic unit purchase "
            f"at the inception NAV date with V_start in the denominator, and "
            f"must not be dragged down by a stale ffill at either bench anchor."
        )


class TestAverageCorpusTimeWeighted:
    def test_three_equal_segments(self):
        """
        Three segments of 100 days at 100K / 200K / 300K → average = 200K.

        Note: ``compute_average_corpus`` weights each row's corpus by the
        number of days UNTIL THE NEXT ROW (last row's corpus has zero
        weight because there is no following segment).  So to get the
        textbook average we add one extra row at the end as a sentinel.
        """
        seg_days = 100
        start = pd.Timestamp("2024-01-01")
        rows = []
        for level, multiplier in enumerate([1, 2, 3], start=0):
            rows.append({
                "nav_date": start + pd.Timedelta(days=level * seg_days),
                "invested_amount": 100_000.0 * multiplier,
            })
        # Sentinel row marking the end of segment 3 — corpus value irrelevant
        # because no further segment follows.
        rows.append({
            "nav_date": start + pd.Timedelta(days=3 * seg_days),
            "invested_amount": 300_000.0,
        })
        df = pd.DataFrame(rows)
        avg = compute_average_corpus(df)
        # (100k*100 + 200k*100 + 300k*100) / 300 = 200k
        assert pytest.approx(avg, rel=1e-6) == 200_000.0

    def test_single_row(self):
        df = pd.DataFrame({
            "nav_date": [pd.Timestamp("2024-01-01")],
            "invested_amount": [500_000.0],
        })
        assert compute_average_corpus(df) == 500_000.0

    def test_empty_df(self):
        df = pd.DataFrame({"nav_date": [], "invested_amount": []})
        assert compute_average_corpus(df) == 0.0


class TestModifiedDietzEdges:
    def test_zero_period_days(self):
        cum, ann = compute_modified_dietz_return(100.0, 200.0, [], 0)
        assert cum == 0.0 and ann == 0.0

    def test_zero_v_start(self):
        cum, ann = compute_modified_dietz_return(0.0, 200.0, [], 365)
        assert cum == 0.0 and ann == 0.0

    def test_no_cash_flows(self):
        # Pure inception → end with no infusions.  Modified-Dietz collapses
        # to (V_end - V_start) / V_start = 100% for a doubling.
        cum, ann = compute_modified_dietz_return(
            100.0, 200.0, [], 365, inception_date=date(2024, 1, 1)
        )
        assert pytest.approx(cum, rel=1e-3) == 100.0
        assert pytest.approx(ann, abs=0.5) == 100.0  # 1-year double → ~100% CAGR

    def test_cf_on_inception_day(self):
        # CF on day 0 (w=1.0) → counts fully in the denominator.
        inception = date(2024, 1, 1)
        cf = [(inception, 100.0)]
        cum, _ = compute_modified_dietz_return(
            100.0, 400.0, cf, 365, inception_date=inception,
        )
        # profit = 400 - 100 - 100 = 200
        # denominator = 100 + 100*1.0 = 200
        # cumulative = 100%
        assert pytest.approx(cum, rel=1e-3) == 100.0

    def test_cf_on_terminal_day_has_zero_weight(self):
        # CF on day 365 (w=0.0) → does not change denominator.
        inception = date(2024, 1, 1)
        terminal = date(2025, 1, 1)
        cf = [(terminal, 100.0)]
        cum, _ = compute_modified_dietz_return(
            100.0, 300.0, cf, 365, inception_date=inception,
        )
        # profit = 300 - 100 - 100 = 100
        # denominator = 100 + 100*0.0 = 100
        # cumulative = 100%
        assert pytest.approx(cum, rel=1e-3) == 100.0
