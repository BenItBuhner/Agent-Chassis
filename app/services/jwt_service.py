"""
JWT token service for user authentication.

Handles creation and validation of access and refresh tokens.
Part of OSP-14 implementation.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings

# Conditional import for JWT library
try:
    from jose import JWTError, jwt

    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    jwt = None  # type: ignore
    JWTError = Exception  # type: ignore


class JWTService:
    """
    Service for creating and validating JWT tokens.

    Supports:
    - Access tokens (short-lived, for API access)
    - Refresh tokens (long-lived, for obtaining new access tokens)
    """

    # Token types
    TOKEN_TYPE_ACCESS = "access"
    TOKEN_TYPE_REFRESH = "refresh"

    @staticmethod
    def is_available() -> bool:
        """Check if JWT functionality is available."""
        return JWT_AVAILABLE and settings.JWT_SECRET_KEY is not None

    @staticmethod
    def create_access_token(
        user_id: str,
        email: str,
        additional_claims: dict[str, Any] | None = None,
    ) -> str:
        """
        Create a short-lived access token.

        Args:
            user_id: User's unique identifier.
            email: User's email address.
            additional_claims: Optional additional claims to include.

        Returns:
            Encoded JWT access token.

        Raises:
            RuntimeError: If JWT is not configured.
        """
        if not JWTService.is_available():
            raise RuntimeError("JWT is not configured. Set JWT_SECRET_KEY in environment.")

        expire = datetime.now(UTC) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

        payload = {
            "sub": user_id,
            "email": email,
            "type": JWTService.TOKEN_TYPE_ACCESS,
            "exp": expire,
            "iat": datetime.now(UTC),
        }

        if additional_claims:
            payload.update(additional_claims)

        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def create_refresh_token(user_id: str) -> str:
        """
        Create a long-lived refresh token.

        Args:
            user_id: User's unique identifier.

        Returns:
            Encoded JWT refresh token.

        Raises:
            RuntimeError: If JWT is not configured.
        """
        if not JWTService.is_available():
            raise RuntimeError("JWT is not configured. Set JWT_SECRET_KEY in environment.")

        expire = datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

        payload = {
            "sub": user_id,
            "type": JWTService.TOKEN_TYPE_REFRESH,
            "exp": expire,
            "iat": datetime.now(UTC),
        }

        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def verify_token(token: str) -> dict[str, Any] | None:
        """
        Verify and decode a JWT token.

        Args:
            token: The JWT token to verify.

        Returns:
            Decoded payload if valid, None if invalid or expired.
        """
        if not JWTService.is_available():
            return None

        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            return payload
        except JWTError:
            return None

    @staticmethod
    def verify_access_token(token: str) -> dict[str, Any] | None:
        """
        Verify an access token specifically.

        Args:
            token: The JWT token to verify.

        Returns:
            Decoded payload if valid access token, None otherwise.
        """
        payload = JWTService.verify_token(token)
        if payload and payload.get("type") == JWTService.TOKEN_TYPE_ACCESS:
            return payload
        return None

    @staticmethod
    def verify_refresh_token(token: str) -> dict[str, Any] | None:
        """
        Verify a refresh token specifically.

        Args:
            token: The JWT token to verify.

        Returns:
            Decoded payload if valid refresh token, None otherwise.
        """
        payload = JWTService.verify_token(token)
        if payload and payload.get("type") == JWTService.TOKEN_TYPE_REFRESH:
            return payload
        return None

    @staticmethod
    def get_token_expiry_seconds() -> int:
        """Get the access token expiry time in seconds."""
        return settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60


# Global instance
jwt_service = JWTService()
