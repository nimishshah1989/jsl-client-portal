"""Client model — cpp_clients table."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base
from backend.utils.encryption import EncryptedString


class Client(Base):
    """
    PMS/advisory client or admin user.
    Username is enforced lowercase via DB constraint.
    Supports soft-delete for SEBI 7-year retention compliance.
    """

    __tablename__ = "cpp_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Fernet ciphertext adds ~80 bytes overhead; widened to 500 / 100 chars
    email: Mapped[str | None] = mapped_column(EncryptedString(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(EncryptedString(100), nullable=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    role: Mapped[str] = mapped_column(
        String(50), default="CLIENT", server_default="CLIENT",
        comment="CLIENT | ADMIN_READONLY | ADMIN_DATA_ENTRY | ADMIN_FULL",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # C5: JWT revocation — bump this on logout/password-change/role-change;
    # the same value is embedded as `tv` in the JWT and validated on every request.
    token_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )

    # C6: block login until the client sets a real password (admin-bulk-created accounts start False)
    is_password_set: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # H3: per-username login lockout
    failed_login_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # C11: per-client reconciliation status flag (soft gate — banner only, no blocking)
    # Default True for clients with no recon history (defensive — don't show banner).
    # Flipped to False by reconciliation_service when QTY_MISMATCH / EXTRA_HOLDING /
    # MISSING_HOLDING is detected for this client.
    is_recon_clean: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    recon_last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recon_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Soft delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cpp_clients.id", ondelete="SET NULL"), nullable=True,
    )

    # PR7 unified-login merge: when several per-code clients are the same person
    # they are collapsed into a single survivor. Non-survivors are soft-retired by
    # pointing merged_into at the survivor's id (is_active is kept so the retired
    # username still works during the alias grace period — login then issues the
    # JWT for the survivor). NULL = a normal, un-merged client. See
    # backend/services/merge_service.py.
    merged_into: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cpp_clients.id", ondelete="SET NULL"), nullable=True,
    )

    # Relationships
    portfolios = relationship("Portfolio", back_populates="client", lazy="selectin")

    __table_args__ = (
        CheckConstraint("username = LOWER(username)", name="username_lower"),
    )

    def __repr__(self) -> str:
        return f"<Client id={self.id} code={self.client_code!r} username={self.username!r}>"
