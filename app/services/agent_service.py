"""
Agent service for executing LLM agent loops with tool calling.

Supports two operational modes:
1. Client-side: Messages passed in request (backward compatible)
2. Server-side: Session-based persistence with Redis/PostgreSQL

Includes ownership-based access control (OSP-12) for server-side sessions.
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import HTTPException
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.security import UserContext
from app.schemas.agent import ChatMessage, CompletionRequest
from app.services.local_tools import local_registry
from app.services.mcp_manager import mcp_manager
from app.services.session_manager import session_manager
from app.services.tool_translator import ToolTranslator

logger = logging.getLogger("agent_chassis.agent")


class AgentService:
    """
    Orchestrates the agent execution loop with tool calling capabilities.

    Handles:
    - Tool discovery (MCP + Local)
    - Multi-turn conversations with tool execution
    - Streaming and non-streaming responses
    - Session persistence (when enabled)
    """

    def __init__(self, client: AsyncOpenAI):
        self.client = client
        # Ensure the client has a generous timeout for "thinking" models
        self.client.timeout = 600.0

    async def _get_tools(self, request: CompletionRequest) -> tuple[list[dict[str, Any]], list[Any], dict[str, Any]]:
        """Gather and filter tools for the request."""
        # 1. Gather Tools (MCP + Local)
        mcp_tools_list = await mcp_manager.list_tools()
        openai_tools = ToolTranslator.convert_all(mcp_tools_list)

        local_tools_map = local_registry.get_tools()
        for _name, func in local_tools_map.items():
            openai_tools.append(ToolTranslator.function_to_openai(func))

        # Filter Tools if allowed_tools is specified
        if request.allowed_tools is not None:
            allowed_set = set(request.allowed_tools)
            openai_tools = [t for t in openai_tools if t["function"]["name"] in allowed_set]

        return openai_tools, mcp_tools_list, local_tools_map

    async def _prepare_messages(
        self,
        request: CompletionRequest,
        user_ctx: UserContext | None = None,
    ) -> tuple[str | None, list[dict[str, Any]], bool]:
        """
        Prepare messages for the agent loop based on request mode.

        Returns:
            Tuple of (session_id, messages, is_new_session) where:
            - session_id is None for client-side mode
            - is_new_session is True if a new session was created
        """
        is_new_session = False

        if request.is_server_side_mode:
            # Reject server-side mode when persistence is disabled to avoid handing out fake session IDs
            if not session_manager.persistence_enabled:
                raise HTTPException(
                    status_code=400,
                    detail="Server-side sessions require persistence. Enable persistence or send full messages instead.",
                )
            # Check if this will be a new session
            is_new_session = request.session_id is None

            # Server-side mode: Load from session manager with access control
            session_id, messages = await session_manager.get_or_create_session(
                session_id=request.session_id,
                messages=None,  # Don't use client messages in server mode
                user_ctx=user_ctx,
            )

            # Add new message if provided
            if request.message:
                messages.append({"role": "user", "content": request.message})
        else:
            # Client-side mode: Use provided messages directly
            session_id = None
            messages = [m.model_dump(exclude_none=True) for m in request.messages]  # type: ignore[union-attr]

        # Add system prompt if provided
        if request.system_prompt:
            # Check if system prompt already exists
            has_system = any(m.get("role") == "system" for m in messages)
            if not has_system:
                messages.insert(0, {"role": "system", "content": request.system_prompt})

        return session_id, messages, is_new_session

    async def _save_session(
        self,
        session_id: str | None,
        messages: list[dict[str, Any]],
        request: CompletionRequest,
        user_ctx: UserContext | None = None,
        is_new_session: bool = False,
    ) -> None:
        """Save session if using server-side persistence."""
        if session_id:
            await session_manager.save_session(
                session_id=session_id,
                messages=messages,
                system_prompt=request.system_prompt,
                model=request.model,
                metadata=request.metadata,
                user_ctx=user_ctx,
                is_new_session=is_new_session,
            )

    async def run_agent(
        self,
        request: CompletionRequest,
        user_ctx: UserContext | None = None,
    ) -> tuple[ChatMessage, str | None]:
        """
        Execute the agent loop synchronously (non-streaming).

        Args:
            request: The completion request.
            user_ctx: Current user context for access control.

        Returns:
            Tuple of (final_message, session_id) where session_id is None for client-side mode.
        """
        session_id, messages, is_new_session = await self._prepare_messages(request, user_ctx)

        model = request.model or settings.OPENAI_MODEL
        openai_tools, mcp_tools_list, local_tools_map = await self._get_tools(request)

        for _ in range(5):  # Max steps
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=openai_tools if openai_tools else None,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    stream=False,
                    timeout=600.0,
                )
            except Exception as e:
                logger.error("OpenAI API Error: %s", e)
                raise HTTPException(status_code=500, detail="Agent execution failed") from e

            message = response.choices[0].message
            messages.append(message.model_dump(exclude_none=True))

            if not message.tool_calls:
                # Save session before returning (owner is set on first save)
                await self._save_session(session_id, messages, request, user_ctx, is_new_session)
                return (ChatMessage(role=message.role, content=message.content), session_id)

            # Execute Tools
            for tool_call in message.tool_calls:
                if request.allowed_tools is not None and tool_call.function.name not in request.allowed_tools:
                    result_content = f"Error: Tool '{tool_call.function.name}' is not allowed in this context."
                else:
                    result_content = await self._execute_tool(tool_call, mcp_tools_list, local_tools_map)

                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result_content})

        # Save session even on max steps
        await self._save_session(session_id, messages, request, user_ctx, is_new_session)
        return (ChatMessage(role="assistant", content="Max execution steps reached."), session_id)

    async def run_agent_stream(
        self,
        request: CompletionRequest,
        user_ctx: UserContext | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Execute the agent loop with streaming responses.

        Args:
            request: The completion request.
            user_ctx: Current user context for access control.

        Yields JSON strings representing partial updates or internal events.
        Final yield includes session_id for server-side mode.
        """
        session_id, messages, is_new_session = await self._prepare_messages(request, user_ctx)

        model = request.model or settings.OPENAI_MODEL
        openai_tools, mcp_tools_list, local_tools_map = await self._get_tools(request)

        for _step in range(5):
            try:
                stream = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=openai_tools if openai_tools else None,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    stream=True,
                    timeout=600.0,
                )
            except Exception as e:
                yield json.dumps({"error": f"OpenAI API Error: {str(e)}"}) + "\n"
                return

            tool_calls_accum: dict[int, dict] = {}
            content_accum = ""
            role = "assistant"

            try:
                async for chunk in stream:
                    delta = chunk.choices[0].delta

                    # Check for reasoning content (DeepSeek/Kimi/etc)
                    if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                        yield (
                            json.dumps({"role": "assistant", "content": delta.reasoning_content, "type": "reasoning"})
                            + "\n"
                        )

                    if delta.role:
                        role = delta.role

                    if delta.content:
                        content_accum += delta.content
                        yield json.dumps({"role": role, "content": delta.content, "type": "content"}) + "\n"

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls_accum:
                                tool_calls_accum[idx] = {
                                    "id": "",
                                    "function": {"name": "", "arguments": ""},
                                    "type": "function",
                                }

                            if tc.id:
                                tool_calls_accum[idx]["id"] += tc.id
                            if tc.function.name:
                                tool_calls_accum[idx]["function"]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_accum[idx]["function"]["arguments"] += tc.function.arguments
            except Exception as e:
                yield json.dumps({"error": f"Stream iteration error: {str(e)}"}) + "\n"
                return

            # Reconstruct message for history
            message_data = {"role": role, "content": content_accum}
            if tool_calls_accum:
                message_data["tool_calls"] = [v for k, v in sorted(tool_calls_accum.items())]

            messages.append(message_data)

            if not tool_calls_accum:
                # Save session and finish (owner is set on first save)
                await self._save_session(session_id, messages, request, user_ctx, is_new_session)
                yield json.dumps({"type": "finish", "content": "", "session_id": session_id}) + "\n"
                return

            yield json.dumps({"type": "status", "content": "Executing tools..."}) + "\n"

            # Execute Tools
            for _idx, tool_data in sorted(tool_calls_accum.items()):
                tool_name = tool_data["function"]["name"]
                tool_args = tool_data["function"]["arguments"]
                tool_id = tool_data["id"]

                if request.allowed_tools is not None and tool_name not in request.allowed_tools:
                    result_content = f"Error: Tool '{tool_name}' is not allowed in this context."
                else:
                    result_content = await self._execute_tool_from_data(
                        tool_name, tool_args, mcp_tools_list, local_tools_map
                    )

                messages.append({"role": "tool", "tool_call_id": tool_id, "content": result_content})
                yield json.dumps({"type": "tool_result", "tool": tool_name, "result": result_content}) + "\n"

        # Save session even on max steps
        await self._save_session(session_id, messages, request, user_ctx, is_new_session)
        yield json.dumps({"type": "error", "content": "Max execution steps reached.", "session_id": session_id}) + "\n"

    async def _execute_tool(self, tool_call, mcp_tools_list, local_tools_map) -> str:
        """Helper for the object-based tool call (non-stream)"""
        return await self._execute_tool_from_data(
            tool_call.function.name, tool_call.function.arguments, mcp_tools_list, local_tools_map
        )

    async def _execute_tool_from_data(self, tool_name: str, tool_args_str: str, mcp_tools_list, local_tools_map) -> str:
        """Unified execution logic"""
        try:
            args = json.loads(tool_args_str)
        except json.JSONDecodeError:
            return "Error: Invalid JSON arguments"

        if tool_name in local_tools_map:
            try:
                func = local_tools_map[tool_name]
                if asyncio.iscoroutinefunction(func):
                    result = await func(**args)
                else:
                    result = func(**args)
                return str(result)
            except Exception as e:
                return f"Error executing local tool: {str(e)}"

        target_server = None
        for item in mcp_tools_list:
            if item["tool"].name == tool_name:
                target_server = item["server"]
                break

        if target_server:
            try:
                result = await mcp_manager.call_tool(target_server, tool_name, args)
                return str(result)
            except Exception as e:
                return f"Error executing MCP tool: {str(e)}"

        return "Error: Tool not found."
