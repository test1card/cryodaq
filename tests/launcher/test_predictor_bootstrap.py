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
import os
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
        _mock_thermal_simulator=None,
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
        _wait_engine_ready=MagicMock(),
        _bridge=MagicMock(),
        _replay_session_verified=False,
    )
    # _check_predictor_bootstrap_hint will be patched at call-site
    ns._check_predictor_bootstrap_hint = lambda: None
    return ns


def _pipe_backed_process(pid: int) -> MagicMock:
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    process = MagicMock()
    process.pid = pid
    process.stderr = os.fdopen(read_fd, "rb", buffering=0)
    return process


def test_mock_environment_true_is_shared_across_launcher_and_engine(monkeypatch) -> None:
    import cryodaq.engine as engine
    import cryodaq.launcher as launcher

    monkeypatch.setenv("CRYODAQ_MOCK", "true")

    assert launcher._resolve_mock_mode is engine._resolve_mock_mode
    assert launcher._resolve_mock_mode(cli_mock=False) is True
    assert engine._resolve_mock_mode(cli_mock=False) is True


def test_mock_environment_contract_accepts_booleans_and_rejects_malformed(monkeypatch) -> None:
    from cryodaq.engine import _resolve_mock_mode

    for value in ("1", "true", "yes", "on", " TRUE "):
        monkeypatch.setenv("CRYODAQ_MOCK", value)
        assert _resolve_mock_mode(cli_mock=False) is True
    for value in ("0", "false", "no", "off", " FALSE "):
        monkeypatch.setenv("CRYODAQ_MOCK", value)
        assert _resolve_mock_mode(cli_mock=False) is False
        assert _resolve_mock_mode(cli_mock=True) is True

    monkeypatch.setenv("CRYODAQ_MOCK", "tru")
    with pytest.raises(ValueError, match="Invalid CRYODAQ_MOCK"):
        _resolve_mock_mode(cli_mock=True)


def test_start_engine_canonicalizes_mock_mode_in_child_environment(monkeypatch, tmp_path) -> None:
    import cryodaq.launcher as mod

    monkeypatch.setenv("CRYODAQ_MOCK", "true")

    for mock, expected in ((False, "0"), (True, "1")):
        captured: dict[str, object] = {}
        fake = _make_fake_self(replay_source=None)
        fake._mock = mock
        fake._mock_thermal_simulator = "127.0.0.1:43210" if mock else None

        def fake_popen(command, **kwargs):
            captured["command"] = command
            captured["environment"] = kwargs["env"]
            return _pipe_backed_process(99)

        try:
            with (
                patch("cryodaq.launcher._is_port_busy", return_value=False),
                patch("cryodaq.launcher.subprocess.Popen", side_effect=fake_popen),
                patch(
                    "cryodaq.launcher._create_engine_stderr_logger",
                    return_value=(None, None, Path("/tmp/x.log")),
                ),
                patch("cryodaq.launcher.LauncherWindow._wait_engine_ready"),
                patch("cryodaq.paths.get_data_dir", return_value=tmp_path),
                patch("cryodaq.logging_setup.read_debug_mode_from_qsettings", return_value=False),
            ):
                mod.LauncherWindow._start_engine(fake)
        finally:
            mod.LauncherWindow._close_engine_stderr_stream(fake)

        assert captured["environment"]["CRYODAQ_MOCK"] == expected
        assert ("--mock" in captured["command"]) is mock
        assert ("--mock-thermal-simulator" in captured["command"]) is mock
        if mock:
            option_index = captured["command"].index("--mock-thermal-simulator")
            assert captured["command"][option_index + 1] == "127.0.0.1:43210"


def test_start_engine_calls_hint_in_non_replay_path() -> None:
    """_start_engine must call _check_predictor_bootstrap_hint when not in replay mode."""
    import cryodaq.launcher as mod

    fake = _make_fake_self(replay_source=None)
    hint_called = []

    def _spy_hint():
        hint_called.append(True)

    fake._check_predictor_bootstrap_hint = _spy_hint

    try:
        with (
            patch("cryodaq.launcher._is_port_busy", return_value=False),
            patch("cryodaq.launcher.subprocess.Popen") as mock_popen,
            patch("cryodaq.launcher._create_engine_stderr_logger", return_value=(None, None, Path("/tmp/x.log"))),
            patch("cryodaq.launcher.LauncherWindow._wait_engine_ready"),
            patch("cryodaq.paths.get_data_dir", return_value=Path("/tmp")),
        ):
            mock_popen.return_value = _pipe_backed_process(99)
            mod.LauncherWindow._start_engine(fake)
    finally:
        mod.LauncherWindow._close_engine_stderr_stream(fake)

    assert hint_called, "_check_predictor_bootstrap_hint was NOT called in non-replay path"


def test_hint_is_not_triggered_in_replay_branch() -> None:
    """_start_engine must NOT call _check_predictor_bootstrap_hint in replay mode."""
    import cryodaq.launcher as mod

    fake = _make_fake_self(replay_source=Path("/data/cool_run.db"))
    hint_called = []

    def _spy_hint():
        hint_called.append(True)

    fake._check_predictor_bootstrap_hint = _spy_hint

    try:
        with (
            patch("cryodaq.launcher._is_port_busy", return_value=False),
            patch("cryodaq.launcher.subprocess.Popen") as mock_popen,
            patch("cryodaq.launcher._create_engine_stderr_logger", return_value=(None, None, Path("/tmp/x.log"))),
            patch("cryodaq.launcher.LauncherWindow._wait_engine_ready"),
            patch("cryodaq.paths.get_data_dir", return_value=Path("/tmp")),
        ):
            mock_popen.return_value = _pipe_backed_process(99)
            mod.LauncherWindow._start_engine(fake)
    finally:
        mod.LauncherWindow._close_engine_stderr_stream(fake)

    assert not hint_called
    fake._bridge.bind_verified_replay_session.assert_called_once_with(
        session_id=fake._replay_session_id,
        source=str(fake._replay_source),
        speed=float(fake._replay_speed),
    )
    assert fake._replay_session_verified is True


# ---------------------------------------------------------------------------
# Behaviour tests — direct method call, no Qt
# ---------------------------------------------------------------------------


def _make_fake_launcher() -> types.SimpleNamespace:
    """Minimal stand-in for LauncherWindow with no Qt dependencies."""
    return types.SimpleNamespace()


def test_launcher_logs_bootstrap_hint_when_missing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
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


def test_launcher_silent_when_model_deployed(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
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


def test_launcher_silent_when_canonical_missing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """No hint logged when canonical source is absent (nothing to bootstrap from)."""
    # Neither cooldown_v5/ nor data/cooldown_model/ exist under tmp_path

    import cryodaq.launcher as mod

    fake = _make_fake_launcher()
    with patch("cryodaq.paths.get_project_root", return_value=tmp_path):
        with caplog.at_level(logging.INFO, logger="cryodaq.launcher"):
            mod.LauncherWindow._check_predictor_bootstrap_hint(fake)

    assert not any("bootstrap-predictor" in r.message for r in caplog.records)
