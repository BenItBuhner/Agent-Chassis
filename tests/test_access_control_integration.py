"""
Integration tests for conversation access control via HTTP API (OSP-12).

Tests the full HTTP flow:
1. Create session as user A → owned by A
2. User B cannot access A's session (403)
3. User A makes session public → User B can access
4. User A adds User C to whitelist → User C can access
5. User A adds User D to blacklist → User D cannot access (even if public)
6. Only owner can modify access settings

These tests require:
- ENABLE_PERSISTENCE=true
- CHASSIS_API_KEY set (for authentication)
- DATABASE_URL and REDIS_URL configured
- OPENAI_API_KEY set with a valid model (uses OPENAI_MODEL from config)

NOTE: These tests make real API calls to create sessions. If the configured
model is unavailable or API key is invalid, tests will fail.
"""

import pytest

from app.core.config import settings
from app.services.database import database
from app.services.redis_cache import redis_cache

# Use configured model or default
TEST_MODEL = settings.OPENAI_MODEL or "kimi-k2-thinking"


# Simulated user IDs
USER_A = "user-alice"
USER_B = "user-bob"
USER_C = "user-charlie"
USER_D = "user-dave"


def get_headers(user_id: str, api_key: str = "test-api-key") -> dict:
    """Get request headers for a specific user."""
    return {
        "X-API-Key": api_key,
        "X-User-ID": user_id,
        "Content-Type": "application/json",
    }


@pytest.fixture(scope="module")
def setup_persistence():
    """Ensure persistence is enabled and connected for integration tests."""
    if not settings.ENABLE_PERSISTENCE:
        pytest.skip("ENABLE_PERSISTENCE is False - skipping integration tests")

    # Note: In real tests, you'd want to ensure connections are established
    # For now, we'll skip if not available
    if not database.is_available and not redis_cache.is_available:
        pytest.skip("No persistence services available")


@pytest.fixture
def test_api_key():
    """Get test API key or skip if not configured."""
    if not settings.CHASSIS_API_KEY:
        pytest.skip("CHASSIS_API_KEY not configured - skipping integration tests")
    return settings.CHASSIS_API_KEY


@pytest.fixture
def check_openai_configured():
    """Skip if OpenAI is not configured (needed for agent completion)."""
    if not settings.OPENAI_API_KEY:
        pytest.skip("OPENAI_API_KEY not configured - skipping integration tests")


@pytest.mark.integration
def test_session_ownership_integration(client, setup_persistence, test_api_key, check_openai_configured):
    """Test that sessions are owned by their creator via HTTP API."""
    # Create session as User A
    response = client.post(
        "/api/v1/agent/completion",
        headers=get_headers(USER_A, test_api_key),
        json={
            "message": "Hello, I am creating a new session!",
            "model": TEST_MODEL,
            "allowed_tools": [],
        },
    )

    assert response.status_code == 200, f"Failed to create session: {response.text}"
    data = response.json()
    session_id = data.get("session_id")
    assert session_id is not None, "Session ID not returned"

    # Get session info as User A (owner) - should include access settings
    response = client.get(
        f"/api/v1/agent/session/{session_id}",
        headers=get_headers(USER_A, test_api_key),
    )

    assert response.status_code == 200
    info = response.json()
    assert info.get("message_count") is not None

    # Owner should see access settings
    if "access" in info:
        assert info["access"].get("owner_id") == USER_A
        assert info["access"].get("is_public") is False

    return session_id


@pytest.mark.integration
def test_access_denied_for_non_owner(client, setup_persistence, test_api_key, check_openai_configured):
    """Test that non-owners are denied access by default."""
    # First create a session as User A
    response = client.post(
        "/api/v1/agent/completion",
        headers=get_headers(USER_A, test_api_key),
        json={
            "message": "Create a private session",
            "model": TEST_MODEL,
            "allowed_tools": [],
        },
    )
    assert response.status_code == 200
    session_id = response.json().get("session_id")

    # User B tries to access User A's session
    response = client.post(
        "/api/v1/agent/completion",
        headers=get_headers(USER_B, test_api_key),
        json={
            "session_id": session_id,
            "message": "Can I access this?",
            "model": TEST_MODEL,
            "allowed_tools": [],
        },
    )

    assert response.status_code == 403, "Non-owner should be denied access"


@pytest.mark.integration
def test_public_access_integration(client, setup_persistence, test_api_key, check_openai_configured):
    """Test that public sessions are accessible to all."""
    # Create session as User A
    response = client.post(
        "/api/v1/agent/completion",
        headers=get_headers(USER_A, test_api_key),
        json={
            "message": "Create a session",
            "model": TEST_MODEL,
            "allowed_tools": [],
        },
    )
    assert response.status_code == 200
    session_id = response.json().get("session_id")

    # User A makes session public
    response = client.patch(
        f"/api/v1/agent/session/{session_id}/access",
        headers=get_headers(USER_A, test_api_key),
        json={"is_public": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("is_public") is True

    # User B should now be able to access
    response = client.get(
        f"/api/v1/agent/session/{session_id}",
        headers=get_headers(USER_B, test_api_key),
    )
    assert response.status_code == 200, "Public session should be accessible to all"


@pytest.mark.integration
def test_whitelist_access_integration(client, setup_persistence, test_api_key, check_openai_configured):
    """Test that whitelisted users can access private sessions."""
    # Create session as User A
    response = client.post(
        "/api/v1/agent/completion",
        headers=get_headers(USER_A, test_api_key),
        json={
            "message": "Create a session",
            "model": TEST_MODEL,
            "allowed_tools": [],
        },
    )
    assert response.status_code == 200
    session_id = response.json().get("session_id")

    # Make session private
    response = client.patch(
        f"/api/v1/agent/session/{session_id}/access",
        headers=get_headers(USER_A, test_api_key),
        json={"is_public": False},
    )
    assert response.status_code == 200

    # User B should be denied
    response = client.get(
        f"/api/v1/agent/session/{session_id}",
        headers=get_headers(USER_B, test_api_key),
    )
    assert response.status_code == 403, "Private session should deny non-owners"

    # User A adds User C to whitelist
    response = client.patch(
        f"/api/v1/agent/session/{session_id}/access",
        headers=get_headers(USER_A, test_api_key),
        json={"add_to_whitelist": [USER_C]},
    )
    assert response.status_code == 200
    data = response.json()
    assert USER_C in data.get("whitelist", [])

    # User C should now be able to access
    response = client.get(
        f"/api/v1/agent/session/{session_id}",
        headers=get_headers(USER_C, test_api_key),
    )
    assert response.status_code == 200, "Whitelisted user should have access"


@pytest.mark.integration
def test_blacklist_access_integration(client, setup_persistence, test_api_key, check_openai_configured):
    """Test that blacklisted users are denied even if public."""
    # Create session as User A
    response = client.post(
        "/api/v1/agent/completion",
        headers=get_headers(USER_A, test_api_key),
        json={
            "message": "Create a session",
            "model": TEST_MODEL,
            "allowed_tools": [],
        },
    )
    assert response.status_code == 200
    session_id = response.json().get("session_id")

    # Make session public AND blacklist User D
    response = client.patch(
        f"/api/v1/agent/session/{session_id}/access",
        headers=get_headers(USER_A, test_api_key),
        json={
            "is_public": True,
            "add_to_blacklist": [USER_D],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("is_public") is True
    assert USER_D in data.get("blacklist", [])

    # User D should be denied despite public
    response = client.get(
        f"/api/v1/agent/session/{session_id}",
        headers=get_headers(USER_D, test_api_key),
    )
    assert response.status_code == 403, "Blacklisted user should be denied even if public"


@pytest.mark.integration
def test_only_owner_can_modify_access(client, setup_persistence, test_api_key, check_openai_configured):
    """Test that only the owner can modify access settings."""
    # Create session as User A
    response = client.post(
        "/api/v1/agent/completion",
        headers=get_headers(USER_A, test_api_key),
        json={
            "message": "Create a session",
            "model": TEST_MODEL,
            "allowed_tools": [],
        },
    )
    assert response.status_code == 200
    session_id = response.json().get("session_id")

    # User B tries to modify access settings
    response = client.patch(
        f"/api/v1/agent/session/{session_id}/access",
        headers=get_headers(USER_B, test_api_key),
        json={"is_public": True},
    )
    assert response.status_code == 403, "Non-owner should not be able to modify access"


@pytest.mark.integration
def test_only_owner_can_delete_session(client, setup_persistence, test_api_key, check_openai_configured):
    """Test that only the owner can delete a session."""
    # Create session as User A
    response = client.post(
        "/api/v1/agent/completion",
        headers=get_headers(USER_A, test_api_key),
        json={
            "message": "Create a session",
            "model": TEST_MODEL,
            "allowed_tools": [],
        },
    )
    assert response.status_code == 200
    session_id = response.json().get("session_id")

    # User B tries to delete
    response = client.delete(
        f"/api/v1/agent/session/{session_id}",
        headers=get_headers(USER_B, test_api_key),
    )
    assert response.status_code == 403, "Non-owner should not be able to delete"

    # User A deletes (should succeed)
    response = client.delete(
        f"/api/v1/agent/session/{session_id}",
        headers=get_headers(USER_A, test_api_key),
    )
    assert response.status_code == 200, "Owner should be able to delete"
