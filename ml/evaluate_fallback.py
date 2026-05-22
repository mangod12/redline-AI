"""Evaluate keyword fallback accuracy against labeled test cases.

Measures how well the heuristic fallback classifies intent and emotion
when ML models are unavailable. Run without any model files — pure
keyword matching evaluation.

Usage:
    python ml/evaluate_fallback.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import os
from dataclasses import dataclass
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.agents.intent.intent_agent import IntentAgent, _keyword_fallback
from app.agents.emotion.emotion_agent import _heuristic_emotion
from app.core.schemas.intent import IntentType
from app.core.schemas.emotion import EmotionType
from app.services.severity_service import compute_severity
from app.services.dispatch_service import select_responder


@dataclass
class TestCase:
    text: str
    expected_intent: IntentType
    expected_severity: str  # critical/high/medium/low
    expected_emotion: EmotionType | None = None  # None = don't check


# Ground truth test cases covering all intent categories
TEST_CASES: list[TestCase] = [
    # MEDICAL
    TestCase("caller reports chest pain and difficulty breathing", IntentType.MEDICAL, "critical"),
    TestCase("someone collapsed unconscious at the park", IntentType.MEDICAL, "critical"),
    TestCase("elderly person fell and has a head injury", IntentType.MEDICAL, "medium"),
    TestCase("child has a seizure need ambulance now", IntentType.MEDICAL, "critical"),
    TestCase("possible overdose found person unresponsive", IntentType.MEDICAL, "critical"),

    # FIRE
    TestCase("fire in the kitchen smoke everywhere", IntentType.FIRE, "high"),
    TestCase("building on fire flames visible from outside", IntentType.FIRE, "high"),
    TestCase("smell of smoke coming from neighbor apartment", IntentType.FIRE, "high"),
    TestCase("burning car on the highway", IntentType.FIRE, "high"),

    # VIOLENT CRIME
    TestCase("someone with a gun threatening people", IntentType.VIOLENT_CRIME, "critical"),
    TestCase("armed robbery at the convenience store", IntentType.VIOLENT_CRIME, "critical"),
    TestCase("person was stabbed bleeding heavily", IntentType.VIOLENT_CRIME, "critical"),
    TestCase("domestic assault in progress screaming", IntentType.VIOLENT_CRIME, "high"),

    # ACCIDENT
    TestCase("two car collision on the highway", IntentType.ACCIDENT, "high"),
    TestCase("vehicle crash with people trapped inside", IntentType.ACCIDENT, "high"),
    TestCase("minor fender bender no injuries", IntentType.ACCIDENT, "medium"),

    # GAS HAZARD
    TestCase("strong gas leak smell in the basement", IntentType.GAS_HAZARD, "high"),
    TestCase("possible carbon monoxide people feeling dizzy", IntentType.GAS_HAZARD, "high"),

    # MENTAL HEALTH
    TestCase("person threatening suicide on bridge", IntentType.MENTAL_HEALTH, "high"),
    TestCase("someone in a mental health crisis very agitated", IntentType.MENTAL_HEALTH, "medium"),

    # NON-EMERGENCY
    TestCase("noise complaint loud music from neighbor", IntentType.NON_EMERGENCY, "low"),
    TestCase("lost wallet at the parking lot need information", IntentType.NON_EMERGENCY, "low"),
    TestCase("non emergency just want to follow up on report", IntentType.NON_EMERGENCY, "low"),

    # UNKNOWN / ambiguous
    TestCase("hello is anyone there please help me", IntentType.UNKNOWN, "medium"),
    TestCase("something bad happened I dont know what to do", IntentType.UNKNOWN, "medium"),
]


def evaluate_intent_fallback() -> dict:
    """Evaluate keyword fallback intent classification."""
    correct = 0
    total = len(TEST_CASES)
    errors: list[dict] = []

    for tc in TEST_CASES:
        result = _keyword_fallback(tc.text, "evaluation")
        predicted = result.intent
        if predicted == tc.expected_intent:
            correct += 1
        else:
            errors.append({
                "text": tc.text[:60],
                "expected": tc.expected_intent.value,
                "predicted": predicted.value,
                "confidence": result.confidence,
            })

    accuracy = correct / total if total > 0 else 0.0
    return {
        "intent_accuracy": round(accuracy * 100, 1),
        "correct": correct,
        "total": total,
        "errors": errors,
    }


async def evaluate_severity() -> dict:
    """Evaluate severity scoring against ground truth."""
    correct = 0
    total = len(TEST_CASES)
    errors: list[dict] = []

    for tc in TEST_CASES:
        predicted = await compute_severity(tc.text, "neutral")
        if predicted == tc.expected_severity:
            correct += 1
        else:
            errors.append({
                "text": tc.text[:60],
                "expected": tc.expected_severity,
                "predicted": predicted,
            })

    accuracy = correct / total if total > 0 else 0.0
    return {
        "severity_accuracy": round(accuracy * 100, 1),
        "correct": correct,
        "total": total,
        "errors": errors,
    }


def evaluate_emotion_heuristic() -> dict:
    """Evaluate heuristic emotion classification."""
    urgency_texts = [
        "help emergency fire gun blood dying",
        "someone attacked weapon explosion crash",
    ]
    calm_texts = [
        "hello how are you today",
        "I would like some information please",
    ]

    urgency_correct = sum(
        1 for t in urgency_texts
        if _heuristic_emotion(t).primary_emotion == EmotionType.FEAR
    )
    calm_correct = sum(
        1 for t in calm_texts
        if _heuristic_emotion(t).primary_emotion == EmotionType.NEUTRAL
    )

    total = len(urgency_texts) + len(calm_texts)
    correct = urgency_correct + calm_correct

    return {
        "emotion_accuracy": round(correct / total * 100, 1) if total > 0 else 0.0,
        "urgency_correct": f"{urgency_correct}/{len(urgency_texts)}",
        "calm_correct": f"{calm_correct}/{len(calm_texts)}",
    }


async def evaluate_dispatch_routing() -> dict:
    """Verify dispatch routing covers all severity x intent combinations."""
    intents = [e.value for e in IntentType]
    severities = ["critical", "high", "medium", "low"]
    missing = []

    for intent in intents:
        for sev in severities:
            responder = await select_responder(intent, sev)
            if not responder:
                missing.append({"intent": intent, "severity": sev})

    return {
        "total_combinations": len(intents) * len(severities),
        "all_covered": len(missing) == 0,
        "missing": missing,
    }


async def main():
    print("=" * 60)
    print("REDLINE AI — FALLBACK EVALUATION REPORT")
    print("=" * 60)

    # Intent
    intent_results = evaluate_intent_fallback()
    print(f"\n--- Intent Fallback Accuracy: {intent_results['intent_accuracy']}% "
          f"({intent_results['correct']}/{intent_results['total']})")
    if intent_results["errors"]:
        print("  Misclassifications:")
        for e in intent_results["errors"]:
            print(f"    '{e['text']}' -> expected={e['expected']}, got={e['predicted']}")

    # Severity
    severity_results = await evaluate_severity()
    print(f"\n--- Severity Accuracy: {severity_results['severity_accuracy']}% "
          f"({severity_results['correct']}/{severity_results['total']})")
    if severity_results["errors"]:
        print("  Misclassifications:")
        for e in severity_results["errors"]:
            print(f"    '{e['text']}' -> expected={e['expected']}, got={e['predicted']}")

    # Emotion
    emotion_results = evaluate_emotion_heuristic()
    print(f"\n--- Emotion Heuristic Accuracy: {emotion_results['emotion_accuracy']}%")
    print(f"    Urgency detection: {emotion_results['urgency_correct']}")
    print(f"    Calm detection: {emotion_results['calm_correct']}")

    # Dispatch coverage
    dispatch_results = await evaluate_dispatch_routing()
    print(f"\n--- Dispatch Routing: {dispatch_results['total_combinations']} combinations, "
          f"all covered={dispatch_results['all_covered']}")

    # Summary
    print("\n" + "=" * 60)
    avg = (intent_results["intent_accuracy"] + severity_results["severity_accuracy"]
           + emotion_results["emotion_accuracy"]) / 3
    print(f"OVERALL FALLBACK QUALITY: {avg:.1f}%")
    print("=" * 60)

    return {
        "intent": intent_results,
        "severity": severity_results,
        "emotion": emotion_results,
        "dispatch": dispatch_results,
    }


if __name__ == "__main__":
    asyncio.run(main())
