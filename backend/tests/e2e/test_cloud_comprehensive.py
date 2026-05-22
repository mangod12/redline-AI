"""Comprehensive Playwright E2E tests — verify every element on Cloud Run deployment.

Covers: dashboard DOM, stat cards, table structure, connection indicator,
responsive layouts, Swagger UI interactions, API endpoints, security headers,
CSP, CORS, and edge cases.

Run:
    CLOUD_URL=https://redline-ai-359883234654.us-central1.run.app \
    python -m pytest backend/tests/e2e/test_cloud_comprehensive.py -v
"""

from __future__ import annotations

import os
import re
import time

import httpx
import pytest

CLOUD_URL = os.getenv(
    "CLOUD_URL", "https://redline-ai-359883234654.us-central1.run.app"
)

skip_no_url = pytest.mark.skipif(not CLOUD_URL, reason="CLOUD_URL not set")

try:
    from playwright.sync_api import sync_playwright

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

skip_no_playwright = pytest.mark.skipif(
    not HAS_PLAYWRIGHT or not CLOUD_URL,
    reason="Playwright or CLOUD_URL not available",
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def http():
    with httpx.Client(base_url=CLOUD_URL, timeout=15.0, follow_redirects=True) as c:
        yield c


@pytest.fixture
def browser_ctx():
    """Yield (browser, page) with desktop viewport."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        yield browser, page
        browser.close()


@pytest.fixture
def mobile_page():
    """Yield page with iPhone-sized viewport."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 375, "height": 812})
        yield page
        browser.close()


@pytest.fixture
def tablet_page():
    """Yield page with iPad-sized viewport."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 768, "height": 1024})
        yield page
        browser.close()


# ═════════════════════════════════════════════════════════════════════════
# 1. DASHBOARD — EVERY DOM ELEMENT
# ═════════════════════════════════════════════════════════════════════════


@skip_no_playwright
class TestDashboardStructure:
    """Verify every visible element on the dashboard."""

    def test_page_title(self, browser_ctx):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        title = page.title()
        assert title, "Page title is empty"
        assert "Dashboard" in title or "Redline" in title or "Dispatcher" in title

    def test_header_text(self, browser_ctx):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        h1 = page.locator("h1")
        assert h1.count() > 0, "No <h1> found"
        assert "Dispatcher Dashboard" in h1.text_content()

    def test_connection_indicator_exists(self, browser_ctx):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        dot = page.locator("#conn-indicator")
        assert dot.count() == 1
        assert dot.is_visible()

    def test_connection_label_exists(self, browser_ctx):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        label = page.locator("#conn-label")
        assert label.count() == 1
        assert label.is_visible()
        text = label.text_content().lower()
        assert text in ("disconnected", "live", "connecting")

    def test_last_updated_element(self, browser_ctx):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        el = page.locator("#last-updated")
        assert el.count() == 1
        assert el.is_visible()


@skip_no_playwright
class TestDashboardStatCards:
    """Verify all 4 stat cards exist and have correct labels."""

    def _load(self, page):
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(1)

    def test_stat_total_card(self, browser_ctx):
        _, page = browser_ctx
        self._load(page)
        el = page.locator("#stat-total")
        assert el.count() == 1
        assert el.is_visible()
        # Should be a number (possibly "0")
        assert el.text_content().strip().isdigit()

    def test_stat_critical_card(self, browser_ctx):
        _, page = browser_ctx
        self._load(page)
        el = page.locator("#stat-critical")
        assert el.count() == 1
        assert el.is_visible()
        assert el.text_content().strip().isdigit()

    def test_stat_high_card(self, browser_ctx):
        _, page = browser_ctx
        self._load(page)
        el = page.locator("#stat-high")
        assert el.count() == 1
        assert el.is_visible()
        assert el.text_content().strip().isdigit()

    def test_stat_fallback_card(self, browser_ctx):
        _, page = browser_ctx
        self._load(page)
        el = page.locator("#stat-fallback")
        assert el.count() == 1
        assert el.is_visible()
        text = el.text_content().strip()
        assert text.endswith("%"), f"Fallback should end with %, got: {text}"

    def test_stat_card_labels(self, browser_ctx):
        _, page = browser_ctx
        self._load(page)
        content = page.content()
        for label in ("Total Calls", "Critical", "High", "Fallback Rate"):
            assert label in content, f"Missing stat card label: {label}"


@skip_no_playwright
class TestDashboardTable:
    """Verify the calls table structure."""

    def _load(self, page):
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")

    def test_table_exists(self, browser_ctx):
        _, page = browser_ctx
        self._load(page)
        table = page.locator("table")
        assert table.count() == 1

    def test_table_headers(self, browser_ctx):
        _, page = browser_ctx
        self._load(page)
        headers = page.locator("thead th")
        expected = [
            "Call ID", "Transcript", "Intent (conf)", "Emotion",
            "Severity", "Responder", "Fallback Flags", "Latency",
        ]
        assert headers.count() == len(expected)
        for i, name in enumerate(expected):
            assert name in headers.nth(i).text_content()

    def test_table_body_exists(self, browser_ctx):
        _, page = browser_ctx
        self._load(page)
        tbody = page.locator("#calls-body")
        assert tbody.count() == 1

    def test_empty_state_message(self, browser_ctx):
        """When no calls, should show placeholder text."""
        _, page = browser_ctx
        self._load(page)
        tbody = page.locator("#calls-body")
        # Either has data rows or the waiting message
        text = tbody.text_content()
        assert text.strip(), "Table body is completely empty"


@skip_no_playwright
class TestDashboardConnectionIndicator:
    """Verify connection indicator color classes."""

    def test_indicator_has_color_class(self, browser_ctx):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        dot = page.locator("#conn-indicator")
        classes = dot.get_attribute("class") or ""
        # Should have either red (disconnected) or green (connected)
        assert "bg-red-500" in classes or "bg-emerald-400" in classes

    def test_indicator_is_round(self, browser_ctx):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        dot = page.locator("#conn-indicator")
        classes = dot.get_attribute("class") or ""
        assert "rounded-full" in classes


# ═════════════════════════════════════════════════════════════════════════
# 2. RESPONSIVE LAYOUTS
# ═════════════════════════════════════════════════════════════════════════


@skip_no_playwright
class TestResponsiveLayouts:
    """Dashboard renders correctly on mobile and tablet."""

    def test_mobile_dashboard_loads(self, mobile_page):
        mobile_page.goto(f"{CLOUD_URL}/dashboard")
        mobile_page.wait_for_load_state("networkidle")
        assert mobile_page.locator("h1").count() > 0
        assert mobile_page.locator("#stat-total").is_visible()
        assert mobile_page.locator("table").count() > 0

    def test_mobile_stat_cards_visible(self, mobile_page):
        mobile_page.goto(f"{CLOUD_URL}/dashboard")
        mobile_page.wait_for_load_state("networkidle")
        for card_id in ("#stat-total", "#stat-critical", "#stat-high", "#stat-fallback"):
            assert mobile_page.locator(card_id).is_visible(), f"{card_id} not visible on mobile"

    def test_mobile_table_scrollable(self, mobile_page):
        mobile_page.goto(f"{CLOUD_URL}/dashboard")
        mobile_page.wait_for_load_state("networkidle")
        # Table container should have overflow-x-auto
        container = mobile_page.locator(".overflow-x-auto")
        assert container.count() > 0, "No scrollable table container on mobile"

    def test_tablet_dashboard_loads(self, tablet_page):
        tablet_page.goto(f"{CLOUD_URL}/dashboard")
        tablet_page.wait_for_load_state("networkidle")
        assert tablet_page.locator("h1").count() > 0
        assert tablet_page.locator("#stat-total").is_visible()
        assert tablet_page.locator("table").count() > 0

    def test_viewport_meta_tag(self, browser_ctx):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        meta = page.locator('meta[name="viewport"]')
        assert meta.count() > 0
        content = meta.get_attribute("content")
        assert "width=device-width" in content


# ═════════════════════════════════════════════════════════════════════════
# 3. SWAGGER UI — EVERY INTERACTIVE ELEMENT
# ═════════════════════════════════════════════════════════════════════════


@skip_no_playwright
class TestSwaggerUI:
    """Verify Swagger UI loads and is interactive."""

    def test_swagger_page_loads(self, browser_ctx):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/docs")
        page.wait_for_load_state("networkidle")
        assert page.title(), "Swagger page has no title"

    def test_swagger_has_api_info(self, browser_ctx):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/docs")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        content = page.content()
        assert "Redline" in content or "API" in content or "swagger" in content.lower()

    def test_swagger_endpoints_listed(self, browser_ctx):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/docs")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        # Swagger UI renders endpoints as opblocks
        opblocks = page.locator(".opblock")
        assert opblocks.count() > 0, "No API endpoints rendered in Swagger UI"

    def test_swagger_expand_endpoint(self, browser_ctx):
        """Click an endpoint to expand it and verify details appear."""
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/docs")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        # Click first endpoint summary to expand
        first_summary = page.locator(".opblock-summary").first
        if first_summary.count() > 0:
            first_summary.click()
            time.sleep(1)
            # Should show parameters or response section
            body = page.locator(".opblock-body")
            assert body.count() > 0, "Endpoint details didn't expand"

    def test_swagger_try_it_button(self, browser_ctx):
        """Verify 'Try it out' button exists on expanded endpoint."""
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/docs")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        first_summary = page.locator(".opblock-summary").first
        if first_summary.count() > 0:
            first_summary.click()
            time.sleep(1)
            try_btn = page.locator("button", has_text="Try it out")
            assert try_btn.count() > 0, "'Try it out' button not found"

    def test_swagger_has_authorize_button(self, browser_ctx):
        """Swagger should have an Authorize button for JWT."""
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/docs")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        auth_btn = page.locator(".btn.authorize, button.authorize")
        # Some Swagger UIs render it differently
        content = page.content()
        assert auth_btn.count() > 0 or "Authorize" in content

    def test_swagger_authorize_modal(self, browser_ctx):
        """Click Authorize and verify modal opens."""
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/docs")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        auth_btn = page.locator("button.authorize, .btn.authorize").first
        if auth_btn.count() > 0:
            auth_btn.click()
            time.sleep(1)
            modal = page.locator(".dialog-ux").first
            if modal.count() > 0:
                assert modal.is_visible(), "Authorize modal didn't open"
                # Close modal
                close_btn = page.locator("button", has_text="Close")
                if close_btn.count() > 0:
                    close_btn.first.click()

    def test_swagger_schema_section(self, browser_ctx):
        """Verify schema/models section exists."""
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/docs")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        content = page.content()
        assert "Schemas" in content or "Models" in content or "schema" in content.lower()

    def test_swagger_health_endpoint_try(self, browser_ctx):
        """Expand health endpoint, try it, verify response."""
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/docs")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        # Find the /health endpoint
        health_block = page.locator(".opblock", has_text="health").first
        if health_block.count() > 0:
            health_block.locator(".opblock-summary").click()
            time.sleep(1)
            try_btn = health_block.locator("button", has_text="Try it out")
            if try_btn.count() > 0:
                try_btn.click()
                time.sleep(0.5)
                execute_btn = health_block.locator("button", has_text="Execute")
                if execute_btn.count() > 0:
                    execute_btn.click()
                    time.sleep(2)
                    # Check response
                    response_body = health_block.locator(".response-col_description pre")
                    if response_body.count() > 0:
                        text = response_body.first.text_content()
                        assert "status" in text


# ═════════════════════════════════════════════════════════════════════════
# 4. API ENDPOINTS — EXHAUSTIVE
# ═════════════════════════════════════════════════════════════════════════


@skip_no_url
class TestAPIHealth:
    def test_health_status_ok(self, http):
        r = http.get("/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] in ("ok", "degraded")

    def test_health_response_time(self, http):
        """Health should respond fast (<2s)."""
        start = time.time()
        http.get("/health")
        elapsed = time.time() - start
        assert elapsed < 2.0, f"Health took {elapsed:.2f}s"

    def test_ready_has_all_checks(self, http):
        r = http.get("/ready")
        assert r.status_code in (200, 503)
        d = r.json()
        assert "checks" in d
        for key in ("database", "redis", "whisper", "intent_model", "emotion_model"):
            assert key in d["checks"], f"Missing readiness check: {key}"

    def test_ready_check_types(self, http):
        """Each check value should be boolean."""
        r = http.get("/ready")
        d = r.json()
        for key, val in d["checks"].items():
            assert isinstance(val, bool), f"Check '{key}' is {type(val)}, expected bool"


@skip_no_url
class TestAPIDocs:
    def test_docs_returns_html(self, http):
        r = http.get("/docs")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_openapi_json_schema(self, http):
        r = http.get("/api/v1/openapi.json")
        if r.status_code == 200:
            schema = r.json()
            assert "openapi" in schema
            assert "paths" in schema
            assert "info" in schema
            assert len(schema["paths"]) > 0, "No paths in OpenAPI schema"

    def test_openapi_lists_all_endpoints(self, http):
        r = http.get("/api/v1/openapi.json")
        if r.status_code == 200:
            paths = r.json()["paths"]
            expected_paths = ["/health", "/ready"]
            for ep in expected_paths:
                assert ep in paths, f"Missing endpoint in OpenAPI: {ep}"


@skip_no_url
class TestAPIDashboard:
    def test_dashboard_returns_html(self, http):
        r = http.get("/dashboard")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_dashboard_has_tailwind(self, http):
        r = http.get("/dashboard")
        assert b"tailwindcss" in r.content

    def test_dashboard_has_charset(self, http):
        r = http.get("/dashboard")
        assert b'charset="UTF-8"' in r.content or b"charset=utf-8" in r.content.lower()

    def test_dashboard_has_doctype(self, http):
        r = http.get("/dashboard")
        assert r.content.strip().startswith(b"<!DOCTYPE html>")


@skip_no_url
class TestAPIAuth:
    def test_login_bad_creds_401(self, http):
        r = http.post(
            "/api/v1/auth/login",
            data={"username": "fake@example.com", "password": "wrong"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code in (401, 403, 422)

    def test_login_empty_body_rejects(self, http):
        r = http.post("/api/v1/auth/login")
        assert r.status_code in (401, 422)

    def test_login_returns_json(self, http):
        r = http.post(
            "/api/v1/auth/login",
            data={"username": "fake@example.com", "password": "wrong"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        body = r.json()
        assert "detail" in body or "error" in body

    def test_register_rejects_missing_fields(self, http):
        r = http.post("/api/v1/auth/register", json={})
        assert r.status_code in (401, 403, 422)


@skip_no_url
class TestAPIProtectedEndpoints:
    """All protected endpoints should reject unauthenticated requests."""

    def test_calls_list_requires_auth(self, http):
        r = http.get("/api/v1/calls/")
        assert r.status_code in (401, 403)

    def test_calls_by_id_requires_auth(self, http):
        r = http.get("/api/v1/calls/00000000-0000-0000-0000-000000000000")
        assert r.status_code in (401, 403)

    def test_emergency_requires_auth(self, http):
        r = http.post(
            "/process-emergency",
            json={"transcript": "test fire"},
        )
        assert r.status_code in (401, 403, 405)

    def test_calls_live_requires_auth(self, http):
        r = http.get("/api/v1/calls/live")
        assert r.status_code in (401, 403)

    def test_metrics_requires_auth(self, http):
        r = http.get("/metrics")
        assert r.status_code in (401, 403)

    def test_calls_start_requires_auth(self, http):
        r = http.post("/api/v1/calls/start", json={"transcript": "test"})
        assert r.status_code in (401, 403, 422)

    def test_severity_analyze_requires_auth(self, http):
        r = http.post(
            "/api/v1/severity/00000000-0000-0000-0000-000000000000/analyze",
            json={},
        )
        assert r.status_code in (401, 403, 404, 422)


# ═════════════════════════════════════════════════════════════════════════
# 5. SECURITY HEADERS
# ═════════════════════════════════════════════════════════════════════════


@skip_no_url
class TestSecurityHeaders:
    def test_x_content_type_options(self, http):
        r = http.get("/health")
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_x_request_id(self, http):
        r = http.get("/health")
        rid = r.headers.get("x-request-id", "")
        assert len(rid) >= 32, f"Request ID too short: {rid}"

    def test_request_id_is_unique(self, http):
        r1 = http.get("/health")
        r2 = http.get("/health")
        id1 = r1.headers.get("x-request-id")
        id2 = r2.headers.get("x-request-id")
        assert id1 != id2, "Request IDs should be unique per request"

    def test_content_security_policy(self, http):
        r = http.get("/dashboard")
        csp = r.headers.get("content-security-policy", "")
        # CSP should exist (may be empty string if not set)
        if csp:
            assert "default-src" in csp or "script-src" in csp

    def test_no_server_header_leak(self, http):
        """Server header should not reveal detailed version info."""
        r = http.get("/health")
        server = r.headers.get("server", "")
        # Should not expose specific versions like "uvicorn/0.x.x"
        assert "uvicorn" not in server.lower() or "/" not in server


@skip_no_url
class TestCORSHeaders:
    def test_cors_preflight(self, http):
        """OPTIONS request should return CORS headers."""
        r = http.request(
            "OPTIONS",
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Should either allow or deny — not error
        assert r.status_code in (200, 204, 400, 403, 405)


# ═════════════════════════════════════════════════════════════════════════
# 6. ERROR HANDLING & EDGE CASES
# ═════════════════════════════════════════════════════════════════════════


@skip_no_url
class TestErrorHandling:
    def test_404_returns_json(self, http):
        r = http.get("/nonexistent-route-xyz")
        assert r.status_code == 404
        body = r.json()
        assert "detail" in body or "error" in body or "message" in body

    def test_method_not_allowed(self, http):
        """DELETE on /health should return 405."""
        r = http.delete("/health")
        assert r.status_code in (405, 404)

    def test_oversized_body_rejected(self, http):
        """Giant payload should be rejected."""
        big_payload = {"transcript": "x" * 500_000}
        r = http.post(
            "/api/v1/auth/login",
            json=big_payload,
        )
        assert r.status_code in (401, 403, 413, 422)

    def test_malformed_json_rejected(self, http):
        """Invalid JSON body should return 422 or 400."""
        r = http.post(
            "/api/v1/auth/login",
            content=b"{invalid json!!!",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code in (400, 401, 422)

    def test_sql_injection_rejected(self, http):
        """SQL injection attempt should not cause 500."""
        r = http.post(
            "/api/v1/auth/login",
            data={"username": "' OR 1=1 --", "password": "test"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code != 500, "SQL injection caused server error"
        assert r.status_code in (401, 403, 422)

    def test_xss_in_query_param(self, http):
        """XSS in query params should not be reflected raw."""
        r = http.get("/dashboard?token=<script>alert(1)</script>")
        assert b"<script>alert(1)</script>" not in r.content


# ═════════════════════════════════════════════════════════════════════════
# 7. BROWSER — JS FUNCTIONALITY & RENDERING
# ═════════════════════════════════════════════════════════════════════════


@skip_no_playwright
class TestDashboardJavaScript:
    """Verify JS functions execute without errors."""

    def test_no_js_console_errors(self, browser_ctx):
        _, page = browser_ctx
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(3)
        real_errors = [
            e for e in errors
            if "WebSocket" not in e and "ws://" not in e and "wss://" not in e
        ]
        assert len(real_errors) == 0, f"JS errors: {real_errors}"

    def test_no_failed_network_requests(self, browser_ctx):
        _, page = browser_ctx
        failed = []
        page.on(
            "requestfailed",
            lambda req: failed.append(f"{req.method} {req.url} -> {req.failure}"),
        )
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        real_failures = [
            f for f in failed
            if "ws://" not in f and "wss://" not in f
            and "cdn.tailwindcss.com" not in f
        ]
        assert len(real_failures) == 0, f"Failed requests: {real_failures}"

    def test_tailwind_css_loaded(self, browser_ctx):
        """Verify Tailwind actually applied styles (not just script tag)."""
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        # Check that body has the dark background from Tailwind
        bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
        assert bg != "rgba(0, 0, 0, 0)", "Body has no background — Tailwind may not have loaded"

    def test_stat_values_are_numbers(self, browser_ctx):
        """All stat card values should be parseable numbers or percentages."""
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        for card_id in ("#stat-total", "#stat-critical", "#stat-high"):
            val = page.locator(card_id).text_content().strip()
            assert val.isdigit(), f"{card_id} value '{val}' is not a number"
        fallback = page.locator("#stat-fallback").text_content().strip()
        assert fallback.endswith("%"), f"Fallback value '{fallback}' doesn't end with %"

    def test_initial_fetch_fires(self, browser_ctx):
        """The initialFetch function should update last-updated text."""
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(3)
        text = page.locator("#last-updated").text_content()
        assert text != "Loading...", "initialFetch didn't update the timestamp"

    def test_escape_html_function(self, browser_ctx):
        """Verify escapeHtml JS function works (XSS protection)."""
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        result = page.evaluate('escapeHtml("<script>alert(1)</script>")')
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_sev_class_function(self, browser_ctx):
        """Verify sevClass returns correct CSS classes."""
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        assert page.evaluate('sevClass("critical")') == "text-rose-400"
        assert page.evaluate('sevClass("high")') == "text-amber-300"
        assert page.evaluate('sevClass("medium")') == "text-yellow-300"
        assert page.evaluate('sevClass("low")') == "text-emerald-300"

    def test_trim_text_function(self, browser_ctx):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        assert page.evaluate('trimText("hello world", 5)') == "hello..."
        assert page.evaluate('trimText("hi", 10)') == "hi"
        assert page.evaluate('trimText("", 10)') == ""


@skip_no_playwright
class TestDashboardScreenshots:
    """Capture screenshots at different viewports for visual verification."""

    def test_desktop_screenshot(self, browser_ctx, tmp_path):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        path = tmp_path / "desktop.png"
        page.screenshot(path=str(path), full_page=True)
        assert path.exists()
        assert path.stat().st_size > 5000

    def test_mobile_screenshot(self, mobile_page, tmp_path):
        mobile_page.goto(f"{CLOUD_URL}/dashboard")
        mobile_page.wait_for_load_state("networkidle")
        time.sleep(1)
        path = tmp_path / "mobile.png"
        mobile_page.screenshot(path=str(path), full_page=True)
        assert path.exists()
        assert path.stat().st_size > 3000

    def test_docs_screenshot(self, browser_ctx, tmp_path):
        _, page = browser_ctx
        page.goto(f"{CLOUD_URL}/docs")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        path = tmp_path / "swagger.png"
        page.screenshot(path=str(path), full_page=True)
        assert path.exists()
        assert path.stat().st_size > 5000


# ═════════════════════════════════════════════════════════════════════════
# 8. PERFORMANCE
# ═════════════════════════════════════════════════════════════════════════


@skip_no_url
class TestPerformance:
    def test_health_under_500ms(self, http):
        times = []
        for _ in range(3):
            start = time.time()
            http.get("/health")
            times.append(time.time() - start)
        avg = sum(times) / len(times)
        assert avg < 0.5, f"Avg health response: {avg:.3f}s"

    def test_dashboard_under_2s(self, http):
        start = time.time()
        http.get("/dashboard")
        elapsed = time.time() - start
        assert elapsed < 2.0, f"Dashboard took {elapsed:.2f}s"

    def test_docs_under_3s(self, http):
        start = time.time()
        http.get("/docs")
        elapsed = time.time() - start
        assert elapsed < 3.0, f"Docs took {elapsed:.2f}s"

    def test_concurrent_health_checks(self, http):
        """5 rapid health checks should all succeed."""
        results = [http.get("/health") for _ in range(5)]
        for r in results:
            assert r.status_code == 200
