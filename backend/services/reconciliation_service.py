"""
Reconciliation engine — 3-way comparison of holdings data.

Compares three independent data sources per client:
  1. NAV file (cpp_nav_series) — total portfolio value
  2. Backoffice Holding Report (.xlsx) — per-holding breakdown
  3. Transaction-derived holdings (cpp_holdings) — our computed positions

Per-holding comparison uses the BO market price on both sides so that
value_diff isolates qty/cost differences, not price-feed artifacts.

Usage:
    from backend.services.reconciliation_service import reconcile
    result = await reconcile(backoffice_holdings, db)
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.reconciliation_commentary import generate_commentary

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")

# Tolerance bands for "match" classification
_QTY_TOLERANCE = Decimal("0")       # Quantity must match exactly
_COST_TOLERANCE = Decimal("0.02")   # ±₹0.02 per-share (rounding)

# Symbols to exclude from "extra in ours" — these are tracked in separate
# backoffice systems (MF/ETF platforms) and are not in the Holding Report.
_EXCLUDE_FROM_EXTRA = {
    "Mirae", "MIRAESMALLCAP", "Amara", "Mankind", "Samvardhana",
    "Jupiter", "Data", "Computer",  # Multi-word symbols from old parser
}


@dataclass
class HoldingMatch:
    """Result of comparing one (client, symbol) pair."""

    client_code: str
    symbol: str
    status: str  # MATCH | QTY_MISMATCH | COST_MISMATCH | MISSING_IN_OURS | EXTRA_IN_OURS

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
    family_group: str = ""
    client_name: str = ""
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

    # 3-way value totals
    nav_total: Decimal | None = None          # Source 1: latest NAV (total portfolio value)
    bo_holdings_total: Decimal = _ZERO         # Source 2: SUM(bo_market_value)
    our_holdings_total: Decimal = _ZERO        # Source 3: SUM(our_qty * bo_price)
    nav_vs_bo_diff: Decimal | None = None      # NAV - BO holdings total
    bo_vs_ours_diff: Decimal = _ZERO           # BO - Ours (position mismatch impact)
    nav_date: dt.date | None = None            # Date of NAV snapshot

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

    @property
    def is_fully_matched(self) -> bool:
        return not self.has_issues


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
    commentary: list[dict] = field(default_factory=list)

    # 3-way aggregate totals
    total_nav_value: Decimal = _ZERO
    total_bo_holdings_value: Decimal = _ZERO
    total_our_holdings_value: Decimal = _ZERO
    total_nav_vs_bo_diff: Decimal = _ZERO
    total_bo_vs_ours_diff: Decimal = _ZERO
    clients_with_nav: int = 0

    @property
    def match_pct(self) -> float:
        total = self.total_holdings_bo + self.total_extra_in_ours
        if total == 0:
            return 100.0
        return round(self.total_holdings_matched / total * 100, 1)

    @property
    def client_match_pct(self) -> float:
        if not self.clients:
            return 100.0
        fully_clean = sum(1 for c in self.clients if c.is_fully_matched)
        return round(fully_clean / len(self.clients) * 100, 1)

    @property
    def clients_fully_matched(self) -> int:
        return sum(1 for c in self.clients if c.is_fully_matched)


def _safe_dec(val: object) -> Decimal:
    """Convert to Decimal, defaulting to zero."""
    if val is None:
        return _ZERO
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return _ZERO


def _classify(bo: dict, our_qty: Decimal, our_avg_cost: Decimal) -> str:
    """Classify a matched holding pair by qty and cost only."""
    bo_qty = _safe_dec(bo["quantity"])
    bo_cost = _safe_dec(bo["avg_cost"])

    if abs(bo_qty - our_qty) > _QTY_TOLERANCE:
        return "QTY_MISMATCH"
    if abs(bo_cost - our_avg_cost) > _COST_TOLERANCE:
        return "COST_MISMATCH"
    return "MATCH"


async def _load_our_holdings(db: AsyncSession) -> tuple[dict[str, dict[str, dict]], dict[str, str]]:
    """Load all holdings from cpp_holdings, keyed by (client_code, symbol)."""
    result = await db.execute(text("""
        SELECT
            c.client_code, c.name, h.symbol, h.quantity,
            h.avg_cost, h.current_price, h.current_value,
            h.unrealized_pnl, h.weight_pct
        FROM cpp_holdings h
        JOIN cpp_clients c ON c.id = h.client_id
        WHERE h.quantity > 0
        ORDER BY c.client_code, h.symbol
    """))

    holdings: dict[str, dict[str, dict]] = {}
    client_names: dict[str, str] = {}
    for row in result.fetchall():
        code, name, symbol = row[0], row[1] or "", row[2]
        if code not in holdings:
            holdings[code] = {}
            client_names[code] = name
        holdings[code][symbol] = {
            "quantity": _safe_dec(row[3]),
            "avg_cost": _safe_dec(row[4]),
            "current_price": _safe_dec(row[5]),
            "current_value": _safe_dec(row[6]),
            "unrealized_pnl": _safe_dec(row[7]),
            "weight_pct": _safe_dec(row[8]),
        }

    logger.info("Loaded our holdings: %d clients, %d total positions",
                len(holdings), sum(len(v) for v in holdings.values()))
    return holdings, client_names


async def _load_latest_navs(db: AsyncSession) -> dict[str, dict]:
    """Load latest NAV per client from cpp_nav_series, keyed by client_code."""
    result = await db.execute(text("""
        SELECT DISTINCT ON (n.client_id)
            c.client_code,
            n.nav_value,
            n.invested_amount,
            COALESCE(n.etf_value, 0) AS etf_value,
            COALESCE(n.cash_value, 0) AS cash_value,
            COALESCE(n.bank_balance, 0) AS bank_balance,
            n.nav_date
        FROM cpp_nav_series n
        JOIN cpp_clients c ON c.id = n.client_id
        WHERE c.is_active = true
        ORDER BY n.client_id, n.nav_date DESC
    """))

    navs: dict[str, dict] = {}
    for row in result.fetchall():
        navs[row[0]] = {
            "nav_value": _safe_dec(row[1]),
            "invested_amount": _safe_dec(row[2]),
            "etf_value": _safe_dec(row[3]),
            "cash_value": _safe_dec(row[4]),
            "bank_balance": _safe_dec(row[5]),
            "nav_date": row[6],
        }

    logger.info("Loaded latest NAVs for %d clients", len(navs))
    return navs


async def reconcile(
    backoffice_holdings: list[dict],
    db: AsyncSession,
) -> ReconciliationSummary:
    """Run full 3-way reconciliation: NAV vs BO Holding Report vs our holdings."""
    our_holdings, client_names = await _load_our_holdings(db)
    latest_navs = await _load_latest_navs(db)

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

    seen_client_codes: set[str] = set()

    for ucc, bo_holdings in sorted(bo_by_client.items()):
        family_group = bo_holdings[0].get("family_group", "")
        client_recon = ClientReconciliation(
            client_code=ucc,
            family_group=family_group,
            client_name=client_names.get(ucc, ""),
            total_holdings_bo=len(bo_holdings),
        )

        our_client_holdings = our_holdings.get(ucc, {})
        if our_client_holdings:
            seen_client_codes.add(ucc)
            client_recon.total_holdings_ours = len(our_client_holdings)
        else:
            client_recon.client_found = False

        our_symbols_seen: set[str] = set()
        bo_total = _ZERO
        our_total_at_bo_price = _ZERO

        for bo in bo_holdings:
            symbol = bo["symbol"]
            our = our_client_holdings.get(symbol)
            bo_price = _safe_dec(bo["market_price"])
            bo_value = _safe_dec(bo["market_value"])
            bo_total += bo_value

            if our is None:
                match = HoldingMatch(
                    client_code=ucc, symbol=symbol, status="MISSING_IN_OURS",
                    bo_quantity=_safe_dec(bo["quantity"]),
                    bo_avg_cost=_safe_dec(bo["avg_cost"]),
                    bo_total_cost=_safe_dec(bo["total_cost"]),
                    bo_market_price=bo_price,
                    bo_market_value=bo_value,
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

                bo_qty = _safe_dec(bo["quantity"])
                bo_cost = _safe_dec(bo["avg_cost"])
                bo_pnl_val = _safe_dec(bo["notional_pnl"])

                # Use BO market price for our value — apples-to-apples comparison
                # so value_diff reflects qty differences only, not price feeds
                our_value_at_bo_price = our_qty * bo_price
                our_total_at_bo_price += our_value_at_bo_price

                our_cost_basis = our_qty * our_avg
                our_pnl_at_bo_price = our_value_at_bo_price - our_cost_basis

                status = _classify(bo, our_qty, our_avg)

                match = HoldingMatch(
                    client_code=ucc, symbol=symbol, status=status,
                    bo_quantity=bo_qty, bo_avg_cost=bo_cost,
                    bo_total_cost=_safe_dec(bo["total_cost"]),
                    bo_market_price=bo_price, bo_market_value=bo_value,
                    bo_pnl=bo_pnl_val,
                    bo_weight_pct=_safe_dec(bo["holding_market_pct"]),
                    bo_isin=bo.get("isin", ""),
                    our_quantity=our_qty, our_avg_cost=our_avg,
                    our_total_cost=our_cost_basis,
                    our_market_price=bo_price,
                    our_market_value=our_value_at_bo_price,
                    our_pnl=our_pnl_at_bo_price,
                    our_weight_pct=our["weight_pct"],
                    qty_diff=(bo_qty - our_qty),
                    cost_diff=(bo_cost - our_avg),
                    value_diff=(bo_value - our_value_at_bo_price),
                    pnl_diff=(bo_pnl_val - our_pnl_at_bo_price),
                    family_group=family_group,
                )

                if status == "MATCH":
                    client_recon.matched_count += 1
                elif status == "QTY_MISMATCH":
                    client_recon.qty_mismatch_count += 1
                elif status == "COST_MISMATCH":
                    client_recon.cost_mismatch_count += 1

            client_recon.matches.append(match)

        # Extra symbols we have that backoffice doesn't
        for symbol, our in our_client_holdings.items():
            if symbol not in our_symbols_seen:
                if symbol in _EXCLUDE_FROM_EXTRA:
                    continue
                match = HoldingMatch(
                    client_code=ucc, symbol=symbol, status="EXTRA_IN_OURS",
                    our_quantity=our["quantity"], our_avg_cost=our["avg_cost"],
                    our_total_cost=(our["quantity"] * our["avg_cost"]),
                    our_market_price=our["current_price"],
                    our_market_value=our["current_value"],
                    our_pnl=our["unrealized_pnl"],
                    our_weight_pct=our["weight_pct"],
                    family_group=family_group,
                )
                client_recon.extra_in_ours_count += 1
                client_recon.matches.append(match)

        # 3-way totals for this client
        client_recon.bo_holdings_total = bo_total
        client_recon.our_holdings_total = our_total_at_bo_price
        client_recon.bo_vs_ours_diff = bo_total - our_total_at_bo_price

        nav_data = latest_navs.get(ucc)
        if nav_data:
            nav_val = nav_data["nav_value"]
            client_recon.nav_total = nav_val
            client_recon.nav_vs_bo_diff = nav_val - bo_total
            client_recon.nav_date = nav_data["nav_date"]
            summary.total_nav_value += nav_val
            summary.clients_with_nav += 1

        summary.total_bo_holdings_value += bo_total
        summary.total_our_holdings_value += our_total_at_bo_price
        summary.total_bo_vs_ours_diff += client_recon.bo_vs_ours_diff

        summary.clients.append(client_recon)
        summary.total_holdings_matched += client_recon.matched_count
        summary.total_qty_mismatches += client_recon.qty_mismatch_count
        summary.total_cost_mismatches += client_recon.cost_mismatch_count
        summary.total_value_mismatches += client_recon.value_mismatch_count
        summary.total_missing_in_ours += client_recon.missing_in_ours_count
        summary.total_extra_in_ours += client_recon.extra_in_ours_count

    summary.total_clients_matched = sum(1 for c in summary.clients if c.client_found)
    summary.total_clients_missing = summary.total_clients_bo - summary.total_clients_matched
    summary.total_nav_vs_bo_diff = summary.total_nav_value - summary.total_bo_holdings_value

    logger.info(
        "3-way reconciliation: %d/%d clients, %d/%d holdings matched, "
        "NAV=%.0f BO=%.0f Ours=%.0f",
        summary.total_clients_matched, summary.total_clients_bo,
        summary.total_holdings_matched, summary.total_holdings_bo,
        summary.total_nav_value, summary.total_bo_holdings_value,
        summary.total_our_holdings_value,
    )

    summary.commentary = generate_commentary(summary)
    return summary
