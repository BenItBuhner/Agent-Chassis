import pytest
from app.services.local_tools import local_registry
from app.services.tool_translator import ToolTranslator

def test_calculator_tool_execution():
    tools = local_registry.get_tools()
    assert "calculate" in tools
    
    calc_func = tools["calculate"]
    
    # Test Add
    assert calc_func(operation="add", a=5, b=3) == "8"
    assert calc_func(operation="add", a=5.5, b=2.0) == "7.5"
    
    # Test Subtract
    assert calc_func(operation="subtract", a=10, b=4) == "6"
    
    # Test Multiply
    assert calc_func(operation="multiply", a=2, b=3) == "6"
    
    # Test Divide
    assert calc_func(operation="divide", a=10, b=2) == "5.0" # Division always returns float in Py3
    assert calc_func(operation="divide", a=5, b=0) == "Error: Division by zero"
    
    # Test Unknown
    assert calc_func(operation="unknown", a=1, b=1) == "Error: Unknown operation 'unknown'"

def test_calculator_schema_generation():
    tools = local_registry.get_tools()
    calc_func = tools["calculate"]
    
    schema = ToolTranslator.function_to_openai(calc_func)
    
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "calculate"
    assert "Performs basic arithmetic operations" in schema["function"]["description"]
    
    props = schema["function"]["parameters"]["properties"]
    assert "operation" in props
    assert "a" in props
    assert "b" in props
    
    required = schema["function"]["parameters"]["required"]
    assert "operation" in required
    assert "a" in required
    assert "b" in required
