from app.models.call import CallStatus
from app.schemas.base import CoreModel, TenantBaseSchema


class CallCreate(CoreModel):
    caller_number: str

class CallUpdate(CoreModel):
    status: CallStatus

class CallResponse(TenantBaseSchema):
    caller_number: str
    status: CallStatus
