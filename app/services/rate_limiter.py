import logging
import time
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.security import get_current_user
from app.services.redis_cache import redis_cache

logger = logging.getLogger("agent_chassis.rate_limit")


class RateLimiter:
    """
    Redis-backed fixed-window rate limiter.

    Identity: authenticated user_id when available, otherwise client IP string.
    Behavior: fail-closed (deny) if Redis is unavailable or errors occur.
    """

    def __init__(self, window_seconds: int, global_limit: int, per_identity_limit: int, fail_closed: bool = True):
        self.window_seconds = window_seconds
        self.global_limit = global_limit
        self.per_identity_limit = per_identity_limit
        self.fail_closed = fail_closed

    def _window_key(self, prefix: str, window_start: int, suffix: str | None = None) -> str:
        if suffix:
            return f"rate:{prefix}:{suffix}:{window_start}"
        return f"rate:{prefix}:{window_start}"

    async def allow(self, identity: str) -> bool:
        """
        Check and increment rate limits for the given identity.
        Returns True if within limits, False if exceeded or if storage errors when fail_closed is True.
        """
        if not redis_cache.is_available or not redis_cache.client:
            logger.error("Rate limiting storage unavailable")
            return not self.fail_closed

        now = int(time.time())
        window_start = (now // self.window_seconds) * self.window_seconds
        ttl = self.window_seconds + 1

        global_key = self._window_key("global", window_start)
        identity_key = self._window_key("user", window_start, identity)

        try:
            pipe = redis_cache.client.pipeline()
            pipe.incr(global_key)
            pipe.expire(global_key, ttl)
            pipe.incr(identity_key)
            pipe.expire(identity_key, ttl)
            results: list[Any] = await pipe.execute()

            global_count = results[0]
            identity_count = results[2]

            if global_count > self.global_limit:
                return False
            if identity_count > self.per_identity_limit:
                return False
            return True
        except Exception as e:  # pragma: no cover - defensive
            logger.error("Rate limit check failed: %s", e)
            return not self.fail_closed

    def retry_after(self) -> int:
        """Seconds until the current window ends."""
        remaining = self.window_seconds - (int(time.time()) % self.window_seconds)
        return remaining if remaining > 0 else self.window_seconds


limiter = RateLimiter(
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    global_limit=settings.RATE_LIMIT_GLOBAL_PER_MINUTE,
    per_identity_limit=settings.RATE_LIMIT_PER_USER_PER_MINUTE,
    fail_closed=True,
)


async def rate_limit_middleware(request: Request, call_next):
    """
    FastAPI middleware applying global + per-identity rate limiting to all API v1 routes.
    Counts streaming requests once at initiation.
    """
    # Skip when disabled or path outside API prefix
    if not settings.ENABLE_RATE_LIMITING or not request.url.path.startswith(settings.API_V1_STR):
        return await call_next(request)

    # Determine identity: prefer authenticated user_id, else client IP
    identity = request.client.host if request.client else "unknown"
    try:
        user_ctx = await get_current_user(
            api_key=request.headers.get("X-API-Key"),
            user_id=request.headers.get("X-User-ID"),
            authorization=request.headers.get("Authorization"),
        )
        if user_ctx.user_id:
            identity = user_ctx.user_id
    except HTTPException:
        # Preserve auth errors; rate limit still applies to IP identity
        pass

    allowed = await limiter.allow(identity)
    if not allowed:
        retry_after = limiter.retry_after()
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please retry later."},
            headers={"Retry-After": str(retry_after)},
        )

    return await call_next(request)
