"""
Tests for security hardening features.

Tests the following security implementations:
- CORS configuration
- Security headers middleware
- Input size limits (messages, metadata)
- Login brute force protection
- JWT secret key validation
- URL sanitization for logging
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.schemas.agent import ChatMessage, CompletionRequest


class TestURLSanitization:
    """Test URL sanitization for safe logging."""

    def test_sanitize_redis_url_with_password(self):
        """Test that Redis URL password is masked."""
        from app.core.config import settings

        url = "rediss://default:secretpassword123@example.com:6379"
        sanitized = settings.sanitize_url(url)

        assert "secretpassword123" not in sanitized
        assert "*****" in sanitized
        assert "example.com" in sanitized

    def test_sanitize_database_url_with_password(self):
        """Test that database URL password is masked."""
        from app.core.config import settings

        url = "postgresql+asyncpg://user:mysecretpass@localhost:5432/db"
        sanitized = settings.sanitize_url(url)

        assert "mysecretpass" not in sanitized
        assert "*****" in sanitized
        assert "localhost" in sanitized

    def test_sanitize_url_without_password(self):
        """Test URL without password returns unchanged."""
        from app.core.config import settings

        url = "redis://localhost:6379"
        sanitized = settings.sanitize_url(url)

        assert sanitized == url

    def test_sanitize_none_url(self):
        """Test None URL returns appropriate message."""
        from app.core.config import settings

        sanitized = settings.sanitize_url(None)
        assert sanitized == "not configured"

    def test_sanitize_empty_url(self):
        """Test empty URL returns appropriate message."""
        from app.core.config import settings

        sanitized = settings.sanitize_url("")
        assert sanitized == "not configured"


class TestInputSizeLimits:
    """Test input size validation on schemas."""

    def test_message_content_within_limit(self):
        """Test message content within limit is accepted."""
        msg = ChatMessage(role="user", content="Hello" * 100)
        assert msg.content == "Hello" * 100

    def test_message_content_at_limit(self):
        """Test message content at exactly the limit."""
        from app.core.config import settings

        # Create content exactly at limit
        content = "x" * settings.MAX_MESSAGE_LENGTH
        msg = ChatMessage(role="user", content=content)
        assert len(msg.content) == settings.MAX_MESSAGE_LENGTH

    def test_message_content_exceeds_limit(self):
        """Test message content exceeding limit is rejected."""
        from app.core.config import settings

        # Create content exceeding limit
        content = "x" * (settings.MAX_MESSAGE_LENGTH + 1)

        with pytest.raises(ValueError) as exc:
            ChatMessage(role="user", content=content)

        # Pydantic error message format: "String should have at most X characters"
        error_msg = str(exc.value).lower()
        assert "string_too_long" in error_msg or "at most" in error_msg

    def test_metadata_within_limit(self):
        """Test metadata within limit is accepted."""
        metadata = {"key": "value", "number": 123}
        request = CompletionRequest(message="Hello", metadata=metadata)
        assert request.metadata == metadata

    def test_metadata_exceeds_limit(self):
        """Test metadata exceeding size limit is rejected."""
        from app.core.config import settings

        # Create metadata exceeding limit
        large_metadata = {"data": "x" * (settings.MAX_METADATA_SIZE + 1000)}

        with pytest.raises(ValueError) as exc:
            CompletionRequest(message="Hello", metadata=large_metadata)

        assert "metadata" in str(exc.value).lower()

    def test_messages_count_within_limit(self):
        """Test messages array within limit is accepted."""
        messages = [ChatMessage(role="user", content=f"msg {i}") for i in range(10)]
        request = CompletionRequest(messages=messages)
        assert len(request.messages) == 10

    def test_messages_count_exceeds_limit(self):
        """Test messages array exceeding limit is rejected."""
        from app.core.config import settings

        # Create more messages than allowed
        messages = [ChatMessage(role="user", content=f"msg {i}") for i in range(settings.MAX_MESSAGES_PER_REQUEST + 1)]

        with pytest.raises(ValueError) as exc:
            CompletionRequest(messages=messages)

        assert "too many messages" in str(exc.value).lower()


class TestSecurityHeaders:
    """Test security headers middleware."""

    def test_security_headers_present(self):
        """Test that security headers are added to responses."""
        from app.main import app

        client = TestClient(app)
        response = client.get("/health")

        # Check security headers
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_api_cache_control_headers(self):
        """Test that API endpoints have cache control headers."""
        from app.core.config import settings
        from app.main import app

        client = TestClient(app)
        # Make a request to an API endpoint
        response = client.post(
            f"{settings.API_V1_STR}/agent/completion",
            json={"message": "test"},
            headers={"X-API-Key": "test"} if settings.CHASSIS_API_KEY else {},
        )

        # API responses should not be cached
        cache_control = response.headers.get("Cache-Control", "")
        assert "no-store" in cache_control or "no-cache" in cache_control


class TestCORSConfiguration:
    """Test CORS middleware configuration."""

    def test_cors_headers_on_options(self):
        """Test CORS headers on preflight requests."""
        from app.main import app

        client = TestClient(app)
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

        # Should have CORS headers
        assert "access-control-allow-origin" in response.headers or response.status_code == 200


class TestJWTConfiguration:
    """Test JWT configuration validation."""

    def test_jwt_secret_auto_generated_warning(self):
        """Test that missing JWT_SECRET_KEY triggers warning when auth enabled."""
        # This tests the validation logic
        with patch.dict("os.environ", {"ENABLE_USER_AUTH": "true"}, clear=False):
            # Create fresh settings to trigger validation
            test_settings = Settings(
                ENABLE_USER_AUTH=True,
                JWT_SECRET_KEY=None,
            )

            # Should auto-generate a key
            assert test_settings.JWT_SECRET_KEY is not None
            assert len(test_settings.JWT_SECRET_KEY) >= 32

    def test_jwt_secret_preserved_when_provided(self):
        """Test that provided JWT_SECRET_KEY is preserved."""
        my_secret = "my-very-secure-secret-key-that-is-long-enough"

        test_settings = Settings(
            ENABLE_USER_AUTH=True,
            JWT_SECRET_KEY=my_secret,
        )

        assert test_settings.JWT_SECRET_KEY == my_secret


class TestLoginRateLimiting:
    """Test login brute force protection."""

    @pytest.mark.asyncio
    async def test_failed_login_tracking_key_format(self):
        """Test that failed login tracking uses correct key format."""
        from app.services.auth_service import AuthService

        service = AuthService()
        email = "test@example.com"

        expected_key = f"auth:login_attempts:{email.lower()}"
        assert service.LOGIN_ATTEMPTS_KEY.format(email=email.lower()) == expected_key

    @pytest.mark.asyncio
    async def test_rate_limit_config_exists(self):
        """Test that rate limit configuration exists."""
        from app.core.config import settings

        assert hasattr(settings, "LOGIN_RATE_LIMIT_ATTEMPTS")
        assert hasattr(settings, "LOGIN_RATE_LIMIT_WINDOW_SECONDS")
        assert settings.LOGIN_RATE_LIMIT_ATTEMPTS > 0
        assert settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS > 0


class TestHealthEndpointSecurity:
    """Test health endpoint security information."""

    def test_health_shows_auth_status(self):
        """Test health endpoint shows authentication status."""
        from app.main import app

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()

        # Should show user auth status
        assert "user_auth_enabled" in data


class TestCompletionRequestValidation:
    """Test completion request validation."""

    def test_temperature_bounds(self):
        """Test temperature is bounded between 0 and 2."""
        # Valid temperature
        request = CompletionRequest(message="test", temperature=1.0)
        assert request.temperature == 1.0

        # At boundaries
        request_low = CompletionRequest(message="test", temperature=0.0)
        assert request_low.temperature == 0.0

        request_high = CompletionRequest(message="test", temperature=2.0)
        assert request_high.temperature == 2.0

    def test_temperature_out_of_bounds(self):
        """Test temperature outside bounds is rejected."""
        with pytest.raises(ValueError):
            CompletionRequest(message="test", temperature=-0.1)

        with pytest.raises(ValueError):
            CompletionRequest(message="test", temperature=2.1)

    def test_max_tokens_bounds(self):
        """Test max_tokens has reasonable bounds."""
        # Valid max_tokens
        request = CompletionRequest(message="test", max_tokens=1000)
        assert request.max_tokens == 1000

        # At minimum
        request_min = CompletionRequest(message="test", max_tokens=1)
        assert request_min.max_tokens == 1

    def test_max_tokens_invalid(self):
        """Test max_tokens with invalid values."""
        with pytest.raises(ValueError):
            CompletionRequest(message="test", max_tokens=0)

        with pytest.raises(ValueError):
            CompletionRequest(message="test", max_tokens=-1)

    def test_session_id_length_limit(self):
        """Test session_id has length limit."""
        # Valid session_id
        request = CompletionRequest(message="test", session_id="abc123")
        assert request.session_id == "abc123"

        # At limit (100 chars)
        long_id = "x" * 100
        request_long = CompletionRequest(message="test", session_id=long_id)
        assert len(request_long.session_id) == 100

    def test_session_id_too_long(self):
        """Test session_id exceeding limit is rejected."""
        too_long_id = "x" * 101

        with pytest.raises(ValueError):
            CompletionRequest(message="test", session_id=too_long_id)
