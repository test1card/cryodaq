from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    import cryodaq.paths

    monkeypatch.setattr(cryodaq.paths, "get_config_dir", lambda: tmp_path)
    return tmp_path


def _disable_h2_and_llm(config_dir: Path) -> None:
    (config_dir / "agent.yaml").write_text(
        "agent:\n  enabled: false\nreporting:\n  automatic_enabled: false\n",
        encoding="utf-8",
    )


def _periodic_config(*, enabled: str = "true", interval: int = 3600) -> str:
    return (
        "telegram:\n"
        "  bot_token: '123456:abcdefghijklmnopqrstuvwxyzABCDE'\n"
        "  chat_id: -100123\n"
        "  timeout_s: 10\n"
        "  verify_ssl: true\n"
        "  send_cleared: true\n"
        "periodic_report:\n"
        f"  enabled: {enabled}\n"
        f"  report_interval_s: {interval}\n"
        "commands:\n"
        "  enabled: false\n"
    )


def test_periodic_only_live_mode_starts_assistant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.launcher import _assistant_runtime_required

    config = _config_dir(monkeypatch, tmp_path)
    _disable_h2_and_llm(config)
    (config / "notifications.yaml").write_text(_periodic_config(), encoding="utf-8")

    assert _assistant_runtime_required(experiment_mode=True) is True


def test_invalid_requested_periodic_starts_for_visible_degraded_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.launcher import _assistant_runtime_required

    config = _config_dir(monkeypatch, tmp_path)
    _disable_h2_and_llm(config)
    (config / "notifications.yaml").write_text(_periodic_config(interval=59), encoding="utf-8")

    assert _assistant_runtime_required(experiment_mode=True) is True


def test_nonboolean_enabled_does_not_start_periodic_only_assistant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from cryodaq.launcher import _assistant_runtime_required

    config = _config_dir(monkeypatch, tmp_path)
    _disable_h2_and_llm(config)
    secret = "123456:abcdefghijklmnopqrstuvwxyzABCDE"
    (config / "notifications.yaml").write_text(_periodic_config(enabled="'true'"), encoding="utf-8")

    assert _assistant_runtime_required(experiment_mode=True) is False
    assert "H3_CONFIG_REJECTED" in caplog.text
    assert secret not in caplog.text
    assert "invalid_enabled" not in caplog.text


def test_replay_never_probes_periodic_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.launcher import _assistant_runtime_required

    config = _config_dir(monkeypatch, tmp_path)
    _disable_h2_and_llm(config)
    (config / "notifications.yaml").write_text(_periodic_config(), encoding="utf-8")

    with patch(
        "cryodaq.periodic_config.probe_periodic_png",
        side_effect=AssertionError("replay must not probe H3"),
    ):
        assert _assistant_runtime_required(experiment_mode=False) is False


@pytest.mark.parametrize(
    ("requested", "experiment_mode", "expected"),
    [(True, True, "1"), (False, True, "0"), (True, False, "0")],
)
def test_assistant_spawn_overwrites_periodic_mode_environment(
    monkeypatch: pytest.MonkeyPatch,
    requested: bool,
    experiment_mode: bool,
    expected: str,
) -> None:
    from cryodaq.launcher import LauncherWindow

    proc = MagicMock(pid=123)
    popen = MagicMock(return_value=proc)
    monkeypatch.setenv("CRYODAQ_ASSISTANT_PERIODIC_MODE", "stale-inherited-value")
    window = SimpleNamespace(
        _assistant_experiment_mode=experiment_mode,
        _assistant_periodic_requested=requested,
        _assistant_proc=None,
    )

    with patch("cryodaq.launcher.subprocess.Popen", popen):
        LauncherWindow._start_assistant(window)  # type: ignore[arg-type]

    assert popen.call_args.kwargs["env"]["CRYODAQ_ASSISTANT_PERIODIC_MODE"] == expected


def test_frozen_periodic_only_starts_assistant_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryodaq.launcher import LauncherWindow

    popen = MagicMock(return_value=MagicMock(pid=123))
    window = SimpleNamespace(
        _assistant_experiment_mode=True,
        _assistant_periodic_requested=True,
        _assistant_periodic_health=None,
        _assistant_proc=None,
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/cryodaq/cryodaq.exe")

    with patch("cryodaq.launcher.subprocess.Popen", popen):
        LauncherWindow._start_assistant(window)  # type: ignore[arg-type]

    assert popen.call_args.args[0] == ["/opt/cryodaq/cryodaq.exe", "--mode=assistant"]
    assert popen.call_args.kwargs["env"]["CRYODAQ_ASSISTANT_PERIODIC_MODE"] == "1"


def test_windows_assistant_spawn_uses_hidden_sentinel_control_channel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.launcher as module

    popen = MagicMock(return_value=MagicMock(pid=123))
    window = SimpleNamespace(
        _assistant_experiment_mode=True,
        _assistant_periodic_requested=False,
        _assistant_proc=None,
    )
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr("cryodaq.paths.get_data_dir", lambda: tmp_path)

    with patch("cryodaq.launcher.subprocess.Popen", popen):
        module.LauncherWindow._start_assistant(window)  # type: ignore[arg-type]

    shutdown_path = window._assistant_shutdown_path
    assert window._assistant_shutdown_authority.path == shutdown_path
    assert shutdown_path.parent == tmp_path / "runtime"
    assert shutdown_path.exists() is False
    assert popen.call_args.kwargs["env"][module._ASSISTANT_SHUTDOWN_ENV] == str(shutdown_path.resolve())
    assert popen.call_args.kwargs["creationflags"] == module._WINDOWS_CREATE_NO_WINDOW


@pytest.mark.parametrize("link_data_root", [False, True], ids=["runtime-parent", "data-root"])
def test_windows_assistant_spawn_rejects_link_backed_sentinel_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    link_data_root: bool,
) -> None:
    import cryodaq.launcher as module

    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        if link_data_root:
            unsafe_root = tmp_path / "linked-data"
            unsafe_root.symlink_to(outside, target_is_directory=True)
        else:
            unsafe_root = tmp_path / "data"
            unsafe_root.mkdir()
            (unsafe_root / "runtime").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if os.name == "nt" and exc.winerror == 1314:
            pytest.skip("Windows account lacks symlink creation privilege")
        raise
    popen = MagicMock()
    window = SimpleNamespace(
        _assistant_experiment_mode=True,
        _assistant_periodic_requested=False,
        _assistant_proc=None,
    )
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr("cryodaq.paths.get_data_dir", lambda: unsafe_root)

    with patch("cryodaq.launcher.subprocess.Popen", popen):
        module.LauncherWindow._start_assistant(window)  # type: ignore[arg-type]

    popen.assert_not_called()
    assert window._assistant_proc is None
    assert window._assistant_shutdown_path is None


def _health(status: str, updated_at: float) -> SimpleNamespace:
    return SimpleNamespace(payload={"health": {"status": status, "updated_at": updated_at}})


def _monitor_window(tmp_path: Path) -> SimpleNamespace:
    from cryodaq.launcher import _PeriodicHealthObservation

    return SimpleNamespace(
        _assistant_periodic_requested=True,
        _assistant_periodic_data_dir=tmp_path,
        _assistant_periodic_health=_PeriodicHealthObservation(started_at=10.0),
        _periodic_reporting_fault=False,
        _periodic_health_read_failed_logged=False,
        _set_periodic_reporting_fault=MagicMock(),
        _clear_periodic_reporting_fault=MagicMock(),
    )


def test_startup_ready_record_is_baseline_until_strictly_newer_ready(
    tmp_path: Path,
) -> None:
    from cryodaq.launcher import LauncherWindow

    window = _monitor_window(tmp_path)
    with (
        patch("cryodaq.periodic_state.load_periodic_state", return_value=_health("ready", 100.0)),
        patch("cryodaq.launcher.time.time", return_value=100.0),
    ):
        LauncherWindow._check_periodic_health(window, monotonic_now=20.0)  # type: ignore[arg-type]
        LauncherWindow._check_periodic_health(window, monotonic_now=80.0)  # type: ignore[arg-type]

    window._clear_periodic_reporting_fault.assert_not_called()
    window._set_periodic_reporting_fault.assert_not_called()

    with (
        patch("cryodaq.periodic_state.load_periodic_state", return_value=_health("ready", 101.0)),
        patch("cryodaq.launcher.time.time", return_value=101.0),
    ):
        LauncherWindow._check_periodic_health(window, monotonic_now=81.0)  # type: ignore[arg-type]

    window._clear_periodic_reporting_fault.assert_called_once()


def test_first_valid_ready_after_missing_state_is_still_only_a_baseline() -> None:
    from cryodaq.launcher import _PeriodicHealthObservation

    observation = _PeriodicHealthObservation(started_at=0.0)
    assert (
        observation.observe(
            status=None,
            updated_at=None,
            monotonic_now=1.0,
            wall_now=100.0,
        )
        is False
    )
    assert (
        observation.observe(
            status="ready",
            updated_at=100.0,
            monotonic_now=2.0,
            wall_now=100.0,
        )
        is False
    )
    assert (
        observation.observe(
            status="ready",
            updated_at=101.0,
            monotonic_now=3.0,
            wall_now=101.0,
        )
        is True
    )


def test_wall_step_never_revalidates_unchanged_future_record_and_correction_recovers() -> None:
    from cryodaq.launcher import _PeriodicHealthObservation

    observation = _PeriodicHealthObservation(started_at=0.0)
    assert not observation.observe(
        status="ready",
        updated_at=100.0,
        monotonic_now=1.0,
        wall_now=100.0,
    )
    assert not observation.observe(
        status="ready",
        updated_at=1_000.0,
        monotonic_now=2.0,
        wall_now=100.0,
    )
    assert observation.high_water_updated_at == 100.0
    assert observation.last_observed_updated_at == 1_000.0

    # Wall time alone cannot turn the unchanged hostile record into a heartbeat.
    assert not observation.observe(
        status="ready",
        updated_at=1_000.0,
        monotonic_now=3.0,
        wall_now=1_000.0,
    )
    assert observation.last_ready_observed_at is None

    # The hostile value never poisoned accepted high water. A genuinely changed,
    # currently valid leader write can recover even though its value is lower.
    assert observation.observe(
        status="ready",
        updated_at=101.0,
        monotonic_now=4.0,
        wall_now=1_000.0,
    )
    assert observation.high_water_updated_at == 101.0
    assert observation.last_ready_observed_at == 4.0


@pytest.mark.parametrize(
    "sample",
    [
        _health("ready", 100.0),
        _health("ready", 99.0),
        _health("degraded_source", 101.0),
        _health("ready", 1_000.0),
    ],
    ids=["duplicate", "rewound", "nonready", "future"],
)
def test_duplicate_rewound_future_or_nonready_never_refreshes(
    tmp_path: Path,
    sample: SimpleNamespace,
) -> None:
    from cryodaq.launcher import LauncherWindow

    window = _monitor_window(tmp_path)
    window._assistant_periodic_health.baseline_observed = True
    window._assistant_periodic_health.high_water_updated_at = 100.0
    with (
        patch("cryodaq.periodic_state.load_periodic_state", return_value=sample),
        patch("cryodaq.launcher.time.time", return_value=100.0),
    ):
        LauncherWindow._check_periodic_health(window, monotonic_now=50.0)  # type: ignore[arg-type]

    window._clear_periodic_reporting_fault.assert_not_called()


def test_newer_nonready_advances_high_water_and_blocks_rewound_ready(tmp_path: Path) -> None:
    from cryodaq.launcher import LauncherWindow

    window = _monitor_window(tmp_path)
    window._assistant_periodic_health.baseline_observed = True
    window._assistant_periodic_health.high_water_updated_at = 100.0
    with (
        patch(
            "cryodaq.periodic_state.load_periodic_state",
            side_effect=[_health("degraded_source", 102.0), _health("ready", 101.0)],
        ),
        patch("cryodaq.launcher.time.time", return_value=102.0),
    ):
        LauncherWindow._check_periodic_health(window, monotonic_now=50.0)  # type: ignore[arg-type]
        LauncherWindow._check_periodic_health(window, monotonic_now=51.0)  # type: ignore[arg-type]

    window._clear_periodic_reporting_fault.assert_not_called()


def test_requested_h3_assistant_exit_raises_persistent_status() -> None:
    from cryodaq.launcher import LauncherWindow

    process = MagicMock()
    process.poll.return_value = 1
    window = SimpleNamespace(
        _assistant_enabled=True,
        _shutdown_requested=False,
        _assistant_proc=process,
        _assistant_periodic_requested=True,
        _assistant_restart_pending=True,
        _set_periodic_reporting_fault=MagicMock(),
    )

    LauncherWindow._check_assistant_health(window)  # type: ignore[arg-type]

    window._set_periodic_reporting_fault.assert_called_once()


def test_missed_initial_and_rolling_deadlines_use_only_monotonic_time(tmp_path: Path) -> None:
    from cryodaq.launcher import LauncherWindow

    window = _monitor_window(tmp_path)
    missing = SimpleNamespace(payload={"health": {"status": "starting", "updated_at": 0.0}})
    with (
        patch("cryodaq.periodic_state.load_periodic_state", return_value=missing),
        patch("cryodaq.launcher.time.time", return_value=10**12),
    ):
        LauncherWindow._check_periodic_health(window, monotonic_now=99.9)  # type: ignore[arg-type]
        LauncherWindow._check_periodic_health(window, monotonic_now=100.0)  # type: ignore[arg-type]

    window._set_periodic_reporting_fault.assert_called_once()

    window = _monitor_window(tmp_path)
    window._assistant_periodic_health.baseline_observed = True
    window._assistant_periodic_health.high_water_updated_at = 100.0
    with (
        patch("cryodaq.periodic_state.load_periodic_state", return_value=_health("ready", 101.0)),
        patch("cryodaq.launcher.time.time", return_value=101.0),
    ):
        LauncherWindow._check_periodic_health(window, monotonic_now=20.0)  # type: ignore[arg-type]
    window._set_periodic_reporting_fault.reset_mock()
    with (
        patch("cryodaq.periodic_state.load_periodic_state", return_value=_health("ready", 101.0)),
        patch("cryodaq.launcher.time.time", return_value=-(10**12)),
    ):
        LauncherWindow._check_periodic_health(window, monotonic_now=109.9)  # type: ignore[arg-type]
        LauncherWindow._check_periodic_health(window, monotonic_now=110.0)  # type: ignore[arg-type]

    window._set_periodic_reporting_fault.assert_called_once()


def test_health_read_failure_is_redacted_and_does_not_refresh(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from cryodaq.launcher import LauncherWindow

    window = _monitor_window(tmp_path)
    secret = "123456:abcdefghijklmnopqrstuvwxyzABCDE"
    with patch(
        "cryodaq.periodic_state.load_periodic_state",
        side_effect=ValueError(f"bad state {secret}"),
    ):
        LauncherWindow._check_periodic_health(window, monotonic_now=100.0)  # type: ignore[arg-type]

    assert "H3_HEALTH_READ_FAILED" in caplog.text
    assert secret not in caplog.text
    window._clear_periodic_reporting_fault.assert_not_called()
    window._set_periodic_reporting_fault.assert_called_once()


def test_periodic_fault_banner_never_starts_safety_alarm() -> None:
    from cryodaq.launcher import LauncherWindow

    banner = MagicMock()
    tray = MagicMock()
    window = SimpleNamespace(
        _periodic_reporting_fault=False,
        _periodic_status_banner=banner,
        _tray=tray,
        _start_engine_down_alarm=MagicMock(),
    )

    LauncherWindow._set_periodic_reporting_fault(window)  # type: ignore[arg-type]

    assert window._periodic_reporting_fault is True
    banner.show.assert_called_once()
    window._start_engine_down_alarm.assert_not_called()


class _LifecycleProcess:
    pid = 731

    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._alive = True

    def poll(self) -> int | None:
        return None if self._alive else 0

    def terminate(self) -> None:
        self._events.append("assistant.terminate")

    def wait(self, *, timeout: float) -> int:
        self._events.append(f"assistant.wait:{timeout:g}")
        self._alive = False
        return 0

    def kill(self) -> None:
        self._events.append("assistant.kill")


class _WindowsLifecycleProcess(_LifecycleProcess):
    def __init__(self, events: list[str], outcomes: list[object]) -> None:
        super().__init__(events)
        self._outcomes = outcomes

    def wait(self, *, timeout: float) -> int:
        self._events.append(f"assistant.wait:{timeout:g}")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        self._alive = False
        return int(outcome)


def test_windows_assistant_shutdown_uses_graceful_then_terminate_then_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.launcher as module

    events: list[str] = []
    authority = module._new_assistant_shutdown_authority(tmp_path)
    shutdown_path = authority.path
    process = _WindowsLifecycleProcess(
        events,
        [
            subprocess.TimeoutExpired("assistant", 10),
            subprocess.TimeoutExpired("assistant", 10),
            0,
        ],
    )
    window = SimpleNamespace(
        _assistant_proc=process,
        _assistant_shutdown_path=shutdown_path,
        _assistant_shutdown_authority=authority,
    )
    monkeypatch.setattr(module.sys, "platform", "win32")

    module.LauncherWindow._stop_assistant(window)  # type: ignore[arg-type]

    assert events == [
        "assistant.wait:10",
        "assistant.terminate",
        "assistant.wait:10",
        "assistant.kill",
        "assistant.wait:5",
    ]
    assert window._assistant_proc is None
    assert window._assistant_shutdown_path is None
    assert shutdown_path.is_file()


@pytest.mark.parametrize("candidate_kind", ["symlink", "broken-symlink", "hardlink", "directory"])
def test_windows_assistant_shutdown_never_trusts_unsafe_existing_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_kind: str,
) -> None:
    import cryodaq.launcher as module

    events: list[str] = []
    authority = module._new_assistant_shutdown_authority(tmp_path)
    shutdown_path = authority.path
    if candidate_kind == "directory":
        shutdown_path.mkdir()
    elif candidate_kind == "hardlink":
        target = tmp_path / "target"
        target.touch()
        os.link(target, shutdown_path)
    else:
        target = tmp_path / ("target" if candidate_kind == "symlink" else "missing")
        if candidate_kind == "symlink":
            target.touch()
        try:
            shutdown_path.symlink_to(target)
        except OSError as exc:
            if os.name == "nt" and exc.winerror == 1314:
                pytest.skip("Windows account lacks symlink creation privilege")
            raise
    process = _WindowsLifecycleProcess(events, [0])
    window = SimpleNamespace(
        _assistant_proc=process,
        _assistant_shutdown_path=shutdown_path,
        _assistant_shutdown_authority=authority,
    )
    monkeypatch.setattr(module.sys, "platform", "win32")

    module.LauncherWindow._stop_assistant(window)  # type: ignore[arg-type]

    assert events == ["assistant.terminate", "assistant.wait:10"]
    assert window._assistant_proc is None
    assert window._assistant_shutdown_path is None
    if candidate_kind == "broken-symlink":
        assert target.exists() is False
    elif candidate_kind == "hardlink":
        assert shutdown_path.exists()
        assert target.exists()


def test_windows_assistant_shutdown_never_unlinks_replacement_after_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.launcher as module

    authority = module._new_assistant_shutdown_authority(tmp_path)
    shutdown_path = authority.path
    replacement = tmp_path / "replacement"
    replacement.write_text("preserve", encoding="utf-8")
    events: list[str] = []

    class _ReplacingProcess(_WindowsLifecycleProcess):
        def wait(self, *, timeout: float) -> int:
            if not events:
                shutdown_path.unlink()
                replacement.replace(shutdown_path)
                events.append(f"assistant.wait:{timeout:g}")
                raise subprocess.TimeoutExpired("assistant", timeout)
            return super().wait(timeout=timeout)

    process = _ReplacingProcess(events, [0])
    window = SimpleNamespace(
        _assistant_proc=process,
        _assistant_shutdown_path=shutdown_path,
        _assistant_shutdown_authority=authority,
    )
    monkeypatch.setattr(module.sys, "platform", "win32")

    module.LauncherWindow._stop_assistant(window)  # type: ignore[arg-type]

    assert shutdown_path.read_text(encoding="utf-8") == "preserve"
    assert events == ["assistant.wait:10", "assistant.terminate", "assistant.wait:10"]


@pytest.mark.parametrize("replacement_kind", ["symlink", "real-directory"])
def test_windows_assistant_shutdown_rejects_runtime_identity_swap_during_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_kind: str,
) -> None:
    import cryodaq.launcher as module

    authority = module._new_assistant_shutdown_authority(tmp_path)
    original_runtime = tmp_path / "runtime-original"
    outside = tmp_path / "outside"
    outside.mkdir()
    real_open = os.open

    def swap_then_open(path: Path, flags: int, mode: int) -> int:
        authority.runtime_dir.rename(original_runtime)
        if replacement_kind == "symlink":
            try:
                authority.runtime_dir.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                if os.name == "nt" and exc.winerror == 1314:
                    pytest.skip("Windows account lacks symlink creation privilege")
                raise
            redirected = outside / authority.path.name
        else:
            authority.runtime_dir.mkdir()
            redirected = authority.path
        descriptor = real_open(path, flags, mode)
        assert redirected.is_file()
        return descriptor

    monkeypatch.setattr(module.os, "open", swap_then_open)
    events: list[str] = []
    process = _WindowsLifecycleProcess(events, [0])
    window = SimpleNamespace(
        _assistant_proc=process,
        _assistant_shutdown_path=authority.path,
        _assistant_shutdown_authority=authority,
    )
    monkeypatch.setattr(module.sys, "platform", "win32")

    module.LauncherWindow._stop_assistant(window)  # type: ignore[arg-type]

    redirected = (outside if replacement_kind == "symlink" else authority.runtime_dir) / authority.path.name
    assert redirected.is_file(), "lost authority must not unlink a redirected object"
    assert events == ["assistant.terminate", "assistant.wait:10"]
    assert window._assistant_proc is None
    assert window._assistant_shutdown_path is None
