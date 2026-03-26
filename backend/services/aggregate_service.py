"""Aggregate portfolio analytics — computes firm-wide metrics across all active clients.

All functions operate on the SUM of NAV values across clients, producing a single
"firm portfolio" time series. Risk metrics are then computed on this aggregate series
using the same functions used for individual client metrics.
"""

from __future__ import annotations

import logging
import time
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

# In-memory cache for expensive composite index (TTL = 5 minutes)
_CACHE_TTL = 300
_cache: dict[str, Any] = {"ts": 0, "agg": None, "port": None, "bench": None}


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


async def _get_cached_composite(db: AsyncSession) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Return (agg_df, port_composite, bench_composite) with 5-min TTL cache."""
    now = time.time()
    if now - _cache["ts"] < _CACHE_TTL and _cache["agg"] is not None:
        return _cache["agg"], _cache["port"], _cache["bench"]

    agg = await _fetch_aggregate_nav(db)
    per_client = await _fetch_per_client_nav(db)
    if per_client.empty:
        port_s = pd.Series(dtype=float)
        bench_s = pd.Series(dtype=float)
    else:
        port_s, bench_s = _build_composite_index(per_client)

    _cache["ts"] = now
    _cache["agg"] = agg
    _cache["port"] = port_s
    _cache["bench"] = bench_s
    return agg, port_s, bench_s


async def _fetch_per_client_nav(db: AsyncSession) -> pd.DataFrame:
    """Fetch per-client daily NAV for AUM-weighted return computation.

    Returns DataFrame with columns: nav_date, client_id, nav_value, benchmark_value.
    """
    result = await db.execute(text("""
        SELECT n.nav_date, n.client_id, n.nav_value, n.benchmark_value
        FROM cpp_nav_series n
        JOIN cpp_clients c ON c.id = n.client_id
        WHERE c.is_active = true AND c.is_admin = false
          AND n.nav_value > 0
        ORDER BY n.nav_date, n.client_id
    """))
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame(columns=["nav_date", "client_id", "nav_value", "benchmark_value"])
    return pd.DataFrame(
        [(r.nav_date, r.client_id, float(r.nav_value), float(r.benchmark_value or 0)) for r in rows],
        columns=["nav_date", "client_id", "nav_value", "benchmark_value"],
    )


def _build_composite_index(per_client: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Build AUM-weighted composite return index from per-client NAV data.

    Vectorized: pivots once, computes daily returns and weights as matrices,
    then multiplies in one shot. ~100x faster than the per-date loop.

    Returns (portfolio_index, benchmark_index) both starting at 100.
    """
    if per_client.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    # Pivot to matrices: rows=dates, cols=clients
    pivot_nav = per_client.pivot_table(
        index="nav_date", columns="client_id", values="nav_value",
    ).sort_index()
    pivot_bench = per_client.pivot_table(
        index="nav_date", columns="client_id", values="benchmark_value",
    ).sort_index()

    # Per-client daily returns (NaN where client missing on either day)
    nav_vals = pivot_nav.values  # (T, C) numpy array
    prev_nav = nav_vals[:-1]     # (T-1, C)
    curr_nav = nav_vals[1:]      # (T-1, C)

    # Mask: client present on BOTH consecutive days
    both_present = ~np.isnan(prev_nav) & ~np.isnan(curr_nav) & (prev_nav > 0)

    # Portfolio daily returns per client
    with np.errstate(divide="ignore", invalid="ignore"):
        port_rets = np.where(both_present, (curr_nav - prev_nav) / prev_nav, 0.0)

    # Weights = prev-day AUM / total prev-day AUM (only for present clients)
    masked_prev = np.where(both_present, prev_nav, 0.0)
    row_totals = masked_prev.sum(axis=1, keepdims=True)
    row_totals = np.where(row_totals > 0, row_totals, 1.0)  # avoid /0
    weights = masked_prev / row_totals

    # Weighted portfolio return per day
    weighted_port_daily = (port_rets * weights).sum(axis=1)  # (T-1,)

    # Benchmark daily returns per client
    bench_vals = pivot_bench.values
    prev_bench = bench_vals[:-1]
    curr_bench = bench_vals[1:]
    bench_present = both_present & ~np.isnan(prev_bench) & ~np.isnan(curr_bench) & (prev_bench > 0)

    with np.errstate(divide="ignore", invalid="ignore"):
        bench_rets = np.where(bench_present, (curr_bench - prev_bench) / prev_bench, 0.0)

    weighted_bench_daily = (bench_rets * weights).sum(axis=1)  # (T-1,)

    # Compound into index starting at 100
    port_cum = 100.0 * np.cumprod(1.0 + weighted_port_daily)
    bench_cum = 100.0 * np.cumprod(1.0 + weighted_bench_daily)

    port_index = np.concatenate([[100.0], port_cum])
    bench_index_arr = np.concatenate([[100.0], bench_cum])

    idx = pd.DatetimeIndex(pivot_nav.index)
    return (
        pd.Series(port_index, index=idx),
        pd.Series(bench_index_arr, index=idx),
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
    """Aggregate NAV series — shows actual total AUM + Nifty equivalent.

    Portfolio line: actual total AUM across all clients (₹ crores).
    Benchmark line: what that same money would be worth in Nifty,
    adjusted for the same cash inflows/outflows as the actual portfolio.
    Cash %: AUM-weighted average cash allocation.
    """
    agg, _, bench_composite = await _get_cached_composite(db)
    if agg.empty:
        return []

    agg = _apply_range_filter(agg, range_filter)
    if agg.empty:
        return []

    total_aum = agg["total_aum"].values
    first_invested = agg["total_invested"].iloc[0]

    results = []
    for i, (_, row) in enumerate(agg.iterrows()):
        nav_date = row["nav_date"]
        port_val = float(total_aum[i])

        # Benchmark: invested amount scaled by Nifty composite growth from inception
        if bench_composite is not None and nav_date in bench_composite.index:
            bench_growth = float(bench_composite.loc[nav_date]) / 100.0  # composite is base-100
            bench_val = float(first_invested) * bench_growth
        else:
            bench_val = float(row["total_benchmark"]) if row["total_benchmark"] > 0 else 0

        results.append({
            "date": nav_date.isoformat(),
            "nav": round(port_val, 0),
            "benchmark": round(bench_val, 0),
            "cash_pct": round(row["weighted_cash_pct"], 2),
        })

    return results


async def get_aggregate_risk_metrics(db: AsyncSession) -> dict[str, Any]:
    """Compute risk metrics on the aggregate (firm-wide) NAV series.

    Uses AUM-weighted daily returns across all clients to build a composite
    index. This eliminates distortion from new clients joining the firm.
    """
    agg, port_series, bench_series = await _get_cached_composite(db)
    if len(port_series) < 2:
        return _empty_risk_response()

    daily_port = compute_daily_returns(port_series)
    daily_bench = compute_daily_returns(bench_series)
    daily_excess = daily_port - daily_bench

    total_days = (port_series.index[-1] - port_series.index[0]).days
    port_cagr = cagr(100.0, float(port_series.iloc[-1]), total_days)
    bench_cagr_val = cagr(100.0, float(bench_series.iloc[-1]), total_days)

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

    # Monthly return profile from composite index (not raw AUM)
    monthly_composite = port_series.resample("ME").last().dropna()
    monthly_ret_series = monthly_composite.pct_change().dropna() * 100
    rets_arr = monthly_ret_series.values
    pos_rets = rets_arr[rets_arr > 0]
    neg_rets = rets_arr[rets_arr <= 0]
    _max_consec = 0
    _cur_streak = 0
    for _loss in (rets_arr <= 0).astype(int):
        if _loss:
            _cur_streak += 1
            _max_consec = max(_max_consec, _cur_streak)
        else:
            _cur_streak = 0
    monthly_stats = {
        "hit_rate": float(len(pos_rets) / len(rets_arr) * 100) if len(rets_arr) > 0 else 0.0,
        "best_month": float(rets_arr.max()) if len(rets_arr) > 0 else 0.0,
        "worst_month": float(rets_arr.min()) if len(rets_arr) > 0 else 0.0,
        "avg_positive_month": float(pos_rets.mean()) if len(pos_rets) > 0 else 0.0,
        "avg_negative_month": float(neg_rets.mean()) if len(neg_rets) > 0 else 0.0,
        "max_consecutive_loss": _max_consec,
        "win_count": int(len(pos_rets)),
        "loss_count": int(len(neg_rets)),
    }

    # Cash metrics (agg already fetched via cache)
    cash_pct = agg["weighted_cash_pct"] if not agg.empty else pd.Series([0.0])
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
    """Multi-period performance table using AUM-weighted composite index."""
    _, port_composite, bench_composite = await _get_cached_composite(db)
    if len(port_composite) < 2:
        return []

    total_data_days = (port_composite.index[-1] - port_composite.index[0]).days

    periods = [
        ("1 Month", 30), ("3 Months", 91), ("6 Months", 182),
        ("1 Year", 365), ("2 Years", 730), ("3 Years", 1095),
        ("5 Years", 1826), ("Since Inception", None),
    ]

    results: list[dict[str, Any]] = []
    for label, period_days in periods:
        if period_days is not None and period_days > total_data_days + 15:
            continue

        if period_days is None:
            port_s = port_composite
            bench_s = bench_composite
        else:
            cutoff = port_composite.index[-1] - pd.Timedelta(days=period_days)
            port_s = port_composite[port_composite.index >= cutoff]
            bench_s = bench_composite[bench_composite.index >= cutoff]

        if len(port_s) < 2:
            continue

        days_in_slice = (port_s.index[-1] - port_s.index[0]).days
        dp = compute_daily_returns(port_s)
        db_r = compute_daily_returns(bench_s)

        results.append({
            "period": label,
            "port_abs_return": _r2(absolute_return(port_s)),
            "bench_abs_return": _r2(absolute_return(bench_s)),
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
    """Monthly return heatmap data using AUM-weighted composite index.

    Uses the composite index (not raw AUM sums) to avoid distortion
    from new clients joining — which would show as huge monthly "returns".
    """
    _, port_composite, _ = await _get_cached_composite(db)
    if len(port_composite) < 30:
        return {"heatmap": [], "stats": _empty_monthly_stats()}

    # Resample composite index to monthly (last value per month)
    monthly = port_composite.resample("ME").last().dropna()
    monthly_ret = monthly.pct_change().dropna() * 100

    # Build heatmap
    months_abbr = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    heatmap: list[dict[str, Any]] = []
    for dt, ret in monthly_ret.items():
        heatmap.append({
            "year": dt.year,
            "month": dt.month - 1,
            "return_pct": round(float(ret), 2),
            "label": f"{months_abbr[dt.month - 1]} {dt.year}",
        })

    # Compute stats from composite monthly returns
    rets = monthly_ret.values
    positive = rets[rets > 0]
    negative = rets[rets <= 0]

    is_loss = (rets <= 0).astype(int)
    max_consec = 0
    current_streak = 0
    for loss in is_loss:
        if loss:
            current_streak += 1
            max_consec = max(max_consec, current_streak)
        else:
            current_streak = 0

    stats = {
        "hit_rate": _r2(float(len(positive) / len(rets) * 100)) if len(rets) > 0 else "0.00",
        "best_month": _r2(float(rets.max())) if len(rets) > 0 else "0.00",
        "worst_month": _r2(float(rets.min())) if len(rets) > 0 else "0.00",
        "avg_positive_month": _r2(float(positive.mean())) if len(positive) > 0 else "0.00",
        "avg_negative_month": _r2(float(negative.mean())) if len(negative) > 0 else "0.00",
        "max_consecutive_loss": max_consec,
        "win_count": int(len(positive)),
        "loss_count": int(len(negative)),
    }

    return {"heatmap": heatmap, "stats": stats}


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
