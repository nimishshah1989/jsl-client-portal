"""NAV Series model — cpp_nav_series table."""

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class NavSeries(Base):
    """
    Daily NAV time series for a client portfolio.
    Drives all performance charts, risk metrics, and drawdown analysis.
    NAV values are absolute rupee amounts (not base-100 normalized).
    """

    __tablename__ = "cpp_nav_series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_clients.id", ondelete="CASCADE"), nullable=False
    )
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    nav_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    nav_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, comment="Absolute NAV in INR"
    )
    invested_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, comment="Corpus / total invested"
    )
    current_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, comment="Current portfolio value"
    )
    benchmark_value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6), nullable=True, comment="Nifty 50 close on this date"
    )
    cash_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="Liquidity % from NAV file"
    )
    etf_value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, comment="Investments in ETF (LIQUIDBEES etc)"
    )
    cash_value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, comment="Cash And Cash Equivalent from NAV file"
    )
    bank_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, comment="Bank Balance from NAV file"
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "client_id", "portfolio_id", "nav_date",
            name="uq_cpp_nav_client_portfolio_date",
        ),
        Index(
            "idx_cpp_nav_client_date",
            "client_id", "portfolio_id", "nav_date",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<NavSeries client={self.client_id} date={self.nav_date} "
            f"nav={self.nav_value}>"
        )
