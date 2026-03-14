from uuid import UUID

from app.schemas.base import CoreModel, TenantBaseSchema


class TranscriptCreate(CoreModel):
    original_text: str
    language: str = "en"

class TranscriptResponse(TenantBaseSchema):
    call_id: UUID
    original_text: str
    translated_text: str | None = None
    language: str
