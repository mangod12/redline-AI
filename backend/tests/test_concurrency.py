"""Concurrency and stress tests — validate agents under parallel load.

These tests verify that:
- Multiple concurrent intent classifications don't interfere
- Multiple concurrent emotion analyses don't interfere
- Severity scoring is deterministic regardless of concurrency
- Circuit breakers trip correctly under concurrent failures
"""

from __future__ import annotations

import asyncio

import pytest
import pybreaker

from app.agents.intent.intent_agent import IntentAgent, _intent_breaker
from app.agents.emotion.emotion_agent import EmotionAgent, _ml_breaker
from app.core.schemas import Transcript
from app.core.schemas.intent import IntentType
from app.core.schemas.emotion import EmotionType
from app.services.severity_service import compute_severity
from app.services.dispatch_service import select_responder


class TestConcurrentIntentClassification:
    @pytest.mark.asyncio
    async def test_10_parallel_classifications(self):
        """10 concurrent intent classifications should all succeed."""
        agent = IntentAgent(loader=None)
        transcripts = [
            Transcript(text=f"there is a fire emergency {i}", confidence=1.0)
            for i in range(10)
        ]
        tasks = [agent.process(t) for t in transcripts]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        for r in results:
            assert r.intent == IntentType.FIRE
            assert r.fallback_used is True

    @pytest.mark.asyncio
    async def test_mixed_intents_parallel(self):
        """Different intent types classified in parallel."""
        agent = IntentAgent(loader=None)
        inputs = [
            ("fire burning building", IntentType.FIRE),
            ("gun robbery attack", IntentType.VIOLENT_CRIME),
            ("chest pain medical", IntentType.MEDICAL),
            ("car crash accident", IntentType.ACCIDENT),
            ("gas leak fumes", IntentType.GAS_HAZARD),
        ]
        tasks = [
            agent.process(Transcript(text=text, confidence=1.0))
            for text, _ in inputs
        ]
        results = await asyncio.gather(*tasks)

        for result, (_, expected_intent) in zip(results, inputs):
            assert result.intent == expected_intent


class TestConcurrentEmotionAnalysis:
    @pytest.mark.asyncio
    async def test_10_parallel_emotions(self):
        """10 concurrent emotion analyses should all succeed."""
        _ml_breaker.close()  # reset breaker
        agent = EmotionAgent(loader=None)
        transcripts = [
            Transcript(text=f"help emergency scared {i}", confidence=1.0)
            for i in range(10)
        ]
        tasks = [agent.process(t) for t in transcripts]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        for r in results:
            assert r.primary_emotion in set(EmotionType)


class TestConcurrentSeverity:
    @pytest.mark.asyncio
    async def test_severity_deterministic_under_concurrency(self):
        """Same inputs should always produce same severity, even in parallel."""
        tasks = [
            compute_severity("someone has been shot", "fear")
            for _ in range(20)
        ]
        results = await asyncio.gather(*tasks)
        assert all(r == "critical" for r in results)

    @pytest.mark.asyncio
    async def test_dispatch_deterministic_under_concurrency(self):
        """Same inputs should always produce same dispatch."""
        tasks = [
            select_responder("fire", "critical")
            for _ in range(20)
        ]
        results = await asyncio.gather(*tasks)
        assert all(r == "fire_dispatch" for r in results)


class TestCircuitBreakerUnderLoad:
    @pytest.mark.asyncio
    async def test_intent_breaker_trips_after_failures(self):
        """Circuit breaker should trip after 3 failed inferences."""
        _intent_breaker.close()  # reset

        class FailingLoader:
            def is_ready(self):
                return True

            async def predict_proba(self, text):
                raise RuntimeError("Forced failure")

        agent = IntentAgent(loader=FailingLoader())

        # Run 5 sequential calls to ensure breaker trips
        for i in range(5):
            result = await agent.process(
                Transcript(text=f"test {i}", confidence=1.0)
            )
            assert result.fallback_used is True

        # After failures, breaker should be open
        assert _intent_breaker.current_state == pybreaker.STATE_OPEN

        # Next call should immediately fallback via circuit_open
        result = await agent.process(
            Transcript(text="fire burning", confidence=1.0)
        )
        assert result.metadata.get("reason") == "circuit_open"

        _intent_breaker.close()  # cleanup
