def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_agent_endpoint_exists(client):
    # Since we haven't set an API key in the test environment,
    # we expect a 503 Service Unavailable or 422 Validation Error depending on request body
    # But first we must send a valid body to pass validation.

    valid_body = {"messages": [{"role": "user", "content": "Hello"}]}

    response = client.post("/api/v1/agent/completion", json=valid_body)

    # We expect 503 because OPENAI_API_KEY is None
    assert response.status_code == 503
    assert response.json() == {"detail": "OpenAI API Key not configured"}
