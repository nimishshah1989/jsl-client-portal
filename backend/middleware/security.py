"""Security middleware — request ID, security headers, CSRF protection."""

from __future__ import annotations

import hmac
import secrets
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from backend.config import get_settings

_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CSRF_COOKIE = "csrf_token"
_CSRF_HEADER = "x-csrf-token"

# H1: paths that are exempt from CSRF enforcement even for unsafe methods.
# Only health check and CORS preflight are exempt. Login, password reset,
# and any other state-changing endpoint MUST present a valid CSRF token.
_CSRF_EXEMPT_PATHS = frozenset({"/api/health"})


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request for tracing and audit."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add OWASP-recommended security headers to every response.

    M3: HSTS is set on EVERY response unless APP_ENV == "development". This
        makes the production-safe default explicit; the only way to disable
        it is to set APP_ENV=development (e.g. for local HTTP testing).

    M4: CSP drops `unsafe-eval`. Next.js production builds do not need eval,
        and the FastAPI app does not serve HTML, so a restrictive CSP is fine
        as a defense-in-depth header — browsers that do receive HTML (e.g.
        the Swagger UI in non-prod) will not need eval either since Swagger
        UI's modern build runs without it.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        settings = get_settings()
        if settings.APP_ENV != "development":
            # M3: HSTS default-on for any non-development environment
            # (production, staging, etc.). Two years, include subdomains,
            # eligible for browser preload list.
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )

        # M4: CSP without unsafe-eval. `script-src 'self'` is sufficient because
        # Next.js production builds don't use eval and the FastAPI app does not
        # serve any HTML that executes inline scripts.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Double-submit cookie CSRF protection for state-changing requests.

    H1 (default-deny): a valid CSRF token is required on EVERY unsafe-method
    request (POST/PUT/PATCH/DELETE), regardless of whether the caller is
    authenticated. This prevents CSRF on login, password reset, and any
    other unauthenticated state-changing endpoint.

    Exemptions:
      - OPTIONS preflight (handled by _CSRF_SAFE_METHODS — OPTIONS is in the
        safe-method set so it short-circuits before any token check)
      - /api/health (no state change, used by load balancers)

    Token issuance:
      - GET /api/auth/csrf issues a token to unauthenticated callers (so the
        login form can obtain one before POST /api/auth/login).
      - POST /api/auth/login also sets the cookie on success for subsequent
        authenticated requests.

    Validation uses constant-time comparison (hmac.compare_digest) to avoid
    timing oracles on the token value.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _CSRF_SAFE_METHODS:
            return await call_next(request)

        if request.url.path in _CSRF_EXEMPT_PATHS:
            return await call_next(request)

        cookie_token = request.cookies.get(_CSRF_COOKIE)
        header_token = request.headers.get(_CSRF_HEADER)

        if (
            not cookie_token
            or not header_token
            or not hmac.compare_digest(cookie_token, header_token)
        ):
            return Response(
                content='{"detail":"CSRF token missing or invalid"}',
                status_code=403,
                media_type="application/json",
            )

        return await call_next(request)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)
