from test_base import *

from app.agents.base import AGENT_REGISTRY
from app.agents.mock.agent import MockAgent
from app.agents.openai.agent import OpenAIAgent

print("AGENT_REGISTRY:", AGENT_REGISTRY)
assert "mock" in AGENT_REGISTRY
assert "openai" in AGENT_REGISTRY
print("MockAgent registrat correctament.")