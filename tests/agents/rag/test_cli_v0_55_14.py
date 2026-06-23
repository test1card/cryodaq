"""v0.55.14 — CLI tests for SCOPE 2 fixes.

- 2.2 — OllamaUnavailableError / OllamaModelMissingError surface as
  exit codes 3/4 with friendly stderr messages instead of bare
  tracebacks.
- 2.5 — `--config` flag accepted; rag.yaml.example fallback honoured
  when no live config exists.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cryodaq.agents.assistant.shared.ollama_client import (
    OllamaModelMissingError,
    OllamaUnavailableError,
)
from cryodaq.agents.rag import cli

# ---------------------------------------------------------------------------
# 2.5 — config resolution priority
# ---------------------------------------------------------------------------


def test_resolve_rag_config_path_prefers_explicit_override(tmp_path: Path) -> None:
    explicit = tmp_path / "custom.yaml"
    explicit.write_text("rag: {}", encoding="utf-8")
    path, label = cli._resolve_rag_config_path(explicit)
    assert path == explicit
    assert "custom.yaml" in label


def test_resolve_rag_config_path_explicit_missing_returns_none(tmp_path: Path) -> None:
    explicit = tmp_path / "does-not-exist.yaml"
    path, label = cli._resolve_rag_config_path(explicit)
    assert path is None
    assert "does-not-exist" in label


def test_resolve_rag_config_path_falls_back_to_yaml_example(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no live config exists, rag.yaml.example is the last-resort
    default — verifies the v0.55.14 fix for SCOPE 2 finding 2.5."""
    monkeypatch.setattr(cli, "get_config_dir", lambda: tmp_path)
    # Only the example file exists
    example = tmp_path / "rag.yaml.example"
    example.write_text("rag: {}", encoding="utf-8")

    path, label = cli._resolve_rag_config_path(None)

    assert path == example
    assert "rag.yaml.example" in label
    assert "defaults" in label.lower()


def test_resolve_rag_config_path_prefers_local_over_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "get_config_dir", lambda: tmp_path)
    (tmp_path / "rag.local.yaml").write_text("rag: {a: 1}", encoding="utf-8")
    (tmp_path / "rag.yaml").write_text("rag: {b: 2}", encoding="utf-8")
    (tmp_path / "rag.yaml.example").write_text("rag: {c: 3}", encoding="utf-8")

    path, label = cli._resolve_rag_config_path(None)

    assert path.name == "rag.local.yaml"


def test_resolve_rag_config_path_prefers_yaml_over_example(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "get_config_dir", lambda: tmp_path)
    (tmp_path / "rag.yaml").write_text("rag: {}", encoding="utf-8")
    (tmp_path / "rag.yaml.example").write_text("rag: {}", encoding="utf-8")

    path, label = cli._resolve_rag_config_path(None)

    assert path.name == "rag.yaml"


def test_resolve_rag_config_path_no_files_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "get_config_dir", lambda: tmp_path)
    path, label = cli._resolve_rag_config_path(None)
    assert path is None
    assert "no rag config found" in label


def test_load_rag_config_handles_none_path() -> None:
    assert cli._load_rag_config(None) == {}


def test_load_rag_config_handles_missing_path(tmp_path: Path) -> None:
    assert cli._load_rag_config(tmp_path / "nope.yaml") == {}


# ---------------------------------------------------------------------------
# 2.2 — Ollama error surface: index_main and search_main must catch
# OllamaModelMissingError (exit 3) and OllamaUnavailableError (exit 4)
# and emit friendly stderr without a traceback.
# ---------------------------------------------------------------------------


def test_ollama_error_classes_imported_at_module_load() -> None:
    """The CLI module must import the Ollama error classes so the
    try/except blocks in index_main / search_main can catch them."""
    assert OllamaModelMissingError in cli.__dict__.values() or hasattr(
        cli, "OllamaModelMissingError"
    )
    assert OllamaUnavailableError in cli.__dict__.values() or hasattr(
        cli, "OllamaUnavailableError"
    )


_INDEX_MAIN_FRIENDLY: dict[type, list[str]] = {
    # index_main messages — from cli.py OllamaModelMissingError handler
    OllamaModelMissingError: [
        "error: embedding model not available in Ollama:",
        "hint:",
        "ollama pull",
    ],
    # index_main messages — from cli.py OllamaUnavailableError handler
    OllamaUnavailableError: [
        "error: cannot reach Ollama:",
        "hint:",
    ],
}


@pytest.mark.parametrize(
    "error_cls,expected_exit",
    [
        (OllamaModelMissingError, 3),
        (OllamaUnavailableError, 4),
    ],
)
def test_index_main_ollama_errors_exit_with_friendly_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    error_cls: type,
    expected_exit: int,
) -> None:
    """index_main must catch Ollama errors, print a friendly message to
    stderr (no bare traceback), and exit with the documented code."""
    # Provide a minimal config so CLI doesn't look up real paths.
    cfg = tmp_path / "rag.yaml"
    cfg.write_text("rag: {}", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["cryodaq-rag-index", "--config", str(cfg)])
    monkeypatch.setattr(
        cli,
        "build_index",
        AsyncMock(side_effect=error_cls("test error")),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.index_main()

    assert exc_info.value.code == expected_exit, (
        f"expected exit {expected_exit}, got {exc_info.value.code}"
    )
    captured = capsys.readouterr()
    expected_substrings = _INDEX_MAIN_FRIENDLY[error_cls]
    for substr in expected_substrings:
        assert substr in captured.err, (
            f"expected {substr!r} in stderr for {error_cls.__name__}; got: {captured.err!r}"
        )
    assert "Traceback (most recent call last)" not in captured.err, (
        f"bare traceback must not appear in stderr; got: {captured.err!r}"
    )


_SEARCH_MAIN_FRIENDLY: dict[type, list[str]] = {
    # search_main messages — from cli.py OllamaModelMissingError handler
    OllamaModelMissingError: [
        "error: embedding model not available:",
        "hint:",
        "ollama pull",
    ],
    # search_main messages — from cli.py OllamaUnavailableError handler
    OllamaUnavailableError: [
        "error: cannot reach Ollama:",
        "hint:",
    ],
}


@pytest.mark.parametrize(
    "error_cls,expected_exit",
    [
        (OllamaModelMissingError, 3),
        (OllamaUnavailableError, 4),
    ],
)
def test_search_main_ollama_errors_exit_with_friendly_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    error_cls: type,
    expected_exit: int,
) -> None:
    """search_main must catch Ollama errors, print a friendly message to
    stderr (no bare traceback), and exit with the documented code."""
    cfg = tmp_path / "rag.yaml"
    cfg.write_text("rag: {}", encoding="utf-8")

    monkeypatch.setattr(
        sys, "argv", ["cryodaq-rag-search", "--config", str(cfg), "test query"]
    )
    monkeypatch.setattr(
        cli,
        "RagSearcher",
        lambda **_kwargs: _make_failing_searcher(error_cls),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.search_main()

    assert exc_info.value.code == expected_exit, (
        f"expected exit {expected_exit}, got {exc_info.value.code}"
    )
    captured = capsys.readouterr()
    expected_substrings = _SEARCH_MAIN_FRIENDLY[error_cls]
    for substr in expected_substrings:
        assert substr in captured.err, (
            f"expected {substr!r} in stderr for {error_cls.__name__}; got: {captured.err!r}"
        )
    assert "Traceback (most recent call last)" not in captured.err, (
        f"bare traceback must not appear in stderr; got: {captured.err!r}"
    )


def _make_failing_searcher(error_cls: type) -> object:
    """Return a fake RagSearcher whose search() raises the given Ollama error."""

    class _FailingSearcher:
        async def search(self, *_args: object, **_kwargs: object) -> list:
            raise error_cls("test error")

    return _FailingSearcher()
