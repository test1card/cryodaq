from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from cryodaq.drivers.registry import (
    DriverAuthority,
    DriverConstructionContext,
    construct_driver,
    validate_instrument_entries,
)
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog
from scripts import soak_mock_stack_runner as runner

_LINUX_PROCESS_AUTHORITY = pytest.mark.skipif(sys.platform != "linux", reason="requires Linux waitid authority")


@pytest.fixture
def linux_subreaper():
    if sys.platform != "linux":
        yield
        return
    prior = runner._set_runner_subreaper(True)
    try:
        yield
    finally:
        runner._set_runner_subreaper(prior)


@pytest.mark.asyncio
async def test_isolated_source_fixture_is_one_passive_mock_sensor(tmp_path) -> None:
    runner._materialize_isolated_mock_config(tmp_path)

    expected = {
        *runner._ISOLATED_TRACKED_CONFIG_FILES,
        *(name for name, _content in runner._ISOLATED_STATIC_CONFIGS),
        "instruments.yaml",
        "channel_descriptors.yaml",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    assert all(".local." not in name for name in expected)

    config = yaml.safe_load((tmp_path / "instruments.yaml").read_text(encoding="utf-8"))
    validated = validate_instrument_entries(config["instruments"])

    assert len(validated) == 1
    assert validated[0].name == runner._ISOLATED_MOCK_INSTRUMENT_NAME
    assert validated[0].spec.authority is DriverAuthority.PASSIVE_MEASUREMENT
    assert "--mock" in runner._SOURCE_ARGV

    driver = construct_driver(validated[0], DriverConstructionContext(mock=True))
    assert driver.mock is True
    assert driver._transport.mock is True

    manifest = yaml.safe_load((tmp_path / "channel_descriptors.yaml").read_text(encoding="utf-8"))
    assert len(manifest["descriptors"]) == 16
    assert len(manifest["bindings"]) == 16
    descriptors = load_live_channel_descriptor_catalog(tmp_path / "channel_descriptors.yaml")
    descriptors.require_exact_instruments((runner._ISOLATED_MOCK_INSTRUMENT_NAME,))
    assert descriptors.grants_control_authority is False

    await driver.connect()
    try:
        readings = await driver.read_channels()
        assert len(readings) == 8
        bound = [descriptors.bind(reading) for reading in readings]
        assert all(item.descriptor.instrument_id == runner._ISOLATED_MOCK_INSTRUMENT_NAME for item in bound)
    finally:
        await driver.disconnect()


@_LINUX_PROCESS_AUTHORITY
def _complete_fixture(tmp_path: Path) -> tuple[Path, int]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((str(runner._REPO_ROOT / "src"), str(runner._REPO_ROOT)))
    snapshot = runner._ExecutionSnapshot(
        runner._REPO_ROOT,
        Path(sys.executable),
        environment,
        "sha256:" + "0" * 64,
    )
    config_dir = tmp_path / "config"
    readings_per_sample = runner._materialize_complete_soak_config(
        config_dir,
        report_interval_s=600,
        source_snapshot=snapshot,
    )
    return config_dir, readings_per_sample


@_LINUX_PROCESS_AUTHORITY
def test_complete_passive_fixture_seal_detects_content_and_link_drift(tmp_path) -> None:
    config_dir, readings_per_sample = _complete_fixture(tmp_path)
    baseline = runner._source_fixture_seal(
        config_dir,
        expected_readings_per_sample=readings_per_sample,
    )
    assert baseline.payload["authority"] == "passive_measurement"
    assert baseline.payload["descriptor_count"] == 16
    assert baseline.payload["binding_count"] == 16
    assert baseline.payload["expected_readings_per_sample"] == 8

    channels = config_dir / "channels.yaml"
    original = channels.read_bytes()
    channels.write_bytes(original + b"\n")
    assert (
        runner._source_fixture_seal(config_dir, expected_readings_per_sample=readings_per_sample).payload
        != baseline.payload
    )
    channels.write_bytes(original)
    channels.chmod(0o600)
    alias = tmp_path / "channels-alias.yaml"
    os.link(channels, alias)
    with pytest.raises(runner._RunnerFoundationError, match="identity is unsafe"):
        runner._source_fixture_seal(config_dir, expected_readings_per_sample=readings_per_sample)


@_LINUX_PROCESS_AUTHORITY
def test_complete_fixture_seal_detects_same_byte_inode_replacement(tmp_path) -> None:
    config_dir, readings_per_sample = _complete_fixture(tmp_path)
    baseline = runner._source_fixture_seal(
        config_dir,
        expected_readings_per_sample=readings_per_sample,
    )
    channels = config_dir / "channels.yaml"
    replacement = tmp_path / "replacement.yaml"
    replacement.write_bytes(channels.read_bytes())
    replacement.chmod(0o600)
    os.replace(replacement, channels)

    replaced = runner._source_fixture_seal(
        config_dir,
        expected_readings_per_sample=readings_per_sample,
    )
    assert replaced.payload == baseline.payload
    assert replaced != baseline


@_LINUX_PROCESS_AUTHORITY
def test_complete_fixture_seal_rejects_rebind_during_pinned_read(tmp_path, monkeypatch) -> None:
    config_dir, readings_per_sample = _complete_fixture(tmp_path)
    channels = config_dir / "channels.yaml"
    original = channels.read_bytes()
    original_inode = channels.stat().st_ino
    real_read = runner.os.read
    rebound = False

    def rebind_then_read(fd: int, count: int) -> bytes:
        nonlocal rebound
        if not rebound and os.fstat(fd).st_ino == original_inode:
            rebound = True
            channels.replace(tmp_path / "channels-original.yaml")
            channels.write_bytes(original)
            channels.chmod(0o600)
        return real_read(fd, count)

    monkeypatch.setattr(runner.os, "read", rebind_then_read)
    with pytest.raises(runner._RunnerFoundationError, match="changed during sealing"):
        runner._source_fixture_seal(config_dir, expected_readings_per_sample=readings_per_sample)
    assert rebound is True


@_LINUX_PROCESS_AUTHORITY
def test_complete_fixture_seal_rejects_topology_template_mode_and_oversize(tmp_path, monkeypatch) -> None:
    config_dir, readings_per_sample = _complete_fixture(tmp_path)
    extra = config_dir / "unexpected.yaml"
    extra.write_text("{}\n", encoding="utf-8")
    extra.chmod(0o600)
    with pytest.raises(runner._RunnerFoundationError, match="topology is not exact"):
        runner._source_fixture_seal(config_dir, expected_readings_per_sample=readings_per_sample)
    extra.unlink()

    channels = config_dir / "channels.yaml"
    original = tmp_path / "channels-original.yaml"
    channels.replace(original)
    channels.symlink_to(original)
    with pytest.raises(runner._RunnerFoundationError, match="identity is unsafe"):
        runner._source_fixture_seal(config_dir, expected_readings_per_sample=readings_per_sample)
    channels.unlink()
    original.replace(channels)

    template = config_dir / "experiment_templates" / "unexpected.yaml"
    template.write_text("{}\n", encoding="utf-8")
    with pytest.raises(runner._RunnerFoundationError, match="template directory is unsafe"):
        runner._source_fixture_seal(config_dir, expected_readings_per_sample=readings_per_sample)
    template.unlink()

    channels.chmod(0o644)
    with pytest.raises(runner._RunnerFoundationError, match="identity is unsafe"):
        runner._source_fixture_seal(config_dir, expected_readings_per_sample=readings_per_sample)
    channels.chmod(0o600)

    monkeypatch.setattr(runner, "_MAX_SOURCE_FIXTURE_FILE_BYTES", 1)
    with pytest.raises(runner._RunnerFoundationError, match="exceeds the reviewed bound"):
        runner._source_fixture_seal(config_dir, expected_readings_per_sample=readings_per_sample)


class _LogEvidence:
    def __init__(self) -> None:
        self.logs: list[tuple[str, str]] = []

    def write_log(self, name: str, text: str) -> None:
        self.logs.append((name, text))


@pytest.mark.skipif(os.name != "posix", reason="launcher log capture is POSIX-only")
def test_launcher_log_capture_is_independent_of_path_rebind(tmp_path) -> None:
    path = tmp_path / "launcher.log"
    evidence = _LogEvidence()

    with runner._launcher_log_capture(evidence, path) as stream:
        stream.write(b"owned diagnostics\n")
        stream.flush()
        path.write_bytes(b"rebound attacker text\n")

    assert evidence.logs == [("log-launcher.txt", "owned diagnostics\n")]
    assert path.read_bytes() == b"rebound attacker text\n"


@pytest.mark.skipif(os.name != "posix", reason="launcher log capture is POSIX-only")
def test_launcher_log_capture_bounds_failure_and_rejects_truncated_pass(tmp_path, monkeypatch) -> None:
    marker = runner._TRUNCATED_LAUNCHER_LOG_MARKER
    monkeypatch.setattr(runner, "_MAX_LAUNCHER_LOG_BYTES", len(marker) + 16)
    failure_evidence = _LogEvidence()

    with pytest.raises(ValueError, match="primary"):
        with runner._launcher_log_capture(failure_evidence, tmp_path / "failure.log") as stream:
            stream.write(b"x" * 128)
            raise ValueError("primary")
    assert failure_evidence.logs[0][1].encode().startswith(marker)
    assert len(failure_evidence.logs[0][1].encode()) <= len(marker) + 16

    with pytest.raises(runner._RunnerFoundationError, match="evidence ceiling"):
        with runner._launcher_log_capture(_LogEvidence(), tmp_path / "pass.log") as stream:
            stream.write(b"x" * 128)


@_LINUX_PROCESS_AUTHORITY
def test_source_gate_bind_failure_reaps_unreleased_session() -> None:
    observed_pid: list[int] = []

    class RejectingObserver:
        def identity_for_pid(self, pid: int) -> runner._ProcessIdentity:
            observed_pid.append(pid)
            raise runner._RunnerFoundationError("deterministic bind failure")

    with pytest.raises(runner._RunnerFoundationError, match="bind failure"):
        runner._spawn_gated_source(
            environment=dict(os.environ),
            stdout=subprocess.DEVNULL,
            inherited_fds=(),
            observer=RejectingObserver(),  # type: ignore[arg-type]
        )

    assert len(observed_pid) == 1
    with pytest.raises(ChildProcessError):
        os.waitpid(observed_pid[0], os.WNOHANG)


@_LINUX_PROCESS_AUTHORITY
def test_owned_session_reaps_clean_terminal_only_after_stable_empty_cut(linux_subreaper) -> None:
    del linux_subreaper
    psutil = pytest.importorskip("psutil")
    observer = runner._LockedPsutilObserver(psutil)
    owner = observer.identity_for_pid(os.getpid())
    process = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(0.1)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    identity = observer.identity_for_pid(process.pid)

    assert (
        runner._wait_and_reap_owned_session(
            process,
            observer=observer,
            expected=identity,
            owner=owner,
            timeout_s=2.0,
        )
        == 0
    )
    assert process.returncode == 0


@_LINUX_PROCESS_AUTHORITY
def test_owned_session_kills_but_rejects_terminal_group_survivor(linux_subreaper) -> None:
    del linux_subreaper
    psutil = pytest.importorskip("psutil")
    observer = runner._LockedPsutilObserver(psutil)
    owner = observer.identity_for_pid(os.getpid())
    process = subprocess.Popen(
        (
            sys.executable,
            "-c",
            "import os,time; child=os.fork(); time.sleep(30) if child == 0 else time.sleep(0.2)",
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    identity = observer.identity_for_pid(process.pid)

    with pytest.raises(runner._RunnerFoundationError, match="survivors"):
        runner._wait_and_reap_owned_session(
            process,
            observer=observer,
            expected=identity,
            owner=owner,
            timeout_s=3.0,
        )
    assert process.returncode == 0


@_LINUX_PROCESS_AUTHORITY
def test_owned_subreaper_kills_and_rejects_detached_session_survivor(linux_subreaper) -> None:
    del linux_subreaper
    psutil = pytest.importorskip("psutil")
    observer = runner._LockedPsutilObserver(psutil)
    owner = observer.identity_for_pid(os.getpid())
    process = subprocess.Popen(
        (
            sys.executable,
            "-c",
            "import os,time; child=os.fork(); (os.setsid(), time.sleep(30)) if child == 0 else time.sleep(0.2)",
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    identity = observer.identity_for_pid(process.pid)

    with pytest.raises(runner._RunnerFoundationError, match="survivors"):
        runner._wait_and_reap_owned_session(
            process,
            observer=observer,
            expected=identity,
            owner=owner,
            timeout_s=3.0,
        )
    assert process.returncode == 0
    assert observer.descendants(owner) == ()


@_LINUX_PROCESS_AUTHORITY
def test_owned_subreaper_reaps_fast_detached_zombie(linux_subreaper) -> None:
    del linux_subreaper
    psutil = pytest.importorskip("psutil")
    observer = runner._LockedPsutilObserver(psutil)
    owner = observer.identity_for_pid(os.getpid())
    process = subprocess.Popen(
        (
            sys.executable,
            "-c",
            "import os,time; child=os.fork(); "
            "(os.setsid(), os._exit(0)) if child == 0 else (print(child, flush=True), time.sleep(0.2))",
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    assert process.stdout is not None
    child_pid = int(process.stdout.readline().decode("ascii").strip())
    process.stdout.close()
    identity = observer.identity_for_pid(process.pid)

    with pytest.raises(runner._RunnerFoundationError, match="survivors"):
        runner._wait_and_reap_owned_session(
            process,
            observer=observer,
            expected=identity,
            owner=owner,
            timeout_s=3.0,
        )

    assert process.returncode == 0
    assert observer.descendants(owner, include_zombies=True) == ()
    with pytest.raises(ChildProcessError):
        os.waitpid(child_pid, os.WNOHANG)


@_LINUX_PROCESS_AUTHORITY
def test_failed_source_force_settlement_reaps_detached_session(linux_subreaper) -> None:
    del linux_subreaper
    psutil = pytest.importorskip("psutil")
    observer = runner._LockedPsutilObserver(psutil)
    owner = observer.identity_for_pid(os.getpid())
    process = subprocess.Popen(
        (
            sys.executable,
            "-c",
            "import os,time; child=os.fork(); (os.setsid(), time.sleep(30)) if child == 0 else time.sleep(30)",
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    identity = observer.identity_for_pid(process.pid)

    runner._force_settle_owned_session(
        process,
        observer=observer,
        expected=identity,
        owner=owner,
    )

    assert process.returncode is not None
    assert observer.descendants(owner, include_zombies=True) == ()


@pytest.mark.parametrize("epoch", [0, 1, 449, 600, 100_000, 1_000_000_000, 2_147_483_647])
def test_short_soak_schedule_reserves_exactly_one_later_boundary(epoch: int) -> None:
    interval_s, planned_offset_s = runner._select_short_soak_report_schedule(float(epoch))

    assert 450 <= planned_offset_s <= 600
    assert planned_offset_s + interval_s >= 1050
    assert runner._validate_short_soak_runtime_schedule(interval_s, float(epoch + 30)) >= 395


def test_short_soak_runtime_schedule_rejects_consumed_reservation() -> None:
    interval_s, planned_offset_s = runner._select_short_soak_report_schedule(100_000.0)

    with pytest.raises(runner._RunnerFoundationError, match="consumed"):
        runner._validate_short_soak_runtime_schedule(
            interval_s,
            100_000.0 + planned_offset_s - 394,
        )
