from typing import Any

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class CompletionRequest(BaseModel):
    messages: list[ChatMessage]
    system_prompt: str | None = None
    model: str | None = "kimi-k2-thinking"
    temperature: float = 0.7
    max_tokens: int | None = 16000
    allowed_tools: list[str] | None = None  # If None, all tools are allowed. If empty list, no tools.
    stream: bool = False


class CompletionResponse(BaseModel):
    role: str
    content: str | None
    tool_calls: list[dict[str, Any]] | None = None
