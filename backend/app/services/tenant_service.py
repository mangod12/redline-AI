from app.models.tenant import Tenant
from app.services.base import CRUDBase


class CRUDTenant(CRUDBase):
    pass

tenant = CRUDTenant(Tenant)
