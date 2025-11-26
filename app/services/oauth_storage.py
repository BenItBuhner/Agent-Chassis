"""
OAuth Token Storage for MCP Server Authentication.

This module provides persistent token storage for OAuth 2.1 authentication
with MCP servers. Tokens are stored on disk to survive application restarts.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.config import settings

# Type-only imports to avoid circular dependencies
if TYPE_CHECKING:
    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

# Runtime imports with graceful fallback
try:
    from mcp.client.auth import TokenStorage
    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

    OAUTH_AVAILABLE = True
except ImportError:
    OAUTH_AVAILABLE = False
    # Create a dummy base class for when OAuth isn't available
    TokenStorage = object  # type: ignore[misc, assignment]


class FileTokenStorage(TokenStorage):
    """
    Persistent file-based token storage for OAuth authentication.

    Stores tokens in JSON files within a dedicated directory, one file per server.
    This allows OAuth tokens to persist across application restarts.

    Directory structure:
        .mcp_tokens/
            server_name_tokens.json   # Contains access/refresh tokens
            server_name_client.json   # Contains client registration info
    """

    def __init__(self, server_name: str):
        """
        Initialize token storage for a specific MCP server.

        Args:
            server_name: Unique identifier for the MCP server
        """
        if not OAUTH_AVAILABLE:
            raise ImportError("OAuth dependencies not available. Install mcp with OAuth support.")

        self.server_name = server_name
        self.storage_dir = Path(settings.OAUTH_TOKENS_PATH)
        self._ensure_storage_dir()

    def _ensure_storage_dir(self) -> None:
        """Create the storage directory if it doesn't exist."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # Add .gitignore to prevent token leakage
        gitignore_path = self.storage_dir / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text("*\n!.gitignore\n")

    @property
    def _tokens_path(self) -> Path:
        """Path to the tokens file for this server."""
        return self.storage_dir / f"{self.server_name}_tokens.json"

    @property
    def _client_info_path(self) -> Path:
        """Path to the client info file for this server."""
        return self.storage_dir / f"{self.server_name}_client.json"

    async def get_tokens(self) -> "OAuthToken | None":
        """
        Retrieve stored OAuth tokens.

        Returns:
            OAuthToken if tokens exist and are valid, None otherwise
        """
        if not self._tokens_path.exists():
            return None

        try:
            data = json.loads(self._tokens_path.read_text())
            return OAuthToken(**data)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            print(f"Warning: Failed to load tokens for {self.server_name}: {e}")
            return None

    async def set_tokens(self, tokens: "OAuthToken") -> None:
        """
        Store OAuth tokens to disk.

        Args:
            tokens: The OAuth tokens to store
        """
        self._tokens_path.write_text(tokens.model_dump_json(indent=2))

    async def get_client_info(self) -> "OAuthClientInformationFull | None":
        """
        Retrieve stored OAuth client registration information.

        Returns:
            OAuthClientInformationFull if stored, None otherwise
        """
        if not self._client_info_path.exists():
            return None

        try:
            data = json.loads(self._client_info_path.read_text())
            return OAuthClientInformationFull(**data)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            print(f"Warning: Failed to load client info for {self.server_name}: {e}")
            return None

    async def set_client_info(self, client_info: "OAuthClientInformationFull") -> None:
        """
        Store OAuth client registration information to disk.

        Args:
            client_info: The client registration information to store
        """
        self._client_info_path.write_text(client_info.model_dump_json(indent=2))

    async def clear(self) -> None:
        """
        Clear all stored tokens and client info for this server.
        Useful for forcing re-authentication.
        """
        if self._tokens_path.exists():
            self._tokens_path.unlink()
        if self._client_info_path.exists():
            self._client_info_path.unlink()


class InMemoryTokenStorage(TokenStorage):
    """
    Simple in-memory token storage for development/testing.

    Tokens are lost when the application restarts.
    Use FileTokenStorage for production deployments.
    """

    def __init__(self):
        if not OAUTH_AVAILABLE:
            raise ImportError("OAuth dependencies not available. Install mcp with OAuth support.")

        self._tokens: OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> "OAuthToken | None":
        return self._tokens

    async def set_tokens(self, tokens: "OAuthToken") -> None:
        self._tokens = tokens

    async def get_client_info(self) -> "OAuthClientInformationFull | None":
        return self._client_info

    async def set_client_info(self, client_info: "OAuthClientInformationFull") -> None:
        self._client_info = client_info
