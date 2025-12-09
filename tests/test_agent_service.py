import json
from unittest.mock import AsyncMock, patch

import pytest
from mcp.types import Tool

from app.schemas.agent import CompletionRequest
from app.services import agent_service
from app.services.agent_service import AgentService


# Helper mocks for OpenAI objects
class MockDelta:
    def __init__(self, role=None, content=None, tool_calls=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls


class MockChoice:
    def __init__(self, delta):
        self.delta = delta


class MockChunk:
    def __init__(self, delta):
        self.choices = [MockChoice(delta)]


@pytest.mark.asyncio
async def test_run_agent_server_mode_rejected_when_persistence_disabled():
    """Server-side mode should fail fast without persistence to avoid fake session IDs"""
    mock_client = AsyncMock()
    service = AgentService(mock_client)
    request = CompletionRequest(session_id="abc123", message="Hello", stream=False)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await service.run_agent(request)

    assert exc.value.status_code == 400
    assert "persistence" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_run_agent_stream_server_mode_rejected_when_persistence_disabled():
    """Streaming server-side mode should also fail fast without persistence"""
    mock_client = AsyncMock()
    service = AgentService(mock_client)
    request = CompletionRequest(session_id="abc123", message="Hello", stream=True)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        async for _ in service.run_agent_stream(request):
            pass

    assert exc.value.status_code == 400
    assert "persistence" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_run_agent_stream_content_only():
    mock_client = AsyncMock()

    # Mock the stream generator
    async def stream_generator(*args, **kwargs):
        # Yield chunks simulating a simple response
        yield MockChunk(MockDelta(role="assistant", content="Hello"))
        yield MockChunk(MockDelta(content=" World"))

    mock_client.chat.completions.create.side_effect = stream_generator

    service = AgentService(mock_client)
    request = CompletionRequest(messages=[{"role": "user", "content": "Hi"}], stream=True)

    # Patch mcp_manager to avoid real calls and return empty list
    with patch("app.services.agent_service.mcp_manager") as mock_mcp:
        mock_mcp.list_tools = AsyncMock(return_value=[])

        chunks = []
        async for chunk in service.run_agent_stream(request):
            chunks.append(json.loads(chunk))

    # Verify content chunks
    content_chunks = [c for c in chunks if c.get("type") == "content"]
    assert len(content_chunks) == 2
    assert content_chunks[0]["content"] == "Hello"
    assert content_chunks[1]["content"] == " World"

    # Verify finish
    assert chunks[-1]["type"] == "finish"


@pytest.mark.asyncio
async def test_run_agent_stream_api_error_handling():
    """Test that the stream yields an error JSON instead of crashing on API failure"""
    mock_client = AsyncMock()
    # Simulate an exception when calling OpenAI
    mock_client.chat.completions.create.side_effect = Exception("Simulated API Failure")

    service = AgentService(mock_client)
    request = CompletionRequest(messages=[{"role": "user", "content": "Hi"}], stream=True)

    with patch("app.services.agent_service.mcp_manager") as mock_mcp:
        mock_mcp.list_tools = AsyncMock(return_value=[])

        chunks = []
        async for chunk in service.run_agent_stream(request):
            chunks.append(json.loads(chunk))

    # Expect a single error chunk
    assert len(chunks) == 1
    assert "error" in chunks[0]
    assert "Simulated API Failure" in chunks[0]["error"]


@pytest.mark.asyncio
async def test_run_agent_hardening_non_stream():
    """Test that non-streaming agent raises 500 on API failure with generic message (security)"""
    mock_client = AsyncMock()
    mock_client.chat.completions.create.side_effect = Exception("Critical Fail")

    service = AgentService(mock_client)
    request = CompletionRequest(messages=[{"role": "user", "content": "Hi"}], stream=False)

    with patch("app.services.agent_service.mcp_manager") as mock_mcp:
        mock_mcp.list_tools = AsyncMock(return_value=[])

        # Should raise HTTPException with GENERIC message (not internal error details)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await service.run_agent(request)

        assert exc.value.status_code == 500
        # Security: Internal error details should NOT be exposed to clients
        assert exc.value.detail == "Agent execution failed"
        assert "Critical Fail" not in exc.value.detail  # Internal details hidden


@pytest.mark.asyncio
async def test_get_tools_merge_and_filter(monkeypatch):
    """Smoke: ensure _get_tools merges MCP + local then filters by allowed_tools."""
    mock_client = AsyncMock()
    service = AgentService(mock_client)

    mcp_tool = Tool(
        name="remote_tool",
        description="remote",
        inputSchema={"type": "object", "properties": {"x": {"type": "number"}}},
    )

    monkeypatch.setattr(
        agent_service.mcp_manager,
        "list_tools",
        AsyncMock(return_value=[{"server": "s1", "tool": mcp_tool}]),
    )

    def local_example(y: int):
        return y

    monkeypatch.setattr(agent_service.local_registry, "get_tools", lambda: {"local_example": local_example})

    request = CompletionRequest(messages=[{"role": "user", "content": "ping"}], allowed_tools=["remote_tool"])

    openai_tools, mcp_tools_list, local_tools_map = await service._get_tools(request)

    assert [t["function"]["name"] for t in openai_tools] == ["remote_tool"]
    assert mcp_tools_list[0]["tool"].name == "remote_tool"
    assert "local_example" in local_tools_map
