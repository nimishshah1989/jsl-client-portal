"""Auth router — login, logout, me, change-password, CSRF, consent."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import get_settings
from backend.database import get_db
from backend.middleware.auth_middleware import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from backend.middleware.security import generate_csrf_token
from backend.models.client import Client
from backend.models.consent import ClientConsent
from backend.schemas.auth import (
    ChangePasswordRequest,
    ConsentRequest,
    LoginRequest,
    LoginResponse,
    UserResponse,
)
from backend.services.audit_service import get_client_ip, get_request_id, log_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)

_settings = get_settings()
COOKIE_MAX_AGE = _settings.JWT_EXPIRY_HOURS * 3600
_SECURE_COOKIE = _settings.APP_ENV == "production"

_LOCKOUT_THRESHOLD = 10
_LOCKOUT_MINUTES = 30


@router.get("/csrf")
async def issue_csrf_token(response: Response) -> dict[str, str]:
    """Issue a CSRF token cookie for unauthenticated callers.

    H1: with CSRF default-deny enabled, the login form must obtain a token
    before it can POST /api/auth/login. This endpoint sets the same
    ``csrf_token`` cookie that POST /login sets after a successful login,
    so the frontend can simply read ``document.cookie`` and echo the value
    in the X-CSRF-Token header.

    Returns the token in the JSON body as well so non-cookie clients (e.g.
    server-rendered pages, native apps) can also use it.
    """
    csrf_token = generate_csrf_token()
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=_SECURE_COOKIE,
        samesite="strict",
        path="/",
        max_age=COOKIE_MAX_AGE,
    )
    return {"csrf_token": csrf_token}


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Authenticate client and set httpOnly JWT cookie + CSRF cookie."""
    stmt = (
        select(Client)
        .options(selectinload(Client.portfolios))
        .where(Client.username == body.username)
        .where(Client.is_active.is_(True))
        .where(Client.is_deleted.is_(False))
    )
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()

    # H3: check lockout before touching the password (prevents timing oracle)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if client is not None and client.locked_until and client.locked_until > now:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCOUNT_LOCKED",
                "locked_until": client.locked_until.isoformat(),
                "message": "Too many failed attempts. Account locked for 30 minutes.",
            },
        )

    if client is None or not verify_password(body.password, client.password_hash):
        if client is not None:
            # H3: track consecutive failures
            client.failed_login_count += 1
            if client.failed_login_count >= _LOCKOUT_THRESHOLD:
                client.locked_until = now + timedelta(minutes=_LOCKOUT_MINUTES)
                client.failed_login_count = 0
            await db.flush()

        await log_audit(
            db, user_id=None, action="LOGIN_FAILED",
            resource_type="SYSTEM", ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:500],
            request_id=get_request_id(request),
            details={"username": body.username},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # C6: block login until password is set (admin-bulk-created accounts)
    if not client.is_password_set:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PASSWORD_NOT_SET",
                "message": "Please set your password before logging in.",
            },
        )

    # Successful login — reset lockout counters (H3)
    client.failed_login_count = 0
    client.locked_until = None
    client.last_login = now

    token = create_access_token(client.id, client.is_admin, client.token_version)
    await db.flush()

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=_SECURE_COOKIE,
        samesite="strict",
        path="/",
        max_age=COOKIE_MAX_AGE,
    )

    csrf_token = generate_csrf_token()
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=_SECURE_COOKIE,
        samesite="strict",
        path="/",
        max_age=COOKIE_MAX_AGE,
    )

    await log_audit(
        db, user_id=client.id, action="LOGIN",
        resource_type="SYSTEM", ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:500],
        request_id=get_request_id(request),
    )

    return LoginResponse(
        client_name=client.name,
        portfolio_count=len(client.portfolios),
        is_admin=client.is_admin,
    )


@router.post("/logout")
async def logout(
    response: Response,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Clear cookies and bump token_version to invalidate all outstanding JWTs (C5)."""
    await db.execute(
        update(Client)
        .where(Client.id == user["client_id"])
        .values(token_version=Client.token_version + 1)
    )
    await db.flush()

    response.delete_cookie(
        key="access_token",
        httponly=True,
        secure=_SECURE_COOKIE,
        samesite="strict",
        path="/",
    )
    response.delete_cookie(
        key="csrf_token",
        httponly=False,
        secure=_SECURE_COOKIE,
        samesite="strict",
        path="/",
    )
    return {"message": "logged out"}


@router.get("/me", response_model=UserResponse)
async def me(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Return authenticated client's profile."""
    stmt = select(Client).where(Client.id == user["client_id"])
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()

    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )

    return UserResponse(
        client_id=client.id,
        client_code=client.client_code,
        name=client.name,
        email=client.email,
        phone=client.phone,
        is_admin=client.is_admin,
        last_login=client.last_login,
    )


@router.post("/change-password")
@limiter.limit("5/hour")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Change password; sets is_password_set=True and invalidates other sessions (C5+C6)."""
    stmt = select(Client).where(Client.id == user["client_id"])
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()

    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )

    if not verify_password(body.old_password, client.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    client.password_hash = hash_password(body.new_password)
    client.is_password_set = True         # C6: gate cleared
    client.token_version += 1             # C5: invalidate all other sessions
    client.failed_login_count = 0         # H3: clear any residual lockout state
    client.locked_until = None
    await db.flush()

    await log_audit(
        db, user_id=user["client_id"], action="UPDATE",
        resource_type="CLIENT", resource_id=user["client_id"],
        ip_address=get_client_ip(request),
        request_id=get_request_id(request),
        details={"field": "password"},
    )

    return {"message": "password changed"}


@router.post("/consent", status_code=status.HTTP_201_CREATED)
async def accept_consent(
    request: Request,
    body: ConsentRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Record client consent acceptance for SEBI compliance."""
    consent = ClientConsent(
        client_id=user["client_id"],
        consent_type=body.consent_type,
        accepted=body.accepted,
        accepted_at=datetime.now(timezone.utc).replace(tzinfo=None) if body.accepted else None,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:500],
    )
    db.add(consent)
    await db.flush()

    await log_audit(
        db, user_id=user["client_id"], action="CREATE",
        resource_type="CONSENT",
        ip_address=get_client_ip(request),
        request_id=get_request_id(request),
        details={"consent_type": body.consent_type, "accepted": body.accepted},
    )

    return {"message": f"consent {'accepted' if body.accepted else 'declined'}"}


@router.get("/consents")
async def get_consents(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return all consent records for the authenticated client."""
    stmt = (
        select(ClientConsent)
        .where(ClientConsent.client_id == user["client_id"])
        .order_by(ClientConsent.created_at.desc())
    )
    result = await db.execute(stmt)
    consents = list(result.scalars().all())
    return [
        {
            "consent_type": c.consent_type,
            "accepted": c.accepted,
            "accepted_at": c.accepted_at.isoformat() if c.accepted_at else None,
            "document_version": c.document_version,
            "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
        }
        for c in consents
    ]
