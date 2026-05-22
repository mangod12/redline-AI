"""Dashboard routes — GET /dashboard, GET /api/v1/calls/live, WS /ws/dashboard."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.security import require_jwt_token
from app.dashboard import call_store

router = APIRouter()
logger = logging.getLogger("redline_ai.dashboard")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# ---------------------------------------------------------------------------
# Connected dashboard clients
# ---------------------------------------------------------------------------
_dashboard_clients: set[WebSocket] = set()


async def _broadcast_to_dashboards(message: dict) -> None:
    """Send a JSON message to every connected dashboard WebSocket."""
    stale: list[WebSocket] = []
    for ws in _dashboard_clients:
        try:
            await ws.send_json(message)
        except Exception:
            stale.append(ws)
    for ws in stale:
        _dashboard_clients.discard(ws)


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request) -> HTMLResponse:
    """Serve the live dispatcher dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "Redline AI Dispatch Dashboard"},
    )


@router.get("/api/v1/calls/live")
async def calls_live(limit: int = 50, token_payload: dict = Depends(require_jwt_token)):
    """Return the most recent emergency call records as JSON."""
    tenant_id = token_payload.get("tenant_id", "")
    try:
        calls = await call_store.aget_recent(limit=min(limit, 100), tenant_id=tenant_id)
    except Exception:
        calls = []
    return {"calls": calls}


# ---------------------------------------------------------------------------
# WebSocket endpoint for real-time dashboard updates
# ---------------------------------------------------------------------------

_PING_INTERVAL_S = 30
_MAX_BACKOFF_S = 30
_INITIAL_BACKOFF_S = 1


@router.websocket("/ws/dashboard")
async def ws_dashboard(websocket: WebSocket):
    """Real-time dashboard feed over WebSocket.

    Authentication is via query-param ``token``.  Once connected the server
    subscribes to the Redis ``redline.events.calls`` channel and forwards
    simplified events to the client.  A keepalive ping is sent every 30 s.
    """
    # --- authenticate via query param ---
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        return

    try:
        import jwt

        from app.core.config import settings
        from app.core.security import ALGORITHM

        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        tenant_id = payload.get("tenant_id", "")
        logger.info(
            "Dashboard WS authenticated, user=%s tenant=%s",
            payload.get("sub"),
            tenant_id,
        )
    except Exception:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await websocket.accept()
    _dashboard_clients.add(websocket)

    # --- Redis pubsub listener ---
    async def _pubsub_listener() -> None:
        from app.core.redis_client import get_redis_client

        backoff = _INITIAL_BACKOFF_S
        while True:
            redis = get_redis_client()
            if not redis:
                logger.warning(
                    "Redis unavailable for dashboard WS, retrying in %ss", backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_S)
                continue

            pubsub = None
            try:
                pubsub = redis.pubsub()
                await pubsub.subscribe("redline.events.calls")
                backoff = _INITIAL_BACKOFF_S

                async for raw_message in pubsub.listen():
                    if raw_message["type"] != "message":
                        continue
                    try:
                        data = json.loads(raw_message["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue

                    event_payload = data.get("payload", {})
                    msg_tenant = event_payload.get("tenant_id", "")

                    # Tenant isolation: only forward events belonging to this tenant
                    if tenant_id and msg_tenant and msg_tenant != tenant_id:
                        continue

                    simplified = {
                        "type": "call_event",
                        "event": data.get("event_type", ""),
                        "call_id": data.get("call_id", ""),
                        "timestamp": data.get("timestamp", ""),
                        **event_payload,
                    }
                    try:
                        await websocket.send_json(simplified)
                    except Exception:
                        return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "Dashboard pubsub error: %s, retrying in %ss", exc, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_S)
            finally:
                if pubsub:
                    with contextlib.suppress(Exception):
                        await pubsub.unsubscribe("redline.events.calls")

    # --- keepalive ping ---
    async def _keepalive_ping() -> None:
        try:
            while True:
                await asyncio.sleep(_PING_INTERVAL_S)
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
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("Dashboard WS error: %s", exc)
    finally:
        _dashboard_clients.discard(websocket)
        listener_task.cancel()
        ping_task.cancel()
        logger.info("Dashboard WS disconnected, user=%s", payload.get("sub"))
