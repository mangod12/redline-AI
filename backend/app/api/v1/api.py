from fastapi import APIRouter
from app.api.v1.endpoints import calls, severity, emergency

api_router = APIRouter()
# Note: auth router is mounted separately in main.py (public, no JWT required)
api_router.include_router(calls.router, prefix="/calls", tags=["calls"])
api_router.include_router(severity.router, prefix="/calls", tags=["severity"])  # /calls/{call_id}/analyze
api_router.include_router(emergency.router, tags=["emergency"])  # /process-emergency
