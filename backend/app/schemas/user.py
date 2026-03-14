import re
from uuid import UUID

from pydantic import EmailStr, field_validator

from app.models.user import RoleEnum
from app.schemas.base import CoreModel, TenantBaseSchema


class UserCreate(CoreModel):
    email: EmailStr
    password: str
    role: RoleEnum = RoleEnum.viewer
    tenant_id: UUID

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>\-_+=\[\]~`/\\]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class UserResponse(TenantBaseSchema):
    email: EmailStr
    role: RoleEnum


class Token(CoreModel):
    access_token: str
    refresh_token: str
    token_type: str


class RefreshRequest(CoreModel):
    refresh_token: str


class TokenPayload(CoreModel):
    sub: str | None = None
    tenant_id: str | None = None
    role: str | None = None
