"""Transaction model — cpp_transactions table."""

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Transaction(Base):
    """
    Individual buy/sell/bonus/corpus transaction for a client portfolio.
    Parsed from PMS backoffice transaction report.
    A single source row may produce both a BUY and SELL record.
    """

    __tablename__ = "cpp_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_clients.id", ondelete="CASCADE"), nullable=False
    )
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    txn_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    txn_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="BUY, SELL, BONUS, CORPUS_IN",
    )
    symbol: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Cleaned symbol e.g. RELIANCE"
    )
    asset_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    asset_class: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="EQUITY, CASH"
    )
    instrument_type: Mapped[str] = mapped_column(
        String(10), default="EQ", server_default="EQ",
        comment="EQ, BE, etc.",
    )
    exchange: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="CM (Cash Market)"
    )
    settlement_no: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Settlement number or Corpus/BONUS"
    )
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), nullable=True, comment="Net rate per share"
    )
    cost_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), nullable=True, comment="All-in cost rate incl taxes"
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, comment="Total amount with all costs"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_cpp_txn_client", "client_id", "portfolio_id", "txn_date"),
        Index("idx_cpp_txn_type", "txn_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} {self.txn_type} {self.symbol} "
            f"date={self.txn_date} amount={self.amount}>"
        )
