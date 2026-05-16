# .context/ — AI Context Folder

Comprehensive documentation of the Redline AI codebase.
Designed for AI agents, new developers, and code review.

## Files

| File | Contents |
|---|---|
| `ARCHITECTURE.md` | Full directory layout, both stacks, component descriptions |
| `DATA_MODELS.md` | All SQLAlchemy models, Node.js SQL schema, Redis keys, ER diagram |
| `ML_MODELS.md` | Intent (DistilBERT), Emotion (CNN), Whisper STT, severity scoring, training data |
| `PIPELINES.md` | Pipeline B (working), Pipeline C (fixed), endpoint map, event system |
| `API_SCHEMAS.md` | All Pydantic DTOs and API request/response schemas, JWT structure |
| `INFRASTRUCTURE.md` | Docker Compose, Dockerfile, env vars, dependencies, security config |
| `AGENT_SYSTEM.md` | BaseAgent, IntentAgent, EmotionAgent, model loaders |
| `KNOWN_ISSUES.md` | 51 audited → 42 fixed, 9 remaining |

## Quick Facts

- **Primary stack**: Python 3.11 / FastAPI / SQLAlchemy async / ONNX Runtime
- **Secondary stack**: Node.js / Express 5 / Google Cloud APIs (original prototype)
- **Database**: PostgreSQL (prod) / SQLite (dev)
- **Cache**: Redis (pub/sub + caching)
- **ML**: DistilBERT intent (ONNX) + CNN emotion (ONNX) + Whisper STT (local)
- **Auth**: JWT (HS256) + bcrypt + Twilio signature validation
- **Monitoring**: Prometheus + Grafana + structlog
- **Container**: Docker Compose (7 services)

## Status (Post-Fix Cycle)

- Pipeline B (emergency endpoint): **WORKING** — parallel intent+emotion, tenant-scoped, rate-limited
- Pipeline C (event-driven): **WORKING** — import fixed, graceful shutdown added
- Node.js pipeline: **WORKING** — Host header injection fixed, REST still needs auth (C2)
- Celery workers: **STUBS** (documented)

## Removed Dead Code
- `backend/app/api/main.py` — secondary FastAPI app
- `backend/app/core/memory/` — duplicate models + Redis client
- `backend/app/core/orchestrator.py` — dead pipeline
- `backend/app/plugins/` — entire plugin system
