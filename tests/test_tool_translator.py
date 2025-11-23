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
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"}
            },
            "required": ["a", "b"]
        }
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
    mcp_tools_list = [
        {"server": "s1", "tool": mcp_tool_1}
    ]
    
    result = ToolTranslator.convert_all(mcp_tools_list)
    assert len(result) == 1
    assert result[0]["function"]["name"] == "t1"
