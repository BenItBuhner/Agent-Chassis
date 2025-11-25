import json
import shutil
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client

from app.core.config import settings


class MCPManager:
    def __init__(self):
        self.config_path = Path(settings.MCP_CONFIG_PATH)
        self.sessions: dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()

    async def load_servers(self):
        """
        Reads the MCP config file and initializes connections to the servers.
        """
        if not self.config_path.exists():
            print(f"MCP Config file not found at {self.config_path}")
            return

        with open(self.config_path) as f:
            config = json.load(f)

        mcp_servers = config.get("mcpServers", {})

        for server_name, server_config in mcp_servers.items():
            print(f"Loading MCP server: {server_name}")
            try:
                if "url" in server_config:
                    await self._connect_sse_server(server_name, server_config)
                elif "command" in server_config:
                    await self._connect_stdio_server(server_name, server_config)
                else:
                    print(f"Skipping {server_name}: Unknown server configuration (missing 'url' or 'command')")
            except Exception as e:
                print(f"Failed to connect to {server_name}: {e}")

    async def _connect_stdio_server(self, name: str, config: dict[str, Any]):
        command = config.get("command")
        args = config.get("args", [])
        env = config.get("env")

        if shutil.which(command) is None:
            print(f"Warning: Command '{command}' not found in PATH.")
        else:
            # Resolve full path (helps on Windows with .cmd/.exe)
            command = shutil.which(command)

        server_params = StdioServerParameters(command=command, args=args, env=env)

        read, write = await self.exit_stack.enter_async_context(stdio_client(server_params))

        session = await self.exit_stack.enter_async_context(ClientSession(read, write))

        await session.initialize()
        self.sessions[name] = session
        print(f"Connected to MCP server (Stdio): {name}")

    async def _connect_sse_server(self, name: str, config: dict[str, Any]):
        url = config.get("url")
        headers = config.get("headers", {})

        # sse_client yields (read, write) streams
        read, write = await self.exit_stack.enter_async_context(sse_client(url=url, headers=headers))

        session = await self.exit_stack.enter_async_context(ClientSession(read, write))

        await session.initialize()
        self.sessions[name] = session
        print(f"Connected to MCP server (SSE): {name}")

    async def list_tools(self) -> list[Any]:
        """
        Aggregates tools from all connected MCP servers.
        """
        all_tools = []
        for name, session in self.sessions.items():
            try:
                result = await session.list_tools()
                for tool in result.tools:
                    all_tools.append({"server": name, "tool": tool})
            except Exception as e:
                print(f"Error listing tools from {name}: {e}")
        return all_tools

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> Any:
        session = self.sessions.get(server_name)
        if not session:
            raise ValueError(f"Server {server_name} not found")

        result = await session.call_tool(tool_name, arguments=arguments)
        return result

    async def cleanup(self):
        """
        Closes all connections.
        """
        await self.exit_stack.aclose()
        self.sessions.clear()


mcp_manager = MCPManager()
