"""Opt-in live-provider smoke for Context Agent structured workflow phases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parents[1]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

from app import create_app  # noqa: E402
from app.services import logic  # noqa: E402


CASE = {
    "country": "Spain",
    "region": "Catalonia",
    "sector": "Private healthcare",
    "company_activity": "Outpatient clinic managing patient appointments and clinical records.",
    "important_assets": "Medical records, appointment system, employee files",
    "critical_assets": "Patient data, clinical records",
    "data_categories": "health data, employee data, personal data",
    "third_party_dependencies": "External laboratory provider",
    "cloud_services": "Cloud appointment SaaS",
    "current_security_operations": "Backups, endpoint protection, access reviews",
    "methodology": "ISO 27001, ISO 27799",
    "regulatory_hints": "GDPR",
    "generic": "Specific",
    "policy_type": "Access control policy",
    "need": "Protect patient data and clinical systems.",
    "language": "English",
}


def _sha256_json(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _phase_summary(name: str, payload: dict) -> dict:
    return {
        "phase": name,
        "success": True,
        "schema_hash": _sha256_json(payload),
        "top_level_keys": sorted(payload.keys()),
    }


def _require_opt_in() -> None:
    if os.getenv("RUN_REAL_PROVIDER_TESTS", "").lower() not in {"1", "true", "yes"}:
        raise SystemExit("RUN_REAL_PROVIDER_TESTS=1 is required for live-provider smoke.")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for live-provider smoke.")


def build_artifact() -> dict:
    app = create_app()
    with app.app_context():
        security_context = logic.build_context_security_context(CASE)
        context_building_prompt = logic.generate_context_prompt(CASE)
        context_building = logic.run_context_building_review(
            context_building_prompt,
            context_id="live-provider-smoke",
        )["structured_review"]

        plan_prompt = logic.generate_context_plan_prompt(CASE)
        planning = logic.run_context_planning_review(
            plan_prompt,
            context_id="live-provider-smoke",
        )["structured_review"]

        plan = logic.approve_context_intelligence_plan({
            **CASE,
            "security_context": security_context,
            "context_intelligence_plan": logic.build_context_intelligence_plan(CASE),
        })
        first_task = plan["revisions"][0]["tasks"][0]
        task_result = logic.run_structured_with_agent(
            logic.build_context_task_prompt(CASE, first_task, plan["revisions"][0]),
            schema_name="context_agent_task_result",
            json_schema=logic.context_phase_output_schema("context_task_result"),
            context_id="live-provider-smoke",
            fallback_phase="context_task_result",
        )

    return {
        "artifact": "context-agent-live-provider-smoke",
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "redaction": "hashes_and_bounded_metadata_only",
        "provider": {
            "api_mode": os.getenv("OPENAI_STRUCTURED_API_MODE", "chat_completions"),
            "model_configured": True,
        },
        "case": {
            "id": "healthcare_live_provider_smoke",
            "input_hash": _sha256_json(CASE),
            "security_context_hash": _sha256_json(security_context),
            "retrieval_collection_families": security_context["retrieval_hints"]["collection_families"],
            "missing_information_count": len(security_context["analysis"]["missing_information"]),
        },
        "phases": [
            _phase_summary("context_building", context_building),
            _phase_summary("context_planning", planning),
            _phase_summary("context_task_result", task_result),
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    _require_opt_in()
    artifact = build_artifact()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "phases": len(artifact["phases"])}, sort_keys=True))


if __name__ == "__main__":
    main()
