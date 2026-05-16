# Redline AI - Pipeline Documentation

## Three Pipelines Exist (Current State)

### Pipeline A: Orchestrator (DEAD CODE — never invoked)
**File**: `backend/app/core/orchestrator.py`
**Status**: Scaffolded, never called from any endpoint or service.

```
Audio → STT Agent → Emotion Agent → Reasoning Agent → Severity Agent → Safety Agent → Dispatch Agent
```
- Uses PluginRegistry to load agents (PluginRegistry also never initialized)
- All agents are mock implementations
- 30s timeout per stage
- Sequential execution only

---

### Pipeline B: Emergency Endpoint (WORKING — main pipeline)
**File**: `backend/app/api/v1/endpoints/emergency.py`
**Endpoint**: `POST /process-emergency`
**Auth**: JWT required
**Status**: Functional. Handles both audio upload and text transcript.

```
Request (audio_file OR transcript)
  │
  ├── If audio_file:
  │     → Validate MIME type (ALLOWED_AUDIO_TYPES)
  │     → Validate size (MAX_AUDIO_BYTES = 25MB)
  │     → Whisper STT → text
  │
  ├── If transcript (form or JSON):
  │     → Validate length (MAX_TRANSCRIPT_LENGTH = 10,000 chars)
  │
  ▼
  Text transcript
  │
  ├── IntentAgent.process(Transcript)
  │     → ONNX DistilBERT (500ms timeout)
  │     → Fallback: keyword matching
  │     → Returns: intent, confidence, fallback_used
  │
  ├── EmotionAgent.process(Transcript)
  │     → ONNX CNN (800ms soft budget, 3s hard timeout)
  │     → Circuit breaker (3 failures → 60s cooldown)
  │     → Fallback: keyword heuristic
  │     → Returns: emotion, confidence, fallback_used
  │
  ├── compute_severity(transcript, emotion)
  │     → Keyword matching + emotion boost
  │     → Returns: critical | high | medium | low
  │
  ├── select_responder(intent, severity)
  │     → Rule-based routing
  │     → Returns: fire_dispatch | ambulance | police_dispatch | general_responder | call_center_followup
  │
  ├── Persist to PostgreSQL (emergency_calls table, NOT tenant-scoped)
  │
  ├── Cache to Redis (fire-and-forget, 5min TTL)
  │
  └── Add to dashboard in-memory store
  │
  ▼
  EmergencyResponse {
    call_id, transcript, intent, intent_confidence,
    emotion, severity, responder, latency_ms, caller_id
  }
```

---

### Pipeline C: Event-Driven Tenant Pipeline (BROKEN — import error)
**Files**: `backend/app/api/v1/endpoints/calls.py` → `backend/app/services/call_processing.py`
**Trigger**: `POST /api/v1/calls/{call_id}/transcript`
**Auth**: JWT + tenant isolation
**Status**: BROKEN. Imports `DispatchService` which was removed from `dispatch_service.py`.

```
POST /api/v1/calls/{call_id}/transcript
  │
  ├── CallProcessor.save_transcript()
  │     → Translate via LibreTranslate (if non-English)
  │     → Persist transcript to DB (tenant-scoped)
  │     → Publish TRANSCRIPT_RECEIVED event to Redis
  │
  ▼ (Redis pub/sub → event_listener.py)
  │
  ├── CallProcessor.process_transcript()
  │     → Publish PROCESSING_STARTED event
  │     → MLClient.analyze() → HTTP POST to ml_service:8001/analyze
  │     │   (keyword-based incident detection, panic/keyword scores)
  │     → Persist AnalysisResult
  │     → Publish ML_ANALYSIS_COMPLETE event
  │     │
  │     ├── SeverityEngine.calculate(panic, keyword, incident)
  │     │     → Numeric 0-10 score + category
  │     ├── Persist SeverityReport
  │     ├── Publish SEVERITY_UPDATED event
  │     │
  │     ├── Geocoder.geocode(location_text)
  │     │     → Nominatim/OSM reverse geocode
  │     ├── Update AnalysisResult with lat/lng
  │     ├── Publish LOCATION_RESOLVED event
  │     │
  │     ├── DispatchService.recommend()  ← BROKEN IMPORT
  │     ├── Persist DispatchRecommendation
  │     └── Publish DISPATCH_RECOMMENDED event
  │
  ▼ (Redis pub/sub → WebSocket)
  │
  WebSocket clients receive real-time events per stage
```

### Event Types (Redis pub/sub)
| Event | Source | Consumer |
|---|---|---|
| TRANSCRIPT_RECEIVED | save_transcript() | event_listener → process_transcript() |
| PROCESSING_STARTED | process_transcript() | WebSocket clients |
| ML_ANALYSIS_COMPLETE | process_transcript() | WebSocket clients |
| SEVERITY_UPDATED | process_transcript() | WebSocket clients |
| LOCATION_RESOLVED | process_transcript() | WebSocket clients |
| DISPATCH_RECOMMENDED | process_transcript() | WebSocket clients |

### Infinite Loop Protection
- event_listener ignores: PROCESSING_STARTED, ML_ANALYSIS_COMPLETE, SEVERITY_UPDATED, LOCATION_RESOLVED, DISPATCH_RECOMMENDED
- Only TRANSCRIPT_RECEIVED triggers processing
- process_transcript() publishes PROCESSING_STARTED (not TRANSCRIPT_RECEIVED)

---

### Node.js Pipeline (Separate app)
**File**: `src/ivr/index.js`
**Trigger**: Twilio webhook → `POST /api/calls/handle-recording`

```
Twilio recording URL
  → Google Cloud Speech-to-Text
  → Detect language
  → Google Cloud Translate (if non-English)
  → Keyword severity analysis (critical/high/medium/low)
  → Keyword responder routing (ambulance/fire/police/other)
  → Build text summary
  → Insert into call_history table (PostgreSQL)
  → Return TwiML response to Twilio
```

---

## Endpoint Map

### Python Backend (FastAPI, port 8000)
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | /health | None | Health check (DB, Redis, models) |
| GET | /metrics | None | Prometheus metrics |
| GET | /docs | None (dev only) | Swagger UI |
| POST | /api/v1/auth/login | Rate limited 5/min | OAuth2 login → JWT |
| POST | /api/v1/auth/register | JWT (super_admin) | Create user |
| POST | /api/v1/calls/start | JWT + tenant | Start new call session |
| GET | /api/v1/calls/ | JWT + tenant | List calls for tenant |
| GET | /api/v1/calls/{id} | JWT + tenant | Get specific call |
| POST | /api/v1/calls/{id}/transcript | JWT + tenant | Add transcript chunk |
| POST | /api/v1/calls/{id}/analyze | JWT + tenant | Generate severity report |
| POST | /process-emergency | JWT | Full pipeline (audio or text) |
| GET | /dashboard | JWT | HTML dashboard |
| GET | /api/v1/calls/live | JWT | Recent calls JSON (dashboard) |
| WS | /ws/calls/{call_id}?token=... | JWT via query param | Real-time call events |

### Node.js (Express, port 3000)
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | /health | None | Health check |
| POST | /api/calls/incoming | Twilio signature | IVR greeting webhook |
| POST | /api/calls/handle-recording | Twilio signature | Recording webhook |
| POST | /api/calls | **NONE** | Manual call submission |
| GET | /api/calls | **NONE** | List all calls |
| GET | /api/calls/:id | **NONE** | Get call by ID |
| PATCH | /api/calls/:id/status | **NONE** | Update call status |

### ML Service (FastAPI, port 8001 — internal only)
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | /health | None | Health check |
| POST | /analyze | None | Text → keyword analysis |
| POST | /analyze-audio | None | Audio → emotion CNN |
