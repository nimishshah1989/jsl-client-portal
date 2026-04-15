"""
Reconciliation engine — 3-way comparison of holdings data.

Compares three independent data sources per client:
  1. NAV file (cpp_nav_series) — total portfolio value, broken down into
     equity / ETF / cash components
  2. Backoffice Holding Report (.xlsx) — per-holding equity breakdown
  3. Transaction-derived holdings (cpp_holdings) — our FIFO-computed positions

Per-holding comparison uses the BO market price on both sides so that
value_diff isolates qty/cost differences, not price-feed artifacts.

Matching is ISIN-first (authoritative, stable across symbol renames).
Symbol fallback is used only when either side lacks ISIN — logged as a warning
and flagged via matched_by="symbol" on the HoldingMatch.

Total-level comparison uses nav_equity_component (NAV minus ETF minus cash),
which is directly comparable to bo_holdings_total. Structural extras (ETF/MF
positions tracked in NAV's ETF column, not in the BO equity report) will appear
as EXTRA_IN_OURS — this is intentional and explained by nav_equity_vs_bo_diff ≈ 0.

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


@dataclass
class HoldingMatch:
    """Result of comparing one (client, symbol/ISIN) pair."""

    client_code: str
    symbol: str
    status: str  # MATCH | QTY_MISMATCH | COST_MISMATCH | MISSING_IN_OURS | EXTRA_IN_OURS

    # How the match was made — "isin" (authoritative) or "symbol" (fallback)
    matched_by: str = "isin"

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
    our_asset_class: str | None = None  # from cpp_holdings — helps identify structural extras

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

    # ── 4-component NAV breakdown (from NAV file) ────────────────────────────
    # nav_total = nav_equity_component + etf_component_nav + cash_component_nav
    nav_total: Decimal | None = None            # Total NAV
    nav_equity_component: Decimal | None = None # Equity Holding At Mkt (col 3)
    etf_component_nav: Decimal | None = None    # Investments in ETF (col 4)
    cash_component_nav: Decimal | None = None   # Cash & Cash Equivalent + Bank Balance
    nav_date: dt.date | None = None

    # ── Equity reconciliation (3-way) ────────────────────────────────────────
    # Source 2: BO Holding Report (equity + exchange-traded ETFs like GOLDBEES)
    bo_holdings_total: Decimal = _ZERO
    # Source 3: Our FIFO-computed holdings valued at BO market prices
    our_holdings_total: Decimal = _ZERO
    # nav_equity_vs_bo_diff ≈ 0 → equity fully reconciled
    nav_equity_vs_bo_diff: Decimal | None = None
    # bo_vs_ours_diff ≈ 0 → our FIFO matches BO exactly (no qty/cost errors)
    bo_vs_ours_diff: Decimal = _ZERO
    # nav_vs_bo_diff: includes ETF+cash structural gap — kept for reference
    nav_vs_bo_diff: Decimal | None = None

    # ── ETF reconciliation ────────────────────────────────────────────────────
    # EXTRA_IN_OURS positions are the ETF/MF holdings tracked in nav's ETF column.
    # Their total current_value (if prices are populated) should ≈ etf_component_nav.
    # If current prices are zero (not yet backfilled), etf_vs_ours_diff will equal
    # etf_component_nav — showing what's unpriced, not a real gap.
    our_etf_holdings_total: Decimal = _ZERO     # Sum of current_value for EXTRA positions
    etf_vs_ours_diff: Decimal | None = None     # etf_component_nav - our_etf_holdings_total

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

    # 4-component aggregate totals across all clients
    total_nav_value: Decimal = _ZERO
    total_nav_equity_value: Decimal = _ZERO    # Equity only (NAV - ETF - cash)
    total_etf_value: Decimal = _ZERO           # ETF column across all clients
    total_cash_value: Decimal = _ZERO          # Cash + bank across all clients
    total_bo_holdings_value: Decimal = _ZERO
    total_our_holdings_value: Decimal = _ZERO
    total_our_etf_holdings_value: Decimal = _ZERO
    # nav_equity_vs_bo ≈ 0 → all equity reconciled firm-wide
    total_nav_equity_vs_bo_diff: Decimal = _ZERO
    # nav_vs_bo includes ETF+cash structural gap (reference)
    total_nav_vs_bo_diff: Decimal = _ZERO
    total_bo_vs_ours_diff: Decimal = _ZERO
    total_etf_vs_ours_diff: Decimal = _ZERO
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


async def _load_our_holdings(
    db: AsyncSession,
) -> tuple[
    dict[str, dict[str, dict]],   # keyed by (client_code, symbol)
    dict[str, dict[str, dict]],   # keyed by (client_code, isin) — where ISIN is known
    dict[str, str],               # client_code → client name
]:
    """Load all holdings from cpp_holdings.

    Returns two parallel lookup dicts so reconciliation can match by ISIN first
    (authoritative, stable) then fall back to symbol (for records without ISIN).
    """
    result = await db.execute(text("""
        SELECT
            c.client_code, c.name, h.symbol, h.isin, h.quantity,
            h.avg_cost, h.current_price, h.current_value,
            h.unrealized_pnl, h.weight_pct, h.asset_class
        FROM cpp_holdings h
        JOIN cpp_clients c ON c.id = h.client_id
        WHERE h.quantity > 0
        ORDER BY c.client_code, h.symbol
    """))

    by_symbol: dict[str, dict[str, dict]] = {}
    by_isin: dict[str, dict[str, dict]] = {}
    client_names: dict[str, str] = {}

    for row in result.fetchall():
        code, name, symbol, isin = row[0], row[1] or "", row[2], row[3] or ""
        holding = {
            "symbol": symbol,
            "isin": isin,
            "quantity": _safe_dec(row[4]),
            "avg_cost": _safe_dec(row[5]),
            "current_price": _safe_dec(row[6]),
            "current_value": _safe_dec(row[7]),
            "unrealized_pnl": _safe_dec(row[8]),
            "weight_pct": _safe_dec(row[9]),
            "asset_class": row[10] or "EQUITY",
        }

        if code not in by_symbol:
            by_symbol[code] = {}
            by_isin[code] = {}
            client_names[code] = name

        by_symbol[code][symbol] = holding
        if isin:
            by_isin[code][isin] = holding

    logger.info(
        "Loaded our holdings: %d clients, %d positions (%d with ISIN)",
        len(by_symbol),
        sum(len(v) for v in by_symbol.values()),
        sum(len(v) for v in by_isin.values()),
    )
    return by_symbol, by_isin, client_names


async def _load_latest_navs(db: AsyncSession) -> dict[str, dict]:
    """Load latest NAV per client from cpp_nav_series, keyed by client_code.

    Returns nav_value (total), equity_component (NAV minus ETF, cash, bank),
    invested_amount, and nav_date. equity_component is directly comparable
    to the BO holding report total.
    """
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
        nav_value = _safe_dec(row[1])
        etf_value = _safe_dec(row[3])       # "Investments in ETF" column
        cash_value = _safe_dec(row[4])      # "Cash And Cash Equivalent" column
        bank_balance = _safe_dec(row[5])    # "Bank Balance" column
        cash_component = cash_value + bank_balance
        # Equity component = NAV minus all non-equity buckets
        # This is what the BO holding report (equity section) should total to
        equity_component = nav_value - etf_value - cash_component
        navs[row[0]] = {
            "nav_value": nav_value,
            "invested_amount": _safe_dec(row[2]),
            "etf_value": etf_value,
            "cash_component": cash_component,   # cash + bank combined
            "equity_component": equity_component,
            "nav_date": row[6],
        }

    logger.info("Loaded latest NAVs for %d clients", len(navs))
    return navs


async def reconcile(
    backoffice_holdings: list[dict],
    db: AsyncSession,
) -> ReconciliationSummary:
    """Run full 3-way reconciliation: NAV vs BO Holding Report vs our holdings.

    Matching priority:
      1. ISIN (authoritative — stable across symbol renames / suffix variations)
      2. Symbol string (fallback only when either side lacks ISIN — logged as warning)

    Total-level comparison uses nav_equity_component (NAV minus ETF minus cash)
    which is directly comparable to bo_holdings_total. nav_equity_vs_bo_diff ≈ 0
    means the equity component of the NAV fully accounts for BO holdings.

    EXTRA_IN_OURS items where the BO total reconciles (bo_vs_ours_diff ≈ 0) are
    structural — typically ETF/MF positions tracked in the NAV file's ETF column
    rather than the equity holding report.
    """
    our_by_symbol, our_by_isin, client_names = await _load_our_holdings(db)
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

        our_sym = our_by_symbol.get(ucc, {})
        our_isn = our_by_isin.get(ucc, {})

        if our_sym:
            seen_client_codes.add(ucc)
            client_recon.total_holdings_ours = len(our_sym)
        else:
            client_recon.client_found = False

        # Track which of our symbols/ISINs were matched by BO entries
        our_isins_seen: set[str] = set()
        our_symbols_seen: set[str] = set()
        bo_total = _ZERO
        our_total_at_bo_price = _ZERO

        for bo in bo_holdings:
            bo_symbol = bo["symbol"]
            bo_isin = (bo.get("isin") or "").strip()
            bo_price = _safe_dec(bo["market_price"])
            bo_value = _safe_dec(bo["market_value"])
            bo_total += bo_value

            # ── ISIN-first lookup ────────────────────────────────────────────
            our = None
            matched_by = "isin"
            if bo_isin and bo_isin in our_isn:
                our = our_isn[bo_isin]
                matched_by = "isin"
            elif bo_symbol in our_sym:
                # Symbol fallback — warn if BO had an ISIN we should have matched
                our = our_sym[bo_symbol]
                matched_by = "symbol"
                if bo_isin:
                    logger.warning(
                        "Client %s symbol %s (ISIN %s): matched by symbol fallback — "
                        "our holdings may be missing ISIN. Re-ingest to populate.",
                        ucc, bo_symbol, bo_isin,
                    )

            if our is None:
                match = HoldingMatch(
                    client_code=ucc, symbol=bo_symbol, status="MISSING_IN_OURS",
                    matched_by="isin" if bo_isin else "symbol",
                    bo_quantity=_safe_dec(bo["quantity"]),
                    bo_avg_cost=_safe_dec(bo["avg_cost"]),
                    bo_total_cost=_safe_dec(bo["total_cost"]),
                    bo_market_price=bo_price,
                    bo_market_value=bo_value,
                    bo_pnl=_safe_dec(bo["notional_pnl"]),
                    bo_weight_pct=_safe_dec(bo["holding_market_pct"]),
                    bo_isin=bo_isin,
                    family_group=family_group,
                )
                client_recon.missing_in_ours_count += 1
            else:
                # Track matched keys to detect EXTRA_IN_OURS later
                if matched_by == "isin":
                    our_isins_seen.add(bo_isin)
                our_symbols_seen.add(our["symbol"])

                our_qty = our["quantity"]
                our_avg = our["avg_cost"]

                bo_qty = _safe_dec(bo["quantity"])
                bo_cost = _safe_dec(bo["avg_cost"])
                bo_pnl_val = _safe_dec(bo["notional_pnl"])

                # Use BO market price for our value — apples-to-apples comparison
                # so value_diff reflects qty/cost differences only, not price feeds
                our_value_at_bo_price = our_qty * bo_price
                our_total_at_bo_price += our_value_at_bo_price

                our_cost_basis = our_qty * our_avg
                our_pnl_at_bo_price = our_value_at_bo_price - our_cost_basis

                status = _classify(bo, our_qty, our_avg)

                match = HoldingMatch(
                    client_code=ucc, symbol=bo_symbol, status=status,
                    matched_by=matched_by,
                    bo_quantity=bo_qty, bo_avg_cost=bo_cost,
                    bo_total_cost=_safe_dec(bo["total_cost"]),
                    bo_market_price=bo_price, bo_market_value=bo_value,
                    bo_pnl=bo_pnl_val,
                    bo_weight_pct=_safe_dec(bo["holding_market_pct"]),
                    bo_isin=bo_isin,
                    our_quantity=our_qty, our_avg_cost=our_avg,
                    our_total_cost=our_cost_basis,
                    our_market_price=bo_price,
                    our_market_value=our_value_at_bo_price,
                    our_pnl=our_pnl_at_bo_price,
                    our_weight_pct=our["weight_pct"],
                    our_asset_class=our.get("asset_class"),
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

        # ── Extra positions (in our holdings, not in BO equity report) ──────
        # These are ETF/MF positions tracked in the NAV file's "Investments in ETF"
        # column rather than the BO equity holding report. They are structural —
        # not a data error — and reconcile against etf_component_nav.
        our_etf_total = _ZERO
        for symbol, our in our_sym.items():
            if symbol in our_symbols_seen:
                continue
            our_isin = our.get("isin", "") or ""
            if our_isin and our_isin in our_isins_seen:
                continue  # Already matched via ISIN under a different symbol name

            our_cv = _safe_dec(our.get("current_value"))
            our_etf_total += our_cv  # sum market value of extras (0 if prices not updated)

            match = HoldingMatch(
                client_code=ucc, symbol=symbol, status="EXTRA_IN_OURS",
                matched_by="isin" if our_isin else "symbol",
                our_quantity=our["quantity"], our_avg_cost=our["avg_cost"],
                our_total_cost=(our["quantity"] * our["avg_cost"]),
                our_market_price=our["current_price"],
                our_market_value=our_cv,
                our_pnl=our["unrealized_pnl"],
                our_weight_pct=our["weight_pct"],
                our_asset_class=our.get("asset_class"),
                bo_isin=our_isin or None,
                family_group=family_group,
            )
            client_recon.extra_in_ours_count += 1
            client_recon.matches.append(match)

        # ── Populate all reconciliation totals for this client ───────────────
        client_recon.bo_holdings_total = bo_total
        client_recon.our_holdings_total = our_total_at_bo_price
        client_recon.bo_vs_ours_diff = bo_total - our_total_at_bo_price
        client_recon.our_etf_holdings_total = our_etf_total

        nav_data = latest_navs.get(ucc)
        if nav_data:
            nav_val = nav_data["nav_value"]
            equity_component = nav_data["equity_component"]
            etf_component = nav_data["etf_value"]
            cash_component = nav_data["cash_component"]
            client_recon.nav_total = nav_val
            client_recon.nav_equity_component = equity_component
            client_recon.etf_component_nav = etf_component
            client_recon.cash_component_nav = cash_component
            client_recon.nav_date = nav_data["nav_date"]
            # Equity check: nav_equity_component ≈ bo_holdings_total → equity reconciled
            client_recon.nav_equity_vs_bo_diff = equity_component - bo_total
            # Full NAV vs BO diff (includes ETF + cash structural gap — reference only)
            client_recon.nav_vs_bo_diff = nav_val - bo_total
            # ETF check: etf_component_nav ≈ our_etf_holdings_total (when prices are current)
            client_recon.etf_vs_ours_diff = etf_component - our_etf_total
            summary.total_nav_value += nav_val
            summary.total_nav_equity_value += equity_component
            summary.total_etf_value += etf_component
            summary.total_cash_value += cash_component
            summary.total_our_etf_holdings_value += our_etf_total
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
    summary.total_nav_equity_vs_bo_diff = (
        summary.total_nav_equity_value - summary.total_bo_holdings_value
    )
    summary.total_etf_vs_ours_diff = (
        summary.total_etf_value - summary.total_our_etf_holdings_value
    )

    logger.info(
        "4-component reconciliation: %d/%d clients, %d/%d holdings matched | "
        "NAV=%.0f  Equity=%.0f  ETF=%.0f  Cash=%.0f | "
        "BO=%.0f  Ours=%.0f  ETF_ours=%.0f",
        summary.total_clients_matched, summary.total_clients_bo,
        summary.total_holdings_matched, summary.total_holdings_bo,
        summary.total_nav_value, summary.total_nav_equity_value,
        summary.total_etf_value, summary.total_cash_value,
        summary.total_bo_holdings_value, summary.total_our_holdings_value,
        summary.total_our_etf_holdings_value,
    )

    summary.commentary = generate_commentary(summary)
    return summary
