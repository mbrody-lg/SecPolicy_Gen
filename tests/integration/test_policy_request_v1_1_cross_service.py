"""Synthetic, in-process Context-to-Policy 1.1 contract across service images.

Context's HTTP post is mocked and Policy uses Flask's test client. This does
not claim to exercise network transport or the running Compose services.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[2]


def _assert_packaged_contract(service):
    project = os.environ.get("CRITICAL_PATH_COMPOSE_PROJECT", "secpolicy-critical-path-ci")
    command = [
        "docker", "run", "--rm", "--entrypoint", "python",
        "-e", "PYTHONPATH=/shared", f"{project}-{service}-agent", "-c",
        "from pathlib import Path; import contracts.policy_request_v1 as contract; "
        "expected = Path('/shared/contracts/policy_request_v1.py'); "
        "assert Path(contract.__file__).resolve() == expected, contract.__file__; "
        "print(contract.__file__)",
    ]
    process = subprocess.run(command, text=True, capture_output=True, timeout=30, check=False)
    assert process.returncode == 0, process.stderr
    assert process.stdout.strip() == "/shared/contracts/policy_request_v1.py"


CONTEXT_SCRIPT = r"""
import json
from copy import deepcopy
from unittest.mock import patch

import mongomock
from bson import ObjectId
from flask import Flask, g

from workload_test_keys import KEY_IDS, configure_test_workload_env, signing_key
configure_test_workload_env()

from app import mongo
from app.context_analysis.policy_input import build_approved_request
from app.services import logic
from test_policy_input import EXAMPLES, context_with_answers, example_answers, structured_answers, synthetic_handoff

tenant = "test-organization"
handoff = synthetic_handoff()
context = context_with_answers(structured_answers(example_answers(EXAMPLES[0])))
context["_id"] = ObjectId("650000000000000000000001")
context["organization_id"] = tenant
context["status"] = "context_ready_for_policy"
context["refined_prompt"] = "Draft the approved synthetic security policy."
request = build_approved_request(context, handoff, tenant_id=tenant)
context["policy_input"]["approval"] = {
    "revision": 1,
    "request": deepcopy(request),
    "answer_snapshot": deepcopy(context["policy_input"]["answers"]),
}
app = Flask(__name__)
app.config.update(
    TESTING=True,
    WORKLOAD_CONTEXT_SIGNING_KID=KEY_IDS["context-agent"],
    WORKLOAD_CONTEXT_SIGNING_KEY=signing_key("context-agent"),
)
db = mongomock.MongoClient().db
transport = {}

class Response:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"context_id": str(context["_id"]), "policy_text": "transport accepted"}

def post(url, *, json, headers, timeout):
    transport.update(url=url, body=json, headers=headers)
    return Response()

with patch.object(mongo, "db", db), \
        patch.object(logic, "policy_handoff_context_from_context_record", return_value=deepcopy(handoff)), \
        patch.object(logic.requests, "post", side_effect=post):
    db.contexts.insert_one(context)
    with app.test_request_context("/"):
        g.organization_id = tenant
        payload = logic.get_context_and_prompt(str(context["_id"]))
        logic.call_policy_agent(payload)

print(json.dumps({"request": request, "transport": transport}))
"""


POLICY_SCRIPT = r"""
import json
import sys
from unittest.mock import patch

import mongomock

from workload_test_keys import configure_test_workload_env
configure_test_workload_env()

from app import create_app, mongo
from app.services import logic

transport = json.load(sys.stdin)
app = create_app()
app.config["TESTING"] = True
db = mongomock.MongoClient().db
observed = {}

class FakeAgent:
    def run(self, *, prompt, context_id, retrieval_plan):
        observed["prompt"] = prompt
        observed["context_id"] = context_id
        observed["plan_request"] = retrieval_plan.policy_request
        observed["families"] = retrieval_plan.required_families
        observed["queries"] = [step.query for step in retrieval_plan.steps]
        return {"text": "Synthetic policy from fake provider"}

manifest = {"version": "1.0", "sources": [
    {"family": "legal_norms", "collection": "synthetic_legal"},
    {"family": "risk_methodologies", "collection": "synthetic_risk"},
]}
with patch.object(mongo, "db", db), \
        patch.object(logic, "load_policy_config", return_value={"type": "fake", "model": "synthetic"}), \
        patch.object(logic, "create_agent_from_config", return_value=FakeAgent()), \
        patch.object(logic, "load_rag_source_manifest", return_value=manifest):
    response = app.test_client().post(
        "/generate_policy", json=transport["body"], headers=transport["headers"],
    )
    saved = db.policies.find_one({"context_id": transport["body"]["context_id"]})

print(json.dumps({
    "status": response.status_code,
    "response": response.get_json(),
    "observed": observed,
    "saved_binding": saved.get("policy_input_binding") if saved else None,
    "saved_tenant": saved.get("organization_id") if saved else None,
}))
"""


def _run_service(service, script, *, input_data=None):
    service_root = ROOT / f"{service}-agent"
    docker_mode = os.environ.get("SECPOLICY_CROSS_SERVICE_DOCKER") == "1"
    root = Path("/shared") if docker_mode else ROOT
    service_path = Path(f"/{service}-agent") if docker_mode else service_root
    env = {name: os.environ[name] for name in ("PATH", "HOME", "LANG") if name in os.environ}
    env.update({
        "TESTING": "true",
        "DEBUG": "false",
        "FLASK_SECRET_KEY": "test-only-secret-key",
        "MONGO_URI": f"mongodb://mongo:27017/{service}-testdb",
        "CONFIG_PATH": str(service_path / "app/config" / f"{service}_agent.yaml"),
        "OPENAI_API_KEY": "test-only-unused-key",
        "PYTHONPATH": os.pathsep.join((
            str(service_path / "tests"), str(service_path), str(root),
        )),
    })
    command = [sys.executable, "-c", textwrap.dedent(script)]
    if docker_mode:
        project = os.environ.get("CRITICAL_PATH_COMPOSE_PROJECT", "secpolicy-critical-path-ci")
        command = ["docker", "run", "--rm", "-i", "-w", str(service_path)]
        for name, value in env.items():
            if name not in ("PATH", "HOME", "LANG"):
                command.extend(("-e", f"{name}={value}"))
        command.extend((f"{project}-{service}-agent", "python", "-c", textwrap.dedent(script)))
    process = subprocess.run(
        command,
        input=json.dumps(input_data) if input_data is not None else None,
        text=True, capture_output=True, cwd=service_root, env=env if not docker_mode else None,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def test_in_process_context_approved_request_reaches_policy_retrieval_and_generation():
    """Replay a mocked HTTP envelope through the two packaged service processes."""
    if os.environ.get("SECPOLICY_CROSS_SERVICE_DOCKER") == "1":
        _assert_packaged_contract("context")
        _assert_packaged_contract("policy")
    emitted = _run_service("context", CONTEXT_SCRIPT)
    request = emitted["request"]
    transport = emitted["transport"]
    assert transport["body"]["policy_request"] == request
    assert transport["headers"]["Authorization"].startswith("Bearer ")
    assert request["version"] == "1.1"
    assert request["approved_context"]["approval_status"] == "approved"

    accepted = _run_service("policy", POLICY_SCRIPT, input_data=transport)
    _assert_accepted(request, accepted)


def _assert_accepted(request, accepted):
    assert accepted["status"] == 200, accepted["response"]
    assert accepted["response"]["policy_text"] == "Synthetic policy from fake provider"
    assert accepted["observed"]["plan_request"] == request
    assert accepted["observed"]["context_id"] == request["context_id"]
    assert "risk_methodologies" in accepted["observed"]["families"]
    priorities = request["business_facts"]["business_priorities"]["value"]
    critical_processes = request["business_facts"]["critical_processes"]["value"]
    assert priorities and critical_processes
    assert all(item in accepted["observed"]["prompt"] for item in priorities)
    assert all(item in accepted["observed"]["prompt"] for item in critical_processes)
    assert all(item in " ".join(accepted["observed"]["queries"]) for item in critical_processes)
    assert accepted["saved_binding"]["snapshot_hash"] == request["approved_context"]["snapshot_hash"]
    assert accepted["saved_binding"]["plan_revision_id"] == request["approved_context"]["plan_revision_id"]
    assert accepted["saved_tenant"] == request["approved_context"]["tenant_id"]


if __name__ == "__main__":
    test_in_process_context_approved_request_reaches_policy_retrieval_and_generation()
