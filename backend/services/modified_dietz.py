"""
Modified-Dietz "Adjusted Return [Weighted]" computation.

Implements the headline cumulative-return methodology used on the PMS
backoffice Portfolio Summary report.  Clients see this same number on
their statements so the portal must match it to the basis point.

Formula
-------

    Adjusted Return [Weighted] %
        = (V_end - V_start - sum(CF_i)) / (V_start + sum(CF_i * w_i)) * 100

Where
    V_start   = inception-day capital (starting corpus from cpp_nav_series)
    V_end     = latest portfolio value (current NAV)
    CF_i      = each subsequent capital infusion / withdrawal
    w_i       = (T - t_i) / T  — fraction of the period the cash flow has
                been deployed, with T = full period in days and t_i = days
                from inception to CF_i.

The same denominator is used for the cash-flow-weighted benchmark
("Absolute Return S&P CNX Nifty [Weighted] %") so the two numbers are
directly comparable.

References
----------
- BJ53 reference report (Investment Summary, 28-Sep-2020 .. 25-May-2026):
      Adjusted Return [Weighted] % = 227.42
      Absolute Return Nifty [Weighted] % = 74.72
      Average Corpus = ₹13,44,632.21
- See ``tests/test_risk_metrics.py`` for the BJ53 pinning tests.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd


# ── Helpers ─────────────────────────────────────────────────────────────────


def _to_pydate(value) -> date:
    """Normalise pandas Timestamp / numpy datetime64 / datetime → date."""
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).date()
    return value


def extract_modified_dietz_inputs(
    nav_df: pd.DataFrame,
) -> tuple[float, float, list[tuple[date, float]], int]:
    """
    Extract Modified-Dietz inputs from an in-memory nav_df.

    Reads V_start from the FIRST ``invested_amount`` (the inception-day
    capital), V_end from the LAST ``current_value`` (or ``nav_value`` if
    current_value is missing/zero), and subsequent corpus deltas as cash
    flows.  The first row is V_start and is NOT included in ``cash_flows``;
    only further infusions/withdrawals are.

    Returns
    -------
    (v_start, v_end, cash_flows, period_days)
        cash_flows is a list of (date, amount) tuples in chronological
        order (excluding the initial capital).  Amounts are positive for
        inflows and negative for outflows.
        period_days is the inclusive day-count from inception to latest.
    """
    if len(nav_df) < 2:
        return 0.0, 0.0, [], 0

    df = nav_df.sort_values("nav_date").reset_index(drop=True)
    v_start = float(df["invested_amount"].iloc[0])

    # Prefer current_value (= portfolio mark-to-market) if available, else nav_value.
    last = df.iloc[-1]
    cv = float(last.get("current_value", 0.0) or 0.0) if "current_value" in df.columns else 0.0
    if cv > 0:
        v_end = cv
    elif "nav_value" in df.columns:
        v_end = float(last["nav_value"])
    else:
        # Synthetic test dataframes may carry only invested_amount; fall back
        # to the latest corpus level so callers that only care about cash
        # flows + denominator (e.g. weighted-bench code path) still work.
        v_end = float(last["invested_amount"])

    cash_flows: list[tuple[date, float]] = []
    prev_corpus = v_start
    for i in range(1, len(df)):
        corpus = float(df["invested_amount"].iloc[i])
        delta = corpus - prev_corpus
        if abs(delta) > 1e-4:
            flow_date = _to_pydate(df["nav_date"].iloc[i])
            cash_flows.append((flow_date, delta))
            prev_corpus = corpus

    start_date = _to_pydate(df["nav_date"].iloc[0])
    end_date = _to_pydate(df["nav_date"].iloc[-1])
    period_days = (end_date - start_date).days

    return v_start, v_end, cash_flows, period_days


# ── Core formulae ───────────────────────────────────────────────────────────


def compute_modified_dietz_return(
    v_start: float,
    v_end: float,
    cash_flows: list[tuple[date, float]],
    period_days: int,
    *,
    inception_date: date | None = None,
) -> tuple[float, float]:
    """
    Compute the Modified-Dietz cumulative and annualised return.

    Parameters
    ----------
    v_start
        Inception-day capital (starting corpus).
    v_end
        Latest portfolio value.
    cash_flows
        List of (date, amount) tuples for capital infusions (positive) and
        withdrawals (negative) AFTER inception.  Should NOT include
        ``v_start`` itself or the terminal ``-v_end`` flow.
    period_days
        Total period length in days (latest_date - inception_date).
    inception_date
        Inception date, used to compute weights for each cash flow.  If
        ``None``, the earliest date in ``cash_flows`` is used minus an
        offset to make all weights valid.  Callers should pass this
        explicitly when known.

    Returns
    -------
    (cumulative_pct, annualised_pct)
        Cumulative return as percentage (e.g., 227.42 for BJ53).
        Annualised return derived from the cumulative via
        ``(1 + cum)^(1/years) - 1`` with ``years = period_days / 365.25``.
        Both ``0.0`` if inputs are degenerate.
    """
    if period_days <= 0 or v_start <= 0:
        return 0.0, 0.0

    # Resolve inception date if not given.  We need it to compute t_i for
    # each cash flow.  When omitted, take it as (earliest_cf_date - 1) so
    # all CFs sit strictly inside the period — this only kicks in for
    # synthetic test inputs without dates.
    if inception_date is None and cash_flows:
        inception_date = min(cf[0] for cf in cash_flows)

    sum_cf = 0.0
    sum_weighted_cf = 0.0
    for cf_date, amount in cash_flows:
        amt = float(amount)
        sum_cf += amt
        if inception_date is None:
            # No reference point — weight every flow at 1.0 (treat as start).
            sum_weighted_cf += amt
            continue
        t_i = (cf_date - inception_date).days
        # Clamp to [0, period_days] to keep weights well-defined for
        # edge-of-period flows that may sit on the same calendar day as
        # inception or the terminal date.
        t_i = max(0, min(period_days, t_i))
        w_i = (period_days - t_i) / period_days
        sum_weighted_cf += amt * w_i

    denominator = v_start + sum_weighted_cf
    if denominator <= 0:
        return 0.0, 0.0

    profit = v_end - v_start - sum_cf
    cumulative_pct = (profit / denominator) * 100.0

    # Annualise: (1 + cum_ret) ^ (1/years) - 1
    years = period_days / 365.25
    cum_ret = cumulative_pct / 100.0
    if 1 + cum_ret <= 0 or years <= 0:
        annualised_pct = 0.0
    else:
        annualised_pct = ((1 + cum_ret) ** (1.0 / years) - 1) * 100.0

    return cumulative_pct, annualised_pct


def compute_average_corpus(nav_df: pd.DataFrame) -> float:
    """
    Time-weighted mean corpus across the period.

    Each row of ``nav_df`` represents the invested_amount that was held
    from that date up to (but not including) the next row.  The average
    weights each level by the number of days it persisted.

        Average_Corpus = Σ(corpus_segment_i * days_i) / Σ(days_i)

    For BJ53 this yields ₹13,44,632.

    Returns 0.0 if the dataframe has fewer than 2 rows or no positive
    span.  Float (caller converts to Decimal before DB write).
    """
    if nav_df is None or len(nav_df) == 0:
        return 0.0

    df = nav_df.sort_values("nav_date").reset_index(drop=True)
    if len(df) == 1:
        return float(df["invested_amount"].iloc[0])

    dates = pd.to_datetime(df["nav_date"]).values
    corpus = df["invested_amount"].astype(float).values

    total_days = (dates[-1] - dates[0]).astype("timedelta64[D]").astype(int)
    if total_days <= 0:
        return float(corpus[-1])

    weighted_sum = 0.0
    for i in range(len(corpus) - 1):
        seg_days = (dates[i + 1] - dates[i]).astype("timedelta64[D]").astype(int)
        if seg_days <= 0:
            continue
        weighted_sum += float(corpus[i]) * seg_days

    return weighted_sum / total_days if total_days > 0 else 0.0


def compute_modified_dietz_bench_return(
    nav_df: pd.DataFrame,
) -> float:
    """
    Cash-flow-weighted benchmark return matching PMS
    "Absolute Return S&P CNX Nifty [Weighted] %".

    Builds a synthetic portfolio that buys Nifty units at the same dates
    and sizes as the client's actual cash flows, marks the units to
    market on the latest date, and applies the SAME Modified-Dietz
    denominator as the portfolio.  This makes portfolio vs benchmark
    directly comparable for the client's actual capital-deployment
    timeline.

    Formula:
        nifty_units_t = v_start / bench_at_inception
                      + sum(CF_i / bench_at_CF_date)
        V_end_bench   = nifty_units * bench_at_latest
        weighted_bench_return =
            (V_end_bench - V_start - sum(CF_i))
            / (V_start + sum(CF_i * w_i))
            * 100

    Returns 0.0 if benchmark data is unavailable, inception bench price
    is missing, or the denominator collapses.
    """
    if nav_df is None or len(nav_df) < 2:
        return 0.0
    if "benchmark_value" not in nav_df.columns:
        return 0.0

    df = nav_df.sort_values("nav_date").reset_index(drop=True)
    bench_vals = df["benchmark_value"].astype(float)
    if bench_vals.sum() == 0 or bench_vals.isna().all():
        return 0.0

    inception_bench = float(bench_vals.iloc[0])
    latest_bench = float(bench_vals.iloc[-1])
    if inception_bench <= 0 or latest_bench <= 0:
        return 0.0

    v_start, _, cash_flows, period_days = extract_modified_dietz_inputs(df)
    if v_start <= 0 or period_days <= 0:
        return 0.0

    inception_date = _to_pydate(df["nav_date"].iloc[0])

    # Map each cash-flow date to its benchmark price by an as-of lookup
    # on the nav_df (the benchmark column is already date-aligned).
    bench_lookup = pd.Series(
        bench_vals.values,
        index=pd.to_datetime(df["nav_date"]).values,
    ).sort_index()

    # Buy units on inception with v_start.
    nifty_units = v_start / inception_bench
    sum_cf = 0.0
    sum_weighted_cf = 0.0
    for cf_date, amount in cash_flows:
        amt = float(amount)
        ts = pd.Timestamp(cf_date)
        # as-of: most recent benchmark price ≤ cf_date.
        try:
            bench_at_cf = float(bench_lookup.asof(ts))
        except KeyError:
            bench_at_cf = 0.0
        if bench_at_cf is None or np.isnan(bench_at_cf) or bench_at_cf <= 0:
            # No benchmark price on this date — skip (don't fabricate one).
            # The portfolio's CF is still recorded in sum_cf so the
            # denominator stays aligned with the portfolio's denominator.
            sum_cf += amt
            t_i = max(0, min(period_days, (cf_date - inception_date).days))
            sum_weighted_cf += amt * (period_days - t_i) / period_days
            continue
        nifty_units += amt / bench_at_cf
        sum_cf += amt
        t_i = max(0, min(period_days, (cf_date - inception_date).days))
        sum_weighted_cf += amt * (period_days - t_i) / period_days

    v_end_bench = nifty_units * latest_bench
    denominator = v_start + sum_weighted_cf
    if denominator <= 0:
        return 0.0

    profit_bench = v_end_bench - v_start - sum_cf
    return (profit_bench / denominator) * 100.0
