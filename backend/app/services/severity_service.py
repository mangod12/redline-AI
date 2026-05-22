"""Severity scoring service.

Combines keyword signals from the transcript with the emotion label
returned by the EmotionAgent to produce a four-level severity string.
"""

from __future__ import annotations

# Keywords that push severity higher
_CRITICAL_KW = frozenset(
    [
        "dying",
        "dead",
        "not breathing",
        "gun",
        "shot",
        "stabbed",
        "explosion",
        "major accident",
        "cardiac arrest",
        "unconscious",
        "no pulse",
        "overdose",
        "active shooter",
        "hostage",
        "mass casualty",
        "collapsed building",
        "bomb",
        "chest pain",
        "seizure",
    ]
)

_HIGH_KW = frozenset(
    [
        "fire",
        "blood",
        "bleeding",
        "can't breathe",
        "choking",
        "broken",
        "serious",
        "pain",
        "emergency",
        "crash",
        "collision",
        "trapped",
        "assault",
        "robbery",
        "weapon",
        "knife",
        "smoke",
        "gas leak",
        "carbon monoxide",
        "suicide",
        "self harm",
        "heart attack",
        "burning",
    ]
)

_MEDIUM_KW = frozenset(
    [
        "hurt",
        "injury",
        "sick",
        "fell",
        "help",
        "scared",
        "worried",
        "anxiety",
        "accident",
        "fender bender",
        "dizzy",
        "faint",
        "mental",
        "crisis",
        "panic",
        "distress",
        "agitated",
        "bad",
    ]
)

# Emotions that boost severity level up by one tier
_HIGH_URGENCY_EMOTIONS = frozenset(["fear", "anger"])
_MEDIUM_URGENCY_EMOTIONS = frozenset(["sadness", "surprise", "disgust"])


async def compute_severity(transcript: str, emotion: str) -> str:
    """Return one of: critical | high | medium | low.

    Args:
        transcript: Raw transcribed text.
        emotion:    Primary emotion string from EmotionAgent
                    (e.g. "fear", "neutral", "sadness").
    """
    lower = transcript.lower()

    # Check for explicit non-emergency phrases first (prevents "emergency" substring match)
    _NON_EMERGENCY_PHRASES = (
        "non emergency",
        "non-emergency",
        "nonemergency",
        "follow up",
        "follow-up",
    )
    if any(phrase in lower for phrase in _NON_EMERGENCY_PHRASES):
        base = "low"
    elif any(kw in lower for kw in _CRITICAL_KW):
        base = "critical"
    elif any(kw in lower for kw in _HIGH_KW):
        base = "high"
    elif any(kw in lower for kw in _MEDIUM_KW):
        base = "medium"
    else:
        base = "low"

    # Optionally promote by one tier based on emotion
    if emotion in _HIGH_URGENCY_EMOTIONS:
        base = _promote(base)
    elif emotion in _MEDIUM_URGENCY_EMOTIONS and base == "low":
        base = "medium"

    return base


_TIERS = ["low", "medium", "high", "critical"]


def _promote(level: str) -> str:
    """Bump severity one tier up (capped at critical)."""
    try:
        idx = _TIERS.index(level)
        return _TIERS[min(idx + 1, len(_TIERS) - 1)]
    except ValueError:
        return level
