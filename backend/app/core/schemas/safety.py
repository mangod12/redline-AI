"""Pydantic models for safety check data."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SafetyStatus(str, Enum):
    """Enumeration of safety check results."""

    SAFE = "safe"
    WARNING = "warning"
    UNSAFE = "unsafe"


class SafetyOutput(BaseModel):
    """Model representing safety check results."""

    status: SafetyStatus = Field(..., description="Overall safety status")
    issues: list[str] = Field(default_factory=list, description="Identified safety issues")
    recommendations: list[str] = Field(default_factory=list, description="Safety recommendations")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in the safety assessment")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
