# Redline AI - Agent System

## Agent Architecture

### BaseAgent (`backend/app/agents/base.py`)
```python
class BaseAgent(ABC):
    @abstractmethod
    async def process(self, input_data: TInput) -> TOutput
    @abstractmethod
    def get_input_schema(self) -> type[TInput]
    @abstractmethod
    def get_output_schema(self) -> type[TOutput]
```
All agents take a Pydantic model in, return a Pydantic model out.

---

## Implemented Agents

### IntentAgent (`backend/app/agents/intent/intent_agent.py`)
- **Input**: `Transcript` → **Output**: `IntentAnalysis`
- **Strategy**: ONNX first (500ms timeout), keyword fallback
- **ML Model**: DistilBERT fine-tuned on 8 emergency intent classes
- **Fallback**: Regex keyword rules → 0.65 confidence
- **Metrics**: Prometheus histograms + counters
- **Used by**: Pipeline B (emergency endpoint)

### EmotionAgent (`backend/app/agents/emotion/emotion_agent.py`)
- **Input**: `Transcript` → **Output**: `EmotionAnalysis`
- **Strategy**: Prioritized ML with soft budget
  1. Circuit breaker check (pybreaker: 3 fails → 60s cooldown)
  2. ML inference with 800ms soft budget
  3. If ML slow/fails → keyword heuristic (2s budget)
  4. Last resort → neutral fallback (confidence=0.0)
- **ML Model**: CNN on MFCC features (currently receives zero tensor — no real audio path)
- **Fallback**: Keyword urgency/distress scoring
- **Metrics**: Prometheus inference latency, failure counts, fallback usage
- **Used by**: Pipeline B (emergency endpoint)

### SeverityAgent (`backend/app/agents/severity/severity_agent.py`)
- Details in `severity_agent.py` — wraps severity logic as an agent
- **Used by**: Tests only (not wired into any pipeline)

### DispatchAgent (`backend/app/agents/dispatch/dispatch_agent.py`)
- Details in `dispatch_agent.py` — wraps dispatch logic as an agent
- **Used by**: Tests only

### Mock Agents (used only by dead orchestrator)
- `mock_stt_agent.py` — Returns hardcoded transcript
- `mock_emotion_agent.py` — Returns hardcoded emotion
- `mock_reasoning_agent.py` — Returns hardcoded reasoning
- `mock_safety_agent.py` — Returns hardcoded safety output

---

## Plugin System (DEAD CODE)

### BasePlugin (`backend/app/plugins/base.py`)
```python
class BasePlugin(ABC):
    def __init__(self, name, version, config)
    @abstractmethod async def initialize()
    @abstractmethod async def shutdown()
    @abstractmethod def get_capabilities() -> Dict
    async def execute_with_timeout(coro, timeout=30.0)
```

### PluginRegistry (`backend/app/plugins/registry.py`)
- Dynamic plugin loading via `importlib.import_module`
- Directory scanning for auto-discovery
- Plugin lifecycle management (load/unload/shutdown)
- **Never initialized** — no code creates a PluginRegistry instance

### Mock Plugins
| Plugin | Location |
|---|---|
| mock_stt | `plugins/stt/mock_stt.py` |
| mock_emotion | `plugins/emotion/mock_emotion.py` |
| mock_llm | `plugins/llm/mock_llm.py` |
| mock_reasoning | `plugins/reasoning/mock_reasoning.py` |
| mock_safety | `plugins/safety/mock_safety.py` |
| mock_severity | `plugins/severity/mock_severity.py` |
| mock_dispatch | `plugins/dispatch/mock_dispatch.py` |

---

## Orchestrator (DEAD CODE)

### File: `backend/app/core/orchestrator.py`
```python
class Orchestrator:
    def __init__(self, plugin_registry: PluginRegistry)
    async def initialize()                              # Load agents from plugins
    async def process_emergency_call(audio_data: bytes) # 6-stage sequential pipeline
    async def _execute_stage(stage_name, input_data)    # Per-stage with 30s timeout
    def get_pipeline_status() -> Dict[str, bool]        # Stage availability
```

### Intended Pipeline (never executed):
```
STT → Emotion → Reasoning → Severity → Safety → Dispatch
```

### Why Dead:
- No endpoint or service creates an `Orchestrator` instance
- Depends on `PluginRegistry` which is also never initialized
- All 6 stages reference `mock_*` plugins only
- The real pipeline in `emergency.py` was built independently

---

## ML Model Loaders

### IntentModelLoader (`backend/app/ml/intent_model_loader.py`)
```python
class IntentModelLoader:
    # Lifecycle
    async def initialize()        # Load tokenizer + ONNX session
    async def shutdown()          # Release resources
    def is_ready() -> bool

    # Inference
    async def predict_proba(text: str) -> np.ndarray  # Returns class probabilities

    # Internal
    _initialize_sync()           # Auto-exports ONNX if missing
    _predict_sync(text)          # Tokenize → ONNX run → softmax
    _export_default_onnx()       # HuggingFace → ONNX export
```
- ThreadPoolExecutor(max_workers=2)
- Double-checked locking (asyncio.Lock)
- ONNX SessionOptions: 1 thread, CPU only, full optimization

### EmotionModelLoader (`backend/app/ml/emotion_model_loader.py`)
```python
class EmotionModelLoader:
    # Lifecycle
    async def initialize()        # Export PT→ONNX if needed, load session
    async def shutdown()

    # Inference
    async def predict(mfcc: np.ndarray) -> Dict[str, float]  # label → probability
    def is_ready() -> bool
```
- ThreadPoolExecutor(max_workers=2)
- threading.Lock for session access
- Supports CUDA + CPU providers
- 3s inference timeout
- 8 emotion labels: neutral, calm, happy, sad, angry, fearful, disgust, surprised

### App State Storage
```python
# In app lifespan (main.py):
app.state.whisper_service = WhisperService(model_size)
app.state.intent_loader = IntentModelLoader()
app.state.emotion_loader = EmotionModelLoader()  # Optional, loaded if model exists
```
