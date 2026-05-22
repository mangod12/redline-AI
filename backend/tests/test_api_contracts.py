"""API contract tests.

Verify that response schemas, enums, and service routing tables are
complete and match what clients expect. Pure logic tests -- no infra
(no DB, no Redis, no HTTP server) required.
"""

from __future__ import annotations

import asyncio
import itertools

import pytest

from app.api.v1.endpoints.emergency import EmergencyResponse
from app.core.schemas.emotion import EmotionType
from app.core.schemas.intent import IntentType
from app.core.schemas.severity import SeverityLevel
from app.services.dispatch_service import select_responder
from app.services.severity_service import compute_severity

# ---------------------------------------------------------------------------
# Constants the client contract depends on
# ---------------------------------------------------------------------------

EXPECTED_INTENTS = frozenset(
    [
        "medical",
        "fire",
        "violent_crime",
        "accident",
        "gas_hazard",
        "mental_health",
        "non_emergency",
        "unknown",
    ]
)

EXPECTED_EMOTIONS = frozenset(
    [
        "anger",
        "fear",
        "sadness",
        "joy",
        "surprise",
        "disgust",
        "neutral",
    ]
)

EXPECTED_SEVERITY_LEVELS = frozenset(["low", "medium", "high", "critical"])

VALID_RESPONDERS = frozenset(
    [
        "police_dispatch",
        "fire_dispatch",
        "ambulance",
        "general_responder",
        "call_center_followup",
    ]
)


# ===================================================================
# 1. EmergencyResponse schema -- required fields and types
# ===================================================================


class TestEmergencyResponseSchema:
    """Verify the EmergencyResponse Pydantic model matches the client contract."""

    REQUIRED_FIELDS: dict[str, type] = {
        "call_id": str,
        "transcript": str,
        "intent": str,
        "intent_confidence": float,
        "emotion": str,
        "severity": str,
        "responder": str,
        "latency_ms": int,
        "caller_id": (str, type(None)),  # Optional[str]
    }

    def test_all_required_fields_present(self) -> None:
        field_names = set(EmergencyResponse.model_fields.keys())
        for name in self.REQUIRED_FIELDS:
            assert name in field_names, f"Missing field: {name}"

    @pytest.mark.parametrize(
        "field_name",
        [
            "call_id",
            "transcript",
            "intent",
            "intent_confidence",
            "emotion",
            "severity",
            "responder",
            "latency_ms",
            "caller_id",
        ],
    )
    def test_field_exists_in_schema(self, field_name: str) -> None:
        assert field_name in EmergencyResponse.model_fields

    def test_no_unexpected_fields(self) -> None:
        """Schema should not silently grow extra fields that break clients."""
        actual = set(EmergencyResponse.model_fields.keys())
        expected = set(self.REQUIRED_FIELDS.keys())
        assert actual == expected, f"Unexpected fields: {actual - expected}"

    def test_roundtrip_serialization(self) -> None:
        """A valid response can be serialized to dict and back."""
        payload = EmergencyResponse(
            call_id="abc-123",
            transcript="help there is a fire",
            intent="fire",
            intent_confidence=0.95,
            emotion="fear",
            severity="high",
            responder="fire_dispatch",
            latency_ms=42,
            caller_id=None,
        )
        data = payload.model_dump()
        restored = EmergencyResponse.model_validate(data)
        assert restored == payload

    def test_json_roundtrip(self) -> None:
        """JSON serialization produces the exact keys clients parse."""
        payload = EmergencyResponse(
            call_id="abc-123",
            transcript="someone is hurt",
            intent="medical",
            intent_confidence=0.88,
            emotion="sadness",
            severity="medium",
            responder="ambulance",
            latency_ms=100,
            caller_id="caller-1",
        )
        json_str = payload.model_dump_json()
        restored = EmergencyResponse.model_validate_json(json_str)
        assert restored == payload

    def test_caller_id_nullable(self) -> None:
        """caller_id may be None (anonymous callers)."""
        payload = EmergencyResponse(
            call_id="x",
            transcript="t",
            intent="unknown",
            intent_confidence=0.0,
            emotion="neutral",
            severity="low",
            responder="call_center_followup",
            latency_ms=0,
            caller_id=None,
        )
        assert payload.caller_id is None


# ===================================================================
# 2. IntentType completeness
# ===================================================================


class TestIntentTypeEnum:
    """All 8 intent types exist and match the expected string values."""

    def test_count(self) -> None:
        assert len(IntentType) == 8

    @pytest.mark.parametrize("value", sorted(EXPECTED_INTENTS))
    def test_member_exists(self, value: str) -> None:
        assert value in {m.value for m in IntentType}

    def test_exact_set(self) -> None:
        actual = {m.value for m in IntentType}
        assert actual == EXPECTED_INTENTS

    @pytest.mark.parametrize("member", list(IntentType))
    def test_str_conversion(self, member: IntentType) -> None:
        """StrEnum members must equal their string value."""
        assert str(member) == member.value


# ===================================================================
# 3. EmotionType completeness
# ===================================================================


class TestEmotionTypeEnum:
    """All 7 emotion types exist and match the expected string values."""

    def test_count(self) -> None:
        assert len(EmotionType) == 7

    @pytest.mark.parametrize("value", sorted(EXPECTED_EMOTIONS))
    def test_member_exists(self, value: str) -> None:
        assert value in {m.value for m in EmotionType}

    def test_exact_set(self) -> None:
        actual = {m.value for m in EmotionType}
        assert actual == EXPECTED_EMOTIONS

    @pytest.mark.parametrize("member", list(EmotionType))
    def test_str_conversion(self, member: EmotionType) -> None:
        assert str(member) == member.value


# ===================================================================
# 4. SeverityLevel completeness
# ===================================================================


class TestSeverityLevelEnum:
    """All 4 severity levels exist and match expected string values."""

    def test_count(self) -> None:
        assert len(SeverityLevel) == 4

    @pytest.mark.parametrize("value", sorted(EXPECTED_SEVERITY_LEVELS))
    def test_member_exists(self, value: str) -> None:
        assert value in {m.value for m in SeverityLevel}

    def test_exact_set(self) -> None:
        actual = {m.value for m in SeverityLevel}
        assert actual == EXPECTED_SEVERITY_LEVELS

    @pytest.mark.parametrize("member", list(SeverityLevel))
    def test_str_conversion(self, member: SeverityLevel) -> None:
        assert str(member) == member.value


# ===================================================================
# 5. Dispatch routing completeness -- every (intent, severity) pair
# ===================================================================


_ALL_INTENT_SEVERITY_PAIRS = list(
    itertools.product(
        sorted(EXPECTED_INTENTS),
        sorted(EXPECTED_SEVERITY_LEVELS),
    )
)


class TestDispatchRouting:
    """Every combination of intent x severity must produce a valid responder."""

    @pytest.mark.parametrize(
        "intent,severity",
        _ALL_INTENT_SEVERITY_PAIRS,
        ids=[f"{i}-{s}" for i, s in _ALL_INTENT_SEVERITY_PAIRS],
    )
    def test_valid_responder_returned(self, intent: str, severity: str) -> None:
        result = asyncio.run(select_responder(intent, severity))
        assert result in VALID_RESPONDERS, (
            f"select_responder({intent!r}, {severity!r}) returned "
            f"{result!r}, expected one of {VALID_RESPONDERS}"
        )

    @pytest.mark.parametrize(
        "intent,severity",
        _ALL_INTENT_SEVERITY_PAIRS,
        ids=[f"{i}-{s}" for i, s in _ALL_INTENT_SEVERITY_PAIRS],
    )
    def test_responder_is_string(self, intent: str, severity: str) -> None:
        result = asyncio.run(select_responder(intent, severity))
        assert isinstance(result, str)

    def test_critical_fire_goes_to_fire_dispatch(self) -> None:
        result = asyncio.run(select_responder("fire", "critical"))
        assert result == "fire_dispatch"

    def test_critical_medical_goes_to_ambulance(self) -> None:
        result = asyncio.run(select_responder("medical", "critical"))
        assert result == "ambulance"

    def test_low_severity_goes_to_call_center(self) -> None:
        result = asyncio.run(select_responder("unknown", "low"))
        assert result == "call_center_followup"


# ===================================================================
# 6. Severity service -- emotion promotion rules
# ===================================================================

# Emotions that SHOULD promote severity
_HIGH_URGENCY_EMOTIONS = ["fear", "anger"]
# Emotions that promote only from low -> medium
_MEDIUM_URGENCY_EMOTIONS = ["sadness", "surprise", "disgust"]
# Emotions that never promote
_NEUTRAL_EMOTIONS = ["joy", "neutral"]


class TestSeverityEmotionPromotion:
    """Verify emotion-based severity promotion logic."""

    @pytest.mark.parametrize("emotion", _HIGH_URGENCY_EMOTIONS)
    def test_high_urgency_emotion_promotes_low_to_medium(self, emotion: str) -> None:
        """Fear/anger on a low-keyword transcript should promote to medium."""
        result = asyncio.run(
            compute_severity("I lost my cat", emotion)
        )
        assert result == "medium", (
            f"emotion={emotion!r} should promote 'low' -> 'medium'"
        )

    @pytest.mark.parametrize("emotion", _HIGH_URGENCY_EMOTIONS)
    def test_high_urgency_emotion_promotes_medium_to_high(self, emotion: str) -> None:
        result = asyncio.run(
            compute_severity("I am hurt and scared", emotion)
        )
        assert result == "high", (
            f"emotion={emotion!r} should promote 'medium' -> 'high'"
        )

    @pytest.mark.parametrize("emotion", _HIGH_URGENCY_EMOTIONS)
    def test_high_urgency_emotion_promotes_high_to_critical(self, emotion: str) -> None:
        result = asyncio.run(
            compute_severity("there is a fire and bleeding", emotion)
        )
        assert result == "critical", (
            f"emotion={emotion!r} should promote 'high' -> 'critical'"
        )

    @pytest.mark.parametrize("emotion", _HIGH_URGENCY_EMOTIONS)
    def test_high_urgency_emotion_caps_at_critical(self, emotion: str) -> None:
        result = asyncio.run(
            compute_severity("someone was shot and is dying", emotion)
        )
        assert result == "critical"

    @pytest.mark.parametrize("emotion", _MEDIUM_URGENCY_EMOTIONS)
    def test_medium_urgency_emotion_promotes_low_to_medium(self, emotion: str) -> None:
        result = asyncio.run(
            compute_severity("I lost my cat", emotion)
        )
        assert result == "medium", (
            f"emotion={emotion!r} should promote 'low' -> 'medium'"
        )

    @pytest.mark.parametrize("emotion", _MEDIUM_URGENCY_EMOTIONS)
    def test_medium_urgency_emotion_does_not_promote_above_medium(
        self, emotion: str
    ) -> None:
        """sadness/surprise/disgust only promote low->medium, not higher."""
        result = asyncio.run(
            compute_severity("there is a fire and bleeding", emotion)
        )
        assert result == "high", (
            f"emotion={emotion!r} should NOT promote 'high' further"
        )

    @pytest.mark.parametrize("emotion", _NEUTRAL_EMOTIONS)
    def test_neutral_emotion_does_not_promote(self, emotion: str) -> None:
        result = asyncio.run(
            compute_severity("I lost my cat", emotion)
        )
        assert result == "low", (
            f"emotion={emotion!r} should NOT promote severity"
        )


# ===================================================================
# 7. Pipeline contract -- compute_severity returns valid level
# ===================================================================

_SAMPLE_TRANSCRIPTS = [
    "someone was shot and is dying",
    "there is a fire in the building",
    "I fell and I am hurt",
    "I lost my wallet",
    "this is a non-emergency follow up",
    "",
    "abcdefg random text no keywords",
]


class TestComputeSeverityContract:
    """compute_severity always returns one of the 4 valid severity strings."""

    @pytest.mark.parametrize(
        "transcript,emotion",
        list(itertools.product(_SAMPLE_TRANSCRIPTS, sorted(EXPECTED_EMOTIONS))),
        ids=[
            f"{t[:20]}...-{e}"
            for t, e in itertools.product(
                _SAMPLE_TRANSCRIPTS, sorted(EXPECTED_EMOTIONS)
            )
        ],
    )
    def test_returns_valid_level(self, transcript: str, emotion: str) -> None:
        result = asyncio.run(
            compute_severity(transcript, emotion)
        )
        assert result in EXPECTED_SEVERITY_LEVELS, (
            f"compute_severity({transcript!r}, {emotion!r}) returned "
            f"{result!r}, expected one of {EXPECTED_SEVERITY_LEVELS}"
        )


# ===================================================================
# 8. Pipeline contract -- select_responder returns valid responder
# ===================================================================


class TestSelectResponderContract:
    """select_responder always returns one of the 5 valid responder strings."""

    @pytest.mark.parametrize(
        "intent,severity",
        _ALL_INTENT_SEVERITY_PAIRS,
        ids=[f"{i}-{s}" for i, s in _ALL_INTENT_SEVERITY_PAIRS],
    )
    def test_returns_valid_responder(self, intent: str, severity: str) -> None:
        result = asyncio.run(
            select_responder(intent, severity)
        )
        assert result in VALID_RESPONDERS

    def test_responder_count(self) -> None:
        """All 5 responder types are reachable from some (intent, severity) pair."""
        seen: set[str] = set()
        for intent, severity in _ALL_INTENT_SEVERITY_PAIRS:
            result = asyncio.run(
                select_responder(intent, severity)
            )
            seen.add(result)
        assert seen == VALID_RESPONDERS, (
            f"Not all responders reachable. Missing: {VALID_RESPONDERS - seen}"
        )
