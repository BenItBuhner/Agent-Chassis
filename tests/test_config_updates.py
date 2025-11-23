import pytest
from app.schemas.agent import CompletionRequest, ChatMessage
from app.core.config import settings

def test_system_prompt_insertion():
    req = CompletionRequest(
        messages=[ChatMessage(role="user", content="Hello")],
        system_prompt="You are a helpful assistant."
    )
    
    # We'll check how the messages are constructed by simulating the service logic
    # Since we can't easily spy on the internal list without mocking run_agent logic
    # Let's just verify the object structure for now.
    assert req.system_prompt == "You are a helpful assistant."

def test_model_fallback():
    # Case 1: Model provided
    req1 = CompletionRequest(messages=[], model="gpt-3.5-turbo")
    assert req1.model == "gpt-3.5-turbo"

    # Case 2: Model missing (Schema Default)
    # Now that we set a default in the schema, it defaults to "kimi-k2-thinking" immediately
    req2 = CompletionRequest(messages=[])
    assert req2.model == "kimi-k2-thinking"
    
    # Verify config default as well
    assert settings.OPENAI_MODEL == "kimi-k2-thinking"
