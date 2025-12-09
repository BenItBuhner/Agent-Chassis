import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import config
from app.services.rate_limiter import RateLimiter, limiter, rate_limit_middleware
from app.services.redis_cache import redis_cache


class StubPipeline:
    def __init__(self, results):
        self.results = results

    def incr(self, _key):
        return self

    def expire(self, _key, _ttl):
        return self

    async def execute(self):
        return self.results


class StubRedis:
    def __init__(self, results):
        self._results = results

    def pipeline(self):
        return StubPipeline(self._results)


@pytest.fixture(autouse=True)
def reset_redis_state():
    """Ensure redis_cache is disconnected after each test."""
    original_client = redis_cache.client
    original_connected = redis_cache._connected
    try:
        redis_cache.client = None
        redis_cache._connected = False
        yield
    finally:
        redis_cache.client = original_client
        redis_cache._connected = original_connected


@pytest.mark.asyncio
async def test_rate_limiter_allows_within_limits():
    redis_cache.client = StubRedis([1, True, 1, True])
    redis_cache._connected = True

    rl = RateLimiter(window_seconds=60, global_limit=2, per_identity_limit=2, fail_closed=True)
    allowed = await rl.allow("user-1")
    assert allowed


@pytest.mark.asyncio
async def test_rate_limiter_blocks_on_global_limit():
    redis_cache.client = StubRedis([3, True, 1, True])  # global exceeds
    redis_cache._connected = True

    rl = RateLimiter(window_seconds=60, global_limit=2, per_identity_limit=5, fail_closed=True)
    allowed = await rl.allow("user-1")
    assert not allowed


@pytest.mark.asyncio
async def test_rate_limiter_blocks_on_identity_limit():
    redis_cache.client = StubRedis([1, True, 4, True])  # identity exceeds
    redis_cache._connected = True

    rl = RateLimiter(window_seconds=60, global_limit=5, per_identity_limit=3, fail_closed=True)
    allowed = await rl.allow("user-1")
    assert not allowed


@pytest.mark.asyncio
async def test_rate_limiter_fail_closed_when_storage_down():
    redis_cache.client = None
    redis_cache._connected = False

    rl = RateLimiter(window_seconds=60, global_limit=5, per_identity_limit=3, fail_closed=True)
    allowed = await rl.allow("user-1")
    assert not allowed


def test_rate_limit_middleware_returns_429_when_denied(monkeypatch):
    app = FastAPI()

    # Enable rate limiting for test
    monkeypatch.setattr(config.settings, "ENABLE_RATE_LIMITING", True)

    async def deny(_identity):
        return False

    monkeypatch.setattr(limiter, "allow", deny)
    monkeypatch.setattr(limiter, "retry_after", lambda: 5)

    app.middleware("http")(rate_limit_middleware)

    @app.get("/api/v1/ping")
    async def ping():
        return {"status": "ok"}

    client = TestClient(app)
    resp = client.get("/api/v1/ping")
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") == "5"
    assert resp.json()["detail"].startswith("Rate limit exceeded")


def test_rate_limit_middleware_passes_when_allowed(monkeypatch):
    app = FastAPI()
    monkeypatch.setattr(config.settings, "ENABLE_RATE_LIMITING", True)

    async def allow(_identity):
        return True

    monkeypatch.setattr(limiter, "allow", allow)
    monkeypatch.setattr(limiter, "retry_after", lambda: 1)

    app.middleware("http")(rate_limit_middleware)

    @app.get("/api/v1/ping")
    async def ping():
        return {"status": "ok"}

    client = TestClient(app)
    resp = client.get("/api/v1/ping")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
