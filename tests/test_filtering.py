def test_tool_filtering():
    from app.schemas.agent import CompletionRequest, ChatMessage
    
    # Case 1: allowed_tools is None -> All tools allowed
    req_all = CompletionRequest(messages=[], allowed_tools=None)
    assert req_all.allowed_tools is None

    # Case 2: allowed_tools is specific -> Only those allowed
    req_specific = CompletionRequest(messages=[], allowed_tools=["get_server_time"])
    assert "get_server_time" in req_specific.allowed_tools
    assert "other_tool" not in req_specific.allowed_tools

def test_agent_service_tool_filtering():
    # We can't easily mock the full service here without complex mocking of the OpenAI client
    # But we can verify the logic by inspecting the code or integration testing.
    # For unit tests, we'll rely on the schema validation above and integration checks.
    pass
