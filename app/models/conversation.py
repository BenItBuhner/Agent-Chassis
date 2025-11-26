"""
SQLAlchemy models for conversation persistence.

This module defines the database schema for storing conversation sessions,
enabling server-side persistence of chat history with ownership and access control.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all SQLAlchemy models with async support."""

    pass


class Conversation(Base):
    """
    Represents a conversation session with full message history and access control.

    Attributes:
        id: Unique session identifier (UUID)
        messages: JSON array of chat messages
        system_prompt: Optional system prompt for the conversation
        model: Model identifier used for this conversation
        created_at: Timestamp when session was created
        updated_at: Timestamp of last update
        message_count: Number of messages in the conversation
        metadata: User-defined metadata (tags, user_id, etc.)

        # Access Control Fields (OSP-12)
        owner_id: Creator's user ID (None for legacy/unauthenticated sessions)
        is_public: If True, anyone can access (default: False, creator-only)
        access_whitelist: User IDs explicitly allowed to access
        access_blacklist: User IDs explicitly denied access (overrides whitelist/public)
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    messages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    system_prompt: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    message_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",  # Column name in DB
        JSONB,
        default=dict,
        nullable=False,
    )

    # Access Control Fields (OSP-12)
    owner_id: Mapped[str | None] = mapped_column(
        String(128),  # Supports hashed API keys or external user IDs
        nullable=True,
        index=True,  # Index for owner lookups
    )
    is_public: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    access_whitelist: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    access_blacklist: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert conversation to dictionary for Redis caching."""
        return {
            "id": self.id,
            "messages": self.messages,
            "system_prompt": self.system_prompt,
            "model": self.model,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "message_count": self.message_count,
            "metadata": self.metadata_,
            # Access control fields
            "owner_id": self.owner_id,
            "is_public": self.is_public,
            "access_whitelist": self.access_whitelist,
            "access_blacklist": self.access_blacklist,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Conversation":
        """Create conversation from dictionary (e.g., from Redis cache)."""
        return cls(
            id=data.get("id"),
            messages=data.get("messages", []),
            system_prompt=data.get("system_prompt"),
            model=data.get("model"),
            message_count=data.get("message_count", 0),
            metadata_=data.get("metadata", {}),
            # Access control fields
            owner_id=data.get("owner_id"),
            is_public=data.get("is_public", False),
            access_whitelist=data.get("access_whitelist", []),
            access_blacklist=data.get("access_blacklist", []),
        )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, owner={self.owner_id}, messages={self.message_count})>"
