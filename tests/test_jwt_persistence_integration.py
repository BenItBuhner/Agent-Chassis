"""
Integration tests for JWT authentication with server-side persistent sessions.

Tests the complete flow:
1. JWT user creates a new session → session stored in DB with owner_id
2. JWT user continues the session → session loaded, access verified
3. Different JWT user cannot access the session → 403 Forbidden
4. Owner can share session via whitelist → other user gains access

Requires: ENABLE_PERSISTENCE=true, DATABASE_URL configured, REDIS_URL configured
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.security import UserContext
from app.schemas.agent import CompletionRequest


@pytest.fixture
def jwt_user_a():
    """JWT-authenticated User A (session owner)."""
    return UserContext(
        user_id="jwt-user-a-uuid-12345",
        auth_enabled=True,
        is_authenticated=True,
        auth_method="jwt",
        email="usera@example.com",
    )


@pytest.fixture
def jwt_user_b():
    """JWT-authenticated User B (different user)."""
    return UserContext(
        user_id="jwt-user-b-uuid-67890",
        auth_enabled=True,
        is_authenticated=True,
        auth_method="jwt",
        email="userb@example.com",
    )


@pytest.fixture
def mock_session_data():
    """Sample session data as stored in DB/Redis."""
    return {
        "id": "test-session-uuid",
        "messages": [
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        "system_prompt": None,
        "model": "kimi-k2-thinking",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "message_count": 2,
        "metadata": {},
        "owner_id": "jwt-user-a-uuid-12345",  # Owned by User A
        "is_public": False,
        "access_whitelist": [],
        "access_blacklist": [],
    }


@pytest.mark.integration
class TestSessionCreationWithJWT:
    """Test that new sessions are correctly created with JWT user as owner."""

    @pytest.mark.asyncio
    async def test_new_session_sets_jwt_user_as_owner(self, jwt_user_a):
        """When JWT user creates a session, owner_id should be their user_id."""
        from unittest.mock import PropertyMock

        from app.services.session_manager import SessionManager

        manager = SessionManager()

        # Mock Redis and DB as available
        mock_redis = MagicMock()
        mock_redis.is_available = True
        mock_redis.set_session = AsyncMock(return_value=True)

        mock_db = MagicMock()
        mock_db.is_available = True
        mock_db.create_conversation = AsyncMock(return_value=True)

        manager._SessionManager__redis = mock_redis  # Override internal
        manager._SessionManager__db = mock_db

        # Mock persistence_enabled property
        with (
            patch.object(SessionManager, "persistence_enabled", new_callable=PropertyMock) as mock_persist,
            patch.object(manager, "redis", mock_redis),
            patch.object(manager, "db", mock_db),
        ):
            mock_persist.return_value = True

            # Simulate saving a new session
            success = await manager.save_session(
                session_id="new-session-123",
                messages=[{"role": "user", "content": "Hello!"}],
                system_prompt=None,
                model="kimi-k2-thinking",
                metadata={},
                user_ctx=jwt_user_a,
                is_new_session=True,
            )

            assert success is True

            # Verify Redis was called with correct owner_id
            redis_call = mock_redis.set_session.call_args
            session_data = redis_call[0][1]  # Second positional arg
            assert session_data["owner_id"] == "jwt-user-a-uuid-12345"
            assert session_data["is_public"] is False

            # Verify DB was called with correct owner_id
            db_call = mock_db.create_conversation.call_args
            assert db_call.kwargs["owner_id"] == "jwt-user-a-uuid-12345"

    @pytest.mark.asyncio
    async def test_owner_can_access_their_session(self, jwt_user_a, mock_session_data):
        """Session owner should be able to load their session."""
        from unittest.mock import PropertyMock

        from app.services.session_manager import SessionManager

        manager = SessionManager()

        with (
            patch.object(manager, "_load_session", new_callable=AsyncMock) as mock_load,
            patch.object(SessionManager, "persistence_enabled", new_callable=PropertyMock) as mock_persist,
        ):
            mock_persist.return_value = True
            mock_load.return_value = mock_session_data

            # Owner (User A) loads their session
            session_id, messages = await manager.get_or_create_session(
                session_id="test-session-uuid",
                messages=None,
                user_ctx=jwt_user_a,
            )

            assert session_id == "test-session-uuid"
            assert len(messages) == 2
            assert messages[0]["content"] == "Hello!"

    @pytest.mark.asyncio
    async def test_non_owner_cannot_access_session(self, jwt_user_b, mock_session_data):
        """Non-owner JWT user should be denied access to another user's session."""
        from unittest.mock import PropertyMock

        from fastapi import HTTPException

        from app.services.session_manager import SessionManager

        manager = SessionManager()

        with (
            patch.object(manager, "_load_session", new_callable=AsyncMock) as mock_load,
            patch.object(SessionManager, "persistence_enabled", new_callable=PropertyMock) as mock_persist,
        ):
            mock_persist.return_value = True
            mock_load.return_value = mock_session_data  # Owned by User A

            # User B tries to access User A's session
            with pytest.raises(HTTPException) as exc_info:
                await manager.get_or_create_session(
                    session_id="test-session-uuid",
                    messages=None,
                    user_ctx=jwt_user_b,
                )

            assert exc_info.value.status_code == 403
            assert "Access denied" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_whitelisted_user_can_access_session(self, jwt_user_b, mock_session_data):
        """User in whitelist should be able to access the session."""
        from unittest.mock import PropertyMock

        from app.services.session_manager import SessionManager

        manager = SessionManager()

        # Add User B to whitelist
        mock_session_data["access_whitelist"] = ["jwt-user-b-uuid-67890"]

        with (
            patch.object(manager, "_load_session", new_callable=AsyncMock) as mock_load,
            patch.object(SessionManager, "persistence_enabled", new_callable=PropertyMock) as mock_persist,
        ):
            mock_persist.return_value = True
            mock_load.return_value = mock_session_data

            # User B (whitelisted) loads the session
            session_id, messages = await manager.get_or_create_session(
                session_id="test-session-uuid",
                messages=None,
                user_ctx=jwt_user_b,
            )

            assert session_id == "test-session-uuid"
            assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_public_session_accessible_by_anyone(self, jwt_user_b, mock_session_data):
        """Public session should be accessible by any authenticated user."""
        from unittest.mock import PropertyMock

        from app.services.session_manager import SessionManager

        manager = SessionManager()

        # Make session public
        mock_session_data["is_public"] = True

        with (
            patch.object(manager, "_load_session", new_callable=AsyncMock) as mock_load,
            patch.object(SessionManager, "persistence_enabled", new_callable=PropertyMock) as mock_persist,
        ):
            mock_persist.return_value = True
            mock_load.return_value = mock_session_data

            # User B accesses public session
            session_id, messages = await manager.get_or_create_session(
                session_id="test-session-uuid",
                messages=None,
                user_ctx=jwt_user_b,
            )

            assert session_id == "test-session-uuid"

    @pytest.mark.asyncio
    async def test_blacklisted_user_denied_even_if_public(self, jwt_user_b, mock_session_data):
        """Blacklisted user should be denied even on public sessions."""
        from unittest.mock import PropertyMock

        from fastapi import HTTPException

        from app.services.session_manager import SessionManager

        manager = SessionManager()

        # Public but User B is blacklisted
        mock_session_data["is_public"] = True
        mock_session_data["access_blacklist"] = ["jwt-user-b-uuid-67890"]

        with (
            patch.object(manager, "_load_session", new_callable=AsyncMock) as mock_load,
            patch.object(SessionManager, "persistence_enabled", new_callable=PropertyMock) as mock_persist,
        ):
            mock_persist.return_value = True
            mock_load.return_value = mock_session_data

            # User B (blacklisted) tries to access
            with pytest.raises(HTTPException) as exc_info:
                await manager.get_or_create_session(
                    session_id="test-session-uuid",
                    messages=None,
                    user_ctx=jwt_user_b,
                )

            assert exc_info.value.status_code == 403


@pytest.mark.integration
class TestSessionDeletionWithJWT:
    """Test that only session owner can delete sessions."""

    @pytest.mark.asyncio
    async def test_owner_can_delete_session(self, jwt_user_a, mock_session_data):
        """Session owner should be able to delete their session."""
        from app.services.session_manager import SessionManager

        manager = SessionManager()

        with (
            patch.object(manager, "_load_session", new_callable=AsyncMock) as mock_load,
            patch.object(manager, "redis") as mock_redis,
            patch.object(manager, "db") as mock_db,
        ):
            mock_load.return_value = mock_session_data
            mock_redis.is_available = True
            mock_redis.delete_session = AsyncMock(return_value=True)
            mock_db.is_available = True
            mock_db.delete_conversation = AsyncMock(return_value=True)

            # Owner deletes their session
            deleted = await manager.delete_session(
                session_id="test-session-uuid",
                user_ctx=jwt_user_a,
            )

            assert deleted is True

    @pytest.mark.asyncio
    async def test_non_owner_cannot_delete_session(self, jwt_user_b, mock_session_data):
        """Non-owner should not be able to delete another user's session."""
        from fastapi import HTTPException

        from app.services.session_manager import SessionManager

        manager = SessionManager()

        with patch.object(manager, "_load_session", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = mock_session_data  # Owned by User A

            # User B tries to delete User A's session
            with pytest.raises(HTTPException) as exc_info:
                await manager.delete_session(
                    session_id="test-session-uuid",
                    user_ctx=jwt_user_b,
                )

            assert exc_info.value.status_code == 403
            assert "Only the owner" in exc_info.value.detail


@pytest.mark.integration
class TestAgentServiceWithJWT:
    """Test AgentService correctly passes JWT user context through the flow."""

    @pytest.mark.asyncio
    async def test_agent_service_passes_user_context_to_session_manager(self, jwt_user_a):
        """AgentService should pass user_ctx to session manager for access control."""
        from unittest.mock import AsyncMock, MagicMock

        from app.services.agent_service import AgentService
        from app.services.session_manager import session_manager

        # Create mock OpenAI client
        mock_client = MagicMock()

        service = AgentService(mock_client)

        # Create a server-side mode request
        request = CompletionRequest(
            message="Hello!",
            model="kimi-k2-thinking",
            allowed_tools=[],
        )

        # Mock the session manager methods
        with (
            patch.object(session_manager, "get_or_create_session", new_callable=AsyncMock) as mock_get,
            patch.object(session_manager, "save_session", new_callable=AsyncMock) as mock_save,
        ):
            # Return a new session
            mock_get.return_value = ("new-session-id", [])
            mock_save.return_value = True

            # Call _prepare_messages which should pass user_ctx
            session_id, messages, is_new = await service._prepare_messages(request, jwt_user_a)

            # Verify user_ctx was passed to get_or_create_session
            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args.kwargs
            assert call_kwargs.get("user_ctx") == jwt_user_a

            assert session_id == "new-session-id"
            assert is_new is True

    @pytest.mark.asyncio
    async def test_agent_service_save_session_with_user_context(self, jwt_user_a):
        """AgentService._save_session should pass user_ctx and is_new_session."""
        from unittest.mock import AsyncMock, MagicMock

        from app.services.agent_service import AgentService
        from app.services.session_manager import session_manager

        mock_client = MagicMock()
        service = AgentService(mock_client)

        request = CompletionRequest(
            message="Hello!",
            model="kimi-k2-thinking",
        )

        with patch.object(session_manager, "save_session", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = True

            await service._save_session(
                session_id="session-123",
                messages=[{"role": "user", "content": "Hello!"}],
                request=request,
                user_ctx=jwt_user_a,
                is_new_session=True,
            )

            mock_save.assert_called_once()
            call_kwargs = mock_save.call_args.kwargs
            assert call_kwargs.get("user_ctx") == jwt_user_a
            assert call_kwargs.get("is_new_session") is True
