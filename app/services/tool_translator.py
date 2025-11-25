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
        """
        name = func.__name__
        description = func.__doc__ or ""
        params = {"type": "object", "properties": {}, "required": []}

        sig = inspect.signature(func)
        for param_name, param in sig.parameters.items():
            # Map Python types to JSON Schema types
            param_type = "string"  # Default
            if param.annotation != inspect.Parameter.empty:
                if param.annotation is int:
                    param_type = "integer"
                elif param.annotation is float:
                    param_type = "number"
                elif param.annotation is bool:
                    param_type = "boolean"
                elif param.annotation is list:
                    param_type = "array"
                elif param.annotation is dict:
                    param_type = "object"

            params["properties"][param_name] = {"type": param_type}

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
