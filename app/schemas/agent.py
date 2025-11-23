from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union

class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None

class CompletionRequest(BaseModel):
    messages: List[ChatMessage]
    system_prompt: Optional[str] = None
    model: Optional[str] = "kimi-k2-thinking"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    allowed_tools: Optional[List[str]] = None  # If None, all tools are allowed. If empty list, no tools.

class CompletionResponse(BaseModel):
    role: str
    content: Optional[str]
    tool_calls: Optional[List[Dict[str, Any]]] = None
