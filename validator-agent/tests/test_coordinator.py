from app.agents.roles.coordinator import Coordinator

def test_coordinator_initializes_correctly(app):
    with app.app_context():
        coordinator = Coordinator()
        assert coordinator.agent is not None
        assert coordinator.config_path.endswith("validator_agent.yaml")
