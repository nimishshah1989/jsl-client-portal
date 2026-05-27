"""Sanity-check regression tests for the Performance Summary table.

These tests assert that the *rendered* numbers fall in plausible ranges,
not just that the formulas are syntactically correct. They cover the three
bugs visible on the production dashboard on 2026-05-26:

  A. Benchmark series stored flat (Abs Return = +0.05% for every period)
     because sparse fetches were forward-filled across years.
  B. 3M/6M/1Y/2Y/3Y/4Y rows collapsed to the inception slice for clients
     whose history was shorter than the period window.
  C. 5Y == Since Inception (a consequence of B for sub-5Y clients).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.services.benchmark_service import align_benchmark
from backend.services.risk_engine import compute_all_metrics, performance_table


# ───────────────────────────── helpers ──────────────────────────────────

def _make_nav_df(days: int, *, seed: int = 42) -> pd.DataFrame:
    """Build a synthetic nav_df with the columns risk_engine expects."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=days, freq="D")
    # Geometric brownian-ish drift up
    daily_ret = rng.normal(0.0008, 0.012, size=days)
    nav = 1_000_000 * np.cumprod(1.0 + daily_ret)
    bench = 18_000 * np.cumprod(1.0 + rng.normal(0.0005, 0.010, size=days))
    return pd.DataFrame({
        "nav_date": dates,
        "nav_value": nav,
        "invested_amount": np.full(days, 1_000_000.0),
        "benchmark_value": bench,
        "twr_value": (nav / nav[0]) * 100.0,
    })


# ─────────────────── Bug B: insufficient-history rows ───────────────────

def test_performance_table_returns_na_for_periods_longer_than_history():
    """Clients with ~60 days of history must NOT see populated 6M/1Y/2Y/3Y/4Y/5Y rows.

    The prior behaviour was to silently reuse the full inception slice for
    every longer period, making 6 different rows show identical numbers.
    """
    nav_df = _make_nav_df(days=60)
    rows = performance_table(nav_df)
    by_period = {r["period"]: r for r in rows}

    # 1M MUST be computed (we have 60 days).
    assert by_period["1 Month"]["port_abs_return"] is not None

    # All longer windows MUST be None.
    for label in ("6 Months", "1 Year", "2 Years", "3 Years", "4 Years", "5 Years"):
        row = by_period[label]
        assert row["port_abs_return"] is None, f"{label} should be N/A but got {row['port_abs_return']}"
        assert row["port_cagr"] is None
        assert row["port_volatility"] is None
        assert row["port_max_dd"] is None
        assert row["port_sharpe"] is None
        assert row["port_sortino"] is None
        assert row["bench_abs_return"] is None
        assert row["bench_volatility"] is None

    # Inception must still compute.
    assert by_period["Since Inception"]["port_abs_return"] is not None


# ─────────── Bug B/C: period rows must be independent of inception ───────────

def test_performance_table_period_independence():
    """With genuine multi-year history, 1Y/2Y/3Y/4Y/5Y rows must all differ.

    If any two agree to 4 decimal places, the slicer is broken (the bug that
    produced identical Port Abs = -0.19% across 3M…4Y on the production dashboard).
    """
    # 6 years of varied daily returns
    rng = np.random.default_rng(7)
    days = 365 * 6 + 10
    dates = pd.date_range("2019-01-01", periods=days, freq="D")
    # Inject regime shifts so each trailing window has a different return profile
    base = rng.normal(0.0003, 0.010, size=days)
    base[0 : days // 6] += 0.003       # year 1 boom
    base[days // 6 : 2 * days // 6] -= 0.003  # year 2 bust
    base[2 * days // 6 : 3 * days // 6] += 0.001
    base[3 * days // 6 : 4 * days // 6] += 0.002
    base[4 * days // 6 : 5 * days // 6] -= 0.001
    base[5 * days // 6 :] += 0.0015
    nav = 1_000_000 * np.cumprod(1.0 + base)
    bench = 18_000 * np.cumprod(1.0 + rng.normal(0.0004, 0.009, size=days))

    nav_df = pd.DataFrame({
        "nav_date": dates,
        "nav_value": nav,
        "invested_amount": np.full(days, 1_000_000.0),
        "benchmark_value": bench,
        "twr_value": (nav / nav[0]) * 100.0,
    })

    rows = performance_table(nav_df)
    by_period = {r["period"]: r for r in rows}

    # All these rows must be populated (we have 6Y of data).
    period_labels = ("1 Year", "2 Years", "3 Years", "4 Years", "5 Years")
    values = []
    for lbl in period_labels:
        v = by_period[lbl]["port_abs_return"]
        assert v is not None, f"{lbl} should be populated"
        values.append(round(float(v), 4))

    # No two trailing periods should agree to 4 decimal places. With varied
    # daily returns across 6 years this is essentially impossible by chance.
    assert len(set(values)) == len(values), (
        f"Period rows collapsed to identical values: {dict(zip(period_labels, values))}"
    )


# ─────────────── Bug A: sparse benchmark must not propagate flat ────────────

def test_yfinance_alignment_does_not_propagate_single_value():
    """A benchmark source with only 2 valid rows must not be ffilled across years.

    Reproduces the production bug: with 2 nearby source rows, the unbounded
    ffill+bfill produced a near-flat series across ~5 years (Vol 0.5%,
    Abs Return +0.05% — the exact numbers from the screenshot).
    The fix returns an EMPTY series rather than write flat data.
    """
    # Nav range = 4 years of daily dates.
    nav_dates = pd.date_range("2021-01-01", "2025-01-01", freq="D")
    # Source = only 2 rows clustered near the start.
    src_dates = pd.DatetimeIndex(["2021-01-04", "2021-01-05"])
    src = pd.DataFrame({"close": [18_000.0, 18_010.0]}, index=src_dates)

    aligned = align_benchmark(nav_dates, src)

    # Must NOT publish a flat series. Either empty (preferred) or with
    # genuine NaN gaps; either way, distinct non-NaN values must be < 2 (we
    # refuse) OR the aligned series should be empty.
    non_na = aligned.dropna()
    if len(non_na) > 0:
        # If any values are published, the published-cell vol can't be near-zero.
        ret = non_na.pct_change().dropna()
        annualised_vol_pct = float(ret.std() * np.sqrt(252) * 100) if len(ret) > 1 else 0.0
        # Either we have <2 distinct values (caught by sanity guard) OR no
        # cells published the same value across the entire span.
        assert non_na.nunique() >= 2, "Aligned series collapsed to a single value"
        # And the published span can't be all of the nav range.
        assert len(non_na) < len(nav_dates), (
            "Sparse source was forward-filled to cover entire 4-year nav range — "
            "produces a near-flat series indistinguishable from no benchmark data"
        )
    # If empty, that is exactly what we want — caller will log "benchmark unavailable".


def test_benchmark_unavailable_emits_empty_not_flat_zero():
    """When the benchmark source has 0 rows, align_benchmark returns empty."""
    nav_dates = pd.date_range("2022-01-01", periods=500, freq="D")
    src = pd.DataFrame({"close": []}, index=pd.DatetimeIndex([]))

    aligned = align_benchmark(nav_dates, src)

    # Must NOT be a flat-zero series — must be empty / all-NaN.
    assert aligned.dropna().empty, (
        "Empty benchmark source must yield empty aligned series, not flat zeros"
    )


# ─────────────── Bug A inverse: realistic benchmark sanity ──────────────

def test_benchmark_realistic_sanity_check():
    """With a realistic 5-year NIFTY-like series, computed metrics must be plausible.

    This is the test that would have caught Bug A: had it existed, the
    flat-series bug would have produced Bench Abs Return ≈ +0.05% and
    Bench Vol ≈ 0.5%, both wildly outside the asserted ranges.
    """
    # Build a 5y daily series with ~14% annualised vol and ~+80% total return.
    rng = np.random.default_rng(123)
    days = 365 * 5 + 1
    dates = pd.date_range("2020-01-01", periods=days, freq="D")
    # Target: tiny positive drift, ~0.9%/day stdev → ~14% annual vol, ~80% total return.
    daily = rng.normal(0.00035, 0.009, size=days)
    bench = 10_000 * np.cumprod(1.0 + daily)
    # Portfolio: small alpha
    port = 1_000_000 * np.cumprod(1.0 + daily + 0.0001)

    nav_df = pd.DataFrame({
        "nav_date": dates,
        "nav_value": port,
        "invested_amount": np.full(days, 1_000_000.0),
        "benchmark_value": bench,
        "twr_value": (port / port[0]) * 100.0,
    })

    rows = performance_table(nav_df)
    by_period = {r["period"]: r for r in rows}

    # 5Y row must reflect a realistic benchmark, not a flat one.
    five_y = by_period["5 Years"]
    bench_abs = float(five_y["bench_abs_return"])
    bench_vol = float(five_y["bench_volatility"])
    bench_dd = float(five_y["bench_max_dd"])

    assert 40.0 <= bench_abs <= 200.0, (
        f"5Y bench abs return = {bench_abs:.2f}% — out of plausible range for "
        f"a realistic 5Y NIFTY-like series. (The bug produced +0.05%.)"
    )
    assert 8.0 <= bench_vol <= 25.0, (
        f"5Y bench volatility = {bench_vol:.2f}% — out of plausible range. "
        f"(The bug produced ~0.5%.)"
    )
    assert bench_dd < -3.0, (
        f"5Y bench max DD = {bench_dd:.2f}% — too shallow. A realistic 5Y "
        f"benchmark should have at least one >3% drawdown. (The bug produced ~-0.14%.)"
    )


# ────── Since-Inception overrides: Modified-Dietz, not TWR base-100 ──────

def _make_bj53_shape_nav_df(days: int = 2000) -> pd.DataFrame:
    """Build a nav_df that mimics BJ53's shape: a single mid-period corpus
    infusion that makes TWR-base-100 and Modified-Dietz diverge meaningfully.

    Without the divergence, this regression test is vacuous — the override is
    a no-op when the two methods agree (no corpus changes).
    """
    rng = np.random.default_rng(2026)
    dates = pd.date_range("2020-09-28", periods=days, freq="D")
    daily_ret = rng.normal(0.0010, 0.012, size=days)
    nav = 333_000.0 * np.cumprod(1.0 + daily_ret)

    # Corpus infusion ~40% of the way through.
    infusion_day = int(days * 0.4)
    infusion = 1_657_506.0
    nav[infusion_day:] = nav[infusion_day:] + infusion

    invested = np.full(days, 333_000.0)
    invested[infusion_day:] = 333_000.0 + infusion

    bench = 11_000 * np.cumprod(1.0 + rng.normal(0.0004, 0.010, size=days))

    return pd.DataFrame({
        "nav_date": dates,
        "nav_value": nav,
        "invested_amount": invested,
        "current_value": nav,
        "benchmark_value": bench,
        "cash_pct": np.full(days, 5.0),
        # twr_value as production builds it via compute_twr_series; for this
        # synthetic test we use a simple inception-base ratio of nav_value
        # which is good enough — compute_all_metrics will use it via the
        # value_col branch.
        "twr_value": (nav / nav[0]) * 100.0,
    })


def test_perf_table_inception_uses_modified_dietz():
    """The Performance Summary "Since Inception" row must show the same
    cumulative-return and CAGR numbers as the dashboard's headline Summary
    card — i.e. the Modified-Dietz "Adjusted Return [Weighted]" figures,
    not the TWR base-100 simple ratio.

    Bug fixed: production dashboard for BJ53 showed 227.47% on the Summary
    card but 316.30% on the Perf Table Since-Inception row because the two
    columns were reading from different computation methods.
    """
    nav_df = _make_bj53_shape_nav_df()
    metrics = compute_all_metrics(nav_df)

    assert "return_inception" in metrics
    assert "cagr_inception" in metrics
    assert metrics["return_inception"] == metrics["absolute_return"], (
        f"return_inception ({metrics['return_inception']:.4f}) must equal "
        f"absolute_return ({metrics['absolute_return']:.4f}) — both should "
        "be the Modified-Dietz cumulative figure shown on the Summary card."
    )
    assert metrics["cagr_inception"] == metrics["cagr"], (
        f"cagr_inception ({metrics['cagr_inception']:.4f}) must equal "
        f"cagr ({metrics['cagr']:.4f}) — both should be the Modified-Dietz "
        "annualised figure shown on the Summary card."
    )


def test_perf_table_trailing_periods_unchanged():
    """Trailing-period (1M..5Y) rows in the Perf Table must STAY on TWR.

    Those windows already match the PMS report under the TWR base-100
    method, so the inception-only fix must not bleed into them. This is the
    regression guard against someone "fixing" the wrong thing later.
    """
    nav_df = _make_bj53_shape_nav_df()
    metrics = compute_all_metrics(nav_df)

    md_cumulative = metrics["absolute_return"]
    md_annualised = metrics["cagr"]

    # On a BJ53-shape series with a corpus infusion, TWR base-100 and
    # Modified-Dietz produce materially different cumulative returns.  Any
    # trailing-period field that happens to coincide with absolute_return
    # would indicate the override leaked.
    for suffix in ("1m", "3m", "6m", "1y", "2y", "3y", "4y", "5y"):
        ret_key = f"return_{suffix}"
        cagr_key = f"cagr_{suffix}"
        # Skip insufficient-history periods (the value can be None).
        if metrics.get(ret_key) is None:
            continue
        assert metrics[ret_key] != md_cumulative, (
            f"{ret_key} ({metrics[ret_key]:.4f}) must remain TWR-based — "
            f"it equals the Modified-Dietz cumulative ({md_cumulative:.4f}), "
            "indicating the inception override leaked into trailing periods."
        )
        if metrics.get(cagr_key) is not None:
            assert metrics[cagr_key] != md_annualised, (
                f"{cagr_key} ({metrics[cagr_key]:.4f}) must remain TWR-based "
                f"— it equals the Modified-Dietz annualised ({md_annualised:.4f})."
            )
