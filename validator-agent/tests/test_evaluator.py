import sys
from pathlib import Path

# Afegeix la ruta arrel del projecte
ROOT_PATH = Path(__file__).resolve().parents[1]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

import pytest
from unittest.mock import patch
from flask import Flask
from app.agents.roles.evaluator import Evaluator

@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["CONFIG_PATH"] = "/validator-agent/app/config/validator_agent.yaml"  # Aquest fitxer ha d'existir per al test
    with app.app_context():
        yield app

def test_evaluator_runs_eva_role(app):
    mock_results = [
        {"role": "AWC", "status": "accepted", "text": "AWC text"},
        {"role": "AWL", "status": "review", "reasons": ["Missing structure"], "recommendations": ["Add structure"]},
        {"role": "AWT", "status": "accepted"}
    ]

    with patch("app.agents.roles.evaluator.create_agent_from_config") as mock_factory:
        mock_agent = mock_factory.return_value
        mock_agent.run.return_value = [{
            "role": "EVA",
            "status": "review",
            "reasons": ["Inconsistent validation"],
            "recommendations": ["Revisit logical consistency"]
        }]

        evaluator = Evaluator()
        result = evaluator.evaluate(mock_results, context_id="dummy-context")

        assert result["role"] == "EVA"
        assert result["status"] == "review"
        assert "reasons" in result
        assert "recommendations" in result

