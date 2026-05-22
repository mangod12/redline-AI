import logging

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger("redline_ai")

_redis_client = None


async def init_redis():
    global _redis_client
    try:
        client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        await client.ping()
        _redis_client = client
        logger.info("Connected to Redis at %s", settings.REDIS_URL)
    except Exception as exc:
        logger.error("Redis connection failed: %s", exc)

        if settings.APP_ENV.lower() != "production":
            logger.warning("Trying fakeredis for local dev")
        try:
            import fakeredis.aioredis as fakeredis_mod

            _redis_client = fakeredis_mod.FakeRedis(decode_responses=True)
            logger.info("fakeredis started (in-memory, data lost on restart)")
        except ImportError:
            logger.error("Neither Redis nor fakeredis available")
            _redis_client = None


async def close_redis():
    global _redis_client
    if _redis_client:
        try:
            await _redis_client.aclose()
        except Exception as exc:
            logger.warning("Error closing Redis connection: %s", exc)
        _redis_client = None


def get_redis_client():
    return _redis_client


async def check_redis_health() -> bool:
    """Return True if Redis is reachable."""
    if _redis_client is None:
        return False
    try:
        await _redis_client.ping()
        return True
    except Exception:
        return False
