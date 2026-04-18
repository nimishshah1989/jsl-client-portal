"""SQLAlchemy 2.0 async engine, session factory, and Base model."""

from __future__ import annotations

import ssl
from collections.abc import AsyncGenerator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import get_settings

settings = get_settings()

# ── Naming convention for constraints (keeps migrations predictable) ──
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""

    metadata = metadata


# ── SSL context for RDS ──
_ssl_context = ssl.create_default_context()
if settings.APP_ENV == "production":
    _ssl_context.check_hostname = True
    _ssl_context.verify_mode = ssl.CERT_REQUIRED
else:
    _ssl_context.check_hostname = False
    _ssl_context.verify_mode = ssl.CERT_NONE

# ── Async engine (for FastAPI) ──
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args={"ssl": _ssl_context},
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Sync engine (for scripts and migrations) ──
sync_engine = create_engine(
    settings.DATABASE_URL_SYNC,
    echo=(settings.APP_ENV == "development"),
    pool_pre_ping=True,
) if settings.DATABASE_URL_SYNC else None

SyncSessionLocal: sessionmaker[Session] | None = (
    sessionmaker(bind=sync_engine, expire_on_commit=False)
    if sync_engine
    else None
)
