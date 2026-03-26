"""
Individual risk metric computation functions.

Every formula matches EXACTLY what is documented in CLAUDE.md and displayed
to clients on the Calculation Methodology page. Do not change any formula
without updating the methodology documentation simultaneously.

All functions operate on numpy/pandas types (float) for computation.
Conversion to Decimal happens in risk_engine.py before DB write.
"""

from __future__ import annotations

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

    # Day-0: if NAV != corpus, capture pre-inception gain/loss ratio.
    # Matches FIE2 compute_twr_unit_nav(): unit_nav[0] = 100 * (NAV_0 / corpus_0)
    initial_ratio = nav_vals[0] / corpus[0] if corpus[0] != 0 else 1.0
    twr = np.ones(len(nav_vals)) * (100.0 * initial_ratio)
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


def absolute_return(nav_series: pd.Series, days: int | None = None) -> float:
    """
    Trailing absolute return over N calendar days.

    Formula: (NAV_end / NAV_start) - 1, expressed as percentage.
    If days is None, computes since inception.
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
    daily_returns: pd.Series,
    risk_free_rate: float = 6.50,
    trading_days: int = 252,
) -> float:
    """
    Sharpe Ratio — risk-adjusted return (daily excess approach).

    Formula: mean(R_daily - Rf_daily) / std(R_daily - Rf_daily) * sqrt(252)
    Where Rf_daily = annual_rf / 252.
    Matches FIE2/Market Pulse reference implementation.
    """
    if len(daily_returns) < 2:
        return 0.0
    daily_rf = risk_free_rate / 100.0 / trading_days
    excess = daily_returns - daily_rf
    std = float(excess.std())
    if std < 1e-10:
        return 0.0
    return float(excess.mean() / std * np.sqrt(trading_days))


def sortino_ratio(
    daily_returns: pd.Series,
    risk_free_rate: float = 6.50,
    trading_days: int = 252,
) -> float:
    """
    Sortino Ratio — penalizes only downside volatility.

    Formula: (mean(R_daily) - Rf_daily) / downside_dev * sqrt(252)
    Where downside = returns below Rf_daily (not below zero).
    Matches FIE2/Market Pulse reference implementation.
    """
    if len(daily_returns) < 2:
        return 0.0
    daily_rf = risk_free_rate / 100.0 / trading_days
    downside = daily_returns[daily_returns < daily_rf] - daily_rf
    if len(downside) == 0:
        return 0.0
    downside_dev = float(np.sqrt((downside**2).mean()))
    if downside_dev < 1e-10:
        return 0.0
    return float((daily_returns.mean() - daily_rf) / downside_dev * np.sqrt(trading_days))


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
