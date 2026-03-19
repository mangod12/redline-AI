"""Redline AI MCP Server.

Exposes the emergency-call analysis pipeline as MCP tools, resources,
and prompts so any MCP-compatible client (Claude Desktop, Gemini,
custom agents) can use Redline AI capabilities.

Tools:
    analyze_emergency  – Full pipeline (intent + emotion + severity + dispatch)
    classify_intent    – Intent classification only
    detect_emotion     – Emotion analysis only
    assess_severity    – Severity scoring from transcript + emotion

Resources:
    redline://system/health   – Live system health snapshot
    redline://calls/recent    – Last 50 processed calls

Prompts:
    emergency-triage – Template for structured emergency analysis
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import (
    CallToolResult,
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    ReadResourceResult,
    Resource,
    TextContent,
    TextResourceContents,
    Tool,
)

log = logging.getLogger("redline_ai.mcp")

# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

server = Server("redline-ai")

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

_TOOLS: list[Tool] = [
    Tool(
        name="analyze_emergency",
        description=(
            "Run the full Redline AI emergency analysis pipeline on a transcript. "
            "Returns intent classification, emotion detection, severity assessment, "
            "and recommended responder."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "transcript": {
                    "type": "string",
                    "description": "The emergency call transcript text to analyze.",
                },
            },
            "required": ["transcript"],
        },
    ),
    Tool(
        name="classify_intent",
        description=(
            "Classify the intent of an emergency call transcript. "
            "Returns one of: medical, fire, violent_crime, accident, "
            "gas_hazard, mental_health, non_emergency, unknown."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "transcript": {
                    "type": "string",
                    "description": "The emergency call transcript text.",
                },
            },
            "required": ["transcript"],
        },
    ),
    Tool(
        name="detect_emotion",
        description=(
            "Detect the primary emotion in an emergency call transcript. "
            "Returns one of: anger, fear, sadness, joy, surprise, disgust, neutral "
            "along with intensity and confidence scores."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "transcript": {
                    "type": "string",
                    "description": "The emergency call transcript text.",
                },
            },
            "required": ["transcript"],
        },
    ),
    Tool(
        name="assess_severity",
        description=(
            "Assess the severity of an emergency call given a transcript and "
            "detected emotion. Returns a severity level (low, medium, high, critical) "
            "and the recommended responder type."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "transcript": {
                    "type": "string",
                    "description": "The emergency call transcript text.",
                },
                "emotion": {
                    "type": "string",
                    "description": "Primary emotion (e.g. 'fear', 'anger', 'neutral').",
                    "default": "neutral",
                },
            },
            "required": ["transcript"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return _TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> CallToolResult:
    arguments = arguments or {}
    transcript = arguments.get("transcript", "")

    if not transcript.strip():
        return CallToolResult(
            content=[TextContent(type="text", text="Error: transcript is required and must be non-empty.")],
            isError=True,
        )

    if name == "analyze_emergency":
        return await _tool_analyze_emergency(transcript)
    if name == "classify_intent":
        return await _tool_classify_intent(transcript)
    if name == "detect_emotion":
        return await _tool_detect_emotion(transcript)
    if name == "assess_severity":
        emotion = arguments.get("emotion", "neutral")
        return await _tool_assess_severity(transcript, emotion)

    return CallToolResult(
        content=[TextContent(type="text", text=f"Unknown tool: {name}")],
        isError=True,
    )


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def _run_intent(transcript: str) -> dict[str, Any]:
    """Run intent classification, returning a plain dict."""
    from app.agents.intent.intent_agent import IntentAgent
    from app.core.schemas import Transcript

    agent = IntentAgent(loader=None)
    result = await agent.process(Transcript(text=transcript, confidence=1.0))
    return {
        "intent": result.intent.value,
        "confidence": round(float(result.confidence), 3),
        "fallback_used": result.fallback_used,
    }


async def _run_emotion(transcript: str) -> dict[str, Any]:
    """Run emotion detection, returning a plain dict."""
    from app.agents.emotion.emotion_agent import EmotionAgent
    from app.core.schemas import Transcript

    agent = EmotionAgent(loader=None)
    result = await agent.process(Transcript(text=transcript, confidence=1.0))
    return {
        "primary_emotion": result.primary_emotion.value,
        "intensity": round(float(result.intensity), 3),
        "confidence": round(float(result.confidence), 3),
    }


async def _tool_analyze_emergency(transcript: str) -> CallToolResult:
    """Full pipeline: intent + emotion + severity + dispatch."""
    from app.services.dispatch_service import select_responder
    from app.services.severity_service import compute_severity

    intent_data = await _run_intent(transcript)
    emotion_data = await _run_emotion(transcript)

    severity = await compute_severity(transcript, emotion_data["primary_emotion"])
    responder = await select_responder(intent_data["intent"], severity)

    result = {
        "transcript": transcript,
        "intent": intent_data,
        "emotion": emotion_data,
        "severity": severity,
        "responder": responder,
    }
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, indent=2))],
    )


async def _tool_classify_intent(transcript: str) -> CallToolResult:
    result = await _run_intent(transcript)
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, indent=2))],
    )


async def _tool_detect_emotion(transcript: str) -> CallToolResult:
    result = await _run_emotion(transcript)
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, indent=2))],
    )


async def _tool_assess_severity(transcript: str, emotion: str) -> CallToolResult:
    from app.services.dispatch_service import select_responder
    from app.services.severity_service import compute_severity

    severity = await compute_severity(transcript, emotion)

    intent_data = await _run_intent(transcript)
    responder = await select_responder(intent_data["intent"], severity)

    result = {
        "severity": severity,
        "emotion_used": emotion,
        "intent": intent_data["intent"],
        "responder": responder,
    }
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, indent=2))],
    )


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@server.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri="redline://system/health",
            name="System Health",
            description="Live health status of Redline AI services (models, DB, Redis).",
            mimeType="application/json",
        ),
        Resource(
            uri="redline://calls/recent",
            name="Recent Calls",
            description="Last 50 emergency calls processed through the pipeline.",
            mimeType="application/json",
        ),
    ]


@server.read_resource()
async def read_resource(uri: str) -> ReadResourceResult:
    if str(uri) == "redline://system/health":
        return await _resource_health()
    if str(uri) == "redline://calls/recent":
        return _resource_recent_calls()

    return ReadResourceResult(
        contents=[TextResourceContents(uri=uri, text=f"Unknown resource: {uri}")],
    )


async def _resource_health() -> ReadResourceResult:
    """Return system health as JSON."""
    from app.core.redis_client import get_redis_client

    redis = get_redis_client()
    redis_status = "disconnected"
    if redis:
        try:
            await redis.ping()
            redis_status = "connected"
        except Exception:
            redis_status = "error"

    health = {
        "status": "ok" if redis_status != "error" else "degraded",
        "redis": redis_status,
        "mcp_server": "running",
    }
    return ReadResourceResult(
        contents=[TextResourceContents(uri="redline://system/health", text=json.dumps(health, indent=2))],
    )


def _resource_recent_calls() -> ReadResourceResult:
    """Return recent calls from the in-memory store."""
    from app.dashboard import call_store

    calls = call_store.get_recent(limit=50)
    return ReadResourceResult(
        contents=[TextResourceContents(uri="redline://calls/recent", text=json.dumps(calls, indent=2))],
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name="emergency-triage",
            description=(
                "Structured emergency call triage analysis. Provide a transcript "
                "and get a comprehensive assessment with recommended actions."
            ),
            arguments=[
                PromptArgument(
                    name="transcript",
                    description="The emergency call transcript to analyze.",
                    required=True,
                ),
                PromptArgument(
                    name="context",
                    description="Additional context (e.g. location, caller history).",
                    required=False,
                ),
            ],
        ),
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
    if name != "emergency-triage":
        raise ValueError(f"Unknown prompt: {name}")

    arguments = arguments or {}
    transcript = arguments.get("transcript", "")
    context = arguments.get("context", "")

    user_text = (
        "Analyze this emergency call transcript using the Redline AI tools.\n\n"
        f"## Transcript\n{transcript}\n\n"
    )
    if context:
        user_text += f"## Additional Context\n{context}\n\n"

    user_text += (
        "## Instructions\n"
        "1. Use `analyze_emergency` to run the full pipeline on the transcript.\n"
        "2. Review the intent, emotion, severity, and responder recommendation.\n"
        "3. Provide a human-readable summary with:\n"
        "   - **Situation Assessment**: What is happening and how urgent is it?\n"
        "   - **Risk Factors**: Key danger indicators from the transcript.\n"
        "   - **Recommended Action**: What responders should be dispatched and why.\n"
        "   - **Special Considerations**: Any emotional state or context that "
        "dispatchers should be aware of.\n"
    )

    return GetPromptResult(
        description="Emergency call triage analysis",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(type="text", text=user_text),
            ),
        ],
    )
