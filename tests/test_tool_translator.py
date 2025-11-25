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
