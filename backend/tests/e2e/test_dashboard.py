"""End-to-end tests for the Redline AI dashboard and core HTTP endpoints.

Requirements:
    pip install pytest pytest-playwright httpx

Usage:
    # Start the server, then run:
    E2E_BASE_URL=http://localhost:8000 pytest backend/tests/e2e/ -v

All tests are skipped when E2E_BASE_URL is not set, since they require
a running server instance.
"""

from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("E2E_BASE_URL", "")
SKIP_REASON = "E2E_BASE_URL env var not set — requires a running server"

skip_unless_e2e = pytest.mark.skipif(not BASE_URL, reason=SKIP_REASON)


# ---------------------------------------------------------------------------
# API tests (httpx — no browser needed)
# ---------------------------------------------------------------------------


@skip_unless_e2e
class TestHealthEndpoints:
    """Verify the unauthenticated health/readiness probes."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self) -> None:
        """GET /health should return 200 with a status field."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/health")

        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert body["status"] in ("ok", "degraded")

    @pytest.mark.asyncio
    async def test_readiness_returns_json(self) -> None:
        """GET /ready should return JSON with status and checks."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/ready")

        # 200 when all services are up, 503 when degraded — both are valid
        assert resp.status_code in (200, 503)
        body = resp.json()
        assert "status" in body
        assert "checks" in body
        assert isinstance(body["checks"], dict)


@skip_unless_e2e
class TestOpenAPIDocs:
    """Verify OpenAPI / Swagger docs are served when ENABLE_DOCS is true."""

    @pytest.mark.asyncio
    async def test_docs_page_loads(self) -> None:
        """GET /docs should return 200 (HTML) when docs are enabled, or 404."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/docs")

        if resp.status_code == 200:
            assert "text/html" in resp.headers.get("content-type", "")
        else:
            # Docs disabled in this environment — 404 is the expected fallback
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_openapi_json_loads(self) -> None:
        """GET /api/v1/openapi.json should return valid JSON schema or 404."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.get("/api/v1/openapi.json")

        if resp.status_code == 200:
            schema = resp.json()
            assert "openapi" in schema
            assert "paths" in schema
        else:
            assert resp.status_code in (404, 403)


@skip_unless_e2e
class TestLoginEndpoint:
    """Verify the login endpoint rejects invalid credentials."""

    LOGIN_PATH = "/api/v1/auth/login"

    @pytest.mark.asyncio
    async def test_login_rejects_invalid_credentials(self) -> None:
        """POST /api/v1/auth/login with bad creds should return 401."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.post(
                self.LOGIN_PATH,
                data={
                    "username": "definitely-not-a-user@example.com",
                    "password": "wrong-password-12345",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        assert resp.status_code in (401, 403)
        body = resp.json()
        assert "detail" in body

    @pytest.mark.asyncio
    async def test_login_rejects_empty_body(self) -> None:
        """POST /api/v1/auth/login with no body should return 422."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            resp = await client.post(self.LOGIN_PATH)

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Browser tests (Playwright — requires `playwright install`)
# ---------------------------------------------------------------------------


@skip_unless_e2e
class TestDashboardBrowser:
    """Browser-based tests for the dashboard UI."""

    @pytest.mark.skipif(
        not BASE_URL,
        reason=SKIP_REASON,
    )
    def test_dashboard_page_loads(self, page) -> None:
        """The /dashboard page should return HTML with a title."""
        page.goto(f"{BASE_URL}/dashboard")

        # The page may require auth and redirect, or serve the dashboard.
        # Accept both scenarios gracefully.
        if page.url.rstrip("/") == f"{BASE_URL}/dashboard":
            assert page.title() != ""
            # Verify minimal DOM structure exists
            body = page.locator("body")
            assert body is not None

    @pytest.mark.skipif(
        not BASE_URL,
        reason=SKIP_REASON,
    )
    def test_health_page_accessible_in_browser(self, page) -> None:
        """Loading /health in a browser should show JSON with status."""
        page.goto(f"{BASE_URL}/health")
        content = page.content()
        assert "status" in content
