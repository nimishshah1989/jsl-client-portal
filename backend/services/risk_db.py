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
    "avg_cash_held", "max_cash_held", "current_cash", "market_correlation",
    "monthly_hit_rate", "best_month", "worst_month",
    "avg_positive_month", "avg_negative_month", "risk_free_rate",
    # Period absolute returns — portfolio
    "return_1m", "return_3m", "return_6m", "return_1y",
    "return_2y", "return_3y", "return_4y", "return_5y", "return_inception",
    # Period absolute returns — benchmark
    "bench_return_1m", "bench_return_3m", "bench_return_6m",
    "bench_return_1y", "bench_return_2y", "bench_return_3y",
    "bench_return_4y", "bench_return_5y", "bench_return_inception",
    # Period CAGR — portfolio
    "cagr_1m", "cagr_3m", "cagr_6m", "cagr_1y", "cagr_2y", "cagr_3y",
    "cagr_4y", "cagr_5y", "cagr_inception",
    # Period CAGR — benchmark
    "bench_cagr_1m", "bench_cagr_3m", "bench_cagr_6m", "bench_cagr_1y",
    "bench_cagr_2y", "bench_cagr_3y", "bench_cagr_4y", "bench_cagr_5y",
    "bench_cagr_inception",
    # Period volatility — portfolio
    "vol_1m", "vol_3m", "vol_6m", "vol_1y", "vol_2y", "vol_3y",
    "vol_4y", "vol_5y", "vol_inception",
    # Period volatility — benchmark
    "bench_vol_1m", "bench_vol_3m", "bench_vol_6m", "bench_vol_1y",
    "bench_vol_2y", "bench_vol_3y", "bench_vol_4y", "bench_vol_5y",
    "bench_vol_inception",
    # Period max drawdown — portfolio
    "dd_1m", "dd_3m", "dd_6m", "dd_1y", "dd_2y", "dd_3y",
    "dd_4y", "dd_5y", "dd_inception",
    # Period max drawdown — benchmark
    "bench_dd_1m", "bench_dd_3m", "bench_dd_6m", "bench_dd_1y",
    "bench_dd_2y", "bench_dd_3y", "bench_dd_4y", "bench_dd_5y",
    "bench_dd_inception",
    # Period Sharpe — portfolio
    "sharpe_1m", "sharpe_3m", "sharpe_6m", "sharpe_1y", "sharpe_2y", "sharpe_3y",
    "sharpe_4y", "sharpe_5y", "sharpe_inception",
    # Period Sharpe — benchmark
    "bench_sharpe_1m", "bench_sharpe_3m", "bench_sharpe_6m", "bench_sharpe_1y",
    "bench_sharpe_2y", "bench_sharpe_3y", "bench_sharpe_4y", "bench_sharpe_5y",
    "bench_sharpe_inception",
    # Period Sortino — portfolio
    "sortino_1m", "sortino_3m", "sortino_6m", "sortino_1y", "sortino_2y", "sortino_3y",
    "sortino_4y", "sortino_5y", "sortino_inception",
    # Period Sortino — benchmark
    "bench_sortino_1m", "bench_sortino_3m", "bench_sortino_6m", "bench_sortino_1y",
    "bench_sortino_2y", "bench_sortino_3y", "bench_sortino_4y", "bench_sortino_5y",
    "bench_sortino_inception",
]

_ALL_EXTRA = [
    "max_dd_start", "max_dd_end", "max_dd_recovery",
    "max_consecutive_loss", "win_months", "loss_months",
]
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


def to_decimal(value: float, places: int = 4, max_abs: float = 99_999_999.0) -> Decimal:
    """Convert float to Decimal with specified precision for DB storage.

    Clamps extreme values to avoid PostgreSQL numeric overflow.
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return Decimal("0")
    # Clamp to avoid NUMERIC(12,4) overflow
    clamped = max(-max_abs, min(max_abs, float(value)))
    quantize_str = "0." + "0" * places
    return Decimal(str(clamped)).quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)


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
    row["win_months"] = metrics.get("win_months", 0)
    row["loss_months"] = metrics.get("loss_months", 0)

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
