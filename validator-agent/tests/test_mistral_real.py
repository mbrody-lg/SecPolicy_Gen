import os

import pytest

from app.agents.mistralai.client import MistralClient


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_REAL_PROVIDER_TESTS", "").strip().lower() not in {"1", "true", "yes", "on"},
        reason="real provider tests require RUN_REAL_PROVIDER_TESTS=1",
    ),
]


def test_mistral_real(client):
    client = MistralClient()

    model = "mistral-small"  # or mistral-medium, mistral-large if you have access
    prompt = "Please summarize the importance of cybersecurity policies."
    instructions = "You are a helpful assistant that provides concise and professional responses."
    temperature = 0.7
    max_tokens = 512

    response = client.chat(
        model=model,
        prompt=prompt,
        instructions=instructions,
        temperature=temperature,
        max_tokens=max_tokens
    )

    assert response is not None
