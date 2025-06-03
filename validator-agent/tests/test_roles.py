def test_validator_agent_all_roles(client, default_prompt, default_context_id):
    response = client.post("/validate-policy", json={
        "context_id": default_context_id,
        "policy_text": default_prompt,
        "structured_plan": "Fake structure",
        "generated_at": "2025-05-21T12:00:00Z"
    })
    assert response.status_code == 200
    data = response.get_json()
    assert "status" in data
