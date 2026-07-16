import hashlib
import json

from scripts.decide_init25_direction import decide


def _digest(report):
    encoded = json.dumps(report, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _reports(*, complete=False):
    reports = {
        "admission": {
            "schema_version": "1.0", "initiative": "INIT-25",
            "gate": "vertical_pilot_admission", "eligible": complete,
        },
        "semantic": {
            "schema_version": "1.0", "initiative": "INIT-25",
            "gate": "paired_semantic_evidence", "complete": complete,
            "case_count": 12, "paired_case_count": 12 if complete else 0,
        },
        "operational": {
            "schema_version": "1.0", "initiative": "INIT-25",
            "gate": "operational_readiness", "ready": complete,
            "campaign_executed": complete,
        },
        "coordination": {
            "schema_version": "1.0", "initiative": "INIT-25",
            "gate": "coordination_ownership", "responsibility_removed": complete,
        },
    }
    reports["adjudication"] = {
        "schema_version": "1.0", "initiative": "INIT-25",
        "gate": "semantic_adjudication", "decision": "passed" if complete else "not_assessed",
        "semantic_report_sha256": _digest(reports["semantic"]),
    }
    return reports


def _decide(reports):
    return decide(reports, {name: _digest(report) for name, report in reports.items()})


def test_current_missing_evidence_pauses_without_closing_initiative() -> None:
    result = _decide(_reports())

    assert result["direction"] == "pause"
    assert result["initiative_open"] is True
    assert result["cutover_authorized"] is False


def test_complete_independent_evidence_can_continue_without_cutover() -> None:
    result = _decide(_reports(complete=True))

    assert result["direction"] == "continue"
    assert result["blockers"] == []
    assert result["cutover_authorized"] is False


def test_partial_observed_evidence_narrows_scope() -> None:
    reports = _reports(complete=True)
    reports["operational"]["ready"] = False
    result = _decide(reports)

    assert result["direction"] == "narrow"
    assert "operational_readiness_passed" in result["blockers"]


def test_tampered_or_untyped_report_fails_closed() -> None:
    reports = _reports(complete=True)
    digests = {name: _digest(report) for name, report in reports.items()}
    reports["admission"]["eligible"] = False
    assert decide(reports, digests)["direction"] == "pause"

    reports = _reports(complete=True)
    reports["semantic"]["gate"] = "manual_claim"
    assert _decide(reports)["direction"] == "pause"


def test_adjudication_must_reference_exact_semantic_report() -> None:
    reports = _reports(complete=True)
    reports["adjudication"]["semantic_report_sha256"] = "0" * 64

    result = _decide(reports)

    assert result["direction"] == "narrow"
    assert "independent_semantic_adjudication_passed" in result["blockers"]
