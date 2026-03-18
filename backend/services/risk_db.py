"""
Database persistence for risk engine results.

Handles upsert of computed risk metrics and drawdown series into
cpp_risk_metrics and cpp_drawdown_series tables.

Separated from risk_engine.py to keep files under 400 lines.
"""

import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# All decimal fields in cpp_risk_metrics that come from compute_all_metrics
DECIMAL_FIELDS = [
    "absolute_return", "cagr", "xirr", "volatility", "sharpe_ratio",
    "sortino_ratio", "max_drawdown", "alpha", "beta", "information_ratio",
    "tracking_error", "up_capture", "down_capture", "ulcer_index",
    "avg_cash_held", "max_cash_held", "market_correlation",
    "monthly_hit_rate", "best_month", "worst_month",
    "avg_positive_month", "avg_negative_month", "risk_free_rate",
    "return_1m", "return_3m", "return_6m", "return_1y",
    "return_2y", "return_3y", "return_5y", "return_inception",
    "bench_return_1m", "bench_return_3m", "bench_return_6m",
    "bench_return_1y", "bench_return_2y", "bench_return_3y",
    "bench_return_5y", "bench_return_inception",
    "bench_volatility", "bench_max_drawdown", "bench_sharpe", "bench_sortino",
]

_ALL_EXTRA = ["max_dd_start", "max_dd_end", "max_dd_recovery", "max_consecutive_loss"]
_ALL_COLS = DECIMAL_FIELDS + _ALL_EXTRA

# Build SQL fragments once at import time
_COL_LIST = ", ".join(_ALL_COLS)
_PARAM_LIST = ", ".join(f":{f}" for f in _ALL_COLS)
_UPDATE_SET = ", ".join(f"{f} = EXCLUDED.{f}" for f in _ALL_COLS)

_UPSERT_SQL = (
    f"INSERT INTO cpp_risk_metrics (client_id, portfolio_id, computed_date, {_COL_LIST}) "
    f"VALUES (:client_id, :portfolio_id, :computed_date, {_PARAM_LIST}) "
    f"ON CONFLICT (client_id, portfolio_id, computed_date) DO UPDATE SET {_UPDATE_SET}"
)


def to_decimal(value: float, places: int = 4) -> Decimal:
    """Convert float to Decimal with specified precision for DB storage."""
    if value is None:
        return Decimal("0")
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return Decimal("0")
    quantize_str = "0." + "0" * places
    return Decimal(str(value)).quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)


def to_date(value: object) -> date | None:
    """Convert pandas Timestamp or datetime to date, or None."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if hasattr(value, "date") and callable(getattr(value, "date")):
        return value.date()
    return None


async def upsert_risk_metrics(
    db: AsyncSession,
    client_id: int,
    portfolio_id: int,
    computed_date: date,
    metrics: dict,
) -> None:
    """Upsert a single row of computed metrics into cpp_risk_metrics."""
    row: dict = {
        "client_id": client_id,
        "portfolio_id": portfolio_id,
        "computed_date": computed_date,
    }
    for field in DECIMAL_FIELDS:
        row[field] = to_decimal(metrics.get(field, 0.0))

    row["max_dd_start"] = to_date(metrics.get("max_dd_start"))
    row["max_dd_end"] = to_date(metrics.get("max_dd_end"))
    row["max_dd_recovery"] = to_date(metrics.get("max_dd_recovery"))
    row["max_consecutive_loss"] = metrics.get("max_consecutive_loss", 0)

    await db.execute(text(_UPSERT_SQL), row)
    logger.debug("Upserted risk metrics for client=%d portfolio=%d", client_id, portfolio_id)


async def replace_drawdown_series(
    db: AsyncSession,
    client_id: int,
    portfolio_id: int,
    dd_df: pd.DataFrame,
) -> int:
    """Delete old drawdown rows and insert new series. Returns row count."""
    await db.execute(
        text("DELETE FROM cpp_drawdown_series WHERE client_id = :cid AND portfolio_id = :pid"),
        {"cid": client_id, "pid": portfolio_id},
    )

    if dd_df.empty:
        return 0

    dd_rows: list[dict] = []
    for _, row in dd_df.iterrows():
        dd_rows.append({
            "client_id": client_id,
            "portfolio_id": portfolio_id,
            "dd_date": to_date(row["dd_date"]),
            "drawdown_pct": to_decimal(float(row["drawdown_pct"]), 6),
            "peak_nav": to_decimal(float(row["peak_nav"]), 6),
            "current_nav": to_decimal(float(row["current_nav"]), 6),
            "bench_drawdown": to_decimal(float(row["bench_drawdown"]), 6),
        })

    # Batch insert (500 rows per batch to avoid query size limits)
    batch_size = 500
    for start in range(0, len(dd_rows), batch_size):
        batch = dd_rows[start : start + batch_size]
        params: dict = {}
        placeholders: list[str] = []
        for i, dr in enumerate(batch):
            p = f"_{start + i}"
            placeholders.append(
                f"(:cid{p}, :pid{p}, :dd{p}, :dpct{p}, :pnav{p}, :cnav{p}, :bdd{p})"
            )
            params[f"cid{p}"] = dr["client_id"]
            params[f"pid{p}"] = dr["portfolio_id"]
            params[f"dd{p}"] = dr["dd_date"]
            params[f"dpct{p}"] = dr["drawdown_pct"]
            params[f"pnav{p}"] = dr["peak_nav"]
            params[f"cnav{p}"] = dr["current_nav"]
            params[f"bdd{p}"] = dr["bench_drawdown"]

        sql = (
            "INSERT INTO cpp_drawdown_series "
            "(client_id, portfolio_id, dd_date, drawdown_pct, peak_nav, "
            "current_nav, bench_drawdown) VALUES " + ", ".join(placeholders)
        )
        await db.execute(text(sql), params)

    logger.debug(
        "Inserted %d drawdown rows for client=%d portfolio=%d",
        len(dd_rows), client_id, portfolio_id,
    )
    return len(dd_rows)
