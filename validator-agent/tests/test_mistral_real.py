from app.agents.mistralai.client import MistralClient

def test_mistral_real(client):
    client = MistralClient()

    model = "mistral-small"  # o mistral-medium, mistral-large si tens accés
    prompt = "Please summarize the importance of cybersecurity policies."
    instructions = "You are a helpful assistant that provides concise and professional responses."
    temperature = 0.7
    max_tokens = 512

    try:
        response = client.chat(
            model=model,
            prompt=prompt,
            instructions=instructions,
            temperature=temperature,
            max_tokens=max_tokens
        )
        print("=== RESPONSE ===")
        print(response)

    except Exception as e:
        print("=== ERROR ===")
        print(str(e))
