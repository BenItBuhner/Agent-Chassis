import inspect
from collections.abc import Callable
from typing import Any

from mcp.types import Tool as MCPTool


class ToolTranslator:
    @staticmethod
    def mcp_to_openai(mcp_tool: MCPTool) -> dict[str, Any]:
        """
        Converts an MCP Tool object to an OpenAI tool definition.
        """
        return {
            "type": "function",
            "function": {
                "name": mcp_tool.name,
                "description": mcp_tool.description or "",
                "parameters": mcp_tool.inputSchema,
            },
        }

    @staticmethod
    def function_to_openai(func: Callable) -> dict[str, Any]:
        """
        Basic conversion of a Python function to OpenAI tool definition.
        Note: This is a simplified implementation. For production, consider
        using libraries like `instructor` or `pydantic` to generate schemas from type hints.
        """
        name = func.__name__
        description = func.__doc__ or ""

        # Very basic parameter extraction (placeholder for more robust logic)
        # In a real scenario, we would parse type hints to JSON Schema
        params = {"type": "object", "properties": {}, "required": []}

        sig = inspect.signature(func)
        for param_name, param in sig.parameters.items():
            params["properties"][param_name] = {"type": "string"}  # Default to string for safety
            if param.default == inspect.Parameter.empty:
                params["required"].append(param_name)

        return {"type": "function", "function": {"name": name, "description": description, "parameters": params}}

    @staticmethod
    def convert_all(mcp_tools: list[Any]) -> list[dict[str, Any]]:
        """
        Takes a list of tool objects (from MCPManager.list_tools) and converts them.
        Each item in mcp_tools is expected to be a dict with {'server': str, 'tool': MCPTool}
        """
        openai_tools = []
        for item in mcp_tools:
            tool = item["tool"]
            openai_tools.append(ToolTranslator.mcp_to_openai(tool))
        return openai_tools


tool_translator = ToolTranslator()
