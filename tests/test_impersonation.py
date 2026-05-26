"""Tests for the impersonation cookie split (C17).

Verifies the cookie invariant:
  - Admin routes  → read only ``access_token``.
  - Portfolio routes → prefer ``impersonation_token`` if present, else fall
    back to ``access_token``.
"""

import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "a" * 64)

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from backend.middleware.auth_middleware import (
    _extract_token,
    create_access_token,
    get_admin_user,
    get_current_user,
)


def _make_request(cookies: dict) -> MagicMock:
    request = MagicMock()
    request.cookies = cookies
    return request


class TestExtractToken:
    def test_admin_route_ignores_impersonation_cookie(self):
        request = _make_request({
            "access_token": "ADMIN_TOK",
            "impersonation_token": "CLIENT_TOK",
        })
        assert _extract_token(request, prefer_impersonation=False) == "ADMIN_TOK"

    def test_portfolio_route_prefers_impersonation_cookie(self):
        request = _make_request({
            "access_token": "ADMIN_TOK",
            "impersonation_token": "CLIENT_TOK",
        })
        assert _extract_token(request, prefer_impersonation=True) == "CLIENT_TOK"

    def test_portfolio_route_falls_back_to_access_token(self):
        request = _make_request({"access_token": "ADMIN_TOK"})
        assert _extract_token(request, prefer_impersonation=True) == "ADMIN_TOK"

    def test_missing_cookie_raises_401(self):
        from fastapi import HTTPException
        request = _make_request({})
        with pytest.raises(HTTPException) as exc:
            _extract_token(request, prefer_impersonation=False)
        assert exc.value.status_code == 401

    def test_missing_cookie_raises_401_on_portfolio_route(self):
        from fastapi import HTTPException
        request = _make_request({})
        with pytest.raises(HTTPException) as exc:
            _extract_token(request, prefer_impersonation=True)
        assert exc.value.status_code == 401


class TestAdminDependency:
    @patch("backend.middleware.auth_middleware.settings")
    def test_admin_route_uses_admin_access_token(self, mock_settings):
        """Admin token in access_token cookie → admin granted."""
        mock_settings.JWT_SECRET = "a" * 64
        mock_settings.JWT_EXPIRY_HOURS = 48

        admin_token = create_access_token(client_id=1, is_admin=True)
        request = _make_request({"access_token": admin_token})

        result = asyncio.run(get_admin_user(request))
        assert result["client_id"] == 1
        assert result["is_admin"] is True

    @patch("backend.middleware.auth_middleware.settings")
    def test_admin_route_ignores_impersonation_token(self, mock_settings):
        """
        When BOTH cookies are present (admin currently impersonating a client),
        admin routes must read access_token, not the client impersonation
        token. Otherwise admin would lose access during impersonation, which
        is exactly the back-nav bug we're fixing.
        """
        mock_settings.JWT_SECRET = "a" * 64
        mock_settings.JWT_EXPIRY_HOURS = 48

        admin_token = create_access_token(client_id=1, is_admin=True)
        client_token = create_access_token(client_id=42, is_admin=False)
        request = _make_request({
            "access_token": admin_token,
            "impersonation_token": client_token,
        })

        result = asyncio.run(get_admin_user(request))
        assert result["client_id"] == 1
        assert result["is_admin"] is True

    @patch("backend.middleware.auth_middleware.settings")
    def test_admin_route_rejects_non_admin_access_token(self, mock_settings):
        """A non-admin access_token gets 403, even if impersonation_token is admin-flagged."""
        mock_settings.JWT_SECRET = "a" * 64
        mock_settings.JWT_EXPIRY_HOURS = 48

        from fastapi import HTTPException
        client_token = create_access_token(client_id=42, is_admin=False)
        # Crafted: impersonation cookie says admin (it shouldn't matter)
        rogue_token = create_access_token(client_id=42, is_admin=True)
        request = _make_request({
            "access_token": client_token,
            "impersonation_token": rogue_token,
        })

        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_admin_user(request))
        assert exc.value.status_code == 403


class TestCurrentUserDependency:
    @patch("backend.middleware.auth_middleware.settings")
    def test_portfolio_route_prefers_impersonation_token(self, mock_settings):
        """
        Admin viewing as client X: access_token=admin, impersonation_token=client.
        Portfolio routes must return the CLIENT's identity.
        """
        mock_settings.JWT_SECRET = "a" * 64
        mock_settings.JWT_EXPIRY_HOURS = 48

        admin_token = create_access_token(client_id=1, is_admin=True)
        client_token = create_access_token(client_id=42, is_admin=False)
        request = _make_request({
            "access_token": admin_token,
            "impersonation_token": client_token,
        })

        result = asyncio.run(get_current_user(request))
        assert result["client_id"] == 42
        assert result["is_admin"] is False
        assert result["via_impersonation"] is True

    @patch("backend.middleware.auth_middleware.settings")
    def test_portfolio_route_falls_back_to_access_token(self, mock_settings):
        """No impersonation cookie → access_token used directly."""
        mock_settings.JWT_SECRET = "a" * 64
        mock_settings.JWT_EXPIRY_HOURS = 48

        client_token = create_access_token(client_id=7, is_admin=False)
        request = _make_request({"access_token": client_token})

        result = asyncio.run(get_current_user(request))
        assert result["client_id"] == 7
        assert result["is_admin"] is False
        assert result["via_impersonation"] is False
