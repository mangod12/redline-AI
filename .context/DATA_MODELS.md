# Redline AI - Data Models

## Database Strategy

- **Development**: SQLite via aiosqlite (USE_SQLITE=true)
- **Production**: PostgreSQL via asyncpg
- **ORM**: SQLAlchemy 2.0 async
- **Migrations**: Alembic (1 migration exists, but app also uses create_all at startup)

**WARNING**: A duplicate model hierarchy exists at `backend/app/core/memory/postgres_models.py` with its own `Base = declarative_base()`, Integer PKs, and overlapping table names (`emergency_calls`, `transcripts`, `audit_logs`). This is DEAD CODE and conflicts with the canonical models below. See KNOWN_ISSUES.md C7.

---

## SQLAlchemy Models (Python Backend)

### Base Classes (`backend/app/models/base.py`)

```python
class BaseModel(Base):          # Abstract
    id: UUID                    # PK, default=uuid4
    created_at: DateTime(tz)    # default=utcnow
    updated_at: DateTime(tz)    # default=utcnow, onupdate=utcnow

class TenantModel(BaseModel):   # Abstract, inherits BaseModel
    tenant_id: UUID             # FK → tenants.id, CASCADE, indexed
```

### Tenant (`tenants` table)
```
id            UUID PK
name          String, indexed, NOT NULL
created_at    DateTime(tz)
updated_at    DateTime(tz)
---
Relationships: users (1:N)
```

### User (`users` table) — extends TenantModel
```
id              UUID PK
email           String, unique, indexed, NOT NULL
hashed_password String, NOT NULL
role            Enum(super_admin, tenant_admin, dispatcher, viewer), default=viewer
tenant_id       UUID FK → tenants.id
created_at      DateTime(tz)
updated_at      DateTime(tz)
---
Relationships: tenant (N:1)
```

### Call (`calls` table) — extends TenantModel
```
id              UUID PK
caller_number   String, indexed, NOT NULL
status          Enum(active, closed), default=active
tenant_id       UUID FK → tenants.id
created_at      DateTime(tz)
updated_at      DateTime(tz)
---
Relationships: transcripts (1:N), severity_reports (1:N), analysis_results (1:N), dispatch_recommendations (1:N)
```

### Transcript (`transcripts` table) — extends TenantModel
```
id              UUID PK
call_id         UUID FK → calls.id, CASCADE, indexed
original_text   String, NOT NULL
translated_text String, nullable
language        String, default="en"
tenant_id       UUID FK → tenants.id
created_at      DateTime(tz)
updated_at      DateTime(tz)
---
Relationships: call (N:1)
```

### AnalysisResult (`analysis_results` table) — extends TenantModel
```
id                  UUID PK
call_id             UUID FK → calls.id, CASCADE, indexed
incident_type       String, NOT NULL
panic_score         Float, NOT NULL
keyword_score       Float, NOT NULL
severity_prediction Integer, nullable
location_text       String, nullable
latitude            Float, nullable
longitude           Float, nullable
geo_confidence      Float, nullable
tenant_id           UUID FK → tenants.id
created_at          DateTime(tz)
updated_at          DateTime(tz)
---
Relationships: call (N:1)
```

### SeverityReport (`severity_reports` table) — extends TenantModel
```
id                UUID PK
call_id           UUID FK → calls.id, CASCADE, indexed
severity_score    Integer, indexed, NOT NULL
category          String, NOT NULL (LOW/MEDIUM/HIGH)
keywords_detected JSONB, default=[]
tenant_id         UUID FK → tenants.id
created_at        DateTime(tz)
updated_at        DateTime(tz)
---
Relationships: call (N:1)
```

### DispatchRecommendation (`dispatch_recommendations` table) — extends TenantModel
```
id          UUID PK
call_id     UUID FK → calls.id, CASCADE, indexed
unit_id     String, NOT NULL
eta_minutes Float, nullable
priority    String, NOT NULL
tenant_id   UUID FK → tenants.id
created_at  DateTime(tz)
updated_at  DateTime(tz)
---
Relationships: call (N:1)
```

### AuditLog (`audit_logs` table) — extends TenantModel
```
id          UUID PK
user_id     UUID FK → users.id, SET NULL, nullable
action      String, indexed, NOT NULL
entity_id   String, nullable
entity_type String, nullable
details     JSONB, default={}
tenant_id   UUID FK → tenants.id
created_at  DateTime(tz)
updated_at  DateTime(tz)
```

### EmergencyCall (`emergency_calls` table) — extends Base DIRECTLY (NOT TenantModel)
```
call_id     UUID PK, default=uuid4
caller_id   String(255), nullable, indexed
transcript  Text, NOT NULL
intent      String(64), default="unknown"
emotion     String(64), default="neutral"
severity    String(16), default="low"
responder   String(64), default="general"
created_at  DateTime(tz), indexed
latency_ms  Integer, default=0
---
NOTE: No tenant_id. No updated_at. No relationships.
Used by /process-emergency endpoint (Pipeline B).
```

---

## Node.js Table (`call_history` — raw SQL)

```sql
CREATE TABLE IF NOT EXISTS call_history (
  id            UUID PRIMARY KEY,
  caller_number VARCHAR(20)  NOT NULL,
  timestamp     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  transcript    TEXT         NOT NULL,
  language      VARCHAR(10),
  translation   TEXT,
  severity      VARCHAR(10)  NOT NULL CHECK (severity IN ('low','medium','high','critical')),
  responder     VARCHAR(20)  NOT NULL CHECK (responder IN ('police','fire','ambulance','other')),
  latitude      DOUBLE PRECISION,
  longitude     DOUBLE PRECISION,
  summary       TEXT         NOT NULL,
  status        VARCHAR(20)  NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','dispatched','resolved')),
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
-- Indexes on severity, responder, timestamp
```

---

## ER Diagram (Python Backend)

```
tenants ──1:N── users
tenants ──1:N── calls
                  │
                  ├──1:N── transcripts
                  ├──1:N── analysis_results
                  ├──1:N── severity_reports
                  └──1:N── dispatch_recommendations

tenants ──1:N── audit_logs

emergency_calls (standalone, no FK to tenants or calls)
```

---

## Redis Data Structures

| Key Pattern | Type | TTL | Usage |
|---|---|---|---|
| `emergency_call:{call_id}` | String (JSON) | 300s | Cached pipeline output |
| `call:{call_id}:latest_transcript` | String (JSON) | 3600s | Latest transcript for convenience |
| `call:{call_id}:severity` | String (JSON) | 3600s | Cached severity report |
| `call_events:{call_id}` | Pub/Sub channel | — | Per-call WebSocket events |
| `redline.events.calls` | Pub/Sub channel | — | Global pipeline events |
