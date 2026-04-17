"""Reconciliation request/response schemas."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from typing import Any

from pydantic import BaseModel, Field


class HoldingMatchResponse(BaseModel):
    """Single holding comparison result."""

    client_code: str
    symbol: str
    status: str  # MATCH | QTY_MISMATCH | COST_MISMATCH | MISSING_IN_OURS | EXTRA_IN_OURS
    matched_by: str = "isin"    # "isin" (authoritative) or "symbol" (fallback)
    family_group: str = ""

    # Backoffice values
    bo_quantity: Decimal | None = None
    bo_avg_cost: Decimal | None = None
    bo_total_cost: Decimal | None = None
    bo_market_price: Decimal | None = None
    bo_market_value: Decimal | None = None
    bo_pnl: Decimal | None = None
    bo_weight_pct: Decimal | None = None
    bo_isin: str | None = None

    # Our computed values
    our_quantity: Decimal | None = None
    our_avg_cost: Decimal | None = None
    our_total_cost: Decimal | None = None
    our_market_price: Decimal | None = None
    our_market_value: Decimal | None = None
    our_pnl: Decimal | None = None
    our_weight_pct: Decimal | None = None
    our_asset_class: str | None = None

    # Diffs
    qty_diff: Decimal | None = None
    cost_diff: Decimal | None = None
    value_diff: Decimal | None = None
    pnl_diff: Decimal | None = None

    model_config = {"from_attributes": True}


class ClientReconciliationResponse(BaseModel):
    """Reconciliation result for a single client — 4-component breakdown.

    The full reconciliation identity:
        nav_total = nav_equity_component + etf_component_nav + cash_component_nav

    Equity check:  nav_equity_vs_bo_diff ≈ 0  →  equity fully reconciled
    ETF check:     etf_vs_ours_diff ≈ 0        →  ETF quantity × price reconciled
                   (diff shows as etf_component_nav when current prices are unpopulated)
    Cash:          cash_component_nav           →  residual, informational
    Holdings:      bo_vs_ours_diff ≈ 0         →  FIFO matches BO on all equity positions
    """

    client_code: str
    client_name: str = ""
    family_group: str = ""
    client_found: bool = True
    total_holdings_bo: int = 0
    total_holdings_ours: int = 0
    matched_count: int = 0
    qty_mismatch_count: int = 0
    cost_mismatch_count: int = 0
    value_mismatch_count: int = 0
    missing_in_ours_count: int = 0
    extra_in_ours_count: int = 0
    structural_etf_count: int = 0
    match_pct: float = 100.0
    has_issues: bool = False
    matches: list[HoldingMatchResponse] = Field(default_factory=list)

    # ── 4-component NAV breakdown (from NAV file) ────────────────────────────
    nav_total: Decimal | None = None
    nav_equity_component: Decimal | None = None   # Equity Holding At Mkt → comparable to BO
    etf_component_nav: Decimal | None = None      # Investments in ETF column
    cash_component_nav: Decimal | None = None     # Cash And Cash Equivalent + Bank Balance
    nav_date: dt.date | None = None

    # ── Equity reconciliation (3-way: NAV equity vs BO vs ours) ─────────────
    bo_holdings_total: Decimal = Decimal("0")
    our_holdings_total: Decimal = Decimal("0")
    nav_equity_vs_bo_diff: Decimal | None = None  # ≈ 0 when equity reconciles
    bo_vs_ours_diff: Decimal = Decimal("0")       # ≈ 0 when FIFO matches BO
    nav_vs_bo_diff: Decimal | None = None         # structural gap (ETF+cash) — reference only

    # ── ETF reconciliation ────────────────────────────────────────────────────
    our_etf_holdings_total: Decimal = Decimal("0")  # sum of EXTRA_IN_OURS current_value
    etf_vs_ours_diff: Decimal | None = None          # ≈ 0 when ETF prices are current


class ReconciliationSummaryResponse(BaseModel):
    """Top-level reconciliation summary — 4-component breakdown across all clients."""

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
    total_structural_etf: int = 0
    match_pct: float = 100.0
    client_match_pct: float = 100.0
    clients_fully_matched: int = 0

    # 4-component aggregate totals
    total_nav_value: Decimal = Decimal("0")
    total_nav_equity_value: Decimal = Decimal("0")
    total_etf_value: Decimal = Decimal("0")
    total_cash_value: Decimal = Decimal("0")
    total_bo_holdings_value: Decimal = Decimal("0")
    total_our_holdings_value: Decimal = Decimal("0")
    total_our_etf_holdings_value: Decimal = Decimal("0")
    total_nav_equity_vs_bo_diff: Decimal = Decimal("0")
    total_nav_vs_bo_diff: Decimal = Decimal("0")
    total_bo_vs_ours_diff: Decimal = Decimal("0")
    total_etf_vs_ours_diff: Decimal = Decimal("0")
    clients_with_nav: int = 0

    market_date: dt.date | None = None
    run_at: str | None = None
    filename: str | None = None
    commentary: list[dict[str, Any]] = Field(default_factory=list)
    clients: list[ClientReconciliationResponse] = Field(default_factory=list)
