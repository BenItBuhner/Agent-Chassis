"""
Authentication service for user account management.

Handles:
- User registration with email verification
- Login with email/password (with brute force protection)
- Google OAuth authentication
- Password reset
- Token refresh

Part of OSP-14 implementation.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from app.core.config import settings
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.services.email_service import email_service
from app.services.jwt_service import jwt_service

logger = logging.getLogger("agent_chassis.auth")

# Conditional imports for password hashing
try:
    import bcrypt

    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    bcrypt = None  # type: ignore

try:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GOOGLE_AUTH_AVAILABLE = False


class AuthService:
    """
    Service for user authentication and account management.

    Uses Redis for verification code storage and rate limiting.
    Uses PostgreSQL for user data persistence.

    Security features:
    - Login brute force protection (configurable attempts/window)
    - Email verification rate limiting
    - Password reset rate limiting
    """

    # Redis key prefixes
    VERIFY_CODE_KEY = "auth:verify:{email}"
    RESET_CODE_KEY = "auth:reset:{email}"
    RATE_LIMIT_KEY = "auth:rate:{email}:{action}"
    LOGIN_ATTEMPTS_KEY = "auth:login_attempts:{email}"

    def __init__(self):
        # Lazy imports to avoid circular dependencies
        self._redis = None
        self._db = None

    @property
    def redis(self):
        """Get Redis cache instance."""
        if self._redis is None:
            from app.services.redis_cache import redis_cache

            self._redis = redis_cache
        return self._redis

    @property
    def db(self):
        """Get database instance."""
        if self._db is None:
            from app.services.database import database

            self._db = database
        return self._db

    # =========================================================================
    # Password Hashing
    # =========================================================================

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt."""
        if not BCRYPT_AVAILABLE:
            raise RuntimeError("bcrypt not installed. Run: pip install bcrypt")
        # bcrypt requires bytes
        password_bytes = password.encode("utf-8")
        # Generate salt and hash (cost factor 12 for security)
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode("utf-8")

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        if not BCRYPT_AVAILABLE:
            raise RuntimeError("bcrypt not installed. Run: pip install bcrypt")
        try:
            password_bytes = plain_password.encode("utf-8")
            hashed_bytes = hashed_password.encode("utf-8")
            return bcrypt.checkpw(password_bytes, hashed_bytes)
        except Exception:
            return False

    # =========================================================================
    # Registration
    # =========================================================================

    async def register(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> User:
        """
        Register a new user account.

        Args:
            email: User's email address.
            password: Plain text password.
            display_name: Optional display name.

        Returns:
            Created User object.

        Raises:
            HTTPException: 400 if email already registered.
            HTTPException: 503 if database not available.
        """
        if not self.db.is_available:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available",
            )

        # Check if email already exists
        existing_user = await self._get_user_by_email(email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        # Create user
        password_hash = self.hash_password(password)
        user = await self._create_user(
            email=email,
            password_hash=password_hash,
            display_name=display_name,
        )

        # Generate and send verification code
        code = email_service.generate_verification_code()
        await self._store_verification_code(email, code)
        await email_service.send_verification_email(email, code)

        return user

    async def verify_email(self, email: str, code: str) -> bool:
        """
        Verify a user's email address.

        Args:
            email: User's email address.
            code: 6-digit verification code.

        Returns:
            True if verification successful.

        Raises:
            HTTPException: 400 if code invalid or expired.
            HTTPException: 404 if user not found.
        """
        # Verify code
        is_valid = await self._verify_code(email, code, self.VERIFY_CODE_KEY.format(email=email))
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification code",
            )

        # Update user
        user = await self._get_user_by_email(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        await self._update_user(user.id, email_verified=True)

        # Clear verification code
        await self._delete_code(self.VERIFY_CODE_KEY.format(email=email))

        return True

    async def resend_verification(self, email: str) -> bool:
        """
        Resend verification email.

        Args:
            email: User's email address.

        Returns:
            True if email sent.

        Raises:
            HTTPException: 404 if user not found.
            HTTPException: 400 if already verified.
            HTTPException: 429 if rate limited.
        """
        user = await self._get_user_by_email(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        if user.email_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already verified",
            )

        # Check rate limit
        if not await self._check_rate_limit(email, "verify"):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Please wait {settings.VERIFICATION_RATE_LIMIT_SECONDS} seconds before requesting another code",
            )

        # Generate and send new code
        code = email_service.generate_verification_code()
        await self._store_verification_code(email, code)
        await email_service.send_verification_email(email, code)

        return True

    # =========================================================================
    # Login
    # =========================================================================

    async def login(self, email: str, password: str) -> TokenResponse:
        """
        Login with email and password with brute force protection.

        Args:
            email: User's email address.
            password: Plain text password.

        Returns:
            TokenResponse with access and refresh tokens.

        Raises:
            HTTPException: 401 if credentials invalid.
            HTTPException: 403 if email not verified.
            HTTPException: 403 if account disabled.
            HTTPException: 429 if too many failed attempts.
        """
        # Check for brute force attack BEFORE checking credentials
        is_locked, remaining_seconds = await self._check_login_lockout(email)
        if is_locked:
            logger.warning("Login blocked for %s - too many failed attempts", email)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts. Try again in {remaining_seconds} seconds.",
                headers={"Retry-After": str(remaining_seconds)},
            )

        user = await self._get_user_by_email(email)

        if not user or not user.password_hash:
            # Record failed attempt even for non-existent users (prevents enumeration)
            await self._record_failed_login(email)
            logger.info("Login failed for %s - user not found or no password", email)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        if not self.verify_password(password, user.password_hash):
            await self._record_failed_login(email)
            logger.info("Login failed for %s - invalid password", email)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        # Password correct - clear failed attempts
        await self._clear_failed_logins(email)

        if not user.email_verified:
            logger.info("Login blocked for %s - email not verified", email)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email not verified. Please check your inbox for the verification code.",
            )

        if not user.is_active:
            logger.warning("Login blocked for %s - account disabled", email)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled",
            )

        # Update last login
        await self._update_user(user.id, last_login_at=datetime.now(UTC))

        logger.info("Successful login for user %s", user.id)
        # Generate tokens
        return self._create_token_response(user.id, user.email)

    async def _check_login_lockout(self, email: str) -> tuple[bool, int]:
        """
        Check if login is locked out due to too many failed attempts.

        Returns:
            Tuple of (is_locked, remaining_seconds).
        """
        if not self.redis.is_available:
            return (False, 0)

        key = self.LOGIN_ATTEMPTS_KEY.format(email=email.lower())
        try:
            raw_data = await self.redis.client.get(key)
            if not raw_data:
                return (False, 0)

            data = json.loads(raw_data)
            attempts = data.get("attempts", 0)

            if attempts >= settings.LOGIN_RATE_LIMIT_ATTEMPTS:
                # Check remaining time
                ttl = await self.redis.client.ttl(key)
                return (True, max(0, ttl))

            return (False, 0)
        except Exception as e:
            logger.error("Redis error checking login lockout: %s", e)
            return (False, 0)

    async def _record_failed_login(self, email: str) -> None:
        """Record a failed login attempt."""
        if not self.redis.is_available:
            return

        key = self.LOGIN_ATTEMPTS_KEY.format(email=email.lower())
        try:
            raw_data = await self.redis.client.get(key)
            if raw_data:
                data = json.loads(raw_data)
                data["attempts"] = data.get("attempts", 0) + 1
            else:
                data = {"attempts": 1, "first_attempt": datetime.now(UTC).isoformat()}

            await self.redis.client.setex(
                key,
                settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
                json.dumps(data),
            )

            if data["attempts"] >= settings.LOGIN_RATE_LIMIT_ATTEMPTS:
                logger.warning(
                    "Login rate limit reached for %s - %d attempts",
                    email,
                    data["attempts"],
                )
        except Exception as e:
            logger.error("Redis error recording failed login: %s", e)

    async def _clear_failed_logins(self, email: str) -> None:
        """Clear failed login attempts after successful login."""
        if not self.redis.is_available:
            return

        key = self.LOGIN_ATTEMPTS_KEY.format(email=email.lower())
        try:
            await self.redis.client.delete(key)
        except Exception as e:
            logger.error("Redis error clearing failed logins: %s", e)

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """
        Refresh an access token.

        Args:
            refresh_token: Valid refresh token.

        Returns:
            New TokenResponse with fresh tokens.

        Raises:
            HTTPException: 401 if refresh token invalid.
        """
        payload = jwt_service.verify_refresh_token(refresh_token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )

        user_id = payload.get("sub")
        user = await self._get_user_by_id(user_id)

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or disabled",
            )

        return self._create_token_response(user.id, user.email)

    # =========================================================================
    # Google OAuth
    # =========================================================================

    async def google_auth(self, id_token: str) -> TokenResponse:
        """
        Authenticate or register via Google OAuth.

        Args:
            id_token: Google ID token from client-side sign-in.

        Returns:
            TokenResponse with access and refresh tokens.

        Raises:
            HTTPException: 400 if token invalid.
            HTTPException: 503 if Google OAuth not configured.
        """
        if not GOOGLE_AUTH_AVAILABLE:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google authentication not available. Install google-auth package.",
            )

        if not settings.GOOGLE_CLIENT_ID:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google OAuth not configured",
            )

        try:
            # Verify Google ID token
            idinfo = google_id_token.verify_oauth2_token(
                id_token,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
            )

            google_id = idinfo["sub"]
            email = idinfo.get("email")
            email_verified = idinfo.get("email_verified", False)
            name = idinfo.get("name")

            if not email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email not provided by Google",
                )

        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Google token: {str(e)}",
            ) from e

        # Check if user exists by Google ID
        user = await self._get_user_by_google_id(google_id)

        if user:
            # Existing Google user - update last login
            await self._update_user(user.id, last_login_at=datetime.now(UTC))
        else:
            # Check if email exists (user registered via email/password)
            user = await self._get_user_by_email(email)

            if user:
                # Link Google account to existing user
                await self._update_user(
                    user.id,
                    google_id=google_id,
                    email_verified=True,  # Google verifies email
                    last_login_at=datetime.now(UTC),
                )
            else:
                # Create new user
                user = await self._create_user(
                    email=email,
                    google_id=google_id,
                    email_verified=email_verified,
                    display_name=name,
                )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled",
            )

        return self._create_token_response(user.id, user.email)

    # =========================================================================
    # Password Reset
    # =========================================================================

    async def request_password_reset(self, email: str) -> bool:
        """
        Request a password reset.

        Args:
            email: User's email address.

        Returns:
            True (always, to prevent email enumeration).
        """
        user = await self._get_user_by_email(email)

        # Always return success to prevent email enumeration
        if not user or not user.password_hash:
            return True

        # Check rate limit
        if not await self._check_rate_limit(email, "reset"):
            return True  # Silent fail for rate limit

        # Generate and send reset code
        code = email_service.generate_verification_code()
        await self._store_reset_code(email, code)
        await email_service.send_password_reset_email(email, code)

        return True

    async def confirm_password_reset(self, email: str, code: str, new_password: str) -> bool:
        """
        Confirm password reset with code.

        Args:
            email: User's email address.
            code: 6-digit reset code.
            new_password: New password.

        Returns:
            True if reset successful.

        Raises:
            HTTPException: 400 if code invalid or expired.
            HTTPException: 404 if user not found.
        """
        # Verify code
        is_valid = await self._verify_code(email, code, self.RESET_CODE_KEY.format(email=email))
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset code",
            )

        user = await self._get_user_by_email(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Update password
        password_hash = self.hash_password(new_password)
        await self._update_user(user.id, password_hash=password_hash)

        # Clear reset code
        await self._delete_code(self.RESET_CODE_KEY.format(email=email))

        return True

    # =========================================================================
    # User Lookup
    # =========================================================================

    async def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by ID (public method for other services)."""
        return await self._get_user_by_id(user_id)

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _create_token_response(self, user_id: str, email: str) -> TokenResponse:
        """Create token response with access and refresh tokens."""
        access_token = jwt_service.create_access_token(user_id, email)
        refresh_token = jwt_service.create_refresh_token(user_id)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=jwt_service.get_token_expiry_seconds(),
        )

    async def _get_user_by_email(self, email: str) -> User | None:
        """Get user by email address."""
        if not self.db.is_available:
            return None

        try:
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import AsyncSession

            async with self.db.session_factory() as session:
                session: AsyncSession
                result = await session.execute(select(User).where(User.email == email.lower()))
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error("Database error getting user by email: %s", e)
            return None

    async def _get_user_by_id(self, user_id: str) -> User | None:
        """Get user by ID."""
        if not self.db.is_available:
            return None

        try:
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import AsyncSession

            async with self.db.session_factory() as session:
                session: AsyncSession
                result = await session.execute(select(User).where(User.id == user_id))
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error("Database error getting user by ID: %s", e)
            return None

    async def _get_user_by_google_id(self, google_id: str) -> User | None:
        """Get user by Google ID."""
        if not self.db.is_available:
            return None

        try:
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import AsyncSession

            async with self.db.session_factory() as session:
                session: AsyncSession
                result = await session.execute(select(User).where(User.google_id == google_id))
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error("Database error getting user by Google ID: %s", e)
            return None

    async def _create_user(
        self,
        email: str,
        password_hash: str | None = None,
        google_id: str | None = None,
        email_verified: bool = False,
        display_name: str | None = None,
    ) -> User:
        """Create a new user in the database."""
        try:
            from sqlalchemy.ext.asyncio import AsyncSession

            user = User(
                email=email.lower(),
                password_hash=password_hash,
                google_id=google_id,
                email_verified=email_verified,
                display_name=display_name,
            )

            async with self.db.session_factory() as session:
                session: AsyncSession
                session.add(user)
                await session.commit()
                await session.refresh(user)
                logger.info("Created new user: %s", user.id)
                return user
        except Exception:
            logger.exception("Database error creating user")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user",
            ) from None

    async def _update_user(self, user_id: str, **kwargs: Any) -> bool:
        """Update user fields."""
        try:
            from sqlalchemy import update
            from sqlalchemy.ext.asyncio import AsyncSession

            async with self.db.session_factory() as session:
                session: AsyncSession
                await session.execute(update(User).where(User.id == user_id).values(**kwargs))
                await session.commit()
                return True
        except Exception as e:
            logger.error("Database error updating user %s: %s", user_id, e)
            return False

    async def _store_verification_code(self, email: str, code: str) -> None:
        """Store verification code in Redis."""
        key = self.VERIFY_CODE_KEY.format(email=email.lower())
        data = {
            "code": code,
            "attempts": 0,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if self.redis.is_available:
            await self.redis.client.setex(
                key,
                settings.VERIFICATION_CODE_EXPIRE_MINUTES * 60,
                json.dumps(data),
            )

    async def _store_reset_code(self, email: str, code: str) -> None:
        """Store password reset code in Redis."""
        key = self.RESET_CODE_KEY.format(email=email.lower())
        data = {
            "code": code,
            "attempts": 0,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if self.redis.is_available:
            await self.redis.client.setex(
                key,
                settings.VERIFICATION_CODE_EXPIRE_MINUTES * 60,
                json.dumps(data),
            )

    async def _verify_code(self, email: str, code: str, key: str) -> bool:
        """Verify a code from Redis."""
        if not self.redis.is_available:
            return False

        try:
            raw_data = await self.redis.client.get(key)
            if not raw_data:
                return False

            data = json.loads(raw_data)
            attempts = data.get("attempts", 0)

            # Check max attempts
            if attempts >= settings.VERIFICATION_MAX_ATTEMPTS:
                await self._delete_code(key)
                return False

            # Increment attempts
            data["attempts"] = attempts + 1
            await self.redis.client.setex(
                key,
                settings.VERIFICATION_CODE_EXPIRE_MINUTES * 60,
                json.dumps(data),
            )

            return data.get("code") == code
        except Exception as e:
            logger.error("Redis error verifying code: %s", e)
            return False

    async def _delete_code(self, key: str) -> None:
        """Delete a code from Redis."""
        if self.redis.is_available:
            await self.redis.client.delete(key)

    async def _check_rate_limit(self, email: str, action: str) -> bool:
        """Check if action is rate limited."""
        if not self.redis.is_available:
            return True  # Allow if Redis not available

        key = self.RATE_LIMIT_KEY.format(email=email.lower(), action=action)
        try:
            exists = await self.redis.client.exists(key)
            if exists:
                return False

            # Set rate limit
            await self.redis.client.setex(
                key,
                settings.VERIFICATION_RATE_LIMIT_SECONDS,
                "1",
            )
            return True
        except Exception as e:
            logger.error("Redis error checking rate limit: %s", e)
            return True


# Global instance
auth_service = AuthService()
