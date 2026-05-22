import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("redline_ai")


class MLClient:
    """Client for communicating with the external ML analysis service."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.ML_SERVICE_URL
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def analyze(self, call_id: str, transcript: str, language: str) -> dict:
        url = f"{self.base_url.rstrip('/')}/analyze"
        payload = {"call_id": call_id, "transcript": transcript, "language": language}
        client = await self._get_client()
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("ML service call failed: %s", e)
            raise
