"""Auth router — login, logout, me, change-password."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
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
from backend.models.client import Client
from backend.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_MAX_AGE = 48 * 3600  # 48 hours in seconds
_settings = get_settings()
_SECURE_COOKIE = _settings.APP_ENV == "production" and "https" in _settings.CORS_ORIGINS


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Authenticate client and set httpOnly JWT cookie."""
    stmt = (
        select(Client)
        .options(selectinload(Client.portfolios))
        .where(Client.username == body.username)
        .where(Client.is_active.is_(True))
    )
    result = await db.execute(stmt)
    client = result.scalar_one_or_none()

    if client is None or not verify_password(body.password, client.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_access_token(client.id, client.is_admin)

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=_SECURE_COOKIE,
        samesite="lax",
        path="/",
        max_age=COOKIE_MAX_AGE,
    )

    client.last_login = datetime.utcnow()
    await db.flush()

    return LoginResponse(
        client_name=client.name,
        portfolio_count=len(client.portfolios),
        is_admin=client.is_admin,
    )


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    """Clear the access_token cookie."""
    response.delete_cookie(
        key="access_token",
        httponly=True,
        secure=_SECURE_COOKIE,
        samesite="lax",
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
async def change_password(
    body: ChangePasswordRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Change the authenticated client's password."""
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
    await db.flush()

    return {"message": "password changed"}
