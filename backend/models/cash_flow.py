"""ORM model for cash flow records (capital inflows/outflows from PMS backoffice)."""

from datetime import date as date_type, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Column, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class CashFlow(Base):
    """A single capital inflow or outflow event for a client."""

    __tablename__ = "cpp_cash_flows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(Integer, ForeignKey("cpp_clients.id", ondelete="CASCADE"), nullable=False)
    portfolio_id: Mapped[int] = mapped_column(Integer, ForeignKey("cpp_portfolios.id", ondelete="CASCADE"), nullable=False)
    flow_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    flow_type: Mapped[str] = mapped_column(String(20), nullable=False)  # INFLOW, OUTFLOW
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    source_ucc: Mapped[str | None] = mapped_column(String(50))  # Original UCC from file
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        UniqueConstraint("client_id", "portfolio_id", "flow_date", "flow_type", "amount", name="uq_cpp_cash_flow"),
    )
