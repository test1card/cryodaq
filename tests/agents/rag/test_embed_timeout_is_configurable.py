"""The embedding timeout must follow the model, not a constant from 2026-05.

`EmbeddingsClient` defaults to 30 s, which was right for qwen3-embedding:0.6b
on a local GPU. Retrieval then moved to qwen3-embedding:8b on the owner's
server, where a single embed call measures 20-34 s — straddling that default.
The result is not a clean failure: `embed()` returns [] on timeout, the indexer
substitutes a zero vector, and the chunk is silently unsearchable. The rebuild
of 2026-09-05 19:53 lost six chunks exactly this way.

This is the same defect as the generation timeout left at 120 s for a model
needing 280 — a timeout sized for equipment that was replaced.
"""

from __future__ import annotations

import pytest

from cryodaq.agents.rag.cli import _DEFAULT_EMBED_TIMEOUT_S, _make_embeddings


def _timeout_of(client) -> float:
    return client._client._timeout_s


def test_the_configured_timeout_reaches_the_client() -> None:
    client = _make_embeddings(
        {
            "ollama_base_url": "http://127.0.0.1:11434",
            "embedding_model": "qwen3-embedding:8b",
            "embed_timeout_s": 240.0,
        }
    )
    assert _timeout_of(client) == 240.0


def test_the_default_clears_the_measured_latency() -> None:
    """34 s was the slowest single call measured; the default must not be near it."""
    client = _make_embeddings({})
    measured_worst_case = 34.0
    assert _timeout_of(client) == _DEFAULT_EMBED_TIMEOUT_S
    assert _DEFAULT_EMBED_TIMEOUT_S > 3 * measured_worst_case, (
        f"default {_DEFAULT_EMBED_TIMEOUT_S}s leaves no headroom over the "
        f"{measured_worst_case}s measured worst case; chunks will time out into "
        "zero vectors"
    )


def test_the_old_thirty_second_default_would_not_pass() -> None:
    """Negative control: the value that actually lost six chunks must fail."""
    assert not (30.0 > 3 * 34.0)


def test_the_shipped_config_sets_it() -> None:
    """A default is not enough — the stand's own config must carry the value."""
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[3]
    cfg = yaml.safe_load((root / "config" / "rag.yaml").read_text(encoding="utf-8"))
    rag = cfg["rag"]
    assert "embed_timeout_s" in rag, "config/rag.yaml does not set embed_timeout_s"
    assert float(rag["embed_timeout_s"]) >= 120.0


def test_an_absent_key_falls_back() -> None:
    """Rewritten 2026-09-05 after review.

    This was parametrised over ``["", None]`` and then put NEITHER value into
    the config — both cases popped a key that was never there, so it tested
    the absent-key path twice under two misleading names.
    """
    client = _make_embeddings({"embedding_model": "qwen3-embedding:8b"})
    assert _timeout_of(client) == _DEFAULT_EMBED_TIMEOUT_S


@pytest.mark.parametrize("bad", ["", None, "not-a-number", []])
def test_an_unusable_value_falls_back_rather_than_crashing(bad) -> None:
    """The values are now actually placed in the config, as the name claims.

    A malformed embed_timeout_s must not stop a rebuild before it starts: the
    fallback is a working default, not a traceback.
    """
    cfg = {"embedding_model": "qwen3-embedding:8b", "embed_timeout_s": bad}
    client = _make_embeddings(cfg)
    assert _timeout_of(client) == _DEFAULT_EMBED_TIMEOUT_S
