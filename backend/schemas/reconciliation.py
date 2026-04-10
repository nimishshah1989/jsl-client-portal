"""Reconciliation request/response schemas."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, Field


class HoldingMatchResponse(BaseModel):
    """Single holding comparison result."""

    client_code: str
    symbol: str
    status: str  # MATCH | QTY_MISMATCH | COST_MISMATCH | VALUE_MISMATCH | MISSING_IN_OURS | EXTRA_IN_OURS
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

    # Diffs
    qty_diff: Decimal | None = None
    cost_diff: Decimal | None = None
    value_diff: Decimal | None = None
    pnl_diff: Decimal | None = None

    model_config = {"from_attributes": True}


class ClientReconciliationResponse(BaseModel):
    """Reconciliation result for a single client."""

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
    match_pct: float = 100.0
    has_issues: bool = False
    matches: list[HoldingMatchResponse] = Field(default_factory=list)


class ReconciliationSummaryResponse(BaseModel):
    """Top-level reconciliation summary."""

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
    match_pct: float = 100.0
    market_date: dt.date | None = None
    clients: list[ClientReconciliationResponse] = Field(default_factory=list)
