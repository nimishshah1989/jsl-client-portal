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
    # Zero-volatility portfolio (e.g. 100% cash) — ratio is undefined
    if float(daily_returns.std()) < 1e-10:
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
    Cash-flow-weighted benchmark return using the virtual units method.

    Matches PMS "Absolute Return S&P CNX Nifty [Weighted] %".

    For each corpus change (inflow/outflow), we "buy" or "sell" Nifty units at
    that date's benchmark price.  The total current value of those units versus
    net contributions gives the cash-flow-adjusted benchmark return.

    Formula:
      - Each corpus delta d at date t: nifty_units += d / benchmark(t)
      - net_corpus = sum of all deltas (inflows positive, outflows negative)
      - weighted_return = (nifty_units * latest_benchmark - net_corpus) / net_corpus * 100

    Returns 0.0 if benchmark data is unavailable or net corpus is zero.
    """
    bench_vals = nav_df["benchmark_value"].astype(float)
    corpus_vals = nav_df["invested_amount"].astype(float)

    if bench_vals.sum() == 0 or bench_vals.isna().all():
        return 0.0

    nifty_units = 0.0
    net_corpus = 0.0
    prev_corpus = 0.0

    for i in range(len(nav_df)):
        corpus = float(corpus_vals.iloc[i])
        bench = float(bench_vals.iloc[i])

        if bench <= 0:
            prev_corpus = corpus
            continue

        if abs(corpus - prev_corpus) > 1e-4:
            delta = corpus - prev_corpus
            nifty_units += delta / bench
            net_corpus += delta
            prev_corpus = corpus

    if net_corpus <= 0 or nifty_units <= 0:
        return 0.0

    latest_bench = float(bench_vals.iloc[-1])
    if latest_bench <= 0:
        return 0.0

    nifty_value = nifty_units * latest_bench
    return ((nifty_value - net_corpus) / net_corpus) * 100


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
