"""Cloud E2E tests — validate the live deployment via httpx + Playwright.

Run:
    CLOUD_URL=https://redline-ai-359883234654.us-central1.run.app pytest tests/e2e/test_cloud.py -v
"""

import os
import time

import httpx
import pytest

CLOUD_URL = os.getenv(
    "CLOUD_URL", "https://redline-ai-359883234654.us-central1.run.app"
)

skip_no_url = pytest.mark.skipif(not CLOUD_URL, reason="CLOUD_URL not set")


@pytest.fixture
def client():
    with httpx.Client(base_url=CLOUD_URL, timeout=30.0) as c:
        yield c


# ---------------------------------------------------------------------------
# Health & Readiness (unauthenticated)
# ---------------------------------------------------------------------------


@skip_no_url
class TestCloudHealth:
    def test_health_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] in ("ok", "degraded")

    def test_ready_returns_json(self, client):
        r = client.get("/ready")
        assert r.status_code in (200, 503)
        d = r.json()
        assert "status" in d
        assert "checks" in d
        checks = d["checks"]
        for key in ("database", "redis", "whisper", "intent_model", "emotion_model"):
            assert key in checks, f"Missing check: {key}"

    def test_whisper_loaded(self, client):
        r = client.get("/ready")
        d = r.json()
        assert d["checks"]["whisper"] is True, "Whisper STT not loaded"

    def test_redis_connected(self, client):
        r = client.get("/ready")
        d = r.json()
        assert d["checks"]["redis"] is True, "Redis not connected"


# ---------------------------------------------------------------------------
# Docs endpoint
# ---------------------------------------------------------------------------


@skip_no_url
class TestCloudDocs:
    def test_docs_page_loads(self, client):
        r = client.get("/docs")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_openapi_json(self, client):
        r = client.get("/api/v1/openapi.json")
        if r.status_code == 200:
            schema = r.json()
            assert "openapi" in schema
            assert "paths" in schema


# ---------------------------------------------------------------------------
# Dashboard (public, no auth)
# ---------------------------------------------------------------------------


@skip_no_url
class TestCloudDashboard:
    def test_dashboard_returns_html(self, client):
        r = client.get("/dashboard")
        assert r.status_code == 200
        assert b"Dispatch Dashboard" in r.content or b"Redline" in r.content

    def test_dashboard_has_tailwind(self, client):
        r = client.get("/dashboard")
        assert b"tailwindcss" in r.content

    def test_dashboard_has_websocket_js(self, client):
        r = client.get("/dashboard")
        assert b"WebSocket" in r.content or b"websocket" in r.content


# ---------------------------------------------------------------------------
# Auth endpoint (no valid creds needed — just verify shape)
# ---------------------------------------------------------------------------


@skip_no_url
class TestCloudAuth:
    def test_login_rejects_bad_creds(self, client):
        r = client.post(
            "/api/v1/auth/login",
            data={"username": "fake@example.com", "password": "wrong"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code in (401, 403, 422)

    def test_login_rejects_empty(self, client):
        r = client.post("/api/v1/auth/login")
        # JWT middleware may reject before validation — 401 or 422 both valid
        assert r.status_code in (401, 422)


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


@skip_no_url
class TestCloudSecurityHeaders:
    def test_has_security_headers(self, client):
        r = client.get("/health")
        headers = r.headers
        assert "x-content-type-options" in headers
        assert headers["x-content-type-options"] == "nosniff"

    def test_has_request_id(self, client):
        r = client.get("/health")
        assert "x-request-id" in r.headers
        # Should be UUID format
        rid = r.headers["x-request-id"]
        assert len(rid) >= 32


# ---------------------------------------------------------------------------
# Pipeline (requires auth — test 401 without token)
# ---------------------------------------------------------------------------


@skip_no_url
class TestCloudPipelineAuth:
    def test_emergency_requires_auth(self, client):
        # Emergency router is mounted at root, not under /api/v1
        r = client.post(
            "/process-emergency",
            json={"transcript": "fire in building"},
        )
        # 401/403 = auth required, 405 = route matched but wrong method guard
        assert r.status_code in (401, 403, 405)

    def test_calls_requires_auth(self, client):
        r = client.get("/api/v1/calls/")
        assert r.status_code in (401, 403)

    def test_calls_by_id_requires_auth(self, client):
        r = client.get("/api/v1/calls/00000000-0000-0000-0000-000000000000")
        assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Playwright Browser Tests
# ---------------------------------------------------------------------------

try:
    from playwright.sync_api import sync_playwright

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


@pytest.mark.skipif(
    not HAS_PLAYWRIGHT or not CLOUD_URL,
    reason="Playwright or CLOUD_URL not available",
)
class TestCloudBrowser:
    """Browser-based E2E tests against live Cloud Run deployment."""

    def _launch(self, p):
        return p.chromium.launch(headless=True)

    def test_dashboard_renders(self):
        with sync_playwright() as p:
            browser = self._launch(p)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{CLOUD_URL}/dashboard")
            page.wait_for_load_state("networkidle")

            # Title
            assert "Dashboard" in page.title() or "Redline" in page.title()

            # Stats cards
            assert page.locator("#stat-total").count() > 0
            assert page.locator("#stat-critical").count() > 0

            # Table exists
            assert page.locator("table").count() > 0

            browser.close()

    def test_dashboard_websocket_indicator(self):
        with sync_playwright() as p:
            browser = self._launch(p)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{CLOUD_URL}/dashboard")
            page.wait_for_load_state("networkidle")

            # Connection indicator exists
            indicator = page.locator("#conn-indicator")
            assert indicator.count() > 0

            # Label exists
            label = page.locator("#conn-label")
            assert label.count() > 0

            browser.close()

    def test_dashboard_responsive_mobile(self):
        with sync_playwright() as p:
            browser = self._launch(p)
            page = browser.new_page(viewport={"width": 375, "height": 812})
            page.goto(f"{CLOUD_URL}/dashboard")
            page.wait_for_load_state("networkidle")

            # Should still render without errors
            assert page.locator("body").count() > 0
            assert page.locator("#stat-total").count() > 0

            browser.close()

    def test_health_json_in_browser(self):
        with sync_playwright() as p:
            browser = self._launch(p)
            page = browser.new_page()
            page.goto(f"{CLOUD_URL}/health")
            content = page.content()
            assert "status" in content

            browser.close()

    def test_docs_swagger_ui(self):
        with sync_playwright() as p:
            browser = self._launch(p)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{CLOUD_URL}/docs")
            page.wait_for_load_state("networkidle")

            # Swagger UI should load
            assert "Swagger" in page.title() or "Redline" in page.title()

            browser.close()

    def test_dashboard_screenshot(self, tmp_path):
        with sync_playwright() as p:
            browser = self._launch(p)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{CLOUD_URL}/dashboard")
            page.wait_for_load_state("networkidle")
            time.sleep(1)

            screenshot_path = tmp_path / "dashboard.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            assert screenshot_path.exists()
            assert screenshot_path.stat().st_size > 5000  # Non-trivial screenshot

            browser.close()

    def test_docs_screenshot(self, tmp_path):
        with sync_playwright() as p:
            browser = self._launch(p)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{CLOUD_URL}/docs")
            page.wait_for_load_state("networkidle")
            time.sleep(1)

            screenshot_path = tmp_path / "docs.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            assert screenshot_path.exists()

            browser.close()

    def test_no_console_errors(self):
        with sync_playwright() as p:
            browser = self._launch(p)
            page = browser.new_page(viewport={"width": 1440, "height": 900})

            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))

            page.goto(f"{CLOUD_URL}/dashboard")
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # Filter out WebSocket connection errors (expected if WS not configured)
            real_errors = [
                e for e in errors if "WebSocket" not in e and "ws://" not in e
            ]
            assert len(real_errors) == 0, f"Console errors: {real_errors}"

            browser.close()

    def test_network_no_failed_resources(self):
        with sync_playwright() as p:
            browser = self._launch(p)
            page = browser.new_page(viewport={"width": 1440, "height": 900})

            failed = []
            page.on(
                "requestfailed",
                lambda req: failed.append(f"{req.method} {req.url} -> {req.failure}"),
            )

            page.goto(f"{CLOUD_URL}/dashboard")
            page.wait_for_load_state("networkidle")
            time.sleep(1)

            # Filter out WebSocket failures and CDN/CSP blocks (expected in strict CSP)
            real_failures = [
                f for f in failed
                if "ws://" not in f and "wss://" not in f
                and "cdn.tailwindcss.com" not in f
            ]
            assert len(real_failures) == 0, f"Failed requests: {real_failures}"

            browser.close()
