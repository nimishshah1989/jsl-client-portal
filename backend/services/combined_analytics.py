"""Combined-view analytics — risk, performance, drawdown, allocation for ONE
client's live portfolios.

Builds a combined base-100 composite index from the client's combined NAV
(TWR-adjusted to strip corpus flows; benchmark = Nifty daily returns), then
reuses the same risk/performance functions as the per-portfolio and admin
aggregate paths. Allocation is the live portfolios' holdings grouped by sector.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.routers.helpers import date_cutoff
from backend.services.combined_service import fetch_combined_nav_df
from backend.services.risk_metrics import (
    absolute_return,
    annualized_volatility,
    cagr,
    compute_daily_returns,
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

RISK_FREE_RATE = float(get_settings().RISK_FREE_RATE)


def _r2(v: float) -> str:
    return f"{v:.2f}"


def _dd_pct(s: pd.Series) -> float:
    """Worst peak-to-trough drawdown (%) of a price series. Robust on monotonic
    series (returns 0.0) — unlike the shared max_drawdown, which argmax-errors
    when the trough is at index 0."""
    if len(s) < 2:
        return 0.0
    return float(((s - s.cummax()) / s.cummax() * 100).min())


def _composite(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Return (port_index, bench_index) base-100 series indexed by date.

    port: TWR-adjusted combined returns (corpus flows removed).
    bench: Nifty daily returns (bench_price is the same index across the
    client's portfolios on a date).
    """
    if len(df) < 2:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    nav = df["nav"].to_numpy()
    invested = df["invested"].to_numpy()
    price = pd.Series(df["bench_price"].to_numpy()).ffill().bfill().to_numpy()
    n = len(df)
    port_ret = np.zeros(n)
    bench_ret = np.zeros(n)
    for i in range(1, n):
        adj_prev = nav[i - 1] + (invested[i] - invested[i - 1])
        if nav[i - 1] > 0 and adj_prev > 0:
            port_ret[i] = nav[i] / adj_prev - 1
        if np.isfinite(price[i]) and np.isfinite(price[i - 1]) and price[i - 1] > 0:
            bench_ret[i] = price[i] / price[i - 1] - 1
    idx = pd.DatetimeIndex(pd.to_datetime(df["nav_date"]))
    return (
        pd.Series(100.0 * np.cumprod(1.0 + port_ret), index=idx),
        pd.Series(100.0 * np.cumprod(1.0 + bench_ret), index=idx),
    )


def _empty_risk() -> dict[str, Any]:
    keys = [
        "alpha", "beta", "information_ratio", "tracking_error", "up_capture",
        "down_capture", "ulcer_index", "market_correlation", "max_drawdown",
        "monthly_hit_rate", "best_month", "worst_month", "avg_positive_month",
        "avg_negative_month", "volatility", "sharpe_ratio", "sortino_ratio",
        "cagr", "bench_cagr", "avg_cash_held", "max_cash_held", "current_cash",
    ]
    out: dict[str, Any] = {k: "0.00" for k in keys}
    out.update({"max_consecutive_loss": 0, "win_months": 0, "loss_months": 0,
                "max_dd_start": None, "max_dd_end": None, "max_dd_recovery": None})
    return out


async def get_combined_risk_metrics(db: AsyncSession, client_id: int) -> dict[str, Any]:
    df = await fetch_combined_nav_df(db, client_id)
    port, bench = _composite(df)
    if len(port) < 2:
        return _empty_risk()

    daily_p = compute_daily_returns(port)
    daily_b = compute_daily_returns(bench)
    daily_excess = daily_p - daily_b
    days = (port.index[-1] - port.index[0]).days or 1
    port_cagr = cagr(100.0, float(port.iloc[-1]), days)
    bench_cagr = cagr(100.0, float(bench.iloc[-1]), days)
    vol = annualized_volatility(daily_p)
    te = tracking_error(daily_excess)
    beta_v = beta(daily_p, daily_b)

    # Drawdown pct + dates, computed inline (robust on monotonic series).
    dd_series = (port - port.cummax()) / port.cummax() * 100
    max_dd_pct = float(dd_series.min())
    trough_ts = dd_series.idxmin()
    pre = port.loc[:trough_ts]            # inclusive — never empty
    peak_ts = pre.idxmax()
    peak_val = float(port.loc[peak_ts])
    post = port.loc[trough_ts:]
    recovered = post[post >= peak_val]
    recovery_ts = recovered.index[0] if len(recovered) else None

    monthly = port.resample("ME").last().dropna().pct_change().dropna() * 100
    rets = monthly.to_numpy()
    pos = rets[rets > 0]
    neg = rets[rets < 0]
    streak = mx = 0
    for loss in (rets < 0).astype(int):
        streak = streak + 1 if loss else 0
        mx = max(mx, streak)

    cash = df["cash_amt"].to_numpy() / np.where(df["nav"].to_numpy() > 0, df["nav"].to_numpy(), 1) * 100

    return {
        "alpha": _r2(alpha(port_cagr, bench_cagr, beta_v, RISK_FREE_RATE)),
        "beta": _r2(beta_v),
        "information_ratio": _r2(information_ratio(port_cagr, bench_cagr, te)),
        "tracking_error": _r2(te),
        "up_capture": _r2(up_capture(daily_p, daily_b)),
        "down_capture": _r2(down_capture(daily_p, daily_b)),
        "ulcer_index": _r2(ulcer_index(port)),
        "market_correlation": _r2(market_correlation(daily_p, daily_b)),
        "max_drawdown": _r2(max_dd_pct),
        "max_dd_start": peak_ts.date().isoformat(),
        "max_dd_end": trough_ts.date().isoformat(),
        "max_dd_recovery": recovery_ts.date().isoformat() if recovery_ts is not None else None,
        "monthly_hit_rate": _r2(len(pos) / len(rets) * 100) if len(rets) else "0.00",
        "best_month": _r2(float(rets.max())) if len(rets) else "0.00",
        "worst_month": _r2(float(rets.min())) if len(rets) else "0.00",
        "avg_positive_month": _r2(float(pos.mean())) if len(pos) else "0.00",
        "avg_negative_month": _r2(float(neg.mean())) if len(neg) else "0.00",
        "max_consecutive_loss": int(mx),
        "win_months": int(len(pos)),
        "loss_months": int(len(neg)),
        "avg_cash_held": _r2(float(np.mean(cash))) if len(cash) else "0.00",
        "max_cash_held": _r2(float(np.max(cash))) if len(cash) else "0.00",
        "current_cash": _r2(float(cash[-1])) if len(cash) else "0.00",
        "volatility": _r2(vol),
        "sharpe_ratio": _r2(sharpe_ratio(port_cagr, vol, RISK_FREE_RATE)),
        "sortino_ratio": _r2(sortino_ratio(port_cagr, daily_p, RISK_FREE_RATE)),
        "cagr": _r2(port_cagr),
        "bench_cagr": _r2(bench_cagr),
    }


async def get_combined_performance_table(db: AsyncSession, client_id: int) -> list[dict[str, Any]]:
    df = await fetch_combined_nav_df(db, client_id)
    port, bench = _composite(df)
    if len(port) < 2:
        return []
    total_days = (port.index[-1] - port.index[0]).days
    periods = [
        ("1 Month", 30), ("3 Months", 91), ("6 Months", 182), ("1 Year", 365),
        ("2 Years", 730), ("3 Years", 1095), ("5 Years", 1826), ("Since Inception", None),
    ]
    out: list[dict[str, Any]] = []
    for label, pdays in periods:
        if pdays is not None and pdays > total_days + 15:
            continue
        if pdays is None:
            ps, bs = port, bench
        else:
            cutoff = port.index[-1] - pd.Timedelta(days=pdays)
            ps, bs = port[port.index >= cutoff], bench[bench.index >= cutoff]
        if len(ps) < 2:
            continue
        d = (ps.index[-1] - ps.index[0]).days
        dp, dbb = compute_daily_returns(ps), compute_daily_returns(bs)
        pc, bc = cagr(float(ps.iloc[0]), float(ps.iloc[-1]), d), cagr(float(bs.iloc[0]), float(bs.iloc[-1]), d)
        pv, bv = annualized_volatility(dp), annualized_volatility(dbb)
        out.append({
            "period": label,
            "port_abs_return": _r2(absolute_return(ps)), "bench_abs_return": _r2(absolute_return(bs)),
            "port_cagr": _r2(pc), "bench_cagr": _r2(bc),
            "port_volatility": _r2(pv), "bench_volatility": _r2(bv),
            "port_max_dd": _r2(_dd_pct(ps)), "bench_max_dd": _r2(_dd_pct(bs)),
            "port_sharpe": _r2(sharpe_ratio(pc, pv, RISK_FREE_RATE)), "bench_sharpe": _r2(sharpe_ratio(bc, bv, RISK_FREE_RATE)),
            "port_sortino": _r2(sortino_ratio(pc, dp, RISK_FREE_RATE)), "bench_sortino": _r2(sortino_ratio(bc, dbb, RISK_FREE_RATE)),
        })
    return out


async def get_combined_drawdown_series(
    db: AsyncSession, client_id: int, range_filter: str = "ALL",
) -> list[dict[str, Any]]:
    df = await fetch_combined_nav_df(db, client_id)
    port, bench = _composite(df)
    if len(port) < 2:
        return []
    port_dd = (port - port.cummax()) / port.cummax() * 100
    bench_dd = (bench - bench.cummax()) / bench.cummax() * 100
    cutoff = date_cutoff(range_filter, port.index[-1].date())
    out = []
    for ts in port.index:
        if cutoff is not None and ts.date() < cutoff:
            continue
        out.append({
            "date": ts.date().isoformat(),
            "drawdown_pct": _r2(float(port_dd.loc[ts])),
            "bench_drawdown": _r2(float(bench_dd.loc[ts])),
        })
    return out


async def get_combined_allocation(db: AsyncSession, client_id: int) -> dict[str, Any]:
    """Sector allocation across the client's live portfolios."""
    rows = (await db.execute(text("""
        SELECT COALESCE(h.sector, 'Other') AS sector, SUM(h.current_value) AS val
        FROM cpp_holdings h
        JOIN cpp_portfolios p ON p.id = h.portfolio_id
        WHERE h.client_id = :cid AND p.is_closed = false
          AND h.quantity > 0 AND h.current_value > 0
        GROUP BY COALESCE(h.sector, 'Other')
        ORDER BY val DESC
    """), {"cid": client_id})).fetchall()
    total = sum(float(r.val) for r in rows) if rows else 0.0
    by_sector = [
        {"name": r.sector, "value": _r2(float(r.val)),
         "weight_pct": _r2(float(r.val) / total * 100 if total else 0.0)}
        for r in rows
    ]
    return {"by_sector": by_sector}
