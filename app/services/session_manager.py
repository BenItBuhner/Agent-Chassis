"""
Unified session manager for conversation persistence.

Orchestrates Redis cache and PostgreSQL database for optimal performance:
- Redis: Fast, TTL-based cache for active sessions
- PostgreSQL: Durable storage for persistence
- Fallback: Graceful handling when storage is unavailable

Includes ownership-based access control (OSP-12):
- Creator-only access by default (when auth enabled)
- Optional public access, whitelist, and blacklist
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.security import UserContext
from app.services.access_control import access_control
from app.services.database import database
from app.services.redis_cache import redis_cache

logger = logging.getLogger("agent_chassis.session")


class SessionManager:
    """
    Manages conversation sessions with a dual-layer storage strategy.

    Storage Flow:
    1. Check Redis cache first (fast path)
    2. On cache miss, check PostgreSQL (durable storage)
    3. On DB hit, repopulate Redis cache
    4. On complete miss, create new session

    Access Control Flow (when auth enabled):
    1. Load session data
    2. Check access via AccessControl service
    3. Deny with 403 if access not allowed

    Supports two operational modes:
    - Client-side mode: Messages passed directly (no persistence)
    - Server-side mode: Session ID-based persistence
    """

    def __init__(self):
        self.redis = redis_cache
        self.db = database

    @property
    def persistence_enabled(self) -> bool:
        """Check if any persistence layer is available."""
        return settings.ENABLE_PERSISTENCE and (self.redis.is_available or self.db.is_available)

    async def get_or_create_session(
        self,
        session_id: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        user_ctx: UserContext | None = None,
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """
        Get existing session or create new one with access control.

        Supports two modes:
        1. Client-side: session_id=None, messages=[...] -> No persistence
        2. Server-side: session_id="abc123" or session_id=None for new session

        Args:
            session_id: Existing session ID to load (optional).
            messages: Client-provided messages (bypasses persistence).
            user_ctx: Current user context for access control.

        Returns:
            Tuple of (session_id, messages).
            - session_id is None in client-side mode
            - messages is the conversation history

        Raises:
            HTTPException: 403 if access denied to existing session.
        """
        # MODE 1: Client-side messages (backward compatible, no persistence)
        if messages is not None and session_id is None:
            return (None, messages)

        # Check if persistence is enabled
        if not self.persistence_enabled:
            # Persistence disabled - treat as client-side mode
            if messages is not None:
                return (None, messages)
            # No messages and no persistence - create ephemeral session
            return (str(uuid.uuid4()), [])

        # MODE 2: Server-side persistence with existing session
        if session_id:
            session_data = await self._load_session(session_id)
            if session_data:
                # ACCESS CONTROL CHECK
                if user_ctx:
                    access_control.check_access_and_raise(user_ctx, session_data, session_id)
                return (session_id, session_data["messages"])
            # Session not found - raise 404 instead of silently creating empty
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found",
            )

        # MODE 3: Create new persistent session
        new_id = str(uuid.uuid4())
        return (new_id, [])

    async def _load_session(self, session_id: str) -> dict[str, Any] | None:
        """
        Load session data from storage (Redis-first, DB-fallback).

        Args:
            session_id: Session identifier.

        Returns:
            Session data dict or None if not found.
        """
        # Try Redis first (fast path)
        if self.redis.is_available:
            cached = await self.redis.get_session(session_id)
            if cached:
                # Refresh TTL on access
                await self.redis.refresh_ttl(session_id)
                return cached

        # Fallback to PostgreSQL
        if self.db.is_available:
            conversation = await self.db.get_conversation(session_id)
            if conversation:
                session_data = conversation.to_dict()
                # Repopulate Redis cache
                if self.redis.is_available:
                    await self.redis.set_session(session_id, session_data)
                return session_data

        return None

    async def save_session(
        self,
        session_id: str | None,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
        user_ctx: UserContext | None = None,
        is_new_session: bool = False,
    ) -> bool:
        """
        Save session to storage layers with ownership tracking.

        Args:
            session_id: Session identifier (None for client-side mode).
            messages: Complete message history.
            system_prompt: Optional system prompt.
            model: Model identifier.
            metadata: User-defined metadata.
            user_ctx: Current user context (for setting owner_id on new sessions).
            is_new_session: If True, sets owner_id from user_ctx.

        Returns:
            True if saved successfully, False otherwise.
        """
        # Client-side mode - no persistence
        if session_id is None:
            return True

        # Persistence disabled
        if not self.persistence_enabled:
            return True

        # Truncate messages if exceeding max
        if len(messages) > settings.SESSION_MAX_MESSAGES:
            # Keep system messages and most recent messages
            system_msgs = [m for m in messages if m.get("role") == "system"]
            other_msgs = [m for m in messages if m.get("role") != "system"]
            keep_count = settings.SESSION_MAX_MESSAGES - len(system_msgs)
            messages = system_msgs + other_msgs[-keep_count:]

        success = True

        if is_new_session:
            # NEW SESSION: Set owner_id and default access control
            owner_id = None
            if user_ctx and user_ctx.can_own_sessions:
                owner_id = user_ctx.user_id

            session_data = {
                "id": session_id,
                "messages": messages,
                "system_prompt": system_prompt,
                "model": model,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "message_count": len(messages),
                "metadata": metadata or {},
                # Access control fields for new sessions
                "owner_id": owner_id,
                "is_public": False,
                "access_whitelist": [],
                "access_blacklist": [],
            }

            # Save to Redis
            if self.redis.is_available:
                redis_success = await self.redis.set_session(session_id, session_data)
                if not redis_success:
                    logger.warning("Failed to cache session %s in Redis", session_id)
                    success = False

            # Create in PostgreSQL
            if self.db.is_available:
                db_success = await self.db.create_conversation(
                    session_id=session_id,
                    messages=messages,
                    system_prompt=system_prompt,
                    model=model,
                    metadata=metadata,
                    owner_id=owner_id,
                )
                if not db_success:
                    logger.warning("Failed to create session %s in database", session_id)
                    success = False
        else:
            # EXISTING SESSION: Preserve access control fields from existing data
            existing_data = await self._load_session(session_id)

            session_data = {
                "id": session_id,
                "messages": messages,
                "system_prompt": system_prompt,
                "model": model,
                "updated_at": datetime.now(UTC).isoformat(),
                "message_count": len(messages),
                "metadata": metadata or {},
                # Preserve access control fields from existing data
                "created_at": existing_data.get("created_at") if existing_data else datetime.now(UTC).isoformat(),
                "owner_id": existing_data.get("owner_id") if existing_data else None,
                "is_public": existing_data.get("is_public", False) if existing_data else False,
                "access_whitelist": existing_data.get("access_whitelist", []) if existing_data else [],
                "access_blacklist": existing_data.get("access_blacklist", []) if existing_data else [],
            }

            # Save to Redis (with preserved access control)
            if self.redis.is_available:
                redis_success = await self.redis.set_session(session_id, session_data)
                if not redis_success:
                    logger.warning("Failed to cache session %s in Redis", session_id)
                    success = False

            # Update in PostgreSQL (don't modify owner_id or access control)
            if self.db.is_available:
                db_success = await self.db.upsert_conversation(
                    session_id=session_id,
                    messages=messages,
                    system_prompt=system_prompt,
                    model=model,
                    metadata=metadata,
                )
                if not db_success:
                    logger.warning("Failed to persist session %s to database", session_id)
                    success = False

        return success

    async def delete_session(
        self,
        session_id: str,
        user_ctx: UserContext | None = None,
    ) -> bool:
        """
        Delete session from all storage layers with ownership check.

        Args:
            session_id: Session identifier.
            user_ctx: Current user context (for ownership verification).

        Returns:
            True if deleted from at least one layer, False otherwise.

        Raises:
            HTTPException: 403 if user is not the owner.
        """
        if not session_id:
            return False

        # Check ownership before deletion
        if user_ctx and user_ctx.auth_enabled:
            session_data = await self._load_session(session_id)
            if session_data:
                access_control.check_owner_and_raise(user_ctx, session_data, session_id)

        deleted = False

        if self.redis.is_available:
            if await self.redis.delete_session(session_id):
                deleted = True

        if self.db.is_available:
            if await self.db.delete_conversation(session_id):
                deleted = True

        return deleted

    async def append_message(
        self,
        session_id: str | None,
        message: dict[str, Any],
        current_messages: list[dict[str, Any]] | None = None,
        user_ctx: UserContext | None = None,
    ) -> list[dict[str, Any]]:
        """
        Append a message to session and save.

        Helper method for common append-and-save pattern.

        Args:
            session_id: Session identifier.
            message: Message to append.
            current_messages: Existing messages (if already loaded).
            user_ctx: Current user context for access control.

        Returns:
            Updated messages list.
        """
        if current_messages is None:
            _, current_messages = await self.get_or_create_session(session_id, user_ctx=user_ctx)

        current_messages.append(message)

        # Auto-save if using server-side persistence
        if session_id and self.persistence_enabled:
            await self.save_session(session_id, current_messages, user_ctx=user_ctx)

        return current_messages

    async def session_exists(self, session_id: str) -> bool:
        """
        Check if a session exists in any storage layer.

        Args:
            session_id: Session identifier.

        Returns:
            True if session exists, False otherwise.
        """
        if not session_id:
            return False

        # Check Redis first
        if self.redis.is_available:
            if await self.redis.exists(session_id):
                return True

        # Check database
        if self.db.is_available:
            conversation = await self.db.get_conversation(session_id)
            return conversation is not None

        return False

    async def get_session_info(
        self,
        session_id: str,
        user_ctx: UserContext | None = None,
    ) -> dict[str, Any] | None:
        """
        Get session information including access control settings.

        Args:
            session_id: Session identifier.
            user_ctx: Current user context for access control.

        Returns:
            Session info dict if found and accessible, None otherwise.

        Raises:
            HTTPException: 403 if access denied.
        """
        if not session_id:
            return None

        session_data = await self._load_session(session_id)
        if not session_data:
            return None

        # Check access
        if user_ctx:
            access_control.check_access_and_raise(user_ctx, session_data, session_id)

        # Return info (include access settings only for owner)
        info = {
            "session_id": session_data.get("id"),
            "message_count": session_data.get("message_count", 0),
            "created_at": session_data.get("created_at"),
            "updated_at": session_data.get("updated_at"),
            "model": session_data.get("model"),
            "metadata": session_data.get("metadata"),
        }

        # Include access settings for owner
        if user_ctx and access_control.is_owner(user_ctx, session_data):
            info["access"] = {
                "owner_id": session_data.get("owner_id"),
                "is_public": session_data.get("is_public", False),
                "whitelist": session_data.get("access_whitelist", []),
                "blacklist": session_data.get("access_blacklist", []),
            }

        return info

    async def update_access_settings(
        self,
        session_id: str,
        user_ctx: UserContext,
        is_public: bool | None = None,
        whitelist: list[str] | None = None,
        blacklist: list[str] | None = None,
        add_to_whitelist: list[str] | None = None,
        remove_from_whitelist: list[str] | None = None,
        add_to_blacklist: list[str] | None = None,
        remove_from_blacklist: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Update access control settings for a session.

        Only the owner can modify access settings.

        Args:
            session_id: Session identifier.
            user_ctx: Current user context (must be owner).
            is_public: Set public access flag.
            whitelist: Replace entire whitelist.
            blacklist: Replace entire blacklist.
            add_to_whitelist: Add users to whitelist.
            remove_from_whitelist: Remove users from whitelist.
            add_to_blacklist: Add users to blacklist.
            remove_from_blacklist: Remove users from blacklist.

        Returns:
            Updated access settings dict.

        Raises:
            HTTPException: 403 if not owner, 404 if session not found.
        """
        if not self.persistence_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Persistence is not enabled",
            )

        # Load session data
        session_data = await self._load_session(session_id)
        if not session_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found",
            )

        # Check ownership
        access_control.check_owner_and_raise(user_ctx, session_data, session_id)

        # Get current values
        current_whitelist = set(session_data.get("access_whitelist", []))
        current_blacklist = set(session_data.get("access_blacklist", []))
        current_is_public = session_data.get("is_public", False)

        # Apply updates
        new_is_public = is_public if is_public is not None else current_is_public

        # Handle whitelist
        if whitelist is not None:
            new_whitelist = set(whitelist)
        else:
            new_whitelist = current_whitelist.copy()
            if add_to_whitelist:
                new_whitelist.update(add_to_whitelist)
            if remove_from_whitelist:
                new_whitelist -= set(remove_from_whitelist)

        # Handle blacklist
        if blacklist is not None:
            new_blacklist = set(blacklist)
        else:
            new_blacklist = current_blacklist.copy()
            if add_to_blacklist:
                new_blacklist.update(add_to_blacklist)
            if remove_from_blacklist:
                new_blacklist -= set(remove_from_blacklist)

        # Validate no overlap
        access_control.validate_access_update(list(new_whitelist), list(new_blacklist))

        # Update storage
        success = await self.db.update_access_settings(
            session_id=session_id,
            is_public=new_is_public,
            whitelist=list(new_whitelist),
            blacklist=list(new_blacklist),
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update access settings",
            )

        # Invalidate Redis cache to ensure consistency
        if self.redis.is_available:
            await self.redis.delete_session(session_id)

        return {
            "session_id": session_id,
            "is_public": new_is_public,
            "whitelist": list(new_whitelist),
            "blacklist": list(new_blacklist),
        }


# Global instance
session_manager = SessionManager()
