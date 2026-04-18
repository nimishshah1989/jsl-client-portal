"""Auth request/response schemas."""

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    """POST /api/auth/login request body."""
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)

    @field_validator("username")
    @classmethod
    def lowercase_username(cls, v: str) -> str:
        return v.strip().lower()


class LoginResponse(BaseModel):
    """POST /api/auth/login response."""
    client_name: str
    portfolio_count: int
    is_admin: bool


class UserResponse(BaseModel):
    """GET /api/auth/me response."""
    client_id: int
    client_code: str
    name: str
    email: str | None = None
    phone: str | None = None
    is_admin: bool
    last_login: dt.datetime | None = None

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    """POST /api/auth/change-password request body."""
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=200)

    @field_validator("new_password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in v):
            raise ValueError("Password must contain at least one special character")
        return v


class ConsentRequest(BaseModel):
    """POST /api/auth/consent request body."""
    consent_type: str = Field(..., pattern="^(PERFORMANCE_REPORTING|RISK_DISCLOSURE|TERMS_OF_SERVICE|DATA_PROCESSING)$")
    accepted: bool
