import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import HTTPException
from openai import AsyncOpenAI

from app.core.config import settings
from app.schemas.agent import ChatMessage, CompletionRequest
from app.services.local_tools import local_registry
from app.services.mcp_manager import mcp_manager
from app.services.tool_translator import ToolTranslator


class AgentService:
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

    async def run_agent(self, request: CompletionRequest) -> ChatMessage:
        """
        Execute the agent loop synchronously (non-streaming).
        Returns the final assistant message.
        """
        messages = [m.model_dump(exclude_none=True) for m in request.messages]
        if request.system_prompt:
            messages.insert(0, {"role": "system", "content": request.system_prompt})

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
                print(f"OpenAI API Error: {e}")
                raise HTTPException(status_code=500, detail=f"OpenAI API Error: {str(e)}") from e

            message = response.choices[0].message
            messages.append(message.model_dump(exclude_none=True))

            if not message.tool_calls:
                return ChatMessage(role=message.role, content=message.content)

            # Execute Tools
            for tool_call in message.tool_calls:
                if request.allowed_tools is not None and tool_call.function.name not in request.allowed_tools:
                    result_content = f"Error: Tool '{tool_call.function.name}' is not allowed in this context."
                else:
                    result_content = await self._execute_tool(tool_call, mcp_tools_list, local_tools_map)

                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result_content})

        return ChatMessage(role="assistant", content="Max execution steps reached.")

    async def run_agent_stream(self, request: CompletionRequest) -> AsyncGenerator[str, None]:
        """
        Execute the agent loop with streaming responses.
        Yields JSON strings representing partial updates or internal events.
        """
        messages = [m.model_dump(exclude_none=True) for m in request.messages]
        if request.system_prompt:
            messages.insert(0, {"role": "system", "content": request.system_prompt})

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
                yield json.dumps({"type": "finish", "content": ""}) + "\n"
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

        yield json.dumps({"type": "error", "content": "Max execution steps reached."}) + "\n"

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
