import os
import sys
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel

# Add the root directory to sys.path so we can import from ml.model and ml.utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ml_service")

# Global model instance
emotion_model = None
_device = "cpu"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global emotion_model, _device
    import torch
    from ml.model import EmotionModel
    from ml.utils import load_model

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    model_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ml", "emotion_model.pt",
    )

    logger.info("Loading emotion model from %s...", model_path)
    try:
        emotion_model = load_model(model_path, EmotionModel, device=_device)
        logger.info("ML Service ready (device=%s)", _device)
    except Exception as exc:
        logger.error("Failed to load emotion model: %s", exc)
        emotion_model = None

    yield

    emotion_model = None
    logger.info("ML Service shut down")


app = FastAPI(title="Redline AI ML Service", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok" if emotion_model is not None else "degraded",
        "model_loaded": emotion_model is not None,
        "device": _device,
    }


class AnalyzeRequest(BaseModel):
    call_id: str
    transcript: str
    language: str


class AnalyzeResponse(BaseModel):
    incident_type: str
    panic_score: float
    keyword_score: float
    severity_prediction: int
    primary_emotion: str
    confidence: float
    location_text: Optional[str] = None


@app.post("/analyze-audio")
async def analyze_audio(file: UploadFile = File(...)):
    """Analyze raw audio for emotion using the CNN model."""
    if not emotion_model:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        from ml.utils import predict_emotion
        audio_bytes = await file.read()
        result = predict_emotion(emotion_model, audio_bytes, device=_device)

        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Audio analysis failed: %s", e)
        raise HTTPException(status_code=500, detail="Audio analysis failed")


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    """Keyword-based text analysis for incident classification."""
    text = req.transcript.lower()

    # Incident detection
    incident = "unknown"
    if "fire" in text:
        incident = "fire"
    elif any(w in text for w in ["break", "intrusion", "house", "robbery"]):
        incident = "intrusion"
    elif any(w in text for w in ["medical", "sick", "hospital"]):
        incident = "medical"

    panic = 0.8 if any(w in text for w in ["help", "emergency", "urgent", "breaking", "attack"]) else 0.2
    keyword = 0.6 if any(w in text for w in ["gun", "fire", "blood", "kill", "intrusion", "break"]) else 0.1
    severity_prediction = int(min((panic + keyword) / 2 * 10, 10))

    # Location extraction
    location = None
    if "near" in text:
        idx = text.find("near")
        location = text[idx + 5 : idx + 55].strip() or None

    # Keywords for additional context
    keywords = [w for w in ["gun", "fire", "blood", "help", "emergency"] if w in text]

    return {
        "incident_type": incident,
        "panic_score": panic,
        "keyword_score": keyword,
        "severity_prediction": severity_prediction,
        "primary_emotion": "fear" if panic > 0.5 else "neutral",
        "confidence": 0.7,
        "location_text": location,
        "keywords": keywords,
    }
