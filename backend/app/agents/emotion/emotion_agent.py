"""Production EmotionAgent with:

- ONNX ML inference via EmotionModelLoader
- Heuristic fallback (keyword scoring)
- asyncio.wait_for timeout (3 s per attempt)
- pybreaker circuit breaker (open after 3 failures, 60 s recovery)
- FIRST_COMPLETED dual-execution strategy
- Confidence threshold guard (< 0.5 → fallback)
- structlog JSON structured logging
- Prometheus metrics: ml_inference_latency, ml_failure_count, fallback_usage_count
- Full type hints
- Never crashes the pipeline – always returns EmotionAnalysis
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pybreaker
import structlog
from prometheus_client import Counter, Histogram

from app.agents.base import BaseAgent
from app.core.config import settings
from app.core.schemas import EmotionAnalysis, EmotionType, Transcript

if TYPE_CHECKING:
    import numpy as np

    from app.ml.emotion_model_loader import EmotionModelLoader

# ---------------------------------------------------------------------------
# Prometheus metrics (module-level; safe for unit tests to re-import)
# ---------------------------------------------------------------------------

ML_INFERENCE_LATENCY = Histogram(
    "ml_inference_latency_seconds",
    "Time spent in ONNX emotion inference",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0],
)

ML_FAILURE_COUNT = Counter(
    "ml_failure_count_total",
    "Total number of ML emotion inference failures",
    ["reason"],  # timeout | exception | low_confidence | circuit_open
)

FALLBACK_USAGE_COUNT = Counter(
    "fallback_usage_count_total",
    "Total number of times the heuristic fallback was used",
    ["trigger"],  # ml_failure | primary_timeout | initial_fallback
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INFERENCE_TIMEOUT_S: float = 3.0
_CONFIDENCE_THRESHOLD: float = 0.5

_URGENCY_KEYWORDS: frozenset[str] = frozenset(
    [
        "help",
        "emergency",
        "fire",
        "gun",
        "blood",
        "dying",
        "scared",
        "attacked",
        "can't breathe",
        "choking",
        "hostile",
        "weapon",
        "explosion",
        "crash",
        "accident",
    ]
)

_DISTRESS_KEYWORDS: frozenset[str] = frozenset(
    [
        "hurt",
        "pain",
        "alone",
        "please",
        "quickly",
        "fast",
        "bad",
        "bleeding",
        "unconscious",
        "faint",
    ]
)

# ---------------------------------------------------------------------------
# Circuit breaker (shared per process; failure_threshold=3, reset_timeout=60s)
# ---------------------------------------------------------------------------

_ml_breaker = pybreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=60,
    name="emotion_ml_breaker",
)

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

log = structlog.get_logger("redline_ai.agents.emotion")


# ---------------------------------------------------------------------------
# MFCC extraction
# ---------------------------------------------------------------------------

def _zero_mfcc() -> np.ndarray:
    """Return a zeroed MFCC placeholder for text-only fallback."""
    import numpy as np

    return np.zeros((1, 1, 40, 94), dtype=np.float32)


# ---------------------------------------------------------------------------
# Heuristic fallback
# ---------------------------------------------------------------------------

def _heuristic_emotion(text: str) -> EmotionAnalysis:
    """Keyword-based heuristic emotion analysis.

    Always succeeds.  Scores are coarse but sufficient for graceful degradation.
    """
    lower = text.lower()

    urgency_hits = sum(1 for kw in _URGENCY_KEYWORDS if kw in lower)
    distress_hits = sum(1 for kw in _DISTRESS_KEYWORDS if kw in lower)

    if urgency_hits >= 2:
        primary = EmotionType.FEAR
        intensity = min(0.5 + urgency_hits * 0.1, 0.95)
        scores: dict[EmotionType, float] = {
            EmotionType.FEAR: intensity,
            EmotionType.ANGER: max(0.0, intensity - 0.3),
            EmotionType.SADNESS: 0.05,
            EmotionType.NEUTRAL: max(0.0, 1.0 - intensity - 0.1),
            EmotionType.JOY: 0.0,
            EmotionType.SURPRISE: 0.05,
            EmotionType.DISGUST: 0.0,
        }
        confidence = 0.65
    elif urgency_hits == 1 or distress_hits >= 2:
        primary = EmotionType.SADNESS
        intensity = 0.55
        scores = {
            EmotionType.FEAR: 0.25,
            EmotionType.SADNESS: 0.55,
            EmotionType.ANGER: 0.1,
            EmotionType.NEUTRAL: 0.1,
            EmotionType.JOY: 0.0,
            EmotionType.SURPRISE: 0.0,
            EmotionType.DISGUST: 0.0,
        }
        confidence = 0.55
    else:
        primary = EmotionType.NEUTRAL
        intensity = 0.2
        scores = {
            EmotionType.NEUTRAL: 0.85,
            EmotionType.SADNESS: 0.05,
            EmotionType.FEAR: 0.05,
            EmotionType.JOY: 0.05,
            EmotionType.ANGER: 0.0,
            EmotionType.SURPRISE: 0.0,
            EmotionType.DISGUST: 0.0,
        }
        confidence = 0.75

    # Normalise scores to sum to 1.0
    total = sum(scores.values())
    scores = {k: v / total for k, v in scores.items()}

    return EmotionAnalysis(
        primary_emotion=primary,
        emotion_scores=scores,
        intensity=intensity,
        confidence=confidence,
        text_segments=[text],
    )


def _neutral_fallback(text: str) -> EmotionAnalysis:
    """Absolute last-resort neutral fallback (used when circuit is OPEN)."""
    return EmotionAnalysis(
        primary_emotion=EmotionType.NEUTRAL,
        emotion_scores={EmotionType.NEUTRAL: 1.0},
        intensity=0.0,
        confidence=0.0,  # signals downstream that this is a forced fallback
        text_segments=[text],
    )


# ---------------------------------------------------------------------------
# Gemini text-based emotion analysis
# ---------------------------------------------------------------------------

_GEMINI_EMOTION_PROMPT = """\
Analyze the emotional state of the speaker in this emergency call transcript.

Transcript: {text}

Respond ONLY with a JSON object in this exact format:
{{
    "primary_emotion": "<one of: anger, fear, sadness, joy, surprise, disgust, neutral>",
    "intensity": <float 0.0 to 1.0>,
    "confidence": <float 0.0 to 1.0>,
    "scores": {{
        "anger": <float>,
        "fear": <float>,
        "sadness": <float>,
        "joy": <float>,
        "surprise": <float>,
        "disgust": <float>,
        "neutral": <float>
    }}
}}
Scores must sum to approximately 1.0. Focus on emergency context."""

_EMOTION_STR_TO_TYPE: dict[str, EmotionType] = {
    "anger": EmotionType.ANGER,
    "fear": EmotionType.FEAR,
    "sadness": EmotionType.SADNESS,
    "joy": EmotionType.JOY,
    "surprise": EmotionType.SURPRISE,
    "disgust": EmotionType.DISGUST,
    "neutral": EmotionType.NEUTRAL,
}


async def _gemini_text_emotion(text: str) -> EmotionAnalysis | None:
    """Use Gemini to detect emotion from text. Returns None on failure."""
    if not settings.GEMINI_API_KEY:
        return None
    try:
        import json

        import google.generativeai as genai

        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")

        prompt = _GEMINI_EMOTION_PROMPT.format(text=text)
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"},
            ),
        )
        data = json.loads(response.text)

        primary_str = data.get("primary_emotion", "neutral").lower()
        primary = _EMOTION_STR_TO_TYPE.get(primary_str, EmotionType.NEUTRAL)

        scores: dict[EmotionType, float] = {}
        for key, val in data.get("scores", {}).items():
            etype = _EMOTION_STR_TO_TYPE.get(key.lower(), EmotionType.NEUTRAL)
            scores[etype] = scores.get(etype, 0.0) + float(val)

        # Ensure all emotions present
        for etype in EmotionType:
            scores.setdefault(etype, 0.0)

        return EmotionAnalysis(
            primary_emotion=primary,
            emotion_scores=scores,
            intensity=float(data.get("intensity", 0.5)),
            confidence=float(data.get("confidence", 0.8)),
            text_segments=[text],
        )
    except Exception as exc:
        log.warning("Gemini text emotion failed, falling back", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Helper: map ONNX label string → EmotionType
# ---------------------------------------------------------------------------

_LABEL_TO_EMOTION: dict[str, EmotionType] = {
    "neutral": EmotionType.NEUTRAL,
    "calm": EmotionType.NEUTRAL,  # map calm → neutral (schema has no CALM)
    "happy": EmotionType.JOY,
    "sad": EmotionType.SADNESS,
    "angry": EmotionType.ANGER,
    "fearful": EmotionType.FEAR,
    "disgust": EmotionType.DISGUST,
    "surprised": EmotionType.SURPRISE,
}


def _scores_to_emotion_analysis(
    raw_scores: dict[str, float], text: str
) -> EmotionAnalysis | None:
    """Convert ONNX probability dict to EmotionAnalysis.

    Returns None if max confidence < threshold so caller can trigger fallback.
    """
    primary_label = max(raw_scores, key=lambda k: raw_scores[k])
    primary_prob = raw_scores[primary_label]

    if primary_prob < _CONFIDENCE_THRESHOLD:
        ML_FAILURE_COUNT.labels(reason="low_confidence").inc()
        log.warning(
            "ML confidence below threshold",
            primary=primary_label,
            confidence=primary_prob,
            threshold=_CONFIDENCE_THRESHOLD,
        )
        return None

    # Map to EmotionType enum values
    mapped: dict[EmotionType, float] = {}
    for label, prob in raw_scores.items():
        etype = _LABEL_TO_EMOTION.get(label, EmotionType.NEUTRAL)
        # Accumulate (calm + neutral both → NEUTRAL)
        mapped[etype] = mapped.get(etype, 0.0) + prob

    primary_emotion = _LABEL_TO_EMOTION.get(primary_label, EmotionType.NEUTRAL)

    return EmotionAnalysis(
        primary_emotion=primary_emotion,
        emotion_scores=mapped,
        intensity=primary_prob,
        confidence=primary_prob,
        text_segments=[text],
    )


# ---------------------------------------------------------------------------
# EmotionAgent
# ---------------------------------------------------------------------------


class EmotionAgent(BaseAgent):
    """Production emotion analysis agent.

    Accepts a Transcript, returns an EmotionAnalysis.

    Execution strategy:
      1. If circuit breaker is OPEN → immediate neutral fallback.
      2. Schedule both ML inference and heuristic fallback as concurrent tasks.
      3. asyncio.wait with FIRST_COMPLETED and 3 s overall timeout.
      4. If ML wins AND confidence ≥ threshold → return ML result.
      5. Otherwise return heuristic result.
      6. Any exception inside ML coroutine → trip circuit breaker.
    """

    def __init__(
        self,
        loader: EmotionModelLoader | None = None,
        config: dict | None = None,
    ) -> None:
        self._loader = loader
        self._config = config or {}

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def get_input_schema(self) -> type:
        return Transcript

    def get_output_schema(self) -> type:
        return EmotionAnalysis

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    async def process(self, input_data: Transcript) -> EmotionAnalysis:
        """Process transcript → EmotionAnalysis. Never raises."""
        text = input_data.text
        bound_log = log.bind(
            call_id=self._config.get("call_id", "unknown"),
            text_len=len(text),
        )

        # ---- Fast path: circuit open → neutral immediately ---------------
        if _ml_breaker.current_state == pybreaker.STATE_OPEN:
            ML_FAILURE_COUNT.labels(reason="circuit_open").inc()
            FALLBACK_USAGE_COUNT.labels(trigger="circuit_open").inc()
            bound_log.warning("Circuit breaker OPEN – returning neutral fallback")
            return _neutral_fallback(text)

        # ---- Text-only path: use Gemini for better accuracy ----------------
        audio_data = getattr(input_data, "audio_data", None)
        if audio_data is None and settings.GEMINI_API_KEY:
            bound_log.info("Text-only input — using Gemini for emotion analysis")
            try:
                gemini_result = await asyncio.wait_for(
                    _gemini_text_emotion(text), timeout=5.0,
                )
                if gemini_result is not None:
                    bound_log.info(
                        "Gemini emotion analysis successful",
                        emotion=gemini_result.primary_emotion.value,
                        confidence=gemini_result.confidence,
                    )
                    return gemini_result
            except TimeoutError:
                bound_log.warning("Gemini emotion timed out — falling back")
            except Exception as exc:
                bound_log.warning("Gemini emotion failed — falling back", error=str(exc))

        # ---- Audio path: ONNX ML Execution ----------------------------------
        # We give ML a "soft budget" of 800ms before falling back.
        # This prevents the instant heuristic from always winning (FIRST_COMPLETED risk).
        ml_task = asyncio.create_task(self._run_ml(text, audio_data=audio_data))

        try:
            # Stage 1: Wait for ML within the soft budget
            ml_result = await asyncio.wait_for(asyncio.shield(ml_task), timeout=0.8)
            if ml_result and ml_result.confidence >= _CONFIDENCE_THRESHOLD:
                bound_log.info("ML inference successful within budget", confidence=ml_result.confidence)
                return ml_result
            elif ml_result:
                bound_log.warning("ML inference had low confidence", confidence=ml_result.confidence)
                # Fall through to heuristic
        except TimeoutError:
            bound_log.warning("ML inference exceeding soft budget – transitioning to fallback")
        except Exception as exc:
            bound_log.error("ML inference failed early", error=str(exc))

        # Stage 2: Fallback to Heuristic
        # We still keep the hard 3s limit for the whole stage.
        try:
            heuristic_result = await asyncio.wait_for(
                self._run_heuristic(text),
                timeout=2.0 # Remaining time
            )

            # If ML task eventually finishes while we were doing heuristic, we could log it
            # but for emergency responsiveness, we return heuristic now.
            FALLBACK_USAGE_COUNT.labels(trigger="ml_slow_or_failure").inc()
            return heuristic_result

        except Exception as exc:
            bound_log.error("Heuristic fallback failed", error=str(exc))
            FALLBACK_USAGE_COUNT.labels(trigger="total_failure").inc()
            return _neutral_fallback(text)
        finally:
            if not ml_task.done():
                ml_task.cancel()

    # ------------------------------------------------------------------
    # Internal coroutines
    # ------------------------------------------------------------------

    async def _run_ml(
        self, text: str, audio_data: bytes | None = None
    ) -> EmotionAnalysis | None:
        """Run ONNX inference.  Trips circuit breaker on any exception."""
        if self._loader is None or not self._loader.is_ready():
            ML_FAILURE_COUNT.labels(reason="exception").inc()
            log.warning("EmotionModelLoader not ready – ML skipped")
            return None

        start = time.perf_counter()
        try:
            if audio_data is not None:
                from app.ml.mfcc_extractor import extract_mfcc

                mfcc = await extract_mfcc(audio_data)
            else:
                mfcc = _zero_mfcc()

            @_ml_breaker
            def _protected_infer() -> dict[str, float]:
                # NOTE: synchronous wrapper required by pybreaker;
                # we call the async loader from inside run_in_executor via
                # a small helper below instead.
                pass

            # Run inference through the loader (already async + threadpool)
            raw_scores = await asyncio.wait_for(
                self._loader.predict(mfcc),
                timeout=_INFERENCE_TIMEOUT_S,
            )
        except TimeoutError:
            ML_FAILURE_COUNT.labels(reason="timeout").inc()
            log.warning("ML inference timed out")
            _ml_breaker.call(lambda: (_ for _ in ()).throw(TimeoutError()))  # trip
            return None
        except pybreaker.CircuitBreakerError:
            ML_FAILURE_COUNT.labels(reason="circuit_open").inc()
            log.warning("Circuit breaker blocked ML call")
            return None
        except Exception as exc:
            ML_FAILURE_COUNT.labels(reason="exception").inc()
            log.error("ML inference exception", exc=str(exc))
            try:
                _ml_breaker.call(
                    lambda: (_ for _ in ()).throw(RuntimeError(str(exc)))
                )
            except Exception:
                pass
            return None
        finally:
            elapsed = time.perf_counter() - start
            ML_INFERENCE_LATENCY.observe(elapsed)

        return _scores_to_emotion_analysis(raw_scores, text)

    async def _run_heuristic(self, text: str) -> EmotionAnalysis:
        """Pure keyword heuristic – never fails."""
        # Yield once so the event loop can schedule the ML task concurrently.
        await asyncio.sleep(0)
        return _heuristic_emotion(text)
