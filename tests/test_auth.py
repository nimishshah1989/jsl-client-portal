"""Tests for auth middleware — password hashing, JWT creation/validation."""

import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "a" * 64)

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from backend.middleware.auth_middleware import (
    hash_password,
    verify_password,
    create_access_token,
    _decode_token,
)


class TestPasswordHashing:
    def test_hash_returns_string(self):
        result = hash_password("testpassword123")
        assert isinstance(result, str)
        assert result.startswith("$2")  # bcrypt prefix

    def test_hash_is_unique(self):
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert h1 != h2  # Different salts

    def test_verify_correct_password(self):
        hashed = hash_password("correct_horse_battery_staple")
        assert verify_password("correct_horse_battery_staple", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_empty_password(self):
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("notempty", hashed) is False


class TestJWT:
    @patch("backend.middleware.auth_middleware.settings")
    def test_create_and_decode_token(self, mock_settings):
        mock_settings.JWT_SECRET = "a" * 64
        mock_settings.JWT_EXPIRY_HOURS = 48

        token = create_access_token(client_id=42, is_admin=False)
        assert isinstance(token, str)

        result = _decode_token(token)
        assert result["client_id"] == 42
        assert result["is_admin"] is False

    @patch("backend.middleware.auth_middleware.settings")
    def test_admin_flag_preserved(self, mock_settings):
        mock_settings.JWT_SECRET = "b" * 64
        mock_settings.JWT_EXPIRY_HOURS = 48

        token = create_access_token(client_id=1, is_admin=True)
        result = _decode_token(token)
        assert result["is_admin"] is True

    @patch("backend.middleware.auth_middleware.settings")
    def test_invalid_token_raises(self, mock_settings):
        mock_settings.JWT_SECRET = "c" * 64
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _decode_token("invalid.token.here")
        assert exc_info.value.status_code == 401

    @patch("backend.middleware.auth_middleware.settings")
    def test_expired_token_raises(self, mock_settings):
        mock_settings.JWT_SECRET = "d" * 64
        mock_settings.JWT_EXPIRY_HOURS = 0  # Immediate expiry

        import jwt as pyjwt
        payload = {
            "sub": "1",
            "admin": False,
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        token = pyjwt.encode(payload, "d" * 64, algorithm="HS256")

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _decode_token(token)
        assert exc_info.value.status_code == 401
