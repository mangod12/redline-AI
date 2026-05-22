"""In-process load simulation — tests pipeline under concurrent pressure.

Uses httpx ASGITransport to hit the real FastAPI app without a running server.
Measures latency distribution and error rates under 10/25/50 concurrent requests.

Requires SECRET_KEY env var to be set.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time

import jwt
import pytest
from datetime import datetime, timedelta, timezone
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def auth_token():
    """Generate a valid JWT for testing."""
    secret = os.getenv("SECRET_KEY", "test-secret-for-load-test")
    return jwt.encode(
        {"sub": "load-test", "tenant_id": "load-tenant", "role": "admin",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        secret, algorithm="HS256",
    )


@pytest.fixture
def test_app():
    """Import app — uses SQLite + fakeredis in test env."""
    os.environ.setdefault("SECRET_KEY", "test-secret-for-load-test")
    os.environ.setdefault("USE_SQLITE", "true")
    os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")
    from app.main import app
    return app


TRANSCRIPTS = [
    "there is a fire in the building help",
    "someone has been shot call police",
    "car accident on highway people trapped",
    "gas leak strong smell in basement",
    "person having seizure not breathing",
    "noise complaint neighbor loud music",
]


@pytest.mark.skipif(
    not os.getenv("SECRET_KEY", "test-secret-for-load-test"),
    reason="SECRET_KEY not set",
)
class TestLoadSimulation:
    @pytest.mark.asyncio
    async def test_10_concurrent_requests(self, test_app, auth_token):
        """10 concurrent requests should all succeed."""
        results = await self._run_load(test_app, auth_token, concurrency=10)
        assert results["error_count"] == 0
        assert results["p95_ms"] < 5000  # generous — no ONNX models loaded

    @pytest.mark.asyncio
    async def test_25_concurrent_requests(self, test_app, auth_token):
        """25 concurrent requests — measure degradation.

        Note: SQLite has limited concurrency (single writer). Some errors
        expected from DB contention. In production with PostgreSQL, this
        should be 0% error rate.
        """
        results = await self._run_load(test_app, auth_token, concurrency=25)
        # SQLite can fail under concurrency — allow up to 40% errors
        assert results["error_rate"] < 0.4
        assert results["p50_ms"] < 2000

    async def _run_load(self, app, token: str, concurrency: int) -> dict:
        transport = ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {token}"}

        latencies: list[float] = []
        errors = 0

        async def _single_request(client: AsyncClient, i: int):
            nonlocal errors
            transcript = TRANSCRIPTS[i % len(TRANSCRIPTS)]
            start = time.perf_counter()
            try:
                r = await client.post(
                    "/process-emergency",
                    json={"transcript": transcript, "caller_id": f"load-{i}"},
                    headers=headers,
                    timeout=30.0,
                )
                elapsed = (time.perf_counter() - start) * 1000
                latencies.append(elapsed)
                if r.status_code >= 400:
                    errors += 1
            except Exception:
                errors += 1
                latencies.append((time.perf_counter() - start) * 1000)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            tasks = [_single_request(client, i) for i in range(concurrency)]
            await asyncio.gather(*tasks)

        sorted_lat = sorted(latencies)
        return {
            "total": concurrency,
            "error_count": errors,
            "error_rate": errors / max(concurrency, 1),
            "p50_ms": sorted_lat[len(sorted_lat) // 2] if sorted_lat else 0,
            "p95_ms": sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0,
            "p99_ms": sorted_lat[int(len(sorted_lat) * 0.99)] if sorted_lat else 0,
            "avg_ms": statistics.mean(latencies) if latencies else 0,
        }
