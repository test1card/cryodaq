"""Tests for Stage 5 predictor bootstrap hint in launcher.

Covers:
  1. Structural: _check_predictor_bootstrap_hint exists and is called from _start_engine
     in non-replay mode.
  2. Hint fires when deployed path is missing but canonical source is present.
  3. Silent when deployed model already exists.
  4. Silent when canonical source is missing (no hint if nothing to bootstrap from).
"""

from __future__ import annotations

import logging
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

LAUNCHER_MODULE = "cryodaq.launcher"


# ---------------------------------------------------------------------------
# Structural tests — source inspection, no QApplication
# ---------------------------------------------------------------------------


def test_check_predictor_bootstrap_hint_exists() -> None:
    import cryodaq.launcher as mod

    assert hasattr(mod.LauncherWindow, "_check_predictor_bootstrap_hint")


def _make_fake_self(replay_source=None):
    """Minimal stand-in for LauncherWindow for _start_engine calls."""
    ns = types.SimpleNamespace(
        _mock=False,
        _replay_source=replay_source,
        _replay_speed=5.0,
        _replay_phase="cooldown",
        _replay_loop=False,
        _force_replay=False,
        _legacy_channel_era=None,
        _engine_proc=None,
        _engine_external=False,
        _engine_stderr_handler=None,
        _engine_stderr_logger=None,
        _engine_stderr_thread=None,
        _restart_pending=False,
    )
    # _check_predictor_bootstrap_hint will be patched at call-site
    ns._check_predictor_bootstrap_hint = lambda: None
    return ns


def test_start_engine_calls_hint_in_non_replay_path() -> None:
    """_start_engine must call _check_predictor_bootstrap_hint when not in replay mode."""
    import cryodaq.launcher as mod

    fake = _make_fake_self(replay_source=None)
    hint_called = []

    def _spy_hint():
        hint_called.append(True)

    fake._check_predictor_bootstrap_hint = _spy_hint

    with (
        patch("cryodaq.launcher._is_port_busy", return_value=False),
        patch("cryodaq.launcher.subprocess.Popen") as mock_popen,
        patch("cryodaq.launcher._create_engine_stderr_logger", return_value=(None, None, Path("/tmp/x.log"))),
        patch("cryodaq.paths.get_data_dir", return_value=Path("/tmp")),
    ):
        m = MagicMock()
        m.pid = 99
        m.stderr = None
        mock_popen.return_value = m
        mod.LauncherWindow._start_engine(fake, wait=False)

    assert hint_called, "_check_predictor_bootstrap_hint was NOT called in non-replay path"


def test_hint_is_not_triggered_in_replay_branch() -> None:
    """_start_engine must NOT call _check_predictor_bootstrap_hint in replay mode."""
    import cryodaq.launcher as mod

    fake = _make_fake_self(replay_source=Path("/data/cool_run.db"))
    hint_called = []

    def _spy_hint():
        hint_called.append(True)

    fake._check_predictor_bootstrap_hint = _spy_hint

    with (
        patch("cryodaq.launcher._is_port_busy", return_value=False),
        patch("cryodaq.launcher.subprocess.Popen") as mock_popen,
        patch("cryodaq.launcher._create_engine_stderr_logger", return_value=(None, None, Path("/tmp/x.log"))),
        patch("cryodaq.paths.get_data_dir", return_value=Path("/tmp")),
    ):
        m = MagicMock()
        m.pid = 99
        m.stderr = None
        mock_popen.return_value = m
        mod.LauncherWindow._start_engine(fake, wait=False)

    assert not hint_called, "_check_predictor_bootstrap_hint was called in replay path — must be suppressed"


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
