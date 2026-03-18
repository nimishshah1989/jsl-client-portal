"""Authentication service — password hashing (bcrypt) and JWT management."""

import logging
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from backend.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# bcrypt with cost factor 12 — NEVER lower
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

_JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Hash a plain-text password using bcrypt with cost factor 12."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception:
        logger.warning("Password verification failed — possibly malformed hash")
        return False


def create_jwt(client_id: int, is_admin: bool) -> str:
    """
    Create an HS256 JWT token.

    Payload:
        sub   — client_id (int)
        admin — whether this user has admin privileges
        exp   — expiry timestamp (now + JWT_EXPIRY_HOURS)
        iat   — issued-at timestamp
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": client_id,
        "admin": is_admin,
        "exp": now + timedelta(hours=settings.JWT_EXPIRY_HOURS),
        "iat": now,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    """
    Decode and validate a JWT token.

    Returns the full payload dict on success.
    Raises ValueError on invalid or expired tokens.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError(f"Invalid or expired token: {exc}") from exc

    # Validate required claims
    if "sub" not in payload:
        raise ValueError("Token missing 'sub' claim")
    if "admin" not in payload:
        raise ValueError("Token missing 'admin' claim")

    return payload
