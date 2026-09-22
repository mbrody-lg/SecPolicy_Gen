from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
WORKFLOW = ROOT / ".github" / "workflows" / "critical-path.yml"
MAKEFILE = ROOT / "Makefile"
CI_RUNNER = ROOT / "scripts" / "run_critical_path_ci.sh"
VALIDATION_RUNNER = ROOT / "scripts" / "run_critical_path_validation.sh"
SMOKE_RUNNER = ROOT / "scripts" / "run_docker_functional_smoke.sh"
BROWSER_RUNNER = ROOT / "scripts" / "run_context_browser_smoke.sh"
SEED_RUNNER = ROOT / "context-agent" / "scripts" / "seed_browser_smoke_contexts.py"
BROWSER_SPEC = ROOT / "tests" / "browser" / "context-workflow.spec.js"
OVERLAY = ROOT / "infrastructure" / "docker-compose.critical-path.yml"


def test_critical_path_workflow_starts_informational_and_retains_evidence():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "name: informational-critical-path" in workflow
    assert "continue-on-error: true" in workflow
    assert "timeout-minutes: 45" in workflow
    assert "scripts/run_critical_path_ci.sh" in workflow
    assert "if: always()" in workflow
    assert "migration/critical-path/metrics.json" in workflow
    assert "migration/functional-smoke-result.json" in workflow
    assert "retention-days: 14" in workflow


def test_artifact_uploads_use_the_node24_action_pinned_by_sha():
    workflows = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS_DIR.glob("*.yml"))
    )

    expected = "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f # v6.0.0"
    assert workflows.count(expected) == 3
    assert "actions/upload-artifact@v4" not in workflows


def test_ci_runner_uses_versioned_fake_env_and_dedicated_compose_project():
    runner = CI_RUNNER.read_text(encoding="utf-8")

    assert "infrastructure/.env.smoke.example" in runner
    assert "secpolicy-critical-path-ci" in runner
    assert "docker-compose.critical-path.yml" in runner
    assert "CRITICAL_PATH_REMOVE_VOLUMES=1" in runner
    assert "make -C \"$ROOT_DIR\" critical-path-validation" in runner
    assert '"total_seconds"' in runner
    assert '"disk_delta_kb"' in runner


def test_critical_path_passes_explicit_env_and_project_to_smoke():
    validation = VALIDATION_RUNNER.read_text(encoding="utf-8")
    smoke = SMOKE_RUNNER.read_text(encoding="utf-8")

    assert 'ENV_FILE="${CRITICAL_PATH_ENV_FILE:-infrastructure/.env}"' in validation
    assert 'ENV_FILE="$ENV_FILE" make docker-preflight' in validation
    assert 'ENV_FILE="$ENV_FILE" scripts/docker_preflight.sh --print-compose' in validation
    bootstrap = '"$ROOT_DIR/scripts/bootstrap_agent_config.sh"'
    assert bootstrap in validation
    assert validation.index(bootstrap) < validation.index('ENV_FILE="$ENV_FILE" make docker-preflight')
    assert 'COMPOSE_PROJECT_NAME="${CRITICAL_PATH_COMPOSE_PROJECT:-}"' in validation
    assert 'MIGRATION_SMOKE_ENV_FILE="$ENV_FILE"' in validation
    assert 'MIGRATION_SMOKE_COMPOSE_PROJECT="$COMPOSE_PROJECT_NAME"' in validation
    assert 'MIGRATION_SMOKE_COMPOSE_OVERRIDE="$COMPOSE_OVERRIDE"' in validation
    assert 'COMPOSE_PROJECT_NAME="${MIGRATION_SMOKE_COMPOSE_PROJECT:-}"' in smoke
    assert 'DOCKER_COMPOSE_CMD+=( -p "$COMPOSE_PROJECT_NAME" )' in smoke


def test_critical_path_overlay_uses_test_only_credentials():
    overlay = OVERLAY.read_text(encoding="utf-8")

    assert "POLICY_CALLBACK_TOKEN: test-only-policy-callback-token" in overlay
    assert overlay.count("SERVICE_AUTH_TOKEN: test-only-service-auth-token") == 3


def test_context_browser_smoke_accepts_critical_path_compose_contract():
    validation = VALIDATION_RUNNER.read_text(encoding="utf-8")
    browser = BROWSER_RUNNER.read_text(encoding="utf-8")

    assert 'CONTEXT_BROWSER_ENV_FILE="$ENV_FILE"' in validation
    assert 'CONTEXT_BROWSER_COMPOSE_PROJECT="$COMPOSE_PROJECT_NAME"' in validation
    assert 'CONTEXT_BROWSER_COMPOSE_OVERRIDE="$COMPOSE_OVERRIDE"' in validation
    assert "CONTEXT_BROWSER_ENV_FILE" in browser
    assert "CONTEXT_BROWSER_COMPOSE_PROJECT" in browser
    assert "CONTEXT_BROWSER_COMPOSE_OVERRIDE" in browser
    assert 'ENV_FILE="$ENV_FILE" make docker-preflight' in browser
    assert 'ENV_FILE="$ENV_FILE" scripts/docker_preflight.sh --print-compose' in browser


def test_governance_target_accepts_the_critical_path_env_file():
    validation = VALIDATION_RUNNER.read_text(encoding="utf-8")
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert "ENV_FILE?=$(INFRA_DIR)/.env" in makefile
    assert "--env-file $(ENV_FILE)" in makefile
    assert "--env-file $(INFRA_DIR)/.env" not in makefile
    assert 'ENV_FILE="$ENV_FILE" make governance-tests' in validation


def test_browser_fixture_provisions_tenant_scoped_test_session():
    seed = SEED_RUNNER.read_text(encoding="utf-8")
    browser_spec = BROWSER_SPEC.read_text(encoding="utf-8")

    assert 'ORGANIZATION_ID = "browser-smoke-org"' in seed
    assert "provision_membership(" in seed
    assert 'roles=["operator"]' in seed
    assert 'context["organization_id"] = ORGANIZATION_ID' in seed
    assert '"session_cookie"' in seed
    assert "addCookies([manifest.session_cookie])" in browser_spec
