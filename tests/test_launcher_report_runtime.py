from __future__ import annotations

from pathlib import Path

import pytest


def _config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    import cryodaq.paths

    monkeypatch.setattr(cryodaq.paths, "get_config_dir", lambda: tmp_path)
    return tmp_path


def test_missing_agent_config_still_requires_report_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.launcher import _assistant_runtime_required

    _config_dir(monkeypatch, tmp_path)
    assert _assistant_runtime_required() is True


def test_explicit_automatic_false_and_llm_disabled_skips_assistant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.launcher import _assistant_runtime_required

    config = _config_dir(monkeypatch, tmp_path)
    (config / "agent.yaml").write_text(
        "agent:\n  enabled: false\nreporting:\n  automatic_enabled: false\n",
        encoding="utf-8",
    )
    assert _assistant_runtime_required() is False


def test_llm_enabled_starts_assistant_when_automatic_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.launcher import _assistant_runtime_required

    config = _config_dir(monkeypatch, tmp_path)
    (config / "agent.yaml").write_text(
        "agent:\n  enabled: true\nreporting:\n  automatic_enabled: false\n",
        encoding="utf-8",
    )
    assert _assistant_runtime_required() is True


def test_broken_agent_config_preserves_default_automatic_reporting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.launcher import _assistant_runtime_required

    config = _config_dir(monkeypatch, tmp_path)
    (config / "agent.yaml").write_text("agent: [", encoding="utf-8")
    assert _assistant_runtime_required() is True


def test_replay_mode_does_not_default_to_automatic_reporting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.launcher import _assistant_runtime_required

    _config_dir(monkeypatch, tmp_path)
    assert _assistant_runtime_required(experiment_mode=False) is False


def test_string_false_does_not_enable_llm_or_disable_reporting_strictness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.launcher import _assistant_runtime_required

    config = _config_dir(monkeypatch, tmp_path)
    (config / "agent.yaml").write_text(
        "agent:\n  enabled: 'false'\nreporting:\n  automatic_enabled: false\n",
        encoding="utf-8",
    )

    assert _assistant_runtime_required() is False
