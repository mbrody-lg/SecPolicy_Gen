"""Keep isolated Docker service copies of the workload verifier in lockstep."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_workload_token_implementation_is_identical_across_services():
    paths = [ROOT / service / "app" / "workload_token.py" for service in (
        "context-agent", "policy-agent", "validator-agent",
    )]
    contents = [path.read_bytes() for path in paths]
    assert all(content == contents[0] for content in contents[1:])
