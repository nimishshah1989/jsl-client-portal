"""Admin request/response schemas."""

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field, field_validator


class UploadResponse(BaseModel):
    """Response after a file upload and ingestion."""
    file_type: str
    filename: str
    rows_processed: int
    rows_failed: int
    clients_affected: int
    errors: list[dict[str, Any]] = Field(default_factory=list)


class UploadPreviewResponse(BaseModel):
    """Response for upload file preview."""
    columns: list[str]
    sample_rows: list[dict[str, Any]]
    row_count: int
    auto_mapped: dict[str, str]


class ClientListResponse(BaseModel):
    """Single client in the admin client list."""
    id: int
    client_code: str
    name: str
    email: str | None = None
    phone: str | None = None
    username: str
    is_active: bool
    is_admin: bool
    portfolio_count: int
    last_login: dt.datetime | None = None

    model_config = {"from_attributes": True}


class CreateClientRequest(BaseModel):
    """POST /api/admin/clients — create single client."""
    client_code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    email: str | None = None
    phone: str | None = None
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=200)
    is_admin: bool = False

    @field_validator("username")
    @classmethod
    def lowercase_username(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("client_code")
    @classmethod
    def strip_client_code(cls, v: str) -> str:
        return v.strip()


class UpdateClientRequest(BaseModel):
    """PUT /api/admin/clients/{client_id}."""
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool | None = None
    new_password: str | None = Field(None, min_length=8, max_length=200)


class BulkCreateResponse(BaseModel):
    """POST /api/admin/clients/bulk-create response."""
    created: int
    skipped: int
    errors: list[dict[str, Any]] = Field(default_factory=list)


class UploadLogResponse(BaseModel):
    """Single upload log entry."""
    id: int
    uploaded_by: int | None = None
    file_type: str
    filename: str | None = None
    rows_processed: int
    rows_failed: int
    clients_affected: int
    errors: list[dict[str, Any]] = Field(default_factory=list)
    uploaded_at: dt.datetime

    model_config = {"from_attributes": True}
