from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_superuser, get_db
from app.core import security
from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.core.security import limiter
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.user import RefreshRequest, Token, UserCreate, UserResponse

router = APIRouter()

# Account lockout constants
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 900  # 15 minutes


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
async def login_access_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """OAuth2 compatible token login — returns access + refresh tokens."""
    redis = get_redis_client()

    # Check lockout
    if redis:
        lockout_key = f"auth:lockout:{form_data.username}"
        locked = await redis.get(lockout_key)
        if locked:
            raise HTTPException(
                status_code=429,
                detail="Account temporarily locked. Try again in 15 minutes.",
            )

    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    if not user or not security.verify_password(form_data.password, user.hashed_password):
        # Track failed attempts
        if redis:
            attempts_key = f"auth:attempts:{form_data.username}"
            attempts = await redis.incr(attempts_key)
            await redis.expire(attempts_key, LOCKOUT_DURATION_SECONDS)
            if attempts >= MAX_FAILED_ATTEMPTS:
                lockout_key = f"auth:lockout:{form_data.username}"
                await redis.setex(lockout_key, LOCKOUT_DURATION_SECONDS, "1")
                await redis.delete(attempts_key)
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    # Clear failed attempts on success
    if redis:
        await redis.delete(f"auth:attempts:{form_data.username}")
        await redis.delete(f"auth:lockout:{form_data.username}")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": security.create_access_token(
            user.id,
            tenant_id=user.tenant_id,
            role=user.role,
            expires_delta=access_token_expires,
        ),
        "refresh_token": security.create_refresh_token(
            user.id,
            tenant_id=user.tenant_id,
            role=user.role,
        ),
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=Token)
@limiter.limit("10/minute")
async def refresh_access_token(
    request: Request,
    body: RefreshRequest,
) -> Any:
    """Exchange a valid refresh token for a new access + refresh token pair."""
    payload = security.verify_refresh_token(body.refresh_token)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": security.create_access_token(
            payload["sub"],
            tenant_id=payload["tenant_id"],
            role=payload["role"],
            expires_delta=access_token_expires,
        ),
        "refresh_token": security.create_refresh_token(
            payload["sub"],
            tenant_id=payload["tenant_id"],
            role=payload["role"],
        ),
        "token_type": "bearer",
    }


@router.post("/register", response_model=UserResponse)
async def register_user(
    *,
    db: AsyncSession = Depends(get_db),
    user_in: UserCreate,
    current_user: User = Depends(get_current_active_superuser),
) -> Any:
    """Register new user. Only super_admin can do this."""
    result = await db.execute(select(User).where(User.email == user_in.email))
    user = result.scalar_one_or_none()
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )

    result = await db.execute(select(Tenant).where(Tenant.id == user_in.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    user = User(
        email=user_in.email,
        hashed_password=security.get_password_hash(user_in.password),
        role=user_in.role,
        tenant_id=user_in.tenant_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
