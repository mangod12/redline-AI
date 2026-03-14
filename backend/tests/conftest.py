"""Pytest configuration for backend tests (Phase 3).

Provides:
- In-memory SQLite async engine (aiosqlite)
- Override of get_db dependency
- Test FastAPI app + httpx AsyncClient
- Seeded tenant, user, and JWT token helpers
"""
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Ensure backend package is importable
# ---------------------------------------------------------------------------
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

# ---------------------------------------------------------------------------
# Import application modules
# ---------------------------------------------------------------------------
from app.core.config import settings as _app_settings
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash
from app.models.base import Base
from app.models.tenant import Tenant
from app.models.user import RoleEnum, User

# ---------------------------------------------------------------------------
# Ensure SECRET_KEY has a non-empty test value for JWT signing/verification
# ---------------------------------------------------------------------------
if not _app_settings.SECRET_KEY:
    object.__setattr__(_app_settings, "SECRET_KEY", "test-secret-key-for-unit-tests-only!!")

# ---------------------------------------------------------------------------
# In-memory SQLite async engine
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = "sqlite+aiosqlite://"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


# ---------------------------------------------------------------------------
# UUID column event listeners for SQLite compatibility
# ---------------------------------------------------------------------------
@event.listens_for(test_engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    """Enable WAL mode and foreign keys for SQLite."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """Create all tables before each test, drop afterwards."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    """Yield a fresh async DB session for direct use in tests."""
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def seeded_tenant(db_session: AsyncSession):
    """Create and return a test tenant."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Test Tenant",
    )
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture
async def seeded_user(db_session: AsyncSession, seeded_tenant: Tenant):
    """Create and return a test user with a known password."""
    user = User(
        id=uuid.uuid4(),
        email="testuser@example.com",
        hashed_password=get_password_hash("SecurePass123!"),
        role=RoleEnum.dispatcher,
        tenant_id=seeded_tenant.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def superadmin_user(db_session: AsyncSession, seeded_tenant: Tenant):
    """Create and return a super_admin user."""
    user = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        hashed_password=get_password_hash("AdminPass123!"),
        role=RoleEnum.super_admin,
        tenant_id=seeded_tenant.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def make_token(user: User) -> str:
    """Generate a valid JWT access token for the given user."""
    return create_access_token(
        subject=str(user.id),
        tenant_id=str(user.tenant_id),
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        expires_delta=timedelta(minutes=30),
    )


@pytest_asyncio.fixture
async def auth_token(seeded_user: User) -> str:
    """Return a valid JWT access token for the default test user."""
    return make_token(seeded_user)


@pytest_asyncio.fixture
async def superadmin_token(superadmin_user: User) -> str:
    """Return a valid JWT access token for the super_admin user."""
    return make_token(superadmin_user)


# ---------------------------------------------------------------------------
# Test application + client
# ---------------------------------------------------------------------------

def _build_test_app():
    """Build a minimal FastAPI app that mirrors production routing
    but without heavy lifespan dependencies (Whisper, Redis, ML models)."""
    from fastapi import Depends, FastAPI

    from app.api.v1.endpoints.auth import router as auth_router
    from app.api.v1.endpoints.calls import router as calls_router
    from app.api.v1.endpoints.emergency import router as emergency_router
    from app.core.security import require_jwt_token
    from app.core.security_headers import SecurityHeadersMiddleware

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    # Auth endpoints (no JWT guard - they issue tokens)
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])

    # Protected call endpoints
    app.include_router(
        calls_router,
        prefix="/api/v1/calls",
        tags=["calls"],
        dependencies=[Depends(require_jwt_token)],
    )

    # Emergency endpoint (no auth in MVP)
    app.include_router(emergency_router, tags=["emergency"])

    # Simple health endpoint for header testing
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    """Yield an httpx AsyncClient bound to the test app with DB override."""
    from app.core.security import limiter

    app = _build_test_app()
    app.state.limiter = limiter  # slowapi decorator needs this on app.state

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    # Also override the get_db imported directly in the emergency endpoint
    from app.core.database import get_db as core_get_db
    app.dependency_overrides[core_get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def authenticated_client(
    db_session: AsyncSession, seeded_user: User
):
    """Yield an httpx AsyncClient with a valid Authorization header."""
    from app.core.security import limiter

    app = _build_test_app()
    app.state.limiter = limiter  # slowapi decorator needs this on app.state

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    from app.core.database import get_db as core_get_db
    app.dependency_overrides[core_get_db] = _override_get_db

    token = make_token(seeded_user)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        yield ac
