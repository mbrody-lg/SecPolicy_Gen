from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "service-tests.yml"
RUNNER = ROOT / "scripts" / "run_service_tests_ci.sh"
OVERLAY = ROOT / "infrastructure" / "docker-compose.service-tests.yml"
SMOKE_ENV = ROOT / "infrastructure" / ".env.smoke.example"


def test_service_test_workflow_has_three_isolated_matrix_checks():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for service in ("context-agent", "policy-agent", "validator-agent"):
        assert f"- {service}" in workflow
    assert "fail-fast: false" in workflow
    assert "timeout-minutes: 30" in workflow
    assert "scripts/run_service_tests_ci.sh" in workflow
    assert "if: always()" in workflow


def test_service_test_runner_uses_fake_env_canonical_targets_and_cleanup():
    runner = RUNNER.read_text(encoding="utf-8")

    assert "infrastructure/.env.smoke.example" in runner
    assert "docker-compose.service-tests.yml" in runner
    assert 'project_name="secpolicy-service-tests-${service}"' in runner
    assert 'target="context-tests"' in runner
    assert 'target="policy-tests"' in runner
    assert 'target="validator-tests"' in runner
    assert "down -v --remove-orphans" in runner
    assert "RUN_REAL_PROVIDER_TESTS" not in runner


def test_service_test_overlay_is_isolated_and_uses_test_only_credentials():
    overlay = OVERLAY.read_text(encoding="utf-8")

    assert "container_name: !reset null" in overlay
    assert "ports: !reset []" in overlay
    assert "POLICY_CALLBACK_TOKEN: test-only-policy-callback-token" in overlay
    assert "SERVICE_AUTH_TOKEN" not in overlay
    assert "WORKLOAD_CONTEXT_SIGNING_PRIVATE_KEY_B64" not in overlay
    assert "WORKLOAD_VALIDATOR_SIGNING_PRIVATE_KEY_B64" not in overlay
    smoke = SMOKE_ENV.read_text(encoding="utf-8")
    assert "WORKLOAD_CONTEXT_SIGNING_KID=context-test-v1" in smoke
    assert "WORKLOAD_VALIDATOR_SIGNING_KID=validator-test-v1" in smoke
    assert "WORKLOAD_CANDIDATE_VERIFY_KEYS=" in smoke
