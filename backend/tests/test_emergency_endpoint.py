"""Phase 3 tests for the /process-emergency endpoint.

The endpoint accepts JSON ``{"transcript": "...", "caller_id": "..."}``
and runs the full pipeline: Intent -> Emotion -> Severity -> Dispatch -> DB.

All ML components (IntentAgent, EmotionAgent, WhisperService) and external
services (Redis, dashboard call_store) are mocked so tests run against the
in-memory SQLite database only.
"""
from dataclasses import dataclass
from enum import Enum
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock data classes matching what the agents return
# ---------------------------------------------------------------------------


class _MockIntentEnum(str, Enum):
    fire = "fire"
    medical = "medical"
    unknown = "unknown"


class _MockEmotionEnum(str, Enum):
    fear = "fear"
    neutral = "neutral"


@dataclass
class _MockIntentResult:
    intent: _MockIntentEnum = _MockIntentEnum.fire
    confidence: float = 0.92
    fallback_used: bool = False


@dataclass
class _MockEmotionResult:
    primary_emotion: _MockEmotionEnum = _MockEmotionEnum.fear
    confidence: float = 0.85


# ---------------------------------------------------------------------------
# Shared patch context
# ---------------------------------------------------------------------------


def _emergency_patches():
    """Return a dict of patches that neutralise all external dependencies."""
    return {
        "intent_agent": patch(
            "app.agents.intent.intent_agent.IntentAgent",
            side_effect=None,
        ),
        "emotion_agent": patch(
            "app.agents.emotion.emotion_agent.EmotionAgent",
            side_effect=None,
        ),
        "cache_call": patch(
            "app.api.v1.endpoints.emergency.cache_call",
            new_callable=AsyncMock,
        ),
        "get_redis": patch(
            "app.api.v1.endpoints.emergency.get_redis_client",
            return_value=None,
        ),
        "call_store": patch(
            "app.api.v1.endpoints.emergency.call_store",
        ),
    }


# ===========================================================================
# JSON body tests
# ===========================================================================


class TestEmergencyJSON:
    @pytest.mark.asyncio
    async def test_process_emergency_json_success(self, client):
        """A valid JSON body with a transcript should return a full response."""
        mock_intent_agent_instance = AsyncMock()
        mock_intent_agent_instance.process = AsyncMock(return_value=_MockIntentResult())

        mock_emotion_agent_instance = AsyncMock()
        mock_emotion_agent_instance.process = AsyncMock(return_value=_MockEmotionResult())

        with (
            patch(
                "app.agents.intent.intent_agent.IntentAgent",
                return_value=mock_intent_agent_instance,
            ),
            patch(
                "app.agents.emotion.emotion_agent.EmotionAgent",
                return_value=mock_emotion_agent_instance,
            ),
            patch(
                "app.api.v1.endpoints.emergency.cache_call",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.v1.endpoints.emergency.get_redis_client",
                return_value=None,
            ),
            patch("app.api.v1.endpoints.emergency.call_store") as mock_store,
        ):
            resp = await client.post(
                "/process-emergency",
                json={
                    "transcript": "There is a fire in the building",
                    "caller_id": "caller-001",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["transcript"] == "There is a fire in the building"
        assert body["intent"] == "fire"
        assert body["emotion"] == "fear"
        assert body["caller_id"] == "caller-001"
        # Severity for "fire" keyword + "fear" emotion = high promoted to critical
        assert body["severity"] == "critical"
        assert body["responder"] == "fire_dispatch"
        assert "call_id" in body
        assert "latency_ms" in body

    @pytest.mark.asyncio
    async def test_process_emergency_missing_transcript(self, client):
        """An empty transcript should return 422."""
        with (
            patch(
                "app.agents.intent.intent_agent.IntentAgent",
                side_effect=Exception("should not be called"),
            ),
            patch(
                "app.agents.emotion.emotion_agent.EmotionAgent",
                side_effect=Exception("should not be called"),
            ),
            patch(
                "app.api.v1.endpoints.emergency.cache_call",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.v1.endpoints.emergency.get_redis_client",
                return_value=None,
            ),
            patch("app.api.v1.endpoints.emergency.call_store"),
        ):
            resp = await client.post(
                "/process-emergency",
                json={"transcript": "", "caller_id": "caller-002"},
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_process_emergency_no_body(self, client):
        """A request with no body at all should return 422."""
        resp = await client.post(
            "/process-emergency",
            content=b"",
            headers={"Content-Type": "application/json"},
        )
        # Either 422 for missing field or 422 for invalid JSON
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_process_emergency_with_agent_fallback(self, client):
        """When agents raise exceptions, the endpoint falls back gracefully."""
        with (
            patch(
                "app.agents.intent.intent_agent.IntentAgent",
                side_effect=Exception("model unavailable"),
            ),
            patch(
                "app.agents.emotion.emotion_agent.EmotionAgent",
                side_effect=Exception("model unavailable"),
            ),
            patch(
                "app.api.v1.endpoints.emergency.cache_call",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.v1.endpoints.emergency.get_redis_client",
                return_value=None,
            ),
            patch("app.api.v1.endpoints.emergency.call_store"),
        ):
            resp = await client.post(
                "/process-emergency",
                json={
                    "transcript": "Someone has been shot and is not breathing",
                    "caller_id": "fallback-test",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        # Agents failed, so fallback values should be used
        assert body["intent"] == "unknown"
        assert body["emotion"] == "neutral"
        # "shot" and "not breathing" are critical keywords
        assert body["severity"] == "critical"
        assert body["responder"] == "police_dispatch"

    @pytest.mark.asyncio
    async def test_process_emergency_low_severity(self, client):
        """A benign transcript with no keywords should yield low severity."""
        mock_intent = AsyncMock()
        mock_intent.process = AsyncMock(
            return_value=_MockIntentResult(
                intent=_MockIntentEnum.unknown, confidence=0.3, fallback_used=True
            )
        )
        mock_emotion = AsyncMock()
        mock_emotion.process = AsyncMock(
            return_value=_MockEmotionResult(
                primary_emotion=_MockEmotionEnum.neutral, confidence=0.5
            )
        )

        with (
            patch(
                "app.agents.intent.intent_agent.IntentAgent",
                return_value=mock_intent,
            ),
            patch(
                "app.agents.emotion.emotion_agent.EmotionAgent",
                return_value=mock_emotion,
            ),
            patch(
                "app.api.v1.endpoints.emergency.cache_call",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.v1.endpoints.emergency.get_redis_client",
                return_value=None,
            ),
            patch("app.api.v1.endpoints.emergency.call_store"),
        ):
            resp = await client.post(
                "/process-emergency",
                json={
                    "transcript": "I would like to report a noise complaint from my neighbor",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["severity"] == "low"
        assert body["responder"] == "call_center_followup"

    @pytest.mark.asyncio
    async def test_process_emergency_medical_intent(self, client):
        """A medical emergency with high severity should dispatch ambulance."""
        mock_intent = AsyncMock()
        mock_intent.process = AsyncMock(
            return_value=_MockIntentResult(
                intent=_MockIntentEnum.medical, confidence=0.95, fallback_used=False
            )
        )
        mock_emotion = AsyncMock()
        mock_emotion.process = AsyncMock(
            return_value=_MockEmotionResult(
                primary_emotion=_MockEmotionEnum.fear, confidence=0.9
            )
        )

        with (
            patch(
                "app.agents.intent.intent_agent.IntentAgent",
                return_value=mock_intent,
            ),
            patch(
                "app.agents.emotion.emotion_agent.EmotionAgent",
                return_value=mock_emotion,
            ),
            patch(
                "app.api.v1.endpoints.emergency.cache_call",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.v1.endpoints.emergency.get_redis_client",
                return_value=None,
            ),
            patch("app.api.v1.endpoints.emergency.call_store"),
        ):
            resp = await client.post(
                "/process-emergency",
                json={
                    "transcript": "Someone is bleeding badly and in serious pain",
                    "caller_id": "med-001",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["intent"] == "medical"
        # "bleeding" and "serious" and "pain" are HIGH keywords, + fear -> critical
        assert body["severity"] == "critical"
        assert body["responder"] == "ambulance"

    @pytest.mark.asyncio
    async def test_response_includes_latency(self, client):
        """The response should include a non-negative latency_ms field."""
        mock_intent = AsyncMock()
        mock_intent.process = AsyncMock(return_value=_MockIntentResult())
        mock_emotion = AsyncMock()
        mock_emotion.process = AsyncMock(return_value=_MockEmotionResult())

        with (
            patch(
                "app.agents.intent.intent_agent.IntentAgent",
                return_value=mock_intent,
            ),
            patch(
                "app.agents.emotion.emotion_agent.EmotionAgent",
                return_value=mock_emotion,
            ),
            patch(
                "app.api.v1.endpoints.emergency.cache_call",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.v1.endpoints.emergency.get_redis_client",
                return_value=None,
            ),
            patch("app.api.v1.endpoints.emergency.call_store"),
        ):
            resp = await client.post(
                "/process-emergency",
                json={"transcript": "There is a fire"},
            )

        assert resp.status_code == 200
        assert resp.json()["latency_ms"] >= 0
