"""Pydantic models for reasoning data."""

from typing import Any

from pydantic import BaseModel, Field


class ReasoningOutput(BaseModel):
    """Model representing reasoning analysis results."""

    key_insights: list[str] = Field(..., description="Key insights extracted from emotion analysis")
    risk_factors: list[str] = Field(..., description="Identified risk factors")
    context_summary: str = Field(..., description="Summary of the situation context")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in the reasoning")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
