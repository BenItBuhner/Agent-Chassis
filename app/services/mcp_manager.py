import json
import logging
import shutil
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolRequest, CallToolRequestParams
from pydantic import AnyUrl, BaseModel, ConfigDict

from app.core.config import settings

logger = logging.getLogger("agent_chassis.mcp")

# Conditional imports for OAuth (may not be needed for all deployments)
try:
    from mcp.client.auth import OAuthClientProvider, TokenStorage
    from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

    OAUTH_AVAILABLE = True
except ImportError:
    OAUTH_AVAILABLE = False


class PermissiveResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    content: Any = None
    isError: bool = False


class InMemoryTokenStorage(TokenStorage):
    """
    Simple in-memory token storage for OAuth.
    For production, use FileTokenStorage from oauth_storage.py.
    """

    def __init__(self):
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> "OAuthToken | None":
        return self.tokens

    async def set_tokens(self, tokens: "OAuthToken") -> None:
        self.tokens = tokens

    async def get_client_info(self) -> "OAuthClientInformationFull | None":
        return self.client_info

    async def set_client_info(self, client_info: "OAuthClientInformationFull") -> None:
        self.client_info = client_info


class MCPManager:
    """
    Manages connections to MCP servers using multiple transport protocols:
    - Stdio: For local subprocess-based servers (command)
    - SSE: Legacy Server-Sent Events transport (url + transport: "sse")
    - Streamable HTTP: Modern HTTP transport (url + transport: "streamable-http")

    Supports OAuth 2.1 authentication for protected MCP servers.
    """

    # Supported transport types for URL-based servers
    TRANSPORT_STREAMABLE_HTTP = "streamable-http"
    TRANSPORT_SSE = "sse"

    def __init__(self):
        self.config_path = Path(settings.MCP_CONFIG_PATH)
        self.sessions: dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        self._oauth_storages: dict[str, TokenStorage] = {}  # Per-server OAuth storage

    async def load_servers(self):
        """
        Reads the MCP config file and initializes connections to the servers.
        Supports multiple transport types and OAuth authentication.
        """
        if not self.config_path.exists():
            logger.warning("MCP Config file not found at %s", self.config_path)
            return

        with open(self.config_path) as f:
            config = json.load(f)

        mcp_servers = config.get("mcpServers", {})

        for server_name, server_config in mcp_servers.items():
            logger.info("Loading MCP server: %s", server_name)
            try:
                if "command" in server_config:
                    # Stdio transport for local subprocess servers
                    await self._connect_stdio_server(server_name, server_config)
                elif "url" in server_config:
                    # URL-based transport (streamable-http or sse)
                    await self._connect_url_server(server_name, server_config)
                else:
                    logger.warning(
                        "Skipping %s: Unknown server configuration (missing 'url' or 'command')", server_name
                    )
            except Exception as e:
                logger.error("Failed to connect to %s: %s", server_name, e)

    async def _connect_url_server(self, name: str, config: dict[str, Any]):
        """
        Routes URL-based server connections to the appropriate transport handler.
        Defaults to streamable-http (modern), with automatic fallback to SSE if
        no explicit transport is specified and streamable-http fails.
        """
        explicit_transport = config.get("transport")

        if explicit_transport:
            # Explicit transport specified - no fallback
            await self._connect_by_transport(name, config, explicit_transport)
        else:
            # No explicit transport - try streamable-http first, fallback to SSE
            await self._connect_url_server_with_fallback(name, config)

    async def _connect_by_transport(self, name: str, config: dict[str, Any], transport: str):
        """Connect using a specific transport type (no fallback)."""
        if transport == self.TRANSPORT_STREAMABLE_HTTP:
            await self._connect_streamable_http_server(name, config)
        elif transport == self.TRANSPORT_SSE:
            await self._connect_sse_server(name, config)
        else:
            logger.warning("Skipping %s: Unknown transport type '%s'", name, transport)

    async def _connect_url_server_with_fallback(self, name: str, config: dict[str, Any]):
        """
        Attempt connection with streamable-http first, fallback to SSE on failure.
        This provides resilience for servers that may use either transport.
        """
        url = config.get("url", "")

        # Try streamable-http first (modern transport)
        try:
            await self._connect_streamable_http_server(name, config)
            return  # Success!
        except Exception as e:
            logger.warning("Streamable HTTP connection failed for %s: %s", name, e)
            logger.info("Attempting SSE fallback for %s...", name)

        # Fallback to SSE (legacy transport)
        try:
            await self._connect_sse_server(name, config)
        except Exception as e:
            logger.error("SSE fallback also failed for %s: %s", name, e)
            raise ConnectionError(f"Failed to connect to {name} at {url} with both transports") from e

    async def _connect_stdio_server(self, name: str, config: dict[str, Any]):
        """Connect to a local subprocess-based MCP server via Stdio."""
        command = config.get("command")
        args = config.get("args", [])
        env = config.get("env")

        if shutil.which(command) is None:
            logger.warning("Command '%s' not found in PATH", command)
        else:
            # Resolve full path (helps on Windows with .cmd/.exe)
            command = shutil.which(command)

        server_params = StdioServerParameters(command=command, args=args, env=env)

        read, write = await self.exit_stack.enter_async_context(stdio_client(server_params))

        session = await self.exit_stack.enter_async_context(ClientSession(read, write))

        await session.initialize()
        self.sessions[name] = session
        logger.info("Connected to MCP server (Stdio): %s", name)

    async def _connect_sse_server(self, name: str, config: dict[str, Any]):
        """Connect to an MCP server using legacy SSE transport."""
        url = config.get("url")
        headers = config.get("headers", {})

        # sse_client yields (read, write) streams
        read, write = await self.exit_stack.enter_async_context(sse_client(url=url, headers=headers))

        session = await self.exit_stack.enter_async_context(ClientSession(read, write))

        await session.initialize()
        self.sessions[name] = session
        logger.info("Connected to MCP server (SSE): %s", name)

    async def _connect_streamable_http_server(self, name: str, config: dict[str, Any]):
        """
        Connect to an MCP server using the modern Streamable HTTP transport.
        Supports optional OAuth authentication.
        """
        url = config.get("url")
        headers = config.get("headers", {})
        oauth_config = config.get("oauth")
        timeout = config.get("timeout", 30.0)  # Default 30 second timeout

        auth = None
        if oauth_config and OAUTH_AVAILABLE:
            auth = self._build_oauth_provider(name, url, oauth_config)
        elif oauth_config and not OAUTH_AVAILABLE:
            logger.warning("OAuth configured for %s but OAuth dependencies not available", name)

        # streamablehttp_client yields (read, write, get_session_id)
        read, write, _ = await self.exit_stack.enter_async_context(
            streamablehttp_client(url=url, headers=headers, auth=auth, timeout=timeout)
        )

        session = await self.exit_stack.enter_async_context(ClientSession(read, write))

        await session.initialize()
        self.sessions[name] = session
        logger.info("Connected to MCP server (Streamable HTTP): %s", name)

    def _build_oauth_provider(self, server_name: str, server_url: str, oauth_config: dict) -> "OAuthClientProvider":
        """
        Build an OAuthClientProvider for authenticated MCP connections.

        OAuth config format:
        {
            "client_name": "Agent Chassis",
            "redirect_uri": "http://localhost:3000/callback",
            "scopes": ["user"],
            "grant_types": ["authorization_code", "refresh_token"]
        }
        """
        if not OAUTH_AVAILABLE:
            raise ImportError("OAuth dependencies not available. Install mcp[auth] for OAuth support.")

        # Create or reuse token storage for this server
        if server_name not in self._oauth_storages:
            # Try to use file-based storage if available, otherwise in-memory
            try:
                from app.services.oauth_storage import FileTokenStorage

                self._oauth_storages[server_name] = FileTokenStorage(server_name)
            except ImportError:
                self._oauth_storages[server_name] = InMemoryTokenStorage()

        storage = self._oauth_storages[server_name]

        # Build OAuth metadata from config
        redirect_uri = oauth_config.get("redirect_uri", settings.OAUTH_REDIRECT_URI)
        client_metadata = OAuthClientMetadata(
            client_name=oauth_config.get("client_name", "Agent Chassis"),
            redirect_uris=[AnyUrl(redirect_uri)],
            grant_types=oauth_config.get("grant_types", ["authorization_code", "refresh_token"]),
            response_types=["code"],
            scope=" ".join(oauth_config.get("scopes", ["user"])),
        )

        # Build the OAuth provider with redirect handlers
        # In a real application, these would trigger a browser flow
        oauth_provider = OAuthClientProvider(
            server_url=server_url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=self._oauth_redirect_handler,
            callback_handler=self._oauth_callback_handler,
        )

        return oauth_provider

    async def _oauth_redirect_handler(self, auth_url: str) -> None:
        """
        Handle OAuth redirect - in production, this would open a browser.
        For now, we log the URL for manual intervention.
        """
        logger.warning("OAuth Authorization Required!")
        logger.info("Visit this URL to authorize: %s", auth_url)

    async def _oauth_callback_handler(self) -> tuple[str, str | None]:
        """
        Handle OAuth callback - in production, this would capture the redirect.
        For now, we prompt for manual input.
        """
        logger.info("After authorizing, paste the callback URL here:")
        # In a CLI context, we'd read from stdin
        # In a web context, we'd capture the redirect
        # For now, raise to indicate this needs implementation
        raise NotImplementedError(
            "OAuth callback handling requires interactive input or a callback server. "
            "For automated flows, pre-configure tokens in the storage."
        )

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
                logger.error("Error listing tools from %s: %s", name, e)
        return all_tools

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> Any:
        session = self.sessions.get(server_name)
        if not session:
            raise ValueError(f"Server {server_name} not found")

        # Bypass strict SDK validation by using raw request
        # result = await session.call_tool(tool_name, arguments=arguments)

        req = CallToolRequest(method="tools/call", params=CallToolRequestParams(name=tool_name, arguments=arguments))

        raw_result = await session.send_request(req, PermissiveResult)

        # The raw_result is now a PermissiveResult object.
        if hasattr(raw_result, "content"):
            return raw_result.content

        return raw_result

    async def cleanup(self):
        """
        Closes all connections.
        """
        await self.exit_stack.aclose()
        self.sessions.clear()


mcp_manager = MCPManager()
