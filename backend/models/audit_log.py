"""Audit Log model — cpp_audit_log table for SEBI compliance."""

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func, Index
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class AuditLog(Base):
    """
    Immutable audit trail for all data access and modifications.
    SEBI requires 7-year retention of access logs.
    """

    __tablename__ = "cpp_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cpp_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    action: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="VIEW | DOWNLOAD | CREATE | UPDATE | DELETE | LOGIN | LOGIN_FAILED | IMPERSONATE | UPLOAD | RECOMPUTE",
    )
    resource_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="PORTFOLIO | HOLDINGS | NAV | TRANSACTIONS | RISK_METRICS | CLIENT | SYSTEM",
    )
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_client_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cpp_clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Client whose data was accessed (for cross-client audit)",
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_cpp_audit_log_action_created", "action", "created_at"),
        Index("ix_cpp_audit_log_target_created", "target_client_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action!r} user={self.user_id}>"
