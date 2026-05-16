"""Dashboard routes — GET /dashboard and GET /api/v1/calls/live."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.security import require_jwt_token

from app.dashboard import call_store

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


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
    return {"calls": await call_store.aget_recent(limit=min(limit, 100), tenant_id=tenant_id)}
