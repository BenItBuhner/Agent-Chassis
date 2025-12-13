from enum import Enum

import pytest
from mcp.types import Tool

from app.services.tool_translator import ToolTranslator


def test_mcp_to_openai_translation():
    # Mock MCP Tool
    mcp_tool = Tool(
        name="calculate_sum",
        description="Adds two numbers",
        inputSchema={
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    )

    # Translate
    openai_tool = ToolTranslator.mcp_to_openai(mcp_tool)

    # Assertions
    assert openai_tool["type"] == "function"
    assert openai_tool["function"]["name"] == "calculate_sum"
    assert openai_tool["function"]["description"] == "Adds two numbers"
    assert openai_tool["function"]["parameters"] == mcp_tool.inputSchema
    assert "a" in openai_tool["function"]["parameters"]["properties"]


def test_convert_all():
    mcp_tool_1 = Tool(name="t1", description="d1", inputSchema={})
    mcp_tools_list = [{"server": "s1", "tool": mcp_tool_1}]

    result = ToolTranslator.convert_all(mcp_tools_list)
    assert len(result) == 1
    assert result[0]["function"]["name"] == "t1"


def test_function_to_openai_translation():
    def sample_func(x: int, y: float, z: bool, s: str = "default", d: dict = None):
        """Sample docstring."""
        pass

    openai_tool = ToolTranslator.function_to_openai(sample_func)

    assert openai_tool["type"] == "function"
    fn = openai_tool["function"]
    assert fn["name"] == "sample_func"
    assert fn["description"] == "Sample docstring."

    props = fn["parameters"]["properties"]
    assert props["x"]["type"] == "integer"
    assert props["y"]["type"] == "number"
    assert props["z"]["type"] == "boolean"
    assert props["s"]["type"] == "string"
    assert props["d"]["type"] == "object"

    # Check required fields (s and d have defaults, so they shouldn't be required)
    assert "x" in fn["parameters"]["required"]
    assert "y" in fn["parameters"]["required"]
    assert "z" in fn["parameters"]["required"]
    assert "s" not in fn["parameters"]["required"]
    assert "d" not in fn["parameters"]["required"]


def test_function_to_openai_typed_collections_and_enums_are_flattened_to_string():
    """Typed collections and enums should retain structure when possible."""

    class Color(Enum):
        RED = "red"
        BLUE = "blue"

    def sample_func(nums: list[int], payload: dict[str, int] | None = None, choice: Color = Color.RED):
        pass

    tool = ToolTranslator.function_to_openai(sample_func)
    props = tool["function"]["parameters"]["properties"]
    required = tool["function"]["parameters"]["required"]

    assert props["nums"]["type"] == "array"
    assert props["nums"]["items"]["type"] == "integer"
    assert props["payload"]["type"] == "object"
    assert props["choice"]["type"] == "string"
    assert set(props["choice"]["enum"]) == {"red", "blue"}

    # Only nums lacks a default, so it is the only required field
    assert required == ["nums"]


def test_function_to_openai_optional_should_not_be_required():
    def sample_func(amount: int | None = None):
        """Compute with an optional amount."""
        pass

    tool = ToolTranslator.function_to_openai(sample_func)
    props = tool["function"]["parameters"]["properties"]
    required = tool["function"]["parameters"]["required"]

    assert props["amount"]["type"] == "integer"
    assert "amount" not in required


@pytest.mark.xfail(strict=True, reason="Per-parameter docstrings are dropped from schema")
def test_function_to_openai_param_description_is_lost():
    def sample_func(count: int):
        """
        Do something.

        Args:
            count: number of items to process
        """
        pass

    tool = ToolTranslator.function_to_openai(sample_func)
    props = tool["function"]["parameters"]["properties"]
    assert props["count"]["description"] == "number of items to process"


def test_mcp_to_openai_passes_through_schema_without_validation():
    """Current behavior: mcp_to_openai does no schema validation, just passes inputSchema."""
    schema = {"type": "object", "properties": {"a": {"type": "number"}}}
    mcp_tool = Tool(name="unvalidated", description=None, inputSchema=schema)

    tool = ToolTranslator.mcp_to_openai(mcp_tool)
    assert tool["function"]["parameters"] == schema


@pytest.mark.xfail(strict=True, reason="Should reject non-dict schemas instead of returning invalid parameters")
def test_mcp_to_openai_rejects_non_mapping_schema():
    mcp_tool = Tool(name="broken", description="bad schema", inputSchema="not-a-dict")

    with pytest.raises(TypeError):
        ToolTranslator.mcp_to_openai(mcp_tool)
