"""Aggregate allocation and monthly returns — extracted from aggregate_service.py.

These functions compute firm-wide allocation breakdowns and monthly return
heatmaps using the shared composite index from aggregate_service.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.aggregate_service import _get_cached_composite


async def get_aggregate_allocation(db: AsyncSession) -> dict[str, Any]:
    """Sector allocation across all active non-admin client holdings.

    Groups by symbol for ETFs (shows actual ETF names like NIFTYBEES),
    by sector for stocks, and lumps small sectors (<2%) into Others.
    """
    result = await db.execute(text("""
        SELECT
            h.symbol,
            COALESCE(h.sector, 'Other') AS sector,
            SUM(h.current_value)        AS total_value
        FROM cpp_holdings h
        JOIN cpp_clients c ON c.id = h.client_id
        WHERE c.is_active = true AND c.is_admin = false
          AND h.quantity > 0
          AND h.current_value > 0
        GROUP BY h.symbol, COALESCE(h.sector, 'Other')
        ORDER BY total_value DESC
    """))
    rows = result.fetchall()
    total = sum(float(r.total_value) for r in rows) if rows else 0.0

    # ETF symbols get their own name; stocks group by sector
    ETF_NAMES = {
        "NIFTYBEES": "Nifty 50 ETF",
        "JUNIORBEES": "Nifty Next 50 ETF",
        "GOLDBEES": "Gold ETF",
        "SILVERBEES": "Silver ETF",
        "PHARMABEES": "Pharma ETF",
        "FMCGIETF": "FMCG ETF",
        "HNGSNGBEES": "Hang Seng ETF",
        "CPSEETF": "CPSE ETF",
        "PSUBNKBEES": "PSU Bank ETF",
        "BANKBEES": "Bank ETF",
        "LIQUIDBEES": "Cash (LIQUIDBEES)",
        "LIQUIDETF": "Cash (LIQUIDETF)",
        "LIQUIDCASE": "Cash (Ledger)",
    }

    sector_totals: dict[str, float] = {}
    for r in rows:
        sym = r.symbol.strip().upper() if r.symbol else ""
        sector = r.sector
        val = float(r.total_value)

        # ETFs get their own category
        if sym in ETF_NAMES:
            label = ETF_NAMES[sym]
        elif sector in ("Cash",):
            label = "Cash"
        elif sector in ("Other", "Unclassified"):
            label = "Other Stocks"
        else:
            label = sector

        sector_totals[label] = sector_totals.get(label, 0.0) + val

    # Sort by value, group small ones into Others
    sorted_sectors = sorted(sector_totals.items(), key=lambda x: x[1], reverse=True)
    main_sectors = []
    others_val = 0.0
    for name, val in sorted_sectors:
        pct = val / total * 100 if total > 0 else 0
        if pct >= 1.5:
            main_sectors.append({
                "name": name,
                "value": _r2(val),
                "current_value": round(val, 0),
                "weight_pct": _r2(pct),
            })
        else:
            others_val += val

    if others_val > 0:
        main_sectors.append({
            "name": "Others",
            "value": _r2(others_val),
            "current_value": round(others_val, 0),
            "weight_pct": _r2(others_val / total * 100 if total > 0 else 0),
        })

    return {"by_sector": main_sectors, "total_value": round(total, 0)}


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
    negative = rets[rets < 0]

    is_loss = (rets < 0).astype(int)
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


def _empty_monthly_stats() -> dict[str, Any]:
    return {
        "hit_rate": 0.0, "best_month": 0.0, "worst_month": 0.0,
        "avg_positive_month": 0.0, "avg_negative_month": 0.0,
        "max_consecutive_loss": 0, "win_count": 0, "loss_count": 0,
    }
