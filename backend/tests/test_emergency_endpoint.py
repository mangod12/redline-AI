"""Basic tests for the /process-emergency endpoint schemas and pipeline logic."""
import pytest
from app.services.severity_service import compute_severity
from app.services.dispatch_service import select_responder


class TestSeverityService:
    @pytest.mark.asyncio
    async def test_critical_keywords(self):
        result = await compute_severity("someone has been shot and is dying", "fear")
        assert result == "critical"

    @pytest.mark.asyncio
    async def test_high_keywords(self):
        result = await compute_severity("there is a fire in the building", "neutral")
        assert result == "high"

    @pytest.mark.asyncio
    async def test_medium_keywords(self):
        result = await compute_severity("someone fell and is hurt", "neutral")
        assert result == "medium"

    @pytest.mark.asyncio
    async def test_low_default(self):
        result = await compute_severity("hello how are you", "neutral")
        assert result == "low"

    @pytest.mark.asyncio
    async def test_emotion_promotes_severity(self):
        result = await compute_severity("hello how are you", "fear")
        assert result == "medium"  # fear promotes low -> medium


class TestDispatchService:
    @pytest.mark.asyncio
    async def test_critical_fire(self):
        result = await select_responder("fire", "critical")
        assert result == "fire_dispatch"

    @pytest.mark.asyncio
    async def test_critical_medical(self):
        result = await select_responder("medical", "critical")
        assert result == "ambulance"

    @pytest.mark.asyncio
    async def test_high_violent_crime(self):
        result = await select_responder("violent_crime", "high")
        assert result == "police_dispatch"

    @pytest.mark.asyncio
    async def test_low_default(self):
        result = await select_responder("unknown", "low")
        assert result == "call_center_followup"
