import json

def test_generate_policy_route_with_openai(client, default_prompt, default_context_id, openai_model_version, default_language):
    payload = {
        "context_id": default_context_id,
        "refined_prompt": default_prompt,
        "language":  default_language,
        "model_version": openai_model_version
    }

    response = client.post(
        "/generate_policy",
        data=json.dumps(payload),
        content_type="application/json"
    )

    assert response.status_code == 200
    data = response.get_json()

    assert "policy_text" in data
    assert "context_id" in data
    assert "model_version" in data
    assert "structured_plan" in data
    assert "language" in data
    assert data["context_id"] == payload["context_id"]
    assert data["language"] == payload["language"]
    assert "[Generated policy simulation]" in data["policy_text"]