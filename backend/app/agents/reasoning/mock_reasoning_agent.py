"""Reasoning Agent using Google Gemini (primary) or Groq (fallback).

Analyzes emotion data from emergency calls and produces structured
reasoning output with key insights, risk factors, and context summary.
"""

import asyncio
import json
import logging
from typing import Any

from ...core.config import settings
from ...core.schemas import EmotionAnalysis, ReasoningOutput
from ..base import BaseAgent

logger = logging.getLogger("redline_ai.reasoning")

_REASONING_PROMPT = """
Analyze the following emergency call emotion data and provide a structured JSON response.
Primary Emotion: {emotion}
Intensity: {intensity}

Respond ONLY with a JSON object in this format:
{{
    "key_insights": ["list", "of", "3", "insights"],
    "risk_factors": ["list", "of", "risk", "factors"],
    "context_summary": "one sentence summary",
    "confidence": 0.9
}}
"""


def _create_gemini_client():
    """Create a Gemini GenerativeModel if API key is available."""
    if not settings.GEMINI_API_KEY:
        return None
    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")
        logger.info("Gemini client initialized for reasoning")
        return model
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")
        return None


def _create_groq_client():
    """Create a Groq client as fallback if API key is available."""
    if not settings.GROQ_API_KEY:
        return None
    try:
        from groq import Groq

        client = Groq(api_key=settings.GROQ_API_KEY)
        logger.info("Groq client initialized as reasoning fallback")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize Groq client: {e}")
        return None


class MockReasoningAgent(BaseAgent):
    """Reasoning Agent using Gemini (primary), Groq (fallback), or mock."""

    def __init__(self, config: dict[str, Any] = None):
        self.config = config or {}
        self.gemini_model = _create_gemini_client()
        self.groq_client = _create_groq_client()

    async def process(self, input_data: EmotionAnalysis) -> ReasoningOutput:
        """Process emotion analysis through Gemini, Groq fallback, or mock."""
        if self.gemini_model:
            return await self._process_with_gemini(input_data)
        if self.groq_client:
            return await self._process_with_groq(input_data)
        await asyncio.sleep(0.1)
        return self._fallback_mock(input_data)

    async def _process_with_gemini(self, input_data: EmotionAnalysis) -> ReasoningOutput:
        prompt = _REASONING_PROMPT.format(
            emotion=input_data.primary_emotion.value,
            intensity=input_data.intensity,
        )
        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.gemini_model.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json"},
                ),
            )
            data = json.loads(response.text)
            return ReasoningOutput(
                key_insights=data.get("key_insights", []),
                risk_factors=data.get("risk_factors", []),
                context_summary=data.get("context_summary", ""),
                confidence=data.get("confidence", 0.8),
                metadata={"engine": "gemini", "model": "gemini-2.0-flash"},
            )
        except Exception as e:
            logger.error(f"Gemini reasoning failed: {e}")
            if self.groq_client:
                return await self._process_with_groq(input_data)
            return self._fallback_mock(input_data)

    async def _process_with_groq(self, input_data: EmotionAnalysis) -> ReasoningOutput:
        prompt = _REASONING_PROMPT.format(
            emotion=input_data.primary_emotion.value,
            intensity=input_data.intensity,
        )
        try:
            loop = asyncio.get_running_loop()
            completion = await loop.run_in_executor(
                None,
                lambda: self.groq_client.chat.completions.create(
                    model="llama3-70b-8192",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                ),
            )
            data = json.loads(completion.choices[0].message.content)
            return ReasoningOutput(
                key_insights=data.get("key_insights", []),
                risk_factors=data.get("risk_factors", []),
                context_summary=data.get("context_summary", ""),
                confidence=data.get("confidence", 0.8),
                metadata={"engine": "groq", "model": "llama3-70b-8192"},
            )
        except Exception as e:
            logger.error(f"Groq reasoning failed: {e}")
            return self._fallback_mock(input_data)

    def _fallback_mock(self, input_data: EmotionAnalysis) -> ReasoningOutput:
        if input_data.primary_emotion == input_data.primary_emotion.FEAR:
            insights = ["[Mock] High emotional distress detected", "[Mock] Potential emergency situation"]
            risk_factors = ["[Mock] Emotional crisis", "[Mock] Possible immediate danger"]
            context = "[Mock] Caller appears to be in distress and may need immediate assistance"
        else:
            insights = ["[Mock] Normal emotional state"]
            risk_factors = []
            context = "[Mock] No immediate concerns detected"

        return ReasoningOutput(
            key_insights=insights,
            risk_factors=risk_factors,
            context_summary=context,
            confidence=0.5,
            metadata={"engine": "mock"},
        )

    def get_input_schema(self):
        return EmotionAnalysis

    def get_output_schema(self):
        return ReasoningOutput
