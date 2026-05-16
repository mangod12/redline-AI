import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("redline_ai.geocoder")

class Geocoder:
    """Geocoding service using OpenStreetMap/Nominatim (Free/Open Source)."""

    def __init__(self):
        self.base_url = settings.GEOCODER_BASE_URL
        self.headers = {
            "User-Agent": "RedlineAI-StudentProject (contact@example.com)"
        }
        self._client = httpx.AsyncClient(headers=self.headers, timeout=5.0)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def geocode(self, text: str) -> dict:
        """Geocode text using Nominatim.

        Note: Following Nominatim's policy - max 1 request/second.
        """
        if not text:
            return {"latitude": 0.0, "longitude": 0.0, "confidence": 0.0, "query": text}

        params = {
            "q": text,
            "format": "json",
            "limit": 1
        }

        try:
            response = await self._client.get(
                self.base_url,
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            if data:
                result = data[0]
                return {
                    "latitude": float(result["lat"]),
                    "longitude": float(result["lon"]),
                    "confidence": 1.0 if result.get("importance", 0) > 0.5 else 0.7,
                    "query": text,
                    "display_name": result.get("display_name")
                }
        except Exception as e:
            logger.error(f"Geocoding error for '{text}': {e}")

        return {
            "latitude": 0.0,
            "longitude": 0.0,
            "confidence": 0.0,
            "query": text
        }
