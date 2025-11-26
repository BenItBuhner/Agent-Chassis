"""
Access control service for conversation sessions.

Implements ownership-based access control for conversations:
- Creator-only access by default (when auth enabled)
- Optional public access
- Whitelist: explicitly allow specific users
- Blacklist: explicitly deny specific users (highest priority)
"""

from typing import Any

from fastapi import HTTPException, status

from app.core.security import UserContext


class AccessControl:
    """
    Centralized access control logic for conversation sessions.

    Access Decision Priority (highest to lowest):
    1. Auth disabled → ALLOW (no ownership tracking)
    2. No owner_id on conversation → ALLOW (legacy/anonymous session)
    3. User in blacklist → DENY
    4. User is owner → ALLOW
    5. Conversation is_public → ALLOW
    6. User in whitelist → ALLOW
    7. Default → DENY
    """

    @staticmethod
    def can_access(
        user_ctx: UserContext,
        conversation_data: dict[str, Any],
    ) -> bool:
        """
        Check if user can access a conversation.

        Args:
            user_ctx: Current user's context (identity and auth state).
            conversation_data: Conversation dict (from DB or Redis cache).

        Returns:
            True if access is allowed, False otherwise.
        """
        # Rule 1: Auth disabled - allow all access
        if not user_ctx.auth_enabled:
            return True

        owner_id = conversation_data.get("owner_id")

        # Rule 2: No owner (legacy/anonymous session) - allow all
        if not owner_id:
            return True

        user_id = user_ctx.user_id
        blacklist = conversation_data.get("access_blacklist", [])
        whitelist = conversation_data.get("access_whitelist", [])
        is_public = conversation_data.get("is_public", False)

        # Rule 3: Blacklist has highest priority - deny
        if user_id and user_id in blacklist:
            return False

        # Rule 4: Owner always has access
        if user_id and user_id == owner_id:
            return True

        # Rule 5: Public conversations accessible to all (except blacklisted)
        if is_public:
            return True

        # Rule 6: Whitelist grants access
        if user_id and user_id in whitelist:
            return True

        # Rule 7: Default deny
        return False

    @staticmethod
    def is_owner(
        user_ctx: UserContext,
        conversation_data: dict[str, Any],
    ) -> bool:
        """
        Check if user is the owner of a conversation.

        Args:
            user_ctx: Current user's context.
            conversation_data: Conversation dict.

        Returns:
            True if user is the owner, False otherwise.
        """
        if not user_ctx.user_id:
            return False

        owner_id = conversation_data.get("owner_id")
        return owner_id is not None and user_ctx.user_id == owner_id

    @staticmethod
    def check_access_and_raise(
        user_ctx: UserContext,
        conversation_data: dict[str, Any],
        session_id: str,
    ) -> None:
        """
        Check access and raise HTTPException if denied.

        Args:
            user_ctx: Current user's context.
            conversation_data: Conversation dict.
            session_id: Session identifier (for error message).

        Raises:
            HTTPException: 403 if access denied, 404 if session not found.
        """
        if not AccessControl.can_access(user_ctx, conversation_data):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to session {session_id}",
            )

    @staticmethod
    def check_owner_and_raise(
        user_ctx: UserContext,
        conversation_data: dict[str, Any],
        session_id: str,
    ) -> None:
        """
        Check ownership and raise HTTPException if not owner.

        Required for modifying access settings.

        Args:
            user_ctx: Current user's context.
            conversation_data: Conversation dict.
            session_id: Session identifier (for error message).

        Raises:
            HTTPException: 403 if not owner.
        """
        if not AccessControl.is_owner(user_ctx, conversation_data):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only the owner can modify access settings for session {session_id}",
            )

    @staticmethod
    def validate_access_update(
        whitelist: list[str] | None,
        blacklist: list[str] | None,
    ) -> None:
        """
        Validate access list updates.

        Ensures no user appears in both whitelist and blacklist.

        Args:
            whitelist: New whitelist values.
            blacklist: New blacklist values.

        Raises:
            HTTPException: 400 if validation fails.
        """
        if whitelist is None or blacklist is None:
            return

        overlap = set(whitelist) & set(blacklist)
        if overlap:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Users cannot be in both whitelist and blacklist: {list(overlap)}",
            )


# Global instance
access_control = AccessControl()
