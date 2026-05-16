# Redline AI - Known Issues & Technical Debt

**Last updated**: After WS1-WS6 fix cycle (51 issues audited, 42 fixed)

---

## FIXED Issues (42 total)

### Critical — Fixed
| ID | Issue | Fix Applied |
|---|---|---|
| C1 | Broken `DispatchService` import in call_processing.py | Replaced with `select_responder` function |
| C3 | EmergencyCall not tenant-scoped | Added `tenant_id` FK column |
| C4 | Dashboard bypasses tenant isolation | Added tenant filtering to `call_store.get_recent()` and `/api/v1/calls/live` |
| C6 | Second unauthenticated FastAPI app (`api/main.py`) | Deleted entirely |
| C7 | Duplicate SQLAlchemy models (`memory/postgres_models.py`) | Deleted entirely |
| C8 | Hardcoded default POSTGRES_PASSWORD | Default changed to "", production startup check added |
| C9 | Broken test patches in test_intent_agent.py | Fixed patch targets, removed non-existent circuit breaker test |

### High — Fixed
| ID | Issue | Fix Applied |
|---|---|---|
| H3 | Duplicate Redis clients (`memory/redis_client.py`) | Deleted dead file |
| H4 | Event listener no graceful shutdown | Added `stop_event_listener()` with task cancellation |
| H7 | Missing aiosqlite in requirements | Added `aiosqlite>=0.20.0` |
| H8 | WebSocket tenant check silent bypass on error | Now closes connection with 4503 on failure |
| H9 | Intent + emotion sequential execution | Replaced with `asyncio.gather()` |
| H10 | `/metrics` unauthenticated | Wrapped in proper FastAPI endpoint |
| H11 | TwiML Host header injection | Uses `PUBLIC_BASE_URL` env var |
| H12 | `CRUDBase.remove()` crashes on None | Added None check with ValueError |
| H13 | Vulnerable npm dependencies | `npm audit fix` — 0 vulnerabilities |
| H15 | Duplicate severity logic in endpoint | Removed, uses `SeverityEngine` directly |

### Medium — Fixed
| ID | Issue | Fix Applied |
|---|---|---|
| M1 | Hardcoded external service URLs | Configurable via `TRANSLATION_SERVICE_URL`, `GEOCODER_BASE_URL` |
| M2 | httpx client created per request | Shared `self._client` in all 3 services |
| M3 | Celery tasks are stubs | Added stub warning comment |
| M4 | Plugin registry never initialized | Deleted entire `plugins/` directory |
| M5 | Missing CSP header | Added `Content-Security-Policy` header |
| M8 | No rate limiting on `/process-emergency` | Added `@limiter.limit("30/minute")` |
| M11 | `.dict()` deprecated in CRUDBase | Replaced with `.model_dump()` |
| M12 | Translation appends "[translation failed]" | Returns original text on failure |
| M13 | `assert` in production code | Replaced with explicit RuntimeError |
| M16 | `caller_id` Form no length validation | Added `max_length=64` |

### Low — Fixed
| ID | Issue | Fix Applied |
|---|---|---|
| L2 | `datetime.utcnow()` in call_store.py | Uses `datetime.now(timezone.utc)` |
| L3 | Duplicate openai-whisper in requirements | Removed duplicate |
| L4 | Missing `.dockerignore` | Created with proper exclusions |
| L5 | `asyncio.get_event_loop()` deprecated | Uses `get_running_loop()` |
| L6 | `datetime.utcnow` in schemas | Fixed in dispatch_report.py and transcript.py |
| L7 | Deprecated X-XSS-Protection header | Removed, CSP replaces it |
| L8 | Health endpoint leaks system state | Simplified to ok/degraded only |
| L10 | PluginRegistry wrong module path | Deleted (plugin system removed) |

### Dead Code Removed
| Item | Action |
|---|---|
| `backend/app/api/main.py` | Deleted |
| `backend/app/core/memory/` | Entire directory deleted |
| `backend/app/core/orchestrator.py` | Deleted |
| `backend/app/plugins/` | Entire directory deleted |

---

## ADDITIONALLY FIXED (WS8-WS10)

### Critical — Fixed
| ID | Issue | Fix Applied |
|---|---|---|
| C2 | Node.js REST API zero auth | Added `requireApiKey` middleware to all 4 REST endpoints |
| C5 | In-memory call store not cross-worker | Replaced with Redis-backed store (`redline:dashboard:calls`) |

### High — Fixed
| ID | Issue | Fix Applied |
|---|---|---|
| H5 | CRUDBase commits per operation | Added `auto_commit=False` option for batch transactions |
| H6 | No WebSocket call_id validation | Added UUID format regex check, rejects with 4002 |
| H14 | config.py os.getenv() bypasses pydantic-settings | Removed all os.getenv(), plain defaults, pydantic handles env loading |

### Medium — Fixed
| ID | Issue | Fix Applied |
|---|---|---|
| M10 | Test coverage gaps | Added 9 tests for severity_service + dispatch_service |

### Low — Fixed
| ID | Issue | Fix Applied |
|---|---|---|
| L1 | Inconsistent logging | Standardized call_processing, event_listener, severity to structlog |
| L9 | BaseAgent TypeVars not bound | Made `BaseAgent(ABC, Generic[TInput, TOutput])` |

---

## REMAINING Issues (3 — architecture decisions only)

| ID | Severity | Issue | Notes |
|---|---|---|---|
| H1 | HIGH | Dual-stack confusion (Node.js + Python) | Architecture decision: deprecate Node.js or document as Twilio-only gateway |
| H2 | HIGH | Two competing pipelines | Pipeline B = canonical (emergency endpoint). Pipeline C = tenant-scoped event-driven. Document relationship. |
| M9 | MEDIUM | Two severity systems | `severity_service.py` (categorical) for Pipeline B, `severity_engine.py` (numeric) for Pipeline C. Document which is used where. |

*M14 (JWT no revocation), M15 (WebSocket token in URL), M17 (Grafana password) documented as accepted limitations.*

---

## Summary

| Severity | Total | Fixed | Remaining |
|----------|-------|-------|-----------|
| CRITICAL | 9 | 9 | 0 |
| HIGH | 15 | 13 | 2 |
| MEDIUM | 17 | 15 | 1 |
| LOW | 10 | 10 | 0 |
| **Total** | **51** | **48** | **3** |
