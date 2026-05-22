from app.models.tenant import Tenant
from app.schemas.tenant import TenantCreate, TenantUpdate
from app.services.base import CRUDBase


class CRUDTenant(CRUDBase):
    pass


tenant = CRUDTenant(Tenant)
