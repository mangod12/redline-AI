"""Phase 3 tests for auth API endpoints.

Covers:
- POST /api/v1/auth/login  (success, wrong password, lockout via Redis mock)
- POST /api/v1/auth/register (valid, duplicate email)
- POST /api/v1/auth/refresh (valid refresh token)

All tests use the in-memory SQLite database and mock Redis where needed.
"""
from unittest.mock import AsyncMock, patch

import pytest

# ===========================================================================
# Login endpoint
# ===========================================================================


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, client, seeded_user, seeded_tenant):
        """Valid credentials should return access + refresh tokens."""
        with patch("app.api.v1.endpoints.auth.get_redis_client", return_value=None):
            resp = await client.post(
                "/api/v1/auth/login",
                data={"username": "testuser@example.com", "password": "SecurePass123!"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client, seeded_user):
        """Wrong password should return 400."""
        with patch("app.api.v1.endpoints.auth.get_redis_client", return_value=None):
            resp = await client.post(
                "/api/v1/auth/login",
                data={"username": "testuser@example.com", "password": "WrongPass999!"},
            )
        assert resp.status_code == 400
        assert "Incorrect" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client):
        """Non-existent email should return 400 (same as wrong password)."""
        with patch("app.api.v1.endpoints.auth.get_redis_client", return_value=None):
            resp = await client.post(
                "/api/v1/auth/login",
                data={"username": "nobody@example.com", "password": "Pass1234!abc"},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_login_lockout_after_max_attempts(self, client, seeded_user):
        """When Redis indicates account is locked, login should return 429."""
        mock_redis = AsyncMock()
        # Simulate already-locked state (Redis has lockout key set)
        mock_redis.get = AsyncMock(return_value="1")

        with patch("app.api.v1.endpoints.auth.get_redis_client", return_value=mock_redis):
            resp = await client.post(
                "/api/v1/auth/login",
                data={"username": "testuser@example.com", "password": "WrongPass1!ab"},
            )

        assert resp.status_code == 429
        assert "locked" in resp.json()["detail"].lower()


# ===========================================================================
# Register endpoint
# ===========================================================================


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_success(
        self, client, superadmin_token, seeded_tenant, db_session
    ):
        """Super admin should be able to register a new user."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "NewUserPass1!x",
                "role": "viewer",
                "tenant_id": str(seeded_tenant.id),
            },
            headers={"Authorization": f"Bearer {superadmin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "newuser@example.com"

    @pytest.mark.asyncio
    async def test_register_duplicate_email(
        self, client, superadmin_token, seeded_tenant, seeded_user
    ):
        """Registering with an already-used email should fail with 400."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "testuser@example.com",  # already exists
                "password": "AnotherPass1!x",
                "role": "viewer",
                "tenant_id": str(seeded_tenant.id),
            },
            headers={"Authorization": f"Bearer {superadmin_token}"},
        )
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_register_requires_superadmin(
        self, client, auth_token, seeded_tenant
    ):
        """A non-super_admin user should be rejected from registering users."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "another@example.com",
                "password": "ValidPass123!x",
                "role": "viewer",
                "tenant_id": str(seeded_tenant.id),
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        # The dispatcher role should not have super_admin privileges
        assert resp.status_code == 400


# ===========================================================================
# Refresh token endpoint
# ===========================================================================


class TestRefreshToken:
    @pytest.mark.asyncio
    async def test_refresh_success(self, client, seeded_user):
        """A valid refresh token should return new access + refresh tokens."""
        from app.core.security import create_refresh_token

        refresh = create_refresh_token(
            subject=str(seeded_user.id),
            tenant_id=str(seeded_user.tenant_id),
            role=seeded_user.role.value,
        )
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_fails(self, client, auth_token):
        """Using an access token as a refresh token must fail."""
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": auth_token},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_with_garbage_token_fails(self, client):
        """A garbage string must fail."""
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "this.is.not.valid"},
        )
        assert resp.status_code == 401
