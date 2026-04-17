from unittest.mock import MagicMock, patch

from app.agents.roles.coordinator import Coordinator


def _build_coordinator(round_outputs, evaluator_outputs, rounds=3):
    coordinator = Coordinator.__new__(Coordinator)
    coordinator.validation = {
        "rounds": rounds,
        "consensus_threshold": 2,
        "vote_strategy": "majority",
    }
    coordinator.debug_mode = False
    coordinator.agent = MagicMock()
    coordinator.agent.roles = [{"AWC": {}}, {"AWL": {}}, {"AWT": {}}, {"EVA": {}}]
    coordinator.agent.run = MagicMock(side_effect=round_outputs)
    coordinator.evaluator = MagicMock()
    coordinator.evaluator.evaluate = MagicMock(side_effect=evaluator_outputs)
    coordinator.log_validation = MagicMock()
    return coordinator


def test_coordinator_initializes_correctly(app):
    with app.app_context():
        coordinator = Coordinator()
        assert coordinator.agent is not None
        assert coordinator.config_path.endswith("validator_agent.yaml")


def test_validate_policy_returns_accepted_without_policy_update():
    round_results = [[
        {"role": "AWC", "status": "accepted", "text": "accepted policy"},
        {"role": "AWL", "status": "accepted"},
        {"role": "AWT", "status": "accepted"},
    ]]
    evaluator_results = [{"status": "accepted", "confidence": 0.99}]
    coordinator = _build_coordinator(round_results, evaluator_results, rounds=3)

    policy_input = {
        "context_id": "ctx-1",
        "policy_text": "initial policy",
        "language": "en",
        "policy_agent_version": "0.1.0",
        "generated_at": "2026-03-05T00:00:00+00:00",
    }

    with patch("app.services.logic.send_policy_update_to_policy_agent") as update_policy:
        result = coordinator.validate_policy(policy_input)

    assert result["status"] == "accepted"
    assert result["text"] == "accepted policy"
    assert coordinator.agent.run.call_count == 1
    assert coordinator.evaluator.evaluate.call_count == 1
    assert coordinator.log_validation.call_count == 1
    assert coordinator.log_validation.call_args.args[3] == 1
    assert coordinator.log_validation.call_args.args[4] is True
    update_policy.assert_not_called()


def test_validate_policy_review_flow_updates_prompt_then_accepts():
    round_one = [
        {
            "role": "AWC",
            "status": "review",
            "reason": "Missing audit scope",
            "recommendations": ["Add audit scope", "Add review cadence"],
        },
        {"role": "AWL", "status": "accepted"},
        {"role": "AWT", "status": "accepted"},
    ]
    round_two = [
        {"role": "AWC", "status": "accepted", "text": "revised accepted policy"},
        {"role": "AWL", "status": "accepted"},
        {"role": "AWT", "status": "accepted"},
    ]
    evaluator_results = [
        {"status": "review", "notes": "needs update"},
        {"status": "accepted", "notes": "ok"},
    ]
    coordinator = _build_coordinator([round_one, round_two], evaluator_results, rounds=3)

    policy_input = {
        "context_id": "ctx-2",
        "policy_text": "original policy",
        "language": "en",
        "policy_agent_version": "0.1.0",
        "generated_at": "2026-03-05T00:00:00+00:00",
    }

    update_response = {
        "policy_text": "revised policy from policy-agent",
        "policy_agent_version": "0.2.0",
        "generated_at": "2026-03-05T01:00:00+00:00",
    }

    with patch("app.services.logic.send_policy_update_to_policy_agent", return_value=update_response) as update_policy:
        result = coordinator.validate_policy(policy_input)

    assert result["status"] == "accepted"
    assert result["policy_text"] == "revised policy from policy-agent"
    assert coordinator.agent.run.call_count == 2
    assert coordinator.agent.run.call_args_list[1].args[0] == "revised policy from policy-agent"
    assert coordinator.evaluator.evaluate.call_count == 2
    assert coordinator.log_validation.call_count == 2

    update_policy.assert_called_once()
    kwargs = update_policy.call_args.kwargs
    assert kwargs["context_id"] == "ctx-2"
    assert kwargs["status"] == "review"
    assert kwargs["reasons"] == ["Missing audit scope"]
    assert kwargs["recommendations"] == ["Add audit scope", "Add review cadence"]


def test_validate_policy_uses_final_vote_when_no_consensus():
    round_one = [
        {"role": "AWC", "status": "review", "reason": "Needs detail", "recommendations": ["Expand scope"]},
        {"role": "AWL", "status": "review", "reason": "Needs structure", "recommendations": ["Add sections"]},
        {"role": "AWT", "status": "accepted"},
    ]
    round_two = [
        {"role": "AWC", "status": "rejected", "reason": "Control gaps", "recommendations": ["Add controls"]},
        {"role": "AWL", "status": "rejected", "reason": "Logic conflicts", "recommendations": ["Resolve conflicts"]},
        {"role": "AWT", "status": "review", "reason": "Tone unclear", "recommendations": ["Clarify tone"]},
    ]
    evaluator_results = [
        {"status": "review"},
        {"status": "review"},
        {"status": "review", "source": "final"},
    ]
    coordinator = _build_coordinator([round_one, round_two], evaluator_results, rounds=2)

    policy_input = {
        "context_id": "ctx-3",
        "policy_text": "policy without consensus",
        "language": "en",
        "policy_agent_version": "0.1.0",
        "generated_at": "2026-03-05T00:00:00+00:00",
    }

    update_response = {
        "policy_text": "policy without consensus",
        "policy_agent_version": "0.1.0",
        "generated_at": "2026-03-05T01:00:00+00:00",
    }

    with patch("app.services.logic.send_policy_update_to_policy_agent", return_value=update_response) as update_policy:
        result = coordinator.validate_policy(policy_input)

    assert result["status"] == "rejected"
    assert result["reasons"] == ["Control gaps", "Logic conflicts"]
    assert result["recommendations"] == ["Add controls", "Resolve conflicts"]
    assert coordinator.agent.run.call_count == 2
    assert coordinator.evaluator.evaluate.call_count == 3
    assert update_policy.call_count == 2

    final_log_call = coordinator.log_validation.call_args_list[-1]
    assert final_log_call.args[3] == coordinator.max_rounds
    assert final_log_call.args[4] is False
