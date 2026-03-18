"""Risk metric model — cpp_risk_metrics table."""

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class RiskMetric(Base):
    """
    Computed risk metrics for a client portfolio on a given date.
    Recomputed after every NAV upload via the risk engine.
    """

    __tablename__ = "cpp_risk_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_clients.id", ondelete="CASCADE"), nullable=False
    )
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    computed_date: Mapped[dt.date] = mapped_column(Date, nullable=False)

    # Returns
    absolute_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cagr: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    xirr: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Risk
    volatility: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sharpe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sortino_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    max_dd_start: Mapped[dt.date | None] = mapped_column(Date)
    max_dd_end: Mapped[dt.date | None] = mapped_column(Date)
    max_dd_recovery: Mapped[dt.date | None] = mapped_column(Date)

    # Benchmark comparison
    alpha: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    beta: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    information_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    tracking_error: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    up_capture: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    down_capture: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Stress
    ulcer_index: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    market_correlation: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Monthly profile
    monthly_hit_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    best_month: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    worst_month: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    avg_positive_month: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    avg_negative_month: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    max_consecutive_loss: Mapped[int | None] = mapped_column(Integer)
    win_months: Mapped[int | None] = mapped_column(Integer)
    loss_months: Mapped[int | None] = mapped_column(Integer)

    # Cash metrics
    avg_cash_held: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    max_cash_held: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    current_cash: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    # Period returns — portfolio
    return_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    return_3m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    return_6m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    return_1y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    return_2y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    return_3y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    return_4y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    return_5y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    return_inception: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Period returns — benchmark
    bench_return_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_return_3m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_return_6m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_return_1y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_return_2y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_return_3y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_return_4y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_return_5y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_return_inception: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Period CAGR — portfolio
    cagr_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cagr_3m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cagr_6m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cagr_1y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cagr_2y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cagr_3y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cagr_4y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cagr_5y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cagr_inception: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Period CAGR — benchmark
    bench_cagr_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_cagr_3m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_cagr_6m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_cagr_1y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_cagr_2y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_cagr_3y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_cagr_4y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_cagr_5y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_cagr_inception: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Period volatility — portfolio
    vol_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    vol_3m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    vol_6m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    vol_1y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    vol_2y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    vol_3y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    vol_inception: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Period volatility — benchmark
    bench_vol_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_vol_3m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_vol_6m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_vol_1y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_vol_2y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_vol_3y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_vol_inception: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Period max drawdown — portfolio
    dd_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    dd_3m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    dd_6m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    dd_1y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    dd_2y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    dd_3y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    dd_inception: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Period max drawdown — benchmark
    bench_dd_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_dd_3m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_dd_6m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_dd_1y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_dd_2y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_dd_3y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_dd_inception: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Period Sharpe — portfolio
    sharpe_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sharpe_3m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sharpe_6m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sharpe_1y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sharpe_2y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sharpe_3y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sharpe_inception: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Period Sharpe — benchmark
    bench_sharpe_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_sharpe_3m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_sharpe_6m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_sharpe_1y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_sharpe_2y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_sharpe_3y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_sharpe_inception: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Period Sortino — portfolio
    sortino_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sortino_3m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sortino_6m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sortino_1y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sortino_2y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sortino_3y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sortino_inception: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Period Sortino — benchmark
    bench_sortino_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_sortino_3m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_sortino_6m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_sortino_1y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_sortino_2y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_sortino_3y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    bench_sortino_inception: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Risk-free rate used
    risk_free_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), default=Decimal("6.50"), server_default="6.5000"
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_cpp_risk_client_date", "client_id", "portfolio_id", "computed_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<RiskMetric client={self.client_id} date={self.computed_date} "
            f"cagr={self.cagr}>"
        )
