"""Async unit tests for the hybrid SeverityAgent.

Verifies:
- Hybrid formula output and weight distribution
- Level classification thresholds
- Critical keyword floor
- Score clamping
"""

from __future__ import annotations

import pytest

from app.agents.severity.severity_agent import (
    SeverityAgent,
    _keyword_score,
    _severity_level,
    _has_critical_floor_keyword,
)
from app.core.schemas import ReasoningOutput, SeverityLevel
from app.core.schemas.severity import SeverityAssessment
from app.core.schemas.intent import IntentType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_reasoning(
    transcript: str = "Caller needs assistance",
    intent: str = "unknown",
    confidence: float = 0.9,
    emotion_intensity: float = 0.7,
    reasoning_score: float = 0.5,
) -> ReasoningOutput:
    return ReasoningOutput(
        key_insights=["insight"],
        risk_factors=[],
        context_summary=transcript,
        confidence=confidence,
        metadata={
            "transcript": transcript,
            "intent": intent,
            "emotion_intensity": emotion_intensity,
            "reasoning_score": reasoning_score,
        },
    )


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


class TestKeywordScore:
    def test_critical_keywords_high_score(self):
        assert _keyword_score("active shooter on site") >= 0.9

    def test_high_keyword_above_0_7(self):
        score = _keyword_score("there is a fire and smoke")
        assert score >= 0.7

    def test_medium_keyword_range(self):
        score = _keyword_score("minor accident with injury")
        assert 0.4 <= score <= 0.7

    def test_no_keywords_returns_zero(self):
        score = _keyword_score("hello how are you")
        assert score == 0.0

    def test_empty_text_returns_zero(self):
        score = _keyword_score("")
        assert score == 0.0


class TestSeverityLevel:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (0.90, SeverityLevel.CRITICAL),
            (0.85, SeverityLevel.CRITICAL),
            (0.70, SeverityLevel.HIGH),
            (0.65, SeverityLevel.HIGH),
            (0.50, SeverityLevel.MEDIUM),
            (0.40, SeverityLevel.MEDIUM),
            (0.30, SeverityLevel.LOW),
            (0.00, SeverityLevel.LOW),
        ],
    )
    def test_threshold_mapping(self, score: float, expected: SeverityLevel):
        assert _severity_level(score) == expected


class TestCriticalFloor:
    def test_not_breathing_is_critical(self):
        assert _has_critical_floor_keyword("patient is not breathing")

    def test_cardiac_arrest_is_critical(self):
        assert _has_critical_floor_keyword("cardiac arrest in progress")

    def test_normal_text_not_critical(self):
        assert not _has_critical_floor_keyword("minor fender bender")


# ---------------------------------------------------------------------------
# Integration tests -- SeverityAgent
# ---------------------------------------------------------------------------


class TestSeverityAgent:
    @pytest.mark.asyncio
    async def test_returns_severity_assessment(self):
        agent = SeverityAgent()
        reasoning = _make_reasoning(
            transcript="help fire shooting",
            intent="fire",
            emotion_intensity=0.8,
        )
        result = await agent.process(reasoning)
        assert isinstance(result, SeverityAssessment)

    @pytest.mark.asyncio
    async def test_high_intensity_increases_score(self):
        agent = SeverityAgent()
        low_em = _make_reasoning(transcript="accident", intent="accident", emotion_intensity=0.1)
        high_em = _make_reasoning(transcript="accident", intent="accident", emotion_intensity=0.9)

        low_result = await agent.process(low_em)
        high_result = await agent.process(high_em)

        assert high_result.score > low_result.score

    @pytest.mark.asyncio
    async def test_critical_floor_keyword_drives_critical(self):
        agent = SeverityAgent()
        reasoning = _make_reasoning(
            transcript="patient is not breathing cardiac arrest",
            intent="medical",
            emotion_intensity=0.5,
        )
        result = await agent.process(reasoning)
        assert result.level == SeverityLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_factors_dict_contains_components(self):
        agent = SeverityAgent()
        reasoning = _make_reasoning(transcript="injury accident", intent="accident")
        result = await agent.process(reasoning)
        assert "keyword_score" in result.factors
        assert "emotion_intensity" in result.factors
        assert "reasoning_score" in result.factors
        assert "intent_score" in result.factors

    @pytest.mark.asyncio
    async def test_score_clamped_0_to_1(self):
        agent = SeverityAgent()
        reasoning = _make_reasoning(
            transcript="not breathing cardiac arrest active shooter bomb",
            intent="violent_crime",
            emotion_intensity=1.0,
        )
        result = await agent.process(reasoning)
        assert 0.0 <= result.score <= 1.0

    @pytest.mark.asyncio
    async def test_low_risk_produces_low_or_medium(self):
        agent = SeverityAgent()
        reasoning = _make_reasoning(
            transcript="lost my cat in the parking lot",
            intent="non_emergency",
            emotion_intensity=0.1,
        )
        result = await agent.process(reasoning)
        assert result.level in {SeverityLevel.LOW, SeverityLevel.MEDIUM}

    @pytest.mark.asyncio
    async def test_reasoning_text_is_populated(self):
        agent = SeverityAgent()
        reasoning = _make_reasoning(transcript="help fire", intent="fire", emotion_intensity=0.7)
        result = await agent.process(reasoning)
        assert len(result.reasoning) > 10
