"""
Derived risk metric functions — benchmark comparison, drawdown analysis,
monthly profile, cash metrics.

Separated from risk_metrics.py (core return/volatility/ratio functions)
to keep both files under the 400-line limit.
"""

import numpy as np
import pandas as pd


def compute_drawdown_series(nav_df: pd.DataFrame) -> pd.DataFrame:
    """
    Drawdown series for the underwater chart.

    Formula: DD_t = (TWR_t - Peak_t) / Peak_t * 100
    Where Peak_t = max(TWR from inception to date t).

    Uses TWR-adjusted values so drawdowns reflect true investment performance
    excluding the effect of capital inflows/outflows.
    Also computes benchmark drawdown for comparison overlay.
    """
    # Use TWR-adjusted values if available, otherwise fall back to raw NAV
    value_col = "twr_value" if "twr_value" in nav_df.columns else "nav_value"
    port_vals = nav_df[value_col]
    port_peak = port_vals.cummax()
    port_dd = ((port_vals - port_peak) / port_peak) * 100

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

    # Use TWR-adjusted values if available, otherwise fall back to raw NAV
    value_col = "twr_value" if "twr_value" in nav_df.columns else "nav_value"
    monthly = nav_df.set_index("nav_date")[value_col].resample("ME").last()
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
    negative = monthly_ret[monthly_ret < 0]

    # Max consecutive loss streak
    is_loss = (monthly_ret < 0).astype(int)
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
    Cash position statistics.

    Uses true cash = ETF + Cash + Bank when breakdown columns are available,
    otherwise falls back to Liquidity % column.

    Returns avg_cash_held, max_cash_held, current_cash (all in %).
    """
    if len(nav_df) == 0:
        return {"avg_cash_held": 0.0, "max_cash_held": 0.0, "current_cash": 0.0}

    has_breakdown = all(
        col in nav_df.columns for col in ("etf_value", "cash_value", "bank_balance")
    )
    nav_vals = nav_df["nav_value"].astype(float)

    if has_breakdown and nav_df["etf_value"].sum() + nav_df["cash_value"].sum() > 0:
        # True cash = ETF (LIQUIDBEES) + ledger cash + bank balance
        total_cash = (
            nav_df["etf_value"].astype(float)
            + nav_df["cash_value"].astype(float)
            + nav_df["bank_balance"].astype(float)
        )
        # Cash as % of NAV for each day
        cash_pct = (total_cash / nav_vals.replace(0, float("nan"))) * 100
        cash_pct = cash_pct.fillna(0).clip(lower=0)
    elif "cash_pct" in nav_df.columns:
        cash_pct = nav_df["cash_pct"].astype(float)
    else:
        return {"avg_cash_held": 0.0, "max_cash_held": 0.0, "current_cash": 0.0}

    return {
        "avg_cash_held": float(cash_pct.mean()),
        "max_cash_held": float(cash_pct.max()),
        "current_cash": float(cash_pct.iloc[-1]),
    }
