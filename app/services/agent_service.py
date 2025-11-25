import asyncio
import json

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

    async def run_agent(self, request: CompletionRequest) -> ChatMessage:
        messages = [m.model_dump(exclude_none=True) for m in request.messages]

        # Prepend system prompt if provided
        if request.system_prompt:
            messages.insert(0, {"role": "system", "content": request.system_prompt})

        # Determine model
        model = request.model or settings.OPENAI_MODEL

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

        # 2. Agent Loop
        for _ in range(5):
            try:
                # Non-streaming completion with long timeout
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
                # We need to catch this and re-raise or handle it
                # Raising HTTPException to ensure FastAPI returns 500
                print(f"OpenAI API Error: {e}")
                raise HTTPException(status_code=500, detail=f"OpenAI API Error: {str(e)}") from e

            message = response.choices[0].message

            # Debug Log
            print(f"Debug - Agent Step Response: {message}")

            messages.append(message.model_dump(exclude_none=True))

            if not message.tool_calls:
                return ChatMessage(role=message.role, content=message.content)

            # 3. Execute Tools
            for tool_call in message.tool_calls:
                # Enforce permission (Double check)
                if request.allowed_tools is not None and tool_call.function.name not in request.allowed_tools:
                    result_content = f"Error: Tool '{tool_call.function.name}' is not allowed in this context."
                else:
                    result_content = await self._execute_tool(tool_call, mcp_tools_list, local_tools_map)

                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result_content})

        return ChatMessage(role="assistant", content="Max execution steps reached.")

    async def _execute_tool(self, tool_call, mcp_tools_list, local_tools_map) -> str:
        tool_name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return "Error: Invalid JSON arguments"

        # Check Local
        if tool_name in local_tools_map:
            try:
                # Run in threadpool if blocking, but assuming async or fast for now
                # If function is async, await it. If sync, run it.
                func = local_tools_map[tool_name]
                if asyncio.iscoroutinefunction(func):
                    result = await func(**args)
                else:
                    result = func(**args)
                return str(result)
            except Exception as e:
                return f"Error executing local tool: {str(e)}"

        # Check MCP
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
