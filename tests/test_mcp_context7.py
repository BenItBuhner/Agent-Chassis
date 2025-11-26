"""
Tests for Context7 MCP server integration via Streamable HTTP transport.

Tests both direct connection and integration via MCPManager.
"""

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


@pytest.mark.asyncio
@pytest.mark.integration
async def test_direct_context7_connection():
    """Test direct connection to Context7 via Streamable HTTP."""
    url = "https://mcp.context7.com/mcp"
    try:
        async with streamablehttp_client(url=url, timeout=30.0) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) > 0, "Should discover tools from Context7"

                # Verify we got some tools
                tool_names = [tool.name for tool in tools.tools]
                assert len(tool_names) > 0
    except Exception as e:
        pytest.fail(f"Failed to connect to Context7: {e}")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_context7_via_mcp_manager():
    """Test Context7 via MCPManager with fallback logic."""
    from app.services.mcp_manager import mcp_manager

    try:
        await mcp_manager.load_servers()
        tools = await mcp_manager.list_tools()

        # Should have at least one server connected
        assert len(mcp_manager.sessions) > 0, "Should have at least one MCP server connected"

        # Should discover tools
        assert len(tools) > 0, "Should discover tools from MCP servers"

        # Verify Context7 is in the list of servers
        server_names = list(mcp_manager.sessions.keys())
        assert "Context7" in server_names, "Context7 server should be loaded"

        await mcp_manager.cleanup()
    except Exception as e:
        await mcp_manager.cleanup()
        pytest.fail(f"Failed to test Context7 via MCPManager: {e}")
