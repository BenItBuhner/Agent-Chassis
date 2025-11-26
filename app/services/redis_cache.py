"""
Redis cache service for conversation session storage.

Provides fast, in-memory caching of conversation sessions with TTL-based expiration.
This is the primary storage layer for active sessions, with PostgreSQL as fallback.
"""

import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger("agent_chassis.redis")

# Conditional import - Redis is optional
try:
    import redis.asyncio as aioredis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None  # type: ignore[assignment]


class RedisCache:
    """
    Async Redis cache for conversation sessions.

    Features:
    - Connection pooling for high concurrency
    - TTL-based automatic expiration
    - JSON serialization for complex objects
    - Graceful degradation if Redis unavailable
    """

    # Redis key prefix for session data
    SESSION_PREFIX = "session:"

    def __init__(self):
        self.client: aioredis.Redis | None = None
        self._connected = False

    @property
    def is_available(self) -> bool:
        """Check if Redis is configured and connected."""
        return self._connected and self.client is not None

    async def connect(self) -> bool:
        """
        Establish connection to Redis.

        Returns:
            True if connection successful, False otherwise.
        """
        if not REDIS_AVAILABLE:
            logger.warning("redis package not installed - Redis caching disabled")
            return False

        if not settings.REDIS_URL:
            logger.warning("REDIS_URL not configured - Redis caching disabled")
            return False

        try:
            self.client = await aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=20,
            )
            # Test connection
            await self.client.ping()
            self._connected = True
            # Use sanitized URL for logging (masks password)
            logger.info("Connected to Redis at %s", settings.sanitize_url(settings.REDIS_URL))
            return True
        except Exception as e:
            logger.error("Failed to connect to Redis: %s", e)
            self.client = None
            self._connected = False
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self.client:
            await self.client.aclose()
            self._connected = False
            logger.info("Redis connection closed")

    def _session_key(self, session_id: str) -> str:
        """Generate Redis key for a session."""
        return f"{self.SESSION_PREFIX}{session_id}"

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """
        Retrieve session data from Redis cache.

        Args:
            session_id: Unique session identifier.

        Returns:
            Session data dict if found, None otherwise.
        """
        if not self.is_available:
            return None

        try:
            data = await self.client.get(self._session_key(session_id))  # type: ignore[union-attr]
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error("Redis get error for session %s: %s", session_id, e)
            return None

    async def set_session(
        self,
        session_id: str,
        data: dict[str, Any],
        ttl: int | None = None,
    ) -> bool:
        """
        Store session data in Redis cache.

        Args:
            session_id: Unique session identifier.
            data: Session data to store.
            ttl: Time-to-live in seconds (defaults to SESSION_TTL_SECONDS).

        Returns:
            True if successful, False otherwise.
        """
        if not self.is_available:
            return False

        try:
            ttl = ttl or settings.SESSION_TTL_SECONDS
            await self.client.setex(  # type: ignore[union-attr]
                self._session_key(session_id),
                ttl,
                json.dumps(data),
            )
            return True
        except Exception as e:
            logger.error("Redis set error for session %s: %s", session_id, e)
            return False

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete session from Redis cache.

        Args:
            session_id: Unique session identifier.

        Returns:
            True if deleted, False otherwise.
        """
        if not self.is_available:
            return False

        try:
            result = await self.client.delete(self._session_key(session_id))  # type: ignore[union-attr]
            return result > 0
        except Exception as e:
            logger.error("Redis delete error for session %s: %s", session_id, e)
            return False

    async def refresh_ttl(self, session_id: str, ttl: int | None = None) -> bool:
        """
        Refresh the TTL on an existing session.

        Args:
            session_id: Unique session identifier.
            ttl: New TTL in seconds (defaults to SESSION_TTL_SECONDS).

        Returns:
            True if successful, False otherwise.
        """
        if not self.is_available:
            return False

        try:
            ttl = ttl or settings.SESSION_TTL_SECONDS
            result = await self.client.expire(self._session_key(session_id), ttl)  # type: ignore[union-attr]
            return result
        except Exception as e:
            logger.error("Redis TTL refresh error for session %s: %s", session_id, e)
            return False

    async def exists(self, session_id: str) -> bool:
        """
        Check if session exists in cache.

        Args:
            session_id: Unique session identifier.

        Returns:
            True if session exists, False otherwise.
        """
        if not self.is_available:
            return False

        try:
            result = await self.client.exists(self._session_key(session_id))  # type: ignore[union-attr]
            return result > 0
        except Exception as e:
            logger.error("Redis exists error for session %s: %s", session_id, e)
            return False


# Global instance
redis_cache = RedisCache()
