from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, event
from prometheus_client import Gauge

from app.core.config import settings

# ---------------------------------------------------------------------------
# Prometheus gauges for SQLAlchemy connection-pool metrics
# ---------------------------------------------------------------------------
db_pool_size = Gauge("db_pool_size", "Current SQLAlchemy pool size")
db_pool_checked_out = Gauge("db_pool_checked_out", "Connections currently in use")
db_pool_overflow = Gauge("db_pool_overflow", "Overflow connections beyond pool_size")
db_pool_checked_in = Gauge("db_pool_checked_in", "Idle connections sitting in pool")

_pool_kwargs = {}
if "postgresql" in settings.SQLALCHEMY_DATABASE_URI:
    _pool_kwargs = {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_timeout": 30,
    }

engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    echo=False,
    future=True,
    **_pool_kwargs,
)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def check_db_health() -> bool:
    """Return True if the database is reachable."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_pool_status() -> dict:
    """Return current connection pool statistics."""
    pool = engine.pool
    return {
        "pool_size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
    }


def collect_pool_metrics() -> None:
    """Update Prometheus gauges from the engine pool.

    Only works when a real connection pool is present (PostgreSQL).
    SQLite uses NullPool / StaticPool which lack these methods — skip gracefully.
    """
    pool = engine.pool
    if not hasattr(pool, "size"):
        return
    db_pool_size.set(pool.size())
    db_pool_checked_out.set(pool.checkedout())
    db_pool_overflow.set(pool.overflow())
    db_pool_checked_in.set(pool.checkedin())
