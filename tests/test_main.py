def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    # Health check now includes persistence info
    assert data["status"] == "healthy"
    assert "persistence_enabled" in data


def test_agent_endpoint_exists(client):
    # Since we haven't set an API key in the test environment,
    # the behavior depends on CHASSIS_API_KEY setting.
    # If CHASSIS_API_KEY is set, we get 403 Forbidden
    # If CHASSIS_API_KEY is None, we get 503 Service Unavailable (no OpenAI key)

    valid_body = {"messages": [{"role": "user", "content": "Hello"}]}

    response = client.post("/api/v1/agent/completion", json=valid_body)

    # Accept either 403 (auth required) or 503 (no OpenAI key)
    # Both indicate the endpoint exists and is being processed
    assert response.status_code in [403, 503]
