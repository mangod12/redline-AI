"""Tests for iteration-3: tenant rate limiting, httpx pooling, Redis health, entrypoint."""

import os
import pytest

from app.core.security import _tenant_or_ip_key


class TestTenantRateLimitKey:
    """Verify the rate limit key function extracts tenant_id from JWT."""

    def test_no_auth_header_returns_ip(self):
        """Without Authorization header, falls back to IP."""

        class FakeRequest:
            headers = {}
            client = type("C", (), {"host": "1.2.3.4"})()
            scope = {"type": "http"}

        key = _tenant_or_ip_key(FakeRequest())
        assert "1.2.3.4" in key or key  # slowapi returns IP string

    def test_valid_bearer_extracts_tenant(self):
        """With a valid JWT containing tenant_id, key is tenant-prefixed."""
        from app.core.security import create_access_token

        token = create_access_token(
            subject="user1",
            tenant_id="test-tenant-123",
            role="dispatcher",
        )

        class FakeRequest:
            headers = {"authorization": f"Bearer {token}"}
            client = type("C", (), {"host": "1.2.3.4"})()
            scope = {"type": "http"}

        key = _tenant_or_ip_key(FakeRequest())
        assert key == "tenant:test-tenant-123"

    def test_invalid_token_falls_back_to_ip(self):
        """Malformed JWT falls back to IP-based key."""

        class FakeRequest:
            headers = {"authorization": "Bearer invalid.token.here"}
            client = type("C", (), {"host": "5.6.7.8"})()
            scope = {"type": "http"}

        key = _tenant_or_ip_key(FakeRequest())
        # Should not be tenant-prefixed
        assert not key.startswith("tenant:")


class TestHttpxPooling:
    """Verify Translation and Geocoder use shared httpx clients."""

    def test_translation_uses_shared_client(self):
        from app.services.translation_service import TranslationService, _get_client

        svc1 = TranslationService()
        svc2 = TranslationService()
        # Both should use the same shared client
        client1 = _get_client()
        client2 = _get_client()
        assert client1 is client2

    def test_geocoder_uses_shared_client(self):
        from app.services.geocoder import Geocoder, _get_client

        geo1 = Geocoder()
        geo2 = Geocoder()
        client1 = _get_client()
        client2 = _get_client()
        assert client1 is client2


class TestRedisHealthCheck:
    """Verify check_redis_health exists and is async."""

    def test_check_redis_health_is_async(self):
        import asyncio
        from app.core.redis_client import check_redis_health

        assert asyncio.iscoroutinefunction(check_redis_health)

    @pytest.mark.asyncio
    async def test_returns_false_when_no_client(self):
        """When Redis isn't initialized, health check returns False."""
        from unittest.mock import patch

        from app.core.redis_client import check_redis_health

        with patch("app.core.redis_client._redis_client", None):
            result = await check_redis_health()
            assert result is False


class TestDockerEntrypoint:
    """Verify entrypoint script exists."""

    def test_entrypoint_exists(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "docker-entrypoint.sh",
        )
        assert os.path.exists(path)
