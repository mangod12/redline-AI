# Redline AI - ML Models & Pipeline

## Models Overview

| Model | Architecture | Format | Input | Output | Location |
|---|---|---|---|---|---|
| Intent Classifier | DistilBERT (fine-tuned) | ONNX | Text (max 128 tokens) | 8-class probabilities | `ml/intent_model.onnx` (auto-exported) |
| Emotion Detector | CNN (custom) | ONNX (from .pt) | MFCC (1×1×40×94 float32) | 8-class probabilities | `ml/emotion_model.onnx` (auto-exported) |
| Speech-to-Text | OpenAI Whisper | PyTorch | Audio bytes (wav/mp3/etc) | Text transcript | Downloaded at startup (cached) |

---

## Intent Classification Model

### Architecture
- **Base**: `distilbert-base-uncased` (HuggingFace)
- **Fine-tuned**: Yes, custom training on emergency dispatch dataset
- **Training code**: `ml/train_intent_model.py`
- **Saved model**: `ml/intent_model/` (config.json, model.safetensors, tokenizer.json)
- **ONNX export**: Auto-exported at startup if `ml/intent_model.onnx` missing

### 8 Intent Classes (`IntentType` enum)
```
medical        - chest pain, not breathing, seizure, overdose, bleeding
fire           - fire, burning, smoke, flames
violent_crime  - gun, weapon, knife, shooting, stabbing, assault, robbery
accident       - accident, collision, crash, vehicle
gas_hazard     - gas leak, fumes, carbon monoxide, chemical smell
mental_health  - suicidal, self harm, panic, depressed, crisis
non_emergency  - noise complaint, parking, lost wallet, information
unknown        - fallback when confidence < 0.6
```

### Inference Path (`IntentAgent`)
```
Text input
  → Tokenize (AutoTokenizer, max_length=128)
  → ONNX Runtime (CPUExecutionProvider, 1 thread)
  → Softmax → probabilities
  → If max_prob >= 0.6 → return ML result
  → If max_prob < 0.6 OR timeout (500ms) OR exception → keyword fallback
```

### Keyword Fallback Rules
Regex patterns checked in order. Returns confidence=0.65 with `fallback_used=True`.

### Prometheus Metrics
- `intent_latency` (Histogram) — inference latency in seconds
- `intent_fallback_count` (Counter, label=reason) — timeout/exception/low_confidence/empty_text

### Loader: `IntentModelLoader`
- ThreadPoolExecutor(max_workers=2)
- Double-checked locking for initialization
- Auto-exports ONNX from HuggingFace if .onnx missing
- Stored on `app.state.intent_loader`

---

## Emotion Detection Model

### Architecture
- **Type**: Custom CNN (`EmotionModel` in `ml/model.py`)
- **Input**: MFCC features (1 channel, 40 mel bands, 94 time frames)
- **Training code**: `ml/train_emotion_cnn_multidataset.py`
- **Saved model**: `ml/emotion_model.pt` (PyTorch checkpoint)
- **ONNX export**: Auto-exported at startup if `ml/emotion_model.onnx` missing

### 8 Emotion Labels
```
neutral, calm, happy, sad, angry, fearful, disgust, surprised
```

### Mapped to EmotionType enum (7 values):
```
EmotionType.NEUTRAL   ← neutral + calm
EmotionType.JOY       ← happy
EmotionType.SADNESS   ← sad
EmotionType.ANGER     ← angry
EmotionType.FEAR      ← fearful
EmotionType.DISGUST   ← disgust
EmotionType.SURPRISE  ← surprised
```

### Inference Path (`EmotionAgent`)
```
Transcript input (text only, no raw audio in current pipeline)
  → Mock MFCC (zeros 1×1×40×94) — real audio featurization not wired yet
  → Circuit breaker check (pybreaker, fail_max=3, reset_timeout=60s)
  → ONNX Runtime inference (3s hard timeout)
  → Softmax → probabilities
  → If confidence >= 0.5 → return ML result
  → If ML fails/slow (800ms soft budget) → keyword heuristic fallback
  → If circuit open → immediate neutral fallback (confidence=0.0)
```

### Keyword Heuristic Fallback
Two keyword sets scored:
- **Urgency**: help, emergency, fire, gun, blood, dying, scared, attacked, can't breathe, choking, hostile, weapon, explosion, crash, accident
- **Distress**: hurt, pain, alone, please, quickly, fast, bad, bleeding, unconscious, faint

Rules:
- urgency_hits >= 2 → FEAR (confidence 0.65)
- urgency_hits == 1 OR distress_hits >= 2 → SADNESS (confidence 0.55)
- else → NEUTRAL (confidence 0.75)

### Prometheus Metrics
- `ml_inference_latency_seconds` (Histogram)
- `ml_failure_count_total` (Counter, label=reason)
- `fallback_usage_count_total` (Counter, label=trigger)

### Loader: `EmotionModelLoader`
- ThreadPoolExecutor(max_workers=2)
- Supports CUDA + CPU providers
- Auto-exports PyTorch → ONNX if .onnx missing
- Stored on `app.state.emotion_loader`

---

## Whisper STT Service

### Configuration
- **Model sizes**: tiny | base | small | medium | large
- **Default**: small (env: WHISPER_MODEL_SIZE)
- **Library**: openai-whisper (local, no API calls)
- **Inference**: Runs in ThreadPoolExecutor via asyncio.run_in_executor

### Whisper Flow
```
Audio bytes
  → Write to NamedTemporaryFile (.wav)
  → whisper.load_model(model_size).transcribe(path, fp16=False)
  → Extract text from result
  → Delete temp file
  → Return text string
```

### Resource Considerations
- Whisper `small` model: ~500MB RAM
- Whisper `tiny` model: ~75MB RAM (used in Docker default)
- Blocking CPU inference offloaded to thread pool
- FileLock prevents concurrent model downloads on multi-worker startup

---

## ML Service (Standalone Container)

### Location: `backend/ml_service/app.py`
- Separate FastAPI app running on port 8001
- Loads `EmotionModel` from `ml/emotion_model.pt`
- Endpoints:
  - `POST /analyze-audio` — raw audio → emotion prediction
  - `POST /analyze` — text → keyword-based analysis (incident type, panic score, keyword score, severity prediction, location extraction)
- **Note**: The `/analyze` endpoint is what `CallProcessor` calls via `MLClient`, but it's just keyword matching, not real ML.

---

## Training Data (`datasets/`)

| File | Classes |
|---|---|
| `final_8class_dataset_clean.csv` | All 8 intent classes (merged) |
| `intent_8class_dataset.csv` | Intent training dataset |
| `medical_dataset.csv` | Medical emergency transcripts |
| `fire_dataset.csv` | Fire emergency transcripts |
| `violent_crime_dataset.csv` | Crime transcripts |
| `accident_dataset.csv` | Accident transcripts |
| `gas_hazard_dataset.csv` | Gas/hazard transcripts |
| `mental_health_dataset.csv` | Mental health crisis transcripts |
| `non_emergency_dataset.csv` | Non-emergency transcripts |
| `unknown_dataset.csv` | Unknown/ambiguous transcripts |
| `tweets.csv` | Supplementary data |

### Training Scripts (`ml/`)
- `train_intent_model.py` — Fine-tune DistilBERT for intent classification
- `train_emotion_cnn_multidataset.py` — Train CNN emotion model
- `build_*.py` — Dataset generation scripts per class
- `build_merge_dataset.py` — Merge all class datasets
- `check_overlap.py` — Validate no data leakage between splits
- `intent_distilbert_training_colab.ipynb` — Colab training notebook

---

## Severity Scoring (Two Implementations)

### Pipeline B: `severity_service.py` → `compute_severity(transcript, emotion)`
- **Output**: categorical string — `critical | high | medium | low`
- **Method**: Keyword matching + emotion-based promotion
- Keyword tiers: CRITICAL (dying, gun, shot...) → HIGH (fire, blood...) → MEDIUM (hurt, injury...) → LOW
- Emotion boost: fear/anger promotes one tier; sadness/surprise/disgust promotes low→medium only

### Pipeline C: `severity_engine.py` → `SeverityEngine.calculate(panic, keyword, incident)`
- **Output**: numeric 0-10 score + category (LOW/MEDIUM/HIGH)
- **Method**: `0.4 * panic_score + 0.3 * keyword_score + 0.3 * incident_priority`
- Incident priorities: fire=1.0, medical=0.9, intrusion=0.8, unknown=0.5
- Categories: score >= 7 → HIGH, >= 4 → MEDIUM, else LOW

### Pipeline B Dispatch: `dispatch_service.py` → `select_responder(intent, severity)`
- Rule-based: critical+fire → fire_dispatch, critical+medical → ambulance, etc.
- Returns: fire_dispatch | ambulance | police_dispatch | general_responder | call_center_followup
