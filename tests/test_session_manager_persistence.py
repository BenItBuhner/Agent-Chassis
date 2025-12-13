import pytest

from app.core.config import settings
from app.services.session_manager import session_manager


class FakeRedis:
    def __init__(self):
        self.store: dict[str, dict] = {}
        self._connected = True

    @property
    def is_available(self) -> bool:
        return self._connected

    async def get_session(self, session_id: str):
        return self.store.get(session_id)

    async def set_session(self, session_id: str, data: dict, ttl: int | None = None):
        self.store[session_id] = data
        return True

    async def delete_session(self, session_id: str):
        self.store.pop(session_id, None)
        return True

    async def refresh_ttl(self, session_id: str, ttl: int | None = None):
        return True

    async def exists(self, session_id: str) -> bool:
        return session_id in self.store


class FakeConversation:
    def __init__(self, data: dict):
        self.data = data

    def to_dict(self):
        return self.data


class FakeDB:
    def __init__(self):
        self.store: dict[str, dict] = {}
        self.is_available = True

    async def get_conversation(self, session_id: str):
        if session_id in self.store:
            return FakeConversation(self.store[session_id])
        return None

    async def create_conversation(
        self,
        session_id: str,
        messages,
        system_prompt=None,
        model=None,
        metadata=None,
        owner_id=None,
    ):
        self.store[session_id] = {
            "id": session_id,
            "messages": messages,
            "system_prompt": system_prompt,
            "model": model,
            "message_count": len(messages),
            "metadata": metadata or {},
            "owner_id": owner_id,
            "is_public": False,
            "access_whitelist": [],
            "access_blacklist": [],
            "created_at": "t0",
            "updated_at": "t0",
        }
        return True

    async def upsert_conversation(self, session_id, messages, system_prompt=None, model=None, metadata=None):
        existing = self.store.get(session_id, {}).copy()
        if not existing:
            await self.create_conversation(session_id, messages, system_prompt, model, metadata)
            return True

        existing["messages"] = messages
        existing["message_count"] = len(messages)
        if system_prompt is not None:
            existing["system_prompt"] = system_prompt
        if model is not None:
            existing["model"] = model
        if metadata is not None:
            existing["metadata"] = metadata
        self.store[session_id] = existing
        return True

    async def delete_conversation(self, session_id: str):
        self.store.pop(session_id, None)
        return True


@pytest.mark.asyncio
async def test_save_session_preserves_metadata_and_access(monkeypatch):
    fake_redis = FakeRedis()
    fake_db = FakeDB()

    # Enable persistence and swap dependencies
    monkeypatch.setattr(settings, "ENABLE_PERSISTENCE", True)
    monkeypatch.setattr(session_manager, "redis", fake_redis)
    monkeypatch.setattr(session_manager, "db", fake_db)

    session_id = "s1"
    messages = [{"role": "user", "content": "hi"}]
    metadata = {"tag": "one"}

    # First save (new session)
    await session_manager.save_session(
        session_id=session_id,
        messages=messages,
        system_prompt="sys",
        model="m",
        metadata=metadata,
        user_ctx=None,
        is_new_session=True,
    )

    stored = fake_redis.store[session_id]
    assert stored["metadata"] == metadata
    assert stored["owner_id"] is None
    assert stored["is_public"] is False
    assert stored["access_whitelist"] == []
    assert stored["access_blacklist"] == []

    # Second save (update) without providing metadata; should preserve old metadata/access
    messages2 = messages + [{"role": "assistant", "content": "hello"}]
    await session_manager.save_session(
        session_id=session_id,
        messages=messages2,
        system_prompt=None,
        model=None,
        metadata=None,
        user_ctx=None,
        is_new_session=False,
    )

    stored2 = fake_redis.store[session_id]
    assert stored2["metadata"] == metadata  # preserved
    assert stored2["message_count"] == len(messages2)
    assert stored2["is_public"] is False
    assert stored2["access_whitelist"] == []
    assert stored2["access_blacklist"] == []

    # DB should also retain metadata after upsert
    assert fake_db.store[session_id]["metadata"] == metadata
