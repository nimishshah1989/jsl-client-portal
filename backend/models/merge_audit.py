"""Merge audit model — cpp_merge_audit table.

One row per retired client folded into a survivor during the PR7 unified-login
merge. This is the reversibility record: it captures exactly which client_id was
re-parented onto which survivor, plus the retired code/username, so the merge can
be audited and (with an RDS snapshot) reasoned about or unwound. ``reverted_at``
is stamped if a row's merge is ever rolled back.
"""

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class MergeAudit(Base):
    """Audit trail of a single retired→survivor client merge."""

    __tablename__ = "cpp_merge_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # No ON DELETE CASCADE: this is the reversibility record and must NOT be erased
    # if a client row is ever hard-deleted. With NO ACTION a referenced client can't
    # be hard-deleted without first handling its audit rows (the system soft-deletes
    # anyway). The denormalised code/username/name below keep the row human-readable.
    survivor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_clients.id"), nullable=False
    )
    retired_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cpp_clients.id"), nullable=False
    )
    retired_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    retired_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Denormalised for a human-readable audit even after rows change.
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ran_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    reverted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<MergeAudit retired={self.retired_id} -> survivor={self.survivor_id} "
            f"code={self.retired_code!r}>"
        )
