import asyncio
from types import SimpleNamespace
from uuid import uuid4
from uuid import UUID

import pytest
import redis.asyncio as redis
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.deps import get_current_user, get_tenant_id
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.security import require_jwt_token
from app.main import app as fastapi_app
from app.models.base import Base
from app.models.analysis_result import AnalysisResult
from app.models.call import Call
from app.models.dispatch_recommendation import DispatchRecommendation
from app.models.severity_report import SeverityReport


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db_session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_end_to_end_pipeline(db_session):
    # make sure Redis is available
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    await redis_client.flushall()

    tenant_id = uuid4()

    async def _fake_require_jwt_token():
        return {"sub": str(uuid4()), "tenant_id": str(tenant_id), "role": "dispatcher"}

    async def _fake_get_current_user():
        return SimpleNamespace(id=uuid4(), tenant_id=tenant_id, role="dispatcher")

    async def _fake_get_tenant_id():
        return tenant_id

    fastapi_app.dependency_overrides[require_jwt_token] = _fake_require_jwt_token
    fastapi_app.dependency_overrides[get_current_user] = _fake_get_current_user
    fastapi_app.dependency_overrides[get_tenant_id] = _fake_get_tenant_id

    try:
        transport = ASGITransport(app=fastapi_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # start a call
            resp = await client.post(
                "/api/v1/calls/start",
                json={"caller_number": "555-1234"},
            )
            assert resp.status_code == 200
            data = resp.json()
            call_id = data["id"]

            # stub ML service
            with respx.mock(base_url=settings.ML_SERVICE_URL) as ml_mock:
                ml_mock.post("/analyze").respond(
                    json={
                        "incident_type": "intrusion",
                        "panic_score": 0.78,
                        "keyword_score": 0.6,
                        "severity_prediction": 8,
                        "location_text": "KIIT campus gate 3",
                    }
                )

                # send transcript
                tresp = await client.post(
                    f"/api/v1/calls/{call_id}/transcript",
                    json={"original_text": "Help someone is breaking into my house", "language": "en"},
                )
                assert tresp.status_code == 200
                await asyncio.sleep(0.2)

                # verify DB records
                call_obj = await db_session.get(Call, UUID(call_id))
                assert call_obj is not None

                # analysis result
                result = (
                    await db_session.execute(
                        select(AnalysisResult).where(AnalysisResult.call_id == UUID(call_id))
                    )
                ).scalar_one_or_none()
                assert result is not None
                assert result.incident_type == "intrusion"
                assert result.location_text == "KIIT campus gate 3"

                # severity report
                severity = (
                    await db_session.execute(
                        select(SeverityReport).where(SeverityReport.call_id == UUID(call_id))
                    )
                ).scalar_one_or_none()
                assert severity is not None
                assert severity.severity_score >= 7

                # dispatch
                dispatch = (
                    await db_session.execute(
                        select(DispatchRecommendation).where(DispatchRecommendation.call_id == UUID(call_id))
                    )
                ).scalar_one_or_none()
                assert dispatch is not None
                assert dispatch.unit_id.startswith("police")
    finally:
        fastapi_app.dependency_overrides.pop(require_jwt_token, None)
        fastapi_app.dependency_overrides.pop(get_current_user, None)
        fastapi_app.dependency_overrides.pop(get_tenant_id, None)
