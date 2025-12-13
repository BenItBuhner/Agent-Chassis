import pytest

from app.services.mcp_manager import mcp_manager


class DummyStorage:
    def __init__(self, tokens=None):
        self._tokens = tokens

    async def get_tokens(self):
        return self._tokens


@pytest.mark.asyncio
async def test_oauth_guard_raises_when_tokens_missing(monkeypatch):
    # Force OAuth path active
    monkeypatch.setattr("app.services.mcp_manager.OAUTH_AVAILABLE", True)

    # Provide dummy storage with no tokens
    dummy_storage = DummyStorage(tokens=None)
    monkeypatch.setattr(mcp_manager, "_get_or_create_oauth_storage", lambda name: dummy_storage)

    # Avoid actual network call by short-circuiting streamablehttp_client (should not be reached)
    called = {"stream": False}

    async def fake_streamablehttp_client(*args, **kwargs):
        called["stream"] = True
        raise AssertionError("streamablehttp_client should not be called when tokens are missing")

    monkeypatch.setattr("app.services.mcp_manager.streamablehttp_client", fake_streamablehttp_client)

    with pytest.raises(RuntimeError) as exc:
        await mcp_manager._connect_streamable_http_server(
            "example",
            {
                "url": "https://example.com/mcp",
                "oauth": {"client_name": "Example"},
            },
        )

    assert "tokens" in str(exc.value)
    assert called["stream"] is False
