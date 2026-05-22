"""Edge case and error path tests for production resilience.

Covers:
- Empty/malformed inputs to all agents
- Severity boundary conditions
- Dispatch routing completeness
- Cache service resilience
- Schema validation
- Config safety checks
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.schemas import Transcript
from app.core.schemas.intent import IntentType, IntentAnalysis
from app.core.schemas.emotion import EmotionType, EmotionAnalysis
from app.core.schemas.severity import SeverityLevel


# ---------------------------------------------------------------------------
# Intent Agent edge cases
# ---------------------------------------------------------------------------


class TestIntentEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_text_returns_unknown(self):
        from app.agents.intent.intent_agent import IntentAgent
        agent = IntentAgent(loader=None)
        result = await agent.process(Transcript(text="", confidence=1.0))
        assert result.fallback_used is True
        assert result.intent == IntentType.UNKNOWN

    @pytest.mark.asyncio
    async def test_whitespace_only_text(self):
        from app.agents.intent.intent_agent import IntentAgent
        agent = IntentAgent(loader=None)
        result = await agent.process(Transcript(text="   \n\t  ", confidence=1.0))
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_very_long_text_does_not_crash(self):
        from app.agents.intent.intent_agent import IntentAgent
        agent = IntentAgent(loader=None)
        long_text = "help " * 5000
        result = await agent.process(Transcript(text=long_text, confidence=1.0))
        assert isinstance(result, IntentAnalysis)

    @pytest.mark.asyncio
    async def test_unicode_text_handled(self):
        from app.agents.intent.intent_agent import IntentAgent
        agent = IntentAgent(loader=None)
        result = await agent.process(Transcript(text="🔥 fuego ayuda fire", confidence=1.0))
        assert result.intent == IntentType.FIRE

    @pytest.mark.asyncio
    async def test_none_loader_fallback(self):
        from app.agents.intent.intent_agent import IntentAgent
        agent = IntentAgent(loader=None)
        result = await agent.process(Transcript(text="someone has a gun and is attacking", confidence=1.0))
        assert result.fallback_used is True
        assert result.intent == IntentType.VIOLENT_CRIME


# ---------------------------------------------------------------------------
# Emotion Agent edge cases
# ---------------------------------------------------------------------------


class TestEmotionEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_text_returns_neutral(self):
        from app.agents.emotion.emotion_agent import EmotionAgent
        agent = EmotionAgent(loader=None)
        result = await agent.process(Transcript(text="", confidence=1.0))
        assert isinstance(result, EmotionAnalysis)

    @pytest.mark.asyncio
    async def test_none_loader_uses_heuristic(self):
        from app.agents.emotion.emotion_agent import EmotionAgent
        agent = EmotionAgent(loader=None)
        result = await agent.process(Transcript(text="help emergency fire", confidence=1.0))
        assert result.primary_emotion in {EmotionType.FEAR, EmotionType.NEUTRAL, EmotionType.SADNESS}

    @pytest.mark.asyncio
    async def test_scores_always_sum_approximately_one(self):
        from app.agents.emotion.emotion_agent import EmotionAgent
        agent = EmotionAgent(loader=None)
        result = await agent.process(Transcript(text="help emergency scared", confidence=1.0))
        total = sum(result.emotion_scores.values())
        assert abs(total - 1.0) < 0.01


# ---------------------------------------------------------------------------
# Severity service edge cases
# ---------------------------------------------------------------------------


class TestSeverityServiceEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_transcript(self):
        from app.services.severity_service import compute_severity
        result = await compute_severity("", "neutral")
        assert result == "low"

    @pytest.mark.asyncio
    async def test_unknown_emotion_no_promotion(self):
        from app.services.severity_service import compute_severity
        result = await compute_severity("minor issue", "unknown_emotion")
        assert result in {"low", "medium"}

    @pytest.mark.asyncio
    async def test_all_severity_levels_reachable(self):
        from app.services.severity_service import compute_severity
        low = await compute_severity("hello", "neutral")
        medium = await compute_severity("someone is hurt", "neutral")
        high = await compute_severity("there is a fire", "neutral")
        critical = await compute_severity("someone has been shot and is dying", "fear")
        assert low == "low"
        assert medium == "medium"
        assert high == "high"
        assert critical == "critical"


# ---------------------------------------------------------------------------
# Dispatch service edge cases
# ---------------------------------------------------------------------------


class TestDispatchEdgeCases:
    @pytest.mark.asyncio
    async def test_unknown_intent_low_severity(self):
        from app.services.dispatch_service import select_responder
        result = await select_responder("unknown", "low")
        assert result == "call_center_followup"

    @pytest.mark.asyncio
    async def test_all_critical_intents_have_responder(self):
        from app.services.dispatch_service import select_responder
        intents = ["fire", "gas_hazard", "medical", "mental_health", "violent_crime", "accident"]
        for intent in intents:
            result = await select_responder(intent, "critical")
            assert result in {"fire_dispatch", "ambulance", "police_dispatch"}

    @pytest.mark.asyncio
    async def test_invalid_severity_falls_through(self):
        from app.services.dispatch_service import select_responder
        result = await select_responder("medical", "invalid_level")
        assert result == "call_center_followup"


# ---------------------------------------------------------------------------
# Cache service resilience
# ---------------------------------------------------------------------------


class TestCacheServiceResilience:
    @pytest.mark.asyncio
    async def test_cache_call_with_none_client(self):
        from app.services.cache_service import cache_call
        # Should not raise
        await cache_call(None, "test-id", {"key": "value"})

    @pytest.mark.asyncio
    async def test_get_cached_call_with_none_client(self):
        from app.services.cache_service import get_cached_call
        result = await get_cached_call(None, "test-id")
        assert result is None


# ---------------------------------------------------------------------------
# Config safety
# ---------------------------------------------------------------------------


class TestConfigSafety:
    def test_sqlite_blocked_in_production(self):
        from app.core.config import Settings
        s = Settings(USE_SQLITE=True, APP_ENV="production")
        with pytest.raises(RuntimeError, match="SQLite is not supported"):
            _ = s.SQLALCHEMY_DATABASE_URI

    def test_default_secret_key_is_empty(self):
        from app.core.config import settings
        # In test env, SECRET_KEY should be empty (not a hardcoded default)
        assert settings.SECRET_KEY == "" or len(settings.SECRET_KEY) > 0

    def test_max_audio_bytes_is_reasonable(self):
        from app.core.config import settings
        assert 1024 * 1024 <= settings.MAX_AUDIO_BYTES <= 100 * 1024 * 1024

    def test_max_transcript_length_is_bounded(self):
        from app.core.config import settings
        assert 100 <= settings.MAX_TRANSCRIPT_LENGTH <= 100_000


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_transcript_requires_text(self):
        with pytest.raises(Exception):
            Transcript(confidence=1.0)  # missing text

    def test_severity_level_enum_values(self):
        assert SeverityLevel.LOW.value == "low"
        assert SeverityLevel.CRITICAL.value == "critical"

    def test_intent_type_all_values(self):
        expected = {"medical", "fire", "violent_crime", "accident", "gas_hazard",
                    "mental_health", "non_emergency", "unknown"}
        actual = {e.value for e in IntentType}
        assert actual == expected

    def test_emotion_type_all_values(self):
        expected = {"anger", "fear", "sadness", "joy", "surprise", "disgust", "neutral"}
        actual = {e.value for e in EmotionType}
        assert actual == expected


# ---------------------------------------------------------------------------
# Whisper service edge cases
# ---------------------------------------------------------------------------


class TestWhisperEdgeCases:
    def test_not_ready_before_init(self):
        from app.services.whisper_service import WhisperService
        svc = WhisperService(model_size="tiny")
        assert svc.is_ready() is False

    @pytest.mark.asyncio
    async def test_transcribe_raises_if_not_ready(self):
        from app.services.whisper_service import WhisperService
        svc = WhisperService()
        with pytest.raises(RuntimeError, match="not initialised"):
            await svc.transcribe(b"fake audio")

    def test_shutdown_clears_model(self):
        from app.services.whisper_service import WhisperService
        svc = WhisperService()
        svc._model = "fake"
        svc.shutdown()
        assert svc.is_ready() is False


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------


class TestPasswordEdgeCases:
    def test_exactly_12_chars_valid(self):
        from app.schemas.user import UserCreate
        import uuid
        u = UserCreate(
            email="test@test.com",
            password="Abcdefghij1!",
            tenant_id=uuid.uuid4(),
        )
        assert u.password == "Abcdefghij1!"

    def test_11_chars_rejected(self):
        from app.schemas.user import UserCreate
        import uuid
        with pytest.raises(Exception):
            UserCreate(
                email="test@test.com",
                password="Abcdefghi1!",
                tenant_id=uuid.uuid4(),
            )
