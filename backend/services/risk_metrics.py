"""
Individual risk metric computation functions.

Every formula matches EXACTLY what is documented in CLAUDE.md and displayed
to clients on the Calculation Methodology page. Do not change any formula
without updating the methodology documentation simultaneously.

All functions operate on numpy/pandas types (float) for computation.
Conversion to Decimal happens in risk_engine.py before DB write.
"""

import numpy as np
import pandas as pd


def compute_twr_index(nav_series: pd.Series) -> pd.Series:
    """
    Time-Weighted Return index — normalize absolute NAV to base 100.

    Formula: TWR_t = (NAV_t / NAV_0) * 100
    """
    first_val = nav_series.iloc[0]
    if first_val == 0:
        return pd.Series(np.zeros(len(nav_series)), index=nav_series.index)
    return (nav_series / first_val) * 100


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
    cagr_pct: float,
    volatility_pct: float,
    risk_free_rate: float = 6.50,
) -> float:
    """
    Sharpe Ratio — risk-adjusted return.

    Formula: (R_p - R_f) / sigma_p
    Where R_p = portfolio CAGR, R_f = risk-free rate, sigma_p = volatility.
    All inputs in percentage terms.
    """
    if volatility_pct == 0:
        return 0.0
    return (cagr_pct - risk_free_rate) / volatility_pct


def sortino_ratio(
    cagr_pct: float,
    daily_returns: pd.Series,
    risk_free_rate: float = 6.50,
) -> float:
    """
    Sortino Ratio — penalizes only downside volatility.

    Formula: (R_p - R_f) / sigma_downside
    Where sigma_downside = sqrt(252) * sqrt(mean(min(R_daily, 0)^2))
    """
    downside = daily_returns[daily_returns < 0]
    if len(downside) == 0:
        return 0.0
    downside_dev = float(np.sqrt((downside**2).mean()) * np.sqrt(252) * 100)
    if downside_dev == 0:
        return 0.0
    return (cagr_pct - risk_free_rate) / downside_dev


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


def compute_drawdown_series(nav_df: pd.DataFrame) -> pd.DataFrame:
    """
    Drawdown series for the underwater chart.

    Formula: DD_t = (NAV_t - Peak_t) / Peak_t * 100
    Where Peak_t = max(NAV from inception to date t).

    Also computes benchmark drawdown for comparison overlay.
    """
    port_peak = nav_df["nav_value"].cummax()
    port_dd = ((nav_df["nav_value"] - port_peak) / port_peak) * 100

    bench_dd = pd.Series(np.zeros(len(nav_df)), index=nav_df.index)
    if "benchmark_value" in nav_df.columns:
        bench_vals = nav_df["benchmark_value"]
        if bench_vals.notna().any() and (bench_vals > 0).any():
            bench_peak = bench_vals.cummax()
            bench_dd = ((bench_vals - bench_peak) / bench_peak) * 100

    return pd.DataFrame(
        {
            "dd_date": nav_df["nav_date"],
            "drawdown_pct": port_dd.values,
            "bench_drawdown": bench_dd.values,
            "peak_nav": port_peak.values,
            "current_nav": nav_df["nav_value"].values,
        }
    )


def beta(daily_port_ret: pd.Series, daily_bench_ret: pd.Series) -> float:
    """
    Beta — portfolio sensitivity to market movements.

    Formula: beta = Cov(R_p, R_b) / Var(R_b)
    """
    if len(daily_port_ret) < 2 or len(daily_bench_ret) < 2:
        return 0.0
    aligned_port, aligned_bench = daily_port_ret.align(daily_bench_ret, join="inner")
    if len(aligned_port) < 2:
        return 0.0
    cov_matrix = np.cov(aligned_port, aligned_bench)
    var_bench = cov_matrix[1, 1]
    if var_bench == 0:
        return 0.0
    return float(cov_matrix[0, 1] / var_bench)


def alpha(
    port_cagr: float,
    bench_cagr: float,
    beta_val: float,
    risk_free_rate: float = 6.50,
) -> float:
    """
    Jensen's Alpha — excess return beyond what beta predicts.

    Formula: alpha = R_p - [R_f + beta * (R_b - R_f)]
    """
    expected_return = risk_free_rate + beta_val * (bench_cagr - risk_free_rate)
    return port_cagr - expected_return


def up_capture(daily_port_ret: pd.Series, daily_bench_ret: pd.Series) -> float:
    """
    Up Capture Ratio — % of benchmark gains captured on up days.

    Formula: mean(port returns on UP days) / mean(bench returns on UP days) * 100
    Where UP days = days when benchmark return > 0.
    """
    aligned_port, aligned_bench = daily_port_ret.align(daily_bench_ret, join="inner")
    up_days = aligned_bench > 0
    if up_days.sum() == 0:
        return 0.0
    port_up = aligned_port[up_days].mean()
    bench_up = aligned_bench[up_days].mean()
    if bench_up == 0:
        return 0.0
    return float((port_up / bench_up) * 100)


def down_capture(daily_port_ret: pd.Series, daily_bench_ret: pd.Series) -> float:
    """
    Down Capture Ratio — % of benchmark losses absorbed on down days.

    Formula: mean(port returns on DOWN days) / mean(bench returns on DOWN days) * 100
    Where DOWN days = days when benchmark return < 0.
    < 100% means we lose less than the market on down days (the goal).
    """
    aligned_port, aligned_bench = daily_port_ret.align(daily_bench_ret, join="inner")
    down_days = aligned_bench < 0
    if down_days.sum() == 0:
        return 0.0
    port_down = aligned_port[down_days].mean()
    bench_down = aligned_bench[down_days].mean()
    if bench_down == 0:
        return 0.0
    return float((port_down / bench_down) * 100)


def information_ratio(
    port_cagr: float,
    bench_cagr: float,
    tracking_error_val: float,
) -> float:
    """
    Information Ratio — risk-adjusted excess return over benchmark.

    Formula: IR = (R_p - R_b) / TE
    """
    if tracking_error_val == 0:
        return 0.0
    return (port_cagr - bench_cagr) / tracking_error_val


def tracking_error(daily_excess_ret: pd.Series) -> float:
    """
    Tracking Error — annualized std of excess returns.

    Formula: TE = sigma(R_p - R_b) * sqrt(252)
    """
    if len(daily_excess_ret) < 2:
        return 0.0
    return float(daily_excess_ret.std() * np.sqrt(252) * 100)


def ulcer_index(nav_series: pd.Series) -> float:
    """
    Ulcer Index — root-mean-square of all drawdowns.

    Formula: UI = sqrt(mean(DD_i^2))
    Unlike Max Drawdown, measures DEPTH AND DURATION of ALL drawdowns.
    """
    if len(nav_series) < 2:
        return 0.0
    running_max = nav_series.cummax()
    drawdown_pct = ((nav_series - running_max) / running_max) * 100
    return float(np.sqrt((drawdown_pct**2).mean()))


def monthly_return_profile(nav_df: pd.DataFrame) -> dict:
    """
    Monthly return statistics.

    Resamples daily NAV to monthly, computes month-over-month returns.
    Returns dict with hit_rate, best, worst, averages, consecutive loss count.
    """
    if len(nav_df) < 30:
        return {
            "monthly_returns": pd.Series(dtype=float),
            "hit_rate": 0.0,
            "best_month": 0.0,
            "worst_month": 0.0,
            "avg_positive_month": 0.0,
            "avg_negative_month": 0.0,
            "max_consecutive_loss": 0,
            "win_count": 0,
            "loss_count": 0,
        }

    monthly = nav_df.set_index("nav_date")["nav_value"].resample("ME").last()
    monthly_ret = monthly.pct_change().dropna() * 100

    if len(monthly_ret) == 0:
        return {
            "monthly_returns": monthly_ret,
            "hit_rate": 0.0,
            "best_month": 0.0,
            "worst_month": 0.0,
            "avg_positive_month": 0.0,
            "avg_negative_month": 0.0,
            "max_consecutive_loss": 0,
            "win_count": 0,
            "loss_count": 0,
        }

    positive = monthly_ret[monthly_ret > 0]
    negative = monthly_ret[monthly_ret <= 0]

    # Max consecutive loss streak
    is_loss = (monthly_ret <= 0).astype(int)
    streaks = is_loss.groupby((is_loss != is_loss.shift()).cumsum()).sum()
    max_consec = int(streaks.max()) if len(streaks) > 0 else 0

    return {
        "monthly_returns": monthly_ret,
        "hit_rate": float((len(positive) / len(monthly_ret)) * 100),
        "best_month": float(monthly_ret.max()),
        "worst_month": float(monthly_ret.min()),
        "avg_positive_month": float(positive.mean()) if len(positive) > 0 else 0.0,
        "avg_negative_month": float(negative.mean()) if len(negative) > 0 else 0.0,
        "max_consecutive_loss": max_consec,
        "win_count": len(positive),
        "loss_count": len(negative),
    }


def market_correlation(
    daily_port_ret: pd.Series,
    daily_bench_ret: pd.Series,
) -> float:
    """
    Pearson correlation between daily portfolio and benchmark returns.

    Range: -1 to +1.
    """
    aligned_port, aligned_bench = daily_port_ret.align(daily_bench_ret, join="inner")
    if len(aligned_port) < 2:
        return 0.0
    return float(aligned_port.corr(aligned_bench))


def cash_metrics(nav_df: pd.DataFrame) -> dict:
    """
    Cash position statistics from the Liquidity % column.

    Returns avg_cash_held, max_cash_held, current_cash (all in %).
    """
    if "cash_pct" not in nav_df.columns or len(nav_df) == 0:
        return {"avg_cash_held": 0.0, "max_cash_held": 0.0, "current_cash": 0.0}

    cash = nav_df["cash_pct"].astype(float)
    return {
        "avg_cash_held": float(cash.mean()),
        "max_cash_held": float(cash.max()),
        "current_cash": float(cash.iloc[-1]),
    }
