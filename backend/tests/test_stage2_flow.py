import asyncio
import json
from uuid import UUID

import pytest
import redis.asyncio as redis
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, get_password_hash
from app.main import app as fastapi_app
from app.models.analysis_result import AnalysisResult
from app.models.call import Call
from app.models.dispatch_recommendation import DispatchRecommendation
from app.models.severity_report import SeverityReport
from app.models.tenant import Tenant
from app.models.user import RoleEnum, User


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_end_to_end_pipeline(db_session):
    # make sure Redis is available
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    await redis_client.flushall()

    tenant = Tenant(name="Stage2 Tenant")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        email="stage2.dispatcher@example.com",
        hashed_password=get_password_hash("SecurePass123!"),
        role=RoleEnum.dispatcher,
        tenant_id=tenant.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token(
        subject=str(user.id),
        tenant_id=str(user.tenant_id),
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
    )
    auth_headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # start a call
        resp = await client.post(
            "/api/v1/calls/start",
            json={"caller_number": "555-1234"},
            headers=auth_headers,
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

            # subscribe to redis events
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(f"call_events:{call_id}")
            await pubsub.subscribe("redline.events.calls")

            # send transcript
            tresp = await client.post(
                f"/api/v1/calls/{call_id}/transcript",
                json={"original_text": "Help someone is breaking into my house", "language": "en"},
                headers=auth_headers,
            )
            assert tresp.status_code == 200
            # Wait a moment for background processing
            await asyncio.sleep(0.2)

            # read events from pubsub
            events = []
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                if not msg:
                    break
                events.append(json.loads(msg["data"]))

            # ensure expected event types were published
            types = {e["event_type"] for e in events}
            assert "TRANSCRIPT_RECEIVED" in types
            assert "ML_ANALYSIS_COMPLETE" in types
            assert "SEVERITY_UPDATED" in types
            assert "LOCATION_RESOLVED" in types
            assert "DISPATCH_RECOMMENDED" in types

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
