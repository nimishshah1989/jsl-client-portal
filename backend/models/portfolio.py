"""Portfolio model — cpp_portfolios table."""

import datetime as dt

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class Portfolio(Base):
    """
    A single portfolio belonging to a client.
    One client may have multiple portfolios (e.g., PMS Equity, PMS Balanced).
    """

    __tablename__ = "cpp_portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_clients.id", ondelete="CASCADE"), nullable=False
    )
    portfolio_name: Mapped[str] = mapped_column(String(200), nullable=False)
    benchmark: Mapped[str] = mapped_column(
        String(50), default="NIFTY500", server_default="NIFTY500"
    )
    inception_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active"
    )
    # Source UCC for this portfolio (e.g. BJ53, BJ53PASS). One portfolio per code.
    client_code: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)
    # Strategy bucket derived from the code suffix — see services/classification.py.
    strategy: Mapped[str] = mapped_column(
        String(20), default="LEADERS", server_default="LEADERS", nullable=False
    )
    # Archived account (CLOSE/CLO suffix): excluded from live aggregates + Combined.
    is_closed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    client = relationship("Client", back_populates="portfolios")

    __table_args__ = (
        UniqueConstraint("client_id", "portfolio_name", name="uq_cpp_portfolios_client_name"),
    )

    def __repr__(self) -> str:
        return (
            f"<Portfolio id={self.id} client_id={self.client_id} "
            f"name={self.portfolio_name!r}>"
        )
