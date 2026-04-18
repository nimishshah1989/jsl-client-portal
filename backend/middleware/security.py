"""Security middleware — request ID, security headers, CSRF protection."""

from __future__ import annotations

import secrets
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from fastapi import HTTPException, status

from backend.config import get_settings

_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CSRF_COOKIE = "csrf_token"
_CSRF_HEADER = "x-csrf-token"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request for tracing and audit."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add OWASP-recommended security headers to every response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        settings = get_settings()
        if settings.APP_ENV == "production":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data:; "
                "connect-src 'self'"
            )
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Double-submit cookie CSRF protection for state-changing requests.
    GET /api/auth/csrf-token sets the cookie; POST/PUT/DELETE must echo it in header.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _CSRF_SAFE_METHODS or request.url.path == "/api/auth/login":
            return await call_next(request)

        cookie_token = request.cookies.get(_CSRF_COOKIE)
        header_token = request.headers.get(_CSRF_HEADER)

        if not cookie_token or not header_token or cookie_token != header_token:
            has_auth = request.cookies.get("access_token")
            if has_auth:
                return Response(
                    content='{"detail":"CSRF token missing or invalid"}',
                    status_code=403,
                    media_type="application/json",
                )

        return await call_next(request)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)
