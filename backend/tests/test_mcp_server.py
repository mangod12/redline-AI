"""Tests for the MCP server tools, resources, and prompts.

These tests exercise the MCP handler functions directly (without
an actual MCP transport) to verify that the Redline AI pipeline
is correctly exposed through MCP.
"""

from __future__ import annotations

import json

import pytest

from app.mcp.server import (
    call_tool,
    get_prompt,
    list_prompts,
    list_resources,
    list_tools,
    read_resource,
)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_returns_four_tools():
    tools = await list_tools()
    names = {t.name for t in tools}
    assert names == {"analyze_emergency", "classify_intent", "detect_emotion", "assess_severity"}


@pytest.mark.asyncio
async def test_analyze_emergency_returns_full_pipeline():
    result = await call_tool("analyze_emergency", {"transcript": "Someone is having a heart attack"})
    assert not result.isError
    data = json.loads(result.content[0].text)
    assert "intent" in data
    assert "emotion" in data
    assert "severity" in data
    assert "responder" in data


@pytest.mark.asyncio
async def test_classify_intent_returns_intent():
    result = await call_tool("classify_intent", {"transcript": "There is a fire in my building"})
    assert not result.isError
    data = json.loads(result.content[0].text)
    assert "intent" in data
    assert "confidence" in data


@pytest.mark.asyncio
async def test_detect_emotion_returns_emotion():
    result = await call_tool("detect_emotion", {"transcript": "Please help me I am so scared"})
    assert not result.isError
    data = json.loads(result.content[0].text)
    assert "primary_emotion" in data
    assert "intensity" in data
    assert "confidence" in data


@pytest.mark.asyncio
async def test_assess_severity_returns_severity():
    result = await call_tool(
        "assess_severity",
        {"transcript": "Someone was stabbed", "emotion": "fear"},
    )
    assert not result.isError
    data = json.loads(result.content[0].text)
    assert data["severity"] in ("low", "medium", "high", "critical")
    assert "responder" in data


@pytest.mark.asyncio
async def test_empty_transcript_returns_error():
    result = await call_tool("analyze_emergency", {"transcript": ""})
    assert result.isError


@pytest.mark.asyncio
async def test_unknown_tool_returns_error():
    result = await call_tool("nonexistent_tool", {"transcript": "hello"})
    assert result.isError


@pytest.mark.asyncio
async def test_missing_transcript_returns_error():
    result = await call_tool("classify_intent", {})
    assert result.isError


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_resources_returns_two():
    resources = await list_resources()
    uris = {str(r.uri) for r in resources}
    assert "redline://system/health" in uris
    assert "redline://calls/recent" in uris


@pytest.mark.asyncio
async def test_read_recent_calls_returns_json():
    result = await read_resource("redline://calls/recent")
    data = json.loads(result.contents[0].text)
    assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_prompts_returns_emergency_triage():
    prompts = await list_prompts()
    names = {p.name for p in prompts}
    assert "emergency-triage" in names


@pytest.mark.asyncio
async def test_get_prompt_returns_structured_message():
    result = await get_prompt(
        "emergency-triage",
        {"transcript": "There is a gas leak in my house"},
    )
    assert result.description == "Emergency call triage analysis"
    assert len(result.messages) == 1
    assert "gas leak" in result.messages[0].content.text


@pytest.mark.asyncio
async def test_get_prompt_with_context():
    result = await get_prompt(
        "emergency-triage",
        {"transcript": "Car accident on highway", "context": "Rural area, nearest hospital 30 min away"},
    )
    assert "Rural area" in result.messages[0].content.text


@pytest.mark.asyncio
async def test_get_unknown_prompt_raises():
    with pytest.raises(ValueError, match="Unknown prompt"):
        await get_prompt("nonexistent", {})
