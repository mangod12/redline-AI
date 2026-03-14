"""Dashboard routes — GET /dashboard, GET /dashboard/login, GET /api/v1/calls/live."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt

from app.core.config import settings
from app.core.security import ALGORITHM, require_jwt_token
from app.dashboard import call_store

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/dashboard/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request) -> HTMLResponse:
    """Serve the dashboard login page."""
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"title": "Redline AI - Login"},
    )


@router.get("/dashboard/logout", include_in_schema=False)
async def logout():
    """Clear auth cookie and redirect to login."""
    response = RedirectResponse(url="/dashboard/login")
    response.delete_cookie("redline_token")
    return response


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request) -> HTMLResponse:
    """Serve the live dispatcher dashboard (requires valid JWT cookie)."""
    token = request.cookies.get("redline_token")
    if not token:
        return RedirectResponse(url="/dashboard/login")
    try:
        jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return RedirectResponse(url="/dashboard/login")

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "Redline AI Dispatch Dashboard"},
    )


@router.get("/api/v1/calls/live")
async def calls_live(limit: int = 50, _: dict = Depends(require_jwt_token)):
    """Return the most recent emergency call records as JSON (requires JWT)."""
    return {"calls": call_store.get_recent(limit=min(limit, 100))}


@router.post("/api/v1/calls/seed-demo", include_in_schema=False)
async def seed_demo_calls(_: dict = Depends(require_jwt_token)):
    """Seed demo events into the in-memory call store (dev only)."""
    if settings.APP_ENV.lower() == "production":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Not available in production")

    call_store.clear()
    demos = [
        dict(transcript="There is a man with a gun at the shopping mall on 5th street, people are running!",
             intent="violent_crime", intent_confidence=0.96, emotion="fear", emotion_confidence=0.91,
             severity="critical", severity_score=9.8, responder="Police (Armed Response) + Ambulance",
             fallback_used=False, intent_fallback=False, emotion_fallback=False, latency_ms=342.5),
        dict(transcript="My apartment building is on fire, the third floor is completely engulfed, people trapped inside!",
             intent="fire", intent_confidence=0.98, emotion="fear", emotion_confidence=0.88,
             severity="critical", severity_score=9.5, responder="Fire Department + Ambulance",
             fallback_used=False, intent_fallback=False, emotion_fallback=False, latency_ms=287.3),
        dict(transcript="My father just collapsed, not breathing and turning blue. I think he is having a heart attack!",
             intent="medical", intent_confidence=0.95, emotion="fear", emotion_confidence=0.85,
             severity="high", severity_score=8.7, responder="Ambulance (Priority 1)",
             fallback_used=False, intent_fallback=False, emotion_fallback=False, latency_ms=198.7),
        dict(transcript="I can smell gas really strongly in my building, multiple neighbors are feeling dizzy.",
             intent="gas_hazard", intent_confidence=0.92, emotion="anger", emotion_confidence=0.65,
             severity="high", severity_score=8.2, responder="Fire Department (HazMat) + Gas Company",
             fallback_used=False, intent_fallback=False, emotion_fallback=False, latency_ms=256.1),
        dict(transcript="My neighbor is standing on the edge of the rooftop, please send someone who can talk to him.",
             intent="mental_health", intent_confidence=0.89, emotion="sadness", emotion_confidence=0.78,
             severity="high", severity_score=8.0, responder="Police (Crisis Unit) + Ambulance",
             fallback_used=False, intent_fallback=False, emotion_fallback=False, latency_ms=312.4),
        dict(transcript="Car accident at Oak and Main. Two cars involved, one person seems hurt but conscious.",
             intent="accident", intent_confidence=0.94, emotion="neutral", emotion_confidence=0.72,
             severity="medium", severity_score=6.5, responder="Ambulance + Police (Traffic)",
             fallback_used=False, intent_fallback=False, emotion_fallback=False, latency_ms=221.8),
        dict(transcript="Someone broke into my car and stole my laptop. They ran down the alley heading east.",
             intent="robbery", intent_confidence=0.87, emotion="anger", emotion_confidence=0.81,
             severity="medium", severity_score=5.8, responder="Police (Patrol)",
             fallback_used=False, intent_fallback=False, emotion_fallback=False, latency_ms=175.2),
        dict(transcript="Something really wrong at the warehouse on River Road, loud banging noises and screaming.",
             intent="unknown", intent_confidence=0.35, emotion="fear", emotion_confidence=0.76,
             severity="medium", severity_score=6.2, responder="Police (Patrol)",
             fallback_used=True, intent_fallback=True, emotion_fallback=False, latency_ms=445.9),
        dict(transcript="Neighbors having a very loud party at 2 AM, music blasting. This has been going on for hours.",
             intent="non_emergency", intent_confidence=0.91, emotion="anger", emotion_confidence=0.58,
             severity="low", severity_score=2.3, responder="Non-Emergency Line",
             fallback_used=False, intent_fallback=False, emotion_fallback=False, latency_ms=134.6),
        dict(transcript="Umm not sure what to say but things are weird here, there is like some stuff going on.",
             intent="unknown", intent_confidence=0.22, emotion="neutral", emotion_confidence=0.31,
             severity="low", severity_score=1.5, responder="Non-Emergency Line",
             fallback_used=True, intent_fallback=True, emotion_fallback=True, latency_ms=523.7),
    ]
    for d in demos:
        call_store.add_call(**d)
    return {"seeded": len(demos)}
