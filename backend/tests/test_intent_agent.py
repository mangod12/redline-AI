import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from app.agents.intent.intent_agent import IntentAgent, INTENT_LABELS, SOFT_TIMEOUT_S
from app.core.schemas.transcript import Transcript
from app.core.schemas.intent import IntentType, IntentAnalysis


def _make_transcript(text: str) -> Transcript:
    return Transcript(text=text, confidence=0.9, language="en", audio_duration=3.0)


def _make_loader(probs=None, raises=None, timeout=False):
    """Create a mock loader whose predict_proba returns an array of floats.

    ``probs`` should be a list of floats with one entry per INTENT_LABEL, or
    None to use a default that gives MEDICAL high confidence.
    """
    loader = MagicMock()
    loader.is_ready.return_value = True

    async def _mock_predict_proba(text):
        if timeout:
            await asyncio.sleep(5)
        if raises:
            raise raises
        # Default: high probability for MEDICAL (index 0)
        return probs or [0.8, 0.05, 0.02, 0.02, 0.02, 0.02, 0.02, 0.05]

    loader.predict_proba = _mock_predict_proba
    return loader


def _probs_for(label: IntentType, confidence: float) -> list[float]:
    """Build a probability array giving *label* the stated confidence."""
    n = len(INTENT_LABELS)
    remainder = max(0.0, 1.0 - confidence)
    split = remainder / (n - 1)
    return [
        confidence if intent == label else split
        for intent in INTENT_LABELS
    ]


class TestIntentAgentHappyPath:
    @pytest.mark.asyncio
    async def test_high_confidence_returns_ml_result(self):
        probs = _probs_for(IntentType.FIRE, 0.9)
        loader = _make_loader(probs=probs)
        agent = IntentAgent(loader=loader)

        result = await agent.process(_make_transcript("there is a huge fire"))
        assert result.intent == IntentType.FIRE
        assert result.confidence == pytest.approx(0.9, abs=0.01)
        assert result.metadata.get("source") == "onnx"
        assert result.fallback_used is False


class TestIntentAgentResilience:
    @pytest.mark.asyncio
    async def test_low_confidence_triggers_fallback(self):
        # All labels below threshold (0.6) -> keyword fallback
        probs = _probs_for(IntentType.FIRE, 0.5)
        loader = _make_loader(probs=probs)
        agent = IntentAgent(loader=loader)

        result = await agent.process(_make_transcript("help need medical"))
        # Keyword fallback should detect "medical"
        assert result.intent == IntentType.MEDICAL
        assert result.metadata.get("source") == "keyword"
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_ml_timeout_triggers_fallback(self):
        loader = _make_loader(timeout=True)
        agent = IntentAgent(loader=loader)

        with patch("app.agents.intent.intent_agent.SOFT_TIMEOUT_S", 0.01):
            result = await agent.process(_make_transcript("there is a fire"))

        assert result.intent == IntentType.FIRE
        assert result.metadata.get("source") == "keyword"
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_ml_exception_triggers_fallback(self):
        loader = _make_loader(raises=RuntimeError("Model crashed"))
        agent = IntentAgent(loader=loader)

        result = await agent.process(_make_transcript("help fire"))
        assert result.intent == IntentType.FIRE
        assert result.metadata.get("source") == "keyword"
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_no_loader_triggers_fallback(self):
        agent = IntentAgent(loader=None)
        result = await agent.process(_make_transcript("there is a fire"))
        assert result.intent == IntentType.FIRE
        assert result.fallback_used is True
        assert result.metadata.get("source") == "keyword"
