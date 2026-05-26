"""JWT authentication middleware — extracts client_id from token."""

from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db

settings = get_settings()

ALGORITHM = "HS256"
_BCRYPT_ROUNDS = 12

# Role hierarchy for admin RBAC (M2).
#
# Each admin route declares the minimum role it requires; a user with a role at
# or above that level passes. CLIENT (rank 0) is never an admin — admin routes
# never see it because get_admin_user already rejects is_admin=False.
#
# Back-compat: if is_admin=True but role is missing/unknown (e.g. seeded admins
# from before the role column existed), we treat them as ADMIN_FULL.
ROLE_CLIENT = "CLIENT"
ROLE_ADMIN_READONLY = "ADMIN_READONLY"
ROLE_ADMIN_DATA_ENTRY = "ADMIN_DATA_ENTRY"
ROLE_ADMIN_FULL = "ADMIN_FULL"

_ROLE_RANK: dict[str, int] = {
    ROLE_CLIENT: 0,
    ROLE_ADMIN_READONLY: 1,
    ROLE_ADMIN_DATA_ENTRY: 2,
    ROLE_ADMIN_FULL: 3,
}


def _normalize_admin_role(role: str | None) -> str:
    """Return the effective admin role, falling back to ADMIN_FULL for legacy admins.

    A row with is_admin=True but role NULL/blank/unknown predates the role
    column being populated, so treat it as fully-privileged to avoid locking
    pre-existing operators out of their own tools.
    """
    if role is None:
        return ROLE_ADMIN_FULL
    role = role.strip().upper()
    if role in _ROLE_RANK and role != ROLE_CLIENT:
        return role
    return ROLE_ADMIN_FULL


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt cost factor 12."""
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against its bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(client_id: int, is_admin: bool, token_version: int) -> str:
    """Create a signed JWT with client_id, admin flag, and revocation version."""
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRY_HOURS)
    payload = {
        "sub": str(client_id),
        "admin": is_admin,
        "tv": token_version,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    client_id_raw = payload.get("sub")
    if client_id_raw is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )

    try:
        client_id = int(client_id_raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid subject claim in token",
        ) from exc

    return {
        "client_id": client_id,
        "is_admin": bool(payload.get("admin", False)),
        "token_version": int(payload.get("tv", 0)),
    }


def _extract_token(request: Request, prefer_impersonation: bool) -> str:
    """
    Read the JWT cookie from the request.

    When ``prefer_impersonation`` is True (portfolio routes), use the
    ``impersonation_token`` cookie if present so an admin can view-as-client
    without losing admin context, falling back to ``access_token``.

    When False (admin routes), only the ``access_token`` cookie is honored —
    admin powers must never be derived from the impersonation cookie.
    """
    if prefer_impersonation:
        token = request.cookies.get("impersonation_token")
        if token:
            return token
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — no access token cookie",
        )
    return token


async def _validate_client_from_db(
    decoded: dict, db: AsyncSession
) -> dict:
    """
    Re-validate token claims against the DB row.
    Checks is_active, is_deleted, and token_version (C5).
    Returns the decoded dict with is_admin refreshed from DB.
    """
    from backend.models.client import Client  # avoid circular import at module level

    result = await db.execute(
        select(
            Client.is_active,
            Client.is_deleted,
            Client.token_version,
            Client.is_admin,
            Client.role,
        )
        .where(Client.id == decoded["client_id"])
    )
    row = result.one_or_none()
    if row is None or not row.is_active or row.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found or inactive",
        )
    if decoded["token_version"] != row.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked — please log in again",
        )
    decoded["is_admin"] = row.is_admin  # always read from DB, not JWT
    # Effective admin role (M2). For non-admins the role on the user record may
    # legitimately be CLIENT — only normalize when the user IS an admin.
    decoded["role"] = (
        _normalize_admin_role(row.role) if row.is_admin else (row.role or ROLE_CLIENT)
    )
    return decoded


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    """
    FastAPI dependency: extract and validate JWT from httpOnly cookie.

    Prefers ``impersonation_token`` over ``access_token`` so admins viewing as
    a client see the client's data while their admin session stays intact (C17).
    Re-validates against DB on every request to honour token_version revocation
    and live is_admin / is_active / is_deleted changes (C5).

    Returns dict with keys: client_id (int), is_admin (bool), token_version (int),
    via_impersonation (bool).
    """
    impersonation = request.cookies.get("impersonation_token")
    token = _extract_token(request, prefer_impersonation=True)
    decoded = _decode_token(token)
    decoded = await _validate_client_from_db(decoded, db)
    decoded["via_impersonation"] = bool(impersonation) and impersonation == token
    return decoded


async def get_admin_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    required_role: str | None = None,
) -> dict:
    """
    FastAPI dependency: 403 if not admin. Admin routes only consult the
    ``access_token`` cookie — ``impersonation_token`` is intentionally ignored
    so admin powers cannot be exercised through an impersonation session (C17).
    Re-validates is_admin from DB so role downgrades take effect immediately (C5).

    When ``required_role`` is supplied (one of the ROLE_* constants), the
    caller's effective admin role must rank at or above it (M2). Routes that
    only read data should pass ``ROLE_ADMIN_READONLY``; mutating routes
    ``ROLE_ADMIN_DATA_ENTRY``; destructive routes ``ROLE_ADMIN_FULL``.
    """
    token = _extract_token(request, prefer_impersonation=False)
    decoded = _decode_token(token)
    decoded = await _validate_client_from_db(decoded, db)
    if not decoded["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    if required_role is not None:
        needed = _ROLE_RANK.get(required_role)
        actual = _ROLE_RANK.get(decoded.get("role", ROLE_ADMIN_FULL), 0)
        if needed is None:
            # Misconfigured route — fail closed.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server misconfiguration: unknown required role",
            )
        if actual < needed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient admin role: this action requires {required_role}"
                ),
            )
    decoded["via_impersonation"] = False
    return decoded


def require_role(required_role: str) -> Callable[..., Awaitable[dict]]:
    """Factory returning a FastAPI dependency that enforces a minimum admin role.

    Usage::

        @router.post("/upload-nav")
        async def upload_nav(
            admin: dict = Depends(require_role(ROLE_ADMIN_DATA_ENTRY)),
            ...
        ):

    See ``get_admin_user`` for the role hierarchy semantics. The factory pattern
    is used because FastAPI's ``Depends`` cannot pass extra kwargs to a single
    dependency, so we close over ``required_role`` and reuse ``get_admin_user``
    for the actual auth + DB re-validation work.
    """
    if required_role not in _ROLE_RANK or required_role == ROLE_CLIENT:
        raise ValueError(f"Invalid admin role: {required_role!r}")

    async def _dep(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        return await get_admin_user(request, db, required_role=required_role)

    # Make introspection (and FastAPI's dep cache key) distinguishable per role.
    _dep.__name__ = f"require_role_{required_role.lower()}"
    return _dep
