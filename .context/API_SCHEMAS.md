# Redline AI - API Schemas & Types

## Pipeline DTOs (`backend/app/core/schemas/`)

### Transcript
```python
class Transcript(BaseModel):
    text: str                           # Transcribed text
    confidence: float                   # 0.0-1.0
    language: str = "en"                # Language code
    timestamp: datetime                 # Transcription time
    audio_duration: Optional[float]     # Audio length in seconds
    speaker_id: Optional[str]          # Speaker identifier
```

### IntentType (Enum)
```python
MEDICAL = "medical"
FIRE = "fire"
VIOLENT_CRIME = "violent_crime"
ACCIDENT = "accident"
GAS_HAZARD = "gas_hazard"
MENTAL_HEALTH = "mental_health"
NON_EMERGENCY = "non_emergency"
UNKNOWN = "unknown"
```

### IntentAnalysis
```python
class IntentAnalysis(BaseModel):
    intent: IntentType                          # Primary intent
    confidence: float                           # 0.0-1.0
    intent_scores: Dict[IntentType, float]      # Per-class probabilities
    fallback_used: bool = False                 # True if keyword fallback
    metadata: Dict[str, str] = {}               # {"source": "onnx"|"keyword", "reason": ...}
```

### EmotionType (Enum)
```python
ANGER = "anger"
FEAR = "fear"
SADNESS = "sadness"
JOY = "joy"
SURPRISE = "surprise"
DISGUST = "disgust"
NEUTRAL = "neutral"
```

### EmotionAnalysis
```python
class EmotionAnalysis(BaseModel):
    primary_emotion: EmotionType               # Dominant emotion
    emotion_scores: Dict[EmotionType, float]   # Per-emotion probabilities
    intensity: float                           # 0.0-1.0
    confidence: float                          # 0.0-1.0
    text_segments: List[str] = []              # Analyzed text segments
```

### SeverityLevel (Enum)
```python
LOW = "low"
MEDIUM = "medium"
HIGH = "high"
CRITICAL = "critical"
```

### SeverityAssessment (used by dead orchestrator only)
```python
class SeverityAssessment(BaseModel):
    level: SeverityLevel
    score: float                    # 0.0-1.0
    factors: Dict[str, float]       # Contributing factors
    reasoning: str                  # Explanation
    confidence: float               # 0.0-1.0
```

### SafetyStatus (Enum) — dead code
```python
SAFE = "safe"
WARNING = "warning"
UNSAFE = "unsafe"
```

### SafetyOutput — dead code
```python
class SafetyOutput(BaseModel):
    status: SafetyStatus
    issues: List[str] = []
    recommendations: List[str] = []
    confidence: float
    metadata: Dict[str, Any] = {}
```

### ReasoningOutput — dead code
```python
class ReasoningOutput(BaseModel):
    key_insights: List[str]
    risk_factors: List[str]
    context_summary: str
    confidence: float
    metadata: Dict[str, Any] = {}
```

### DispatchAction (Enum) — dead code
```python
SEND_EMERGENCY_SERVICES = "send_emergency_services"
NOTIFY_AUTHORITIES = "notify_authorities"
MONITOR_SITUATION = "monitor_situation"
NO_ACTION_REQUIRED = "no_action_required"
```

### DispatchReport — dead code
```python
class DispatchReport(BaseModel):
    action: DispatchAction
    priority: str
    resources_required: List[str] = []
    location: Optional[str]
    estimated_response_time: Optional[str]
    reasoning: str
    timestamp: datetime
    confidence: float
```

---

## API Schemas (`backend/app/schemas/`)

### Base
```python
class CoreModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class BaseSchema(CoreModel):
    id: UUID
    created_at: datetime
    updated_at: datetime

class TenantBaseSchema(BaseSchema):
    tenant_id: UUID
```

### User
```python
class UserCreate(CoreModel):
    email: EmailStr
    password: str   # min 12 chars, requires upper+lower+digit
    role: RoleEnum = RoleEnum.viewer
    tenant_id: UUID

class UserResponse(TenantBaseSchema):
    email: EmailStr
    role: RoleEnum

class Token(CoreModel):
    access_token: str
    token_type: str

class TokenPayload(CoreModel):
    sub: Optional[str]
    tenant_id: Optional[str]
    role: Optional[str]
```

### Call
```python
class CallCreate(CoreModel):
    caller_number: str

class CallResponse(TenantBaseSchema):
    caller_number: str
    status: CallStatus  # active | closed
```

### Transcript
```python
class TranscriptCreate(CoreModel):
    original_text: str
    language: str = "en"

class TranscriptResponse(TenantBaseSchema):
    call_id: UUID
    original_text: str
    translated_text: Optional[str]
    language: str
```

### SeverityReport
```python
class SeverityReportCreate(CoreModel):
    severity_score: int
    category: str
    keywords_detected: List[str] = []

class SeverityReportResponse(TenantBaseSchema):
    call_id: UUID
    severity_score: int
    category: str
    keywords_detected: List[str]
```

### AnalysisResult
```python
class AnalysisResultCreate(CoreModel):
    call_id: UUID
    incident_type: str
    panic_score: float
    keyword_score: float
    severity_prediction: Optional[int]
    location_text: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    geo_confidence: Optional[float]

class AnalysisResultResponse(TenantBaseSchema):
    # Same fields as Create + id, timestamps, tenant_id
```

### DispatchRecommendation
```python
class DispatchRecommendationCreate(CoreModel):
    call_id: UUID
    unit_id: str
    eta_minutes: Optional[float]
    priority: str

class DispatchRecommendationResponse(TenantBaseSchema):
    # Same fields + id, timestamps, tenant_id
```

### Tenant
```python
class TenantCreate(CoreModel):
    name: str

class TenantResponse(BaseSchema):    # Note: BaseSchema, not TenantBaseSchema
    name: str
```

### Emergency Endpoint (inline schemas)
```python
class EmergencyJSONRequest(BaseModel):
    transcript: str  # max_length=10_000
    caller_id: Optional[str]  # max_length=64

class EmergencyResponse(BaseModel):
    call_id: str
    transcript: str
    intent: str
    intent_confidence: float
    emotion: str
    severity: str
    responder: str
    latency_ms: int
    caller_id: Optional[str]
```

---

## JWT Token Structure
```json
{
    "exp": "2026-05-16T14:00:00Z",
    "sub": "user-uuid-string",
    "tenant_id": "tenant-uuid-string",
    "role": "dispatcher"
}
```
- Algorithm: HS256
- Signing key: SECRET_KEY env var
- Default expiry: 120 minutes
