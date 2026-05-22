"""Pytest configuration for backend tests.

Adds the app directory to sys.path and provides shared fixtures.
"""
import sys
from pathlib import Path

import pytest

# Add the backend directory to Python path so 'app' package is importable
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


@pytest.fixture
def sample_transcript():
    """Provide a sample Transcript for agent tests."""
    from app.core.schemas import Transcript
    return Transcript(text="there is a fire in the building", confidence=0.95)


@pytest.fixture
def critical_transcript():
    """Provide a critical emergency transcript."""
    from app.core.schemas import Transcript
    return Transcript(text="someone is not breathing cardiac arrest please help", confidence=0.99)


@pytest.fixture
def benign_transcript():
    """Provide a non-emergency transcript."""
    from app.core.schemas import Transcript
    return Transcript(text="hello I lost my wallet in the parking lot", confidence=0.90)


@pytest.fixture(autouse=True)
def reset_circuit_breakers():
    """Reset circuit breakers before each test to prevent state leakage."""
    yield
    try:
        from app.agents.intent.intent_agent import _intent_breaker
        _intent_breaker.close()
    except Exception:
        pass
    try:
        from app.agents.emotion.emotion_agent import _ml_breaker
        _ml_breaker.close()
    except Exception:
        pass
