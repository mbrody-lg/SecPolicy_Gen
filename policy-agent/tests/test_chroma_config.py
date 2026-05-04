import pytest

from app.agents.vector.chroma.config import get_chroma_host, get_chroma_port


def test_get_chroma_host_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv("CHROMA_HOST", raising=False)

    assert get_chroma_host(default="localhost") == "localhost"


def test_get_chroma_host_rejects_blank_override(monkeypatch):
    monkeypatch.setenv("CHROMA_HOST", " ")

    with pytest.raises(ValueError, match="CHROMA_HOST"):
        get_chroma_host(default="localhost")


@pytest.mark.parametrize("value", ["0", "65536", "not-a-number"])
def test_get_chroma_port_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("CHROMA_PORT", value)

    with pytest.raises(ValueError, match="CHROMA_PORT"):
        get_chroma_port(default="8000")


def test_get_chroma_port_accepts_valid_port(monkeypatch):
    monkeypatch.setenv("CHROMA_PORT", "8000")

    assert get_chroma_port(default="1234") == 8000
