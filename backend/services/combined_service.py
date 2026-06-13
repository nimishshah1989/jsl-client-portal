"""Combined-view service — aggregates ONE client's live portfolios into a single
view (NAV series, summary cards, merged holdings).

"Live" excludes closed portfolios (is_closed). For a client with a single
portfolio the combined view equals that portfolio. ₹ quantities are additive
(summed across portfolios); returns/ratios are recomputed from the combined
TWR series — they are never summed.

Reconciliation invariants (see tests/test_combined_service.py):
  - combined invested / current / nav-per-date == sum of the client's live
    portfolios
  - combined holding qty / value per symbol == sum across portfolios
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.holding import Holding
from backend.models.transaction import Transaction
from backend.routers.helpers import date_cutoff
from backend.services.risk_metrics import cagr

_ZERO = Decimal("0")
_TWO = Decimal("0.01")


def _d2(v: Decimal | float | None) -> str:
    if v is None:
        return "0.00"
    return str(Decimal(str(v)).quantize(_TWO, rounding=ROUND_HALF_UP))


async def _live_portfolio_ids(db: AsyncSession, client_id: int) -> list[int]:
    """Portfolio ids for a client's LIVE (not closed) portfolios."""
    rows = (await db.execute(text(
        "SELECT id FROM cpp_portfolios WHERE client_id = :cid AND is_closed = false"
    ), {"cid": client_id})).fetchall()
    return [r[0] for r in rows]


async def fetch_combined_nav_df(db: AsyncSession, client_id: int) -> pd.DataFrame:
    """Daily combined NAV across the client's live portfolios.

    Columns: nav_date, nav (Σ current_value), invested (Σ invested_amount),
    bench_price (Nifty close — identical across a client's portfolios on a
    date), cash_amt (Σ etf+cash+bank). Sorted by date.
    """
    result = await db.execute(text("""
        SELECT
            n.nav_date,
            SUM(n.current_value)                                        AS nav,
            SUM(n.invested_amount)                                      AS invested,
            MAX(n.benchmark_value)                                      AS bench_price,
            SUM(COALESCE(n.etf_value,0) + COALESCE(n.cash_value,0)
                + COALESCE(n.bank_balance,0))                          AS cash_amt
        FROM cpp_nav_series n
        JOIN cpp_portfolios p ON p.id = n.portfolio_id
        WHERE n.client_id = :cid AND p.is_closed = false
        GROUP BY n.nav_date
        HAVING SUM(n.current_value) > 0
        ORDER BY n.nav_date
    """), {"cid": client_id})
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame(columns=["nav_date", "nav", "invested", "bench_price", "cash_amt"])
    df = pd.DataFrame(
        [(r.nav_date, float(r.nav), float(r.invested or 0),
          float(r.bench_price) if r.bench_price else np.nan,
          float(r.cash_amt or 0)) for r in rows],
        columns=["nav_date", "nav", "invested", "bench_price", "cash_amt"],
    )
    # Normalise nav_date to python date objects — Postgres returns date, SQLite
    # (tests) returns str. Keeps date arithmetic + isoformat consistent.
    df["nav_date"] = pd.to_datetime(df["nav_date"]).dt.date
    return df


def _twr_index(nav: np.ndarray, invested: np.ndarray) -> np.ndarray:
    """Base-100 time-weighted index that strips corpus inflows/outflows.

    On each step the previous NAV is adjusted by the corpus change so new cash
    is not counted as return (mirrors the per-portfolio YTD/risk-engine logic).
    """
    idx = np.empty(len(nav))
    idx[0] = 100.0
    level = 100.0
    for i in range(1, len(nav)):
        prev = nav[i - 1]
        corpus_chg = invested[i] - invested[i - 1]
        adj_prev = prev + corpus_chg
        if prev > 0 and adj_prev > 0:
            level *= nav[i] / adj_prev
        idx[i] = level
    return idx


def _nifty_equiv(df: pd.DataFrame) -> np.ndarray:
    """What the client's combined invested capital would be worth in Nifty,
    using the virtual-units method on combined corpus changes."""
    invested = df["invested"].to_numpy()
    price = pd.Series(df["bench_price"].to_numpy()).ffill().bfill().to_numpy()
    flows = np.diff(invested, prepend=0.0)
    flows[0] = invested[0]
    units = 0.0
    out = np.zeros(len(df))
    for i in range(len(df)):
        p = price[i]
        if np.isfinite(p) and p > 0:
            units += flows[i] / p
            out[i] = units * p
        else:
            out[i] = out[i - 1] if i else 0.0
    return out


async def get_combined_nav_series(
    db: AsyncSession, client_id: int, range_filter: str = "ALL",
) -> list[dict[str, Any]]:
    """Combined portfolio-value series + Nifty equivalent + cash %."""
    df = await fetch_combined_nav_df(db, client_id)
    if df.empty:
        return []
    nifty = _nifty_equiv(df)
    cutoff = date_cutoff(range_filter, df["nav_date"].iloc[-1])

    points: list[dict[str, Any]] = []
    for i, row in df.iterrows():
        if cutoff is not None and row["nav_date"] < cutoff:
            continue
        nav_v = row["nav"]
        cash_pct = (row["cash_amt"] / nav_v * 100) if nav_v > 0 else 0.0
        points.append({
            "date": row["nav_date"].isoformat() if hasattr(row["nav_date"], "isoformat") else str(row["nav_date"]),
            "nav": _d2(nav_v),
            "benchmark": _d2(nifty[i]) if nifty[i] > 0 else None,
            "invested": _d2(row["invested"]),
            "cash_pct": _d2(max(0.0, min(100.0, cash_pct))),
        })
    return points


async def get_combined_summary(db: AsyncSession, client_id: int) -> dict[str, Any]:
    """Combined summary cards. ₹ are additive; CAGR / max DD recomputed from the
    combined TWR series."""
    df = await fetch_combined_nav_df(db, client_id)
    if df.empty:
        return {}

    invested = Decimal(str(df["invested"].iloc[-1]))
    current = Decimal(str(df["nav"].iloc[-1]))
    profit = current - invested
    profit_pct = (profit / invested * 100) if invested else _ZERO
    cash_amt = Decimal(str(df["cash_amt"].iloc[-1]))
    cash_pct = (cash_amt / current * 100) if current else _ZERO

    cagr_pct = _ZERO
    max_dd = _ZERO
    if len(df) >= 2:
        twr = pd.Series(_twr_index(df["nav"].to_numpy(), df["invested"].to_numpy()))
        days = (df["nav_date"].iloc[-1] - df["nav_date"].iloc[0]).days
        cagr_pct = Decimal(str(cagr(100.0, float(twr.iloc[-1]), days)))
        # Worst peak-to-trough on the TWR series; 0 when monotonic.
        drawdown = (twr - twr.cummax()) / twr.cummax() * 100
        max_dd = Decimal(str(float(drawdown.min())))

    return {
        "invested": _d2(invested),
        "current_value": _d2(current),
        "profit_amount": _d2(profit),
        "profit_pct": _d2(profit_pct),
        "cagr": _d2(cagr_pct),
        "max_drawdown": _d2(max_dd),
        "cash_amount": _d2(cash_amt),
        "cash_pct": _d2(max(_ZERO, min(Decimal("100"), cash_pct))),
        "as_of_date": df["nav_date"].iloc[-1].isoformat()
        if hasattr(df["nav_date"].iloc[-1], "isoformat") else str(df["nav_date"].iloc[-1]),
        "portfolio_count": len(await _live_portfolio_ids(db, client_id)),
    }


async def get_combined_transactions(
    db: AsyncSession,
    client_id: int,
    page: int = 1,
    per_page: int = 50,
    txn_type: str | None = None,
    asset_class: str | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> dict[str, Any]:
    """Paginated transactions across the client's live portfolios."""
    live = await _live_portfolio_ids(db, client_id)
    if not live:
        return {"items": [], "total": 0, "page": page, "per_page": per_page, "total_pages": 1}

    base = (
        select(Transaction)
        .where(Transaction.client_id == client_id)
        .where(Transaction.portfolio_id.in_(live))
    )
    if txn_type:
        base = base.where(Transaction.txn_type == txn_type.upper())
    if asset_class:
        base = base.where(Transaction.asset_class == asset_class.upper())
    if date_from:
        base = base.where(Transaction.txn_date >= date_from)
    if date_to:
        base = base.where(Transaction.txn_date <= date_to)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    offset = (page - 1) * per_page
    txns = list((await db.execute(
        base.order_by(desc(Transaction.txn_date), desc(Transaction.id)).offset(offset).limit(per_page)
    )).scalars().all())
    total_pages = max(1, (total + per_page - 1) // per_page)

    items = [
        {
            "id": t.id,
            "txn_date": t.txn_date.isoformat() if hasattr(t.txn_date, "isoformat") else str(t.txn_date),
            "txn_type": t.txn_type, "symbol": t.symbol, "asset_name": t.asset_name,
            "asset_class": t.asset_class,
            "quantity": _d2(t.quantity) if t.quantity is not None else None,
            "price": _d2(t.price) if t.price is not None else None,
            "amount": _d2(t.amount),
        }
        for t in txns
    ]
    return {"items": items, "total": total, "page": page, "per_page": per_page, "total_pages": total_pages}


def merge_holdings(rows: list[dict]) -> list[dict]:
    """Merge holdings by symbol across portfolios (pure — unit tested).

    qty/value/pnl summed; avg_cost is quantity-weighted; weight recomputed on
    the combined total. Input rows: symbol, asset_name, sector, asset_class,
    quantity, avg_cost, current_price, current_value, unrealized_pnl.
    """
    agg: dict[str, dict] = {}
    for r in rows:
        sym = r["symbol"]
        a = agg.setdefault(sym, {
            "symbol": sym, "asset_name": r.get("asset_name"), "sector": r.get("sector"),
            "asset_class": r.get("asset_class"), "quantity": _ZERO, "cost_basis": _ZERO,
            "current_value": _ZERO, "unrealized_pnl": _ZERO, "current_price": r.get("current_price"),
        })
        qty = Decimal(str(r.get("quantity") or 0))
        avg = Decimal(str(r.get("avg_cost") or 0))
        a["quantity"] += qty
        a["cost_basis"] += qty * avg
        a["current_value"] += Decimal(str(r.get("current_value") or 0))
        a["unrealized_pnl"] += Decimal(str(r.get("unrealized_pnl") or 0))
        if r.get("current_price"):
            a["current_price"] = r["current_price"]

    total = sum(a["current_value"] for a in agg.values()) or _ZERO
    out = []
    for a in agg.values():
        qty = a["quantity"]
        avg_cost = (a["cost_basis"] / qty) if qty else _ZERO
        weight = (a["current_value"] / total * 100) if total else _ZERO
        pnl_pct = ((a["current_value"] / a["cost_basis"] - 1) * 100) if a["cost_basis"] else _ZERO
        out.append({
            "symbol": a["symbol"], "asset_name": a["asset_name"], "sector": a["sector"],
            "asset_class": a["asset_class"], "quantity": qty, "avg_cost": avg_cost,
            "current_price": Decimal(str(a["current_price"])) if a["current_price"] else _ZERO,
            "current_value": a["current_value"], "unrealized_pnl": a["unrealized_pnl"],
            "pnl_pct": pnl_pct, "weight_pct": weight,
        })
    out.sort(key=lambda x: x["current_value"], reverse=True)
    return out


async def get_combined_holdings(db: AsyncSession, client_id: int) -> list[dict[str, Any]]:
    """Merged holdings across the client's live portfolios."""
    live = await _live_portfolio_ids(db, client_id)
    if not live:
        return []
    rows = list((await db.execute(
        select(Holding)
        .where(Holding.client_id == client_id)
        .where(Holding.portfolio_id.in_(live))
        .where(Holding.quantity > 0)
    )).scalars().all())
    merged = merge_holdings([
        {
            "symbol": h.symbol, "asset_name": h.asset_name, "sector": h.sector,
            "asset_class": h.asset_class, "quantity": h.quantity, "avg_cost": h.avg_cost,
            "current_price": h.current_price, "current_value": h.current_value,
            "unrealized_pnl": h.unrealized_pnl,
        }
        for h in rows
    ])
    return [
        {
            "symbol": m["symbol"], "asset_name": m["asset_name"], "sector": m["sector"],
            "asset_class": m["asset_class"], "quantity": _d2(m["quantity"]),
            "avg_cost": _d2(m["avg_cost"]), "current_price": _d2(m["current_price"]),
            "current_value": _d2(m["current_value"]), "unrealized_pnl": _d2(m["unrealized_pnl"]),
            "pnl_pct": _d2(m["pnl_pct"]), "weight_pct": _d2(m["weight_pct"]),
        }
        for m in merged
    ]
