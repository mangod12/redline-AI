
from app.schemas.base import BaseSchema, CoreModel


class TenantCreate(CoreModel):
    name: str

class TenantUpdate(CoreModel):
    name: str | None = None

class TenantResponse(BaseSchema):
    name: str
