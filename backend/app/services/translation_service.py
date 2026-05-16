import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("redline_ai.translation")

class TranslationService:
    """Translation service using LibreTranslate (Open Source)."""

    def __init__(self, api_url: str | None = None):
        self.api_url = api_url or settings.TRANSLATION_SERVICE_URL
        self._client = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def translate(self, text: str, source_lang: str) -> str:
        """Translate text using LibreTranslate.

        Args:
            text: Text to translate.
            source_lang: Source language code (e.g., 'es', 'fr').
        """
        if not source_lang or source_lang.lower().startswith("en"):
            return text

        payload = {
            "q": text,
            "source": source_lang.lower()[:2], # Take first two chars
            "target": "en",
            "format": "text"
        }

        try:
            response = await self._client.post(self.api_url, data=payload)

            if response.status_code == 200:
                return response.json().get("translatedText", text)
            else:
                logger.warning(f"LibreTranslate returned status {response.status_code}")
        except Exception as e:
            logger.error(f"Translation error: {e}")

        return text
