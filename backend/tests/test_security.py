"""Phase 3 tests for core security functionality.

Covers:
- Password schema validation (UserCreate)
- JWT access token creation and decoding
- JWT refresh token creation and verification
- Security headers middleware
- Production config validation guards
"""
from datetime import timedelta

import pytest
from jose import jwt
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.security import (
    ALGORITHM,
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
    verify_refresh_token,
)
from app.schemas.user import UserCreate

# ---- helpers ---------------------------------------------------------------

_VALID_PASSWORD = "MyStr0ng!Pass"
_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _make_user_create(password: str) -> UserCreate:
    """Attempt to build a UserCreate with the given password."""
    return UserCreate(
        email="test@example.com",
        password=password,
        tenant_id=_TENANT_ID,
    )


# ===========================================================================
# Password validation (schema-level)
# ===========================================================================


class TestPasswordValidation:
    def test_too_short(self):
        with pytest.raises(ValidationError, match="at least 12 characters"):
            _make_user_create("Ab1!")

    def test_missing_uppercase(self):
        with pytest.raises(ValidationError, match="uppercase"):
            _make_user_create("alllowercase1!")

    def test_missing_lowercase(self):
        with pytest.raises(ValidationError, match="lowercase"):
            _make_user_create("ALLUPPERCASE1!")

    def test_missing_digit(self):
        with pytest.raises(ValidationError, match="digit"):
            _make_user_create("NoDigitsHere!!")

    def test_missing_special_char(self):
        with pytest.raises(ValidationError, match="special character"):
            _make_user_create("NoSpecialChar1A")

    def test_valid_password_accepted(self):
        user = _make_user_create(_VALID_PASSWORD)
        assert user.password == _VALID_PASSWORD


# ===========================================================================
# Password hashing / verification
# ===========================================================================


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = get_password_hash("Test1234!abc")
        assert verify_password("Test1234!abc", hashed) is True

    def test_wrong_password_fails(self):
        hashed = get_password_hash("Test1234!abc")
        assert verify_password("WrongPassword1!", hashed) is False

    def test_hash_is_not_plaintext(self):
        hashed = get_password_hash("Test1234!abc")
        assert hashed != "Test1234!abc"


# ===========================================================================
# JWT access tokens
# ===========================================================================


class TestAccessToken:
    def test_create_and_decode(self):
        token = create_access_token(
            subject="user-123",
            tenant_id="tenant-456",
            role="dispatcher",
        )
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "user-123"
        assert payload["tenant_id"] == "tenant-456"
        assert payload["role"] == "dispatcher"
        assert payload["type"] == "access"

    def test_custom_expiry(self):
        token = create_access_token(
            subject="user-1",
            tenant_id="t-1",
            role="viewer",
            expires_delta=timedelta(minutes=5),
        )
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "user-1"
        assert "exp" in payload

    def test_default_expiry_present(self):
        token = create_access_token(
            subject="user-1", tenant_id="t-1", role="viewer"
        )
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert "exp" in payload


# ===========================================================================
# JWT refresh tokens
# ===========================================================================


class TestRefreshToken:
    def test_create_and_verify(self):
        token = create_refresh_token(
            subject="user-789",
            tenant_id="tenant-abc",
            role="tenant_admin",
        )
        payload = verify_refresh_token(token)
        assert payload["sub"] == "user-789"
        assert payload["tenant_id"] == "tenant-abc"
        assert payload["role"] == "tenant_admin"
        assert payload["type"] == "refresh"

    def test_access_token_rejected_as_refresh(self):
        """An access token must not pass refresh verification."""
        from fastapi import HTTPException

        access = create_access_token(
            subject="u", tenant_id="t", role="viewer"
        )
        with pytest.raises(HTTPException) as exc_info:
            verify_refresh_token(access)
        assert exc_info.value.status_code == 401

    def test_garbage_token_rejected(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            verify_refresh_token("not.a.valid.jwt")
        assert exc_info.value.status_code == 401


# ===========================================================================
# Security headers middleware
# ===========================================================================


@pytest.mark.asyncio
async def test_security_headers_present(client):
    """Every response must include the OWASP security headers."""
    resp = await client.get("/health")
    assert resp.status_code == 200

    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-xss-protection"] == "1; mode=block"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in resp.headers["permissions-policy"]
    assert "default-src 'self'" in resp.headers["content-security-policy"]


# ===========================================================================
# Production config validation
# ===========================================================================


class TestProductionConfigValidation:
    """Settings.validate_production_settings rejects unsafe configs."""

    def test_rejects_sqlite_in_production(self):
        with pytest.raises(ValueError, match="USE_SQLITE must be false"):
            Settings(
                APP_ENV="production",
                USE_SQLITE=True,
                SECRET_KEY="a" * 32,
                TWILIO_AUTH_TOKEN="tok",
                POSTGRES_PASSWORD="strongpw",
                ENABLE_DOCS=False,
            )

    def test_rejects_default_postgres_password(self):
        with pytest.raises(ValueError, match="POSTGRES_PASSWORD must be changed"):
            Settings(
                APP_ENV="production",
                USE_SQLITE=False,
                SECRET_KEY="a" * 32,
                TWILIO_AUTH_TOKEN="tok",
                POSTGRES_PASSWORD="postgres",
                ENABLE_DOCS=False,
            )

    def test_rejects_short_secret_key(self):
        with pytest.raises(ValueError, match="SECRET_KEY must be at least 32"):
            Settings(
                APP_ENV="production",
                USE_SQLITE=False,
                SECRET_KEY="short",
                TWILIO_AUTH_TOKEN="tok",
                POSTGRES_PASSWORD="strongpw",
                ENABLE_DOCS=False,
            )

    def test_rejects_missing_twilio_token(self):
        with pytest.raises(ValueError, match="TWILIO_AUTH_TOKEN must be set"):
            Settings(
                APP_ENV="production",
                USE_SQLITE=False,
                SECRET_KEY="a" * 32,
                TWILIO_AUTH_TOKEN="",
                POSTGRES_PASSWORD="strongpw",
                ENABLE_DOCS=False,
            )

    def test_rejects_docs_enabled_in_production(self):
        with pytest.raises(ValueError, match="ENABLE_DOCS must be false"):
            Settings(
                APP_ENV="production",
                USE_SQLITE=False,
                SECRET_KEY="a" * 32,
                TWILIO_AUTH_TOKEN="tok",
                POSTGRES_PASSWORD="strongpw",
                ENABLE_DOCS=True,
            )

    def test_valid_production_config_passes(self):
        s = Settings(
            APP_ENV="production",
            USE_SQLITE=False,
            SECRET_KEY="a" * 32,
            TWILIO_AUTH_TOKEN="tok",
            POSTGRES_PASSWORD="strongpw",
            ENABLE_DOCS=False,
        )
        assert s.APP_ENV == "production"
