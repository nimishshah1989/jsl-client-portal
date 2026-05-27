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


_STUCK_RUN_MIN_LENGTH = 10  # consecutive identical bench rows that triggers "stuck"


def _resolve_anchor_bench(
    bench_series: pd.Series,
    target_date: pd.Timestamp,
    *,
    direction: str = "forward",
) -> float:
    """
    Return the benchmark value at ``target_date`` UNLESS that value is the
    tail of a long forward-filled / constant run, in which case fall through
    to the first value that breaks the constant.

    Why this exists: PR #21 documented that ``cpp_nav_series.benchmark_value``
    was stuck at a single value (23,643.50) for 87% of 384,883 NAV rows
    before the JIP ``index_prices`` repoint landed.  Until every client has
    been recomputed with the fresh benchmark backfill, the latest row of
    ``benchmark_value`` for some clients is still the stuck ffill value
    rather than the actual Nifty close on the latest NAV date.  Using that
    stuck value as ``latest_bench`` understates the synthetic Nifty portfolio
    at the terminal and drags the weighted-bench return down by several
    percentage points (BJ53: 74.72 expected → 70.41 observed in production).

    A long, perfectly-constant run hugging the anchor is the only signal we
    can detect without an external lookup; this routine deliberately does
    NOT touch anchors when neighbouring values disagree, so well-behaved
    series (and unit-test fixtures with distinct daily values) are
    unaffected.

    ``bench_series`` must be a date-indexed pd.Series of float bench prices,
    sorted ascending by index.
    """
    if target_date not in bench_series.index:
        return float(bench_series.iloc[-1] if direction == "backward" else bench_series.iloc[0])

    anchor_value = float(bench_series.loc[target_date])
    if anchor_value <= 0 or np.isnan(anchor_value):
        return anchor_value  # caller will guard against it.

    anchor_pos = bench_series.index.get_loc(target_date)

    # Count the contiguous run of values equal to anchor_value pinned to the
    # anchor side.  For the FORWARD (inception) anchor we walk outward FROM
    # row 0 — i.e. forwards in time — counting how many consecutive leading
    # rows share the anchor value.  For the BACKWARD (latest) anchor we walk
    # outward from the last row — i.e. backwards in time.
    if direction == "backward":
        # Anchor sits at the end; count identical trailing rows.
        run = 1
        i = anchor_pos - 1
        while i >= 0 and float(bench_series.iloc[i]) == anchor_value:
            run += 1
            i -= 1
        next_distinct_pos = i  # index of the first non-stuck row
    else:
        # Anchor sits at the start; count identical leading rows.
        run = 1
        i = anchor_pos + 1
        while i < len(bench_series) and float(bench_series.iloc[i]) == anchor_value:
            run += 1
            i += 1
        next_distinct_pos = i

    if run < _STUCK_RUN_MIN_LENGTH:
        # Not a long forward-filled run; the anchor is genuine — use it.
        return anchor_value

    if next_distinct_pos < 0 or next_distinct_pos >= len(bench_series):
        # The entire series is one constant value — nothing better to use.
        return anchor_value

    candidate = float(bench_series.iloc[next_distinct_pos])
    if candidate <= 0 or np.isnan(candidate):
        return anchor_value

    return candidate


def compute_modified_dietz_bench_return(
    nav_df: pd.DataFrame,
    *,
    inception_bench_override: float | None = None,
    latest_bench_override: float | None = None,
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

    The two ``*_override`` kwargs let callers (e.g. the async risk engine)
    inject an authoritative inception / latest Nifty close fetched directly
    from ``fie_v3.index_prices`` so the function does not silently use a
    forward-filled / stale ``benchmark_value`` from ``cpp_nav_series``.
    BJ53 production was hitting 70.41% (vs the 74.72% PMS reference)
    specifically because the terminal ``benchmark_value`` for the latest
    nav_date was a stale ffill of an earlier Nifty close — not the
    24,031.70 close on 2026-05-25 that the PMS report uses.

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

    bench_series = pd.Series(
        bench_vals.values,
        index=pd.to_datetime(df["nav_date"]).values,
    ).sort_index()

    # Resolve inception and terminal Nifty anchors.  Prefer explicit
    # overrides from the caller (authoritative source-of-truth); otherwise
    # fall back to the value in the dataframe, with stuck-tail detection.
    if inception_bench_override is not None and inception_bench_override > 0:
        inception_bench = float(inception_bench_override)
    else:
        inception_bench = _resolve_anchor_bench(
            bench_series, bench_series.index[0], direction="forward"
        )

    if latest_bench_override is not None and latest_bench_override > 0:
        latest_bench = float(latest_bench_override)
    else:
        latest_bench = _resolve_anchor_bench(
            bench_series, bench_series.index[-1], direction="backward"
        )

    if inception_bench <= 0 or latest_bench <= 0:
        return 0.0

    v_start, _, cash_flows, period_days = extract_modified_dietz_inputs(df)
    if v_start <= 0 or period_days <= 0:
        return 0.0

    inception_date = _to_pydate(df["nav_date"].iloc[0])

    # Buy units on inception with v_start (anchored to the resolved
    # inception Nifty close, not necessarily the row's stored value).
    nifty_units = v_start / inception_bench
    sum_cf = 0.0
    sum_weighted_cf = 0.0
    for cf_date, amount in cash_flows:
        amt = float(amount)
        ts = pd.Timestamp(cf_date)
        # as-of: most recent benchmark price ≤ cf_date.
        try:
            bench_at_cf = float(bench_series.asof(ts))
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
