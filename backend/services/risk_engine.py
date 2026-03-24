"""
Risk computation engine — orchestrator and performance table builder.

Triggered after every NAV data upload. Operates per (client_id, portfolio_id).
Computes ALL metrics, builds the multi-period performance table, and upserts
results into cpp_risk_metrics and cpp_drawdown_series.

Individual metric functions live in risk_metrics.py.
DB upsert logic lives in risk_db.py.
"""

import logging
from decimal import Decimal

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.risk_db import replace_drawdown_series, upsert_risk_metrics
from backend.services.risk_metrics import (
    absolute_return,
    alpha,
    annualized_volatility,
    beta,
    cagr,
    cash_metrics,
    compute_daily_returns,
    compute_drawdown_series,
    compute_twr_series,
    down_capture,
    information_ratio,
    market_correlation,
    max_drawdown,
    monthly_return_profile,
    sharpe_ratio,
    sortino_ratio,
    tracking_error,
    ulcer_index,
    up_capture,
)
from backend.services.xirr_service import (
    compute_xirr,
    extract_cash_flows_from_corpus,
    extract_cash_flows_from_db,
)

logger = logging.getLogger(__name__)

# Period definitions: (label, calendar_days). None = since inception.
PERIODS = [
    ("1 Month", 30),
    ("3 Months", 91),
    ("6 Months", 182),
    ("1 Year", 365),
    ("2 Years", 730),
    ("3 Years", 1095),
    ("4 Years", 1461),
    ("5 Years", 1826),
    ("Since Inception", None),
]

# Period label to DB column suffix mapping
_PERIOD_COL_MAP = {
    "1 Month": "1m",
    "3 Months": "3m",
    "6 Months": "6m",
    "1 Year": "1y",
    "2 Years": "2y",
    "3 Years": "3y",
    "4 Years": "4y",
    "5 Years": "5y",
    "Since Inception": "inception",
}

_RF_RATE = 7.00


def _slice_nav_df(nav_df: pd.DataFrame, days: int | None) -> pd.DataFrame:
    """Slice nav_df to trailing N calendar days. None = full series."""
    if days is None or len(nav_df) == 0:
        return nav_df
    cutoff = nav_df["nav_date"].iloc[-1] - pd.Timedelta(days=days)
    return nav_df[nav_df["nav_date"] >= cutoff].copy()


def _compute_period_metrics(
    slice_df: pd.DataFrame,
    risk_free_rate: float = _RF_RATE,
) -> dict:
    """Compute all metrics for a single time period slice."""
    if len(slice_df) < 2:
        return {}

    # Use TWR-adjusted values for portfolio return calculations
    value_col = "twr_value" if "twr_value" in slice_df.columns else "nav_value"
    port_series = slice_df[value_col].astype(float)
    port_series.index = slice_df["nav_date"]

    bench_series = slice_df["benchmark_value"].astype(float)
    bench_series.index = slice_df["nav_date"]

    port_ret = compute_daily_returns(port_series)
    bench_ret = compute_daily_returns(bench_series)

    days_in_slice = (port_series.index[-1] - port_series.index[0]).days
    if days_in_slice <= 0:
        days_in_slice = 1

    port_cagr = cagr(float(port_series.iloc[0]), float(port_series.iloc[-1]), days_in_slice)
    bench_cagr = cagr(float(bench_series.iloc[0]), float(bench_series.iloc[-1]), days_in_slice)

    port_vol = annualized_volatility(port_ret)
    bench_vol = annualized_volatility(bench_ret)

    port_dd = max_drawdown(port_series)
    bench_dd = max_drawdown(bench_series)

    return {
        "port_abs_return": absolute_return(port_series),
        "bench_abs_return": absolute_return(bench_series),
        "port_cagr": port_cagr,
        "bench_cagr": bench_cagr,
        "port_volatility": port_vol,
        "bench_volatility": bench_vol,
        "port_max_dd": port_dd["max_dd_pct"],
        "bench_max_dd": bench_dd["max_dd_pct"],
        "port_sharpe": sharpe_ratio(port_ret, risk_free_rate),
        "bench_sharpe": sharpe_ratio(bench_ret, risk_free_rate),
        "port_sortino": sortino_ratio(port_ret, risk_free_rate),
        "bench_sortino": sortino_ratio(bench_ret, risk_free_rate),
    }


def performance_table(
    nav_df: pd.DataFrame,
    risk_free_rate: float = _RF_RATE,
) -> list[dict]:
    """
    Generate multi-period performance table matching Market Pulse format.

    For each period (1M through Inception), computes absolute return, CAGR,
    volatility, max drawdown, Sharpe, and Sortino for both portfolio and benchmark.
    """
    results: list[dict] = []
    for label, days in PERIODS:
        slice_df = _slice_nav_df(nav_df, days)
        if len(slice_df) < 2:
            continue
        metrics = _compute_period_metrics(slice_df, risk_free_rate)
        if metrics:
            metrics["period"] = label
            results.append(metrics)
    return results


def compute_all_metrics(
    nav_df: pd.DataFrame,
    risk_free_rate: float = _RF_RATE,
) -> dict:
    """
    Compute ALL risk metrics for a single client+portfolio.

    Args:
        nav_df: DataFrame with columns [nav_date, nav_value, invested_amount,
                benchmark_value, cash_pct]. Must contain twr_value column
                (added by run_risk_engine before calling this).
                Sorted ascending by nav_date.
        risk_free_rate: Annual risk-free rate in % (default 6.50).

    Returns:
        Dict of all computed metrics keyed by DB column name.
    """
    if len(nav_df) < 2:
        logger.warning("Cannot compute metrics — less than 2 NAV data points")
        return {}

    # Use TWR-adjusted values for all return/risk calculations.
    # Raw nav_value includes corpus infusions as value increases, which
    # would be incorrectly counted as returns.
    value_col = "twr_value" if "twr_value" in nav_df.columns else "nav_value"
    port_series = nav_df[value_col].astype(float)
    port_series.index = pd.DatetimeIndex(nav_df["nav_date"])

    bench_series = nav_df["benchmark_value"].astype(float)
    bench_series.index = pd.DatetimeIndex(nav_df["nav_date"])

    port_ret = compute_daily_returns(port_series)
    bench_ret = compute_daily_returns(bench_series)
    excess_ret = port_ret - bench_ret.reindex(port_ret.index, method="ffill").fillna(0)

    total_days = (port_series.index[-1] - port_series.index[0]).days
    if total_days <= 0:
        total_days = 1

    # Core metrics (inception-to-date)
    # For SI CAGR, use TWR_BASE=100 as start (not actual first unit_nav which
    # may differ due to pre-inception gains). Matches FIE2 reference.
    port_cagr = cagr(100.0, float(port_series.iloc[-1]), total_days)
    bench_cagr = cagr(float(bench_series.iloc[0]), float(bench_series.iloc[-1]), total_days)
    port_vol = annualized_volatility(port_ret)
    dd_result = max_drawdown(port_series)
    beta_val = beta(port_ret, bench_ret)
    te_val = tracking_error(excess_ret)

    # XIRR from corpus changes (fallback — may be overridden by real cash flows
    # in run_risk_engine if cpp_cash_flows data exists)
    xirr_val = 0.0
    if "invested_amount" in nav_df.columns:
        xirr_df = pd.DataFrame({
            "date": nav_df["nav_date"],
            "corpus": nav_df["invested_amount"].astype(float),
            "nav": nav_df["nav_value"].astype(float),
        })
        cash_flows = extract_cash_flows_from_corpus(xirr_df)
        if len(cash_flows) >= 2:
            xirr_val = compute_xirr(cash_flows)

    # Monthly profile and cash
    monthly_profile = monthly_return_profile(nav_df)
    cash_stats = cash_metrics(nav_df)

    # Period returns
    perf = performance_table(nav_df, risk_free_rate)
    period_returns: dict[str, float] = {}
    bench_period_returns: dict[str, float] = {}
    for row in perf:
        suffix = _PERIOD_COL_MAP.get(row["period"])
        if suffix:
            # Absolute returns
            period_returns[f"return_{suffix}"] = row["port_abs_return"]
            bench_period_returns[f"bench_return_{suffix}"] = row["bench_abs_return"]
            # CAGR
            period_returns[f"cagr_{suffix}"] = row["port_cagr"]
            bench_period_returns[f"bench_cagr_{suffix}"] = row["bench_cagr"]
            # Volatility
            period_returns[f"vol_{suffix}"] = row["port_volatility"]
            bench_period_returns[f"bench_vol_{suffix}"] = row["bench_volatility"]
            # Max drawdown
            period_returns[f"dd_{suffix}"] = row["port_max_dd"]
            bench_period_returns[f"bench_dd_{suffix}"] = row["bench_max_dd"]
            # Sharpe
            period_returns[f"sharpe_{suffix}"] = row["port_sharpe"]
            bench_period_returns[f"bench_sharpe_{suffix}"] = row["bench_sharpe"]
            # Sortino
            period_returns[f"sortino_{suffix}"] = row["port_sortino"]
            bench_period_returns[f"bench_sortino_{suffix}"] = row["bench_sortino"]

    result = {
        "absolute_return": absolute_return(port_series),
        "cagr": port_cagr,
        "xirr": xirr_val,
        "volatility": port_vol,
        "sharpe_ratio": sharpe_ratio(port_ret, risk_free_rate),
        "sortino_ratio": sortino_ratio(port_ret, risk_free_rate),
        "max_drawdown": dd_result["max_dd_pct"],
        "max_dd_start": dd_result["dd_start"],
        "max_dd_end": dd_result["dd_end"],
        "max_dd_recovery": dd_result["dd_recovery"],
        "alpha": alpha(port_cagr, bench_cagr, beta_val, risk_free_rate),
        "beta": beta_val,
        "information_ratio": information_ratio(port_cagr, bench_cagr, te_val),
        "tracking_error": te_val,
        "up_capture": up_capture(port_ret, bench_ret),
        "down_capture": down_capture(port_ret, bench_ret),
        "ulcer_index": ulcer_index(port_series),
        "max_consecutive_loss": monthly_profile["max_consecutive_loss"],
        "win_months": monthly_profile["win_count"],
        "loss_months": monthly_profile["loss_count"],
        "avg_cash_held": cash_stats["avg_cash_held"],
        "max_cash_held": cash_stats["max_cash_held"],
        "current_cash": cash_stats["current_cash"],
        "market_correlation": market_correlation(port_ret, bench_ret),
        "monthly_hit_rate": monthly_profile["hit_rate"],
        "best_month": monthly_profile["best_month"],
        "worst_month": monthly_profile["worst_month"],
        "avg_positive_month": monthly_profile["avg_positive_month"],
        "avg_negative_month": monthly_profile["avg_negative_month"],
        "risk_free_rate": risk_free_rate,
    }
    result.update(period_returns)
    result.update(bench_period_returns)
    return result


async def run_risk_engine(
    client_id: int,
    portfolio_id: int,
    db_session: AsyncSession,
    risk_free_rate: float = _RF_RATE,
) -> dict:
    """
    Master orchestrator — computes all metrics and upserts to DB.

    1. Fetch nav_df from cpp_nav_series for this client+portfolio
    2. Compute all metrics
    3. Compute drawdown series
    4. Upsert into cpp_risk_metrics (via risk_db)
    5. Upsert into cpp_drawdown_series (via risk_db)
    """
    logger.info("Running risk engine for client=%d portfolio=%d", client_id, portfolio_id)

    # 1. Fetch NAV data
    result = await db_session.execute(
        text("""
            SELECT nav_date, nav_value, invested_amount, current_value,
                   benchmark_value, cash_pct,
                   COALESCE(etf_value, 0) AS etf_value,
                   COALESCE(cash_value, 0) AS cash_value,
                   COALESCE(bank_balance, 0) AS bank_balance
            FROM cpp_nav_series
            WHERE client_id = :cid AND portfolio_id = :pid
            ORDER BY nav_date ASC
        """),
        {"cid": client_id, "pid": portfolio_id},
    )
    rows = result.fetchall()

    if len(rows) < 2:
        logger.warning("Insufficient NAV data for client=%d portfolio=%d", client_id, portfolio_id)
        return {}

    nav_df = pd.DataFrame(rows, columns=[
        "nav_date", "nav_value", "invested_amount", "current_value",
        "benchmark_value", "cash_pct", "etf_value", "cash_value", "bank_balance",
    ])
    nav_df["nav_date"] = pd.to_datetime(nav_df["nav_date"])
    for col in ["nav_value", "invested_amount", "current_value", "benchmark_value",
                 "cash_pct", "etf_value", "cash_value", "bank_balance"]:
        nav_df[col] = pd.to_numeric(nav_df[col], errors="coerce").fillna(0)
    nav_df = nav_df.sort_values("nav_date").reset_index(drop=True)

    # 2. Compute TWR index that adjusts for corpus changes (infusions/withdrawals).
    #    Raw nav_value includes cash infusions as value increases, which would be
    #    incorrectly counted as investment returns. The TWR series chain-links
    #    sub-period returns around corpus change events.
    nav_df["twr_value"] = compute_twr_series(nav_df)

    # 3. Compute all metrics (using twr_value for return calculations)
    metrics = compute_all_metrics(nav_df, risk_free_rate)
    if not metrics:
        return {}

    # 3b. Recompute XIRR using real cash flows if available in cpp_cash_flows
    cf_result = await db_session.execute(
        text("""
            SELECT flow_date, flow_type, amount
            FROM cpp_cash_flows
            WHERE client_id = :cid AND portfolio_id = :pid
            ORDER BY flow_date ASC
        """),
        {"cid": client_id, "pid": portfolio_id},
    )
    cf_rows = cf_result.fetchall()
    if cf_rows:
        terminal_date = nav_df["nav_date"].iloc[-1].to_pydatetime()
        terminal_value = float(nav_df["nav_value"].iloc[-1])
        real_flows = extract_cash_flows_from_db(cf_rows, terminal_date, terminal_value)
        if len(real_flows) >= 2:
            xirr_val = compute_xirr(real_flows)
            metrics["xirr"] = xirr_val
            logger.info(
                "XIRR for client=%d portfolio=%d computed from %d actual cash flows",
                client_id, portfolio_id, len(cf_rows),
            )

    # 4. Compute drawdown series (uses twr_value via the column in nav_df)
    dd_df = compute_drawdown_series(nav_df)

    # 5. Upsert risk metrics
    computed = nav_df["nav_date"].iloc[-1].date()
    await upsert_risk_metrics(db_session, client_id, portfolio_id, computed, metrics)

    # 6. Upsert drawdown series
    dd_count = await replace_drawdown_series(db_session, client_id, portfolio_id, dd_df)

    logger.info(
        "Risk engine complete for client=%d portfolio=%d: %d metrics, %d drawdown points",
        client_id, portfolio_id, len(metrics), dd_count,
    )
    return metrics
