import os
from test_base import *

from app.agents.factory import create_agent_from_config
from app.agents.base import AGENT_REGISTRY

# Create temporary YAML config file for mock agent
test_yaml = """
type: mock
name: TestAgent
instructions: Simula una resposta.
model: simulador
"""

test_config_path = "/tmp/test_mock_agent.yaml"

with open(test_config_path, "w") as f:
    f.write(test_yaml)

# Run factory method
agent = create_agent_from_config(test_config_path)

# Run the agent with a dummy prompt
prompt = "Aquest és un test de context inicial"
response = agent.run(prompt)

# Output for verification
assert "MockAgent" in agent.__class__.__name__
assert "[MOCK]" in response
assert "mock", AGENT_REGISTRY