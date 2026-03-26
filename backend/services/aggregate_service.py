"""Aggregate portfolio analytics — computes firm-wide metrics across all active clients.

All functions operate on the SUM of NAV values across clients, producing a single
"firm portfolio" time series. Risk metrics are then computed on this aggregate series
using the same functions used for individual client metrics.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.routers.helpers import RANGE_DAYS
from backend.services.risk_metrics import (
    absolute_return,
    annualized_volatility,
    cagr,
    compute_daily_returns,
    compute_twr_index,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
)
from backend.services.risk_metrics_analysis import (
    alpha,
    beta,
    down_capture,
    information_ratio,
    market_correlation,
    tracking_error,
    ulcer_index,
    up_capture,
)

logger = logging.getLogger(__name__)

RISK_FREE_RATE = 7.00  # India 10Y govt bond yield proxy


async def _fetch_aggregate_nav(db: AsyncSession) -> pd.DataFrame:
    """Fetch daily aggregate NAV series across all active, non-admin clients.

    Returns DataFrame with columns: nav_date, total_aum, total_invested,
    total_benchmark, weighted_cash_pct — sorted by nav_date ascending.
    """
    result = await db.execute(text("""
        SELECT
            n.nav_date,
            SUM(n.nav_value)                             AS total_aum,
            SUM(n.invested_amount)                       AS total_invested,
            SUM(n.benchmark_value)                       AS total_benchmark,
            CASE WHEN SUM(n.nav_value) > 0
                 THEN SUM(n.nav_value * COALESCE(n.cash_pct, 0)) / SUM(n.nav_value)
                 ELSE 0 END                              AS weighted_cash_pct
        FROM cpp_nav_series n
        JOIN cpp_clients c ON c.id = n.client_id
        WHERE c.is_active = true AND c.is_admin = false
        GROUP BY n.nav_date
        HAVING SUM(n.nav_value) > 0
        ORDER BY n.nav_date
    """))
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame(columns=[
            "nav_date", "total_aum", "total_invested",
            "total_benchmark", "weighted_cash_pct",
        ])

    return pd.DataFrame(
        [(r.nav_date, float(r.total_aum), float(r.total_invested),
          float(r.total_benchmark or 0), float(r.weighted_cash_pct or 0))
         for r in rows],
        columns=["nav_date", "total_aum", "total_invested",
                 "total_benchmark", "weighted_cash_pct"],
    )


def _apply_range_filter(df: pd.DataFrame, range_filter: str) -> pd.DataFrame:
    """Slice DataFrame to trailing N days based on range_filter."""
    days = RANGE_DAYS.get(range_filter.upper())
    if days is None or df.empty:
        return df
    cutoff = df["nav_date"].iloc[-1] - pd.Timedelta(days=days)
    return df[df["nav_date"] >= cutoff].reset_index(drop=True)


async def get_aggregate_nav_series(
    db: AsyncSession, range_filter: str = "ALL",
) -> list[dict[str, Any]]:
    """Aggregate NAV series normalized to base 100, matching individual nav-series shape."""
    agg = await _fetch_aggregate_nav(db)
    if agg.empty:
        return []

    agg = _apply_range_filter(agg, range_filter)
    if agg.empty:
        return []

    port_index = compute_twr_index(pd.Series(agg["total_aum"].values))
    bench_vals = agg["total_benchmark"].values
    bench_index = (
        compute_twr_index(pd.Series(bench_vals))
        if bench_vals[0] > 0 else pd.Series(np.zeros(len(agg)))
    )

    return [
        {
            "date": row["nav_date"].isoformat(),
            "nav": round(float(port_index.iloc[i]), 2),
            "benchmark": round(float(bench_index.iloc[i]), 2),
            "cash_pct": round(row["weighted_cash_pct"], 2),
        }
        for i, (_, row) in enumerate(agg.iterrows())
    ]


async def get_aggregate_risk_metrics(db: AsyncSession) -> dict[str, Any]:
    """Compute risk metrics on the aggregate (firm-wide) NAV series."""
    agg = await _fetch_aggregate_nav(db)
    if len(agg) < 2:
        return _empty_risk_response()

    port_series = pd.Series(agg["total_aum"].values, index=pd.to_datetime(agg["nav_date"]))
    bench_series = pd.Series(agg["total_benchmark"].values, index=pd.to_datetime(agg["nav_date"]))

    daily_port = compute_daily_returns(port_series)
    daily_bench = compute_daily_returns(bench_series)
    daily_excess = daily_port - daily_bench

    total_days = (agg["nav_date"].iloc[-1] - agg["nav_date"].iloc[0]).days
    port_cagr = cagr(float(port_series.iloc[0]), float(port_series.iloc[-1]), total_days)
    bench_cagr_val = cagr(float(bench_series.iloc[0]), float(bench_series.iloc[-1]), total_days)

    vol = annualized_volatility(daily_port)
    sharpe = sharpe_ratio(daily_port, RISK_FREE_RATE)
    sortino_val = sortino_ratio(daily_port, RISK_FREE_RATE)
    dd = max_drawdown(port_series)
    beta_val = beta(daily_port, daily_bench)
    alpha_val = alpha(port_cagr, bench_cagr_val, beta_val, RISK_FREE_RATE)
    up_cap = up_capture(daily_port, daily_bench)
    down_cap = down_capture(daily_port, daily_bench)
    te = tracking_error(daily_excess)
    ir = information_ratio(port_cagr, bench_cagr_val, te)
    ui = ulcer_index(port_series)
    corr = market_correlation(daily_port, daily_bench)

    # Monthly return profile
    monthly_stats = _compute_monthly_profile(agg)

    # Cash metrics
    cash_pct = agg["weighted_cash_pct"]
    avg_cash = float(cash_pct.mean())
    max_cash = float(cash_pct.max())
    current_cash = float(cash_pct.iloc[-1])

    return {
        "alpha": _r2(alpha_val),
        "beta": _r2(beta_val),
        "information_ratio": _r2(ir),
        "tracking_error": _r2(te),
        "up_capture": _r2(up_cap),
        "down_capture": _r2(down_cap),
        "ulcer_index": _r2(ui),
        "market_correlation": _r2(corr),
        "max_drawdown": _r2(dd["max_dd_pct"]),
        "max_dd_start": dd["dd_start"].isoformat() if dd["dd_start"] is not None else None,
        "max_dd_end": dd["dd_end"].isoformat() if dd["dd_end"] is not None else None,
        "max_dd_recovery": dd["dd_recovery"].isoformat() if dd["dd_recovery"] is not None else None,
        "monthly_hit_rate": _r2(monthly_stats["hit_rate"]),
        "best_month": _r2(monthly_stats["best_month"]),
        "worst_month": _r2(monthly_stats["worst_month"]),
        "avg_positive_month": _r2(monthly_stats["avg_positive_month"]),
        "avg_negative_month": _r2(monthly_stats["avg_negative_month"]),
        "max_consecutive_loss": monthly_stats["max_consecutive_loss"],
        "win_months": monthly_stats["win_count"],
        "loss_months": monthly_stats["loss_count"],
        "avg_cash_held": _r2(avg_cash),
        "max_cash_held": _r2(max_cash),
        "current_cash": _r2(current_cash),
        "volatility": _r2(vol),
        "sharpe_ratio": _r2(sharpe),
        "sortino_ratio": _r2(sortino_val),
        "cagr": _r2(port_cagr),
        "bench_cagr": _r2(bench_cagr_val),
    }


async def get_aggregate_performance_table(db: AsyncSession) -> list[dict[str, Any]]:
    """Multi-period performance table for the aggregate portfolio."""
    agg = await _fetch_aggregate_nav(db)
    if len(agg) < 2:
        return []

    total_data_days = (agg["nav_date"].iloc[-1] - agg["nav_date"].iloc[0]).days

    periods = [
        ("1 Month", 30), ("3 Months", 91), ("6 Months", 182),
        ("1 Year", 365), ("2 Years", 730), ("3 Years", 1095),
        ("5 Years", 1826), ("Since Inception", None),
    ]

    results: list[dict[str, Any]] = []
    for label, period_days in periods:
        if period_days is not None and period_days > total_data_days + 15:
            continue

        sliced = _apply_range_filter(agg, "ALL") if period_days is None else agg[
            agg["nav_date"] >= agg["nav_date"].iloc[-1] - pd.Timedelta(days=period_days)
        ]
        if len(sliced) < 2:
            continue

        port_s = pd.Series(sliced["total_aum"].values, index=pd.to_datetime(sliced["nav_date"]))
        bench_s = pd.Series(sliced["total_benchmark"].values, index=pd.to_datetime(sliced["nav_date"]))
        days_in_slice = (sliced["nav_date"].iloc[-1] - sliced["nav_date"].iloc[0]).days

        p_ret = absolute_return(port_s)
        b_ret = absolute_return(bench_s)
        dp = compute_daily_returns(port_s)
        db_r = compute_daily_returns(bench_s)

        results.append({
            "period": label,
            "port_abs_return": _r2(p_ret),
            "bench_abs_return": _r2(b_ret),
            "port_cagr": _r2(cagr(float(port_s.iloc[0]), float(port_s.iloc[-1]), days_in_slice)),
            "bench_cagr": _r2(cagr(float(bench_s.iloc[0]), float(bench_s.iloc[-1]), days_in_slice)),
            "port_volatility": _r2(annualized_volatility(dp)),
            "bench_volatility": _r2(annualized_volatility(db_r)),
            "port_max_dd": _r2(max_drawdown(port_s)["max_dd_pct"]),
            "bench_max_dd": _r2(max_drawdown(bench_s)["max_dd_pct"]),
            "port_sharpe": _r2(sharpe_ratio(dp, RISK_FREE_RATE)),
            "bench_sharpe": _r2(sharpe_ratio(db_r, RISK_FREE_RATE)),
            "port_sortino": _r2(sortino_ratio(dp, RISK_FREE_RATE)),
            "bench_sortino": _r2(sortino_ratio(db_r, RISK_FREE_RATE)),
        })

    return results


async def get_aggregate_allocation(db: AsyncSession) -> dict[str, Any]:
    """Sector allocation across all active non-admin client holdings."""
    result = await db.execute(text("""
        SELECT
            COALESCE(h.sector, 'Other') AS sector,
            SUM(h.current_value)        AS total_value
        FROM cpp_holdings h
        JOIN cpp_clients c ON c.id = h.client_id
        WHERE c.is_active = true AND c.is_admin = false
          AND h.quantity > 0
          AND h.current_value > 0
        GROUP BY COALESCE(h.sector, 'Other')
        ORDER BY total_value DESC
    """))
    rows = result.fetchall()
    total = sum(float(r.total_value) for r in rows) if rows else 0.0

    by_sector = [
        {
            "name": r.sector,
            "value": _r2(float(r.total_value)),
            "weight_pct": _r2(float(r.total_value) / total * 100 if total > 0 else 0),
        }
        for r in rows
    ]
    return {"by_sector": by_sector}


async def get_aggregate_monthly_returns(db: AsyncSession) -> dict[str, Any]:
    """Monthly return heatmap data from the aggregate NAV series."""
    agg = await _fetch_aggregate_nav(db)
    if len(agg) < 30:
        return {"heatmap": [], "stats": _empty_monthly_stats()}

    monthly_stats = _compute_monthly_profile(agg)

    # Build heatmap data
    monthly_last: dict[tuple[int, int], float] = {}
    for _, row in agg.iterrows():
        key = (row["nav_date"].year, row["nav_date"].month)
        monthly_last[key] = row["total_aum"]

    sorted_keys = sorted(monthly_last.keys())
    heatmap: list[dict[str, Any]] = []
    months_abbr = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for i in range(1, len(sorted_keys)):
        prev_val = monthly_last[sorted_keys[i - 1]]
        curr_val = monthly_last[sorted_keys[i]]
        if prev_val > 0:
            ret = ((curr_val - prev_val) / prev_val) * 100
            year, month = sorted_keys[i]
            heatmap.append({
                "year": year,
                "month": month - 1,
                "return_pct": round(ret, 2),
                "label": f"{months_abbr[month - 1]} {year}",
            })

    return {
        "heatmap": heatmap,
        "stats": {
            "hit_rate": _r2(monthly_stats["hit_rate"]),
            "best_month": _r2(monthly_stats["best_month"]),
            "worst_month": _r2(monthly_stats["worst_month"]),
            "avg_positive_month": _r2(monthly_stats["avg_positive_month"]),
            "avg_negative_month": _r2(monthly_stats["avg_negative_month"]),
            "max_consecutive_loss": monthly_stats["max_consecutive_loss"],
            "win_count": monthly_stats["win_count"],
            "loss_count": monthly_stats["loss_count"],
        },
    }


# ── Private helpers ──────────────────────────────────────────────────────


def _r2(val: float) -> str:
    """Round float to 2 decimal places, return as string."""
    return f"{val:.2f}"


def _compute_monthly_profile(agg: pd.DataFrame) -> dict[str, Any]:
    """Compute monthly return stats from aggregate DataFrame."""
    monthly_last: dict[tuple[int, int], float] = {}
    for _, row in agg.iterrows():
        key = (row["nav_date"].year, row["nav_date"].month)
        monthly_last[key] = row["total_aum"]

    sorted_keys = sorted(monthly_last.keys())
    monthly_rets: list[float] = []
    for i in range(1, len(sorted_keys)):
        prev_val = monthly_last[sorted_keys[i - 1]]
        curr_val = monthly_last[sorted_keys[i]]
        if prev_val > 0:
            monthly_rets.append(((curr_val - prev_val) / prev_val) * 100)

    if not monthly_rets:
        return _empty_monthly_stats()

    rets = np.array(monthly_rets)
    positive = rets[rets > 0]
    negative = rets[rets <= 0]

    # Max consecutive loss streak
    is_loss = (rets <= 0).astype(int)
    max_consec = 0
    current_streak = 0
    for loss in is_loss:
        if loss:
            current_streak += 1
            max_consec = max(max_consec, current_streak)
        else:
            current_streak = 0

    return {
        "hit_rate": float(len(positive) / len(rets) * 100),
        "best_month": float(rets.max()),
        "worst_month": float(rets.min()),
        "avg_positive_month": float(positive.mean()) if len(positive) > 0 else 0.0,
        "avg_negative_month": float(negative.mean()) if len(negative) > 0 else 0.0,
        "max_consecutive_loss": max_consec,
        "win_count": int(len(positive)),
        "loss_count": int(len(negative)),
    }


def _empty_monthly_stats() -> dict[str, Any]:
    return {
        "hit_rate": 0.0, "best_month": 0.0, "worst_month": 0.0,
        "avg_positive_month": 0.0, "avg_negative_month": 0.0,
        "max_consecutive_loss": 0, "win_count": 0, "loss_count": 0,
    }


def _empty_risk_response() -> dict[str, Any]:
    """Return zeroed-out risk response when data is insufficient."""
    return {
        "alpha": "0.00", "beta": "0.00", "information_ratio": "0.00",
        "tracking_error": "0.00", "up_capture": "0.00", "down_capture": "0.00",
        "ulcer_index": "0.00", "market_correlation": "0.00",
        "max_drawdown": "0.00", "max_dd_start": None, "max_dd_end": None,
        "max_dd_recovery": None, "monthly_hit_rate": "0.00",
        "best_month": "0.00", "worst_month": "0.00",
        "avg_positive_month": "0.00", "avg_negative_month": "0.00",
        "max_consecutive_loss": 0, "win_months": 0, "loss_months": 0,
        "avg_cash_held": "0.00", "max_cash_held": "0.00", "current_cash": "0.00",
        "volatility": "0.00", "sharpe_ratio": "0.00", "sortino_ratio": "0.00",
        "cagr": "0.00", "bench_cagr": "0.00",
    }
