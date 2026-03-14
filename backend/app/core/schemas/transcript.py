"""Pydantic models for transcript data."""

from datetime import datetime

from pydantic import BaseModel, Field


class Transcript(BaseModel):
    """Model representing a speech-to-text transcript."""

    text: str = Field(..., description="The transcribed text")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score of the transcription")
    language: str = Field(default="en", description="Language code of the transcript")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of transcription")
    audio_duration: float | None = Field(None, description="Duration of the audio in seconds")
    speaker_id: str | None = Field(None, description="Identifier for the speaker if available")
