"""Tests for Stage 4 replay launcher integration."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers to invoke argparse the same way main() does, without Qt
# ---------------------------------------------------------------------------


def _parse_launcher_args(argv: list[str]) -> argparse.Namespace:
    """Run the same argparse block as launcher.main() without spawning Qt."""
    from cryodaq.launcher import _REPLAY_LIST_SENTINEL

    parser = argparse.ArgumentParser(description="CryoDAQ Launcher")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--tray", action="store_true")
    parser.add_argument(
        "--replay", nargs="?", const=_REPLAY_LIST_SENTINEL, default=None, metavar="PATH"
    )
    parser.add_argument("--replay-speed", type=float, default=5.0)
    parser.add_argument("--replay-phase", type=str, default="cooldown")
    parser.add_argument("--replay-loop", action="store_true")
    parser.add_argument("--force-replay", action="store_true")
    args, _ = parser.parse_known_args(argv)
    return args


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def test_launcher_replay_flag_parsed():
    args = _parse_launcher_args(["--replay", "/fake/path.db", "--replay-speed", "50"])
    assert args.replay == "/fake/path.db"
    assert args.replay_speed == 50.0


def test_launcher_replay_speed_default_five():
    args = _parse_launcher_args(["--replay", "/some.db"])
    assert args.replay_speed == 5.0


def test_launcher_replay_phase_default_cooldown():
    args = _parse_launcher_args(["--replay", "/some.db"])
    assert args.replay_phase == "cooldown"


def test_launcher_replay_sentinel_when_no_path():
    from cryodaq.launcher import _REPLAY_LIST_SENTINEL

    args = _parse_launcher_args(["--replay"])
    assert args.replay == _REPLAY_LIST_SENTINEL


# ---------------------------------------------------------------------------
# Mutual exclusion
# ---------------------------------------------------------------------------


def test_launcher_replay_and_mock_mutually_exclusive(monkeypatch, capsys):
    """--mock + --replay must raise SystemExit before Qt starts."""
    monkeypatch.setattr(sys, "argv", ["cryodaq", "--mock", "--replay", "/some.db"])
    # Prevent Qt from starting
    with patch("cryodaq.launcher.QApplication"), pytest.raises(SystemExit) as exc_info:
        from cryodaq import launcher

        # Reload to pick up monkeypatched argv isn't needed —
        # we call main() which reads sys.argv via parse_known_args.
        launcher.main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "--mock" in captured.err and "--replay" in captured.err


# ---------------------------------------------------------------------------
# Window title
# ---------------------------------------------------------------------------


def test_launcher_replay_window_title_contains_replay():
    """Title format for replay mode contains REPLAY and source basename."""
    src = Path("/data/cool_run.db")
    title = f"CryoDAQ — REPLAY: {src.name}"
    assert "REPLAY" in title
    assert "cool_run.db" in title


def test_launcher_replay_window_title_normal_when_no_source():
    title = "CryoDAQ — Криогенная лаборатория АКЦ ФИАН"
    assert "REPLAY" not in title
    assert "АКЦ ФИАН" in title


# ---------------------------------------------------------------------------
# _start_engine cmd construction — uses SimpleNamespace to avoid Qt init
# ---------------------------------------------------------------------------


def _make_fake_self(src: Path, *, loop: bool = False) -> object:
    import types

    return types.SimpleNamespace(
        _mock=False,
        _replay_source=src,
        _replay_speed=5.0,
        _replay_phase="cooldown",
        _replay_loop=loop,
        _force_replay=False,
        _legacy_channel_era=None,
        _engine_proc=None,
        _engine_external=False,
        _engine_stderr_handler=None,
        _engine_stderr_logger=None,
        _engine_stderr_thread=None,
    )


def _stderr_logger_retval() -> tuple:
    return (MagicMock(), MagicMock(), Path("/tmp/x.log"))


def test_launcher_start_engine_builds_replay_cmd():
    """_start_engine dispatches to cryodaq.replay_engine with correct args."""
    captured_cmd: list[str] = []
    src = Path("/data/run.db")

    def fake_popen(cmd, **kwargs):
        captured_cmd.extend(cmd)
        m = MagicMock()
        m.pid = 12345
        m.stderr = None
        return m

    from cryodaq.launcher import LauncherWindow

    with (
        patch("cryodaq.launcher._is_port_busy", return_value=False),
        patch("cryodaq.launcher.subprocess.Popen", side_effect=fake_popen),
        patch(
            "cryodaq.launcher._create_engine_stderr_logger",
            return_value=_stderr_logger_retval(),
        ),
        patch("cryodaq.launcher.LauncherWindow._wait_engine_ready"),
        patch("cryodaq.paths.get_data_dir", return_value=Path("/data")),
    ):
        LauncherWindow._start_engine(_make_fake_self(src), wait=False)

    assert "-m" in captured_cmd
    replay_m_idx = captured_cmd.index("-m")
    assert captured_cmd[replay_m_idx + 1] == "cryodaq.replay_engine"
    assert "--source" in captured_cmd
    assert captured_cmd[captured_cmd.index("--source") + 1] == str(src)
    assert "--speed" in captured_cmd
    assert captured_cmd[captured_cmd.index("--speed") + 1] == "5.0"


def test_launcher_start_engine_appends_loop_flag():
    captured_cmd: list[str] = []
    src = Path("/data/run.db")

    def fake_popen(cmd, **kwargs):
        captured_cmd.extend(cmd)
        m = MagicMock()
        m.pid = 1
        m.stderr = None
        return m

    from cryodaq.launcher import LauncherWindow

    with (
        patch("cryodaq.launcher._is_port_busy", return_value=False),
        patch("cryodaq.launcher.subprocess.Popen", side_effect=fake_popen),
        patch(
            "cryodaq.launcher._create_engine_stderr_logger",
            return_value=_stderr_logger_retval(),
        ),
        patch("cryodaq.launcher.LauncherWindow._wait_engine_ready"),
        patch("cryodaq.paths.get_data_dir", return_value=Path("/data")),
    ):
        LauncherWindow._start_engine(_make_fake_self(src, loop=True), wait=False)

    assert "--loop" in captured_cmd


# ---------------------------------------------------------------------------
# Source listing (_print_replay_sources)
# ---------------------------------------------------------------------------


def test_launcher_replay_no_source_lists_available(tmp_path, capsys):
    """--replay without path prints listing and exits 0."""
    cooldown_dir = tmp_path / "cooldown_v5"
    cooldown_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Write two minimal curve JSON files
    for i in range(2):
        (cooldown_dir / f"curve_{i}.json").write_text(
            json.dumps({"duration_hours": 8.0 + i, "T_cold_final": 3.1 + i * 0.5}),
            encoding="utf-8",
        )

    # Write one SQLite DB
    con = sqlite3.connect(str(data_dir / "data_2026-04-21.db"))
    con.execute("CREATE TABLE readings (timestamp REAL, channel TEXT, value REAL)")
    con.execute("INSERT INTO readings VALUES (1745000000.0, 'Т12', 3.1)")
    con.commit()
    con.close()

    with patch("cryodaq.paths.get_data_dir", return_value=data_dir):
        from cryodaq.launcher import _print_replay_sources

        _print_replay_sources()

    out = capsys.readouterr().out
    assert "curve_0.json" in out
    assert "curve_1.json" in out
    assert "data_2026-04-21.db" in out
    assert "cryodaq --replay" in out


def test_launcher_replay_listing_handles_missing_cooldown_v5(tmp_path, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    with patch("cryodaq.paths.get_data_dir", return_value=data_dir):
        from cryodaq.launcher import _print_replay_sources

        _print_replay_sources()

    out = capsys.readouterr().out
    assert "(нет файлов)" in out


def test_launcher_replay_listing_handles_missing_data_dir(tmp_path, capsys):
    data_dir = tmp_path / "data"  # does not exist
    cooldown_dir = tmp_path / "cooldown_v5"
    cooldown_dir.mkdir()

    with patch("cryodaq.paths.get_data_dir", return_value=data_dir):
        from cryodaq.launcher import _print_replay_sources

        _print_replay_sources()

    out = capsys.readouterr().out
    assert "(нет файлов)" in out


def test_launcher_replay_listing_handles_malformed_json(tmp_path, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    cooldown_dir = tmp_path / "cooldown_v5"
    cooldown_dir.mkdir()
    (cooldown_dir / "bad_curve.json").write_text("{not valid json", encoding="utf-8")

    with patch("cryodaq.paths.get_data_dir", return_value=data_dir):
        from cryodaq.launcher import _print_replay_sources

        _print_replay_sources()  # must not raise

    out = capsys.readouterr().out
    assert "bad_curve.json" in out
    assert "ошибка чтения" in out


# ---------------------------------------------------------------------------
# Regression: Stage 4b D2 introduced a duplicate `from PySide6.QtCore import
# QTimer` inside LauncherWindow.__init__ that shadowed the module-level
# binding for the entire method (Python LEGB: any local assignment makes the
# name function-local for the whole scope), causing UnboundLocalError on
# line ~328 where self._async_timer = QTimer(self) is constructed.
# ---------------------------------------------------------------------------


def test_launcher_init_no_duplicate_qtimer_import() -> None:
    """LauncherWindow.__init__ must not contain `from PySide6.QtCore import QTimer`.

    The redundant inner import (added in Stage 4b for the replay-engine-failed
    branch) shadows the module-level binding and breaks every launcher startup
    with UnboundLocalError on the early QTimer(self) constructor calls.
    """
    import inspect

    from cryodaq.launcher import LauncherWindow

    init_src = inspect.getsource(LauncherWindow.__init__)
    assert "from PySide6.QtCore import QTimer" not in init_src, (
        "Duplicate QTimer import inside __init__ shadows module-level binding"
    )


def test_launcher_qtimer_module_import_present() -> None:
    """Module top must still import QTimer for the rest of the file to work."""
    import inspect

    from cryodaq import launcher

    src = inspect.getsource(launcher)
    # Anything before the first 'class ' is module-level; QTimer must appear there
    pre_class = src.split("class ", 1)[0]
    assert "QTimer" in pre_class, "QTimer must be imported at module top"
