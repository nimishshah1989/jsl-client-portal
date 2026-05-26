"""JWT authentication middleware — extracts client_id from token."""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import HTTPException, Request, status

from backend.config import get_settings

settings = get_settings()

ALGORITHM = "HS256"
_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt cost factor 12."""
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against its bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(client_id: int, is_admin: bool) -> str:
    """Create a signed JWT with client_id and admin flag."""
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRY_HOURS)
    payload = {
        "sub": str(client_id),
        "admin": is_admin,
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


async def get_current_user(request: Request) -> dict:
    """
    FastAPI dependency: extract and validate JWT from httpOnly cookie.
    Returns dict with keys: client_id (int), is_admin (bool), via_impersonation (bool).

    Prefers ``impersonation_token`` over ``access_token`` so admins viewing as
    a client see the client's data while their admin session stays intact.
    """
    impersonation = request.cookies.get("impersonation_token")
    token = _extract_token(request, prefer_impersonation=True)
    decoded = _decode_token(token)
    decoded["via_impersonation"] = bool(impersonation) and impersonation == token
    return decoded


async def get_admin_user(request: Request) -> dict:
    """
    FastAPI dependency: 403 if not admin. Admin routes only consult the
    ``access_token`` cookie — ``impersonation_token`` is intentionally ignored
    so admin powers cannot be exercised through an impersonation session.
    """
    token = _extract_token(request, prefer_impersonation=False)
    user = _decode_token(token)
    if not user["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
