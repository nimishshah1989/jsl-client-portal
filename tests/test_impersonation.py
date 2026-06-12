"""Tests for the impersonation cookie split (C17) + DB re-validation (C5).

Verifies the cookie invariant:
  - Admin routes  → read only ``access_token``.
  - Portfolio routes → prefer ``impersonation_token`` if present, else fall
    back to ``access_token``.

The auth dependencies re-validate the decoded token against the DB
(``_validate_client_from_db``: is_active / is_deleted / token_version, and
is_admin/role are taken from the DB row). So these tests run against a real
in-memory session seeded with the relevant clients, rather than mocking that
step away — the admin/non-admin gating is exactly what we want to prove.
"""

import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "a" * 64)

import os as _os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.middleware.auth_middleware import (
    ROLE_ADMIN_FULL,
    ROLE_CLIENT,
    _extract_token,
    create_access_token,
    get_admin_user,
    get_current_user,
)
from backend.models.client import Client


def _make_request(cookies: dict) -> MagicMock:
    request = MagicMock()
    request.cookies = cookies
    return request


@pytest_asyncio.fixture(scope="function")
async def auth_db():
    """In-memory session seeded with the clients the auth flow re-validates:
    id=1 admin, id=7 + id=42 non-admin. All active, not deleted, token_version=1.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[Client.__table__]))

    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as session:
        session.add_all([
            Client(id=1, client_code="ADM1", name="Admin One", username="adminone",
                   password_hash="x", is_active=True, is_admin=True,
                   role=ROLE_ADMIN_FULL, token_version=1),
            Client(id=7, client_code="CL7", name="Client Seven", username="clientseven",
                   password_hash="x", is_active=True, is_admin=False,
                   role=ROLE_CLIENT, token_version=1),
            Client(id=42, client_code="CL42", name="Client Forty Two", username="clientfortytwo",
                   password_hash="x", is_active=True, is_admin=False,
                   role=ROLE_CLIENT, token_version=1),
        ])
        await session.commit()
        try:
            yield session
        finally:
            await engine.dispose()
            _os.unlink(tmp.name)


def _jwt_settings():
    """Patch auth_middleware.settings so create/decode share a known secret."""
    mock = patch("backend.middleware.auth_middleware.settings")
    return mock


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
    @pytest.mark.asyncio
    async def test_admin_route_uses_admin_access_token(self, auth_db):
        """Admin token in access_token cookie → admin granted."""
        with _jwt_settings() as mock_settings:
            mock_settings.JWT_SECRET = "a" * 64
            mock_settings.JWT_EXPIRY_HOURS = 48
            admin_token = create_access_token(client_id=1, is_admin=True, token_version=1)
            request = _make_request({"access_token": admin_token})

            result = await get_admin_user(request, db=auth_db)
            assert result["client_id"] == 1
            assert result["is_admin"] is True

    @pytest.mark.asyncio
    async def test_admin_route_ignores_impersonation_token(self, auth_db):
        """
        When BOTH cookies are present (admin currently impersonating a client),
        admin routes must read access_token, not the client impersonation
        token. Otherwise admin would lose access during impersonation, which
        is exactly the back-nav bug we're fixing.
        """
        with _jwt_settings() as mock_settings:
            mock_settings.JWT_SECRET = "a" * 64
            mock_settings.JWT_EXPIRY_HOURS = 48
            admin_token = create_access_token(client_id=1, is_admin=True, token_version=1)
            client_token = create_access_token(client_id=42, is_admin=False, token_version=1)
            request = _make_request({
                "access_token": admin_token,
                "impersonation_token": client_token,
            })

            result = await get_admin_user(request, db=auth_db)
            assert result["client_id"] == 1
            assert result["is_admin"] is True

    @pytest.mark.asyncio
    async def test_admin_route_rejects_non_admin_access_token(self, auth_db):
        """A non-admin access_token gets 403, even if impersonation_token is admin-flagged."""
        from fastapi import HTTPException
        with _jwt_settings() as mock_settings:
            mock_settings.JWT_SECRET = "a" * 64
            mock_settings.JWT_EXPIRY_HOURS = 48
            client_token = create_access_token(client_id=42, is_admin=False, token_version=1)
            # Crafted: impersonation cookie says admin (it shouldn't matter)
            rogue_token = create_access_token(client_id=42, is_admin=True, token_version=1)
            request = _make_request({
                "access_token": client_token,
                "impersonation_token": rogue_token,
            })

            with pytest.raises(HTTPException) as exc:
                await get_admin_user(request, db=auth_db)
            assert exc.value.status_code == 403


class TestCurrentUserDependency:
    @pytest.mark.asyncio
    async def test_portfolio_route_prefers_impersonation_token(self, auth_db):
        """
        Admin viewing as client X: access_token=admin, impersonation_token=client.
        Portfolio routes must return the CLIENT's identity.
        """
        with _jwt_settings() as mock_settings:
            mock_settings.JWT_SECRET = "a" * 64
            mock_settings.JWT_EXPIRY_HOURS = 48
            admin_token = create_access_token(client_id=1, is_admin=True, token_version=1)
            client_token = create_access_token(client_id=42, is_admin=False, token_version=1)
            request = _make_request({
                "access_token": admin_token,
                "impersonation_token": client_token,
            })

            result = await get_current_user(request, db=auth_db)
            assert result["client_id"] == 42
            assert result["is_admin"] is False
            assert result["via_impersonation"] is True

    @pytest.mark.asyncio
    async def test_portfolio_route_falls_back_to_access_token(self, auth_db):
        """No impersonation cookie → access_token used directly."""
        with _jwt_settings() as mock_settings:
            mock_settings.JWT_SECRET = "a" * 64
            mock_settings.JWT_EXPIRY_HOURS = 48
            client_token = create_access_token(client_id=7, is_admin=False, token_version=1)
            request = _make_request({"access_token": client_token})

            result = await get_current_user(request, db=auth_db)
            assert result["client_id"] == 7
            assert result["is_admin"] is False
            assert result["via_impersonation"] is False
