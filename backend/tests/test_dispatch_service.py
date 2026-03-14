"""Phase 3 tests for the dispatch service.

Tests:
- ``select_responder(intent, severity)`` free function
- ``DispatchService.recommend(severity_score, incident_type)`` class method

Logic from dispatch_service.py:

select_responder:
  critical:
    fire/gas_hazard -> fire_dispatch
    medical/mental_health -> ambulance
    else -> police_dispatch
  high:
    medical/mental_health -> ambulance
    fire/gas_hazard -> fire_dispatch
    else -> police_dispatch
  medium:
    medical -> ambulance
    else -> general_responder
  low (anything else):
    -> call_center_followup

DispatchService.recommend:
  severity_score > 8  -> police-12, eta 4, HIGH
  severity_score > 5  -> responder-1, eta 10, MEDIUM
  else                -> monitor-0, eta None, LOW
"""

import pytest

from app.services.dispatch_service import DispatchService, select_responder

# ===========================================================================
# select_responder -- critical severity
# ===========================================================================


class TestSelectResponderCritical:
    @pytest.mark.asyncio
    async def test_fire_critical(self):
        assert await select_responder("fire", "critical") == "fire_dispatch"

    @pytest.mark.asyncio
    async def test_gas_hazard_critical(self):
        assert await select_responder("gas_hazard", "critical") == "fire_dispatch"

    @pytest.mark.asyncio
    async def test_medical_critical(self):
        assert await select_responder("medical", "critical") == "ambulance"

    @pytest.mark.asyncio
    async def test_mental_health_critical(self):
        assert await select_responder("mental_health", "critical") == "ambulance"

    @pytest.mark.asyncio
    async def test_robbery_critical(self):
        assert await select_responder("robbery", "critical") == "police_dispatch"

    @pytest.mark.asyncio
    async def test_unknown_critical(self):
        assert await select_responder("unknown", "critical") == "police_dispatch"


# ===========================================================================
# select_responder -- high severity
# ===========================================================================


class TestSelectResponderHigh:
    @pytest.mark.asyncio
    async def test_medical_high(self):
        assert await select_responder("medical", "high") == "ambulance"

    @pytest.mark.asyncio
    async def test_mental_health_high(self):
        assert await select_responder("mental_health", "high") == "ambulance"

    @pytest.mark.asyncio
    async def test_fire_high(self):
        assert await select_responder("fire", "high") == "fire_dispatch"

    @pytest.mark.asyncio
    async def test_gas_hazard_high(self):
        assert await select_responder("gas_hazard", "high") == "fire_dispatch"

    @pytest.mark.asyncio
    async def test_robbery_high(self):
        assert await select_responder("robbery", "high") == "police_dispatch"

    @pytest.mark.asyncio
    async def test_unknown_high(self):
        assert await select_responder("unknown", "high") == "police_dispatch"


# ===========================================================================
# select_responder -- medium severity
# ===========================================================================


class TestSelectResponderMedium:
    @pytest.mark.asyncio
    async def test_medical_medium(self):
        assert await select_responder("medical", "medium") == "ambulance"

    @pytest.mark.asyncio
    async def test_fire_medium(self):
        assert await select_responder("fire", "medium") == "general_responder"

    @pytest.mark.asyncio
    async def test_unknown_medium(self):
        assert await select_responder("unknown", "medium") == "general_responder"

    @pytest.mark.asyncio
    async def test_mental_health_medium(self):
        """mental_health at medium severity goes to general_responder (not ambulance)."""
        assert await select_responder("mental_health", "medium") == "general_responder"


# ===========================================================================
# select_responder -- low severity
# ===========================================================================


class TestSelectResponderLow:
    @pytest.mark.asyncio
    async def test_any_intent_low(self):
        assert await select_responder("medical", "low") == "call_center_followup"

    @pytest.mark.asyncio
    async def test_fire_low(self):
        assert await select_responder("fire", "low") == "call_center_followup"

    @pytest.mark.asyncio
    async def test_unknown_low(self):
        assert await select_responder("unknown", "low") == "call_center_followup"


# ===========================================================================
# DispatchService.recommend
# ===========================================================================


class TestDispatchServiceRecommend:
    @pytest.fixture
    def service(self):
        return DispatchService()

    @pytest.mark.asyncio
    async def test_high_severity_score(self, service):
        result = await service.recommend(severity_score=9.0, incident_type="fire")
        assert result["unit_id"] == "police-12"
        assert result["eta_minutes"] == 4
        assert result["priority"] == "HIGH"

    @pytest.mark.asyncio
    async def test_medium_severity_score(self, service):
        result = await service.recommend(severity_score=6.0, incident_type="medical")
        assert result["unit_id"] == "responder-1"
        assert result["eta_minutes"] == 10
        assert result["priority"] == "MEDIUM"

    @pytest.mark.asyncio
    async def test_low_severity_score(self, service):
        result = await service.recommend(severity_score=3.0, incident_type="noise")
        assert result["unit_id"] == "monitor-0"
        assert result["eta_minutes"] is None
        assert result["priority"] == "LOW"

    @pytest.mark.asyncio
    async def test_boundary_score_8(self, service):
        """Exactly 8 is NOT > 8, so should fall to medium tier."""
        result = await service.recommend(severity_score=8.0, incident_type="theft")
        assert result["priority"] == "MEDIUM"

    @pytest.mark.asyncio
    async def test_boundary_score_5(self, service):
        """Exactly 5 is NOT > 5, so should fall to low tier."""
        result = await service.recommend(severity_score=5.0, incident_type="noise")
        assert result["priority"] == "LOW"

    @pytest.mark.asyncio
    async def test_boundary_score_above_8(self, service):
        result = await service.recommend(severity_score=8.1, incident_type="assault")
        assert result["priority"] == "HIGH"
