"""Unit tests for compute_severity and select_responder."""

import pytest

from app.services.severity_service import compute_severity
from app.services.dispatch_service import select_responder


# ---------------------------------------------------------------------------
# compute_severity
# ---------------------------------------------------------------------------


class TestComputeSeverity:
    @pytest.mark.asyncio
    async def test_critical_keyword(self):
        result = await compute_severity("someone was shot in the street", "neutral")
        assert result == "critical"

    @pytest.mark.asyncio
    async def test_critical_keyword_with_fear_stays_critical(self):
        result = await compute_severity("there was an explosion nearby", "fear")
        assert result == "critical"

    @pytest.mark.asyncio
    async def test_high_keyword(self):
        result = await compute_severity("there is a fire in the building", "neutral")
        assert result == "high"

    @pytest.mark.asyncio
    async def test_high_keyword_promoted_by_fear(self):
        result = await compute_severity("there is a fire in the building", "fear")
        assert result == "critical"

    @pytest.mark.asyncio
    async def test_medium_keyword(self):
        result = await compute_severity("someone fell and got hurt", "neutral")
        assert result == "medium"

    @pytest.mark.asyncio
    async def test_medium_keyword_promoted_by_anger(self):
        result = await compute_severity("someone fell and got hurt", "anger")
        assert result == "high"

    @pytest.mark.asyncio
    async def test_low_severity_no_keywords(self):
        result = await compute_severity("I want to report a noise complaint", "neutral")
        assert result == "low"

    @pytest.mark.asyncio
    async def test_low_promoted_by_sadness(self):
        result = await compute_severity("something happened here", "sadness")
        assert result == "medium"

    @pytest.mark.asyncio
    async def test_low_promoted_by_fear(self):
        result = await compute_severity("something happened here", "fear")
        assert result == "medium"

    @pytest.mark.asyncio
    async def test_empty_transcript(self):
        result = await compute_severity("", "neutral")
        assert result == "low"


# ---------------------------------------------------------------------------
# select_responder
# ---------------------------------------------------------------------------


class TestSelectResponder:
    @pytest.mark.asyncio
    async def test_critical_fire(self):
        assert await select_responder("fire", "critical") == "fire_dispatch"

    @pytest.mark.asyncio
    async def test_critical_medical(self):
        assert await select_responder("medical", "critical") == "ambulance"

    @pytest.mark.asyncio
    async def test_critical_unknown(self):
        assert await select_responder("unknown", "critical") == "police_dispatch"

    @pytest.mark.asyncio
    async def test_high_medical(self):
        assert await select_responder("medical", "high") == "ambulance"

    @pytest.mark.asyncio
    async def test_high_fire(self):
        assert await select_responder("fire", "high") == "fire_dispatch"

    @pytest.mark.asyncio
    async def test_high_other(self):
        assert await select_responder("robbery", "high") == "police_dispatch"

    @pytest.mark.asyncio
    async def test_medium_medical(self):
        assert await select_responder("medical", "medium") == "ambulance"

    @pytest.mark.asyncio
    async def test_medium_other(self):
        assert await select_responder("fire", "medium") == "general_responder"

    @pytest.mark.asyncio
    async def test_low_severity(self):
        assert await select_responder("unknown", "low") == "call_center_followup"

    @pytest.mark.asyncio
    async def test_critical_mental_health(self):
        assert await select_responder("mental_health", "critical") == "ambulance"

    @pytest.mark.asyncio
    async def test_critical_gas_hazard(self):
        assert await select_responder("gas_hazard", "critical") == "fire_dispatch"
