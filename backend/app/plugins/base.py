"""Base classes for plugins in the Redline AI system."""

import asyncio
from abc import ABC, abstractmethod
from typing import Any


class BasePlugin(ABC):
    """Abstract base class for all plugins.

    Plugins provide implementations for various AI components that can be
    swapped dynamically. Each plugin has a name, version, and configuration.
    """

    def __init__(self, name: str, version: str, config: dict[str, Any] | None = None):
        self.name = name
        self.version = version
        self.config = config or {}

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the plugin with its configuration."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up resources when shutting down the plugin."""
        pass

    @abstractmethod
    def get_capabilities(self) -> dict[str, Any]:
        """Return the capabilities and metadata of this plugin."""
        pass

    async def execute_with_timeout(self, coro: asyncio.coroutines.Coroutine, timeout: float = 30.0):
        """Execute a coroutine with a timeout.

        Args:
            coro: The coroutine to execute.
            timeout: Timeout in seconds.

        Returns:
            The result of the coroutine.

        Raises:
            asyncio.TimeoutError: If the execution times out.
        """
        return await asyncio.wait_for(coro, timeout=timeout)
