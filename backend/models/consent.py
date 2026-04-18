"""Client Consent model — cpp_client_consents table for SEBI compliance."""

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ClientConsent(Base):
    """
    Tracks explicit client consent for services and disclosures.
    SEBI PMS circular requires documented consent for all services.
    """

    __tablename__ = "cpp_client_consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_clients.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    consent_type: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="PERFORMANCE_REPORTING | RISK_DISCLOSURE | TERMS_OF_SERVICE | DATA_PROCESSING",
    )
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accepted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    document_version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1.0",
    )
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ClientConsent id={self.id} client={self.client_id} type={self.consent_type!r}>"
