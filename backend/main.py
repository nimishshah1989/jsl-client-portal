"""FastAPI application entry point for the Client Portfolio Portal."""

import logging
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.config import get_settings
from backend.database import async_engine

settings = get_settings()

# ── Logging ──
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("cpp")


# ── Lifespan: verify DB on startup ──


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Verify database connectivity on startup, dispose engine on shutdown."""
    logger.info("Starting %s (env=%s)", settings.APP_NAME, settings.APP_ENV)
    try:
        async with async_engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.close()
        logger.info("Database connection verified")
    except Exception as exc:
        logger.error("Database connection FAILED: %s", exc)
        raise RuntimeError(
            f"Cannot connect to database. Check DATABASE_URL. Error: {exc}"
        ) from exc
    yield
    await async_engine.dispose()
    logger.info("Application shutdown complete")


# ── App ──

app = FastAPI(
    title=settings.APP_NAME,
    version=os.getenv("APP_VERSION", "1.0.0"),
    docs_url="/api/docs" if settings.APP_ENV != "production" else None,
    redoc_url="/api/redoc" if settings.APP_ENV != "production" else None,
    openapi_url="/api/openapi.json" if settings.APP_ENV != "production" else None,
    lifespan=lifespan,
)

# ── CORS ──

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ── Exception Handlers ──


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Return 422 for value errors raised in business logic."""
    logger.warning("ValueError on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler — log full traceback, return sanitized 500."""
    logger.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# ── Routers ──

from backend.routers.auth import router as auth_router  # noqa: E402
from backend.routers.portfolio import router as portfolio_router  # noqa: E402
from backend.routers.portfolio_detail import router as portfolio_detail_router  # noqa: E402
from backend.routers.admin import router as admin_router  # noqa: E402
from backend.routers.admin_clients import router as admin_clients_router  # noqa: E402

app.include_router(auth_router)
app.include_router(portfolio_router)
app.include_router(portfolio_detail_router)
app.include_router(admin_router)
app.include_router(admin_clients_router)


# ── Health Check ──


@app.get("/api/health")
async def health() -> dict:
    """Health check endpoint for load balancer and monitoring."""
    return {
        "status": "healthy",
        "service": "client-portfolio-portal",
        "version": os.getenv("APP_VERSION", "1.0.0"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
