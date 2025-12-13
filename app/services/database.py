"""
PostgreSQL database service for conversation persistence.

Provides durable storage for conversation sessions, serving as the
fallback/persistence layer when Redis cache misses occur.
"""

import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings

logger = logging.getLogger("agent_chassis.database")

# Conditional imports - database is optional
try:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.models.conversation import Base, Conversation

    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False


class Database:
    """
    Async PostgreSQL database service for conversation persistence.

    Features:
    - Async connection pooling
    - Automatic table creation
    - CRUD operations for conversations
    - Graceful degradation if database unavailable
    """

    def __init__(self):
        self.engine = None
        self.session_factory = None
        self._connected = False

    @property
    def is_available(self) -> bool:
        """Check if database is configured and connected."""
        return self._connected and self.engine is not None

    async def connect(self) -> bool:
        """
        Establish connection to PostgreSQL and create tables if needed.

        Returns:
            True if connection successful, False otherwise.
        """
        if not SQLALCHEMY_AVAILABLE:
            logger.warning("SQLAlchemy not installed - Database persistence disabled")
            return False

        if not settings.DATABASE_URL:
            logger.warning("DATABASE_URL not configured - Database persistence disabled")
            return False

        try:
            self.engine = create_async_engine(
                settings.DATABASE_URL,
                echo=False,  # Set to True for SQL debugging
                pool_size=5,
                max_overflow=10,
            )

            self.session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            # Create tables if they don't exist
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            self._connected = True
            # Use sanitized URL for logging (masks password)
            logger.info("Connected to database: %s", settings.sanitize_url(settings.DATABASE_URL))
            return True
        except Exception as e:
            logger.error("Failed to connect to database: %s", e)
            self.engine = None
            self.session_factory = None
            self._connected = False
            return False

    async def close(self) -> None:
        """Close database connection pool."""
        if self.engine:
            await self.engine.dispose()
            self._connected = False
            logger.info("Database connection closed")

    async def get_session(self) -> AsyncGenerator["AsyncSession", None]:
        """
        Get an async database session.

        Yields:
            AsyncSession for database operations.
        """
        if not self.is_available or not self.session_factory:
            raise RuntimeError("Database not connected")

        async with self.session_factory() as session:
            yield session

    async def get_conversation(self, session_id: str) -> "Conversation | None":
        """
        Retrieve a conversation by ID.

        Args:
            session_id: Unique conversation identifier.

        Returns:
            Conversation object if found, None otherwise.
        """
        if not self.is_available:
            return None

        try:
            async with self.session_factory() as session:
                result = await session.execute(select(Conversation).where(Conversation.id == session_id))
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error("Database get error for session %s: %s", session_id, e)
            return None

    async def create_conversation(
        self,
        session_id: str,
        messages: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
        owner_id: str | None = None,
    ) -> "Conversation | None":
        """
        Create a new conversation with ownership.

        Args:
            session_id: Unique conversation identifier.
            messages: Initial messages list.
            system_prompt: Optional system prompt.
            model: Model identifier.
            metadata: User-defined metadata.
            owner_id: Creator's user ID for access control.

        Returns:
            Created Conversation object, or None on failure.
        """
        if not self.is_available:
            return None

        try:
            conversation = Conversation(
                id=session_id,
                messages=messages or [],
                system_prompt=system_prompt,
                model=model,
                message_count=len(messages) if messages else 0,
                metadata_=metadata or {},
                # Access control fields
                owner_id=owner_id,
                is_public=False,
                access_whitelist=[],
                access_blacklist=[],
            )

            async with self.session_factory() as session:
                session.add(conversation)
                await session.commit()
                await session.refresh(conversation)
                return conversation
        except Exception as e:
            logger.error("Database create error for session %s: %s", session_id, e)
            return None

    async def update_conversation(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> bool:
        """
        Update an existing conversation.

        Args:
            session_id: Unique conversation identifier.
            messages: Updated messages list.
            system_prompt: Optional system prompt update.
            model: Optional model update.

        Returns:
            True if update successful, False otherwise.
        """
        if not self.is_available:
            return False

        try:
            async with self.session_factory() as session:
                result = await session.execute(select(Conversation).where(Conversation.id == session_id))
                conversation = result.scalar_one_or_none()

                if not conversation:
                    return False

                conversation.messages = messages
                conversation.message_count = len(messages)
                conversation.updated_at = datetime.now(UTC)

                if system_prompt is not None:
                    conversation.system_prompt = system_prompt
                if model is not None:
                    conversation.model = model

                await session.commit()
                return True
        except Exception as e:
            logger.error("Database update error for session %s: %s", session_id, e)
            return False

    async def upsert_conversation(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Create or update a conversation (upsert).

        Args:
            session_id: Unique conversation identifier.
            messages: Messages list.
            system_prompt: Optional system prompt.
            model: Model identifier.
            metadata: User-defined metadata.

        Returns:
            True if successful, False otherwise.
        """
        if not self.is_available:
            return False

        try:
            async with self.session_factory() as session:
                result = await session.execute(select(Conversation).where(Conversation.id == session_id))
                conversation = result.scalar_one_or_none()

                if conversation:
                    # Update existing
                    conversation.messages = messages
                    conversation.message_count = len(messages)
                    conversation.updated_at = datetime.now(UTC)
                    if system_prompt is not None:
                        conversation.system_prompt = system_prompt
                    if model is not None:
                        conversation.model = model
                    if metadata is not None:
                        conversation.metadata_ = metadata
                else:
                    # Create new
                    conversation = Conversation(
                        id=session_id,
                        messages=messages,
                        system_prompt=system_prompt,
                        model=model,
                        message_count=len(messages),
                        metadata_=metadata or {},
                    )
                    session.add(conversation)

                await session.commit()
                return True
        except Exception as e:
            logger.error("Database upsert error for session %s: %s", session_id, e)
            return False

    async def delete_conversation(self, session_id: str) -> bool:
        """
        Delete a conversation.

        Args:
            session_id: Unique conversation identifier.

        Returns:
            True if deleted, False otherwise.
        """
        if not self.is_available:
            return False

        try:
            async with self.session_factory() as session:
                result = await session.execute(select(Conversation).where(Conversation.id == session_id))
                conversation = result.scalar_one_or_none()

                if conversation:
                    await session.delete(conversation)
                    await session.commit()
                    return True
                return False
        except Exception as e:
            logger.error("Database delete error for session %s: %s", session_id, e)
            return False

    async def update_access_settings(
        self,
        session_id: str,
        is_public: bool | None = None,
        whitelist: list[str] | None = None,
        blacklist: list[str] | None = None,
    ) -> bool:
        """
        Update access control settings for a conversation.

        Args:
            session_id: Unique conversation identifier.
            is_public: Whether the conversation is publicly accessible.
            whitelist: List of user IDs with explicit access.
            blacklist: List of user IDs denied access.

        Returns:
            True if update successful, False otherwise.
        """
        if not self.is_available:
            return False

        try:
            async with self.session_factory() as session:
                result = await session.execute(select(Conversation).where(Conversation.id == session_id))
                conversation = result.scalar_one_or_none()

                if not conversation:
                    return False

                if is_public is not None:
                    conversation.is_public = is_public
                if whitelist is not None:
                    conversation.access_whitelist = whitelist
                if blacklist is not None:
                    conversation.access_blacklist = blacklist

                conversation.updated_at = datetime.now(UTC)
                await session.commit()
                return True
        except Exception as e:
            logger.error("Database access settings update error for session %s: %s", session_id, e)
            return False


# Global instance
database = Database()
