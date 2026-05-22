import asyncio
import contextlib
import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from prometheus_client import Gauge

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.redis_client import get_redis_client

router = APIRouter()
logger = logging.getLogger("redline_ai")

WEBSOCKET_CONNECTIONS = Gauge(
    "websocket_active_connections",
    "Number of active WebSocket connections",
)

_MAX_PUBSUB_MESSAGE_BYTES = 256 * 1024  # 256 KB guard for Redis JSON


class ConnectionManager:
    def __init__(self):
        # Maps call_id -> list of websockets
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, call_id: str):
        await websocket.accept()
        if call_id not in self.active_connections:
            self.active_connections[call_id] = []
        self.active_connections[call_id].append(websocket)
        logger.info(
            f"WebSocket connected for call {call_id}. Total connections: {len(self.active_connections[call_id])}"
        )

    def disconnect(self, websocket: WebSocket, call_id: str):
        if call_id in self.active_connections:
            if websocket in self.active_connections[call_id]:
                self.active_connections[call_id].remove(websocket)
            if not self.active_connections[call_id]:
                del self.active_connections[call_id]
        logger.info(f"WebSocket disconnected from call {call_id}.")

    async def broadcast_to_call(self, call_id: str, message: dict):
        if call_id in self.active_connections:
            for connection in self.active_connections[call_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error sending message to client: {e}")


manager = ConnectionManager()


@router.websocket("/calls/{call_id}")
async def websocket_endpoint(websocket: WebSocket, call_id: str):
    # Authenticate via query parameter token (standard JS WebSocket can't set headers)
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        return

    # Validate call_id format (must be valid UUID)
    import re

    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
    )
    if not uuid_pattern.match(call_id):
        await websocket.close(code=4002, reason="Invalid call_id format")
        return

    try:
        import jwt

        from app.core.config import settings
        from app.core.security import ALGORITHM

        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        # Token is valid — proceed with connection
        logger.info(
            f"WebSocket authenticated for call {call_id}, user={payload.get('sub')}"
        )
    except Exception:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    # Verify tenant has access to this call
    try:
        from sqlalchemy import select

        from app.core.database import AsyncSessionLocal
        from app.models.emergency_call import EmergencyCall

        user_tenant = payload.get("tenant_id")
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EmergencyCall).where(EmergencyCall.call_id == call_id)
            )
            call_record = result.scalar_one_or_none()
            if (
                call_record
                and getattr(call_record, "tenant_id", None) is not None
                and user_tenant is not None
                and str(call_record.tenant_id) != str(user_tenant)
            ):
                await websocket.close(code=4003, reason="Access denied to this call")
                return
    except Exception as exc:
        logger.error(f"Tenant verification failed for call {call_id}: {exc}")
        await websocket.close(code=4503, reason="Tenant verification unavailable")
        return

    # Rate limit: cap total WebSocket connections
    total_conns = sum(len(v) for v in manager.active_connections.values())
    if total_conns >= settings.MAX_WS_CONNECTIONS:
        await websocket.close(code=4429, reason="Too many connections")
        return

    await manager.connect(websocket, call_id)
    WEBSOCKET_CONNECTIONS.inc()

    redis = get_redis_client()
    if not redis:
        logger.error("Redis not initialized for websockets")
        manager.disconnect(websocket, call_id)
        return

    pubsub = redis.pubsub()
    channel_name = f"call_events:{call_id}"
    await pubsub.subscribe(channel_name)

    async def _pubsub_listener():
        async for raw_message in pubsub.listen():
            if raw_message["type"] == "message":
                try:
                    raw_data = raw_message["data"]
                    if isinstance(raw_data, (str, bytes)) and len(raw_data) > _MAX_PUBSUB_MESSAGE_BYTES:
                        logger.warning("Oversized pubsub message dropped (%d bytes)", len(raw_data))
                        continue
                    data = json.loads(raw_data)
                    simplified = {
                        "type": data.get("event_type", "").lower(),
                        **data.get("payload", {}),
                        "call_id": data.get("call_id"),
                    }
                    await manager.broadcast_to_call(call_id, simplified)
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning(f"Malformed pubsub message: {exc}")

    async def _keepalive_ping():
        """Send a ping frame every 30s to detect stale connections."""
        try:
            while True:
                await asyncio.sleep(30)
                await websocket.send_json({"type": "ping"})
        except (WebSocketDisconnect, Exception):
            raise

    listener_task = asyncio.create_task(_pubsub_listener())
    ping_task = asyncio.create_task(_keepalive_ping())

    try:
        done, pending = await asyncio.wait(
            [listener_task, ping_task],
            return_when=asyncio.FIRST_EXCEPTION,
        )
        # Cancel whichever task is still running
        for task in pending:
            task.cancel()
        # Re-raise the first real exception (if any)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
    finally:
        WEBSOCKET_CONNECTIONS.dec()
        manager.disconnect(websocket, call_id)
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel_name)
