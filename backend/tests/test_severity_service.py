"""Phase 3 tests for the severity scoring service.

Tests ``compute_severity(transcript, emotion)`` which returns one of:
critical | high | medium | low

Logic (from severity_service.py):
1. Keyword matching sets a base level:
   - _CRITICAL_KW  -> critical
   - _HIGH_KW      -> high
   - _MEDIUM_KW    -> medium
   - else           -> low

2. Emotion-based promotion:
   - "fear" / "anger"  (HIGH_URGENCY)   -> promote one tier
   - "sadness" / "surprise" / "disgust" (MEDIUM_URGENCY) -> promote only if base == low
"""

import pytest

from app.services.severity_service import compute_severity


# ===========================================================================
# Keyword-only (neutral emotion, no promotion)
# ===========================================================================


class TestKeywordBaseSeverity:
    @pytest.mark.asyncio
    async def test_critical_keyword_dying(self):
        assert await compute_severity("The person is dying", "neutral") == "critical"

    @pytest.mark.asyncio
    async def test_critical_keyword_gun(self):
        assert await compute_severity("He has a gun", "neutral") == "critical"

    @pytest.mark.asyncio
    async def test_critical_keyword_not_breathing(self):
        assert await compute_severity("She is not breathing", "neutral") == "critical"

    @pytest.mark.asyncio
    async def test_critical_keyword_cardiac_arrest(self):
        assert await compute_severity("Cardiac arrest in progress", "neutral") == "critical"

    @pytest.mark.asyncio
    async def test_critical_keyword_overdose(self):
        assert await compute_severity("This is an overdose situation", "neutral") == "critical"

    @pytest.mark.asyncio
    async def test_high_keyword_fire(self):
        assert await compute_severity("There is a fire in the building", "neutral") == "high"

    @pytest.mark.asyncio
    async def test_high_keyword_bleeding(self):
        assert await compute_severity("Bleeding heavily from a wound", "neutral") == "high"

    @pytest.mark.asyncio
    async def test_high_keyword_choking(self):
        assert await compute_severity("The child is choking", "neutral") == "high"

    @pytest.mark.asyncio
    async def test_high_keyword_emergency(self):
        assert await compute_severity("This is an emergency", "neutral") == "high"

    @pytest.mark.asyncio
    async def test_medium_keyword_hurt(self):
        assert await compute_severity("Somebody is hurt", "neutral") == "medium"

    @pytest.mark.asyncio
    async def test_medium_keyword_fell(self):
        assert await compute_severity("An elderly person fell down", "neutral") == "medium"

    @pytest.mark.asyncio
    async def test_medium_keyword_help(self):
        assert await compute_severity("I need help", "neutral") == "medium"

    @pytest.mark.asyncio
    async def test_low_no_keywords(self):
        assert await compute_severity("I want to report a noise complaint", "neutral") == "low"

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        assert await compute_severity("CARDIAC ARREST happening now", "neutral") == "critical"


# ===========================================================================
# Emotion-based promotion (high-urgency emotions: fear, anger)
# ===========================================================================


class TestHighUrgencyEmotionPromotion:
    @pytest.mark.asyncio
    async def test_low_promoted_to_medium_by_fear(self):
        assert await compute_severity("Just a noise complaint", "fear") == "medium"

    @pytest.mark.asyncio
    async def test_medium_promoted_to_high_by_fear(self):
        assert await compute_severity("Someone is hurt", "fear") == "high"

    @pytest.mark.asyncio
    async def test_high_promoted_to_critical_by_anger(self):
        assert await compute_severity("There is a fire", "anger") == "critical"

    @pytest.mark.asyncio
    async def test_critical_stays_critical_with_fear(self):
        """Critical is the ceiling -- cannot be promoted further."""
        assert await compute_severity("Person is dying", "fear") == "critical"

    @pytest.mark.asyncio
    async def test_low_promoted_to_medium_by_anger(self):
        assert await compute_severity("Minor dispute", "anger") == "medium"


# ===========================================================================
# Emotion-based promotion (medium-urgency emotions: sadness, surprise, disgust)
# ===========================================================================


class TestMediumUrgencyEmotionPromotion:
    @pytest.mark.asyncio
    async def test_low_promoted_to_medium_by_sadness(self):
        assert await compute_severity("Nothing happened yet", "sadness") == "medium"

    @pytest.mark.asyncio
    async def test_low_promoted_to_medium_by_surprise(self):
        assert await compute_severity("I saw something unusual", "surprise") == "medium"

    @pytest.mark.asyncio
    async def test_low_promoted_to_medium_by_disgust(self):
        assert await compute_severity("There is a mess", "disgust") == "medium"

    @pytest.mark.asyncio
    async def test_medium_stays_medium_with_sadness(self):
        """Medium-urgency emotions only promote low -> medium, not further."""
        assert await compute_severity("Someone is hurt", "sadness") == "medium"

    @pytest.mark.asyncio
    async def test_high_stays_high_with_surprise(self):
        assert await compute_severity("There is a fire", "surprise") == "high"

    @pytest.mark.asyncio
    async def test_critical_stays_critical_with_disgust(self):
        assert await compute_severity("Person is dying", "disgust") == "critical"


# ===========================================================================
# Edge cases
# ===========================================================================


class TestSeverityEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_transcript(self):
        assert await compute_severity("", "neutral") == "low"

    @pytest.mark.asyncio
    async def test_unknown_emotion(self):
        """An emotion not in any urgency set should cause no promotion."""
        assert await compute_severity("Just checking in", "joy") == "low"

    @pytest.mark.asyncio
    async def test_multiple_keyword_tiers_highest_wins(self):
        """Critical keywords should win even if high/medium keywords also present."""
        assert await compute_severity("fire and gun shot victim is hurt", "neutral") == "critical"
