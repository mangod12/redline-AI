import re
import httpx
import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("redline_ai.geocoder")

_CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f-\x9f]')

# Module-level shared client
_shared_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=5.0,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
        )
    return _shared_client


class Geocoder:
    """Geocoding service using OpenStreetMap/Nominatim (Free/Open Source)."""

    def __init__(self):
        self.base_url = settings.GEOCODER_BASE_URL
        self.headers = {
            "User-Agent": "RedlineAI-EmergencyGeocoder/1.0"
        }

    async def close(self):
        pass  # Client is shared; closed at app shutdown

    async def geocode(self, text: str) -> dict:
        """Geocode text using Nominatim.

        Note: Following Nominatim's policy - max 1 request/second.
        """
        if not text:
            return {"latitude": 0.0, "longitude": 0.0, "confidence": 0.0, "query": text}

        text = _CONTROL_CHARS.sub('', text.strip())[:500]

        params = {
            "q": text,
            "format": "json",
            "limit": 1
        }

        try:
            client = _get_client()
            response = await client.get(
                self.base_url,
                params=params,
                headers=self.headers,
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
            logger.error("Geocoding error for '%s': %s", text, e)

        return {
            "latitude": 0.0,
            "longitude": 0.0,
            "confidence": 0.0,
            "query": text
        }
