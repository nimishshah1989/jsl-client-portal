"""Upload Log model — cpp_upload_log table."""

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class UploadLog(Base):
    """
    Audit trail for admin file uploads.
    Tracks row counts, failures, and parse errors per upload.

    Also serves as the persistent backing store for in-flight upload jobs (C7).
    The ``job_id`` column is the UUID handed back to the admin UI from the
    upload endpoint; the UI polls ``/upload-status/{job_id}`` to read the
    current row from this table. Because rows live in Postgres rather than a
    process-local dict, polling works across multi-worker uvicorn setups even
    if the polling request lands on a different worker from the one running
    the ingestion task.
    """

    __tablename__ = "cpp_upload_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uploaded_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cpp_clients.id", ondelete="SET NULL"), nullable=True
    )
    file_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="NAV or TRANSACTIONS"
    )
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rows_processed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rows_failed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    clients_affected: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    errors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="'[]'::jsonb"
    )
    uploaded_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # C7: persistent background-job state.
    job_id: Mapped[str | None] = mapped_column(
        String(36), unique=True, nullable=True,
        comment="UUID issued at upload start; clients poll status by this",
    )
    status: Mapped[str] = mapped_column(
        String(20), default="completed", server_default="completed", nullable=False,
        comment="processing | completed | failed",
    )
    progress_pct: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False,
    )
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<UploadLog id={self.id} type={self.file_type!r} "
            f"rows={self.rows_processed} failed={self.rows_failed}>"
        )
