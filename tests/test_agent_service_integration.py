"""
Integration tests for AgentService with real OpenAI API calls.

Tests both streaming and blocking modes with local tools and MCP tools.
Requires OPENAI_API_KEY to be configured.
"""

import asyncio
import json

import pytest
import pytest_asyncio
from openai import AsyncOpenAI

from app.core.config import settings
from app.schemas.agent import ChatMessage, CompletionRequest
from app.services.agent_service import AgentService
from app.services.mcp_manager import mcp_manager

# Test timeout: 120 seconds per test (API calls can be slow)
TEST_TIMEOUT = 120.0


@pytest.fixture
def check_openai_configured():
    """Skip tests if OpenAI API key is not configured."""
    if not settings.OPENAI_API_KEY:
        pytest.skip("OPENAI_API_KEY not configured - skipping integration tests")


@pytest_asyncio.fixture
async def mcp_setup():
    """Setup MCP servers for integration tests that need MCP tools."""
    try:
        await mcp_manager.load_servers()
        yield
    except Exception as e:
        pytest.skip(f"Failed to load MCP servers: {e}")
    finally:
        # Cleanup MCP connections
        try:
            await mcp_manager.cleanup()
        except Exception:
            # Ignore cleanup errors (task group issues are OK in teardown)
            pass


@pytest.fixture
def openai_client(check_openai_configured):
    """Create OpenAI client for tests."""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL, timeout=120.0)
    return client


@pytest.fixture
def agent_service(openai_client):
    """Create AgentService instance for tests."""
    return AgentService(openai_client)


# =============================================================================
# Local Tools Tests (Calculator/Time)
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agent_service_blocking_local_tools(agent_service, check_openai_configured):
    """Test blocking mode with local tools (calculator and time). Doesn't require MCP setup."""
    # Patch mcp_manager.list_tools to return empty list quickly (avoid MCP server calls)
    from unittest.mock import patch

    prompt = "Calculate 5 * 5 and then tell me the result."
    tools = ["calculate", "get_server_time"]

    request = CompletionRequest(
        messages=[ChatMessage(role="user", content=prompt)],
        allowed_tools=tools,
        stream=False,
    )

    # Mock MCP manager to avoid hanging on MCP server calls
    with patch("app.services.agent_service.mcp_manager.list_tools", return_value=[]):
        try:
            response, session_id = await asyncio.wait_for(
                agent_service.run_agent(request),
                timeout=TEST_TIMEOUT,
            )
        except TimeoutError:
            pytest.fail(f"Test timed out after {TEST_TIMEOUT} seconds")
        except Exception as e:
            pytest.fail(f"Agent execution failed: {e}")

    # Verify response structure
    assert response.role == "assistant", f"Expected assistant role, got {response.role}"
    assert response.content is not None, "Response content should not be None"
    assert len(response.content) > 0, "Response content should not be empty"

    # Verify the response mentions the calculation result (25)
    # Be lenient - the model might phrase it differently
    content_lower = response.content.lower()
    assert "25" in response.content or "twenty-five" in content_lower or "twenty five" in content_lower, (
        f"Expected '25' in response, got: {response.content[:200]}"
    )

    # Tool calls might not always be present depending on model behavior
    # Just verify the response is valid
    if response.tool_calls:
        tool_names = [tc["function"]["name"] for tc in response.tool_calls]
        # If tool calls exist, verify calculate was used
        assert "calculate" in tool_names, f"Expected 'calculate' in tool calls, got: {tool_names}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agent_service_streaming_local_tools(agent_service, check_openai_configured):
    """Test streaming mode with local tools (calculator and time). Doesn't require MCP setup."""
    # Patch mcp_manager.list_tools to return empty list quickly (avoid MCP server calls)
    from unittest.mock import patch

    prompt = "Calculate 10 + 20 and tell me the result."
    tools = ["calculate", "get_server_time"]

    request = CompletionRequest(
        messages=[ChatMessage(role="user", content=prompt)],
        allowed_tools=tools,
        stream=True,
    )

    chunks = []
    content_parts = []
    tool_results = []

    # Mock MCP manager to avoid hanging on MCP server calls
    with patch("app.services.agent_service.mcp_manager.list_tools", return_value=[]):
        try:

            async def collect_chunks():
                async for chunk_str in agent_service.run_agent_stream(request):
                    chunk = json.loads(chunk_str)
                    chunks.append(chunk)
                    chunk_type = chunk.get("type")

                    if chunk_type == "content":
                        content_parts.append(chunk.get("content", ""))
                    elif chunk_type == "tool_result":
                        tool_results.append(chunk)

            await asyncio.wait_for(collect_chunks(), timeout=TEST_TIMEOUT)
        except TimeoutError:
            pytest.fail(f"Test timed out after {TEST_TIMEOUT} seconds")
        except Exception as e:
            pytest.fail(f"Streaming failed: {e}")

    # Verify we got chunks
    assert len(chunks) > 0, "Should receive at least one chunk"

    # Verify we got a finish chunk
    assert chunks[-1]["type"] == "finish", f"Last chunk should be 'finish', got: {chunks[-1].get('type')}"

    # Verify we got content
    full_content = "".join(content_parts)
    assert len(full_content) > 0, "Should receive content chunks"

    # Verify the response mentions the calculation result (30)
    content_lower = full_content.lower()
    assert "30" in full_content or "thirty" in content_lower, f"Expected '30' in response, got: {full_content[:200]}"

    # Tool results might not always be present in streaming mode
    # Just verify we got valid chunks
    if tool_results:
        tool_names = [tr.get("tool") for tr in tool_results]
        assert "calculate" in tool_names, f"Expected 'calculate' in tool results, got: {tool_names}"


# =============================================================================
# MCP Tools Tests (Memory Server)
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agent_service_blocking_mcp_tools(agent_service, mcp_setup):
    """Test blocking mode with MCP memory tools."""
    # Check if memory server is available
    tools = await mcp_manager.list_tools()
    memory_tools = [t for t in tools if "create" in t.name.lower() or "memory" in t.name.lower()]

    if not memory_tools:
        pytest.skip("Memory MCP server not available - skipping MCP tool test")

    prompt = "Create a memory entity named 'TestEntity' with a description 'This is a test entity'."
    tool_names = [t.name for t in memory_tools[:1]]  # Use first memory tool

    request = CompletionRequest(
        messages=[ChatMessage(role="user", content=prompt)],
        allowed_tools=tool_names,
        stream=False,
    )

    try:
        response, session_id = await asyncio.wait_for(
            agent_service.run_agent(request),
            timeout=TEST_TIMEOUT,
        )
    except TimeoutError:
        pytest.fail(f"Test timed out after {TEST_TIMEOUT} seconds")
    except Exception as e:
        pytest.fail(f"Agent execution failed: {e}")

    # Verify response structure
    assert response.role == "assistant"
    assert response.content is not None
    assert len(response.content) > 0

    # Tool calls might not always be present depending on model behavior
    # Just verify the response is valid


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agent_service_streaming_mcp_tools(agent_service, mcp_setup):
    """Test streaming mode with MCP memory tools."""
    # Check if memory server is available
    tools = await mcp_manager.list_tools()
    memory_tools = [t for t in tools if "create" in t.name.lower() or "memory" in t.name.lower()]

    if not memory_tools:
        pytest.skip("Memory MCP server not available - skipping MCP tool test")

    prompt = "Create a memory entity named 'StreamTestEntity'."
    tool_names = [t.name for t in memory_tools[:1]]  # Use first memory tool

    request = CompletionRequest(
        messages=[ChatMessage(role="user", content=prompt)],
        allowed_tools=tool_names,
        stream=True,
    )

    chunks = []
    content_parts = []
    tool_results = []

    try:

        async def collect_chunks():
            async for chunk_str in agent_service.run_agent_stream(request):
                chunk = json.loads(chunk_str)
                chunks.append(chunk)
                chunk_type = chunk.get("type")

                if chunk_type == "content":
                    content_parts.append(chunk.get("content", ""))
                elif chunk_type == "tool_result":
                    tool_results.append(chunk)

        await asyncio.wait_for(collect_chunks(), timeout=TEST_TIMEOUT)
    except TimeoutError:
        pytest.fail(f"Test timed out after {TEST_TIMEOUT} seconds")
    except Exception as e:
        pytest.fail(f"Streaming failed: {e}")

    # Verify we got chunks
    assert len(chunks) > 0

    # Verify we got a finish chunk
    assert chunks[-1]["type"] == "finish"

    # Verify we got content
    full_content = "".join(content_parts)
    assert len(full_content) > 0

    # Tool results might not always be present in streaming mode
    # Just verify we got valid chunks


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agent_service_no_tools(agent_service, check_openai_configured):
    """Test agent service without any tools. Doesn't require MCP setup."""
    # Patch mcp_manager.list_tools to return empty list quickly (avoid MCP server calls)
    from unittest.mock import patch

    prompt = "What is 2 + 2? Just answer with the number."

    request = CompletionRequest(
        messages=[ChatMessage(role="user", content=prompt)],
        allowed_tools=[],  # No tools
        stream=False,
    )

    # Mock MCP manager to avoid hanging on MCP server calls
    with patch("app.services.agent_service.mcp_manager.list_tools", return_value=[]):
        try:
            response, session_id = await asyncio.wait_for(
                agent_service.run_agent(request),
                timeout=TEST_TIMEOUT,
            )
        except TimeoutError:
            pytest.fail(f"Test timed out after {TEST_TIMEOUT} seconds")
        except Exception as e:
            pytest.fail(f"Agent execution failed: {e}")

    # Verify response structure
    assert response.role == "assistant"
    assert response.content is not None
    assert len(response.content) > 0

    # Should not have tool calls
    assert response.tool_calls is None or len(response.tool_calls) == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agent_service_invalid_tool_name(agent_service, check_openai_configured):
    """Test agent service with invalid tool name (should still work, just won't use that tool)."""
    # Patch mcp_manager.list_tools to return empty list quickly (avoid MCP server calls)
    from unittest.mock import patch

    prompt = "Calculate 3 * 3 and tell me the result."
    tools = ["calculate", "nonexistent_tool_12345"]  # One valid, one invalid

    request = CompletionRequest(
        messages=[ChatMessage(role="user", content=prompt)],
        allowed_tools=tools,
        stream=False,
    )

    # Mock MCP manager to avoid hanging on MCP server calls
    with patch("app.services.agent_service.mcp_manager.list_tools", return_value=[]):
        try:
            response, session_id = await asyncio.wait_for(
                agent_service.run_agent(request),
                timeout=TEST_TIMEOUT,
            )
        except TimeoutError:
            pytest.fail(f"Test timed out after {TEST_TIMEOUT} seconds")
        except Exception as e:
            pytest.fail(f"Agent execution failed: {e}")

    # Should still work, just won't use the invalid tool
    assert response.role == "assistant"
    assert response.content is not None

    # Should use the valid tool (calculate) if tool calls are made
    if response.tool_calls:
        tool_names = [tc["function"]["name"] for tc in response.tool_calls]
        assert "calculate" in tool_names
        assert "nonexistent_tool_12345" not in tool_names


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agent_service_multiple_turns(agent_service, check_openai_configured):
    """Test agent service with multiple conversation turns. Doesn't require MCP setup."""
    # Patch mcp_manager.list_tools to return empty list quickly (avoid MCP server calls)
    from unittest.mock import patch

    # First turn
    request1 = CompletionRequest(
        messages=[
            ChatMessage(role="user", content="Calculate 5 + 5"),
        ],
        allowed_tools=["calculate"],
        stream=False,
    )

    # Mock MCP manager to avoid hanging on MCP server calls
    with patch("app.services.agent_service.mcp_manager.list_tools", return_value=[]):
        try:
            response1, session_id1 = await asyncio.wait_for(
                agent_service.run_agent(request1),
                timeout=TEST_TIMEOUT,
            )
        except TimeoutError:
            pytest.fail(f"First turn timed out after {TEST_TIMEOUT} seconds")
        except Exception as e:
            pytest.fail(f"First turn failed: {e}")

    assert response1.role == "assistant"
    assert "10" in response1.content or "ten" in response1.content.lower()

    # Second turn (continuing conversation)
    request2 = CompletionRequest(
        messages=[
            ChatMessage(role="user", content="Calculate 5 + 5"),
            ChatMessage(role="assistant", content=response1.content),
            ChatMessage(role="user", content="Now multiply that result by 2"),
        ],
        allowed_tools=["calculate"],
        stream=False,
    )

    # Mock MCP manager again for second turn
    with patch("app.services.agent_service.mcp_manager.list_tools", return_value=[]):
        try:
            response2, session_id2 = await asyncio.wait_for(
                agent_service.run_agent(request2),
                timeout=TEST_TIMEOUT,
            )
        except TimeoutError:
            pytest.fail(f"Second turn timed out after {TEST_TIMEOUT} seconds")
        except Exception as e:
            pytest.fail(f"Second turn failed: {e}")

    assert response2.role == "assistant"
    assert response2.content is not None
    # Should mention 20 (10 * 2)
    assert "20" in response2.content or "twenty" in response2.content.lower()
