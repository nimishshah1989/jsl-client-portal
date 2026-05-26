"""Schemas for DPDP Act 2023 data-rights endpoints under /api/me.

Covers:
  - §11 (right of access)         — export
  - §12 (right to erasure)        — erasure request
  - §7  (right to withdraw consent) — consent withdrawal
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field


class ErasureRequestBody(BaseModel):
    """POST /api/me/erasure-request request body.

    The reason is optional and free-text; it is logged in the audit row for the
    operator's records, but no automated action depends on its contents.
    """

    reason: str | None = Field(default=None, max_length=2000)


class ErasureRequestResponse(BaseModel):
    """202 Accepted response for an erasure request.

    Erasure is a manual operator workflow because SEBI mandates a 7-year
    retention window that overrides the DPDP Act's default deletion right
    for transaction/NAV data. The account is frozen (soft-deleted +
    token_version bumped) so the client cannot log in, but their data rows
    are preserved pending legal review.
    """

    status: str
    message: str


class ConsentWithdrawBody(BaseModel):
    """POST /api/me/consent/withdraw request body."""

    consent_type: str = Field(..., min_length=1, max_length=100)


class ConsentWithdrawResponse(BaseModel):
    """200 OK response after a consent has been marked revoked."""

    status: str
    consent_type: str
    withdrawn_at: dt.datetime


class DataExportResponse(BaseModel):
    """§11 export response — loose schema; payload is the client's data dump.

    Kept intentionally permissive (``dict[str, Any]`` values) because the
    contents include every row from eight different tables and the schema
    is documentary, not enforced — the endpoint returns the raw JSON file
    as an attachment.
    """

    as_of: dt.datetime
    client_id: int
    profile: dict[str, Any]
    portfolios: list[dict[str, Any]]
    nav_series: list[dict[str, Any]]
    transactions: list[dict[str, Any]]
    holdings: list[dict[str, Any]]
    risk_metrics: list[dict[str, Any]]
    drawdown_series: list[dict[str, Any]]
    consents: list[dict[str, Any]]
    audit_log: list[dict[str, Any]]
