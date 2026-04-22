from unittest.mock import MagicMock, patch

import pytest

from app.agents.vector.model_loader import (
    LocalSentenceTransformerEmbeddingFunction,
    download_model_if_needed,
    load_model,
)


def test_download_model_if_needed_requires_explicit_opt_in_for_remote_fetch(monkeypatch):
    monkeypatch.delenv("POLICY_AGENT_ALLOW_MODEL_DOWNLOAD", raising=False)

    with patch("app.agents.vector.model_loader.is_model_cached", return_value=False):
        with pytest.raises(RuntimeError, match="POLICY_AGENT_ALLOW_MODEL_DOWNLOAD=1"):
            download_model_if_needed("intfloat/e5-base")


def test_load_model_uses_local_only_safe_defaults():
    with patch("app.agents.vector.model_loader.is_model_cached", return_value=True):
        with patch("app.agents.vector.model_loader.has_safetensors_weights", return_value=True):
            with patch("sentence_transformers.SentenceTransformer") as sentence_transformer:
                load_model("intfloat/e5-base", revision="abc123")

    sentence_transformer.assert_called_once_with(
        "intfloat/e5-base",
        revision="abc123",
        local_files_only=True,
        trust_remote_code=False,
        model_kwargs={"use_safetensors": True},
    )


def test_local_embedding_function_uses_preloaded_model():
    model = MagicMock()
    model.encode.return_value = [[0.1, 0.2], [0.3, 0.4]]
    embedding_fn = LocalSentenceTransformerEmbeddingFunction(model)

    result = embedding_fn(["doc one", "doc two"])

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    model.encode.assert_called_once_with(
        ["doc one", "doc two"],
        normalize_embeddings=True,
    )
