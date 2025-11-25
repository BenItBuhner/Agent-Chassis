import json
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.agent import CompletionRequest
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
    """Test that non-streaming agent raises 500 on API failure (as per current design)"""
    mock_client = AsyncMock()
    mock_client.chat.completions.create.side_effect = Exception("Critical Fail")

    service = AgentService(mock_client)
    request = CompletionRequest(messages=[{"role": "user", "content": "Hi"}], stream=False)

    with patch("app.services.agent_service.mcp_manager") as mock_mcp:
        mock_mcp.list_tools = AsyncMock(return_value=[])

        # Should raise HTTPException
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await service.run_agent(request)

        assert exc.value.status_code == 500
        assert "Critical Fail" in exc.value.detail
