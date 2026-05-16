# Redline AI - Infrastructure & Deployment

## Docker Compose Services

```
┌─────────────────────────────────────────────────────────┐
│                    docker-compose.yml                     │
│                                                          │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   app    │  │ celery_worker│  │    ml_service     │  │
│  │ :8000   │  │  (background) │  │    :8001          │  │
│  │ Gunicorn │  │  Celery       │  │ Uvicorn          │  │
│  │ +Uvicorn │  │  (stubs only) │  │ emotion CNN      │  │
│  └────┬─────┘  └──────┬───────┘  └────────┬─────────┘  │
│       │               │                    │             │
│       └───────┬───────┴────────────────────┘             │
│               │                                          │
│        ┌──────┴──────┐    ┌──────────────┐              │
│        │   redis     │    │   postgres   │              │
│        │   :6379     │    │   :5432      │              │
│        │   7-alpine  │    │   15-alpine  │              │
│        └─────────────┘    └──────────────┘              │
│                                                          │
│        ┌──────────────┐    ┌──────────────┐             │
│        │ prometheus   │    │   grafana    │             │
│        │ :9090        │    │   :3000      │             │
│        └──────────────┘    └──────────────┘             │
└─────────────────────────────────────────────────────────┘
```

### Port Mapping
| Service | Internal Port | External Port | Notes |
|---|---|---|---|
| app | 8000 | 8000 | Only externally exposed backend |
| celery_worker | — | — | No ports, background processing |
| ml_service | 8001 | — | Internal only (expose, not ports) |
| redis | 6379 | — | Internal only |
| postgres | 5432 | — | Internal only |
| prometheus | 9090 | — | Internal only |
| grafana | 3000 | 3000 | Dashboard UI |

### Container Dependencies
```
app          → redis (healthy), postgres (healthy)
celery_worker → redis (healthy), postgres (healthy)
ml_service    → none (standalone)
prometheus    → app
grafana       → prometheus
```

### Health Checks
| Service | Method | Interval |
|---|---|---|
| app | curl http://localhost:8000/health | 30s (start_period: 120s) |
| celery_worker | ps aux | 30s |
| ml_service | python urllib.request.urlopen(...) | 30s (start_period: 45s) |
| redis | redis-cli ping | 10s |
| postgres | pg_isready | 10s |

---

## Dockerfile (Python Backend)

```dockerfile
FROM python:3.11-slim
# System deps: gcc, ffmpeg (for Whisper audio), curl (for healthcheck)
# Step 1: Install CPU-only PyTorch (200MB vs 3GB CUDA)
# Step 2: pip install -r requirements.txt
# Non-root user: app
# CMD: gunicorn app.main:app -c gunicorn.conf.py
```

### Gunicorn Config
- Worker class: UvicornWorker (async ASGI)
- Workers: max(2, cpu_count) — override via GUNICORN_WORKERS
- Timeout: 120s (Whisper STT is slow on CPU)
- Max requests: 1000 (worker recycling)
- Max requests jitter: 100

---

## Environment Variables

### Required
| Variable | Description | Example |
|---|---|---|
| SECRET_KEY | JWT signing key | `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| POSTGRES_USER | DB user | redline_user |
| POSTGRES_PASSWORD | DB password | (generate random) |
| POSTGRES_DB | DB name | redline |

### Optional
| Variable | Default | Description |
|---|---|---|
| APP_ENV | development | development/production |
| USE_SQLITE | true | Use SQLite (dev) or PostgreSQL |
| POSTGRES_SERVER | localhost | DB host |
| POSTGRES_PORT | 5432 | DB port |
| REDIS_URL | redis://localhost:6379 | Redis connection |
| ML_SERVICE_URL | http://localhost:8001 | ML microservice |
| WHISPER_MODEL_SIZE | small | tiny/base/small/medium/large |
| ALLOWED_ORIGINS | http://localhost:3000,http://localhost:5173 | CORS origins |
| ENABLE_DOCS | true | Swagger/ReDoc (disabled in prod) |
| TWILIO_AUTH_TOKEN | — | Twilio webhook validation |
| GROQ_API_KEY | — | Groq LLM API (unused currently) |
| GUNICORN_WORKERS | cpu_count | Worker count override |
| GF_ADMIN_PASSWORD | — | Grafana admin password |

---

## Key Dependencies

### Python (`requirements.txt`)
| Package | Version | Purpose |
|---|---|---|
| fastapi | >=0.104.1 | Web framework |
| uvicorn[standard] | >=0.24.0 | ASGI server |
| gunicorn | >=21.2.0 | Process manager |
| celery | >=5.3.6 | Task queue |
| sqlalchemy[asyncio] | >=2.0.23 | ORM |
| asyncpg | >=0.29.0 | PostgreSQL async driver |
| redis | >=5.0.1 | Redis client |
| PyJWT[crypto] | >=2.8.0 | JWT auth |
| passlib[bcrypt] | >=1.7.4 | Password hashing |
| onnxruntime | >=1.17.0 | ML inference |
| transformers | >=4.36.0 | Tokenizer + model loading |
| openai-whisper | >=20231117 | Speech-to-text |
| structlog | >=24.1.0 | Structured logging |
| prometheus-client | >=0.20.0 | Metrics |
| starlette-prometheus | >=0.9.0 | Middleware metrics |
| pybreaker | >=1.2.0 | Circuit breaker |
| slowapi | >=0.1.9 | Rate limiting |
| twilio | >=9.0.0 | Webhook validation |
| torch | >=2.1.0 | PyTorch (for model export) |
| numpy | >=1.26.0,<2.0 | Numerics |
| httpx | >=0.25.2 | Async HTTP client |

### Node.js (`package.json`)
| Package | Version | Purpose |
|---|---|---|
| express | ^5.2.1 | Web framework |
| @google-cloud/speech | ^7.2.1 | Google STT |
| @google-cloud/translate | ^9.3.0 | Google Translate |
| twilio | ^5.12.2 | Twilio SDK |
| pg | ^8.18.0 | PostgreSQL client |
| dotenv | ^17.3.1 | Env file loading |
| uuid | ^13.0.0 | UUID generation |
| jest | ^30.2.0 | Testing (dev) |

---

## Security Configuration

### Middleware Stack (order matters)
1. SecurityHeadersMiddleware (X-Frame-Options, X-Content-Type-Options, etc.)
2. CORSMiddleware (configured origins, no wildcard in prod)
3. SlowAPIMiddleware (rate limiting)
4. PrometheusMiddleware (metrics collection)

### Auth Flow
```
Client → Bearer token in Authorization header
  → HTTPBearer scheme extracts token
  → jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
  → Payload contains: sub (user_id), tenant_id, role
  → get_current_user queries DB for user
  → get_tenant_id extracts and validates tenant
```

### WebSocket Auth
```
Client → ws://host/ws/calls/{call_id}?token=JWT
  → jwt.decode from query param
  → DB lookup: EmergencyCall.call_id → verify tenant_id matches
  → Accept or close(4001/4003)
```

### Password Policy
- Minimum 12 characters
- At least 1 uppercase letter
- At least 1 lowercase letter
- At least 1 digit
- Enforced via Pydantic validator on UserCreate
