"""Portfolio response schemas — all financial values as Decimal (str-serialized)."""

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, Field


class SummaryResponse(BaseModel):
    """GET /api/portfolio/summary — top-level stat cards."""
    invested: str
    current_value: str
    profit_amount: str
    profit_pct: str
    cagr: str
    ytd_return: str
    max_drawdown: str
    as_of_date: dt.date
    cash_amount: str | None = None   # Current cash in ₹ (from Cash & Cash Equivalent)
    cash_pct: str | None = None      # Current cash as % of NAV


class NavSeriesPoint(BaseModel):
    """Single data point in the NAV time series chart.

    nav          — actual portfolio current_value in ₹
    benchmark    — what the same invested_amount would be worth in Nifty at this date (₹)
    invested     — corpus/invested amount at this date (₹) — for step-line overlay
    benchmark_raw — base-100 Nifty index value (kept for reference/future use)
    cash_pct     — liquidity % clamped to [0, 100]
    """
    date: dt.date
    nav: str
    benchmark: str | None = None
    invested: str | None = None
    benchmark_raw: str | None = None
    cash_pct: str | None = None
    cash_flow: str | None = None  # Non-null on dates with inflow/outflow (₹ amount, negative=outflow)


class PerformanceRow(BaseModel):
    """One row in the multi-period performance table."""
    period: str
    port_abs_return: str | None = None
    bench_abs_return: str | None = None
    port_cagr: str | None = None
    bench_cagr: str | None = None
    port_volatility: str | None = None
    bench_volatility: str | None = None
    port_max_dd: str | None = None
    bench_max_dd: str | None = None
    port_sharpe: str | None = None
    bench_sharpe: str | None = None
    port_sortino: str | None = None
    bench_sortino: str | None = None


class GrowthResponse(BaseModel):
    """GET /api/portfolio/growth — what your money became."""
    invested: str
    portfolio: str
    nifty: str
    fd: str
    inception_date: dt.date
    latest_date: dt.date
    years: str


class AllocationItem(BaseModel):
    """Single allocation slice (by class or sector)."""
    name: str
    value: str
    weight_pct: str


class AllocationResponse(BaseModel):
    """GET /api/portfolio/allocation — sector-only breakdown."""
    by_sector: list[AllocationItem]


class HoldingResponse(BaseModel):
    """Single holding row."""
    symbol: str
    asset_name: str | None = None
    asset_class: str | None = None
    sector: str | None = None
    quantity: str
    avg_cost: str
    current_price: str | None = None
    current_value: str | None = None
    unrealized_pnl: str | None = None
    pnl_pct: str | None = None
    weight_pct: str | None = None


class DrawdownPoint(BaseModel):
    """Single data point in the underwater chart."""
    date: dt.date
    drawdown_pct: str
    bench_drawdown: str | None = None


class RiskScorecardResponse(BaseModel):
    """GET /api/portfolio/risk-scorecard."""
    # Benchmark comparison
    alpha: str | None = None
    beta: str | None = None
    information_ratio: str | None = None
    tracking_error: str | None = None
    up_capture: str | None = None
    down_capture: str | None = None
    # Stress
    ulcer_index: str | None = None
    market_correlation: str | None = None
    max_drawdown: str | None = None
    max_dd_start: dt.date | None = None
    max_dd_end: dt.date | None = None
    max_dd_recovery: dt.date | None = None
    # Monthly profile
    monthly_hit_rate: str | None = None
    best_month: str | None = None
    worst_month: str | None = None
    avg_positive_month: str | None = None
    avg_negative_month: str | None = None
    max_consecutive_loss: int | None = None
    win_months: int | None = None
    loss_months: int | None = None
    # Monthly return series for heatmap (year, month, return_pct)
    monthly_returns: list[dict] = []
    # Cash
    avg_cash_held: str | None = None
    max_cash_held: str | None = None
    current_cash: str | None = None
    # Headline risk metrics
    volatility: str | None = None
    sharpe_ratio: str | None = None
    sortino_ratio: str | None = None


class TransactionItem(BaseModel):
    """Single transaction row."""
    id: int
    txn_date: dt.date
    txn_type: str
    symbol: str
    asset_name: str | None = None
    asset_class: str | None = None
    quantity: str | None = None
    price: str | None = None
    amount: str


class PaginatedTransactions(BaseModel):
    """GET /api/portfolio/transactions — paginated."""
    items: list[TransactionItem]
    total: int
    page: int
    per_page: int
    total_pages: int


class XIRRResponse(BaseModel):
    """GET /api/portfolio/xirr."""
    xirr: str
    cash_flows_count: int
    first_investment_date: dt.date | None = None
    total_invested: str
    cash_flow_source: str = "inferred"  # "actual" or "inferred"


class MethodologyMetricInput(BaseModel):
    """Inputs used to compute a specific metric."""
    model_config = {"extra": "allow"}


class MethodologyMetric(BaseModel):
    """A single metric for the methodology page."""
    value: str | None = None
    benchmark_value: str | None = None
    inputs: dict[str, str | None] = Field(default_factory=dict)


class MethodologyResponse(BaseModel):
    """GET /api/portfolio/methodology."""
    as_of_date: dt.date
    risk_free_rate: str
    trading_days_per_year: int = 252
    benchmark_name: str = "NIFTY 50"
    metrics: dict[str, MethodologyMetric]
