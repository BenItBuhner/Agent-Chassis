"""
Security utilities for API authentication and user identity tracking.

Supports multiple authentication methods (OSP-14):
1. JWT Bearer token (when ENABLE_USER_AUTH is enabled)
2. API Key authentication (when CHASSIS_API_KEY is set)
3. User identity via X-User-ID header (legacy/dev mode)

Authentication priority:
1. JWT Bearer token (if present and valid)
2. API Key + X-User-ID (if API key matches)
3. X-User-ID only (if auth disabled)
"""

import hashlib
from dataclasses import dataclass

from fastapi import Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

# Define header schemes
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
user_id_header = APIKeyHeader(name="X-User-ID", auto_error=False)


@dataclass
class UserContext:
    """
    Represents the current user's identity and authentication state.

    Attributes:
        user_id: Unique identifier for the user
        auth_enabled: Whether any authentication is enabled
        is_authenticated: Whether the user provided valid credentials
        auth_method: How the user was authenticated (jwt, api_key, header, none)
        email: User's email (only set for JWT auth)
        is_admin: Whether user has admin privileges (only set for JWT auth)
    """

    user_id: str | None
    auth_enabled: bool
    is_authenticated: bool
    auth_method: str = "none"  # jwt, api_key, header, none
    email: str | None = None
    is_admin: bool = False

    @property
    def can_own_sessions(self) -> bool:
        """Check if this user context can own sessions (requires auth + user_id)."""
        return self.auth_enabled and self.user_id is not None

    @property
    def is_jwt_authenticated(self) -> bool:
        """Check if user is authenticated via JWT."""
        return self.auth_method == "jwt"


def _hash_api_key(api_key: str) -> str:
    """
    Create a deterministic user ID from an API key.

    Uses SHA-256 to create a stable identifier without storing the actual key.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()[:32]


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Extract Bearer token from Authorization header."""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def get_api_key(
    api_key: str | None = Security(api_key_header),
) -> str | None:
    """
    Validates the API Key provided in the header.
    If CHASSIS_API_KEY is set in environment, it enforces validation.
    If not set, it allows open access (for dev/testing).

    Returns:
        The validated API key if authentication passed, None if auth disabled.

    Raises:
        HTTPException: 403 if authentication required but key invalid/missing.
    """
    expected_key = settings.CHASSIS_API_KEY

    if expected_key:
        if api_key == expected_key:
            return api_key
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    # If no key is configured on the server, we allow access
    return None


async def get_current_user(
    api_key: str | None = Security(api_key_header),
    user_id: str | None = Security(user_id_header),
    authorization: str | None = Header(None),
) -> UserContext:
    """
    Extract and validate the current user's identity.

    Authentication priority:
    1. JWT Bearer token (if ENABLE_USER_AUTH and token present)
    2. API Key (if CHASSIS_API_KEY set and key matches)
    3. X-User-ID header (if auth disabled)

    Returns:
        UserContext with user identity and authentication state.

    Raises:
        HTTPException: 401/403 if authentication required but credentials invalid.
    """
    # Check if any auth is enabled
    api_key_auth_enabled = settings.CHASSIS_API_KEY is not None
    jwt_auth_enabled = settings.ENABLE_USER_AUTH and settings.JWT_SECRET_KEY is not None
    auth_enabled = api_key_auth_enabled or jwt_auth_enabled

    # PRIORITY 1: JWT Bearer token (if user auth enabled)
    if jwt_auth_enabled:
        bearer_token = _extract_bearer_token(authorization)
        if bearer_token:
            # Import here to avoid circular imports
            from app.services.jwt_service import jwt_service

            payload = jwt_service.verify_access_token(bearer_token)
            if payload:
                return UserContext(
                    user_id=payload.get("sub"),
                    auth_enabled=True,
                    is_authenticated=True,
                    auth_method="jwt",
                    email=payload.get("email"),
                    is_admin=payload.get("is_admin", False),
                )
            # Invalid JWT - if JWT auth is required, fail
            # But if API key auth is also available, continue to check that
            if not api_key_auth_enabled:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired access token",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    # PRIORITY 2: API Key authentication
    if api_key_auth_enabled:
        if api_key == settings.CHASSIS_API_KEY:
            # API key valid - determine user ID
            resolved_user_id = user_id if user_id else _hash_api_key(api_key)
            return UserContext(
                user_id=resolved_user_id,
                auth_enabled=True,
                is_authenticated=True,
                auth_method="api_key",
            )
        # API key invalid - fail if this is the only auth method
        # (if JWT auth was tried and failed above, we already returned/raised)
        if not jwt_auth_enabled or not _extract_bearer_token(authorization):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Could not validate credentials",
            )

    # PRIORITY 3: No auth required - use X-User-ID header if provided
    if not auth_enabled:
        return UserContext(
            user_id=user_id,  # May be None
            auth_enabled=False,
            is_authenticated=False,
            auth_method="header" if user_id else "none",
        )

    # If we reach here, auth is enabled but no valid credentials provided
    if jwt_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Could not validate credentials",
    )


async def require_authenticated_user(
    user_ctx: UserContext = Security(get_current_user),
) -> UserContext:
    """
    Dependency that requires an authenticated user.

    Use this for endpoints that must have a valid user.

    Raises:
        HTTPException: 401 if not authenticated.
    """
    if not user_ctx.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user_ctx


async def require_admin_user(
    user_ctx: UserContext = Security(get_current_user),
) -> UserContext:
    """
    Dependency that requires an admin user.

    Use this for admin-only endpoints.

    Raises:
        HTTPException: 401 if not authenticated.
        HTTPException: 403 if not admin.
    """
    if not user_ctx.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    if not user_ctx.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user_ctx
