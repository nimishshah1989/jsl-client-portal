"""
Reconciliation engine — compare backoffice Holding Report against our computed holdings.

Matches holdings by (client_code + symbol), computes diffs per field,
and categorizes each pair as MATCH / QTY_MISMATCH / COST_MISMATCH /
MISSING_IN_OURS / EXTRA_IN_OURS.

Usage:
    from backend.services.reconciliation_service import reconcile
    result = await reconcile(backoffice_holdings, db)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")

# Tolerance bands for "match" classification
_QTY_TOLERANCE = Decimal("0")       # Quantity must match exactly
_COST_TOLERANCE = Decimal("0.02")   # ±₹0.02 per-share (rounding)
_VALUE_TOLERANCE = Decimal("1.00")  # ±₹1 on market value (rounding)


@dataclass
class HoldingMatch:
    """Result of comparing one (client, symbol) pair."""

    client_code: str
    symbol: str
    status: str  # MATCH | QTY_MISMATCH | COST_MISMATCH | VALUE_MISMATCH | MISSING_IN_OURS | EXTRA_IN_OURS

    # Backoffice values (None when EXTRA_IN_OURS)
    bo_quantity: Decimal | None = None
    bo_avg_cost: Decimal | None = None
    bo_total_cost: Decimal | None = None
    bo_market_price: Decimal | None = None
    bo_market_value: Decimal | None = None
    bo_pnl: Decimal | None = None
    bo_weight_pct: Decimal | None = None
    bo_isin: str | None = None

    # Our computed values (None when MISSING_IN_OURS)
    our_quantity: Decimal | None = None
    our_avg_cost: Decimal | None = None
    our_total_cost: Decimal | None = None
    our_market_price: Decimal | None = None
    our_market_value: Decimal | None = None
    our_pnl: Decimal | None = None
    our_weight_pct: Decimal | None = None

    # Diffs (only for matched symbols)
    qty_diff: Decimal | None = None
    cost_diff: Decimal | None = None
    value_diff: Decimal | None = None
    pnl_diff: Decimal | None = None

    family_group: str = ""


@dataclass
class ClientReconciliation:
    """Reconciliation result for a single client."""

    client_code: str
    family_group: str
    matches: list[HoldingMatch] = field(default_factory=list)
    total_holdings_bo: int = 0
    total_holdings_ours: int = 0
    matched_count: int = 0
    qty_mismatch_count: int = 0
    cost_mismatch_count: int = 0
    value_mismatch_count: int = 0
    missing_in_ours_count: int = 0
    extra_in_ours_count: int = 0
    client_found: bool = True

    @property
    def match_pct(self) -> float:
        total = self.total_holdings_bo + self.extra_in_ours_count
        if total == 0:
            return 100.0
        return round(self.matched_count / total * 100, 1)

    @property
    def has_issues(self) -> bool:
        return (
            self.qty_mismatch_count > 0
            or self.cost_mismatch_count > 0
            or self.missing_in_ours_count > 0
            or self.extra_in_ours_count > 0
        )


@dataclass
class ReconciliationSummary:
    """Top-level summary across all clients."""

    total_clients_bo: int = 0
    total_clients_matched: int = 0
    total_clients_missing: int = 0
    total_holdings_bo: int = 0
    total_holdings_matched: int = 0
    total_qty_mismatches: int = 0
    total_cost_mismatches: int = 0
    total_value_mismatches: int = 0
    total_missing_in_ours: int = 0
    total_extra_in_ours: int = 0
    clients: list[ClientReconciliation] = field(default_factory=list)

    @property
    def match_pct(self) -> float:
        total = self.total_holdings_bo + self.total_extra_in_ours
        if total == 0:
            return 100.0
        return round(self.total_holdings_matched / total * 100, 1)


def _safe_dec(val: object) -> Decimal:
    """Convert to Decimal, defaulting to zero."""
    if val is None:
        return _ZERO
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return _ZERO


def _classify(
    bo: dict,
    our_qty: Decimal,
    our_avg_cost: Decimal,
    our_market_price: Decimal,
    our_market_value: Decimal,
    our_pnl: Decimal,
) -> str:
    """Classify a matched holding pair."""
    bo_qty = _safe_dec(bo["quantity"])
    bo_cost = _safe_dec(bo["avg_cost"])

    qty_diff = abs(bo_qty - our_qty)
    cost_diff = abs(bo_cost - our_avg_cost)
    value_diff = abs(_safe_dec(bo["market_value"]) - our_market_value)

    if qty_diff > _QTY_TOLERANCE:
        return "QTY_MISMATCH"
    if cost_diff > _COST_TOLERANCE:
        return "COST_MISMATCH"
    if value_diff > _VALUE_TOLERANCE:
        return "VALUE_MISMATCH"
    return "MATCH"


async def _load_our_holdings(db: AsyncSession) -> dict[str, dict[str, dict]]:
    """
    Load all holdings from cpp_holdings, keyed by (client_code, symbol).

    Returns:
        {client_code: {symbol: {quantity, avg_cost, current_price, current_value, ...}}}
    """
    result = await db.execute(text("""
        SELECT
            c.client_code,
            h.symbol,
            h.quantity,
            h.avg_cost,
            h.current_price,
            h.current_value,
            h.unrealized_pnl,
            h.weight_pct
        FROM cpp_holdings h
        JOIN cpp_clients c ON c.id = h.client_id
        WHERE h.quantity > 0
        ORDER BY c.client_code, h.symbol
    """))

    holdings: dict[str, dict[str, dict]] = {}
    for row in result.fetchall():
        code = row[0]
        symbol = row[1]
        if code not in holdings:
            holdings[code] = {}
        holdings[code][symbol] = {
            "quantity": _safe_dec(row[2]),
            "avg_cost": _safe_dec(row[3]),
            "current_price": _safe_dec(row[4]),
            "current_value": _safe_dec(row[5]),
            "unrealized_pnl": _safe_dec(row[6]),
            "weight_pct": _safe_dec(row[7]),
        }

    logger.info("Loaded our holdings: %d clients, %d total positions",
                len(holdings), sum(len(v) for v in holdings.values()))
    return holdings


async def reconcile(
    backoffice_holdings: list[dict],
    db: AsyncSession,
) -> ReconciliationSummary:
    """
    Run full reconciliation between backoffice holding report and our DB.

    Args:
        backoffice_holdings: Output of parse_holding_report().
        db: Async database session.

    Returns:
        ReconciliationSummary with per-client details.
    """
    # Load our holdings from DB
    our_holdings = await _load_our_holdings(db)

    # Group backoffice by client
    bo_by_client: dict[str, list[dict]] = {}
    for h in backoffice_holdings:
        ucc = h["ucc"]
        if ucc not in bo_by_client:
            bo_by_client[ucc] = []
        bo_by_client[ucc].append(h)

    summary = ReconciliationSummary(
        total_clients_bo=len(bo_by_client),
        total_holdings_bo=len(backoffice_holdings),
    )

    # Track which of our client codes were seen (to find extras)
    seen_client_codes: set[str] = set()

    for ucc, bo_holdings in sorted(bo_by_client.items()):
        family_group = bo_holdings[0].get("family_group", "")
        client_recon = ClientReconciliation(
            client_code=ucc,
            family_group=family_group,
            total_holdings_bo=len(bo_holdings),
        )

        our_client_holdings = our_holdings.get(ucc, {})
        if our_client_holdings:
            seen_client_codes.add(ucc)
            client_recon.total_holdings_ours = len(our_client_holdings)
        else:
            client_recon.client_found = False

        our_symbols_seen: set[str] = set()

        for bo in bo_holdings:
            symbol = bo["symbol"]
            our = our_client_holdings.get(symbol)

            if our is None:
                # Backoffice has it, we don't
                match = HoldingMatch(
                    client_code=ucc,
                    symbol=symbol,
                    status="MISSING_IN_OURS",
                    bo_quantity=_safe_dec(bo["quantity"]),
                    bo_avg_cost=_safe_dec(bo["avg_cost"]),
                    bo_total_cost=_safe_dec(bo["total_cost"]),
                    bo_market_price=_safe_dec(bo["market_price"]),
                    bo_market_value=_safe_dec(bo["market_value"]),
                    bo_pnl=_safe_dec(bo["notional_pnl"]),
                    bo_weight_pct=_safe_dec(bo["holding_market_pct"]),
                    bo_isin=bo.get("isin", ""),
                    family_group=family_group,
                )
                client_recon.missing_in_ours_count += 1
            else:
                our_symbols_seen.add(symbol)
                our_qty = our["quantity"]
                our_avg = our["avg_cost"]
                our_price = our["current_price"]
                our_value = our["current_value"]
                our_pnl = our["unrealized_pnl"]
                our_weight = our["weight_pct"]

                status = _classify(bo, our_qty, our_avg, our_price, our_value, our_pnl)

                bo_qty = _safe_dec(bo["quantity"])
                bo_cost = _safe_dec(bo["avg_cost"])
                bo_value = _safe_dec(bo["market_value"])
                bo_pnl_val = _safe_dec(bo["notional_pnl"])

                match = HoldingMatch(
                    client_code=ucc,
                    symbol=symbol,
                    status=status,
                    bo_quantity=bo_qty,
                    bo_avg_cost=bo_cost,
                    bo_total_cost=_safe_dec(bo["total_cost"]),
                    bo_market_price=_safe_dec(bo["market_price"]),
                    bo_market_value=bo_value,
                    bo_pnl=bo_pnl_val,
                    bo_weight_pct=_safe_dec(bo["holding_market_pct"]),
                    bo_isin=bo.get("isin", ""),
                    our_quantity=our_qty,
                    our_avg_cost=our_avg,
                    our_total_cost=(our_qty * our_avg),
                    our_market_price=our_price,
                    our_market_value=our_value,
                    our_pnl=our_pnl,
                    our_weight_pct=our_weight,
                    qty_diff=(bo_qty - our_qty),
                    cost_diff=(bo_cost - our_avg),
                    value_diff=(bo_value - our_value),
                    pnl_diff=(bo_pnl_val - our_pnl),
                    family_group=family_group,
                )

                if status == "MATCH":
                    client_recon.matched_count += 1
                elif status == "QTY_MISMATCH":
                    client_recon.qty_mismatch_count += 1
                elif status == "COST_MISMATCH":
                    client_recon.cost_mismatch_count += 1
                elif status == "VALUE_MISMATCH":
                    client_recon.value_mismatch_count += 1

            client_recon.matches.append(match)

        # Check for symbols we have that backoffice doesn't
        for symbol, our in our_client_holdings.items():
            if symbol not in our_symbols_seen:
                match = HoldingMatch(
                    client_code=ucc,
                    symbol=symbol,
                    status="EXTRA_IN_OURS",
                    our_quantity=our["quantity"],
                    our_avg_cost=our["avg_cost"],
                    our_total_cost=(our["quantity"] * our["avg_cost"]),
                    our_market_price=our["current_price"],
                    our_market_value=our["current_value"],
                    our_pnl=our["unrealized_pnl"],
                    our_weight_pct=our["weight_pct"],
                    family_group=family_group,
                )
                client_recon.extra_in_ours_count += 1
                client_recon.matches.append(match)

        summary.clients.append(client_recon)
        summary.total_holdings_matched += client_recon.matched_count
        summary.total_qty_mismatches += client_recon.qty_mismatch_count
        summary.total_cost_mismatches += client_recon.cost_mismatch_count
        summary.total_value_mismatches += client_recon.value_mismatch_count
        summary.total_missing_in_ours += client_recon.missing_in_ours_count
        summary.total_extra_in_ours += client_recon.extra_in_ours_count

    summary.total_clients_matched = sum(1 for c in summary.clients if c.client_found)
    summary.total_clients_missing = summary.total_clients_bo - summary.total_clients_matched

    logger.info(
        "Reconciliation complete: %d/%d clients matched, %d/%d holdings matched, "
        "%d qty mismatches, %d cost mismatches, %d missing, %d extra",
        summary.total_clients_matched, summary.total_clients_bo,
        summary.total_holdings_matched, summary.total_holdings_bo,
        summary.total_qty_mismatches, summary.total_cost_mismatches,
        summary.total_missing_in_ours, summary.total_extra_in_ours,
    )

    return summary
