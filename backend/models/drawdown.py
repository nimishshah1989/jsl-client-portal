"""Drawdown series model — cpp_drawdown_series table."""

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


class DrawdownSeries(Base):
    """
    Daily drawdown percentage for underwater chart visualization.
    Recomputed after every NAV upload.
    """

    __tablename__ = "cpp_drawdown_series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_clients.id", ondelete="CASCADE"), nullable=False
    )
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    dd_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    drawdown_pct: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, comment="Negative pct from peak"
    )
    bench_drawdown: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True, comment="Benchmark drawdown pct"
    )
    peak_nav: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    current_nav: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_cpp_dd_client_date", "client_id", "portfolio_id", "dd_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<DrawdownSeries client={self.client_id} date={self.dd_date} "
            f"dd={self.drawdown_pct}%>"
        )
