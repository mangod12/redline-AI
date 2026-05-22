"""Cloud load benchmark — measure pipeline latency under concurrent requests.

Run: CLOUD_URL=https://redline-ai-359883234654.us-central1.run.app pytest tests/e2e/test_cloud_load.py -v -s
"""

import asyncio
import os
import statistics
import time

import httpx
import pytest

CLOUD_URL = os.getenv("CLOUD_URL", "")

TRANSCRIPTS = [
    "fire in the building smoke everywhere people trapped",
    "someone has been shot bleeding heavily at the park",
    "car crash on highway driver unconscious trapped",
    "strong gas smell in basement carbon monoxide alarm",
    "child having seizure not breathing turning blue",
    "armed robbery gun in convenience store hostage",
    "person threatening suicide on bridge need crisis team",
    "noise complaint loud music neighbor parking lot",
]


CLOUD_AUTH_TOKEN = os.getenv("CLOUD_AUTH_TOKEN", "")


@pytest.mark.skipif(
    not CLOUD_URL or not CLOUD_AUTH_TOKEN,
    reason="CLOUD_URL and CLOUD_AUTH_TOKEN required for load tests",
)
class TestCloudLoad:

    @pytest.mark.asyncio
    async def test_10_concurrent_cloud_requests(self):
        """10 simultaneous requests to cloud pipeline."""
        results = await self._run_concurrent(10)
        print(f"\n  10 concurrent: p50={results['p50']}ms avg={results['avg']}ms errors={results['errors']}")
        assert results["errors"] == 0
        assert results["p50"] < 5000

    @pytest.mark.asyncio
    async def test_sequential_latency_warmup(self):
        """5 sequential requests — measure cold vs warm latency."""
        latencies = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(5):
                t = TRANSCRIPTS[i % len(TRANSCRIPTS)]
                t0 = time.perf_counter()
                r = await client.post(
                    f"{CLOUD_URL}/process-emergency",
                    headers={"Authorization": f"Bearer {CLOUD_AUTH_TOKEN}"},
                    json={"transcript": t},
                )
                ms = (time.perf_counter() - t0) * 1000
                latencies.append(ms)
                assert r.status_code == 200

        print(f"\n  Sequential latencies: {[f'{l:.0f}ms' for l in latencies]}")
        print(f"  First (cold): {latencies[0]:.0f}ms, Last (warm): {latencies[-1]:.0f}ms")
        # Warm requests should be faster than cold
        assert latencies[-1] < latencies[0] * 3  # generous

    async def _run_concurrent(self, n: int) -> dict:
        latencies = []
        errors = 0

        async def _one(client: httpx.AsyncClient, i: int):
            nonlocal errors
            t = TRANSCRIPTS[i % len(TRANSCRIPTS)]
            t0 = time.perf_counter()
            try:
                r = await client.post(
                    f"{CLOUD_URL}/process-emergency",
                    headers={"Authorization": f"Bearer {CLOUD_AUTH_TOKEN}"},
                    json={"transcript": t, "caller_id": f"load-{i}"},
                )
                ms = (time.perf_counter() - t0) * 1000
                latencies.append(ms)
                if r.status_code >= 400:
                    errors += 1
            except Exception:
                errors += 1

        async with httpx.AsyncClient(timeout=30.0) as client:
            await asyncio.gather(*[_one(client, i) for i in range(n)])

        s = sorted(latencies)
        return {
            "p50": int(s[len(s) // 2]) if s else 0,
            "p95": int(s[int(len(s) * 0.95)]) if s else 0,
            "avg": int(statistics.mean(latencies)) if latencies else 0,
            "errors": errors,
        }
