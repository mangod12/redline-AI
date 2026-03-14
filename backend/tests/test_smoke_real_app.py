"""Integration smoke tests using the REAL app from app.main.

Unlike the unit tests (which build a separate FastAPI app in
conftest._build_test_app()), this test imports the actual ``app`` object
that Gunicorn serves in production.  This catches wiring bugs that only
manifest when all routers, middleware, and dependencies are assembled
together in main.py.

Bugs this suite would have caught during development:
  1. Auth router mounted behind JWT guard  -> login returned 401
  2. /api/v1/calls/live caught by /{call_id} -> 422 UUID parse error
  3. CSP blocked cdn.jsdelivr.net           -> Swagger UI failed to load
  4. Security headers missing on responses
  5. Dashboard accessible without authentication
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base

# ---------------------------------------------------------------------------
# Lightweight in-memory DB for smoke tests.
# pg_dialect patches from conftest.py are already applied (conftest loads
# first), so PostgreSQL-specific column types are SQLite-compatible.
# ---------------------------------------------------------------------------

_smoke_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
_SmokeSession = sessionmaker(
    _smoke_engine, class_=AsyncSession, expire_on_commit=False
)


@asynccontextmanager
async def _noop_lifespan(app):
    """Replace the real lifespan (Whisper, ONNX, Redis, DB bootstrap)
    with a no-op so tests boot instantly without external services."""
    app.state.whisper_service = None
    app.state.intent_loader = None
    yield


@pytest_asyncio.fixture
async def real_app_client():
    """httpx client wired to the REAL app from main.py.

    The heavy lifespan is replaced with a no-op, and the DB dependency
    is overridden to use an in-memory SQLite engine.
    """
    # Create tables on our in-memory engine
    async with _smoke_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.main import app
    from app.core.database import get_db

    # Swap lifespan so we don't need Whisper / ONNX / Redis / Postgres
    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _noop_lifespan

    # Override DB dependency (same function object used by all endpoints)
    original_overrides = dict(app.dependency_overrides)

    async def _override_get_db():
        async with _SmokeSession() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client
    finally:
        # Restore original state on the module-level singleton
        app.router.lifespan_context = original_lifespan
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

        async with _smoke_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


# ===================================================================
# Route wiring tests
# ===================================================================


class TestRouteWiring:
    """Verify the REAL router mounting order is correct."""

    @pytest.mark.asyncio
    async def test_login_accessible_without_jwt(self, real_app_client):
        """POST /api/v1/auth/login must NOT sit behind the JWT guard.

        Regression: auth router was inside api_router which applied
        Depends(require_jwt_token) to all children -> login returned 401.
        """
        resp = await real_app_client.post(
            "/api/v1/auth/login",
            data={"username": "nobody@test.com", "password": "wrong"},
        )
        # 400 = bad creds (correct).  401 with "bearer" = BUG.
        assert resp.status_code != 401 or "bearer" not in resp.json().get(
            "detail", ""
        ).lower(), "Login endpoint is behind JWT guard — auth router mounted incorrectly"

    @pytest.mark.asyncio
    async def test_refresh_accessible_without_jwt(self, real_app_client):
        """POST /api/v1/auth/refresh must NOT require a bearer token."""
        resp = await real_app_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid.token.here"},
        )
        assert resp.status_code != 401 or "bearer" not in resp.json().get(
            "detail", ""
        ).lower(), "Refresh endpoint is behind JWT guard"

    @pytest.mark.asyncio
    async def test_calls_live_not_caught_by_call_id(self, real_app_client):
        """GET /api/v1/calls/live must NOT match /{call_id} with 'live'.

        Regression: dashboard_router was mounted AFTER api_router so
        /api/v1/calls/live hit the /{call_id} path -> 422 UUID parse error.
        """
        resp = await real_app_client.get("/api/v1/calls/live")
        # 401 = no auth (correct).  422 = UUID parse error = BUG.
        assert resp.status_code != 422, (
            "/api/v1/calls/live matched by /{call_id} — route conflict"
        )

    @pytest.mark.asyncio
    async def test_dashboard_redirects_to_login(self, real_app_client):
        """GET /dashboard without auth cookie -> 302 to /dashboard/login."""
        resp = await real_app_client.get(
            "/dashboard", follow_redirects=False
        )
        assert resp.status_code in (302, 307)
        assert "/dashboard/login" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_dashboard_login_page_exists(self, real_app_client):
        """GET /dashboard/login returns 200 with HTML."""
        resp = await real_app_client.get("/dashboard/login")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_health_endpoint(self, real_app_client):
        """GET /health returns 200 with a status field."""
        resp = await real_app_client.get("/health")
        assert resp.status_code == 200
        assert "status" in resp.json()

    @pytest.mark.asyncio
    async def test_protected_calls_require_jwt(self, real_app_client):
        """GET /api/v1/calls without a token must return 401 or 403."""
        resp = await real_app_client.get("/api/v1/calls/")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_docs_available_in_dev_mode(self, real_app_client):
        """GET /docs returns 200 in development mode (ENABLE_DOCS=true)."""
        resp = await real_app_client.get("/docs")
        assert resp.status_code == 200


# ===================================================================
# Security header tests
# ===================================================================


class TestSecurityHeaders:
    """Verify SecurityHeadersMiddleware is wired on the REAL app."""

    @pytest.mark.asyncio
    async def test_owasp_headers_present(self, real_app_client):
        """Every response must include OWASP-recommended headers."""
        resp = await real_app_client.get("/health")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"
        assert (
            resp.headers["Referrer-Policy"]
            == "strict-origin-when-cross-origin"
        )
        assert "camera=()" in resp.headers["Permissions-Policy"]

    @pytest.mark.asyncio
    async def test_csp_allows_required_cdns(self, real_app_client):
        """CSP must allowlist Tailwind (dashboard) AND jsdelivr (Swagger).

        Regression: CSP only listed cdn.tailwindcss.com — Swagger UI
        (served from cdn.jsdelivr.net) was blocked by the browser.
        """
        csp = (await real_app_client.get("/health")).headers[
            "Content-Security-Policy"
        ]
        assert "cdn.tailwindcss.com" in csp, "CSP missing Tailwind CDN"
        assert "cdn.jsdelivr.net" in csp, "CSP missing jsdelivr CDN (Swagger)"

    @pytest.mark.asyncio
    async def test_csp_allows_websockets(self, real_app_client):
        """CSP connect-src must allow ws:/wss: for dashboard WebSocket."""
        csp = (await real_app_client.get("/health")).headers[
            "Content-Security-Policy"
        ]
        assert "ws:" in csp
        assert "wss:" in csp

    @pytest.mark.asyncio
    async def test_csp_blocks_framing(self, real_app_client):
        """CSP must include frame-ancestors 'none' (clickjacking)."""
        csp = (await real_app_client.get("/health")).headers[
            "Content-Security-Policy"
        ]
        assert "frame-ancestors 'none'" in csp
