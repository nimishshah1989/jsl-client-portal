"""Holding model — cpp_holdings table."""

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Holding(Base):
    """
    Current holdings for a client portfolio.
    Computed by aggregating buy/sell transactions using weighted average cost.
    """

    __tablename__ = "cpp_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_clients.id", ondelete="CASCADE"), nullable=False
    )
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(100), nullable=False)
    asset_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    asset_class: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, comment="Weighted average cost per unit"
    )
    current_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), nullable=True, comment="Latest market price"
    )
    current_value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, comment="quantity * current_price"
    )
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, comment="(current_price - avg_cost) * quantity"
    )
    weight_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="Pct of total portfolio value"
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "client_id", "portfolio_id", "symbol",
            name="uq_cpp_holdings_client_portfolio_symbol",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Holding client={self.client_id} symbol={self.symbol!r} "
            f"qty={self.quantity}>"
        )
