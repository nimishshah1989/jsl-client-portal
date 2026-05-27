"""
Individual risk metric computation functions.

Every formula matches EXACTLY what is documented in CLAUDE.md and displayed
to clients on the Calculation Methodology page. Do not change any formula
without updating the methodology documentation simultaneously.

All functions operate on numpy/pandas types (float) for computation.
Conversion to Decimal happens in risk_engine.py before DB write.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd


def compute_twr_index(nav_series: pd.Series) -> pd.Series:
    """
    Time-Weighted Return index — normalize absolute NAV to base 100.

    Simple normalization WITHOUT corpus adjustment (for benchmark or when
    no invested_amount data is available).

    Formula: TWR_t = (NAV_t / NAV_0) * 100
    """
    first_val = nav_series.iloc[0]
    if first_val == 0:
        return pd.Series(np.zeros(len(nav_series)), index=nav_series.index)
    return (nav_series / first_val) * 100


def compute_twr_series(nav_df: pd.DataFrame) -> np.ndarray:
    """
    Compute proper TWR index (base 100) adjusting for corpus changes.

    When the invested_amount (corpus) changes between days, it means the client
    added or withdrew cash. Raw NAV values include these infusions as value
    increases, which would be incorrectly counted as returns.

    On a normal day (no corpus change):
        daily_return = (NAV_today / NAV_yesterday) - 1

    On a corpus change day:
        corpus_change = invested_today - invested_yesterday
        adjusted_prev = NAV_yesterday + corpus_change
        daily_return = (NAV_today / adjusted_prev) - 1

    The adjustment subtracts the infusion effect: if NAV went from 100 to 120
    but 15 was new money, the true return is (120 / (100+15)) - 1 = 4.35%,
    not (120/100) - 1 = 20%.

    Chain-link: TWR_t = TWR_{t-1} * (1 + daily_return_t), starting at 100.
    """
    nav_vals = nav_df["nav_value"].values.astype(float)
    corpus = nav_df["invested_amount"].values.astype(float)

    # TWR always starts at base 100 on day 0.  Pre-inception gain (NAV_0 > corpus_0)
    # belongs to a prior tracking period and must NOT inflate the in-scope return —
    # PMS's "Adjusted Return [Weighted] %" reports cumulative TWR from day 0, so we
    # anchor there as well.  Chain-linking below captures the actual investment
    # performance from inception onward.
    twr = np.ones(len(nav_vals)) * 100.0
    for i in range(1, len(nav_vals)):
        prev_nav = nav_vals[i - 1]
        if prev_nav == 0:
            twr[i] = twr[i - 1]
            continue

        corpus_change = corpus[i] - corpus[i - 1]
        if corpus_change != 0:
            # Adjust previous NAV by the infusion/withdrawal amount so
            # the return only reflects market movement, not cash flow.
            adjusted_prev = prev_nav + corpus_change
            if adjusted_prev <= 0:
                # Edge case: withdrawal larger than NAV (shouldn't happen)
                twr[i] = twr[i - 1]
                continue
            daily_ret = (nav_vals[i] / adjusted_prev) - 1
        else:
            daily_ret = (nav_vals[i] / prev_nav) - 1

        twr[i] = twr[i - 1] * (1 + daily_ret)

    return twr


def compute_daily_returns(series: pd.Series) -> pd.Series:
    """
    Simple daily returns (NOT log returns).

    Formula: R_t = (P_t - P_{t-1}) / P_{t-1}
    """
    return series.pct_change().dropna()


def simple_return(nav_series: pd.Series, days: int | None = None) -> float:
    """
    Trailing simple return over N calendar days.

    Formula: (NAV_end / NAV_start) - 1, expressed as percentage.
    If days is None, computes since inception.

    NOTE: This is the naive TWR ratio between two endpoints. For the
    inception-to-date headline return shown on the dashboard, the portal
    uses ``compute_modified_dietz_return`` instead, which matches the
    "Adjusted Return [Weighted] %" reported on the PMS backoffice report.
    ``simple_return`` is kept for trailing-period rows where the ratio is
    computed off the TWR-adjusted series.
    """
    if len(nav_series) < 2:
        return 0.0
    end_val = float(nav_series.iloc[-1])
    if days is None:
        start_val = float(nav_series.iloc[0])
    else:
        target_date = nav_series.index[-1] - pd.Timedelta(days=days)
        start_val = float(nav_series.asof(target_date))
    if start_val == 0:
        return 0.0
    return ((end_val / start_val) - 1) * 100


# Backwards-compatible alias.  Module-level callers (period table builders in
# risk_engine and aggregate_service, plus existing tests) keep importing
# ``absolute_return``; under the hood it is the same simple two-endpoint ratio.
# The *headline* inception return persisted in cpp_risk_metrics.absolute_return
# is recomputed by ``compute_modified_dietz_return`` in risk_engine.
absolute_return = simple_return


def cagr(start_value: float, end_value: float, days: int) -> float:
    """
    Compound Annual Growth Rate.

    Formula: ((end / start) ^ (365.25 / days)) - 1
    Uses 365.25 to account for leap years. Expressed as percentage.
    """
    if days <= 0 or start_value <= 0 or end_value <= 0:
        return 0.0
    years = days / 365.25
    return ((end_value / start_value) ** (1 / years) - 1) * 100


def annualized_volatility(daily_returns: pd.Series) -> float:
    """
    Annualized standard deviation of daily returns.

    Formula: sigma_annual = sigma_daily * sqrt(252)
    Where 252 = trading days per year. Expressed as percentage.
    """
    if len(daily_returns) < 2:
        return 0.0
    return float(daily_returns.std() * np.sqrt(252) * 100)


def sharpe_ratio(
    cagr_pct: float,
    volatility_pct: float,
    risk_free_rate: float = 6.50,
) -> float:
    """
    Sharpe Ratio — risk-adjusted return.

    Formula: (R_p - R_f) / σ_p
    Where:
      R_p = portfolio CAGR (annualized return) — already in %
      R_f = risk-free rate (6.50% = India 10Y govt bond yield)
      σ_p = annualized volatility — already in %

    Interpretation:
      > 1.0 = Good risk-adjusted returns
      > 2.0 = Excellent
      < 0   = Returns below risk-free rate

    Spec reference: CLAUDE.md "Risk Computation Engine — 7. Sharpe Ratio".
    """
    if volatility_pct is None or float(volatility_pct) == 0.0:
        return 0.0
    return float((float(cagr_pct) - float(risk_free_rate)) / float(volatility_pct))


def sortino_ratio(
    cagr_pct: float,
    daily_returns: pd.Series,
    risk_free_rate: float = 6.50,
    trading_days: int = 252,
) -> float:
    """
    Sortino Ratio — penalizes only downside volatility.

    Formula: (R_p - R_f) / σ_downside
    Where:
      σ_downside = √(252) × √(mean(min(R_daily, 0)²)) (expressed as %)
      Only NEGATIVE daily returns contribute to downside deviation
      (threshold is ZERO, not the daily risk-free rate).

    Sortino penalizes only downside volatility — upside volatility is a good
    thing. More appropriate than Sharpe for portfolios with asymmetric
    returns.

    Spec reference: CLAUDE.md "Risk Computation Engine — 8. Sortino Ratio".
    """
    if daily_returns is None or len(daily_returns) < 2:
        return 0.0
    downside = daily_returns[daily_returns < 0]
    if len(downside) == 0:
        return 0.0
    # σ_downside annualised and expressed as a percentage to match cagr_pct units
    downside_dev_pct = float(np.sqrt((downside**2).mean()) * np.sqrt(trading_days) * 100)
    if downside_dev_pct < 1e-10:
        return 0.0
    return float((float(cagr_pct) - float(risk_free_rate)) / downside_dev_pct)


def max_drawdown(nav_series: pd.Series) -> dict:
    """
    Maximum Drawdown — worst peak-to-trough decline.

    Formula: Max DD = max((Peak_t - NAV_t) / Peak_t) over all t
    Where Peak_t = running maximum of NAV from inception to t.

    Returns dict with:
        max_dd_pct  — maximum drawdown as negative percentage
        dd_start    — date of the peak before the max drawdown
        dd_end      — date of the trough (lowest point)
        dd_recovery — date when NAV recovered to peak (None if not recovered)
    """
    if len(nav_series) < 2:
        return {
            "max_dd_pct": 0.0,
            "dd_start": None,
            "dd_end": None,
            "dd_recovery": None,
        }

    running_max = nav_series.cummax()
    drawdown = (nav_series - running_max) / running_max

    max_dd_pct = float(drawdown.min() * 100)
    trough_idx = drawdown.idxmin()
    peak_idx = nav_series[:trough_idx].idxmax()

    # Recovery: first date after trough where NAV >= peak value
    peak_value = nav_series[peak_idx]
    post_trough = nav_series[trough_idx:]
    recovery_candidates = post_trough[post_trough >= peak_value]
    recovery_idx = recovery_candidates.index[0] if len(recovery_candidates) > 0 else None

    return {
        "max_dd_pct": max_dd_pct,
        "dd_start": peak_idx,
        "dd_end": trough_idx,
        "dd_recovery": recovery_idx,
    }


def compute_weighted_avg_corpus(nav_df: pd.DataFrame) -> float:
    """
    Time-weighted average corpus over the holding period.

    For each NAV row the invested_amount ("corpus") is held between that date
    and the next.  We multiply the corpus level by the day-count it was
    maintained and divide by the total day span:

        weighted_avg_corpus = Σ (corpus_t × Δdays_t) / total_days

    This is the denominator PMS uses for its "Adjusted Return [Weighted] %":
    profit / time-weighted-average-corpus × 100 (Simple-Dietz style).
    """
    if len(nav_df) < 2:
        return float(nav_df["invested_amount"].iloc[0]) if len(nav_df) else 0.0

    dates = pd.to_datetime(nav_df["nav_date"]).values
    corpus = nav_df["invested_amount"].astype(float).values

    total_days = (dates[-1] - dates[0]).astype("timedelta64[D]").astype(int)
    if total_days <= 0:
        return float(corpus[-1])

    weighted_sum = 0.0
    for i in range(len(corpus) - 1):
        segment_days = (dates[i + 1] - dates[i]).astype("timedelta64[D]").astype(int)
        if segment_days <= 0:
            continue
        weighted_sum += float(corpus[i]) * segment_days

    return weighted_sum / total_days if total_days > 0 else 0.0


def compute_weighted_bench_return(nav_df: pd.DataFrame) -> float:
    """
    Cash-flow-weighted benchmark return matching PMS
    "Absolute Return S&P CNX Nifty [Weighted] %".

    Delegates to ``backend.services.modified_dietz`` which applies the
    Modified-Dietz denominator (= V_start + Σ CF_i * w_i, i.e. the time-
    weighted average corpus) rather than naively dividing by net
    contributions.  This was the production bug that made BJ53 read
    47.55% instead of the official 74.72%.

    See ``modified_dietz.compute_modified_dietz_bench_return`` for the
    full math + worked example.
    """
    from backend.services.modified_dietz import compute_modified_dietz_bench_return

    return compute_modified_dietz_bench_return(nav_df)


# ── Re-exports from risk_metrics_analysis for backward compatibility ──
from backend.services.risk_metrics_analysis import (  # noqa: F401, E402
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

# ── Re-exports for Modified-Dietz (PMS "Adjusted Return [Weighted]") ──
from backend.services.modified_dietz import (  # noqa: F401, E402
    compute_average_corpus,
    compute_modified_dietz_bench_return,
    compute_modified_dietz_return,
    extract_modified_dietz_inputs,
)
