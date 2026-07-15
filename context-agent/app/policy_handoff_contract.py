"""Pure validation for the Context Agent policy handoff contract."""

POLICY_HANDOFF_CONTEXT_VERSION = "1.0"
FINAL_CONTEXT_VERSION = "1.0"


def _string_list(value):
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _error(error_code: str, *, field: str | None = None) -> dict:
    result = {
        "success": False,
        "error_type": "contract_error",
        "error_code": error_code,
        "message": "Policy handoff context is not valid.",
    }
    if field:
        result["field"] = field
    return result


def validate_policy_handoff_context(handoff: dict, *, security_context_version: str = "1.0") -> dict:
    if not isinstance(handoff, dict):
        return _error("policy_handoff_not_object")
    if handoff.get("version") != POLICY_HANDOFF_CONTEXT_VERSION:
        return _error("policy_handoff_version_unsupported")
    if handoff.get("contract") != "context_agent.policy_handoff":
        return _error("policy_handoff_contract_invalid")
    if handoff.get("source") != "context-agent":
        return _error("policy_handoff_source_invalid")
    if handoff.get("security_context_version") != security_context_version:
        return _error("security_context_version_unsupported")
    if handoff.get("final_context_version") != FINAL_CONTEXT_VERSION:
        return _error("final_context_version_unsupported")
    if handoff.get("final_context_status") != "ready":
        return _error("final_context_not_ready")
    if handoff.get("context_ready_for_policy") is not True:
        return _error("context_not_ready_for_policy")
    if not str(handoff.get("plan_revision_id") or "").strip():
        return _error("plan_revision_id_missing")
    if not str(handoff.get("context_snapshot_hash") or "").strip():
        return _error("context_snapshot_hash_missing")
    sections = handoff.get("final_context_sections")
    if not isinstance(sections, dict) or not sections:
        return _error("final_context_sections_missing")
    for section_id, section in sections.items():
        if not isinstance(section, dict):
            return _error("final_context_section_invalid", field=f"final_context_sections.{section_id}")
        if section.get("status") != "accepted":
            return _error("final_context_section_not_accepted", field=f"final_context_sections.{section_id}.status")
        if not str(section.get("content") or "").strip():
            return _error("final_context_section_empty", field=f"final_context_sections.{section_id}.content")
    findings = handoff.get("structured_findings")
    if not isinstance(findings, list) or not findings:
        return _error("structured_findings_missing")
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            return _error("structured_finding_invalid", field=f"structured_findings.{index}")
        if finding.get("status") != "completed":
            return _error("structured_finding_not_completed", field=f"structured_findings.{index}.status")
        if not str(finding.get("task_id") or "").strip():
            return _error("structured_finding_task_id_missing", field=f"structured_findings.{index}.task_id")
        has_evidence = any(_string_list(finding.get(field)) for field in ("findings", "risks", "policy_implications"))
        if not has_evidence and not str(finding.get("content") or "").strip():
            return _error("structured_finding_evidence_missing", field=f"structured_findings.{index}")
    if handoff.get("unresolved_gaps"):
        return _error("policy_handoff_unresolved_gaps")
    hints = handoff.get("retrieval_hints")
    if not isinstance(hints, dict):
        return _error("retrieval_hints_missing")
    if not _string_list(hints.get("collection_families")):
        return _error("retrieval_hints_incomplete", field="retrieval_hints.collection_families")
    return {"success": True}

