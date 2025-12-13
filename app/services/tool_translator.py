import inspect
from collections.abc import Callable, Mapping
from enum import Enum
from typing import Any, get_args, get_origin

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
            schema = ToolTranslator._annotation_to_schema(param.annotation)
            params["properties"][param_name] = schema

            if param.default == inspect.Parameter.empty:
                params["required"].append(param_name)

        return {"type": "function", "function": {"name": name, "description": description, "parameters": params}}

    @staticmethod
    def _annotation_to_schema(annotation: Any) -> dict[str, Any]:
        """
        Convert a Python type annotation to a basic JSON Schema shape.
        Falls back to string when unsure (OpenAI tolerates permissive schemas).
        """
        if annotation == inspect.Parameter.empty:
            return {"type": "string"}

        # Simple primitives
        if annotation is int:
            return {"type": "integer"}
        if annotation is float:
            return {"type": "number"}
        if annotation is bool:
            return {"type": "boolean"}
        if annotation is str:
            return {"type": "string"}
        if annotation is dict:
            return {"type": "object"}
        if annotation is list:
            return {"type": "array"}

        # Enums -> string with enum values
        if inspect.isclass(annotation) and issubclass(annotation, Enum):
            return {"type": "string", "enum": [member.value for member in annotation]}

        origin = get_origin(annotation)
        args = get_args(annotation)

        # Collections
        if origin in (list, set, tuple):
            items_schema = ToolTranslator._annotation_to_schema(args[0]) if args else {}
            schema: dict[str, Any] = {"type": "array"}
            if items_schema:
                schema["items"] = items_schema
            return schema

        if origin in (dict, Mapping):
            return {"type": "object"}

        # Optional/Union types - pick first concrete type
        if origin is None and hasattr(annotation, "__origin__"):
            origin = annotation.__origin__

        if origin is not None and args:
            # Attempt to map first argument (best effort)
            return ToolTranslator._annotation_to_schema(args[0])

        # Fallback
        return {"type": "string"}

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
