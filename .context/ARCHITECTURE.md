# Redline AI - Architecture Overview

## What This Is

AI-powered IVR (Interactive Voice Response) platform for emergency dispatch. Processes 911-style calls through ML pipeline: audio → transcription → intent classification → emotion analysis → severity scoring → responder routing.

## Two Stacks (Current State)

### Node.js Layer (`src/`)
- **Role**: Twilio IVR webhook handler + Google Cloud STT
- **Framework**: Express 5.x
- **Database**: PostgreSQL via `pg` (raw SQL, `call_history` table)
- **STT**: Google Cloud Speech-to-Text (requires credentials)
- **Analysis**: Keyword-based only (no ML)
- **Auth**: Twilio webhook signature validation only. REST endpoints have NO auth.
- **Status**: Original prototype. Functional but limited.

### Python/FastAPI Layer (`backend/`)
- **Role**: Full ML pipeline + multi-tenant API + real-time WebSocket dashboard
- **Framework**: FastAPI + Gunicorn (UvicornWorker)
- **Database**: PostgreSQL via SQLAlchemy async + Alembic migrations
- **STT**: OpenAI Whisper (local, CPU, no API costs)
- **ML**: ONNX DistilBERT (intent) + ONNX CNN (emotion)
- **Cache**: Redis (pub/sub + caching)
- **Workers**: Celery (configured but tasks are stubs)
- **Auth**: JWT (PyJWT) + bcrypt + rate limiting (slowapi)
- **Observability**: Prometheus + Grafana + structlog
- **Status**: Production-capable backend. Primary development target.

## Key Relationship
Node.js and Python are **independent apps** sharing a PostgreSQL instance but writing to **different tables** with different schemas. No runtime communication between them. Docker Compose only runs the Python stack.

---

## Python Backend Architecture

### Directory Layout
```
backend/
├── app/
│   ├── main.py                    # FastAPI app, lifespan, middleware, routers
│   ├── worker.py                  # Celery app definition
│   ├── tasks.py                   # Celery tasks (STUBS - not implemented)
│   ├── agents/                    # ML agent implementations
│   │   ├── base.py                # BaseAgent ABC (process, get_input_schema, get_output_schema)
│   │   ├── intent/
│   │   │   └── intent_agent.py    # ONNX DistilBERT + keyword fallback
│   │   ├── emotion/
│   │   │   └── emotion_agent.py   # ONNX CNN + keyword fallback + circuit breaker
│   │   ├── severity/
│   │   │   └── severity_agent.py  # Severity assessment agent
│   │   ├── dispatch/
│   │   │   └── dispatch_agent.py  # Dispatch recommendation agent
│   │   ├── stt/
│   │   │   └── mock_stt_agent.py  # Mock STT agent
│   │   ├── reasoning/
│   │   │   └── mock_reasoning_agent.py  # Mock reasoning agent
│   │   └── safety/
│   │       └── mock_safety_agent.py     # Mock safety agent
│   ├── api/
│   │   ├── deps.py                # Auth dependencies (get_current_user, get_tenant_id)
│   │   └── v1/
│   │       ├── api.py             # Router aggregator
│   │       └── endpoints/
│   │           ├── auth.py        # POST /login, POST /register
│   │           ├── calls.py       # CRUD for tenant-scoped calls
│   │           ├── severity.py    # POST /{call_id}/analyze
│   │           └── emergency.py   # POST /process-emergency (main pipeline)
│   ├── api/
│   │   ├── main.py                # DEAD CODE - Secondary FastAPI app (orchestrator pipeline)
│   │   │                          #   NO auth, NO file size validation, hardcoded "mock_call_id"
│   │   │                          #   Uses dead Orchestrator + PluginRegistry + memory/redis_client
│   │   │                          #   Would conflict on port 8000 if both apps run
│   │   ├── deps.py                # Auth dependencies (get_current_user, get_tenant_id)
│   │   └── v1/                    # (unchanged below)
│   │   ...
│   ├── core/
│   │   ├── config.py              # Pydantic Settings (env-driven)
│   │   ├── database.py            # SQLAlchemy async engine + session factory
│   │   ├── security.py            # JWT create/verify, bcrypt, rate limiter, Twilio validation
│   │   ├── orchestrator.py        # DEAD CODE - 6-stage plugin pipeline (never called)
│   │   ├── events.py              # Redis pub/sub event publisher
│   │   ├── event_listener.py      # Background Redis subscriber → CallProcessor
│   │   ├── redis_client.py        # Global async Redis singleton
│   │   ├── logging.py             # Logging config
│   │   ├── memory/
│   │   │   ├── redis_client.py    # DEAD CODE - Class-based Redis client (used only by dead api/main.py)
│   │   │   └── postgres_models.py # DEAD CODE - Duplicate SQLAlchemy models (Integer PKs, separate Base)
│   │   │                          #   Conflicts: emergency_calls, transcripts, audit_logs table names
│   │   │                          #   overlap with app/models/ (which uses UUID PKs)
│   │   └── schemas/               # Pipeline data transfer objects
│   │       ├── transcript.py      # Transcript
│   │       ├── emotion.py         # EmotionType, EmotionAnalysis
│   │       ├── intent.py          # IntentType, IntentAnalysis
│   │       ├── severity.py        # SeverityLevel, SeverityAssessment
│   │       ├── reasoning.py       # ReasoningOutput (used only by dead orchestrator)
│   │       ├── safety.py          # SafetyOutput (used only by dead orchestrator)
│   │       └── dispatch_report.py # DispatchReport (used only by dead orchestrator)
│   ├── models/                    # SQLAlchemy ORM models
│   │   ├── base.py                # BaseModel (UUID PK, timestamps), TenantModel (+tenant_id FK)
│   │   ├── tenant.py              # Tenant (name)
│   │   ├── user.py                # User (email, hashed_password, role enum, tenant FK)
│   │   ├── call.py                # Call + Transcript (tenant-scoped)
│   │   ├── emergency_call.py      # EmergencyCall (NOT tenant-scoped - design issue)
│   │   ├── analysis_result.py     # AnalysisResult (tenant-scoped)
│   │   ├── severity_report.py     # SeverityReport (tenant-scoped)
│   │   ├── dispatch_recommendation.py  # DispatchRecommendation (tenant-scoped)
│   │   └── audit_log.py           # AuditLog (tenant-scoped)
│   ├── schemas/                   # API request/response Pydantic models
│   │   ├── base.py                # CoreModel, BaseSchema (id+timestamps), TenantBaseSchema
│   │   ├── user.py                # UserCreate (password validation), Token, TokenPayload
│   │   ├── call.py                # CallCreate, CallResponse
│   │   ├── transcript.py          # TranscriptCreate, TranscriptResponse
│   │   ├── severity_report.py     # SeverityReportCreate, SeverityReportResponse
│   │   ├── analysis_result.py     # AnalysisResultCreate, AnalysisResultResponse
│   │   ├── dispatch_recommendation.py  # DispatchRecommendationCreate/Response
│   │   ├── tenant.py              # TenantCreate, TenantResponse
│   │   └── audit_log.py           # AuditLogCreate, AuditLogResponse
│   ├── services/
│   │   ├── base.py                # CRUDBase (generic get/create/update/remove)
│   │   ├── call_service.py        # CRUDCall, CRUDTranscript, CRUDAnalysis, CRUDDispatch
│   │   ├── call_processing.py     # CallProcessor (Stage 2 pipeline via events)
│   │   ├── severity_service.py    # compute_severity() - categorical (low/medium/high/critical)
│   │   ├── severity_engine.py     # SeverityEngine - numeric 0-10 (LOW/MEDIUM/HIGH)
│   │   ├── dispatch_service.py    # select_responder() - rule-based routing
│   │   ├── intent_service.py      # classify_intent() - keyword heuristic (pre-ML)
│   │   ├── whisper_service.py     # WhisperService - local Whisper STT wrapper
│   │   ├── translation_service.py # TranslationService - LibreTranslate (external)
│   │   ├── geocoder.py            # Geocoder - Nominatim/OSM (external)
│   │   ├── ml_client.py           # MLClient - HTTP client to ml_service
│   │   ├── cache_service.py       # cache_call(), get_cached_call() - Redis
│   │   └── tenant_service.py      # Tenant CRUD
│   ├── ml/
│   │   ├── intent_model_loader.py # ONNX DistilBERT loader + auto-export
│   │   └── emotion_model_loader.py # ONNX CNN loader + PyTorch→ONNX export
│   ├── plugins/                   # DEAD CODE - never initialized
│   │   ├── base.py                # BasePlugin ABC
│   │   ├── registry.py            # PluginRegistry (dynamic loading)
│   │   └── */mock_*.py            # Mock plugin implementations
│   ├── middleware/
│   │   └── security_headers.py    # X-Frame-Options, X-Content-Type-Options, etc.
│   ├── dashboard/
│   │   ├── call_store.py          # In-memory deque (thread-safe, NOT cross-worker)
│   │   ├── routes.py              # GET /dashboard (HTML), GET /api/v1/calls/live (JSON)
│   │   └── templates/index.html   # Dashboard Jinja2 template
│   └── websockets/
│       └── connection_manager.py  # WebSocket /ws/calls/{call_id} with Redis pub/sub
├── ml_service/
│   └── app.py                     # Standalone FastAPI ML service (emotion CNN + keyword analysis)
├── tests/
│   ├── conftest.py                # Adds backend/ to sys.path
│   ├── test_intent_agent.py       # IntentAgent unit tests
│   ├── test_emotion_agent.py      # EmotionAgent unit tests
│   ├── test_severity_agent.py     # SeverityAgent tests
│   ├── test_dispatch_agent.py     # DispatchAgent tests
│   ├── test_stage2_flow.py        # Stage 2 pipeline tests
│   └── test_security_fixes.py     # Security config validation tests
├── alembic/                       # Database migration tool
│   ├── env.py
│   └── versions/
│       └── 0001_add_analysis_and_dispatch_tables.py
├── Dockerfile                     # Python 3.11-slim + ffmpeg + CPU PyTorch
├── requirements.txt               # All Python dependencies
├── gunicorn.conf.py               # Gunicorn config (UvicornWorker, 120s timeout)
└── prometheus.yml                 # Prometheus scrape config
```

### Node.js Layout
```
src/
├── server.js           # Entry point - starts Express, initializes DB
├── app.js              # Express routes (health, Twilio webhooks, REST API)
├── config/index.js     # dotenv config (PORT, DATABASE_URL, Twilio, Google)
├── db/index.js         # PostgreSQL pool + raw SQL (call_history table)
├── ivr/
│   ├── index.js        # processCall() pipeline + buildGreetingTwiml()
│   └── speechToText.js # Google Cloud Speech-to-Text wrapper
├── analysis/index.js   # Keyword-based severity (critical/high/medium/low)
├── routing/index.js    # Keyword-based responder (ambulance/fire/police/other)
├── summary/index.js    # Text summary builder for dispatchers
└── translation/index.js # Google Cloud Translate wrapper
tests/
├── analysis.test.js
├── routing.test.js
├── speechToText.test.js
├── summary.test.js
└── translation.test.js
```
