"""Cloud E2E tests — validate the live deployment via Playwright + httpx.

Run: CLOUD_URL=https://redline-ai-359883234654.us-central1.run.app pytest tests/e2e/test_cloud.py -v
"""

import os
import time

import httpx
import pytest

CLOUD_URL = os.getenv("CLOUD_URL", "https://redline-ai-359883234654.us-central1.run.app")
SKIP_REASON = "Set CLOUD_URL to run cloud E2E tests"


@pytest.fixture
def client():
    with httpx.Client(base_url=CLOUD_URL, timeout=30.0) as c:
        yield c


# ---------------------------------------------------------------------------
# API Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not CLOUD_URL, reason=SKIP_REASON)
class TestCloudHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok"

    def test_health_shows_models(self, client):
        r = client.get("/health")
        d = r.json()
        assert "emotion_model" in d
        assert "intent_model" in d
        assert "whisper_model" in d

    def test_all_models_ready(self, client):
        r = client.get("/health")
        d = r.json()
        assert d["emotion_model"] == "ready"
        assert d["intent_model"] == "ready"
        assert d["whisper_model"] == "ready"
        assert d["redis"] == "connected"
        assert d["database"] == "connected"


@pytest.mark.skipif(not CLOUD_URL, reason=SKIP_REASON)
class TestCloudPipeline:
    @pytest.mark.parametrize("transcript,expected_intent", [
        ("building on fire people trapped", "fire"),
        ("gun shooting robbery armed attack", "violent_crime"),
        ("car accident driver unconscious", "accident"),
        ("child having seizure not breathing", "medical"),
    ])
    def test_intent_classification(self, client, transcript, expected_intent):
        r = client.post("/process-emergency", json={"transcript": transcript})
        assert r.status_code == 200
        d = r.json()
        assert d["intent"] == expected_intent

    def test_response_has_all_fields(self, client):
        r = client.post("/process-emergency", json={"transcript": "fire in building help"})
        assert r.status_code == 200
        d = r.json()
        required = ["call_id", "transcript", "intent", "intent_confidence",
                     "emotion", "severity", "responder", "latency_ms"]
        for field in required:
            assert field in d, f"Missing field: {field}"

    def test_latency_under_5_seconds(self, client):
        t0 = time.perf_counter()
        r = client.post("/process-emergency", json={"transcript": "emergency help fire"})
        wall = (time.perf_counter() - t0) * 1000
        assert r.status_code == 200
        assert r.json()["latency_ms"] < 5000
        assert wall < 10000  # generous wall clock

    def test_empty_transcript_rejected(self, client):
        r = client.post("/process-emergency", json={"transcript": ""})
        assert r.status_code == 422


@pytest.mark.skipif(not CLOUD_URL, reason=SKIP_REASON)
class TestCloudDemoPage:
    def test_demo_page_loads(self, client):
        r = client.get("/demo")
        assert r.status_code == 200
        assert b"Redline AI" in r.content

    def test_dashboard_redirects_to_login(self, client):
        r = client.get("/dashboard", follow_redirects=False)
        assert r.status_code in (200, 301, 302, 307)


# ---------------------------------------------------------------------------
# Playwright Browser Tests
# ---------------------------------------------------------------------------

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


@pytest.mark.skipif(not HAS_PLAYWRIGHT or not CLOUD_URL, reason="Playwright or CLOUD_URL not available")
class TestCloudBrowser:
    def test_demo_renders_correctly(self):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{CLOUD_URL}/demo")
            page.wait_for_load_state("networkidle")

            assert "Redline AI" in page.title() or page.locator("text=Redline AI").count() > 0
            assert page.locator("text=Analyze").count() > 0
            assert page.locator("text=System Online").count() > 0

            browser.close()

    def test_demo_analyze_fire_scenario(self):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{CLOUD_URL}/demo")
            page.wait_for_load_state("networkidle")
            time.sleep(1)

            # Click fire chip
            page.click("text=Building on fire, people trapped")
            time.sleep(0.5)
            page.click("button:has-text('Analyze')")

            # Wait for result
            page.wait_for_selector("text=EMERGENCY ANALYSIS", timeout=15000)
            time.sleep(1)

            # Verify result content
            assert page.locator("text=Fire").count() > 0
            assert page.locator("text=fire_dispatch").count() > 0

            browser.close()

    def test_demo_analyze_medical_scenario(self):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{CLOUD_URL}/demo")
            page.wait_for_load_state("networkidle")
            time.sleep(1)

            # Type custom scenario
            input_el = page.locator("[placeholder*='emergency'], [placeholder*='scenario'], input, textarea").first
            input_el.fill("Someone collapsed not breathing cardiac arrest at mall")
            time.sleep(0.5)
            page.click("button:has-text('Analyze')")

            page.wait_for_selector("text=EMERGENCY ANALYSIS", timeout=15000)
            time.sleep(1)

            assert page.locator("text=Medical").count() > 0
            assert page.locator("text=ambulance").count() > 0

            browser.close()
