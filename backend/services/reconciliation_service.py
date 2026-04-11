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
        """True if every holding in this client is a perfect match."""
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

    @property
    def match_pct(self) -> float:
        """Datapoint accuracy: % of individual holdings that match perfectly."""
        total = self.total_holdings_bo + self.total_extra_in_ours
        if total == 0:
            return 100.0
        return round(self.total_holdings_matched / total * 100, 1)

    @property
    def client_match_pct(self) -> float:
        """Client accuracy: % of clients where ALL holdings match perfectly."""
        if not self.clients:
            return 100.0
        fully_clean = sum(1 for c in self.clients if c.is_fully_matched)
        return round(fully_clean / len(self.clients) * 100, 1)

    @property
    def clients_fully_matched(self) -> int:
        """Count of clients with zero mismatches."""
        return sum(1 for c in self.clients if c.is_fully_matched)


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
    """Classify a matched holding pair.

    Only qty and cost are compared — these are what we control.
    Market value/price differences are expected (different price feed dates)
    and are NOT flagged as mismatches.
    """
    bo_qty = _safe_dec(bo["quantity"])
    bo_cost = _safe_dec(bo["avg_cost"])

    qty_diff = abs(bo_qty - our_qty)
    cost_diff = abs(bo_cost - our_avg_cost)

    if qty_diff > _QTY_TOLERANCE:
        return "QTY_MISMATCH"
    if cost_diff > _COST_TOLERANCE:
        return "COST_MISMATCH"
    return "MATCH"


async def _load_our_holdings(db: AsyncSession) -> tuple[dict[str, dict[str, dict]], dict[str, str]]:
    """
    Load all holdings from cpp_holdings, keyed by (client_code, symbol).

    Returns:
        ({client_code: {symbol: {...}}}, {client_code: client_name})
    """
    result = await db.execute(text("""
        SELECT
            c.client_code,
            c.name,
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
    client_names: dict[str, str] = {}
    for row in result.fetchall():
        code = row[0]
        name = row[1] or ""
        symbol = row[2]
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
    our_holdings, client_names = await _load_our_holdings(db)

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

                bo_qty = _safe_dec(bo["quantity"])
                bo_cost = _safe_dec(bo["avg_cost"])
                bo_price = _safe_dec(bo["market_price"])
                bo_value = _safe_dec(bo["market_value"])
                bo_pnl_val = _safe_dec(bo["notional_pnl"])

                # If our current_price is missing (not yet fetched from yfinance),
                # use the BO market price for apples-to-apples value comparison.
                # This way value_diff reflects qty/cost differences only, not
                # stale-price artifacts.
                if our_price == _ZERO and bo_price > _ZERO:
                    our_price = bo_price
                    our_value = our_qty * bo_price
                    cost_basis = our_qty * our_avg
                    our_pnl = our_value - cost_basis

                status = _classify(bo, our_qty, our_avg, our_price, our_value, our_pnl)

                match = HoldingMatch(
                    client_code=ucc,
                    symbol=symbol,
                    status=status,
                    bo_quantity=bo_qty,
                    bo_avg_cost=bo_cost,
                    bo_total_cost=_safe_dec(bo["total_cost"]),
                    bo_market_price=bo_price,
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
                # Skip symbols known to be tracked in separate systems
                if symbol in _EXCLUDE_FROM_EXTRA:
                    continue
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

    # Generate automated commentary
    summary.commentary = generate_commentary(summary)

    return summary


def generate_commentary(summary: ReconciliationSummary) -> list[dict]:
    """
    Analyze mismatch patterns and generate human-readable commentary.

    Detects:
      - Consistent quantity ratios (stock splits/bonuses)
      - Systematic cost differences per symbol
      - Symbols missing/extra across many clients
      - Overall match quality

    Returns list of dicts: {type, severity, title, detail, affected_clients}
    """
    from collections import Counter

    insights: list[dict] = []
    all_matches: list[HoldingMatch] = []
    for c in summary.clients:
        all_matches.extend(c.matches)

    # --- 1. Detect quantity ratio patterns (stock splits/bonuses) ---
    qty_mismatches = [m for m in all_matches if m.status == "QTY_MISMATCH"]
    if qty_mismatches:
        # Group by symbol, check for consistent ratios
        by_symbol: dict[str, list[float]] = {}
        for m in qty_mismatches:
            if m.bo_quantity and m.our_quantity and m.bo_quantity > 0:
                ratio = float(m.our_quantity / m.bo_quantity)
                sym = m.symbol
                if sym not in by_symbol:
                    by_symbol[sym] = []
                by_symbol[sym].append(round(ratio, 1))

        for sym, ratios in by_symbol.items():
            ratio_counts = Counter(ratios)
            dominant_ratio, count = ratio_counts.most_common(1)[0]
            if count >= 3 and dominant_ratio != 1.0:
                # Consistent ratio across multiple clients = likely corporate action
                insights.append({
                    "type": "STOCK_SPLIT",
                    "severity": "high",
                    "title": f"{sym}: Likely {dominant_ratio:.0f}:1 stock split or bonus",
                    "detail": (
                        f"Our system shows {dominant_ratio:.0f}x the quantity vs backoffice "
                        f"across {count} clients. Avg cost matches, confirming this is a "
                        f"corporate action (split/bonus) that the backoffice adjusted but "
                        f"our transaction history hasn't been corrected for."
                    ),
                    "affected_clients": count,
                    "symbol": sym,
                })
            elif count >= 2:
                insights.append({
                    "type": "QTY_PATTERN",
                    "severity": "medium",
                    "title": f"{sym}: Quantity mismatch ({dominant_ratio:.1f}x ratio) across {count} clients",
                    "detail": (
                        f"Consistent {dominant_ratio:.1f}x quantity ratio suggests a "
                        f"corporate action or systematic transaction gap."
                    ),
                    "affected_clients": count,
                    "symbol": sym,
                })

    # --- 2. Detect systematic cost differences per symbol ---
    cost_mismatches = [m for m in all_matches if m.status == "COST_MISMATCH"]
    if cost_mismatches:
        by_symbol_cost: dict[str, list[Decimal]] = {}
        for m in cost_mismatches:
            if m.cost_diff is not None:
                sym = m.symbol
                if sym not in by_symbol_cost:
                    by_symbol_cost[sym] = []
                by_symbol_cost[sym].append(abs(m.cost_diff))

        for sym, diffs in by_symbol_cost.items():
            avg_diff = sum(diffs) / len(diffs)
            if len(diffs) >= 5:
                insights.append({
                    "type": "COST_SYSTEMATIC",
                    "severity": "medium",
                    "title": f"{sym}: Systematic avg cost difference (avg diff: Rs.{avg_diff:.2f})",
                    "detail": (
                        f"Avg cost differs across {len(diffs)} clients by an average of "
                        f"Rs.{avg_diff:.2f}. This is likely due to a corporate action "
                        f"(unit consolidation, bonus) that changed the cost basis in the "
                        f"backoffice but not in our WAC computation."
                    ),
                    "affected_clients": len(diffs),
                    "symbol": sym,
                })

    # --- 3. Symbols extra in ours (sold/removed in backoffice) ---
    extra = [m for m in all_matches if m.status == "EXTRA_IN_OURS"]
    if extra:
        extra_by_sym = Counter(m.symbol for m in extra)
        for sym, count in extra_by_sym.most_common(5):
            if count >= 5:
                insights.append({
                    "type": "EXTRA_SYMBOL",
                    "severity": "medium",
                    "title": f"{sym}: Present in our system but not in backoffice ({count} clients)",
                    "detail": (
                        f"We show {sym} holdings for {count} clients but the backoffice "
                        f"doesn't. This stock was likely sold, transferred out, or removed "
                        f"in a transaction batch we haven't ingested."
                    ),
                    "affected_clients": count,
                    "symbol": sym,
                })

    # --- 4. Symbols missing in ours (new positions in backoffice) ---
    missing = [m for m in all_matches if m.status == "MISSING_IN_OURS"]
    if missing:
        missing_by_sym = Counter(m.symbol for m in missing)
        for sym, count in missing_by_sym.most_common(5):
            if count >= 3:
                insights.append({
                    "type": "MISSING_SYMBOL",
                    "severity": "medium",
                    "title": f"{sym}: Present in backoffice but missing in our system ({count} clients)",
                    "detail": (
                        f"Backoffice shows {sym} for {count} clients but we don't have it. "
                        f"These are likely new positions from a transaction batch we "
                        f"haven't processed yet."
                    ),
                    "affected_clients": count,
                    "symbol": sym,
                })

    # --- 5. Overall health commentary ---
    if summary.total_holdings_bo > 0:
        match_rate = summary.total_holdings_matched / summary.total_holdings_bo * 100
        if match_rate >= 95:
            insights.insert(0, {
                "type": "HEALTH",
                "severity": "good",
                "title": f"Excellent match rate: {match_rate:.1f}%",
                "detail": "Holdings data is well-aligned with the backoffice.",
                "affected_clients": 0,
            })
        elif match_rate >= 70:
            insights.insert(0, {
                "type": "HEALTH",
                "severity": "medium",
                "title": f"Moderate match rate: {match_rate:.1f}%",
                "detail": "Review the insights below for systematic issues to fix.",
                "affected_clients": 0,
            })
        else:
            insights.insert(0, {
                "type": "HEALTH",
                "severity": "critical",
                "title": f"Low match rate: {match_rate:.1f}% — systematic issues detected",
                "detail": (
                    "Most mismatches are likely from corporate actions (stock splits, "
                    "bonuses) that the backoffice applied but our system hasn't adjusted for. "
                    "See specific insights below."
                ),
                "affected_clients": 0,
            })

    # Sort: critical → high → medium → good
    severity_order = {"critical": 0, "high": 1, "medium": 2, "good": 3}
    insights.sort(key=lambda x: severity_order.get(x["severity"], 99))

    return insights
