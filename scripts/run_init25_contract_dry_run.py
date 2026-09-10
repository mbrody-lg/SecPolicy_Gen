#!/usr/bin/env python3
"""Produce deterministic INIT-25 candidate artifacts without external services."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_init25_parity_report import build_report
from scripts.validate_init25_parity_artifact import validate_no_sensitive_fields


ARTIFACT_FIELDS = {
    "context_agent.policy_handoff.v1": {
        "assumptions", "business_context", "context_ready_for_policy",
        "context_snapshot_hash", "contract", "final_context_sections",
        "final_context_status", "final_context_version", "plan_revision_id",
        "retrieval_hints", "security_context_version", "source",
        "structured_findings", "unresolved_gaps", "version",
    },
    "rag.retrieval_context": {
        "context_id", "refined_prompt", "language", "country", "region",
        "sector", "important_assets", "critical_assets", "methodology",
        "specificity", "need", "data_types",
    },
    "rag.retrieval_plan": {"context_id", "steps", "required_families", "coverage_notes"},
    "rag.retrieval_evidence": {"text", "source_id", "collection", "family"},
    "policy_agent.policy_draft": {
        "context_id", "language", "policy_text", "structured_plan", "generated_at",
        "policy_agent_version", "retrieval_evidence",
    },
    "validator.validation_payload": {"context_id", "policy_text", "structured_plan", "generated_at"},
    "validator.validation_decision": {"status", "reasons", "recommendations"},
}


def _load_handoff_validator():
    path = ROOT / "context-agent" / "app" / "policy_handoff_contract.py"
    spec = importlib.util.spec_from_file_location("context_agent_policy_handoff_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load policy handoff contract from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_policy_handoff_context


validate_policy_handoff_context = _load_handoff_validator()


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _error(errors: list[dict[str, str]], artifact: str, code: str, field: str = "") -> None:
    error = {"error_code": code, "stage": artifact}
    if field:
        error["field"] = field
    errors.append(error)


def build_candidate_artifacts(case_id: str, source: dict[str, Any]) -> dict[str, Any]:
    validate_no_sensitive_fields(source)
    security_findings = source.get("security_findings", [])
    if not isinstance(security_findings, list) or any(not isinstance(item, dict) for item in security_findings):
        raise SystemExit("INIT-25 dry-run case error: security_findings must be a list of objects")
    required = {
        "country", "region", "sector", "important_assets", "critical_assets",
        "methodology", "specificity", "need", "language", "refined_context",
        "context_ready_for_policy", "required_evidence_families", "evidence",
        "policy_text", "structured_plan", "validation", "generated_at",
    }
    missing = required - set(source)
    if missing:
        raise SystemExit(f"INIT-25 dry-run case error: missing input fields: {', '.join(sorted(missing))}")

    required_families = _string_list(source["required_evidence_families"])
    evidence = source["evidence"] if isinstance(source["evidence"], list) else []
    handoff = {
        "version": "1.0",
        "source": "context-agent",
        "contract": "context_agent.policy_handoff",
        "security_context_version": "1.0",
        "final_context_version": "1.0",
        "final_context_status": "ready" if source["context_ready_for_policy"] else "review",
        "context_ready_for_policy": source["context_ready_for_policy"],
        "plan_revision_id": f"plan-{case_id}",
        "context_snapshot_hash": f"fixture:{case_id}",
        "business_context": {"country": source["country"], "region": source["region"], "sector": source["sector"]},
        "final_context_sections": {"scope": {"status": "accepted", "content": source["refined_context"]}},
        "structured_findings": [{"task_id": "fixture-analysis", "status": "completed", "findings": [source["refined_context"]]}],
        "retrieval_hints": {"collection_families": required_families},
        "assumptions": [],
        "unresolved_gaps": [],
    }
    artifacts = {"context_agent.policy_handoff.v1": handoff}
    if source["context_ready_for_policy"] is not True:
        return artifacts

    retrieval_context = {
        "context_id": case_id,
        "refined_prompt": source["refined_context"],
        "language": source["language"],
        "country": source["country"],
        "region": source["region"],
        "sector": source["sector"],
        "important_assets": source["important_assets"],
        "critical_assets": source["critical_assets"],
        "methodology": source["methodology"],
        "specificity": source["specificity"],
        "need": source["need"],
        "data_types": [source["sector"], source["need"]],
    }
    retrieval_plan = {
        "context_id": case_id,
        "steps": [
            {
                "family": item.get("family"),
                "collection": item.get("collection"),
                "query": f"{source['need']} {source['sector']}",
                "filters": {"country": source["country"], "region": source["region"]},
                "top_k": 5,
            }
            for item in evidence if isinstance(item, dict)
        ],
        "required_families": required_families,
        "coverage_notes": ["Deterministic INIT-25 contract fixture."],
    }
    policy_draft = {
        "context_id": case_id,
        "language": source["language"],
        "policy_text": source["policy_text"],
        "structured_plan": source["structured_plan"],
        "generated_at": source["generated_at"],
        "policy_agent_version": "init25-contract-runner",
        "retrieval_evidence": [item.get("source_id") for item in evidence if isinstance(item, dict)],
    }
    artifacts.update({
        "rag.retrieval_context": retrieval_context,
        "rag.retrieval_plan": retrieval_plan,
        "rag.retrieval_evidence": evidence,
        "policy_agent.policy_draft": policy_draft,
        "validator.validation_payload": {
            "context_id": case_id,
            "policy_text": source["policy_text"],
            "structured_plan": source["structured_plan"],
            "generated_at": source["generated_at"],
        },
        "validator.validation_decision": source["validation"],
    })
    return artifacts


def _artifact_fields(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        return sorted(payload)
    if isinstance(payload, list):
        return sorted({key for item in payload if isinstance(item, dict) for key in item})
    return []


def _validate_artifacts(case_id: str, artifacts: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for missing in sorted(set(ARTIFACT_FIELDS) - set(artifacts)):
        _error(errors, missing, "artifact_missing")
    for extra in sorted(set(artifacts) - set(ARTIFACT_FIELDS)):
        _error(errors, extra, "artifact_not_allowed")

    handoff_result = validate_policy_handoff_context(artifacts.get("context_agent.policy_handoff.v1"))
    if not handoff_result.get("success"):
        _error(errors, "context_agent.policy_handoff.v1", handoff_result["error_code"], handoff_result.get("field", ""))

    for name, required in ARTIFACT_FIELDS.items():
        if name not in artifacts or name == "context_agent.policy_handoff.v1":
            continue
        payload = artifacts[name]
        if name == "rag.retrieval_evidence":
            if not isinstance(payload, list) or not payload:
                _error(errors, name, "retrieval_evidence_invalid")
                continue
            for item in payload:
                if not isinstance(item, dict) or set(item) != required or any(not _non_empty_string(item[field]) for field in required):
                    _error(errors, name, "retrieval_evidence_item_invalid")
                    break
            continue
        if not isinstance(payload, dict) or set(payload) != required:
            _error(errors, name, "artifact_fields_invalid")

    plan = artifacts.get("rag.retrieval_plan")
    if isinstance(plan, dict):
        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps:
            _error(errors, "rag.retrieval_plan", "retrieval_steps_invalid", "steps")
        else:
            for step in steps:
                if (
                    not isinstance(step, dict)
                    or set(step) != {"family", "collection", "query", "filters", "top_k"}
                    or not all(_non_empty_string(step.get(field)) for field in ("family", "collection", "query"))
                    or not isinstance(step.get("filters"), dict)
                    or not isinstance(step.get("top_k"), int)
                    or step["top_k"] <= 0
                ):
                    _error(errors, "rag.retrieval_plan", "retrieval_step_invalid", "steps")
                    break
        for field in ("required_families", "coverage_notes"):
            if not _string_list(plan.get(field)):
                _error(errors, "rag.retrieval_plan", "field_value_invalid", field)

    retrieval_context = artifacts.get("rag.retrieval_context")
    if isinstance(retrieval_context, dict):
        for field in ("context_id", "refined_prompt", "language", "country", "region", "sector", "methodology", "specificity", "need"):
            if not _non_empty_string(retrieval_context.get(field)):
                _error(errors, "rag.retrieval_context", "field_value_invalid", field)
        for field in ("important_assets", "critical_assets", "data_types"):
            if not _string_list(retrieval_context.get(field)):
                _error(errors, "rag.retrieval_context", "field_value_invalid", field)

    for name in ("policy_agent.policy_draft", "validator.validation_payload"):
        payload = artifacts.get(name)
        if not isinstance(payload, dict):
            continue
        for field in ("context_id", "policy_text", "generated_at"):
            if not _non_empty_string(payload.get(field)):
                _error(errors, name, "field_value_invalid", field)
        if not isinstance(payload.get("structured_plan"), list):
            _error(errors, name, "field_value_invalid", "structured_plan")
    policy_draft = artifacts.get("policy_agent.policy_draft")
    if isinstance(policy_draft, dict):
        for field in ("language", "policy_agent_version"):
            if not _non_empty_string(policy_draft.get(field)):
                _error(errors, "policy_agent.policy_draft", "field_value_invalid", field)
        if not _string_list(policy_draft.get("retrieval_evidence")):
            _error(errors, "policy_agent.policy_draft", "field_value_invalid", "retrieval_evidence")

    for name in ("rag.retrieval_context", "rag.retrieval_plan", "policy_agent.policy_draft", "validator.validation_payload"):
        payload = artifacts.get(name)
        if isinstance(payload, dict) and payload.get("context_id") != case_id:
            _error(errors, name, "context_id_mismatch", "context_id")
    decision = artifacts.get("validator.validation_decision")
    if isinstance(decision, dict):
        if decision.get("status") not in {"accepted", "review", "rejected"}:
            _error(errors, "validator.validation_decision", "validation_status_invalid", "status")
        for field in ("reasons", "recommendations"):
            value = decision.get(field)
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                _error(errors, "validator.validation_decision", "field_value_invalid", field)
    return errors


def run_case(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    validate_no_sensitive_fields(case)
    case_id = case.get("case_id")
    source = case.get("input")
    if not _non_empty_string(case_id) or not isinstance(source, dict):
        raise SystemExit("INIT-25 dry-run case error: case_id and input are required")
    artifacts = build_candidate_artifacts(case_id, source)
    decision = artifacts.get("validator.validation_decision")
    evidence = artifacts.get("rag.retrieval_evidence")
    evidence_items = evidence if isinstance(evidence, list) else []
    summary = {
        "validation_status": decision.get("status", "unknown") if isinstance(decision, dict) else "unknown",
        "covered_evidence_families": sorted({item["family"] for item in evidence_items if isinstance(item, dict) and _non_empty_string(item.get("family"))}),
        "correlation_id": f"init25-contract-{case_id}",
        "artifacts": {name: _artifact_fields(payload) for name, payload in sorted(artifacts.items())},
        "runtime_errors": _validate_artifacts(case_id, artifacts),
        "security_findings": source.get("security_findings", []),
    }
    authoritative = {
        "validation_status": case.get("authoritative_validation_status", "accepted"),
        "required_evidence_families": _string_list(source.get("required_evidence_families")),
        "artifacts": {name: sorted(fields) for name, fields in ARTIFACT_FIELDS.items()},
    }
    return artifacts, summary, build_report(case_id, authoritative, summary)


def _load_case(path: Path, case_id: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        raise SystemExit("INIT-25 dry-run case error: case file must contain a cases list")
    for case in cases:
        if isinstance(case, dict) and case.get("case_id") == case_id:
            return case
    raise SystemExit(f"INIT-25 dry-run case error: unknown case_id {case_id}")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-file", required=True, type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    artifacts, summary, report = run_case(_load_case(args.case_file, args.case_id))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(args.output_dir / "candidate-artifacts.json", artifacts)
    _write_json(args.output_dir / "candidate-summary.json", summary)
    _write_json(args.output_dir / "parity-report.json", report)
    if report["recommendation"] == "pause":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
