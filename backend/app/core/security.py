from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Union

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import bcrypt
from jose import JWTError, jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from twilio.request_validator import RequestValidator

from app.core.config import settings

log = structlog.get_logger("redline_ai.security")

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

ALGORITHM = "HS256"
_bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(
    subject: Union[str, Any], tenant_id: str, role: str, expires_delta: timedelta | None = None
) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "tenant_id": str(tenant_id),
        "role": str(role),
        "type": "access",
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(
    subject: Union[str, Any], tenant_id: str, role: str,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "tenant_id": str(tenant_id),
        "role": str(role),
        "type": "refresh",
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def verify_refresh_token(token: str) -> dict[str, Any]:
    """Decode and validate a refresh token. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from exc

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is not a refresh token",
        )
    return payload


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


async def require_jwt_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc


async def verify_twilio_signature(request: Request) -> None:
    if not settings.TWILIO_AUTH_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="TWILIO_AUTH_TOKEN is not configured",
        )

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing Twilio signature",
        )

    form = await request.form()
    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    valid = validator.validate(str(request.url), dict(form), signature)

    if not valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio signature",
        )
