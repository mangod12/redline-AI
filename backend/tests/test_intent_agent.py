import pytest
import asyncio
from unittest.mock import patch, MagicMock
from app.agents.intent.intent_agent import IntentAgent
from app.core.schemas.transcript import Transcript
from app.core.schemas.intent import IntentType, IntentAnalysis

def _make_transcript(text: str) -> Transcript:
    return Transcript(text=text, confidence=0.9, language="en", audio_duration=3.0)

def _make_loader(probs=None, raises=None, timeout=False):
    loader = MagicMock()
    loader.is_ready.return_value = True

    async def _mock_predict_proba(text):
        if timeout:
            await asyncio.sleep(5)
        if raises:
            raise raises
        # 8 classes: medical, fire, violent_crime, accident, gas_hazard, mental_health, non_emergency, unknown
        return probs or [0.8, 0.05, 0.0, 0.0, 0.0, 0.0, 0.0, 0.15]

    loader.predict_proba = _mock_predict_proba
    return loader

class TestIntentAgentHappyPath:
    @pytest.mark.asyncio
    async def test_high_confidence_returns_ml_result(self):
        # 8 classes: medical, fire, violent_crime, accident, gas_hazard, mental_health, non_emergency, unknown
        loader = _make_loader(probs=[0.05, 0.9, 0.0, 0.0, 0.0, 0.0, 0.0, 0.05])
        agent = IntentAgent(loader=loader)

        result = await agent.process(_make_transcript("there is a huge fire"))
        assert result.intent == IntentType.FIRE
        assert result.confidence == 0.9
        assert result.metadata.get("source") == "onnx"
        assert result.fallback_used is False

class TestIntentAgentResilience:
    @pytest.mark.asyncio
    async def test_low_confidence_triggers_fallback(self):
        # 0.5 is < threshold (0.6)
        # 8 classes: medical, fire, violent_crime, accident, gas_hazard, mental_health, non_emergency, unknown
        loader = _make_loader(probs=[0.3, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.2])
        agent = IntentAgent(loader=loader)

        result = await agent.process(_make_transcript("help need medical"))
        # The keyword rules have "medical" so it should trigger MEDICAL
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
