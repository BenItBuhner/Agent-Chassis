"""
Pydantic schemas for agent API requests and responses.

Supports two operational modes:
1. Client-side: Full message history passed in request (backward compatible)
2. Server-side: Session-based persistence with session_id + single message

Includes access control schemas for ownership-based session management (OSP-12).
Includes input size validation to prevent memory exhaustion attacks.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings


class ChatMessage(BaseModel):
    """
    Represents a single message in a conversation.

    Content is limited to MAX_MESSAGE_LENGTH (default 100KB) to prevent
    memory exhaustion attacks.
    """

    role: str = Field(..., max_length=50)
    content: str | None = Field(None, max_length=settings.MAX_MESSAGE_LENGTH)
    name: str | None = Field(None, max_length=100)
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = Field(None, max_length=100)

    @field_validator("content")
    @classmethod
    def validate_content_length(cls, v: str | None) -> str | None:
        """Validate content doesn't exceed maximum length."""
        if v is not None and len(v) > settings.MAX_MESSAGE_LENGTH:
            raise ValueError(f"Message content exceeds maximum length of {settings.MAX_MESSAGE_LENGTH} characters")
        return v


class CompletionRequest(BaseModel):
    """
    Request for agent completion.

    Supports two modes:
    1. Client-side mode (backward compatible):
       - Provide `messages` array with full conversation history
       - No server-side persistence

    2. Server-side mode:
       - Provide `session_id` to continue existing conversation
       - OR provide just `message` to start new session
       - Server persists conversation in Redis/PostgreSQL

    Input limits:
    - Message content: MAX_MESSAGE_LENGTH (default 100KB)
    - Metadata: MAX_METADATA_SIZE (default 10KB)
    - Messages array: MAX_MESSAGES_PER_REQUEST (default 100)
    """

    # Server-side persistence mode
    session_id: str | None = Field(None, max_length=100)  # Existing session to continue
    message: str | None = Field(None, max_length=settings.MAX_MESSAGE_LENGTH)  # Single new message

    # Client-side mode (backward compatible)
    messages: list[ChatMessage] | None = None  # Full history from client

    # Common fields
    system_prompt: str | None = Field(None, max_length=settings.MAX_MESSAGE_LENGTH)
    model: str | None = Field("kimi-k2-thinking", max_length=100)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(16000, ge=1, le=128000)
    allowed_tools: list[str] | None = None  # If None, all tools. If empty list, no tools.
    stream: bool = False

    # Session metadata (only used in server-side mode)
    metadata: dict[str, Any] | None = None  # User-defined metadata for the session

    @field_validator("messages")
    @classmethod
    def validate_messages_count(cls, v: list[ChatMessage] | None) -> list[ChatMessage] | None:
        """Validate message count doesn't exceed limit."""
        if v is not None and len(v) > settings.MAX_MESSAGES_PER_REQUEST:
            raise ValueError(f"Too many messages ({len(v)}). Maximum is {settings.MAX_MESSAGES_PER_REQUEST}")
        return v

    @field_validator("metadata")
    @classmethod
    def validate_metadata_size(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate metadata size doesn't exceed limit."""
        if v is not None:
            try:
                serialized = json.dumps(v)
                if len(serialized) > settings.MAX_METADATA_SIZE:
                    raise ValueError(
                        f"Metadata too large ({len(serialized)} bytes). Maximum is {settings.MAX_METADATA_SIZE} bytes"
                    )
            except (TypeError, ValueError) as e:
                raise ValueError(f"Invalid metadata: {e}") from e
        return v

    @model_validator(mode="after")
    def validate_mode(self) -> CompletionRequest:
        """
        Validate that request uses either client-side or server-side mode.

        Rules:
        - Cannot mix messages[] with session_id/message
        - Must provide EITHER messages[] OR (session_id and/or message)
        """
        has_messages = self.messages is not None and len(self.messages) > 0
        has_session_mode = self.session_id is not None or self.message is not None

        # Allow messages=None with session_id/message (server-side mode)
        # Allow messages=[...] without session_id/message (client-side mode)
        # Disallow mixing both modes

        if has_messages and has_session_mode:
            raise ValueError(
                "Cannot mix client-side mode (messages[]) with server-side mode (session_id/message). "
                "Use EITHER messages[] OR session_id/message."
            )

        if not has_messages and not has_session_mode:
            raise ValueError("Must provide either messages[] (client-side) or session_id/message (server-side).")

        return self

    @property
    def is_server_side_mode(self) -> bool:
        """Check if request is using server-side persistence mode."""
        return self.session_id is not None or self.message is not None


class CompletionResponse(BaseModel):
    """
    Response from agent completion.

    Includes session_id when using server-side persistence mode,
    allowing clients to continue the conversation.
    """

    role: str
    content: str | None
    tool_calls: list[dict[str, Any]] | None = None

    # Server-side mode: session ID for continuation
    session_id: str | None = None


class SessionInfo(BaseModel):
    """Information about a session (for session management endpoints)."""

    session_id: str
    message_count: int
    created_at: str | None = None
    updated_at: str | None = None
    model: str | None = None
    metadata: dict[str, Any] | None = None
    # Access control info (only included for session owner)
    access: AccessSettings | None = None


class AccessSettings(BaseModel):
    """
    Access control settings for a conversation session.

    Only visible to the session owner.
    """

    owner_id: str | None = None
    is_public: bool = False
    whitelist: list[str] = []
    blacklist: list[str] = []


class AccessUpdateRequest(BaseModel):
    """
    Request to update access control settings.

    All fields are optional - only provided fields are updated.
    Supports both full replacement and incremental updates.
    """

    # Full replacement options
    is_public: bool | None = None
    whitelist: list[str] | None = None  # Replace entire whitelist
    blacklist: list[str] | None = None  # Replace entire blacklist

    # Incremental update options
    add_to_whitelist: list[str] | None = None
    remove_from_whitelist: list[str] | None = None
    add_to_blacklist: list[str] | None = None
    remove_from_blacklist: list[str] | None = None

    @model_validator(mode="after")
    def validate_no_mixing(self) -> AccessUpdateRequest:
        """Ensure user doesn't mix full replacement with incremental updates."""
        has_full_whitelist = self.whitelist is not None
        has_incremental_whitelist = self.add_to_whitelist is not None or self.remove_from_whitelist is not None

        has_full_blacklist = self.blacklist is not None
        has_incremental_blacklist = self.add_to_blacklist is not None or self.remove_from_blacklist is not None

        if has_full_whitelist and has_incremental_whitelist:
            raise ValueError("Cannot mix whitelist replacement with add_to_whitelist/remove_from_whitelist")

        if has_full_blacklist and has_incremental_blacklist:
            raise ValueError("Cannot mix blacklist replacement with add_to_blacklist/remove_from_blacklist")

        return self


class AccessUpdateResponse(BaseModel):
    """Response after updating access settings."""

    session_id: str
    is_public: bool
    whitelist: list[str]
    blacklist: list[str]
