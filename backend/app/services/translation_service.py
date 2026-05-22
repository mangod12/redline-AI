import httpx
import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("redline_ai.translation")

# Module-level shared client — reused across all TranslationService instances
_shared_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=10.0,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _shared_client


class TranslationService:
    """Translation service using LibreTranslate (Open Source)."""

    def __init__(self, api_url: str = ""):
        api_url = api_url or settings.TRANSLATION_SERVICE_URL
        from urllib.parse import urlparse
        parsed = urlparse(api_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid translation service URL scheme: {parsed.scheme}")
        self.api_url = api_url

    async def close(self):
        pass  # Client is shared; closed at app shutdown

    async def translate(self, text: str, source_lang: str) -> str:
        if not source_lang or source_lang.lower().startswith("en"):
            return text

        payload = {
            "q": text,
            "source": source_lang.lower()[:2],
            "target": "en",
            "format": "text"
        }

        try:
            client = _get_client()
            response = await client.post(self.api_url, data=payload)

            if response.status_code == 200:
                return response.json().get("translatedText", text)
            else:
                logger.warning("LibreTranslate returned status %s", response.status_code)
        except Exception as e:
            logger.error("Translation error: %s", e)

        return text
