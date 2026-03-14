"""Mock safety plugin."""

from typing import Any

from ...agents.safety.mock_safety_agent import MockSafetyAgent
from ..base import BasePlugin


class MockSafetyPlugin(BasePlugin):
    """Mock plugin for safety checks."""

    def __init__(self):
        super().__init__(name="mock_safety", version="1.0.0")

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def get_capabilities(self) -> dict[str, Any]:
        return {"type": "safety", "mock": True}

    async def create_agent(self) -> MockSafetyAgent:
        return MockSafetyAgent()
