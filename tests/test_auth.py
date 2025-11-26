"""
Tests for the authentication system (OSP-14).

Tests cover:
- JWT token generation and validation
- Password hashing
- User registration flow
- Login flow
- Token refresh
- Email verification (mocked)
"""

from datetime import UTC

import pytest

from app.core.config import settings

# =============================================================================
# JWT Service Tests
# =============================================================================


class TestJWTService:
    """Tests for JWT token service."""

    @pytest.fixture
    def jwt_service(self):
        """Get JWT service with test configuration."""
        # Temporarily set JWT_SECRET_KEY for testing
        original_key = settings.JWT_SECRET_KEY
        settings.JWT_SECRET_KEY = "test-secret-key-for-testing-only"

        from app.services.jwt_service import JWTService

        service = JWTService()

        yield service

        # Restore original setting
        settings.JWT_SECRET_KEY = original_key

    def test_is_available_with_secret(self, jwt_service):
        """JWT should be available when secret key is set."""
        assert jwt_service.is_available() is True

    def test_create_access_token(self, jwt_service):
        """Should create a valid access token."""
        token = jwt_service.create_access_token(user_id="user-123", email="test@example.com")

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_refresh_token(self, jwt_service):
        """Should create a valid refresh token."""
        token = jwt_service.create_refresh_token(user_id="user-123")

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_verify_access_token(self, jwt_service):
        """Should verify a valid access token."""
        token = jwt_service.create_access_token(user_id="user-123", email="test@example.com")

        payload = jwt_service.verify_access_token(token)

        assert payload is not None
        assert payload.get("sub") == "user-123"
        assert payload.get("email") == "test@example.com"
        assert payload.get("type") == "access"

    def test_verify_refresh_token(self, jwt_service):
        """Should verify a valid refresh token."""
        token = jwt_service.create_refresh_token(user_id="user-123")

        payload = jwt_service.verify_refresh_token(token)

        assert payload is not None
        assert payload.get("sub") == "user-123"
        assert payload.get("type") == "refresh"

    def test_verify_invalid_token(self, jwt_service):
        """Should return None for invalid token."""
        payload = jwt_service.verify_token("invalid-token")
        assert payload is None

    def test_access_token_not_valid_as_refresh(self, jwt_service):
        """Access token should not be valid as refresh token."""
        token = jwt_service.create_access_token(user_id="user-123", email="test@example.com")

        payload = jwt_service.verify_refresh_token(token)
        assert payload is None

    def test_refresh_token_not_valid_as_access(self, jwt_service):
        """Refresh token should not be valid as access token."""
        token = jwt_service.create_refresh_token(user_id="user-123")

        payload = jwt_service.verify_access_token(token)
        assert payload is None


# =============================================================================
# Password Hashing Tests
# =============================================================================


class TestPasswordHashing:
    """Tests for password hashing functionality."""

    def test_hash_password(self):
        """Should hash a password."""
        from app.services.auth_service import AuthService

        password = "TestPassword123"
        hashed = AuthService.hash_password(password)

        assert hashed is not None
        assert hashed != password
        assert len(hashed) > 0

    def test_verify_correct_password(self):
        """Should verify correct password."""
        from app.services.auth_service import AuthService

        password = "TestPassword123"
        hashed = AuthService.hash_password(password)

        assert AuthService.verify_password(password, hashed) is True

    def test_verify_incorrect_password(self):
        """Should reject incorrect password."""
        from app.services.auth_service import AuthService

        password = "TestPassword123"
        wrong_password = "WrongPassword456"
        hashed = AuthService.hash_password(password)

        assert AuthService.verify_password(wrong_password, hashed) is False

    def test_different_hashes_for_same_password(self):
        """Should generate different hashes for the same password (salt)."""
        from app.services.auth_service import AuthService

        password = "TestPassword123"
        hash1 = AuthService.hash_password(password)
        hash2 = AuthService.hash_password(password)

        assert hash1 != hash2  # Different salts
        assert AuthService.verify_password(password, hash1) is True
        assert AuthService.verify_password(password, hash2) is True


# =============================================================================
# Email Service Tests
# =============================================================================


class TestEmailService:
    """Tests for email service."""

    def test_generate_verification_code(self):
        """Should generate 6-digit verification code."""
        from app.services.email_service import EmailService

        code = EmailService.generate_verification_code()

        assert len(code) == 6
        assert code.isdigit()

    def test_verification_codes_are_random(self):
        """Should generate different codes each time."""
        from app.services.email_service import EmailService

        codes = [EmailService.generate_verification_code() for _ in range(10)]
        unique_codes = set(codes)

        # With 10 random 6-digit codes, we should have at least some variation
        assert len(unique_codes) > 1


# =============================================================================
# Auth Schemas Tests
# =============================================================================


class TestAuthSchemas:
    """Tests for auth request/response schemas."""

    def test_register_request_valid(self):
        """Should accept valid registration data."""
        from app.schemas.auth import RegisterRequest

        request = RegisterRequest(email="test@example.com", password="SecurePass123", display_name="Test User")

        assert request.email == "test@example.com"
        assert request.password == "SecurePass123"
        assert request.display_name == "Test User"

    def test_register_request_password_too_short(self):
        """Should reject password shorter than 8 characters."""
        from pydantic import ValidationError

        from app.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(
                email="test@example.com",
                password="Short1",  # Too short
            )

    def test_register_request_password_no_digit(self):
        """Should reject password without digit."""
        from pydantic import ValidationError

        from app.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(
                email="test@example.com",
                password="NoDigitsHere",
            )

    def test_register_request_password_no_letter(self):
        """Should reject password without letter."""
        from pydantic import ValidationError

        from app.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(
                email="test@example.com",
                password="12345678",  # No letters
            )

    def test_register_request_invalid_email(self):
        """Should reject invalid email format."""
        from pydantic import ValidationError

        from app.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(
                email="not-an-email",
                password="SecurePass123",
            )

    def test_verify_email_request_valid(self):
        """Should accept valid verification code."""
        from app.schemas.auth import VerifyEmailRequest

        request = VerifyEmailRequest(email="test@example.com", code="123456")

        assert request.code == "123456"

    def test_verify_email_request_code_too_short(self):
        """Should reject code shorter than 6 digits."""
        from pydantic import ValidationError

        from app.schemas.auth import VerifyEmailRequest

        with pytest.raises(ValidationError):
            VerifyEmailRequest(
                email="test@example.com",
                code="12345",  # Too short
            )

    def test_verify_email_request_code_too_long(self):
        """Should reject code longer than 6 digits."""
        from pydantic import ValidationError

        from app.schemas.auth import VerifyEmailRequest

        with pytest.raises(ValidationError):
            VerifyEmailRequest(
                email="test@example.com",
                code="1234567",  # Too long
            )


# =============================================================================
# Security Integration Tests
# =============================================================================


class TestSecurityIntegration:
    """Tests for security module integration."""

    def test_user_context_can_own_sessions_with_auth(self):
        """UserContext should allow session ownership when authenticated."""
        from app.core.security import UserContext

        ctx = UserContext(user_id="user-123", auth_enabled=True, is_authenticated=True, auth_method="jwt")

        assert ctx.can_own_sessions is True
        assert ctx.is_jwt_authenticated is True

    def test_user_context_cannot_own_sessions_without_auth(self):
        """UserContext should not allow session ownership without auth."""
        from app.core.security import UserContext

        ctx = UserContext(user_id="user-123", auth_enabled=False, is_authenticated=False, auth_method="none")

        assert ctx.can_own_sessions is False

    def test_user_context_cannot_own_sessions_without_user_id(self):
        """UserContext should not allow session ownership without user_id."""
        from app.core.security import UserContext

        ctx = UserContext(user_id=None, auth_enabled=True, is_authenticated=True, auth_method="api_key")

        assert ctx.can_own_sessions is False

    def test_hash_api_key(self):
        """Should create deterministic hash from API key."""
        from app.core.security import _hash_api_key

        key = "test-api-key-12345"
        hash1 = _hash_api_key(key)
        hash2 = _hash_api_key(key)

        assert hash1 == hash2
        assert len(hash1) == 32
        assert hash1 != key

    def test_extract_bearer_token(self):
        """Should extract Bearer token from Authorization header."""
        from app.core.security import _extract_bearer_token

        token = _extract_bearer_token("Bearer abc123")
        assert token == "abc123"

        token = _extract_bearer_token("bearer XYZ789")  # Case insensitive
        assert token == "XYZ789"

        token = _extract_bearer_token("Basic abc123")  # Wrong scheme
        assert token is None

        token = _extract_bearer_token(None)
        assert token is None

        token = _extract_bearer_token("")
        assert token is None


# =============================================================================
# User Model Tests
# =============================================================================


class TestUserModel:
    """Tests for User database model."""

    def test_user_to_dict(self):
        """Should convert User to dictionary without sensitive data."""
        from datetime import datetime

        from app.models.user import User

        user = User(
            id="user-123",
            email="test@example.com",
            email_verified=True,
            password_hash="hashed_password",  # Sensitive - should not be in dict
            google_id="google-123",
            display_name="Test User",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            updated_at=datetime(2024, 1, 2, tzinfo=UTC),
            is_active=True,
            is_admin=False,
        )

        data = user.to_dict()

        assert data["id"] == "user-123"
        assert data["email"] == "test@example.com"
        assert data["email_verified"] is True
        assert data["google_id"] is True  # Boolean, not actual ID
        assert data["display_name"] == "Test User"
        assert "password_hash" not in data  # Sensitive
        assert "hashed_password" not in str(data)  # Double check


# =============================================================================
# Integration Tests (require running services)
# =============================================================================


@pytest.mark.integration
class TestAuthIntegration:
    """Integration tests for auth endpoints (require database and Redis)."""

    @pytest.fixture
    def client(self):
        """Get test client."""
        from fastapi.testclient import TestClient

        from app.main import app

        return TestClient(app)

    def test_auth_disabled_by_default(self, client):
        """Auth endpoints should return 503 when user auth is disabled."""
        response = client.post("/api/v1/auth/login", json={"email": "test@example.com", "password": "password123"})

        # Should fail because ENABLE_USER_AUTH is False by default
        assert response.status_code == 503
        assert "not enabled" in response.json()["detail"].lower()


class TestJWTWithServerSidePersistence:
    """Tests to verify JWT auth integrates correctly with server-side persistence."""

    def test_jwt_user_context_can_own_sessions(self):
        """JWT-authenticated user should be able to own sessions."""
        from app.core.security import UserContext

        # Simulate JWT-authenticated user
        jwt_user = UserContext(
            user_id="user-uuid-123",
            auth_enabled=True,
            is_authenticated=True,
            auth_method="jwt",
            email="test@example.com",
        )

        assert jwt_user.can_own_sessions is True
        assert jwt_user.is_jwt_authenticated is True
        assert jwt_user.user_id == "user-uuid-123"

    def test_jwt_user_id_used_as_owner_id(self):
        """JWT user_id should be used as session owner_id."""
        from app.core.security import UserContext

        jwt_user = UserContext(
            user_id="jwt-user-abc123",
            auth_enabled=True,
            is_authenticated=True,
            auth_method="jwt",
            email="owner@example.com",
        )

        # This is what session_manager uses to set owner_id
        owner_id = jwt_user.user_id if jwt_user.can_own_sessions else None

        assert owner_id == "jwt-user-abc123"

    def test_access_control_with_jwt_user(self):
        """Access control should work correctly with JWT-authenticated users."""
        from app.core.security import UserContext
        from app.services.access_control import AccessControl

        # Session owned by JWT user
        session_data = {
            "id": "session-123",
            "owner_id": "jwt-owner-id",
            "is_public": False,
            "access_whitelist": [],
            "access_blacklist": [],
        }

        # Owner accessing their session
        owner_ctx = UserContext(
            user_id="jwt-owner-id",
            auth_enabled=True,
            is_authenticated=True,
            auth_method="jwt",
        )
        assert AccessControl.can_access(owner_ctx, session_data) is True
        assert AccessControl.is_owner(owner_ctx, session_data) is True

        # Other JWT user trying to access
        other_ctx = UserContext(
            user_id="jwt-other-id",
            auth_enabled=True,
            is_authenticated=True,
            auth_method="jwt",
        )
        assert AccessControl.can_access(other_ctx, session_data) is False
        assert AccessControl.is_owner(other_ctx, session_data) is False

        # Whitelist grants access
        session_data["access_whitelist"] = ["jwt-other-id"]
        assert AccessControl.can_access(other_ctx, session_data) is True

    def test_api_key_and_jwt_users_isolated(self):
        """API key users and JWT users should have separate session ownership."""
        from app.core.security import UserContext
        from app.services.access_control import AccessControl

        # Session owned by JWT user
        session_data = {
            "id": "session-123",
            "owner_id": "jwt-user-uuid",
            "is_public": False,
            "access_whitelist": [],
            "access_blacklist": [],
        }

        # JWT owner
        jwt_owner = UserContext(
            user_id="jwt-user-uuid",
            auth_enabled=True,
            is_authenticated=True,
            auth_method="jwt",
        )
        assert AccessControl.can_access(jwt_owner, session_data) is True

        # API key user (different user_id)
        api_key_user = UserContext(
            user_id="api-key-hash-xyz",
            auth_enabled=True,
            is_authenticated=True,
            auth_method="api_key",
        )
        assert AccessControl.can_access(api_key_user, session_data) is False

        # They are isolated - API key user cannot access JWT user's session
        assert AccessControl.is_owner(api_key_user, session_data) is False
