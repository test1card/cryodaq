"""Tests for Stage 5 predictor bootstrap hint in launcher.

Covers:
  1. Structural: _check_predictor_bootstrap_hint exists and is called from _start_engine
     in non-replay mode.
  2. Hint fires when deployed path is missing but canonical source is present.
  3. Silent when deployed model already exists.
  4. Silent when canonical source is missing (no hint if nothing to bootstrap from).
"""

from __future__ import annotations

import inspect
import logging
import types
from pathlib import Path
from unittest.mock import patch

import pytest

LAUNCHER_MODULE = "cryodaq.launcher"


# ---------------------------------------------------------------------------
# Structural tests — source inspection, no QApplication
# ---------------------------------------------------------------------------


def test_check_predictor_bootstrap_hint_exists() -> None:
    import cryodaq.launcher as mod

    assert hasattr(mod.LauncherWindow, "_check_predictor_bootstrap_hint")


def test_start_engine_calls_hint_in_non_replay_path() -> None:
    import cryodaq.launcher as mod

    src = inspect.getsource(mod.LauncherWindow._start_engine)
    assert "_check_predictor_bootstrap_hint" in src
    assert "replay_source" in src


def test_hint_is_not_triggered_in_replay_branch() -> None:
    """The guard must come before the replay/non-replay branch split."""
    import cryodaq.launcher as mod

    src = inspect.getsource(mod.LauncherWindow._start_engine)
    hint_idx = src.find("_check_predictor_bootstrap_hint")
    replay_guard_idx = src.find("replay_source")
    # hint call should appear inside the non-replay guard (i.e., after checking
    # replay_source), not after the else: that builds the real-engine command
    assert hint_idx < replay_guard_idx + 50  # both on the same early guard block


# ---------------------------------------------------------------------------
# Behaviour tests — direct method call, no Qt
# ---------------------------------------------------------------------------


def _make_fake_launcher() -> types.SimpleNamespace:
    """Minimal stand-in for LauncherWindow with no Qt dependencies."""
    return types.SimpleNamespace()


def test_launcher_logs_bootstrap_hint_when_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Hint logged when deployed model absent but canonical source present."""
    canonical = tmp_path / "cooldown_v5" / "predictor_model.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("{}", encoding="utf-8")
    # deployed does NOT exist — tmp_path/data/cooldown_model/ not created

    import cryodaq.launcher as mod

    fake = _make_fake_launcher()
    with patch("cryodaq.paths.get_project_root", return_value=tmp_path):
        with caplog.at_level(logging.INFO, logger="cryodaq.launcher"):
            mod.LauncherWindow._check_predictor_bootstrap_hint(fake)

    assert any("bootstrap-predictor" in r.message for r in caplog.records)
    assert all(r.levelno == logging.INFO for r in caplog.records if "bootstrap" in r.message)


def test_launcher_silent_when_model_deployed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """No hint logged when deployed model already exists."""
    canonical = tmp_path / "cooldown_v5" / "predictor_model.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("{}", encoding="utf-8")

    deployed = tmp_path / "data" / "cooldown_model" / "predictor_model.json"
    deployed.parent.mkdir(parents=True)
    deployed.write_text("{}", encoding="utf-8")

    import cryodaq.launcher as mod

    fake = _make_fake_launcher()
    with patch("cryodaq.paths.get_project_root", return_value=tmp_path):
        with caplog.at_level(logging.INFO, logger="cryodaq.launcher"):
            mod.LauncherWindow._check_predictor_bootstrap_hint(fake)

    assert not any("bootstrap-predictor" in r.message for r in caplog.records)


def test_launcher_silent_when_canonical_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """No hint logged when canonical source is absent (nothing to bootstrap from)."""
    # Neither cooldown_v5/ nor data/cooldown_model/ exist under tmp_path

    import cryodaq.launcher as mod

    fake = _make_fake_launcher()
    with patch("cryodaq.paths.get_project_root", return_value=tmp_path):
        with caplog.at_level(logging.INFO, logger="cryodaq.launcher"):
            mod.LauncherWindow._check_predictor_bootstrap_hint(fake)

    assert not any("bootstrap-predictor" in r.message for r in caplog.records)
