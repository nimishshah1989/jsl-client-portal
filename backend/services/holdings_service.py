"""Holdings computation service — FIFO cost method (matches backoffice).

Aggregates all BUY/SELL/BONUS/CORPUS_IN transactions per symbol to compute
current holdings with average cost, unrealized P&L, and portfolio weights.

Cost method: FIFO (First-In, First-Out) using the NET RATE column.
This exactly matches the PMS backoffice computation.

  BUY / CORPUS_IN:  append a new lot (qty, price) to the symbol's lot queue
  SELL:             consume oldest lots first (FIFO); avg cost of remaining lots
                    = sum(qty_i × price_i) / total_qty
  BONUS:            append a zero-cost lot (qty, 0); dilutes avg cost naturally
"""

from __future__ import annotations

import logging
from collections import deque
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

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
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return _ZERO


def _fifo_avg_cost(lots: deque) -> Decimal:
    """Compute weighted average cost of remaining FIFO lots.

    Returns the weighted average of (qty × price) across all remaining lots.
    Returns zero if the lot queue is empty.
    """
    total_qty = _ZERO
    total_cost = _ZERO
    for lot_qty, lot_price in lots:
        total_qty += lot_qty
        total_cost += lot_qty * lot_price
    if total_qty <= _ZERO:
        return _ZERO
    return (total_cost / total_qty).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)


def compute_holdings(
    transactions_df: pd.DataFrame,
    current_prices: dict[str, Decimal] | None = None,
) -> pd.DataFrame:
    """
    Compute current holdings from transaction history using FIFO cost method.

    Uses NET RATE (the price column) to match the backoffice avg cost calculation.

    Args:
        transactions_df: DataFrame with columns:
            symbol, txn_type, quantity, price, amount, asset_class, date
            Must be sorted ascending by date.
            Optional column: isin (carried through to output if present)
        current_prices: Optional dict of {symbol: current_price} for P&L.
            If not provided, P&L fields will be zero.

    Returns:
        DataFrame with columns:
            symbol, isin, asset_class, quantity, avg_cost, current_price,
            current_value, unrealized_pnl, unrealized_pnl_pct, weight_pct
        Only symbols with quantity > 0 are returned.
    """
    if transactions_df.empty:
        return pd.DataFrame(columns=[
            "symbol", "isin", "asset_class", "quantity", "avg_cost",
            "current_price", "current_value", "unrealized_pnl",
            "unrealized_pnl_pct", "weight_pct",
        ])

    if current_prices is None:
        current_prices = {}

    has_isin_col = "isin" in transactions_df.columns

    # Per-symbol state
    lots: dict[str, deque] = {}          # symbol → deque of (qty, price) lots
    asset_classes: dict[str, str] = {}   # symbol → asset_class
    isins: dict[str, str] = {}           # symbol → most recently seen ISIN

    # Sort by date to process in chronological order
    sorted_df = (
        transactions_df.sort_values("date")
        if "date" in transactions_df.columns
        else transactions_df
    )

    for _, txn in sorted_df.iterrows():
        symbol = str(txn["symbol"]).strip()
        txn_type = str(txn["txn_type"]).strip().upper()
        qty = _dec(txn["quantity"])
        price = _dec(txn["price"])
        asset_class = str(txn.get("asset_class", "EQUITY")).strip()

        # Track ISIN — use the last non-empty ISIN seen for this symbol
        if has_isin_col:
            raw_isin = txn.get("isin", "")
            if raw_isin and str(raw_isin).strip() and str(raw_isin).strip().lower() not in ("nan", "none", ""):
                isins[symbol] = str(raw_isin).strip()

        if symbol not in lots:
            lots[symbol] = deque()
            asset_classes[symbol] = asset_class

        if txn_type in ("BUY", "CORPUS_IN"):
            # Add a new lot at the purchase price
            if qty > _ZERO:
                lots[symbol].append((qty, price))

        elif txn_type == "SELL":
            # Consume oldest lots first (FIFO)
            remaining = qty
            lot_queue = lots[symbol]
            while remaining > _ZERO and lot_queue:
                lot_qty, lot_price = lot_queue[0]
                if lot_qty <= remaining:
                    remaining -= lot_qty
                    lot_queue.popleft()
                else:
                    lot_queue[0] = (lot_qty - remaining, lot_price)
                    remaining = _ZERO
            if remaining > _ZERO:
                logger.warning(
                    "FIFO sell for %s: over-sold by %s — likely missing BUY transactions",
                    symbol,
                    remaining,
                )

        elif txn_type == "BONUS":
            # Bonus shares have zero cost — append a zero-price lot
            if qty > _ZERO:
                lots[symbol].append((qty, _ZERO))

        else:
            logger.debug("Unknown txn_type %r for symbol %s — skipping", txn_type, symbol)

        # Update asset class
        if asset_class and asset_class != "EQUITY":
            asset_classes[symbol] = asset_class

    # ── Build result rows ─────────────────────────────────────────────────────
    rows: list[dict] = []
    for symbol, lot_queue in lots.items():
        total_qty = sum(lq for lq, _ in lot_queue)
        if total_qty <= _ZERO:
            continue

        total_qty_dec = _dec(total_qty)
        avg_cost = _fifo_avg_cost(lot_queue)
        cur_price = _dec(current_prices.get(symbol, _ZERO))
        cur_value = (total_qty_dec * cur_price).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        cost_basis = (total_qty_dec * avg_cost).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        unrealized = cur_value - cost_basis
        pnl_pct = _ZERO
        if cost_basis > _ZERO:
            pnl_pct = ((cur_value / cost_basis - 1) * 100).quantize(
                _TWO_PLACES, rounding=ROUND_HALF_UP
            )

        rows.append({
            "symbol": symbol,
            "isin": isins.get(symbol, ""),
            "asset_class": asset_classes.get(symbol, "EQUITY"),
            "quantity": total_qty_dec,
            "avg_cost": avg_cost,
            "current_price": cur_price,
            "current_value": cur_value,
            "unrealized_pnl": unrealized,
            "unrealized_pnl_pct": pnl_pct,
            "weight_pct": _ZERO,  # computed below
        })

    if not rows:
        return pd.DataFrame(columns=[
            "symbol", "isin", "asset_class", "quantity", "avg_cost",
            "current_price", "current_value", "unrealized_pnl",
            "unrealized_pnl_pct", "weight_pct",
        ])

    result_df = pd.DataFrame(rows)

    # Compute weight_pct based on total portfolio value (non-zero current_value only)
    total_value = result_df["current_value"].sum()
    if total_value > 0:
        result_df["weight_pct"] = result_df["current_value"].apply(
            lambda v: (_dec(v) / _dec(total_value) * 100).quantize(
                _TWO_PLACES, rounding=ROUND_HALF_UP
            )
        )

    result_df = result_df.sort_values("weight_pct", ascending=False).reset_index(drop=True)

    logger.info(
        "FIFO holdings computed: %d active positions across %d symbols processed",
        len(result_df),
        len(lots),
    )
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
