"""
Holdings computation service — Weighted Average Cost Method.

Aggregates all BUY/SELL/BONUS/CORPUS_IN transactions per symbol to compute
current holdings with average cost, unrealized P&L, and portfolio weights.

Cost method:
  BUY:       new_avg = (old_qty * old_avg + buy_qty * buy_price) / (old_qty + buy_qty)
  SELL:      avg_cost unchanged, reduce quantity
  BONUS:     new_avg = (old_qty * old_avg) / (old_qty + bonus_qty)
  CORPUS_IN: treated as initial position — same as BUY logic
"""

import logging
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_FOUR_PLACES = Decimal("0.0001")
_TWO_PLACES = Decimal("0.01")


def _dec(value: object) -> Decimal:
    """Convert a value to Decimal safely."""
    if value is None:
        return _ZERO
    try:
        d = Decimal(str(value))
        if d.is_nan() or d.is_infinite():
            return _ZERO
        return d
    except Exception:
        return _ZERO


def compute_holdings(
    transactions_df: pd.DataFrame,
    current_prices: dict[str, Decimal] | None = None,
) -> pd.DataFrame:
    """
    Compute current holdings from transaction history using Weighted Average Cost.

    Args:
        transactions_df: DataFrame with columns:
            symbol, txn_type, quantity, price, amount, asset_class, date
            Must be sorted ascending by date.
        current_prices: Optional dict of {symbol: current_price} for P&L computation.
            If not provided, P&L fields will be zero.

    Returns:
        DataFrame with columns:
            symbol, asset_class, quantity, avg_cost, current_price,
            current_value, unrealized_pnl, unrealized_pnl_pct, weight_pct
        Only symbols with quantity > 0 are returned.
    """
    if transactions_df.empty:
        return pd.DataFrame(columns=[
            "symbol", "asset_class", "quantity", "avg_cost", "current_price",
            "current_value", "unrealized_pnl", "unrealized_pnl_pct", "weight_pct",
        ])

    if current_prices is None:
        current_prices = {}

    # Track positions per symbol
    positions: dict[str, dict] = {}

    # Sort by date to process in chronological order
    sorted_df = transactions_df.sort_values("date") if "date" in transactions_df.columns else transactions_df

    for _, txn in sorted_df.iterrows():
        symbol = str(txn["symbol"]).strip()
        txn_type = str(txn["txn_type"]).strip().upper()
        qty = _dec(txn["quantity"])
        price = _dec(txn["price"])
        asset_class = str(txn.get("asset_class", "EQUITY")).strip()

        if symbol not in positions:
            positions[symbol] = {
                "quantity": _ZERO,
                "avg_cost": _ZERO,
                "asset_class": asset_class,
            }

        pos = positions[symbol]

        if txn_type in ("BUY", "CORPUS_IN"):
            # Weighted average cost: (old_qty * old_avg + new_qty * new_price) / total_qty
            old_qty = pos["quantity"]
            old_avg = pos["avg_cost"]
            new_total_qty = old_qty + qty
            if new_total_qty > 0:
                pos["avg_cost"] = (
                    (old_qty * old_avg + qty * price) / new_total_qty
                ).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)
            pos["quantity"] = new_total_qty

        elif txn_type == "SELL":
            # Avg cost unchanged, reduce quantity
            pos["quantity"] = max(pos["quantity"] - qty, _ZERO)

        elif txn_type == "BONUS":
            # Bonus shares: zero cost, dilutes average
            old_qty = pos["quantity"]
            old_avg = pos["avg_cost"]
            new_total_qty = old_qty + qty
            if new_total_qty > 0:
                # new_avg = (old_qty * old_avg) / (old_qty + bonus_qty)
                pos["avg_cost"] = (
                    (old_qty * old_avg) / new_total_qty
                ).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)
            pos["quantity"] = new_total_qty

        else:
            logger.debug("Unknown txn_type %r for symbol %s — skipping", txn_type, symbol)

        # Update asset class if not set
        if not pos["asset_class"] or pos["asset_class"] == "EQUITY":
            pos["asset_class"] = asset_class

    # Build result — only symbols with positive quantity
    rows: list[dict] = []
    for symbol, pos in positions.items():
        if pos["quantity"] <= 0:
            continue

        cur_price = _dec(current_prices.get(symbol, _ZERO))
        cur_value = (pos["quantity"] * cur_price).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        cost_basis = (pos["quantity"] * pos["avg_cost"]).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        unrealized = cur_value - cost_basis
        pnl_pct = _ZERO
        if cost_basis > 0:
            pnl_pct = ((cur_value / cost_basis - 1) * 100).quantize(
                _TWO_PLACES, rounding=ROUND_HALF_UP
            )

        rows.append({
            "symbol": symbol,
            "asset_class": pos["asset_class"],
            "quantity": pos["quantity"],
            "avg_cost": pos["avg_cost"],
            "current_price": cur_price,
            "current_value": cur_value,
            "unrealized_pnl": unrealized,
            "unrealized_pnl_pct": pnl_pct,
            "weight_pct": _ZERO,  # Computed below after total is known
        })

    if not rows:
        return pd.DataFrame(columns=[
            "symbol", "asset_class", "quantity", "avg_cost", "current_price",
            "current_value", "unrealized_pnl", "unrealized_pnl_pct", "weight_pct",
        ])

    result_df = pd.DataFrame(rows)

    # Compute weight_pct based on total portfolio value
    total_value = sum(r["current_value"] for r in rows)
    if total_value > 0:
        result_df["weight_pct"] = result_df["current_value"].apply(
            lambda v: (v / total_value * 100).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        )

    # Sort by weight descending
    result_df = result_df.sort_values("weight_pct", ascending=False).reset_index(drop=True)

    logger.info("Holdings computed: %d active positions", len(result_df))
    return result_df


def compute_allocation(holdings_df: pd.DataFrame) -> dict:
    """
    Compute allocation breakdowns from holdings.

    Returns dict with:
        by_class:  list of {class, value, weight_pct}
        by_sector: list of {sector, value, weight_pct}
    """
    if holdings_df.empty:
        return {"by_class": [], "by_sector": []}

    # By asset class
    class_groups = holdings_df.groupby("asset_class").agg(
        value=("current_value", "sum"),
        weight_pct=("weight_pct", "sum"),
    ).reset_index()
    by_class = [
        {
            "class": row["asset_class"],
            "value": row["value"],
            "weight_pct": row["weight_pct"],
        }
        for _, row in class_groups.iterrows()
    ]

    # By sector (if sector column exists and has data)
    by_sector: list[dict] = []
    if "sector" in holdings_df.columns and holdings_df["sector"].notna().any():
        sector_groups = holdings_df[holdings_df["sector"].notna()].groupby("sector").agg(
            value=("current_value", "sum"),
            weight_pct=("weight_pct", "sum"),
        ).reset_index()
        by_sector = [
            {
                "sector": row["sector"],
                "value": row["value"],
                "weight_pct": row["weight_pct"],
            }
            for _, row in sector_groups.iterrows()
        ]

    return {"by_class": by_class, "by_sector": by_sector}
