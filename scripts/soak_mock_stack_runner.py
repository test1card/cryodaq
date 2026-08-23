"""POSIX source-mode short-soak runner and durable R3b receipt authority."""

from __future__ import annotations

import ctypes
import dataclasses
import errno
import hashlib
import io
import json
import math
import os
import re
import secrets
import selectors
import signal
import socket
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol

import yaml

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_TEST_FILE: Final = "tests/integration/test_periodic_png_multiprocess.py"
_EXACT_NODE_IDS: Final = (
    f"{_TEST_FILE}::test_real_loopback_publisher_rep_and_adapter_startup_hydration_alarm_seals",
    f"{_TEST_FILE}::test_publisher_restart_changes_session_and_fresh_adapter_recovers",
    f"{_TEST_FILE}::test_subscriber_disconnect_monitor_invalidates_and_callbacks_stop",
    f"{_TEST_FILE}::test_two_assistants_one_leader_per_domain",
    f"{_TEST_FILE}::test_killed_elected_assistant_replacement_makes_one_forward_result",
    f"{_TEST_FILE}::test_killed_rendering_leader_promotes_then_authorizes_one_delivery",
    f"{_TEST_FILE}::test_replay_exact_off_child_creates_no_periodic_resources",
)
_COLLECTION_ARGV: Final = (
    ".venv/bin/python",
    "-m",
    "pytest",
    "-p",
    "pytest_asyncio.plugin",
    "-p",
    "pytest_timeout",
    "-p",
    "no:cacheprovider",
    "--collect-only",
    "-q",
    *_EXACT_NODE_IDS,
)
_EXECUTION_ARGV: Final = (
    ".venv/bin/python",
    "-m",
    "pytest",
    "-p",
    "pytest_asyncio.plugin",
    "-p",
    "pytest_timeout",
    "-p",
    "no:cacheprovider",
    "-q",
    *_EXACT_NODE_IDS,
)
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_SUMMARY_RE = re.compile(r"7 passed in [0-9]+(?:\.[0-9]+)?s\Z")
_COLLECTION_SUMMARY_RE = re.compile(r"7 tests collected in [0-9]+(?:\.[0-9]+)?s\Z")
_PROGRESS_RE = re.compile(r"\.{7}\s+\[100%\]\Z")
_FORBIDDEN_PYTEST_MARKERS: Final = (" skipped", " deselected", " xfailed", " xpassed", " error")
_MAX_STREAM_BYTES: Final = 8 * 1024 * 1024
_MAX_SNAPSHOT_ARCHIVE_BYTES: Final = 32 * 1024 * 1024
_EXACT_SIX_TIMEOUT_S: Final = 300.0
_PROCESS_GROUP_GRACE_S: Final = 2.0
_STATUS_STRUCT: Final = struct.Struct("!i")
_SUPERVISOR_CODE: Final = """\
import ctypes, os, select, struct, sys
if sys.platform != "linux" or ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
    raise SystemExit(126)
status_fd = int(sys.argv[1])
release_fd = int(sys.argv[2])
start_fd = int(sys.argv[3])
argv = sys.argv[4:]
if os.read(start_fd, 1) != b"G":
    raise SystemExit(125)
os.close(start_fd)
child = os.fork()
if child == 0:
    os.close(status_fd)
    os.close(release_fd)
    os.execve("/proc/self/exe", argv, os.environ)
os.close(1)
os.close(2)
_, status = os.waitpid(child, 0)
exit_code = os.waitstatus_to_exitcode(status)
os.write(status_fd, struct.pack("!i", exit_code))
os.close(status_fd)
while True:
    try:
        while os.waitpid(-1, os.WNOHANG)[0] > 0:
            pass
    except ChildProcessError:
        pass
    if select.select([release_fd], [], [], 0.05)[0]:
        os.read(release_fd, 1)
        break
os.close(release_fd)
"""
_MAX_START_IDENTITY_BYTES: Final = 128
_BRIDGE_HANDSHAKE_SCHEMA: Final = "cryodaq.soak.bridge-identity"
_BRIDGE_DATA_SCHEMA: Final = "cryodaq.soak.bridge-data"
_BRIDGE_HANDSHAKE_VERSION: Final = 1
_MAX_BRIDGE_HANDSHAKE_BYTES: Final = 512
_BRIDGE_FD_ENV: Final = "CRYODAQ_SOAK_BRIDGE_FD"
_BRIDGE_NONCE_ENV: Final = "CRYODAQ_SOAK_BRIDGE_NONCE"
_ARTIFACT_FD_ENV: Final = "CRYODAQ_SOAK_ARTIFACT_FD"
_ARTIFACT_NONCE_ENV: Final = "CRYODAQ_SOAK_ARTIFACT_NONCE"
_FRAME_PREFIX: Final = struct.Struct("!I")
_ARTIFACT_IO_TIMEOUT_S: Final = 10.0
_POST_ACK_HEALTH_TIMEOUT_S: Final = 40.0
_SHORT_SOAK_NEXT_REPORT_MIN_S: Final = 450
_SHORT_SOAK_NEXT_REPORT_MAX_S: Final = 600
_SHORT_SOAK_THIRD_REPORT_FLOOR_S: Final = 1050
_MAX_RECEIPT_LEDGER_BYTES: Final = 8 * 1024 * 1024
_MAX_RECEIPT_RECORD_BYTES: Final = 8 * 1024
_MAX_LAUNCHER_LOG_BYTES: Final = 8 * 1024 * 1024
_ASSISTANT_LOG_BACKUP_COUNT: Final = 14
_ASSISTANT_LOG_ROTATION_RE: Final = re.compile(r"assistant\.log\.\d{4}-\d{2}-\d{2}\Z")
_MAX_SOURCE_FIXTURE_FILE_BYTES: Final = 4 * 1024 * 1024
_TRUNCATED_LAUNCHER_LOG_MARKER: Final = b"[launcher log truncated; bounded tail follows]\n"
_LOCKED_PSUTIL_VERSION: Final = "7.2.2"
_SOURCE_ARGV: Final = (sys.executable, "-m", "cryodaq.launcher", "--mock", "--tray")
_SOURCE_GATE_CODE: Final = """\
import os, sys
gate_fd = int(sys.argv[1])
if os.read(gate_fd, 1) != b"G":
    raise SystemExit(125)
os.close(gate_fd)
os.execve("/proc/self/exe", sys.argv[2:], os.environ)
"""
# LS218_2 rather than LS218_1, and the difference is the whole point: the engine
# REFUSES to start a SafetyManager with no critical channel, and refuses again when a
# declared channel is not classified safety-critical by its own descriptor. Every one
# of LS218_1's sixteen descriptors is observational, so no declaration could satisfy
# both, and the fixture could not start the engine at all. LS218_2 is the SAME driver
# (lakeshore_218s), the same passive measurement authority, and the same reviewed
# cardinality of sixteen descriptors and sixteen bindings, and it carries TWO
# safety_critical_input channels. Nothing reviewed is loosened and no classification is
# fabricated; the fixture simply uses the tracked instrument that has what the startup
# path requires.
_ISOLATED_MOCK_INSTRUMENT_NAME: Final = "LS218_2"
_ISOLATED_TRACKED_CONFIG_FILES: Final = ("channels.yaml",)
# The launcher resolves a theme at IMPORT time, so a config root without the theme
# packs kills the source stack before any of it runs. Measured on Ubuntu 22.04.5:
# the short soak reached the runner phase, wrote its evidence files, passed the
# exact-six gate, and then failed with "source stack did not reach the exact
# four-role startup cut" -- because the child is told to read config from the
# ISOLATED root, and this set is everything that root gets. Theme packs carry no
# hardware authority, so copying them does not weaken the isolation the curated
# set exists to provide; they are colours.
_ISOLATED_TRACKED_CONFIG_DIRS: Final = ("themes",)
_ISOLATED_STATIC_CONFIGS: Final = (
    ("interlocks.yaml", "interlocks: []\n"),
    ("alarms_v3.yaml", "{}\n"),
    ("housekeeping.yaml", "{}\n"),
    ("plugins.yaml", "{}\n"),
    ("cooldown.yaml", "{}\n"),
)
_SOURCE_START_TIMEOUT_S: Final = 30.0
_RECOVERY_TIMEOUT_S: Final = 60.0
_SHUTDOWN_TIMEOUT_S: Final = 20.0


class _RunnerFoundationError(ValueError):
    """Pure validation failed; this never represents production authority."""


class _ObservedProcessGone(_RunnerFoundationError):
    """An enumerated descendant exited before its identity could settle."""


class _RunnerActivationDisabled(RuntimeError):
    """The requested host/profile is outside the reviewed Linux short path."""


class _ShaBoundary(StrEnum):
    BEFORE_COLLECTION = "before_collection"
    BETWEEN_COLLECTION_AND_EXECUTION = "between_collection_and_execution"
    AFTER_EXECUTION = "after_execution"
    BEFORE_SOURCE_LAUNCH = "before_source_launch"
    AFTER_SOURCE_SHUTDOWN = "after_source_shutdown"
    BEFORE_TERMINAL_ACCEPTANCE = "before_terminal_acceptance"


@dataclass(frozen=True, slots=True)
class _RunProvenance:
    """Immutable non-authoritative run identity supplied to later R2 code."""

    run_id: str
    nonce_sha256: str
    platform: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{32}", self.run_id) is None:
            raise _RunnerFoundationError("run_id must be 128-bit lowercase hex")
        if _SHA256_RE.fullmatch(self.nonce_sha256) is None:
            raise _RunnerFoundationError("nonce_sha256 must be canonical")
        if self.platform not in {"linux", "darwin"}:
            raise _RunnerFoundationError("R1 provenance supports POSIX Linux/macOS only")


@dataclass(frozen=True, slots=True)
class _WorktreeImportProof:
    repo_root: Path
    interpreter: Path
    interpreter_sha256: str
    cryodaq_import: Path

    def __post_init__(self) -> None:
        root = self.repo_root.resolve()
        interpreter = self.interpreter.resolve()
        imported = self.cryodaq_import.resolve()
        expected_interpreter = (root / ".venv/bin/python").resolve()
        expected_package = (root / "src/cryodaq").resolve()
        if interpreter != expected_interpreter:
            raise _RunnerFoundationError("interpreter is not the exact worktree .venv Python")
        if _SHA256_RE.fullmatch(self.interpreter_sha256) is None:
            raise _RunnerFoundationError("interpreter hash must be canonical")
        if not imported.is_relative_to(expected_package):
            raise _RunnerFoundationError("cryodaq import does not resolve inside the exact worktree src")
        object.__setattr__(self, "repo_root", root)
        object.__setattr__(self, "interpreter", interpreter)
        object.__setattr__(self, "cryodaq_import", imported)


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns)


def _hash_regular_file(path: Path) -> str:
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise _RunnerFoundationError("worktree interpreter is not a regular file")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            opened = os.fstat(stream.fileno())
    except OSError as exc:
        raise _RunnerFoundationError("worktree interpreter hash is unavailable") from exc
    after = path.stat()
    if _file_identity(before) != _file_identity(opened) or _file_identity(before) != _file_identity(after):
        raise _RunnerFoundationError("worktree interpreter changed while hashing")
    return f"sha256:{digest.hexdigest()}"


def _copy_running_executable(expected: Path, destination: Path) -> str:
    """Copy the already-open Linux process image without reopening its pathname."""

    source_fd: int | None = None
    destination_fd: int | None = None
    digest = hashlib.sha256()
    try:
        source_fd = os.open("/proc/self/exe", os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        source_before = os.fstat(source_fd)
        if not stat.S_ISREG(source_before.st_mode):
            raise _RunnerFoundationError("running interpreter is not a regular file")
        if Path(f"/proc/self/fd/{source_fd}").resolve(strict=True) != expected.resolve(strict=True):
            raise _RunnerActivationDisabled("runner is not executing under the exact worktree .venv interpreter")
        destination_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o500,
        )
        while chunk := os.read(source_fd, 1024 * 1024):
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                if written <= 0:
                    raise _RunnerFoundationError("sealed interpreter copy made no progress")
                view = view[written:]
        os.fsync(destination_fd)
        source_after = os.fstat(source_fd)
    except OSError as exc:
        raise _RunnerActivationDisabled("running interpreter capture is unavailable") from exc
    finally:
        if destination_fd is not None:
            os.close(destination_fd)
        if source_fd is not None:
            os.close(source_fd)
    if _file_identity(source_before) != _file_identity(source_after):
        raise _RunnerFoundationError("running interpreter changed while being captured")
    captured = f"sha256:{digest.hexdigest()}"
    if _hash_regular_file(destination) != captured:
        raise _RunnerFoundationError("sealed interpreter copy contradicts its source")
    return captured


def _controlled_test_environment(
    repo_root: Path, site_packages: Path, *, runtime_library_dir: Path | None = None
) -> dict[str, str]:
    root = Path(repo_root).resolve()
    environment = {
        "HOME": "/nonexistent",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root), str(site_packages.resolve()))),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "TMPDIR": "/tmp",
        "TZ": "UTC",
        "XDG_CACHE_HOME": "/nonexistent",
        "XDG_CONFIG_HOME": "/nonexistent",
    }
    # This stage COPIES the interpreter into the snapshot, and a relocated interpreter
    # cannot use the run-paths that were relative to where it used to live. The first
    # extension module that needs the C++ runtime then loads the SYSTEM one, and every
    # library loaded afterwards is stuck with it. Measured on Ubuntu 22.04.5 with a
    # conda interpreter: `import zmq` then `import sqlite3` raises
    #   ImportError: /lib/x86_64-linux-gnu/libstdc++.so.6: version `CXXABI_1.3.15'
    #   not found (required by <prefix>/lib/libicui18n.so.78)
    # and collection of the exact-six module fails with it, while either import alone
    # succeeds. Naming the interpreter's OWN library directory removes the ambiguity;
    # the value is derived from the interpreter, never inherited from the caller, so
    # the environment stays closed.
    if runtime_library_dir is not None:
        resolved_library_dir = Path(runtime_library_dir).resolve()
        if resolved_library_dir.is_dir():
            environment["LD_LIBRARY_PATH"] = str(resolved_library_dir)
    return environment


def _controlled_git_environment() -> dict[str, str]:
    return {"HOME": "/nonexistent", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin"}


def _source_environment(
    root: Path,
    *,
    source_root: Path,
    bridge_grant: dict[str, str],
    artifact_grant: dict[str, str],
) -> dict[str, str]:
    """Build the closed source-child environment without ambient inheritance."""

    resolved = Path(root).resolve(strict=True)
    sealed_source = Path(source_root).resolve(strict=True)
    if not resolved.is_absolute() or resolved == _REPO_ROOT or resolved.is_relative_to(_REPO_ROOT):
        raise _RunnerFoundationError("source root is not isolated from the repository")
    if set(bridge_grant) != {_BRIDGE_FD_ENV, _BRIDGE_NONCE_ENV}:
        raise _RunnerFoundationError("bridge capability grant fields are not exact")
    if set(artifact_grant) != {_ARTIFACT_FD_ENV, _ARTIFACT_NONCE_ENV}:
        raise _RunnerFoundationError("artifact capability grant fields are not exact")
    home = resolved / "home"
    temporary = resolved / "tmp"
    cache = resolved / "cache"
    config = resolved / "xdg-config"
    for path in (home, temporary, cache, config):
        path.mkdir(mode=0o700)
    return {
        "CRYODAQ_ROOT": str(resolved),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": os.pathsep.join((str(sealed_source / "src"), str(sealed_source))),
        "PYTHONUNBUFFERED": "1",
        "QT_QPA_PLATFORM": "offscreen",
        "TMPDIR": str(temporary),
        "TZ": "UTC",
        "XDG_CACHE_HOME": str(cache),
        "XDG_CONFIG_HOME": str(config),
        **bridge_grant,
        **artifact_grant,
    }


def _engine_critical_channel_ids(descriptors: list[dict]) -> list[str]:
    """The channels the ENGINE will treat as critical, by the engine's own rule.

    THE RULE IS COPIED FROM PRODUCTION, NOT INVENTED HERE, and the previous version of
    this derivation did not match it. `safety_pattern_liveness.py` builds
    `critical_manifest_ids` from descriptors whose **quantity is `temperature`** AND whose
    safety class is `safety_critical_input`, then refuses when the declared set is not
    exactly that set. It applies NO role test.

    What the earlier filter did instead: it tested `safety_class` and excluded the
    `source_readback` role. That role test is a NO-OP -- `descriptors.py` refuses any
    descriptor that is `source_readback` without the `hazardous_source_readback` class, so
    a channel can never be both `source_readback` and `safety_critical_input` -- and the
    `quantity` test, the one that decides, was missing. The two agreed only because both of
    LS218_2's safety-critical descriptors happen to be temperature (measured: Т11 and Т12,
    both `quantity=temperature`, both `role=primary_measurement`). A non-temperature
    safety-critical descriptor added later would have been OVER-declared, the engine's
    union check would have fired, and the engine would have refused to start -- after the
    fixture's own test had said it could.
    """

    return sorted(
        item["channel_id"]
        for item in descriptors
        if item.get("quantity") == "temperature" and item.get("safety_class") == "safety_critical_input"
    )


def _materialize_isolated_mock_config(
    config_dir: Path,
    *,
    source_root: Path = _REPO_ROOT,
    validation_interpreter: Path | None = None,
    validation_environment: dict[str, str] | None = None,
) -> int | None:
    """Build an explicit passive-only config set from reviewed tracked bases."""

    source_dir = Path(source_root).resolve(strict=True) / "config"
    for name in _ISOLATED_TRACKED_CONFIG_FILES:
        source = source_dir / name
        if not source.is_file():
            raise _RunnerFoundationError(f"required tracked soak config is unavailable: {name}")
        (config_dir / name).write_bytes(source.read_bytes())
    for name in _ISOLATED_TRACKED_CONFIG_DIRS:
        source = source_dir / name
        if not source.is_dir():
            raise _RunnerFoundationError(f"required tracked soak config directory is unavailable: {name}")
        target = config_dir / name
        target.mkdir(mode=0o700)
        copied = 0
        for item in sorted(source.iterdir()):
            # Refused by NAME rather than skipped. A skipped entry makes the isolated
            # root diverge from the tracked tree silently, and the seal seals what the
            # child sees without ever comparing back to the source, so the divergence
            # would surface later as a launcher failure with no named cause.
            if not item.is_file():
                raise _RunnerFoundationError(
                    f"tracked soak config directory holds a non-file entry: {name}/{item.name}"
                )
            copy = target / item.name
            copy.write_bytes(item.read_bytes())
            # The caller's chmod sweep only reaches the top level, and the seal demands
            # 0o600 on every sealed file.
            copy.chmod(0o600)
            copied += 1
        if copied == 0:
            raise _RunnerFoundationError(f"tracked soak config directory is empty: {name}")
    for name, content in _ISOLATED_STATIC_CONFIGS:
        (config_dir / name).write_text(content, encoding="utf-8")

    instruments_raw = yaml.safe_load((source_dir / "instruments.yaml").read_text(encoding="utf-8"))
    if type(instruments_raw) is not dict or type(instruments_raw.get("instruments")) is not list:
        raise _RunnerFoundationError("tracked instrument config is malformed")
    selected = [
        item
        for item in instruments_raw["instruments"]
        if type(item) is dict and item.get("name") == _ISOLATED_MOCK_INSTRUMENT_NAME
    ]
    if len(selected) != 1:
        raise _RunnerFoundationError("tracked passive soak instrument is not unique")
    instrument_path = config_dir / "instruments.yaml"
    instrument_path.write_text(
        yaml.safe_dump({"instruments": selected}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    if validation_interpreter is None or validation_environment is None:
        from cryodaq.drivers.registry import DriverAuthority, validate_instrument_entries

        validated = validate_instrument_entries(selected)
        if len(validated) != 1 or validated[0].spec.authority is not DriverAuthority.PASSIVE_MEASUREMENT:
            raise _RunnerFoundationError("isolated soak instrument is not passive measurement authority")
        readings_per_sample = None
    else:
        validation_code = """
import asyncio
import json
import pathlib
import sys

import yaml

from cryodaq.drivers.registry import (
    DriverConstructionContext,
    construct_driver,
    validate_instrument_entries,
)


async def probe() -> None:
    raw = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    items = validate_instrument_entries(raw["instruments"])
    if len(items) != 1:
        raise RuntimeError("fixture instrument is not unique")
    driver = construct_driver(items[0], DriverConstructionContext(mock=True))
    await driver.connect()
    try:
        readings = await driver.read_channels()
    finally:
        await driver.disconnect()
    print(json.dumps({"authority": items[0].spec.authority.value, "readings": len(readings)}))


asyncio.run(probe())
"""
        validated = subprocess.run(
            (str(validation_interpreter), "-c", validation_code, str(instrument_path)),
            cwd=Path(source_root).resolve(strict=True),
            env=validation_environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        try:
            behavior = json.loads(validated.stdout)
        except json.JSONDecodeError:
            behavior = None
        if (
            validated.returncode != 0
            or validated.stderr.strip()
            or type(behavior) is not dict
            or set(behavior) != {"authority", "readings"}
            or behavior["authority"] != "passive_measurement"
            or type(behavior["readings"]) is not int
            or behavior["readings"] <= 0
        ):
            raise _RunnerFoundationError("snapshot-bound passive instrument validation failed")
        readings_per_sample = behavior["readings"]

    descriptors_raw = yaml.safe_load((source_dir / "channel_descriptors.yaml").read_text(encoding="utf-8"))
    if (
        type(descriptors_raw) is not dict
        or descriptors_raw.get("schema_version") != 1
        or type(descriptors_raw.get("descriptors")) is not list
        or type(descriptors_raw.get("bindings")) is not list
    ):
        raise _RunnerFoundationError("tracked descriptor config is malformed")
    descriptor_manifest = {
        "schema_version": 1,
        "descriptors": [
            item
            for item in descriptors_raw["descriptors"]
            if type(item) is dict and item.get("instrument_id") == _ISOLATED_MOCK_INSTRUMENT_NAME
        ],
        "bindings": [
            item
            for item in descriptors_raw["bindings"]
            if type(item) is dict and item.get("instrument_id") == _ISOLATED_MOCK_INSTRUMENT_NAME
        ],
    }
    if not descriptor_manifest["descriptors"] or not descriptor_manifest["bindings"]:
        raise _RunnerFoundationError("tracked passive soak descriptors are unavailable")
    descriptor_ids = {item["channel_id"] for item in descriptor_manifest["descriptors"]}
    binding_ids = {item["channel_id"] for item in descriptor_manifest["bindings"]}
    if len(descriptor_manifest["descriptors"]) != 16 or len(descriptor_manifest["bindings"]) != 16:
        raise _RunnerFoundationError("tracked passive soak descriptor cardinality changed")
    if descriptor_ids != binding_ids:
        raise _RunnerFoundationError("tracked passive soak descriptor bindings do not match")
    (config_dir / "channel_descriptors.yaml").write_text(
        yaml.safe_dump(descriptor_manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # `critical_channels` entries are EXACT canonical identities, not patterns:
    # `_resolve_critical_bindings` does `if channel_id not in storage_catalog.by_channel_id`.
    # The fixture used to declare the literal string ".*", meaning "everything", and no
    # channel has that identity, so the engine refused to start at its boot-time safety
    # liveness check -- the F-1 silent-safety-kill guard doing exactly its job. Measured on
    # Ubuntu 22.04.5: the launcher started, the engine died before its readiness receipt,
    # and the reason was
    #   Dead safety/alarm channel pattern(s): 1 match NO channel on the plane their
    #   consumer sees ... pattern='.*' source=safety.yaml critical_channels
    # Deriving the list from the roster keeps the original intent -- every channel is
    # critical -- and cannot drift from the descriptors the same call just wrote. For this
    # fixture it is the two channels LS218_2 carries as safety-critical inputs; it was the
    # EMPTY set while the fixture used LS218_1, whose sixteen descriptors are all
    # observational, and an empty list is refused outright by the engine. Derived rather
    # than assumed either way: a safety-critical descriptor added later is declared
    # automatically, and one removed stops being declared.
    critical_channels = _engine_critical_channel_ids(descriptor_manifest["descriptors"])
    # The physical-alarms document is taken from the tracked base and then DISARMED,
    # rather than written as a short static string. The production loader requires exactly
    # cooldown, vacuum and landmarks, complete key sets in the first two, and the two
    # canonical landmark channels with non-empty alias lists in the third, so a curtailed
    # document cannot satisfy it and the engine refused to start on it. Only the three
    # arming flags are overridden, so the soak stays passive while the document stays the
    # reviewed one.
    physical_raw = yaml.safe_load((source_dir / "physical_alarms.yaml").read_text(encoding="utf-8"))
    if type(physical_raw) is not dict or set(physical_raw) != {"cooldown", "vacuum", "landmarks"}:
        raise _RunnerFoundationError("tracked physical alarms config is malformed")
    physical_raw["cooldown"]["enabled"] = False
    physical_raw["vacuum"]["enabled"] = False
    physical_raw["vacuum"]["escalate_to_safety"] = False
    (config_dir / "physical_alarms.yaml").write_text(
        yaml.safe_dump(physical_raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (config_dir / "safety.yaml").write_text(
        yaml.safe_dump(
            {
                "critical_channels": critical_channels,
                "require_keithley_for_run": False,
                "keithley_channels": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return readings_per_sample


def _materialize_complete_soak_config(
    config_dir: Path,
    *,
    report_interval_s: int,
    source_snapshot: _ExecutionSnapshot,
) -> int:
    config_dir.mkdir(mode=0o700)
    (config_dir / "agent.yaml").write_text(
        "agent:\n  enabled: false\nreporting:\n  automatic_enabled: true\n",
        encoding="utf-8",
    )
    (config_dir / "notifications.yaml").write_text(
        "telegram:\n  bot_token: '123456:abcdefghijklmnopqrstuvwxyz'\n  chat_id: -100123\n"
        "periodic_report:\n  enabled: true\n"
        f"  report_interval_s: {report_interval_s}\n",
        encoding="utf-8",
    )
    (config_dir / "experiment_templates").mkdir(mode=0o700)
    readings_per_sample = _materialize_isolated_mock_config(
        config_dir,
        source_root=source_snapshot.root,
        validation_interpreter=source_snapshot.interpreter,
        validation_environment=source_snapshot.environment,
    )
    for path in config_dir.iterdir():
        if path.is_file():
            path.chmod(0o600)
    if readings_per_sample is None:
        raise _RunnerFoundationError("snapshot-bound fixture behavior was not measured")
    return readings_per_sample


@dataclass(frozen=True, slots=True)
class _SourceFixtureSeal:
    payload: dict[str, object]
    identities: tuple[tuple[object, ...], ...]


def _source_fixture_seal(config_dir: Path, *, expected_readings_per_sample: int) -> _SourceFixtureSeal:
    """Describe the complete passive fixture with a canonical no-link tree seal."""

    expected_files = {
        "agent.yaml",
        "alarms_v3.yaml",
        "channel_descriptors.yaml",
        "channels.yaml",
        "cooldown.yaml",
        "housekeeping.yaml",
        "instruments.yaml",
        "interlocks.yaml",
        "notifications.yaml",
        "physical_alarms.yaml",
        "plugins.yaml",
        "safety.yaml",
    }
    if type(expected_readings_per_sample) is not int or expected_readings_per_sample <= 0:
        raise _RunnerFoundationError("passive source fixture behavior is invalid")

    def identity(info: os.stat_result) -> tuple[int, ...]:
        return (
            info.st_mode,
            info.st_dev,
            info.st_ino,
            info.st_uid,
            info.st_gid,
            info.st_nlink,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    directory_before = config_dir.lstat()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(config_dir, flags)
    try:
        directory_opened = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(directory_opened.st_mode)
            or not os.path.samestat(directory_before, directory_opened)
            or directory_opened.st_uid != os.getuid()
            or stat.S_IMODE(directory_opened.st_mode) != 0o700
        ):
            raise _RunnerFoundationError("passive source fixture directory identity is unsafe")
        expected_names = expected_files | {"experiment_templates"} | set(_ISOLATED_TRACKED_CONFIG_DIRS)
        if set(os.listdir(directory_fd)) != expected_names:
            raise _RunnerFoundationError("passive source fixture topology is not exact")

        identities: list[tuple[object, ...]] = [(".", *identity(directory_opened))]
        template_info = os.stat("experiment_templates", dir_fd=directory_fd, follow_symlinks=False)
        template_fd = os.open("experiment_templates", flags, dir_fd=directory_fd)
        try:
            template_opened = os.fstat(template_fd)
            if (
                not stat.S_ISDIR(template_opened.st_mode)
                or not os.path.samestat(template_info, template_opened)
                or template_opened.st_uid != os.getuid()
                or stat.S_IMODE(template_opened.st_mode) != 0o700
                or os.listdir(template_fd)
            ):
                raise _RunnerFoundationError("passive source fixture template directory is unsafe")
            identities.append(("experiment_templates", *identity(template_opened)))
        finally:
            os.close(template_fd)

        entries: list[dict[str, object]] = [{"path": "experiment_templates", "kind": "directory"}]
        nofollow = getattr(os, "O_NOFOLLOW", 0)

        def seal_file(name: str, parent_fd: int, label: str) -> None:
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            try:
                fd = os.open(name, os.O_RDONLY | nofollow, dir_fd=parent_fd)
            except OSError as exc:
                raise _RunnerFoundationError("passive source fixture file identity is unsafe") from exc
            try:
                opened = os.fstat(fd)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or not os.path.samestat(before, opened)
                    or opened.st_nlink != 1
                    or opened.st_uid != os.getuid()
                    or stat.S_IMODE(opened.st_mode) != 0o600
                ):
                    raise _RunnerFoundationError("passive source fixture file identity is unsafe")
                content_bytes = 0
                content_sha256 = hashlib.sha256()
                while chunk := os.read(fd, 1024 * 1024):
                    content_bytes += len(chunk)
                    if content_bytes > _MAX_SOURCE_FIXTURE_FILE_BYTES:
                        raise _RunnerFoundationError("passive source fixture file exceeds the reviewed bound")
                    content_sha256.update(chunk)
                if identity(os.fstat(fd)) != identity(opened):
                    raise _RunnerFoundationError("passive source fixture changed during sealing")
            finally:
                os.close(fd)
            after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if identity(after) != identity(opened):
                raise _RunnerFoundationError("passive source fixture changed during sealing")
            identities.append((label, *identity(opened)))
            entries.append(
                {
                    "path": label,
                    "kind": "file",
                    "bytes": content_bytes,
                    "sha256": f"sha256:{content_sha256.hexdigest()}",
                }
            )

        for name in sorted(expected_files):
            seal_file(name, directory_fd, name)

        # The theme packs are a POPULATED tracked directory, unlike the empty template
        # directory above. They are sealed exactly as the files are -- identity, no
        # links, exact mode, content hashed -- because a directory the launcher must
        # read at import is the last place an unsealed byte belongs.
        for tracked in sorted(_ISOLATED_TRACKED_CONFIG_DIRS):
            sub_before = os.stat(tracked, dir_fd=directory_fd, follow_symlinks=False)
            sub_fd = os.open(tracked, flags, dir_fd=directory_fd)
            try:
                sub_opened = os.fstat(sub_fd)
                if (
                    not stat.S_ISDIR(sub_opened.st_mode)
                    or not os.path.samestat(sub_before, sub_opened)
                    or sub_opened.st_uid != os.getuid()
                    or stat.S_IMODE(sub_opened.st_mode) != 0o700
                ):
                    raise _RunnerFoundationError("passive source fixture directory identity is unsafe")
                identities.append((tracked, *identity(sub_opened)))
                entries.append({"path": tracked, "kind": "directory"})
                sub_names = sorted(os.listdir(sub_fd))
                if not sub_names:
                    raise _RunnerFoundationError("passive source fixture tracked directory is empty")
                for sub_name in sub_names:
                    seal_file(sub_name, sub_fd, f"{tracked}/{sub_name}")
                if sorted(os.listdir(sub_fd)) != sub_names:
                    raise _RunnerFoundationError("passive source fixture topology changed during sealing")
            finally:
                os.close(sub_fd)
        if set(os.listdir(directory_fd)) != expected_names:
            raise _RunnerFoundationError("passive source fixture topology changed during sealing")
        if identity(os.fstat(directory_fd)) != identity(directory_opened):
            raise _RunnerFoundationError("passive source fixture directory changed during sealing")
    finally:
        os.close(directory_fd)
    entries.sort(key=lambda item: str(item["path"]))
    tree_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
    )
    return _SourceFixtureSeal(
        payload={
            "schema": "cryodaq-soak-source-fixture/v1",
            "instrument_id": _ISOLATED_MOCK_INSTRUMENT_NAME,
            "authority": "passive_measurement",
            "mock": True,
            "descriptor_count": 16,
            "binding_count": 16,
            "expected_readings_per_sample": expected_readings_per_sample,
            "entries": entries,
            "tree_sha256": tree_hash,
        },
        identities=tuple(identities),
    )


def _select_short_soak_report_schedule(now_epoch: float) -> tuple[int, int]:
    """Choose exactly one post-fault aligned boundary inside the short run."""

    if isinstance(now_epoch, bool) or not isinstance(now_epoch, (int, float)) or not math.isfinite(now_epoch):
        raise _RunnerFoundationError("short-soak schedule epoch is invalid")
    now_second = int(now_epoch)
    for interval_s in range(600, 3601):
        next_offset_s = (-now_second) % interval_s or interval_s
        if (
            _SHORT_SOAK_NEXT_REPORT_MIN_S <= next_offset_s <= _SHORT_SOAK_NEXT_REPORT_MAX_S
            and next_offset_s + interval_s >= _SHORT_SOAK_THIRD_REPORT_FLOOR_S
        ):
            return interval_s, next_offset_s
    raise _RunnerFoundationError("unable to align the reviewed short-soak report cadence")


def _validate_short_soak_runtime_schedule(interval_s: int, now_epoch: float) -> int:
    """Fail closed if startup latency consumed the two-receipt reservation."""

    if type(interval_s) is not int or interval_s < 60 or interval_s > 86_400:
        raise _RunnerFoundationError("short-soak report interval is invalid")
    if isinstance(now_epoch, bool) or not isinstance(now_epoch, (int, float)) or not math.isfinite(now_epoch):
        raise _RunnerFoundationError("short-soak runtime epoch is invalid")
    next_offset_s = (-int(now_epoch)) % interval_s or interval_s
    if not (395 <= next_offset_s <= 700 and next_offset_s + interval_s > 900):
        raise _RunnerFoundationError("short-soak startup consumed the exact two-receipt cadence reservation")
    return next_offset_s


class _BoundedLauncherLogDrain:
    """Continuously drain launcher output while retaining only a bounded tail."""

    __slots__ = ("_chunks", "_error", "_read_fd", "_retained", "_thread", "_total", "writer")

    def __init__(self) -> None:
        read_fd, write_fd = os.pipe()
        self._read_fd = read_fd
        self.writer = os.fdopen(write_fd, "wb", buffering=0)
        self._chunks: deque[bytes] = deque()
        self._retained = 0
        self._total = 0
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._drain, name="cryodaq-soak-log-drain", daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        try:
            while chunk := os.read(self._read_fd, 64 * 1024):
                self._total += len(chunk)
                self._chunks.append(chunk)
                self._retained += len(chunk)
                while self._retained > _MAX_LAUNCHER_LOG_BYTES:
                    excess = self._retained - _MAX_LAUNCHER_LOG_BYTES
                    head = self._chunks[0]
                    if len(head) <= excess:
                        self._chunks.popleft()
                        self._retained -= len(head)
                    else:
                        self._chunks[0] = head[excess:]
                        self._retained -= excess
        except BaseException as exc:  # noqa: BLE001 - transferred to the owner thread
            self._error = exc
        finally:
            os.close(self._read_fd)

    def finish(self) -> tuple[bytes, int]:
        if not self.writer.closed:
            self.writer.close()
        self._thread.join(timeout=_PROCESS_GROUP_GRACE_S)
        if self._thread.is_alive():
            raise _RunnerFoundationError("launcher log writer did not settle")
        if self._error is not None:
            raise _RunnerFoundationError("launcher log drain failed") from self._error
        return b"".join(self._chunks), self._total


def _publish_launcher_log(evidence: Any, raw: bytes, total_bytes: int, *, allow_truncated: bool) -> None:
    """Publish one redacted, bounded snapshot from a completed pipe drain."""

    from scripts.soak_mock_stack import redact_text

    if not isinstance(raw, bytes) or type(total_bytes) is not int or total_bytes < len(raw):
        raise _RunnerFoundationError("launcher log drain evidence is invalid")
    truncated = total_bytes > _MAX_LAUNCHER_LOG_BYTES
    encoded = redact_text(raw.decode("utf-8", errors="replace")).encode("utf-8")
    truncated = truncated or len(encoded) > _MAX_LAUNCHER_LOG_BYTES
    if truncated and not allow_truncated:
        raise _RunnerFoundationError("launcher log exceeded the reviewed evidence ceiling")
    if truncated:
        tail_bytes = _MAX_LAUNCHER_LOG_BYTES - len(_TRUNCATED_LAUNCHER_LOG_MARKER)
        tail = encoded[-tail_bytes:]
        while tail and tail[0] & 0xC0 == 0x80:
            tail = tail[1:]
        payload = _TRUNCATED_LAUNCHER_LOG_MARKER + tail.decode("utf-8", errors="ignore").encode("utf-8")
    else:
        payload = encoded
    evidence.write_log("log-launcher.txt", payload.decode("utf-8"))


_ENGINE_STDERR_EVIDENCE_NAME: Final = "log-engine-stderr.txt"
_ENGINE_STDERR_ABSENT_MARKER: Final = (
    "<no engine stderr log was written under the isolated state root; the engine either "
    "never started or never opened its stderr log>\n"
)


def _publish_engine_stderr(evidence: Any, state_root: Path) -> None:
    """Publish the engine's own stderr, so a dead engine can say why it died.

    Without this the run reports a CONDITION without its SUBJECT. The launcher forwards
    engine stderr to a rotating log under the writable state root, which for this run is
    the runner's own temporary directory and is deleted with it, so
    ``Launcher construction failed; phase=engine exception=RuntimeError`` arrived with no
    way to see the engine's traceback. Measured 2026-08-19 on Ubuntu 22.04.5: the evidence
    bundle held six files and none of them was that log.

    The artifact is ALWAYS written, and says so when the log is absent, because a missing
    file is indistinguishable from a publisher that silently did nothing.
    """

    from scripts.soak_mock_stack import redact_text

    path = Path(state_root) / "logs" / "engine.stderr.log"
    try:
        raw = path.read_bytes()
    except OSError:
        evidence.write_log(_ENGINE_STDERR_EVIDENCE_NAME, _ENGINE_STDERR_ABSENT_MARKER)
        return

    encoded = redact_text(raw.decode("utf-8", errors="replace")).encode("utf-8")
    if len(encoded) > _MAX_LAUNCHER_LOG_BYTES:
        # Keep the END: a traceback's cause is written last, and the bound exists to
        # protect the bundle's size, not to choose which half of the failure survives.
        tail_bytes = _MAX_LAUNCHER_LOG_BYTES - len(_TRUNCATED_LAUNCHER_LOG_MARKER)
        tail = encoded[-tail_bytes:]
        while tail and tail[0] & 0xC0 == 0x80:
            tail = tail[1:]
        encoded = _TRUNCATED_LAUNCHER_LOG_MARKER + tail
    evidence.write_log(_ENGINE_STDERR_EVIDENCE_NAME, encoded.decode("utf-8", errors="replace"))


_ASSISTANT_LOG_EVIDENCE_NAME: Final = "log-assistant.txt"
_ASSISTANT_LOG_ABSENT_MARKER: Final = (
    "<no assistant log was written under the isolated state root; the assistant either "
    "never started or never opened its log>\n"
)
_ASSISTANT_LOG_REPLACED_MARKER: Final = (
    "REFUSED: the log directory was not the same directory after the read as before it. "
    "This platform has no descriptor-anchored traversal, so the read cannot be bound to "
    "the directory that was validated; what it can do is prove afterwards that nothing "
    "swapped underneath it, and that proof failed. Nothing read is published, because a "
    "stream that may have come from a replaced directory is worse than none."
)
_ASSISTANT_LOG_REFUSED_MARKER: Final = (
    "<the assistant log was refused: the path under the isolated state root is not a "
    "regular file. The measured process can write that directory, so a symbolic link "
    "there would have copied an unrelated file into this bundle.>\n"
)
_ASSISTANT_LOG_NOT_REGULAR_MARKER: Final = (
    "<the assistant log was refused: the name under the isolated state root exists but is "
    "not a regular file -- a directory, reparse point, device, or fifo holds it. Nothing "
    "read is published, because reading it could copy bytes the isolated root never wrote.>\n"
)
_ASSISTANT_LOG_HARD_LINKED_MARKER: Final = (
    "<the assistant log was refused: it is a regular file carrying more than one link "
    "(st_nlink != 1), so its bytes may also live under a path outside this isolated root. "
    "Nothing read is published.>\n"
)
_ASSISTANT_LOG_REPLACED_OR_UNREADABLE_MARKER: Final = (
    "<the assistant log was refused: during the walk the leaf could neither be measured nor "
    "opened without following links -- it was removed, replaced, or made unreadable between "
    "enumeration and open. Nothing read is published.>\n"
)
_ASSISTANT_LOG_OPENED_BUT_UNREADABLE_MARKER: Final = (
    "<the assistant log was refused: it opened as a lone regular file but could not be "
    "read to the retention bound. Nothing read is published, because a partial stream "
    "from a failing file is worse than an honest refusal.>\n"
)
_ASSISTANT_LOG_RECORD_SPANS_BOUNDARY_MARKER: Final = (
    "<part of the assistant log was withheld: its retained tail began inside one record "
    "with no line break anywhere inside the retained window, so publishing it could carry "
    "the undetectable half of a credential whose identifying prefix was already gone. That "
    "record was discarded whole rather than guessed at.>\n"
)
_ASSISTANT_LOG_DIRECTORY_UNTRUSTED_MARKER: Final = (
    "<the assistant log was refused: the logs directory under the isolated state root could "
    "not be opened and proven to be a plain, unlinked directory -- missing, linked, "
    "replaced, or unreadable. Nothing is published, because nothing inside it can be "
    "trusted on that platform.>\n"
)


class _AssistantLogLeafRefusal(StrEnum):
    """The closed set of reasons a no-follow regular-file read refuses.

    Every member names a condition somebody actually observed. A single untyped
    ``None`` here once made the publisher claim ``symbolic link`` for hard links,
    open failures, races, and I/O errors alike -- a marker asserting a topology
    nobody saw.
    """

    SYMBOLIC_LINK = "symbolic-link"
    NOT_REGULAR_FILE = "not-regular-file"
    HARD_LINKED = "hard-linked"
    REPLACED_OR_UNREADABLE = "replaced-or-unreadable"
    OPENED_BUT_UNREADABLE = "opened-but-unreadable"
    RECORD_SPANS_RETENTION_BOUNDARY = "record-spans-retention-boundary"


_ASSISTANT_LOG_LEAF_REFUSAL_MARKERS: Final[dict[_AssistantLogLeafRefusal, str]] = {
    _AssistantLogLeafRefusal.SYMBOLIC_LINK: _ASSISTANT_LOG_REFUSED_MARKER,
    _AssistantLogLeafRefusal.NOT_REGULAR_FILE: _ASSISTANT_LOG_NOT_REGULAR_MARKER,
    _AssistantLogLeafRefusal.HARD_LINKED: _ASSISTANT_LOG_HARD_LINKED_MARKER,
    _AssistantLogLeafRefusal.REPLACED_OR_UNREADABLE: _ASSISTANT_LOG_REPLACED_OR_UNREADABLE_MARKER,
    _AssistantLogLeafRefusal.OPENED_BUT_UNREADABLE: _ASSISTANT_LOG_OPENED_BUT_UNREADABLE_MARKER,
    _AssistantLogLeafRefusal.RECORD_SPANS_RETENTION_BOUNDARY: _ASSISTANT_LOG_RECORD_SPANS_BOUNDARY_MARKER,
}


def _assistant_log_uses_pathname_traversal(*, platform: str | None = None) -> bool:
    """Whether this platform lacks descriptor-relative log traversal."""

    return (os.name if platform is None else platform) == "nt"


def _read_regular_file_no_follow(
    directory_descriptor: int | None, path: Path | str, *, maximum_bytes: int
) -> tuple[bytes, int] | _AssistantLogLeafRefusal:
    """Read a file the MEASURED PROCESS can replace, without following a link.

    The isolated state root is writable by the very process this bundle describes. If it
    replaces `logs/assistant.log` with a symbolic link before teardown, an ordinary read
    copies whatever the runner can reach into the retained evidence. So the open refuses
    to follow a link, and the descriptor is checked to be a regular file before a byte is
    read -- the check is on the DESCRIPTOR, not on the path, because a path can change
    between the check and the open.

    The returned tail is RECORD-ALIGNED: a bounded slice that begins mid-record would
    carry text whose identifying context stayed behind, and `redact_text` cannot
    recognize a credential whose keyword it never sees. One byte before the cutoff is
    read so alignment can PROVE whether the slice starts at a record boundary; a record
    with no line break inside the window is refused whole instead of guessed at.

    Returns the aligned bounded tail and full descriptor size when safe. Otherwise it
    returns exactly which closed condition refused: a symbolic link, a non-regular file,
    a hard link, a leaf replaced or unreadable during the walk, a file that opened but
    could not be read, or a record spanning the whole retention window. It never returns
    ``None`` -- silence here would force the publisher to invent why nothing was read.
    """

    # TWO CHECKS, because neither is enough alone. `O_NOFOLLOW` does not exist on
    # Windows, where `getattr` would quietly return 0 and the open would follow the link
    # -- a guard that is absent on one platform is a guard that is untested there. So the
    # link is rejected first by `lstat`, which does not follow, and the open still asks
    # for `O_NOFOLLOW` where the platform has it.
    try:
        link_info = os.lstat(path, dir_fd=directory_descriptor)
    except OSError:
        return _AssistantLogLeafRefusal.REPLACED_OR_UNREADABLE
    if stat.S_ISLNK(link_info.st_mode):
        return _AssistantLogLeafRefusal.SYMBOLIC_LINK
    if not stat.S_ISREG(link_info.st_mode):
        return _AssistantLogLeafRefusal.NOT_REGULAR_FILE

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, dir_fd=directory_descriptor)
    except OSError as error:
        # ELOOP is `O_NOFOLLOW` refusing a link that raced in after the lstat above: name
        # the link it is rather than folding it into "replaced or unreadable".
        if error.errno == errno.ELOOP:
            return _AssistantLogLeafRefusal.SYMBOLIC_LINK
        return _AssistantLogLeafRefusal.REPLACED_OR_UNREADABLE
    try:
        info = os.fstat(descriptor)
        if stat.S_ISLNK(info.st_mode):
            return _AssistantLogLeafRefusal.SYMBOLIC_LINK
        if not stat.S_ISREG(info.st_mode):
            return _AssistantLogLeafRefusal.NOT_REGULAR_FILE
        if info.st_nlink != 1:
            return _AssistantLogLeafRefusal.HARD_LINKED
        size = info.st_size
        if maximum_bytes <= 0:
            os.close(descriptor)
            descriptor = -1
            return b"", size

        # ONE byte of context BEFORE the cutoff decides everything: if the byte at
        # `size - maximum_bytes - 1` is a newline, the slice already begins at a record
        # boundary; otherwise it begins inside one and must be trimmed forward to the
        # next one. Without that byte, alignment would silently drop a whole record.
        window = maximum_bytes + 1 if size > maximum_bytes else maximum_bytes
        if size > maximum_bytes:
            os.lseek(descriptor, size - window, os.SEEK_SET)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            raw = handle.read(window)
        if size > maximum_bytes:
            if raw[:1] == b"\n":
                raw = raw[1:]
            else:
                newline = raw.find(b"\n")
                if newline < 0:
                    # No record boundary exists inside the retained window. Any prefix of
                    # this record carries text whose identifying context -- possibly the
                    # keyword of a credential -- was already cut off upstream, and no
                    # detector can recognize the remainder. Discard the whole record.
                    return _AssistantLogLeafRefusal.RECORD_SPANS_RETENTION_BOUNDARY
                raw = raw[newline + 1 :]
        return raw, size
    except OSError:
        return _AssistantLogLeafRefusal.OPENED_BUT_UNREADABLE
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _assistant_log_path_is_absent(directory_descriptor: int | None, path: Path | str) -> bool:
    """Return whether a log leaf is absent without following a replacement link."""

    try:
        os.lstat(path, dir_fd=directory_descriptor)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _directory_identity(directory: Path) -> tuple[int, int] | None:
    """The volume and index of ``directory``, or None if it is not a plain directory.

    Used only where descriptor-relative traversal does not exist. Comparing this before
    and after the reads does not CLOSE the replacement window -- nothing on that platform
    can -- but it turns a read from a directory somebody swapped in into a refusal
    instead of into published evidence.
    """

    try:
        info = os.lstat(directory)
    except OSError:
        return None
    if not stat.S_ISDIR(info.st_mode) or os.path.islink(directory) or os.path.isjunction(directory):
        return None
    return (info.st_dev, info.st_ino)


def _rotated_assistant_log_names(directory: Path | int) -> list[str] | None:
    """Return the bounded set of exact dated assistant-log rotations, oldest first."""

    rotated: list[str] = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if _ASSISTANT_LOG_ROTATION_RE.fullmatch(entry.name) is None:
                continue
            rotated.append(entry.name)
            if len(rotated) > _ASSISTANT_LOG_BACKUP_COUNT:
                return None
    return sorted(rotated)


def _assistant_log_files(state_root: Path) -> tuple[int | None, list[Path | str]] | None:
    """The active log and every rotated backup, oldest first.

    `setup_logging` rotates the assistant log daily and keeps up to fourteen dated
    backups. On a multi-day run the decisive line is often written on the day it happened
    and never repeats, so reading only the active file retains the last day and deletes
    the cause -- the exact evidence loss this publisher exists to stop.
    """

    directory = Path(state_root) / "logs"
    active = "assistant.log"
    try:
        directory_info = os.lstat(directory)
        if not stat.S_ISDIR(directory_info.st_mode) or os.path.islink(directory) or os.path.isjunction(directory):
            return None
        if _assistant_log_uses_pathname_traversal():
            # Windows lacks descriptor-relative `open`; explicitly reject reparse roots,
            # then use a non-globbing enumeration. Any directory access failure is refused.
            # The window this leaves open -- the directory replaced between here and the
            # leaf reads -- cannot be closed on this platform, so the publisher proves
            # afterwards that the directory did not change, and refuses if it did.
            rotated = _rotated_assistant_log_names(directory)
            if rotated is None:
                return None
            return None, [*(directory / name for name in rotated), directory / active]
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        directory_descriptor = os.open(directory, directory_flags)
    except OSError:
        # The measured process can replace `logs`, so a descriptor is the authority for
        # traversal. Do not fall back to pathname globbing when opening it fails.
        return None
    keep_descriptor = False
    try:
        opened_info = os.fstat(directory_descriptor)
        if not stat.S_ISDIR(opened_info.st_mode) or (
            (opened_info.st_dev, opened_info.st_ino) != (directory_info.st_dev, directory_info.st_ino)
        ):
            return None
        rotated = _rotated_assistant_log_names(directory_descriptor)
        if rotated is None:
            return None
    except OSError:
        return None
    else:
        keep_descriptor = True
        return directory_descriptor, [*rotated, active]
    finally:
        if not keep_descriptor:
            os.close(directory_descriptor)


def _publish_assistant_log(evidence: Any, state_root: Path) -> None:
    """Publish the assistant's own log, so a periodic reporter can say why it stopped.

    Without this the reporter's diagnosis exists and is unreachable. The launcher sends
    the assistant child's stderr to the null device, and `setup_logging("assistant")`
    writes `logs/assistant.log` under the writable state root -- which for this run is
    the runner's temporary directory and is deleted with it. So the line naming WHICH
    condition took the live source lived only inside a directory the run removes, and
    the bundle a week-long run leaves behind never held it.

    The artifact is ALWAYS written, and says so when the log is absent or when the path
    is not readable as a lone regular file -- naming WHICH closed condition refused,
    because a marker asserting an unobserved topology diagnoses nothing. Each retained
    per-file tail is record-aligned before redaction, so the redactor never meets a
    credential whose identifying prefix was already cut off by the size bound.
    """

    from scripts.soak_mock_stack import redact_text

    logs_directory = Path(state_root) / "logs"
    # On the descriptor path this is None and unused: the descriptor IS the binding.
    identity_before = _directory_identity(logs_directory) if _assistant_log_uses_pathname_traversal() else None

    selected = _assistant_log_files(state_root)
    if selected is None:
        evidence.write_log(_ASSISTANT_LOG_EVIDENCE_NAME, _ASSISTANT_LOG_DIRECTORY_UNTRUSTED_MARKER)
        return
    directory_descriptor, paths = selected

    # Walk newest-to-oldest and prepend each retained suffix. This preserves the
    # combined stream's tail while never acquiring more than the bundle can retain.
    # A per-file cap would still read one full cap for every rotated day before the
    # deque could discard it.
    collected: deque[bytes] = deque()
    retained_bytes = 0
    source_bytes = 0
    refusals: list[_AssistantLogLeafRefusal] = []
    try:
        for path in reversed(paths):
            # A missing leaf is absent; every existing leaf must pass the no-follow read.
            if _assistant_log_path_is_absent(directory_descriptor, path):
                continue
            remaining = max(_MAX_LAUNCHER_LOG_BYTES - retained_bytes, 0)
            result = _read_regular_file_no_follow(directory_descriptor, path, maximum_bytes=remaining)
            if isinstance(result, _AssistantLogLeafRefusal):
                if result not in refusals:
                    refusals.append(result)
                continue
            raw, size = result
            source_bytes += size
            if raw:
                collected.appendleft(raw)
                retained_bytes += len(raw)
    finally:
        if directory_descriptor is not None:
            os.close(directory_descriptor)

    if _assistant_log_uses_pathname_traversal() and (
        identity_before is None or _directory_identity(logs_directory) != identity_before
    ):
        evidence.write_log(_ASSISTANT_LOG_EVIDENCE_NAME, _ASSISTANT_LOG_REPLACED_MARKER)
        return

    if not collected:
        evidence.write_log(
            _ASSISTANT_LOG_EVIDENCE_NAME,
            "".join(_ASSISTANT_LOG_LEAF_REFUSAL_MARKERS[refusal] for refusal in refusals)
            if refusals
            else _ASSISTANT_LOG_ABSENT_MARKER,
        )
        return

    payload = redact_text(b"".join(collected).decode("utf-8", errors="replace")).encode("utf-8")
    refusal_notice = "".join(_ASSISTANT_LOG_LEAF_REFUSAL_MARKERS[refusal] for refusal in refusals).encode("utf-8")
    encoded = refusal_notice + payload
    if source_bytes > _MAX_LAUNCHER_LOG_BYTES or len(encoded) > _MAX_LAUNCHER_LOG_BYTES:
        # Keep the END, across the rotated files as one stream: the bound protects the
        # bundle's size and must not choose which half of the failure survives.
        tail_bytes = _MAX_LAUNCHER_LOG_BYTES - len(_TRUNCATED_LAUNCHER_LOG_MARKER) - len(refusal_notice)
        tail = payload[-tail_bytes:]
        while tail and tail[0] & 0xC0 == 0x80:
            tail = tail[1:]
        encoded = _TRUNCATED_LAUNCHER_LOG_MARKER + refusal_notice + tail
    evidence.write_log(_ASSISTANT_LOG_EVIDENCE_NAME, encoded.decode("utf-8", errors="replace"))


@contextmanager
def _launcher_log_capture(
    evidence: Any,
    path: Path,
    *,
    settle_writer: Callable[[], None] | None = None,
    state_root: Path | None = None,
):
    """Capture stdout through a continuously drained, memory-bounded pipe.

    ``state_root`` names the writable root the child was given, so the engine's own
    stderr log can be published beside the launcher log. It is optional so a caller
    that has no such root is unchanged.
    """

    if path.exists():
        raise FileExistsError(path)
    drain = _BoundedLauncherLogDrain()
    try:
        yield drain.writer
    except BaseException as primary:
        settled = True
        if settle_writer is not None:
            try:
                settle_writer()
            except Exception as settle_error:  # noqa: BLE001 - retain the primary failure
                settled = False
                primary.add_note(f"launcher writer settlement failed: {settle_error}")
        try:
            if settled:
                raw, total_bytes = drain.finish()
                _publish_launcher_log(evidence, raw, total_bytes, allow_truncated=True)
            elif not drain.writer.closed:
                drain.writer.close()
        except Exception as capture_error:  # noqa: BLE001 - preserve the primary failure
            primary.add_note(f"launcher diagnostic capture failed: {capture_error}")
        if state_root is not None:
            try:
                _publish_engine_stderr(evidence, state_root)
            except Exception as engine_error:  # noqa: BLE001 - preserve the primary failure
                primary.add_note(f"engine stderr capture failed: {engine_error}")
            try:
                _publish_assistant_log(evidence, state_root)
            except Exception as assistant_error:  # noqa: BLE001 - preserve the primary failure
                primary.add_note(f"assistant log capture failed: {assistant_error}")
        raise
    else:
        raw, total_bytes = drain.finish()
        _publish_launcher_log(evidence, raw, total_bytes, allow_truncated=False)
        if state_root is not None:
            _publish_engine_stderr(evidence, state_root)
            _publish_assistant_log(evidence, state_root)


@dataclass(frozen=True, slots=True)
class _ExecutionSnapshot:
    root: Path
    interpreter: Path
    environment: dict[str, str]
    tree_sha256: str

    def assert_sealed(self) -> None:
        if _tree_sha256(self.root) != self.tree_sha256:
            raise _RunnerFoundationError("sealed exact-six snapshot changed during execution")


def _snapshot_fingerprint(entry: os.stat_result) -> bytes:
    """Serialize exactly the metadata a tree digest depends on.

    Stability checks must compare this fingerprint rather than a whole
    ``os.stat_result``: the latter also covers access time, which is not hashed
    and which merely reading an entry can perturb.
    """

    return json.dumps(
        [
            entry.st_mode,
            entry.st_dev,
            entry.st_ino,
            entry.st_uid,
            entry.st_gid,
            entry.st_nlink,
            entry.st_size,
            entry.st_mtime_ns,
            entry.st_ctime_ns,
        ],
        separators=(",", ":"),
    ).encode("ascii")


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    root_info = root.lstat()
    digest.update(
        json.dumps(
            [
                stat.S_IMODE(root_info.st_mode),
                root_info.st_dev,
                root_info.st_ino,
                root_info.st_uid,
                root_info.st_gid,
                root_info.st_nlink,
                root_info.st_mtime_ns,
                root_info.st_ctime_ns,
            ],
            separators=(",", ":"),
        ).encode("ascii")
    )
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix().encode()
        info = path.lstat()
        metadata = _snapshot_fingerprint(info)
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(path).encode()
            # Compare exactly the metadata this digest depends on, and require the
            # target itself to be unchanged. A full ``os.stat_result`` comparison
            # also covers access time, which is not hashed and which reading the
            # link can itself perturb: on ext4 with ``relatime``, once atime is
            # older than mtime an ``os.readlink()`` updates it, so the guard would
            # reject a snapshot solely because it had looked at it. Comparing
            # identity alone would be the opposite error, ignoring same-inode
            # changes to metadata the digest does depend on. Re-reading the target
            # is strictly stronger than the previous check for the property that
            # actually matters: that the link still points where it did.
            if _snapshot_fingerprint(path.lstat()) != metadata or os.readlink(path).encode() != target:
                raise _RunnerFoundationError("sealed snapshot link changed during hashing")
            digest.update(b"L\0" + relative + b"\0" + metadata + b"\0" + target + b"\0")
        elif stat.S_ISREG(info.st_mode):
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            try:
                opened = os.fstat(fd)
                if not os.path.samestat(info, opened):
                    raise _RunnerFoundationError("sealed snapshot file changed before hashing")
                digest.update(b"F\0" + relative + b"\0" + metadata + b"\0")
                while chunk := os.read(fd, 1024 * 1024):
                    digest.update(chunk)
            finally:
                os.close(fd)
            if not os.path.samestat(info, path.lstat()):
                raise _RunnerFoundationError("sealed snapshot file changed during hashing")
        elif stat.S_ISDIR(info.st_mode):
            digest.update(b"D\0" + relative + b"\0" + metadata + b"\0")
        else:
            raise _RunnerFoundationError("sealed snapshot contains a special file")
    return f"sha256:{digest.hexdigest()}"


@contextmanager
def _sealed_execution_snapshot(git_sha: str):
    interpreter = _REPO_ROOT / ".venv/bin/python"
    try:
        resolved = interpreter.resolve(strict=True)
    except OSError as exc:
        raise _RunnerActivationDisabled("exact worktree .venv interpreter is unavailable") from exc
    try:
        archive = subprocess.run(
            ("git", "archive", "--format=tar", git_sha),
            cwd=_REPO_ROOT,
            env=_controlled_git_environment(),
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise _RunnerActivationDisabled("sealed exact-six snapshot is unavailable") from exc
    if len(archive) > _MAX_SNAPSHOT_ARCHIVE_BYTES:
        raise _RunnerActivationDisabled("sealed exact-six snapshot exceeds the reviewed bound")
    site_packages = (
        Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    ).resolve()
    if not site_packages.is_dir():
        raise _RunnerActivationDisabled("exact worktree site-packages is unavailable")
    with tempfile.TemporaryDirectory(prefix="cryodaq-exact-six-") as temporary:
        root = Path(temporary)
        try:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
                bundle.extractall(root, filter="data")
            snapshot_interpreter = root / ".venv/bin/python"
            snapshot_interpreter.parent.mkdir(parents=True)
            _copy_running_executable(resolved, snapshot_interpreter)
            environment = _controlled_test_environment(
                root, site_packages, runtime_library_dir=Path(sys.base_prefix) / "lib"
            )
            code = "from pathlib import Path; import cryodaq; print(Path(cryodaq.__file__).resolve())"
            imported = subprocess.run(
                (str(snapshot_interpreter), "-c", code),
                cwd=root,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if imported.stderr.strip() or len(imported.stdout.splitlines()) != 1:
                raise _RunnerFoundationError("sealed exact-six import proof output is invalid")
            if not Path(imported.stdout.strip()).resolve().is_relative_to((root / "src/cryodaq").resolve()):
                raise _RunnerFoundationError("sealed exact-six import escaped the snapshot")
            for path in root.rglob("*"):
                if path.is_file() and path != snapshot_interpreter:
                    path.chmod(0o400)
                elif path.is_dir():
                    path.chmod(0o500)
            root.chmod(0o500)
            snapshot = _ExecutionSnapshot(root, snapshot_interpreter, environment, _tree_sha256(root))
            yield snapshot
            snapshot.assert_sealed()
        finally:
            root.chmod(0o700)
            for path in root.rglob("*"):
                if path.is_dir():
                    path.chmod(0o700)


@dataclass(frozen=True, slots=True)
class _CleanShaObservation:
    boundary: _ShaBoundary
    git_sha: str
    clean: bool

    def __post_init__(self) -> None:
        if not isinstance(self.boundary, _ShaBoundary):
            raise TypeError("boundary must be a _ShaBoundary")
        if _GIT_SHA_RE.fullmatch(self.git_sha) is None:
            raise _RunnerFoundationError("git_sha must be full lowercase 40-character hex")
        if not isinstance(self.clean, bool):
            raise TypeError("clean must be a bool")


def _validate_clean_sha_chain(
    observations: tuple[_CleanShaObservation, ...],
    *,
    expected: tuple[_ShaBoundary, ...] = tuple(_ShaBoundary),
) -> str:
    if tuple(item.boundary for item in observations) != expected:
        raise _RunnerFoundationError("clean SHA observations are incomplete or out of order")
    if any(not item.clean for item in observations):
        raise _RunnerFoundationError("worktree drift is terminal")
    shas = {item.git_sha for item in observations}
    if len(shas) != 1:
        raise _RunnerFoundationError("clean SHA changed across runner boundaries")
    return observations[0].git_sha


@dataclass(frozen=True, slots=True)
class _ProcessIdentity:
    pid: int
    start_identity: str

    def __post_init__(self) -> None:
        if isinstance(self.pid, bool) or self.pid <= 0:
            raise _RunnerFoundationError("child PID must be positive")
        if not isinstance(self.start_identity, str):
            raise TypeError("child start identity must be a string")
        encoded = self.start_identity.encode("utf-8")
        if (
            not encoded
            or len(encoded) > _MAX_START_IDENTITY_BYTES
            or any(ord(char) < 32 or ord(char) == 127 for char in self.start_identity)
        ):
            raise _RunnerFoundationError("child start identity is empty or oversized")


class _ChildIdentityObserver(Protocol):
    """R2 adapter boundary; PID alone never identifies a process."""

    def identity_for_pid(self, pid: int) -> _ProcessIdentity: ...


def _interpreter_multiprocessing_service_pids() -> frozenset[int]:
    """PIDs of *this* interpreter's own multiprocessing service processes.

    The forkserver daemon and the resource tracker are children of the running
    interpreter, started lazily by ``multiprocessing`` itself. No launcher
    spawns them, they outlive every individual launcher by design, and from
    Python 3.14 ``forkserver`` is the default start method on Linux -- so any
    process that has touched ``multiprocessing`` at all owns one. Counting them
    as launcher survivors fails an ownership assertion for a process the
    launcher never created; this is what made
    ``test_owned_session_reaps_clean_terminal_only_after_stable_empty_cut``
    fail on Linux CI and pass everywhere the default was still ``fork``.

    Only the service processes themselves are excluded. Descendant traversal
    still passes through them, so a genuine leak parented by one is reported.
    """

    pids: set[int] = set()
    for module_name, service_attribute, pid_attribute in (
        ("multiprocessing.forkserver", "_forkserver", "_forkserver_pid"),
        ("multiprocessing.resource_tracker", "_resource_tracker", "_pid"),
    ):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        pid = getattr(getattr(module, service_attribute, None), pid_attribute, None)
        if type(pid) is int and pid > 0:
            pids.add(pid)
    return frozenset(pids)


class _LockedPsutilObserver:
    """Fail-closed PID/start observer used only by source qualification.

    The module object is injected only to keep import-time product behavior
    independent of the dev extra.  Runtime construction requires the exact
    lockfile version and never skips access/identity errors.
    """

    __slots__ = ("_psutil",)

    def __init__(self, psutil_module: Any) -> None:
        if getattr(psutil_module, "__version__", None) != _LOCKED_PSUTIL_VERSION:
            raise _RunnerActivationDisabled("locked psutil observer version is unavailable")
        required = ("Process", "NoSuchProcess", "AccessDenied", "TimeoutExpired", "STATUS_ZOMBIE")
        if any(not hasattr(psutil_module, name) for name in required):
            raise _RunnerActivationDisabled("psutil observer API is incomplete")
        self._psutil = psutil_module

    def _process(self, pid: int) -> Any:
        if type(pid) is not int or pid <= 0:
            raise _RunnerFoundationError("observer PID is invalid")
        try:
            return self._psutil.Process(pid)
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied) as exc:
            raise _RunnerFoundationError("process identity is unavailable") from exc

    def _identity(self, process: Any, *, allow_zombie: bool = False) -> _ProcessIdentity:
        try:
            started = float(process._proc.create_time(monotonic=True))
            status = process.status()
        except (
            AttributeError,
            self._psutil.NoSuchProcess,
            self._psutil.AccessDenied,
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            raise _RunnerFoundationError("process start identity is unavailable") from exc
        if not math.isfinite(started) or started <= 0:
            raise _RunnerFoundationError("process start identity is not live")
        if status == self._psutil.STATUS_ZOMBIE and not allow_zombie:
            raise _ObservedProcessGone("process start identity is not live")
        started_ns = int(round(started * 1_000_000_000))
        return _ProcessIdentity(process.pid, f"psutil-{_LOCKED_PSUTIL_VERSION}:monotonic-ns={started_ns}")

    def identity_for_pid(self, pid: int) -> _ProcessIdentity:
        return self._identity(self._process(pid))

    def recheck_exact(self, expected: _ProcessIdentity) -> None:
        """Prove PID/start continuity even after the owned leader is a zombie."""

        if not isinstance(expected, _ProcessIdentity):
            raise TypeError("expected identity must be a _ProcessIdentity")
        if self._identity(self._process(expected.pid), allow_zombie=True) != expected:
            raise _RunnerFoundationError("PID/start identity changed; refusing process operation")

    def group_members(self, process_group_id: int) -> tuple[_ProcessIdentity, ...]:
        members: list[_ProcessIdentity] = []
        if not hasattr(self._psutil, "process_iter"):
            raise _RunnerFoundationError("process-group observer API is unavailable")
        try:
            processes = tuple(self._psutil.process_iter())
        except (self._psutil.AccessDenied, OSError) as exc:
            raise _RunnerFoundationError("process-group membership is unavailable") from exc
        for process in processes:
            try:
                if os.getpgid(process.pid) == process_group_id:
                    members.append(self._identity(process))
            except (ProcessLookupError, self._psutil.NoSuchProcess):
                continue
            except _ObservedProcessGone:
                continue
            except _RunnerFoundationError as exc:
                if isinstance(exc.__cause__, self._psutil.NoSuchProcess):
                    continue
                raise
            except (PermissionError, self._psutil.AccessDenied, OSError, TypeError, ValueError) as exc:
                raise _RunnerFoundationError("process-group membership cannot be proven") from exc
        return tuple(sorted(members, key=lambda item: item.pid))

    def descendants(
        self,
        leader: _ProcessIdentity,
        *,
        include_zombies: bool = False,
    ) -> tuple[_ProcessIdentity, ...]:
        process = self._process(leader.pid)
        if self._identity(process, allow_zombie=True) != leader:
            raise _RunnerFoundationError("PID/start identity changed; refusing descendant scan")
        try:
            processes = tuple(self._psutil.process_iter())
        except (self._psutil.AccessDenied, OSError) as exc:
            raise _RunnerFoundationError("owned descendant scan is unavailable") from exc
        observed: list[tuple[_ProcessIdentity, int]] = []
        for candidate in processes:
            try:
                identity = self._identity(candidate, allow_zombie=include_zombies)
                parent_pid = int(candidate._proc.ppid())
                if self._identity(self._process(identity.pid), allow_zombie=include_zombies) != identity:
                    raise _RunnerFoundationError("process identity changed during descendant scan")
            except _ObservedProcessGone:
                continue
            except _RunnerFoundationError as exc:
                if isinstance(exc.__cause__, self._psutil.NoSuchProcess):
                    continue
                raise
            except self._psutil.NoSuchProcess:
                continue
            except (self._psutil.AccessDenied, OSError, TypeError, ValueError) as exc:
                raise _RunnerFoundationError("owned descendant scan is unavailable") from exc
            observed.append((identity, parent_pid))
        service_pids = _interpreter_multiprocessing_service_pids()
        owned: set[_ProcessIdentity] = set()
        frontier = {leader.pid}
        seen: set[int] = set()
        while frontier:
            next_frontier: set[int] = set()
            for identity, parent_pid in observed:
                if identity in owned or identity.pid in seen or parent_pid not in frontier:
                    continue
                seen.add(identity.pid)
                # Traverse *through* this interpreter's own multiprocessing
                # service processes without counting them; anything they in
                # turn parent is still reported.
                if identity.pid not in service_pids:
                    owned.add(identity)
                next_frontier.add(identity.pid)
            if len(owned) > 128:
                raise _RunnerFoundationError("owned descendant count exceeds the reviewed bound")
            frontier = next_frontier
        self.recheck_exact(leader)
        return tuple(sorted(owned, key=lambda item: item.pid))

    def signal_exact_for_cleanup(self, identity: _ProcessIdentity, signum: int) -> None:
        allowed = {signal.SIGTERM, getattr(signal, "SIGKILL", 9)}
        if isinstance(signum, bool) or not isinstance(signum, int) or signum not in allowed:
            raise _RunnerFoundationError("cleanup signal is outside the reviewed allowlist")
        process = self._recheck(identity)
        try:
            process.send_signal(signum)
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied, OSError) as exc:
            raise _RunnerFoundationError("exact-identity cleanup signal failed") from exc

    def _recheck(self, expected: _ProcessIdentity) -> Any:
        if not isinstance(expected, _ProcessIdentity):
            raise TypeError("expected identity must be a _ProcessIdentity")
        process = self._process(expected.pid)
        if self._identity(process) != expected:
            raise _RunnerFoundationError("PID/start identity changed; refusing process operation")
        return process

    def _forkserver_of(self, pid: int, *, expected_launcher_pid: int) -> int | None:
        """Return `pid` if it is THIS launcher's multiprocessing fork server, else None.

        Python 3.14 makes `forkserver` the Linux default, and the laboratory target is
        3.14.6, so a multiprocessing child is forked from a fork-server process and is not
        a direct child of the launcher. Measured on that machine: bridge 821 reported
        parent 820 while the launcher was 793. The direct-child rule was true under `fork`,
        the previous default, and silently stopped being true.

        The property the rule exists to prove is that the bridge belongs to THIS launcher,
        and a two-step chain proves exactly that -- but only when the intermediate is both
        a direct child of the launcher AND recognisably the fork server. Anything looser
        would accept a grandchild of an unrelated shape, so both halves are checked and
        neither is inferred from the other.
        """

        try:
            candidate = self._process(pid)
            candidate_parent = int(candidate.ppid())
            candidate_argv = " ".join(candidate.cmdline())
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied, OSError, TypeError, ValueError):
            return None
        # THE DIRECT-CHILD REQUIREMENT IS WHAT MAKES THE NEXT TEST SOUND, and it is not
        # defence in depth -- it is load-bearing. Measured on the laboratory interpreter
        # (Python 3.14.6, `evidence/tools/` probe): a process forked BY the fork server
        # inherits the fork server's command line EXACTLY. The bridge's own argv therefore
        # contains `multiprocessing.forkserver` too. So the module token alone identifies
        # the fork server AND every one of its children, and only the parent tells them
        # apart: the fork server's parent is the launcher, its children's parent is the
        # fork server.
        if candidate_parent != expected_launcher_pid:
            return None
        # This is a SUBSTRING test and the comment used to claim it was an exact match on
        # the module. It was not, and it cannot be: the token lives inside a `-c` code
        # string, measured as
        #   python -B -c "import sys; from multiprocessing.forkserver import main; main(...)"
        # so there is no argument equal to the module name to compare against. The check
        # is sound because of the parent test above, not because of this one.
        if "multiprocessing.forkserver" not in candidate_argv:
            return None
        return pid

    def observe_assistant(self, pid: int, *, expected_launcher_pid: int) -> _AssistantProcessObservation:
        process = self._process(pid)
        identity = self._identity(process)
        try:
            parent_pid = int(process.ppid())
            argv = tuple(process.cmdline())
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied, OSError, TypeError, ValueError) as exc:
            raise _RunnerFoundationError("assistant process observation is unavailable") from exc
        role = _exact_child_role(argv)
        observation = _AssistantProcessObservation(identity, parent_pid, role, True)
        _bind_positive_assistant_identity(observation, expected_launcher_pid=expected_launcher_pid)
        return observation

    def observe_bridge(self, pid: int, *, expected_launcher_pid: int) -> _BridgeProcessObservation:
        process = self._process(pid)
        identity = self._identity(process)
        try:
            parent_pid = int(process.ppid())
            argv = tuple(process.cmdline())
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied, OSError, TypeError, ValueError) as exc:
            raise _RunnerFoundationError("bridge process observation is unavailable") from exc
        try:
            _exact_child_role(argv)
        except _RunnerFoundationError:
            pass
        else:
            raise _RunnerFoundationError("positive bridge identity collides with another child role")
        belongs = parent_pid == expected_launcher_pid or (
            self._forkserver_of(parent_pid, expected_launcher_pid=expected_launcher_pid) is not None
        )
        observation = _BridgeProcessObservation(
            identity, parent_pid, "zmq_bridge", True, expected_launcher_pid if belongs else 0
        )
        if not belongs:
            raise _RunnerFoundationError(
                "reported bridge does not belong to this launcher: "
                f"bridge pid {pid} reports parent {parent_pid}, launcher is {expected_launcher_pid}, "
                "and that parent is not this launcher's multiprocessing fork server"
            )
        return observation

    def signal_exact(self, identity: _ProcessIdentity, signum: int) -> None:
        if isinstance(signum, bool) or not isinstance(signum, int) or signum != signal.SIGTERM:
            raise _RunnerFoundationError("qualification permits only exact-identity SIGTERM")
        process = self._recheck(identity)
        try:
            process.send_signal(signum)
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied, OSError) as exc:
            raise _RunnerFoundationError("exact-identity signal failed") from exc

    def wait_gone(self, identity: _ProcessIdentity, *, timeout_s: float) -> None:
        if type(timeout_s) not in {int, float} or not math.isfinite(float(timeout_s)) or not 0 < timeout_s <= 20:
            raise _RunnerFoundationError("process wait timeout is outside the reviewed bound")
        if not isinstance(identity, _ProcessIdentity):
            raise TypeError("expected identity must be a _ProcessIdentity")
        try:
            process = self._psutil.Process(identity.pid)
        except self._psutil.NoSuchProcess:
            return
        except self._psutil.AccessDenied as exc:
            raise _RunnerFoundationError("process identity cannot be rechecked before wait") from exc
        if self._identity(process) != identity:
            raise _RunnerFoundationError("PID/start identity changed; refusing process operation")
        try:
            process.wait(timeout=float(timeout_s))
        except self._psutil.NoSuchProcess:
            return
        except (self._psutil.AccessDenied, self._psutil.TimeoutExpired, OSError) as exc:
            raise _RunnerFoundationError("exact process identity did not settle") from exc
        try:
            current = self._psutil.Process(identity.pid)
        except self._psutil.NoSuchProcess:
            return
        except self._psutil.AccessDenied as exc:
            raise _RunnerFoundationError("settled process identity cannot be rechecked") from exc
        if self._identity(current) == identity:
            raise _RunnerFoundationError("exact process identity remains live after wait")


# Whole-argv suffixes (everything after argv[0], the interpreter) allowlisted
# per role. `_exact_child_role` requires an exact tuple match against one of
# these — no extra, duplicate, leading, or trailing tokens tolerated.
_ROLE_ARGV_SUFFIXES: Final = {
    "assistant": (("-m", "cryodaq.agents.assistant_bootstrap"), ("--mode=assistant",)),
    "engine": (
        ("-m", "cryodaq.engine"),
        ("--mode=engine",),
        ("-m", "cryodaq.engine", "--mock"),
        ("--mode=engine", "--mock"),
    ),
}


def _exact_child_role(argv: tuple[str, ...]) -> str:
    if not argv or any(type(item) is not str for item in argv):
        raise _RunnerFoundationError("child argv is unavailable")
    rest = argv[1:]
    for role, suffixes in _ROLE_ARGV_SUFFIXES.items():
        if rest in suffixes:
            return role
    raise _RunnerFoundationError("child argv is not an exact allowlisted role")


class _CleanShaCollector:
    """Collect ordered clean-SHA observations from fixed Git commands."""

    __slots__ = ("_next", "_observations", "_repo_root", "_sha")

    def __init__(self, repo_root: Path) -> None:
        root = Path(repo_root).resolve()
        if not (root / ".git").exists():
            raise _RunnerFoundationError("runner root is not a Git worktree")
        self._repo_root = root
        self._next = 0
        self._observations: list[_CleanShaObservation] = []
        self._sha: str | None = None

    def observe(self, boundary: _ShaBoundary) -> _CleanShaObservation:
        boundaries = tuple(_ShaBoundary)
        if self._next >= len(boundaries) or boundary is not boundaries[self._next]:
            raise _RunnerFoundationError("clean SHA boundary is out of order")
        try:
            sha = subprocess.run(
                ("git", "rev-parse", "HEAD"),
                cwd=self._repo_root,
                env=_controlled_git_environment(),
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            status = subprocess.run(
                ("git", "status", "--porcelain=v1", "--untracked-files=all"),
                cwd=self._repo_root,
                env=_controlled_git_environment(),
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise _RunnerFoundationError("clean SHA observation failed") from exc
        observation = _CleanShaObservation(boundary, sha, not bool(status))
        if not observation.clean:
            raise _RunnerFoundationError("worktree drift is terminal")
        if self._sha is None:
            self._sha = sha
        elif sha != self._sha:
            raise _RunnerFoundationError("clean SHA changed across runner boundaries")
        self._next += 1
        self._observations.append(observation)
        return observation

    @property
    def observations(self) -> tuple[_CleanShaObservation, ...]:
        return tuple(self._observations)


@dataclass(frozen=True, slots=True)
class _BridgeHandshakeRecord:
    nonce: str
    launcher_pid: int
    bridge_pid: int
    restart_count: int


@dataclass(frozen=True, slots=True)
class _BridgeDataRecord:
    nonce: str
    launcher_pid: int
    bridge_pid: int
    restart_count: int
    sequence: int


class _BridgeHandshakePipe:
    """Runner-owned POSIX one-shot pipe; it grants no evidence acceptance."""

    __slots__ = ("nonce", "read_fd", "write_fd")

    def __init__(self, *, nonce: str, read_fd: int, write_fd: int) -> None:
        self.nonce = nonce
        self.read_fd = read_fd
        self.write_fd = write_fd

    @classmethod
    def create(cls) -> _BridgeHandshakePipe:
        if os.name != "posix":
            raise _RunnerActivationDisabled("bridge handshake pipe is POSIX-only")
        nonce = secrets.token_hex(32)
        read_fd, write_fd = os.pipe()
        try:
            os.set_inheritable(read_fd, False)
            os.set_inheritable(write_fd, False)
            return cls(nonce=nonce, read_fd=read_fd, write_fd=write_fd)
        except BaseException:
            os.close(read_fd)
            os.close(write_fd)
            raise

    def child_environment(self) -> dict[str, str]:
        if self.write_fd < 0:
            raise _RunnerFoundationError("bridge handshake write descriptor is closed")
        return {_BRIDGE_FD_ENV: str(self.write_fd), _BRIDGE_NONCE_ENV: self.nonce}

    def child_pass_fds(self) -> tuple[int, ...]:
        if self.write_fd < 0:
            raise _RunnerFoundationError("bridge handshake write descriptor is closed")
        return (self.write_fd,)

    def close_parent_write_end(self) -> None:
        if self.write_fd >= 0:
            os.close(self.write_fd)
            self.write_fd = -1

    def close(self) -> None:
        self.close_parent_write_end()
        if self.read_fd >= 0:
            os.close(self.read_fd)
            self.read_fd = -1


class _ArtifactCapabilityPair:
    """Runner-owned AF_UNIX socketpair with one launcher-only duplicate."""

    __slots__ = ("nonce", "runner", "launcher")

    def __init__(self, nonce: str, runner: socket.socket, launcher: socket.socket) -> None:
        self.nonce = nonce
        self.runner = runner
        self.launcher = launcher

    @classmethod
    def create(cls) -> _ArtifactCapabilityPair:
        if os.name != "posix":
            raise _RunnerActivationDisabled("artifact capability is POSIX-only")
        runner, launcher = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            runner.set_inheritable(False)
            launcher.set_inheritable(False)
            return cls(secrets.token_hex(32), runner, launcher)
        except BaseException:
            runner.close()
            launcher.close()
            raise

    def child_environment(self) -> dict[str, str]:
        if self.launcher.fileno() < 3:
            raise _RunnerFoundationError("artifact launcher endpoint is closed")
        return {
            _ARTIFACT_FD_ENV: str(self.launcher.fileno()),
            _ARTIFACT_NONCE_ENV: self.nonce,
        }

    def child_pass_fds(self) -> tuple[int, ...]:
        if self.launcher.fileno() < 3:
            raise _RunnerFoundationError("artifact launcher endpoint is closed")
        return (self.launcher.fileno(),)

    def close_launcher_end(self) -> None:
        if self.launcher.fileno() >= 0:
            self.launcher.close()

    def close(self) -> None:
        self.close_launcher_end()
        if self.runner.fileno() >= 0:
            self.runner.close()


class _ArtifactReceiptSink:
    """Runner-side bounded decoder and durable file+ledger authority."""

    __slots__ = ("_dir_fd", "_last_generation", "_next_sequence", "_nonce", "_socket", "_terminal")

    def __init__(self, endpoint: socket.socket, *, nonce: str, evidence_dir: Path) -> None:
        from cryodaq.agents.assistant.soak_periodic_delivery import frame_body_limit

        if os.name != "posix":
            raise _RunnerActivationDisabled("artifact receipt sink is POSIX-only")
        if re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
            raise _RunnerFoundationError("artifact nonce is invalid")
        if endpoint.family != socket.AF_UNIX or endpoint.type & socket.SOCK_STREAM != socket.SOCK_STREAM:
            raise _RunnerFoundationError("artifact endpoint is invalid")
        endpoint.getpeername()
        metadata = evidence_dir.lstat()
        if (
            not evidence_dir.is_absolute()
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.getuid()
        ):
            raise _RunnerFoundationError("evidence directory is unsafe")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        self._dir_fd = os.open(evidence_dir, flags)
        opened = os.fstat(self._dir_fd)
        if not os.path.samestat(metadata, opened):
            os.close(self._dir_fd)
            raise _RunnerFoundationError("evidence directory identity changed")
        self._socket = endpoint
        self._socket.set_inheritable(False)
        self._socket.settimeout(_ARTIFACT_IO_TIMEOUT_S)
        self._nonce = nonce
        self._last_generation = 0
        self._next_sequence = 1
        self._terminal = False
        _ = frame_body_limit()

    def accept_one(
        self,
        *,
        assistant_observation: _AssistantProcessObservation,
        expected_launcher_pid: int,
        expected_assistant_generation: int,
        expected_slot_id: str,
        expected_generation_id: str,
        expected_owner_token: str,
        expected_artifact_sha256: str,
    ) -> dict[str, object]:
        from cryodaq.agents.assistant.soak_periodic_delivery import (
            build_ack,
            decode_frame_body,
            frame_body_limit,
        )

        if self._terminal:
            raise _RunnerFoundationError("artifact sink is terminal")
        try:
            deadline = time.monotonic() + _ARTIFACT_IO_TIMEOUT_S
            if (
                type(expected_assistant_generation) is not int
                or expected_assistant_generation <= 0
                or type(expected_slot_id) is not str
                or _SHA256_RE.fullmatch(expected_slot_id) is None
                or type(expected_generation_id) is not str
                or re.fullmatch(r"[0-9a-f]{32}", expected_generation_id) is None
                or type(expected_owner_token) is not str
                or re.fullmatch(r"[0-9a-f]{32}", expected_owner_token) is None
                or type(expected_artifact_sha256) is not str
                or _SHA256_RE.fullmatch(expected_artifact_sha256) is None
            ):
                raise _RunnerFoundationError("expected artifact authority is invalid")
            assistant_identity = _bind_positive_assistant_identity(
                assistant_observation,
                expected_launcher_pid=expected_launcher_pid,
            )
            prefix = self._read_exact(_FRAME_PREFIX.size, deadline=deadline)
            (size,) = _FRAME_PREFIX.unpack(prefix)
            if not 1 <= size <= frame_body_limit():
                raise _RunnerFoundationError("artifact frame size is invalid")
            frame = decode_frame_body(self._read_exact(size, deadline=deadline))
            metadata = frame.metadata
            generation = metadata["assistant_generation"]
            sequence = metadata["sequence"]
            if (
                metadata["nonce"] != self._nonce
                or metadata["assistant_pid"] != assistant_identity.pid
                or generation != expected_assistant_generation
                or metadata["slot_id"] != expected_slot_id
                or metadata["generation_id"] != expected_generation_id
                or metadata["owner_token"] != expected_owner_token
                or metadata["artifact_sha256"] != expected_artifact_sha256
                or type(generation) is not int
                or type(sequence) is not int
                or generation < self._last_generation
                or generation > self._last_generation + 1
                or (generation == self._last_generation and sequence != self._next_sequence)
                or (generation == self._last_generation + 1 and sequence != 1)
            ):
                raise _RunnerFoundationError("artifact identity/generation/sequence is invalid")
            ack = build_ack(frame)
            ack_metadata = json.loads(ack[_FRAME_PREFIX.size :].decode("ascii"))
            self._persist(
                frame,
                ack_metadata=ack_metadata,
                assistant_start_identity=assistant_identity.start_identity,
            )
            self._write_all(ack, deadline=deadline)
            self._last_generation = generation
            self._next_sequence = sequence + 1
            return dict(metadata)
        except BaseException:
            self._terminal = True
            self.close()
            raise

    def _persist(
        self,
        frame: Any,
        *,
        ack_metadata: dict[str, object],
        assistant_start_identity: str,
    ) -> None:
        metadata = frame.metadata
        generation = metadata["assistant_generation"]
        sequence = metadata["sequence"]
        digest = str(metadata["artifact_sha256"])[7:]
        final_name = f"periodic-g{generation}-s{sequence}-{digest}.png"
        staging = f".{final_name}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(staging, flags, 0o600, dir_fd=self._dir_fd)
        try:
            os.fchmod(fd, 0o600)
            staging_stat = os.fstat(fd)
            if (
                not stat.S_ISREG(staging_stat.st_mode)
                or staging_stat.st_uid != os.getuid()
                or stat.S_IMODE(staging_stat.st_mode) != 0o600
                or staging_stat.st_nlink != 1
            ):
                raise _RunnerFoundationError("artifact staging descriptor is unsafe")
            self._write_fd(fd, frame.photo)
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(staging, final_name, src_dir_fd=self._dir_fd, dst_dir_fd=self._dir_fd, follow_symlinks=False)
            os.unlink(staging, dir_fd=self._dir_fd)
            os.fsync(self._dir_fd)
            verify_fd = os.open(final_name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=self._dir_fd)
            try:
                final_stat = os.fstat(verify_fd)
                if (
                    not stat.S_ISREG(final_stat.st_mode)
                    or final_stat.st_uid != os.getuid()
                    or stat.S_IMODE(final_stat.st_mode) != 0o600
                    or final_stat.st_nlink != 1
                    or final_stat.st_size != len(frame.photo)
                ):
                    raise _RunnerFoundationError("persisted artifact descriptor is unsafe")
                raw = bytearray()
                while len(raw) <= len(frame.photo):
                    chunk = os.read(verify_fd, min(64 * 1024, len(frame.photo) + 1 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                if bytes(raw) != frame.photo:
                    raise _RunnerFoundationError("persisted artifact rehash mismatch")
            finally:
                os.close(verify_fd)
            record = (
                json.dumps(
                    {
                        "acknowledgement_sha256": ack_metadata["acknowledgement_sha256"],
                        "assistant_start_identity": assistant_start_identity,
                        "filename": final_name,
                        "receipt_id": ack_metadata["receipt_id"],
                        **metadata,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("ascii")
                + b"\n"
            )
            if len(record) > _MAX_RECEIPT_RECORD_BYTES:
                raise _RunnerFoundationError("receipt ledger record is oversized")
            ledger = self._open_validated_ledger()
            try:
                if os.fstat(ledger).st_size + len(record) > _MAX_RECEIPT_LEDGER_BYTES:
                    raise _RunnerFoundationError("receipt ledger capacity is exhausted")
                self._write_fd(ledger, record)
                os.fsync(ledger)
            finally:
                os.close(ledger)
            os.fsync(self._dir_fd)
        except BaseException:
            try:
                os.unlink(staging, dir_fd=self._dir_fd)
            except OSError:
                pass
            raise

    def _open_validated_ledger(self) -> int:
        name = "periodic-receipts.jsonl"
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        nonblock = getattr(os, "O_NONBLOCK", 0)
        created = False
        try:
            fd = os.open(
                name,
                os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_EXCL | nofollow | nonblock,
                0o600,
                dir_fd=self._dir_fd,
            )
            created = True
            os.fchmod(fd, 0o600)
        except FileExistsError:
            observed = os.stat(name, dir_fd=self._dir_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(observed.st_mode)
                or observed.st_uid != os.getuid()
                or stat.S_IMODE(observed.st_mode) != 0o600
                or observed.st_nlink != 1
                or not 1 <= observed.st_size <= _MAX_RECEIPT_LEDGER_BYTES
            ):
                raise _RunnerFoundationError("existing receipt ledger is unsafe") from None
            fd = os.open(name, os.O_RDWR | os.O_APPEND | nofollow | nonblock, dir_fd=self._dir_fd)
            opened = os.fstat(fd)
            if not os.path.samestat(observed, opened):
                os.close(fd)
                raise _RunnerFoundationError("receipt ledger identity changed")
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
        ):
            os.close(fd)
            raise _RunnerFoundationError("receipt ledger descriptor is unsafe")
        if not created:
            raw = os.pread(fd, metadata.st_size + 1, 0)
            if len(raw) != metadata.st_size or not raw.endswith(b"\n"):
                os.close(fd)
                raise _RunnerFoundationError("receipt ledger has a partial tail")
            seen_receipts: set[str] = set()
            ledger_generation = 0
            ledger_next_sequence = 1
            for line in raw.splitlines(keepends=True):
                if len(line) > _MAX_RECEIPT_RECORD_BYTES or not line.endswith(b"\n"):
                    os.close(fd)
                    raise _RunnerFoundationError("receipt ledger record is invalid")
                try:
                    value = json.loads(line[:-1].decode("ascii"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    os.close(fd)
                    raise _RunnerFoundationError("receipt ledger record is invalid") from None
                canonical = (
                    json.dumps(
                        value,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ).encode("ascii")
                    + b"\n"
                )
                if type(value) is not dict or canonical != line:
                    os.close(fd)
                    raise _RunnerFoundationError("receipt ledger record is not canonical")
                if not self._valid_ledger_record(value):
                    os.close(fd)
                    raise _RunnerFoundationError("receipt ledger record is semantically invalid")
                receipt_id = value["receipt_id"]
                generation = value["assistant_generation"]
                sequence = value["sequence"]
                if (
                    receipt_id in seen_receipts
                    or generation < ledger_generation
                    or generation > ledger_generation + 1
                    or (generation == ledger_generation and sequence != ledger_next_sequence)
                    or (generation == ledger_generation + 1 and sequence != 1)
                ):
                    os.close(fd)
                    raise _RunnerFoundationError("receipt ledger ordering is invalid")
                seen_receipts.add(receipt_id)
                ledger_generation = generation
                ledger_next_sequence = sequence + 1
        return fd

    @staticmethod
    def _valid_ledger_record(value: dict[str, object]) -> bool:
        expected = {
            "acknowledgement_sha256",
            "artifact_sha256",
            "artifact_size",
            "assistant_generation",
            "assistant_pid",
            "assistant_start_identity",
            "caption_sha256",
            "caption_size",
            "filename",
            "generation_id",
            "nonce",
            "owner_token",
            "receipt_id",
            "schema",
            "sequence",
            "slot_id",
            "type",
            "version",
        }
        if set(value) != expected:
            return False
        generation = value["assistant_generation"]
        sequence = value["sequence"]
        artifact_hash = value["artifact_sha256"]
        try:
            start_identity_bytes = value["assistant_start_identity"].encode("utf-8")
        except (AttributeError, UnicodeEncodeError):
            return False
        ack_core = {
            "artifact_sha256": artifact_hash,
            "assistant_generation": generation,
            "assistant_pid": value["assistant_pid"],
            "nonce": value["nonce"],
            "receipt_id": value["receipt_id"],
            "schema": value["schema"],
            "sequence": sequence,
            "type": "ack",
            "version": value["version"],
        }
        expected_ack = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    ack_core,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("ascii")
            ).hexdigest()
        )
        return bool(
            type(generation) is int
            and generation > 0
            and type(sequence) is int
            and sequence > 0
            and value["receipt_id"] == f"g{generation}:s{sequence}"
            and type(artifact_hash) is str
            and _SHA256_RE.fullmatch(artifact_hash) is not None
            and value["filename"] == f"periodic-g{generation}-s{sequence}-{artifact_hash[7:]}.png"
            and type(value["acknowledgement_sha256"]) is str
            and value["acknowledgement_sha256"] == expected_ack
            and value["schema"] == "cryodaq.soak.periodic-artifact"
            and type(value["version"]) is int
            and value["version"] == 1
            and value["type"] == "artifact"
            and type(value["assistant_pid"]) is int
            and value["assistant_pid"] > 0
            and type(value["nonce"]) is str
            and re.fullmatch(r"[0-9a-f]{64}", value["nonce"]) is not None
            and type(value["slot_id"]) is str
            and _SHA256_RE.fullmatch(value["slot_id"]) is not None
            and type(value["generation_id"]) is str
            and re.fullmatch(r"[0-9a-f]{32}", value["generation_id"]) is not None
            and type(value["owner_token"]) is str
            and re.fullmatch(r"[0-9a-f]{32}", value["owner_token"]) is not None
            and type(value["caption_sha256"]) is str
            and _SHA256_RE.fullmatch(value["caption_sha256"]) is not None
            and type(value["artifact_size"]) is int
            and 33 <= value["artifact_size"] <= 10 * 1024 * 1024
            and type(value["caption_size"]) is int
            and 1 <= value["caption_size"] <= 4096
            and type(value["assistant_start_identity"]) is str
            and 1 <= len(start_identity_bytes) <= _MAX_START_IDENTITY_BYTES
        )

    def _read_exact(self, size: int, *, deadline: float) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise _RunnerFoundationError("artifact stream deadline expired")
            self._socket.settimeout(timeout)
            try:
                chunk = self._socket.recv(remaining)
            except TimeoutError as exc:
                raise _RunnerFoundationError("artifact stream deadline expired") from exc
            if not chunk:
                raise _RunnerFoundationError("artifact stream ended mid-frame")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _write_all(self, raw: bytes, *, deadline: float) -> None:
        view = memoryview(raw)
        while view:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise _RunnerFoundationError("artifact ACK deadline expired")
            self._socket.settimeout(timeout)
            try:
                sent = self._socket.send(view)
            except TimeoutError as exc:
                raise _RunnerFoundationError("artifact ACK deadline expired") from exc
            if sent <= 0:
                raise _RunnerFoundationError("artifact ACK did not progress")
            view = view[sent:]

    @staticmethod
    def _write_fd(fd: int, raw: bytes) -> None:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise _RunnerFoundationError("durable evidence write did not progress")
            view = view[written:]

    def close(self) -> None:
        if self._socket.fileno() >= 0:
            self._socket.close()
        if self._dir_fd >= 0:
            os.close(self._dir_fd)
            self._dir_fd = -1


@dataclass(frozen=True, slots=True)
class _JoinedReceiptEvidence:
    """One non-authoritative, fully joined local-delivery observation.

    Construction proves agreement between independently collected evidence
    surfaces.  It intentionally grants no terminal PASS authority: the future
    executor must still bind this value to its owned process handles, exact-six
    execution, clean-SHA chain, and cleanup result.
    """

    assistant: _ProcessIdentity
    assistant_generation: int
    sequence: int
    slot_id: str
    generation_id: str
    owner_token: str
    artifact_sha256: str
    receipt_id: str
    acknowledgement_sha256: str
    ledger_record_sha256: str
    destination_fingerprint: str
    state_updated_at: float
    health_updated_at: float


def _validate_joined_receipt(
    *,
    ledger_record: dict[str, object],
    delivery_state_payload: dict[str, object],
    terminal_state_payload: dict[str, object],
    artifact_bytes: bytes,
    assistant_observation: _AssistantProcessObservation,
    expected_launcher_pid: int,
) -> _JoinedReceiptEvidence:
    """Join one ACK/file/ledger/process/state cut without accepting PASS.

    The pre-ACK DELIVERING cut supplies owner authority. The post-ACK
    ``last_terminal`` cut supplies durable success; neither is sufficient
    alone because terminal rotation deliberately omits the owner token.
    """

    from cryodaq.periodic_state import (
        PeriodicStateDocument,
        periodic_local_destination_fingerprint,
    )

    if type(ledger_record) is not dict or not _ArtifactReceiptSink._valid_ledger_record(ledger_record):
        raise _RunnerFoundationError("receipt ledger record is not valid joined evidence")
    if type(delivery_state_payload) is not dict or type(terminal_state_payload) is not dict:
        raise _RunnerFoundationError("periodic state payload is not a mapping")
    try:
        delivery_state = PeriodicStateDocument(delivery_state_payload).payload
        terminal_state = PeriodicStateDocument(terminal_state_payload).payload
    except (TypeError, ValueError) as exc:
        raise _RunnerFoundationError("periodic state payload is invalid") from exc
    if type(artifact_bytes) is not bytes:
        raise TypeError("artifact_bytes must be exact bytes")

    assistant = _bind_positive_assistant_identity(
        assistant_observation,
        expected_launcher_pid=expected_launcher_pid,
    )
    active = delivery_state["active"]
    terminal = terminal_state["last_terminal"]
    if type(active) is not dict or active["status"] != "DELIVERING":
        raise _RunnerFoundationError("joined delivery state must retain the active owner")
    if terminal_state["active"] is not None or type(terminal) is not dict or terminal["status"] != "SUCCEEDED":
        raise _RunnerFoundationError("joined terminal state must durably rotate successful delivery")
    artifact = active["artifact"]
    receipt = terminal["receipt"]
    health = terminal_state["health"]
    if type(artifact) is not dict or type(receipt) is not dict or type(health) is not dict:
        raise _RunnerFoundationError("joined state lacks terminal artifact, receipt, or health evidence")

    artifact_sha256 = f"sha256:{hashlib.sha256(artifact_bytes).hexdigest()}"
    nonce = ledger_record["nonce"]
    try:
        destination = periodic_local_destination_fingerprint(nonce)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise _RunnerFoundationError("local destination evidence is invalid") from exc
    state_updated = terminal_state["updated_at"]
    delivery_updated = delivery_state["updated_at"]
    health_updated = health["updated_at"]
    finished_at = terminal["finished_at"]
    if not all(type(value) in {int, float} for value in (state_updated, delivery_updated, health_updated, finished_at)):
        raise _RunnerFoundationError("joined state timestamps are invalid")
    if (
        float(finished_at) < float(delivery_updated)
        or float(state_updated) < float(finished_at)
        or float(health_updated) < float(finished_at)
        or health["status"] != "ready"
        or health["error_code"] is not None
        or health["error_text"] != ""
    ):
        raise _RunnerFoundationError("ready health evidence does not reach the delivery cut")

    expected = {
        "assistant_pid": assistant.pid,
        "assistant_start_identity": assistant.start_identity,
        "slot_id": active["slot_id"],
        "generation_id": active["generation_id"],
        "owner_token": active["owner_token"],
        "artifact_sha256": artifact["sha256"],
        "artifact_size": artifact["size"],
        "receipt_id": receipt["receipt_id"],
        "acknowledgement_sha256": receipt["acknowledgement_sha256"],
    }
    for field, value in expected.items():
        if ledger_record[field] != value:
            raise _RunnerFoundationError(f"ledger/state/process join mismatch: {field}")
    if (
        receipt["kind"] != "soak_local"
        or active["destination_fingerprint"] != destination
        or terminal["destination_fingerprint"] != destination
        or terminal["slot_id"] != active["slot_id"]
        or terminal["generation_id"] != active["generation_id"]
        or terminal["artifact_sha256"] != artifact["sha256"]
        or artifact_sha256 != ledger_record["artifact_sha256"]
        or len(artifact_bytes) != ledger_record["artifact_size"]
        or terminal_state["unresolved_delivery"] != []
    ):
        raise _RunnerFoundationError("local receipt/file/state authority does not agree")

    return _JoinedReceiptEvidence(
        assistant=assistant,
        assistant_generation=ledger_record["assistant_generation"],  # type: ignore[arg-type]
        sequence=ledger_record["sequence"],  # type: ignore[arg-type]
        slot_id=ledger_record["slot_id"],  # type: ignore[arg-type]
        generation_id=ledger_record["generation_id"],  # type: ignore[arg-type]
        owner_token=ledger_record["owner_token"],  # type: ignore[arg-type]
        artifact_sha256=ledger_record["artifact_sha256"],  # type: ignore[arg-type]
        receipt_id=ledger_record["receipt_id"],  # type: ignore[arg-type]
        acknowledgement_sha256=ledger_record["acknowledgement_sha256"],  # type: ignore[arg-type]
        ledger_record_sha256="sha256:"
        + hashlib.sha256(
            json.dumps(ledger_record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest(),
        destination_fingerprint=destination,
        state_updated_at=float(state_updated),
        health_updated_at=float(health_updated),
    )


@dataclass(frozen=True, slots=True)
class _PrePostReceiptEvidence:
    pre_fault: _JoinedReceiptEvidence
    post_fault: _JoinedReceiptEvidence


class _DeliveryEvidenceAuthority:
    __slots__ = ()

    def __new__(cls) -> _DeliveryEvidenceAuthority:
        del cls
        raise _RunnerFoundationError("delivery evidence authority cannot be caller-constructed")


@dataclass(frozen=True, slots=True)
class _OwnedRunResult:
    pre_ledger_record: dict[str, object]
    pre_delivery_state_payload: dict[str, object]
    pre_terminal_state_payload: dict[str, object]
    pre_artifact_bytes: bytes
    pre_assistant_observation: _AssistantProcessObservation
    post_ledger_record: dict[str, object]
    post_delivery_state_payload: dict[str, object]
    post_terminal_state_payload: dict[str, object]
    post_artifact_bytes: bytes
    post_assistant_observation: _AssistantProcessObservation
    expected_launcher_pid: int
    report_interval_s: int
    ledger_records: tuple[dict[str, object], ...]
    observations: tuple[Any, ...]
    survivors: tuple[Any, ...]
    graceful: bool
    shutdown_elapsed: float
    collector: _CleanShaCollector


class _DeliveryEvidenceRegistry:
    """One-shot Evidence-bound records created by the integrated owner."""

    __slots__ = ("_records",)

    def __init__(self) -> None:
        self._records: dict[int, tuple[_DeliveryEvidenceAuthority, Any, dict[str, object]]] = {}

    def run(self, runner: Any, evidence: Any, selected: Any) -> None:
        if type(runner) is not _PosixSoakRunner or runner._used is not True:
            raise _RunnerFoundationError("delivery run is not owned by the active runner")
        result = _PosixSoakRunner._run_owned(runner, evidence, selected)
        if type(result) is not _OwnedRunResult:
            raise _RunnerFoundationError("owned runner returned an invalid private result")
        proof = _validate_pre_post_receipts(
            pre_ledger_record=result.pre_ledger_record,
            pre_delivery_state_payload=result.pre_delivery_state_payload,
            pre_terminal_state_payload=result.pre_terminal_state_payload,
            pre_artifact_bytes=result.pre_artifact_bytes,
            pre_assistant_observation=result.pre_assistant_observation,
            post_ledger_record=result.post_ledger_record,
            post_delivery_state_payload=result.post_delivery_state_payload,
            post_terminal_state_payload=result.post_terminal_state_payload,
            post_artifact_bytes=result.post_artifact_bytes,
            post_assistant_observation=result.post_assistant_observation,
            expected_launcher_pid=result.expected_launcher_pid,
            expected_interval_s=result.report_interval_s,
            ledger_records=result.ledger_records,
        )

        def encode(item: _JoinedReceiptEvidence) -> dict[str, object]:
            return {
                "assistant_pid": item.assistant.pid,
                "assistant_start_identity": item.assistant.start_identity,
                "assistant_generation": item.assistant_generation,
                "sequence": item.sequence,
                "receipt_id": item.receipt_id,
                "artifact_sha256": item.artifact_sha256,
                "artifact_name": (
                    f"periodic-g{item.assistant_generation}-s{item.sequence}-{item.artifact_sha256[7:]}.png"
                ),
                "acknowledgement_sha256": item.acknowledgement_sha256,
                "ledger_record_sha256": item.ledger_record_sha256,
                "destination_fingerprint": item.destination_fingerprint,
                "state_updated_at": item.state_updated_at,
                "health_updated_at": item.health_updated_at,
            }

        payload: dict[str, object] = {
            "schema": "cryodaq-soak-periodic-delivery-result/v1",
            "status": "PASS",
            "pre_fault": encode(proof.pre_fault),
            "post_fault": encode(proof.post_fault),
        }
        authority = object.__new__(_DeliveryEvidenceAuthority)
        self._records[id(authority)] = (authority, evidence, payload)
        try:
            evidence._accept_periodic_delivery_result(authority)
        except BaseException:
            self._records.pop(id(authority), None)
            raise
        _PosixSoakRunner._finish_owned(runner, evidence, result)

    def consume(self, authority: object, evidence: Any) -> dict[str, object]:
        record = self._records.get(id(authority))
        if record is None or record[0] is not authority or record[1] is not evidence:
            raise _RunnerFoundationError("delivery authority is unregistered, spent, or bound to another Evidence")
        del self._records[id(authority)]
        return record[2]


_DELIVERY_EVIDENCE = _DeliveryEvidenceRegistry()


def _consume_periodic_delivery_authority(authority: object, evidence: Any) -> dict[str, object]:
    return _DELIVERY_EVIDENCE.consume(authority, evidence)


def _validate_pre_post_receipts(
    *,
    pre_ledger_record: dict[str, object],
    pre_delivery_state_payload: dict[str, object],
    pre_terminal_state_payload: dict[str, object],
    pre_artifact_bytes: bytes,
    pre_assistant_observation: _AssistantProcessObservation,
    post_ledger_record: dict[str, object],
    post_delivery_state_payload: dict[str, object],
    post_terminal_state_payload: dict[str, object],
    post_artifact_bytes: bytes,
    post_assistant_observation: _AssistantProcessObservation,
    expected_launcher_pid: int,
    expected_interval_s: int,
    ledger_records: tuple[dict[str, object], ...],
) -> _PrePostReceiptEvidence:
    """Build both joins internally, then require exact assistant replacement."""

    pre_fault = _validate_joined_receipt(
        ledger_record=pre_ledger_record,
        delivery_state_payload=pre_delivery_state_payload,
        terminal_state_payload=pre_terminal_state_payload,
        artifact_bytes=pre_artifact_bytes,
        assistant_observation=pre_assistant_observation,
        expected_launcher_pid=expected_launcher_pid,
    )
    post_fault = _validate_joined_receipt(
        ledger_record=post_ledger_record,
        delivery_state_payload=post_delivery_state_payload,
        terminal_state_payload=post_terminal_state_payload,
        artifact_bytes=post_artifact_bytes,
        assistant_observation=post_assistant_observation,
        expected_launcher_pid=expected_launcher_pid,
    )
    if (
        pre_ledger_record["nonce"] != post_ledger_record["nonce"]
        or pre_fault.destination_fingerprint != post_fault.destination_fingerprint
    ):
        raise _RunnerFoundationError("replacement assistant changed the retained local capability authority")
    pre_active = pre_delivery_state_payload["active"]
    post_active = post_delivery_state_payload["active"]
    if (
        type(pre_active) is not dict
        or type(post_active) is not dict
        or type(pre_active["interval_s"]) is not int
        or pre_active["interval_s"] != expected_interval_s
        or post_active["interval_s"] != pre_active["interval_s"]
        or post_active["slot_end"] - pre_active["slot_end"] != pre_active["interval_s"]
        or post_active["config_fingerprint"] != pre_active["config_fingerprint"]
    ):
        raise _RunnerFoundationError("qualification receipts are not adjacent slots under one schedule")
    if len(ledger_records) != 2:
        raise _RunnerFoundationError("qualification requires exactly two receipt ledger records")
    if any(type(item) is not dict or not _ArtifactReceiptSink._valid_ledger_record(item) for item in ledger_records):
        raise _RunnerFoundationError("qualification ledger contains invalid records")
    expected_ids = (pre_fault.receipt_id, post_fault.receipt_id)
    observed_hashes = tuple(
        "sha256:"
        + hashlib.sha256(
            json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        for item in ledger_records
    )
    if (
        tuple(item["receipt_id"] for item in ledger_records) != expected_ids
        or observed_hashes != (pre_fault.ledger_record_sha256, post_fault.ledger_record_sha256)
        or len(set(expected_ids)) != 2
    ):
        raise _RunnerFoundationError("qualification ledger is duplicate, reordered, or incomplete")
    if (
        post_fault.assistant == pre_fault.assistant
        or pre_fault.sequence != 1
        or post_fault.sequence != 1
        or pre_fault.assistant_generation != 1
        or post_fault.assistant_generation != 2
        or post_fault.slot_id == pre_fault.slot_id
        or post_fault.generation_id == pre_fault.generation_id
        or post_fault.owner_token == pre_fault.owner_token
        or post_fault.state_updated_at <= pre_fault.state_updated_at
        or max(post_fault.health_updated_at, post_fault.state_updated_at)
        <= max(pre_fault.health_updated_at, pre_fault.state_updated_at)
    ):
        raise _RunnerFoundationError("replacement assistant lacks a strictly newer joined authority cut")
    return _PrePostReceiptEvidence(pre_fault, post_fault)


@dataclass(frozen=True, slots=True)
class _BridgeProcessObservation:
    identity: _ProcessIdentity
    parent_pid: int
    role: str
    alive: bool
    # The launcher pid the observer PROVED this bridge belongs to: either as a direct
    # child, or forked from a fork server that is itself a direct child. Zero means the
    # observer proved nothing, which is the default, so a construction that forgets the
    # field REFUSES rather than passes.
    #
    # It carries the PID and not a bare boolean on purpose. A boolean says only that some
    # launcher was proved, and the binder could not tell WHICH, so its error message named
    # a pid that had taken no part in the decision. The two pids coincide at today's single
    # call site; they would not have to at a second one.
    #
    # BE CLEAR ABOUT WHAT THE BINDER'S COMPARISON IS AND IS NOT. It is a FAIL-CLOSED
    # cross-check, not a second independent look at the process table -- the binder cannot
    # look at processes at all. `observe_bridge` already RAISES when it proves nothing, so
    # for any observation that function returns the comparison is satisfied by
    # construction. Its value is against an observation built by hand, or by a future
    # second call site, that never verified anything: the field defaults to zero and the
    # binder refuses. Saying it restores an independent parentage check would be a claim
    # the code does not support.
    verified_against_launcher_pid: int = 0


@dataclass(frozen=True, slots=True)
class _AssistantProcessObservation:
    identity: _ProcessIdentity
    parent_pid: int
    role: str
    alive: bool


def _bind_positive_assistant_identity(
    observation: _AssistantProcessObservation,
    *,
    expected_launcher_pid: int,
) -> _ProcessIdentity:
    if type(observation.alive) is not bool or not observation.alive:
        raise _RunnerFoundationError("reported assistant process is not alive")
    if type(expected_launcher_pid) is not int or expected_launcher_pid <= 0:
        raise _RunnerFoundationError("launcher identity is invalid")
    if observation.parent_pid != expected_launcher_pid:
        raise _RunnerFoundationError(
            "reported assistant is not a direct launcher child: "
            f"assistant pid {observation.identity.pid} reports parent {observation.parent_pid}, "
            f"launcher is {expected_launcher_pid}"
        )
    if observation.role != "assistant":
        raise _RunnerFoundationError("reported PID is not the allowlisted assistant role")
    return observation.identity


def _bind_positive_bridge_identity(
    record: _BridgeHandshakeRecord,
    observation: _BridgeProcessObservation,
) -> _ProcessIdentity:
    """Bind reported PID to one positive direct-child observer identity."""

    if type(observation.alive) is not bool or not observation.alive:
        raise _RunnerFoundationError("reported bridge process is not alive")
    if observation.identity.pid != record.bridge_pid:
        raise _RunnerFoundationError("observer bridge PID contradicts launcher record")
    if (
        type(observation.parent_pid) is not int
        or type(observation.verified_against_launcher_pid) is not int
        or observation.verified_against_launcher_pid != record.launcher_pid
    ):
        raise _RunnerFoundationError(
            "reported bridge does not belong to this launcher: "
            f"bridge pid {observation.identity.pid} reports parent {observation.parent_pid!r}; "
            f"the observer proved it belongs to launcher "
            f"{observation.verified_against_launcher_pid!r}, and the record names "
            f"{record.launcher_pid}"
        )
    if observation.role != "zmq_bridge":
        raise _RunnerFoundationError("reported PID is not the allowlisted bridge role")
    return observation.identity


class _BridgeEpochGuard:
    """Pure terminal guard for post-handshake PID/start/restart stability."""

    __slots__ = ("_identity", "_restart_count", "_terminal")

    def __init__(self, identity: _ProcessIdentity, restart_count: int) -> None:
        if type(restart_count) is not int or restart_count != 1:
            raise _RunnerFoundationError("bridge epoch must begin at restart count one")
        self._identity = identity
        self._restart_count = restart_count
        self._terminal = False

    def observe(self, identity: _ProcessIdentity, *, restart_count: int) -> None:
        if self._terminal:
            raise _RunnerFoundationError("bridge epoch guard is terminal")
        if type(restart_count) is not int or identity != self._identity or restart_count != self._restart_count:
            self._terminal = True
            raise _RunnerFoundationError("bridge PID/start identity changed or restarted")


def _parse_bridge_handshake(
    payload: bytes,
    *,
    expected_nonce: str,
    expected_launcher_pid: int,
    received_before_deadline: bool,
) -> _BridgeHandshakeRecord:
    """Parse one launcher-owned bridge record without granting runner authority."""

    if not received_before_deadline:
        raise _RunnerFoundationError("bridge handshake arrived after its deadline")
    if not payload or len(payload) > _MAX_BRIDGE_HANDSHAKE_BYTES or payload.count(b"\n") != 1:
        raise _RunnerFoundationError("bridge handshake is missing, duplicate, or oversized")
    if not payload.endswith(b"\n"):
        raise _RunnerFoundationError("bridge handshake record is incomplete")
    try:
        value = json.loads(payload[:-1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _RunnerFoundationError("bridge handshake is not canonical JSON") from exc
    expected_keys = {"schema", "version", "nonce", "launcher_pid", "bridge_pid", "restart_count"}
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise _RunnerFoundationError("bridge handshake keys are invalid")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
    if canonical != payload:
        raise _RunnerFoundationError("bridge handshake is not canonical")
    if (
        value["schema"] != _BRIDGE_HANDSHAKE_SCHEMA
        or type(value["version"]) is not int
        or value["version"] != _BRIDGE_HANDSHAKE_VERSION
    ):
        raise _RunnerFoundationError("bridge handshake schema is invalid")
    nonce = value["nonce"]
    launcher_pid = value["launcher_pid"]
    bridge_pid = value["bridge_pid"]
    restart_count = value["restart_count"]
    if not isinstance(nonce, str) or nonce != expected_nonce or re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
        raise _RunnerFoundationError("bridge handshake nonce mismatch")
    if launcher_pid != expected_launcher_pid or isinstance(launcher_pid, bool) or launcher_pid <= 0:
        raise _RunnerFoundationError("bridge handshake launcher PID mismatch")
    if isinstance(bridge_pid, bool) or not isinstance(bridge_pid, int) or bridge_pid <= 0 or bridge_pid == launcher_pid:
        raise _RunnerFoundationError("bridge handshake bridge PID is invalid")
    if type(restart_count) is not int or restart_count != 1:
        raise _RunnerFoundationError("bridge restarted before positive identity acceptance")
    return _BridgeHandshakeRecord(nonce, launcher_pid, bridge_pid, restart_count)


def _parse_bridge_data(
    payload: bytes,
    *,
    expected_nonce: str,
    expected_launcher_pid: int,
    expected_bridge_pid: int,
    after_sequence: int,
) -> _BridgeDataRecord:
    """Parse one bounded launcher-observed bridge-data fact."""

    if not payload or len(payload) > _MAX_BRIDGE_HANDSHAKE_BYTES or not payload.endswith(b"\n"):
        raise _RunnerFoundationError("bridge data fact is incomplete or oversized")
    try:
        value = json.loads(payload[:-1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _RunnerFoundationError("bridge data fact is not canonical JSON") from exc
    expected = {
        "schema",
        "version",
        "nonce",
        "launcher_pid",
        "bridge_pid",
        "restart_count",
        "sequence",
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
    if type(value) is not dict or set(value) != expected or canonical != payload:
        raise _RunnerFoundationError("bridge data fact schema is invalid")
    sequence = value["sequence"]
    if (
        value["schema"] != _BRIDGE_DATA_SCHEMA
        or type(value["version"]) is not int
        or value["version"] != _BRIDGE_HANDSHAKE_VERSION
        or value["nonce"] != expected_nonce
        or value["launcher_pid"] != expected_launcher_pid
        or value["bridge_pid"] != expected_bridge_pid
        or type(value["restart_count"]) is not int
        or value["restart_count"] != 1
        or type(sequence) is not int
        or sequence <= after_sequence
    ):
        raise _RunnerFoundationError("bridge data fact contradicts the accepted epoch")
    return _BridgeDataRecord(
        expected_nonce,
        expected_launcher_pid,
        expected_bridge_pid,
        1,
        sequence,
    )


@dataclass(frozen=True, slots=True)
class _StreamEvidence:
    byte_count: int
    sha256: str
    output_complete: bool


class _BoundedStreamDigest:
    """Continuously hash bounded output without retaining its bytes."""

    __slots__ = ("_byte_count", "_complete", "_finalized", "_hash", "_limit")

    def __init__(self, *, limit: int = _MAX_STREAM_BYTES) -> None:
        if isinstance(limit, bool) or limit <= 0 or limit > _MAX_STREAM_BYTES:
            raise _RunnerFoundationError("stream limit is outside the reviewed bound")
        self._limit = limit
        self._byte_count = 0
        self._hash = hashlib.sha256()
        self._complete = True
        self._finalized = False

    def feed(self, chunk: bytes) -> None:
        if self._finalized:
            raise _RunnerFoundationError("finalized stream cannot accept bytes")
        if not isinstance(chunk, bytes):
            raise TypeError("stream chunk must be bytes")
        if not self._complete:
            raise _RunnerFoundationError("overflowed stream is terminal")
        next_count = self._byte_count + len(chunk)
        if next_count > self._limit:
            self._complete = False
            raise _RunnerFoundationError("stream output exceeded the reviewed bound")
        self._hash.update(chunk)
        self._byte_count = next_count

    def finalize(self) -> _StreamEvidence:
        if self._finalized:
            raise _RunnerFoundationError("stream evidence can be finalized only once")
        self._finalized = True
        return _StreamEvidence(
            byte_count=self._byte_count,
            sha256=f"sha256:{self._hash.hexdigest()}",
            output_complete=self._complete,
        )


def _decode_complete_output(stdout: _StreamEvidence, payload: bytes) -> str:
    if not stdout.output_complete or len(payload) != stdout.byte_count:
        raise _RunnerFoundationError("parser requires complete runner-owned output")
    if f"sha256:{hashlib.sha256(payload).hexdigest()}" != stdout.sha256:
        raise _RunnerFoundationError("output bytes contradict streaming evidence")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _RunnerFoundationError("pytest output is not strict UTF-8") from exc


_DIAGNOSTIC_OUTPUT_LIMIT = 4096
_DIAGNOSTIC_HEAD_SHARE = _DIAGNOSTIC_OUTPUT_LIMIT // 2
_DIAGNOSTIC_TRUNCATION_MARKER = "\n...[truncated %d character(s); the tail of the stream follows]\n"


def _child_failure_message(exit_code: int, stdout: bytes, stderr: bytes) -> str:
    """Describe a failed child run, keeping the END of each stream as well as its start.

    Keeping only the first characters is what a length bound does if nobody chooses,
    and for a pytest child it discards exactly the part that says what went wrong:
    the assertion, the traceback and the short test summary all sit at the END. A
    real ubuntu-latest failure arrived here as four kilobytes of the child test's own
    source text, then ``...[truncated]`` where the cause would have been, which is a
    message that names a condition and withholds its subject.

    The bound itself is unchanged: at most ``_DIAGNOSTIC_OUTPUT_LIMIT`` characters of
    a stream reach the message. They are now taken from both ends instead of one.
    """

    def bounded(payload: bytes) -> str:
        text = payload.decode("utf-8", errors="replace")
        if not text:
            return "<empty>"
        if len(text) <= _DIAGNOSTIC_OUTPUT_LIMIT:
            return text
        tail_share = _DIAGNOSTIC_OUTPUT_LIMIT - _DIAGNOSTIC_HEAD_SHARE
        dropped = len(text) - _DIAGNOSTIC_OUTPUT_LIMIT
        return (
            text[:_DIAGNOSTIC_HEAD_SHARE] + (_DIAGNOSTIC_TRUNCATION_MARKER % dropped) + text[len(text) - tail_share :]
        )

    return f"exit code {exit_code}; captured stdout:\n{bounded(stdout)}; captured stderr:\n{bounded(stderr)}"


def _parse_exact_collection(
    *,
    stdout_evidence: _StreamEvidence,
    stdout: bytes,
    stderr_evidence: _StreamEvidence,
    stderr: bytes,
    exit_code: int,
) -> tuple[str, ...]:
    if exit_code != 0:
        raise _RunnerFoundationError(
            "exact-six collection execution failed: " + _child_failure_message(exit_code, stdout, stderr)
        )
    out = _decode_complete_output(stdout_evidence, stdout)
    err = _decode_complete_output(stderr_evidence, stderr)
    if err.strip():
        raise _RunnerFoundationError("exact-six collection wrote stderr")
    lowered = out.casefold()
    if any(marker in lowered for marker in _FORBIDDEN_PYTEST_MARKERS):
        raise _RunnerFoundationError("exact-six collection contains a forbidden pytest outcome")
    lines = tuple(line.strip() for line in out.splitlines() if line.strip())
    nodes = tuple(line for line in lines if line.startswith(f"{_TEST_FILE}::"))
    summaries = tuple(line for line in lines if _COLLECTION_SUMMARY_RE.fullmatch(line))
    if nodes != _EXACT_NODE_IDS or len(summaries) != 1:
        raise _RunnerFoundationError("collection is not the exact ordered six-node matrix")
    if len(lines) != len(nodes) + 1:
        raise _RunnerFoundationError("collection output contains unexpected records")
    return nodes


def _validate_exact_execution(
    *,
    stdout_evidence: _StreamEvidence,
    stdout: bytes,
    stderr_evidence: _StreamEvidence,
    stderr: bytes,
    exit_code: int,
) -> None:
    if exit_code != 0:
        raise _RunnerFoundationError("exact-six execution failed: " + _child_failure_message(exit_code, stdout, stderr))
    out = _decode_complete_output(stdout_evidence, stdout)
    err = _decode_complete_output(stderr_evidence, stderr)
    if err.strip():
        raise _RunnerFoundationError("exact-six execution wrote stderr")
    lowered = out.casefold()
    if any(marker in lowered for marker in _FORBIDDEN_PYTEST_MARKERS):
        raise _RunnerFoundationError("exact-six execution contains a forbidden pytest outcome")
    lines = tuple(line.strip() for line in out.splitlines() if line.strip())
    if len(lines) != 2 or _PROGRESS_RE.fullmatch(lines[0]) is None or _SUMMARY_RE.fullmatch(lines[1]) is None:
        raise _RunnerFoundationError("execution output is not the exact six-pass result")


@dataclass(frozen=True, slots=True)
class _CompletedCommand:
    stdout_evidence: _StreamEvidence
    stdout: bytes
    stderr_evidence: _StreamEvidence
    stderr: bytes
    exit_code: int


def _require_posix_exact_six() -> None:
    if os.name != "posix" or sys.platform != "linux":
        raise _RunnerActivationDisabled("exact-six execution authority requires Linux subreaper ownership")


def _runner_subreaper_state() -> bool:
    """Return the verified Linux child-subreaper state."""

    _require_posix_exact_six()
    libc = ctypes.CDLL(None, use_errno=True)
    observed = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(observed), 0, 0, 0) != 0:  # PR_GET_CHILD_SUBREAPER
        raise _RunnerActivationDisabled("Linux child-subreaper authority is unavailable")
    return bool(observed.value)


def _apply_runner_subreaper(enabled: bool) -> None:
    """Set and verify Linux child-subreaper state."""

    _require_posix_exact_six()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, int(enabled), 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise _RunnerActivationDisabled("Linux child-subreaper activation failed")
    observed = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(observed), 0, 0, 0) != 0 or observed.value != int(enabled):
        raise _RunnerActivationDisabled("Linux child-subreaper authority is unavailable")


def _set_runner_subreaper(enabled: bool) -> bool:
    """Set Linux child-subreaper state and return the prior state."""

    prior = _runner_subreaper_state()
    _apply_runner_subreaper(enabled)
    return prior


@contextmanager
def _block_termination_signals() -> Any:
    """Defer SIGINT/SIGTERM until a fail-closed cleanup boundary is complete."""

    if sys.platform != "linux" or not hasattr(signal, "pthread_sigmask"):
        raise _RunnerActivationDisabled("Linux termination-signal masking is unavailable")
    blocked = {signal.SIGINT, signal.SIGTERM}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def _enable_runner_subreaper() -> None:
    """Make escaped descendants reparent to this qualification owner."""

    _set_runner_subreaper(True)


def _waitid_terminal_without_reap(pid: int, *, deadline: float) -> bool:
    """Observe one owned child terminal while keeping its PID/PGID reserved."""

    required = ("P_PID", "WEXITED", "WNOHANG", "WNOWAIT")
    if sys.platform != "linux" or not hasattr(os, "waitid") or any(not hasattr(os, name) for name in required):
        raise _RunnerActivationDisabled("Linux waitid WNOWAIT authority is unavailable")
    options = os.WEXITED | os.WNOHANG | os.WNOWAIT
    while time.monotonic() < deadline:
        try:
            result = os.waitid(os.P_PID, pid, options)
        except InterruptedError:
            continue
        except ChildProcessError as exc:
            raise _RunnerFoundationError("owned launcher was reaped before settlement proof") from exc
        if result is not None:
            return True
        time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
    return False


def _settle_unbound_session(process: subprocess.Popen[bytes]) -> None:
    """Settle a new-session child while its unreaped PID makes numeric PGID safe."""

    pid = process.pid
    try:
        owns_group = os.getpgid(pid) == pid
    except ProcessLookupError:
        owns_group = False
    try:
        if owns_group:
            os.killpg(pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        pass
    if not _waitid_terminal_without_reap(pid, deadline=time.monotonic() + _PROCESS_GROUP_GRACE_S):
        try:
            if owns_group:
                os.killpg(pid, getattr(signal, "SIGKILL", 9))
            else:
                process.kill()
        except ProcessLookupError:
            pass
        if not _waitid_terminal_without_reap(pid, deadline=time.monotonic() + _PROCESS_GROUP_GRACE_S):
            raise _RunnerFoundationError("unbound launcher did not settle")
    if owns_group:
        try:
            os.killpg(pid, getattr(signal, "SIGKILL", 9))
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=_PROCESS_GROUP_GRACE_S)
    except subprocess.TimeoutExpired as exc:
        raise _RunnerFoundationError("unbound launcher could not be reaped") from exc


def _spawn_gated_source(
    *,
    environment: dict[str, str],
    stdout: Any,
    inherited_fds: tuple[int, ...],
    observer: _LockedPsutilObserver,
    source_root: Path = _REPO_ROOT,
) -> tuple[subprocess.Popen[bytes], _ProcessIdentity]:
    """Bind exact same-PID session authority before the source launcher can exec."""

    gate_read, gate_write = os.pipe()
    argv = (sys.executable, "-I", "-c", _SOURCE_GATE_CODE, str(gate_read), *_SOURCE_ARGV)
    try:
        process = subprocess.Popen(
            argv,
            cwd=Path(source_root).resolve(strict=True),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            close_fds=True,
            pass_fds=(gate_read, *inherited_fds),
            start_new_session=True,
        )
    except BaseException:
        os.close(gate_read)
        os.close(gate_write)
        raise
    os.close(gate_read)
    try:
        identity = observer.identity_for_pid(process.pid)
        if os.getpgid(process.pid) != process.pid:
            raise _RunnerFoundationError("source launcher does not own its process group")
        observer.recheck_exact(identity)
        if os.write(gate_write, b"G") != 1:
            raise _RunnerFoundationError("source launcher gate release was incomplete")
    except BaseException:
        os.close(gate_write)
        _settle_unbound_session(process)
        raise
    os.close(gate_write)
    return process, identity


def _settle_adopted_owner_descendants(
    *,
    observer: _LockedPsutilObserver,
    owner: _ProcessIdentity,
    deadline: float,
) -> tuple[_ProcessIdentity, ...]:
    """Kill/reap late subreaper adoptees and prove two stable empty scans."""

    settlement_deadline = max(deadline, time.monotonic() + _PROCESS_GROUP_GRACE_S)
    observed: set[_ProcessIdentity] = set()
    empty_scans = 0
    while time.monotonic() < settlement_deadline and empty_scans < 2:
        descendants = tuple(observer.descendants(owner, include_zombies=True))
        if descendants:
            observed.update(descendants)
            empty_scans = 0
            for identity in sorted(set(descendants), key=lambda item: item.pid, reverse=True):
                try:
                    observer.signal_exact_for_cleanup(identity, getattr(signal, "SIGKILL", 9))
                except _ObservedProcessGone:
                    pass
                try:
                    terminal = os.waitid(os.P_PID, identity.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                except ChildProcessError:
                    terminal = None
                if terminal is not None:
                    try:
                        os.waitpid(identity.pid, os.WNOHANG)
                    except ChildProcessError:
                        pass
        else:
            empty_scans += 1
        if empty_scans < 2:
            time.sleep(min(0.05, max(0.001, settlement_deadline - time.monotonic())))
    if empty_scans < 2:
        raise _RunnerFoundationError("qualification owner did not reach a stable empty descendant cut")
    return tuple(sorted(observed, key=lambda item: item.pid))


def _reap_pinned_owned_session(
    process: subprocess.Popen[bytes],
    *,
    observer: _LockedPsutilObserver,
    expected: _ProcessIdentity,
    owner: _ProcessIdentity,
    deadline: float,
    reject_survivors: bool,
) -> int:
    """Reap a terminal pinned leader after all adopted descendants settle."""

    observer.recheck_exact(expected)
    if os.getpgid(process.pid) != process.pid:
        raise _RunnerFoundationError("source launcher lost process-group ownership before reap")
    settlement_deadline = max(deadline, time.monotonic() + _PROCESS_GROUP_GRACE_S)
    empty_group = 0
    empty_descendants = 0
    observed_survivors: set[_ProcessIdentity] = set()
    while time.monotonic() < settlement_deadline and (empty_group < 2 or empty_descendants < 2):
        members = tuple(identity for identity in observer.group_members(process.pid) if identity != expected)
        descendants = tuple(
            identity for identity in observer.descendants(owner, include_zombies=True) if identity != expected
        )
        if members:
            observed_survivors.update(members)
            empty_group = 0
        else:
            empty_group += 1
        if descendants:
            observed_survivors.update(descendants)
            empty_descendants = 0
        else:
            empty_descendants += 1
        for identity in sorted(set(members) | set(descendants), key=lambda item: item.pid, reverse=True):
            try:
                observer.signal_exact_for_cleanup(identity, getattr(signal, "SIGKILL", 9))
            except _ObservedProcessGone:
                pass
            try:
                terminal = os.waitid(os.P_PID, identity.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            except ChildProcessError:
                terminal = None
            if terminal is not None:
                try:
                    os.waitpid(identity.pid, os.WNOHANG)
                except ChildProcessError:
                    pass
        if empty_group < 2 or empty_descendants < 2:
            time.sleep(min(0.05, max(0.001, settlement_deadline - time.monotonic())))
    if empty_group < 2 or empty_descendants < 2:
        raise _RunnerFoundationError("source launcher ownership did not reach a stable empty cut")
    return_code = process.wait(timeout=_PROCESS_GROUP_GRACE_S)
    observed_survivors.update(
        _settle_adopted_owner_descendants(
            observer=observer,
            owner=owner,
            deadline=time.monotonic() + _PROCESS_GROUP_GRACE_S,
        )
    )
    if observed_survivors and reject_survivors:
        raise _RunnerFoundationError("source launcher left process survivors at graceful exit")
    return return_code


def _wait_and_reap_owned_session(
    process: subprocess.Popen[bytes],
    *,
    observer: _LockedPsutilObserver,
    expected: _ProcessIdentity,
    owner: _ProcessIdentity,
    timeout_s: float,
) -> int:
    """Pin the exited leader while proving its session and descendants empty."""

    deadline = time.monotonic() + timeout_s
    if not _waitid_terminal_without_reap(process.pid, deadline=deadline):
        raise _RunnerFoundationError("source launcher exceeded graceful shutdown ceiling")
    return _reap_pinned_owned_session(
        process,
        observer=observer,
        expected=expected,
        owner=owner,
        deadline=deadline,
        reject_survivors=True,
    )


def _force_settle_owned_session(
    process: subprocess.Popen[bytes],
    *,
    observer: _LockedPsutilObserver,
    expected: _ProcessIdentity,
    owner: _ProcessIdentity,
) -> None:
    """Force a failed source run to a proven empty subreaper-owned cut."""

    try:
        observer.signal_exact_for_cleanup(expected, signal.SIGTERM)
    except _ObservedProcessGone:
        pass
    deadline = time.monotonic() + _PROCESS_GROUP_GRACE_S
    if not _waitid_terminal_without_reap(process.pid, deadline=deadline):
        try:
            observer.signal_exact_for_cleanup(expected, getattr(signal, "SIGKILL", 9))
        except _ObservedProcessGone:
            pass
        deadline = time.monotonic() + _PROCESS_GROUP_GRACE_S
        if not _waitid_terminal_without_reap(process.pid, deadline=deadline):
            raise _RunnerFoundationError("failed source launcher could not be pinned terminal")
    _reap_pinned_owned_session(
        process,
        observer=observer,
        expected=expected,
        owner=owner,
        deadline=deadline,
        reject_survivors=False,
    )


def _settle_process_group(
    process: subprocess.Popen[bytes],
    *,
    observer: _LockedPsutilObserver,
    expected: _ProcessIdentity,
) -> None:
    """Boundedly terminate the runner-owned session and reap its leader."""

    pid = process.pid
    sigkill = getattr(signal, "SIGKILL", 9)

    def recheck() -> None:
        try:
            observer.recheck_exact(expected)
        except AttributeError:
            if observer.identity_for_pid(pid) != expected:
                raise _RunnerFoundationError("exact-six process identity changed; refusing numeric PGID") from None

    def group_exists() -> bool:
        recheck()
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return False
        return True

    recheck()
    if os.getpgid(pid) != pid:
        raise _RunnerFoundationError("exact-six child no longer owns its process group")
    recheck()
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + _PROCESS_GROUP_GRACE_S
    while group_exists() and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
    if group_exists():
        recheck()
        try:
            os.killpg(pid, sigkill)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=_PROCESS_GROUP_GRACE_S)
    except subprocess.TimeoutExpired as exc:
        raise _RunnerFoundationError("exact-six process leader did not settle") from exc


def _observe_stable_descendant_cut(
    *,
    observer: _LockedPsutilObserver,
    expected: _ProcessIdentity,
    deadline: float,
    signum: int | None = None,
) -> tuple[tuple[_ProcessIdentity, ...], bool]:
    """Require two consecutive empty scans within the existing bound."""

    signaled: set[_ProcessIdentity] = set()
    descendants: tuple[_ProcessIdentity, ...] = ()
    empty_scans = 0
    while time.monotonic() < deadline and empty_scans < 2:
        descendants = observer.descendants(expected)
        if descendants:
            empty_scans = 0
            if signum is not None:
                for identity in reversed(descendants):
                    if identity not in signaled:
                        observer.signal_exact_for_cleanup(identity, signum)
                        signaled.add(identity)
        else:
            empty_scans += 1
        if empty_scans < 2:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.05, max(0.001, remaining)))
    return descendants, empty_scans == 2


def _settle_owned_tree_once(
    process: subprocess.Popen[bytes],
    *,
    observer: _LockedPsutilObserver,
    expected: _ProcessIdentity,
) -> None:
    deadline = time.monotonic() + _PROCESS_GROUP_GRACE_S
    descendants, stable = _observe_stable_descendant_cut(
        observer=observer,
        expected=expected,
        deadline=deadline,
        signum=signal.SIGTERM,
    )
    if not stable:
        deadline = time.monotonic() + _PROCESS_GROUP_GRACE_S
        descendants, stable = _observe_stable_descendant_cut(
            observer=observer,
            expected=expected,
            deadline=deadline,
            signum=getattr(signal, "SIGKILL", 9),
        )
    if descendants or not stable:
        raise _RunnerFoundationError("owned exact-six descendants did not settle")
    _settle_process_group(process, observer=observer, expected=expected)


def _settle_owned_tree(
    process: subprocess.Popen[bytes],
    *,
    observer: _LockedPsutilObserver,
    expected: _ProcessIdentity,
) -> None:
    """Finish settlement despite two interruptions, then propagate the first."""

    interrupted: BaseException | None = None
    completed = False
    for _attempt in range(3):
        try:
            _settle_owned_tree_once(process, observer=observer, expected=expected)
        except BaseException as exc:
            is_interruption = isinstance(exc, (KeyboardInterrupt, SystemExit)) or type(exc).__name__ == "RunInterrupted"
            if not is_interruption:
                raise
            if interrupted is None:
                interrupted = exc
        else:
            completed = True
            break
    if not completed:
        raise _RunnerFoundationError("owned-tree cleanup was interrupted at every bounded attempt") from interrupted
    if interrupted is not None:
        raise interrupted


def _execute_bounded_process(
    argv: tuple[str, ...],
    *,
    observer: _LockedPsutilObserver,
    snapshot: _ExecutionSnapshot,
    timeout_s: float = _EXACT_SIX_TIMEOUT_S,
) -> _CompletedCommand:
    """Run one fixed pytest command with bounded output and session cleanup."""

    _require_posix_exact_six()
    if argv not in {_COLLECTION_ARGV, _EXECUTION_ARGV}:
        raise _RunnerFoundationError("runner command is not fixed exact-six argv")
    if type(timeout_s) not in {int, float} or not math.isfinite(float(timeout_s)) or not 0 < timeout_s <= 300:
        raise _RunnerFoundationError("exact-six timeout is outside the reviewed bound")
    status_read, status_write = os.pipe()
    release_read, release_write = os.pipe()
    start_read, start_write = os.pipe()
    supervisor_argv = (
        str(snapshot.interpreter),
        "-I",
        "-c",
        _SUPERVISOR_CODE,
        str(status_write),
        str(release_read),
        str(start_read),
        *argv,
    )
    try:
        process = subprocess.Popen(
            supervisor_argv,
            cwd=snapshot.root,
            env=snapshot.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(status_write, release_read, start_read),
            start_new_session=True,
        )
    except BaseException:
        for fd in (status_read, status_write, release_read, release_write, start_read, start_write):
            os.close(fd)
        raise
    os.close(status_write)
    os.close(release_read)
    os.close(start_read)
    try:
        identity = observer.identity_for_pid(process.pid)
    except BaseException:
        os.close(start_write)
        os.close(release_write)
        os.close(status_read)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        _settle_unbound_session(process)
        raise
    try:
        os.write(start_write, b"G")
    except BaseException:
        os.close(start_write)
        _settle_owned_tree(process, observer=observer, expected=identity)
        os.close(release_write)
        os.close(status_read)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        raise
    else:
        os.close(start_write)
    if process.stdout is None or process.stderr is None:
        _settle_owned_tree(process, observer=observer, expected=identity)
        raise _RunnerFoundationError("exact-six pipes are unavailable")
    stdout_digest = _BoundedStreamDigest()
    stderr_digest = _BoundedStreamDigest()
    stdout = bytearray()
    stderr = bytearray()
    status = bytearray()
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + float(timeout_s)
    try:
        if observer.identity_for_pid(process.pid) != identity:
            raise _RunnerFoundationError("exact-six process identity changed before PGID probe")
        if os.getpgid(process.pid) != process.pid:
            raise _RunnerFoundationError("exact-six child does not own its process group")
        selector.register(process.stdout, selectors.EVENT_READ, ("stream", stdout_digest, stdout))
        selector.register(process.stderr, selectors.EVENT_READ, ("stream", stderr_digest, stderr))
        selector.register(status_read, selectors.EVENT_READ, ("status", None, status))
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _RunnerFoundationError("exact-six command timed out")
            for key, _events in selector.select(min(remaining, 0.25)):
                chunk = os.read(key.fd, 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                kind, digest, retained = key.data
                if kind == "status" and len(retained) + len(chunk) > _STATUS_STRUCT.size:
                    raise _RunnerFoundationError("exact-six supervisor status is oversized")
                if digest is not None:
                    digest.feed(chunk)
                retained.extend(chunk)
        if len(status) != _STATUS_STRUCT.size:
            raise _RunnerFoundationError("exact-six supervisor status is incomplete")
        exit_code = _STATUS_STRUCT.unpack(status)[0]
        quiescence_deadline = time.monotonic() + _PROCESS_GROUP_GRACE_S
        descendants, stable = _observe_stable_descendant_cut(
            observer=observer,
            expected=identity,
            deadline=quiescence_deadline,
        )
        if descendants or not stable:
            raise _RunnerFoundationError("exact-six child left owned descendants")
        if observer.group_members(process.pid) != (identity,):
            raise _RunnerFoundationError("exact-six child left process-group survivors")
    except BaseException:
        _settle_owned_tree(process, observer=observer, expected=identity)
        raise
    else:
        _settle_owned_tree(process, observer=observer, expected=identity)
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
        os.close(status_read)
        os.close(release_write)
    return _CompletedCommand(
        stdout_digest.finalize(),
        bytes(stdout),
        stderr_digest.finalize(),
        bytes(stderr),
        exit_code,
    )


class _ExactSixAuthority:
    __slots__ = ()

    def __new__(cls) -> _ExactSixAuthority:
        del cls
        raise _RunnerFoundationError("exact-six authority cannot be caller-constructed")


class _ExactSixProvenance:
    __slots__ = ()

    def __new__(cls) -> _ExactSixProvenance:
        del cls
        raise _RunnerFoundationError("exact-six provenance cannot be caller-constructed")


class _ExactSixExecutionRegistry:
    """Own completion registration; calling execute necessarily runs both commands."""

    __slots__ = ("_provenance", "_records")

    def __init__(self) -> None:
        self._records: dict[int, tuple[_ExactSixAuthority, Any, dict[str, object]]] = {}
        self._provenance: dict[int, tuple[_ExactSixProvenance, Any, bool]] = {}

    def execute(self, evidence: Any, *, collector: _CleanShaCollector | None = None) -> dict[str, object]:
        _require_posix_exact_six()
        try:
            import psutil
        except ImportError as exc:
            raise _RunnerActivationDisabled("locked psutil observer is unavailable") from exc
        observer = _LockedPsutilObserver(psutil)
        collector = collector or _CleanShaCollector(_REPO_ROOT)
        git_sha = collector.observe(_ShaBoundary.BEFORE_COLLECTION).git_sha
        with _sealed_execution_snapshot(git_sha) as snapshot:
            collection = _execute_bounded_process(_COLLECTION_ARGV, observer=observer, snapshot=snapshot)
            _parse_exact_collection(
                stdout_evidence=collection.stdout_evidence,
                stdout=collection.stdout,
                stderr_evidence=collection.stderr_evidence,
                stderr=collection.stderr,
                exit_code=collection.exit_code,
            )
            collector.observe(_ShaBoundary.BETWEEN_COLLECTION_AND_EXECUTION)
            snapshot.assert_sealed()
            execution = _execute_bounded_process(_EXECUTION_ARGV, observer=observer, snapshot=snapshot)
            _validate_exact_execution(
                stdout_evidence=execution.stdout_evidence,
                stdout=execution.stdout,
                stderr_evidence=execution.stderr_evidence,
                stderr=execution.stderr,
                exit_code=execution.exit_code,
            )
            snapshot.assert_sealed()
        collector.observe(_ShaBoundary.AFTER_EXECUTION)
        payload: dict[str, object] = {
            "schema": "cryodaq-exact-six-result/v1",
            "command": list(_EXECUTION_ARGV),
            "test_identity": f"{_TEST_FILE}::exact-six",
            "git_sha": git_sha,
            "exit_code": execution.exit_code,
            "status": "PASS",
        }
        authority = object.__new__(_ExactSixAuthority)
        self._records[id(authority)] = (authority, evidence, payload)
        evidence._accept_exact_six_result(authority)
        return payload

    def consume(self, authority: object, evidence: Any) -> tuple[dict[str, object], _ExactSixProvenance]:
        record = self._records.get(id(authority))
        if record is None or record[0] is not authority or record[1] is not evidence:
            raise _RunnerFoundationError("exact-six authority is unregistered, spent, or bound to another Evidence")
        del self._records[id(authority)]
        provenance = object.__new__(_ExactSixProvenance)
        self._provenance[id(provenance)] = (provenance, evidence, False)
        return record[2], provenance

    def consume_provenance(self, provenance: object, evidence: Any) -> None:
        record = self._provenance.get(id(provenance))
        if record is None or record[0] is not provenance or record[1] is not evidence:
            raise _RunnerFoundationError("exact-six provenance is unregistered or bound to another Evidence")
        if not record[2]:
            self._provenance[id(provenance)] = (record[0], record[1], True)


_EXACT_SIX_EXECUTIONS = _ExactSixExecutionRegistry()


def _collect_and_execute_exact_six(evidence: Any) -> dict[str, object]:
    return _EXACT_SIX_EXECUTIONS.execute(evidence)


def _consume_exact_six_authority(authority: object, evidence: Any) -> tuple[dict[str, object], _ExactSixProvenance]:
    return _EXACT_SIX_EXECUTIONS.consume(authority, evidence)


def _consume_exact_six_provenance(provenance: object, evidence: Any) -> None:
    _EXACT_SIX_EXECUTIONS.consume_provenance(provenance, evidence)


class _CleanupPhase(StrEnum):
    IDLE = "idle"
    REQUESTED = "requested"
    COMPLETE = "complete"
    TERMINAL_IDENTITY_MISMATCH = "terminal_identity_mismatch"


@dataclass(frozen=True, slots=True)
class _CleanupEvidence:
    phase: _CleanupPhase
    process_group_id: int
    leader: _ProcessIdentity
    descendants: tuple[_ProcessIdentity, ...]
    forced: bool


class _CancellationCleanupContract:
    """Pure cleanup-once state; R2 performs signals and reaping."""

    __slots__ = ("_descendants", "_forced", "_leader", "_phase", "_process_group_id")

    def __init__(
        self,
        process_group_id: int,
        leader: _ProcessIdentity,
        descendants: tuple[_ProcessIdentity, ...],
    ) -> None:
        if isinstance(process_group_id, bool) or process_group_id <= 0:
            raise _RunnerFoundationError("process group ID must be positive")
        if not isinstance(leader, _ProcessIdentity) or leader.pid != process_group_id:
            raise _RunnerFoundationError("declared leader must own the process-group ID")
        descendants = tuple(descendants)
        if sum(item == leader for item in descendants) != 1:
            raise _RunnerFoundationError("cleanup must contain exactly one declared leader identity")
        if len({item.pid for item in descendants}) != len(descendants):
            raise _RunnerFoundationError("cleanup descendant PIDs must be unique across epochs")
        self._process_group_id = process_group_id
        self._leader = leader
        self._descendants = tuple(descendants)
        self._phase = _CleanupPhase.IDLE
        self._forced = False

    def request(self) -> _CleanupEvidence:
        if self._phase is not _CleanupPhase.IDLE:
            raise _RunnerFoundationError("cleanup can be requested only once")
        self._phase = _CleanupPhase.REQUESTED
        return self.evidence()

    def complete(self, *, forced: bool) -> _CleanupEvidence:
        if self._phase is not _CleanupPhase.REQUESTED:
            raise _RunnerFoundationError("cleanup must be requested before completion")
        if not isinstance(forced, bool):
            raise TypeError("forced must be a bool")
        self._forced = forced
        self._phase = _CleanupPhase.COMPLETE
        return self.evidence()

    def record_identity_recheck(self, observed: _ProcessIdentity) -> None:
        """Require exact PID/start continuity before each future R2 operation.

        R2 must call this immediately before every signal and reap. A missing
        PID, changed start identity, or PID reuse is terminal; this R1 method
        intentionally performs no process operation itself.
        """

        if self._phase is not _CleanupPhase.REQUESTED:
            raise _RunnerFoundationError("identity recheck requires requested cleanup")
        expected = next((item for item in self._descendants if item.pid == observed.pid), None)
        if expected != observed:
            self._phase = _CleanupPhase.TERMINAL_IDENTITY_MISMATCH
            raise _RunnerFoundationError("PID/start identity mismatch is terminal; do not signal or reap")

    def evidence(self) -> _CleanupEvidence:
        return _CleanupEvidence(
            self._phase,
            self._process_group_id,
            self._leader,
            self._descendants,
            self._forced,
        )


class _PosixSoakRunner:
    """Single-use owner of the real Linux source-mode short qualification."""

    __slots__ = ("_prior_subreaper", "_subreaper_restored", "_used")

    def __init__(self) -> None:
        self._used = False
        self._prior_subreaper: bool | None = None
        self._subreaper_restored = False

    @staticmethod
    def require_platform() -> None:
        _require_posix_exact_six()
        if not hasattr(signal, "pthread_sigmask"):
            raise _RunnerActivationDisabled("Linux termination-signal masking is unavailable")
        try:
            signal.pthread_sigmask(signal.SIG_BLOCK, set())
        except (OSError, RuntimeError, ValueError) as exc:
            raise _RunnerActivationDisabled("Linux termination-signal masking is unavailable") from exc

    @staticmethod
    def _pipe_records(pipe: _BridgeHandshakePipe, retained: bytearray) -> list[bytes]:
        os.set_blocking(pipe.read_fd, False)
        while True:
            try:
                chunk = os.read(pipe.read_fd, _MAX_BRIDGE_HANDSHAKE_BYTES)
            except BlockingIOError:
                break
            if not chunk:
                break
            retained.extend(chunk)
            if len(retained) > 64 * _MAX_BRIDGE_HANDSHAKE_BYTES:
                raise _RunnerFoundationError("bridge evidence stream is oversized")
        records: list[bytes] = []
        while b"\n" in retained:
            index = retained.index(b"\n") + 1
            records.append(bytes(retained[:index]))
            del retained[:index]
        return records

    @staticmethod
    def _load_roles(observer: Any, launcher: Any, bridge: Any) -> tuple[dict[str, Any], dict[Any, Any]]:
        from scripts import soak_mock_stack as soak

        snapshots = tuple(observer.snapshot())
        tree = soak.descendants(snapshots, launcher)
        return soak.classify_tree(tree, launcher, bridge_identity=bridge), tree

    @staticmethod
    def _periodic_cut(data_dir: Path) -> dict[str, object] | None:
        from cryodaq.periodic_state import load_periodic_state

        try:
            payload = load_periodic_state(data_dir).payload
        except (OSError, TypeError, ValueError):
            return None
        return payload if type(payload) is dict else None

    def run(self, evidence: Any, selected: Any = None) -> None:
        self.require_platform()
        from scripts import soak_mock_stack as _soak_for_default

        if selected is None:
            selected = _soak_for_default.profile("short")
        if self._used:
            raise _RunnerFoundationError("POSIX soak runner is single-use")
        from scripts import soak_mock_stack as soak

        if type(evidence) is not soak.Evidence:
            raise TypeError("evidence must be the exact Evidence type")
        self._used = True
        try:
            # Begin the restoration guard before PR_SET so a failed
            # verification or asynchronous interruption after mutation always
            # rolls back to the observed prior state.
            self._prior_subreaper = _runner_subreaper_state()
            _apply_runner_subreaper(True)
            _DELIVERY_EVIDENCE.run(self, evidence, selected)
        finally:
            if self._prior_subreaper is not None and not self._subreaper_restored:
                self._restore_subreaper()

    def _restore_subreaper(self) -> None:
        if self._subreaper_restored:
            return
        if self._prior_subreaper is None:
            raise _RunnerFoundationError("qualification subreaper prior state is unavailable")
        with _block_termination_signals():
            _apply_runner_subreaper(self._prior_subreaper)
            self._subreaper_restored = True

    def _run_owned(self, evidence: Any, selected: Any) -> _OwnedRunResult:
        """Run, validate, seal, and publish one short-soak terminal result."""

        import platform
        from datetime import UTC, datetime

        import psutil

        from scripts import soak_mock_stack as soak

        # THE PROFILE NOW ARRIVES FROM THE CALLER, and until this change it did not arrive
        # at all: `main()` computed one, used it to name the evidence directory, and then
        # called a runner that chose its own.
        #
        # THE REFUSAL STAYS, and its reason is now TRUE instead of tautological. The old
        # line compared a name against the literal it had just asked for, which cannot
        # fail. This one names the contract that actually forbids a long profile today:
        # `Evidence` rejects a manifest whose `expected_receipts` is not 2
        # (`soak_mock_stack.py`), and the qualification refuses a ledger whose length is
        # not 2 (`_validate_pre_post_receipts`). A long profile could therefore start,
        # fault processes for hours, and never seal. Admitting one before that contract
        # changes would spend a night of machine time to produce nothing.
        #
        # IT COMPARES FIELDS, AND IT HAS TO BE CLASS-AGNOSTIC. Two stricter-looking checks
        # were tried and both would have refused EVERY REAL RUN; a test that drives this
        # boundary caught them before they shipped.
        #
        # The soak starts as `python -m scripts.soak_mock_stack`, so the entry module is
        # `__main__` while this runner does `from scripts import soak_mock_stack`. Those are
        # TWO module instances. `selected is soak.PROFILES[name]` is therefore false for
        # every real run -- and so is `==`, because dataclass equality requires the same
        # class and the two instances define two `SoakProfile` classes.
        #
        # Comparing the FIELDS answers the question that actually matters: does this profile
        # carry what the reviewed profile of that name carries. A look-alike whose fields
        # differ is refused; one identical in every field is the reviewed profile in all but
        # object identity, and behaves as such.
        registered = soak.PROFILES.get(getattr(selected, "name", None))
        if registered is None or dataclasses.asdict(registered) != dataclasses.asdict(selected):
            raise _RunnerFoundationError("soak profile is not one of the reviewed profiles")
        if selected.name != "short":
            raise _RunnerFoundationError(
                "the evidence contract seals exactly two receipts, so only the short "
                f"profile can qualify; {selected.name!r} would run and never seal"
            )
        locked = _LockedPsutilObserver(psutil)
        owner_identity = locked.identity_for_pid(os.getpid())
        if locked.descendants(owner_identity, include_zombies=True):
            raise _RunnerFoundationError("qualification owner has unexpected live descendants")
        collector = _CleanShaCollector(_REPO_ROOT)
        report_interval_s, report_boundary_offset_s = _select_short_soak_report_schedule(time.time())
        sha = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=_REPO_ROOT,
            env=_controlled_git_environment(),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        with _sealed_execution_snapshot(sha) as fixture_snapshot:
            with tempfile.TemporaryDirectory(prefix="cryodaq-fixture-seal-") as fixture_temporary:
                fixture_config = Path(fixture_temporary) / "config"
                fixture_readings_per_sample = _materialize_complete_soak_config(
                    fixture_config,
                    report_interval_s=report_interval_s,
                    source_snapshot=fixture_snapshot,
                )
                source_fixture = _source_fixture_seal(
                    fixture_config,
                    expected_readings_per_sample=fixture_readings_per_sample,
                ).payload
        evidence.write_manifest(
            {
                # The profile that RAN, never a literal. The thresholds beside this line
                # already read `selected`; this one did not, so a manifest could have named
                # the short profile while another one ran. Nothing can reach that state
                # today because the entry point refuses every profile but the short one --
                # which is exactly why it must be right before that refusal is ever lifted.
                "profile": selected.name,
                "git_sha": sha,
                "dirty": False,
                "platform": platform.platform(),
                "python": sys.version,
                "source_command": list(_SOURCE_ARGV),
                "thresholds": soak.effective_thresholds(selected),
                "periodic_schedule": {
                    "interval_s": report_interval_s,
                    "selection_boundary_offset_s": report_boundary_offset_s,
                    # Two, and NOT derived. `Evidence` rejects a manifest whose count is
                    # not 2 and the qualification refuses a ledger that is not two records
                    # long, so a derived count would only describe a run that cannot seal.
                    "expected_receipts": 2,
                },
                "source_fixture": source_fixture,
                "fatal_log_allowlist": [],
                "capture_policy": "allowlisted metadata only; environment values forbidden",
            }
        )
        exact = _EXACT_SIX_EXECUTIONS.execute(evidence, collector=collector)
        evidence.write_prerequisites(
            {
                "exact_six": {
                    "command": exact["command"],
                    "git_sha": exact["git_sha"],
                    "exit_code": exact["exit_code"],
                    "status": exact["status"],
                    "result_artifact": "exact-six-result.json",
                    "result_sha256": evidence._sha256("exact-six-result.json"),
                },
                "observer": {"identity": "psutil/create_time", "version": _LOCKED_PSUTIL_VERSION, "locked": True},
                "local_publisher": {
                    "identity": "inherited-af-unix-periodic-artifact/v1",
                    "reviewed": True,
                    "transport": "local-only",
                },
                "bridge_identity": {"capability": "launcher-inherited-pipe/v1", "positive": True},
            }
        )
        collector.observe(_ShaBoundary.BEFORE_SOURCE_LAUNCH)
        evidence.begin_run()
        os.chmod(evidence.directory, 0o700)
        broad = soak.PsutilObserver(psutil)
        observations: set[Any] = set()
        receipt_cut_type = tuple[
            dict[str, object],
            dict[str, object],
            dict[str, object],
            bytes,
            _AssistantProcessObservation,
        ]
        pre_assistant_fault_cut: receipt_cut_type | None = None
        post_assistant_fault_cut: receipt_cut_type | None = None
        assistant_fault_injected = False
        process: subprocess.Popen[bytes] | None = None
        launcher_identity: _ProcessIdentity | None = None
        launcher_settled = False
        bridge_pipe: _BridgeHandshakePipe | None = None
        artifact_pair: _ArtifactCapabilityPair | None = None
        sink: _ArtifactReceiptSink | None = None
        bridge_buffer = bytearray()
        log_path: Path | None = None
        graceful = False
        shutdown_elapsed = 0.0
        source_snapshot_context = _sealed_execution_snapshot(sha)
        source_snapshot = source_snapshot_context.__enter__()
        try:
            bridge_pipe = _BridgeHandshakePipe.create()
            artifact_pair = _ArtifactCapabilityPair.create()
            sink = _ArtifactReceiptSink(
                artifact_pair.runner,
                nonce=artifact_pair.nonce,
                evidence_dir=evidence.directory,
            )
            with tempfile.TemporaryDirectory(prefix="cryodaq-source-soak-") as temporary:
                root = Path(temporary).resolve()
                root.chmod(0o700)
                config_dir = root / "config"
                data_dir = root / "data"
                data_dir.mkdir(mode=0o700)
                source_readings_per_sample = _materialize_complete_soak_config(
                    config_dir,
                    report_interval_s=report_interval_s,
                    source_snapshot=source_snapshot,
                )
                if source_readings_per_sample != fixture_readings_per_sample:
                    raise _RunnerFoundationError("passive source fixture behavior differs from its manifest")
                source_runtime_seal = _source_fixture_seal(
                    config_dir,
                    expected_readings_per_sample=source_readings_per_sample,
                )
                if source_runtime_seal.payload != source_fixture:
                    raise _RunnerFoundationError("passive source fixture differs from its manifest seal")
                log_path = root / "launcher.log"
                environment = _source_environment(
                    root,
                    source_root=source_snapshot.root,
                    bridge_grant=bridge_pipe.child_environment(),
                    artifact_grant=artifact_pair.child_environment(),
                )

                def settle_log_writer() -> None:
                    nonlocal launcher_settled
                    if process is not None and launcher_identity is not None and not launcher_settled:
                        if process.returncode is not None:
                            _settle_adopted_owner_descendants(
                                observer=locked,
                                owner=owner_identity,
                                deadline=time.monotonic() + _PROCESS_GROUP_GRACE_S,
                            )
                            launcher_settled = True
                            return
                        _force_settle_owned_session(
                            process,
                            observer=locked,
                            expected=launcher_identity,
                            owner=owner_identity,
                        )
                        launcher_settled = True

                with _launcher_log_capture(evidence, log_path, settle_writer=settle_log_writer, state_root=root) as log:
                    process, launcher_identity = _spawn_gated_source(
                        environment=environment,
                        stdout=log,
                        inherited_fds=bridge_pipe.child_pass_fds() + artifact_pair.child_pass_fds(),
                        observer=locked,
                        source_root=source_snapshot.root,
                    )
                    bridge_pipe.close_parent_write_end()
                    artifact_pair.close_launcher_end()
                    launcher = soak.ProcessIdentity(
                        process.pid,
                        int(launcher_identity.start_identity.rsplit("=", 1)[1]),
                    )
                    deadline = time.monotonic() + _SOURCE_START_TIMEOUT_S
                    handshake: _BridgeHandshakeRecord | None = None
                    bridge = None
                    bridge_guard: _BridgeEpochGuard | None = None
                    bridge_sequence = 0
                    roles: dict[str, Any] | None = None
                    while time.monotonic() < deadline and roles is None:
                        for raw in self._pipe_records(bridge_pipe, bridge_buffer):
                            if handshake is None:
                                handshake = _parse_bridge_handshake(
                                    raw,
                                    expected_nonce=bridge_pipe.nonce,
                                    expected_launcher_pid=process.pid,
                                    received_before_deadline=True,
                                )
                                bridge_observation = locked.observe_bridge(
                                    handshake.bridge_pid,
                                    expected_launcher_pid=process.pid,
                                )
                                bridge_identity = _bind_positive_bridge_identity(handshake, bridge_observation)
                                bridge_guard = _BridgeEpochGuard(bridge_identity, handshake.restart_count)
                                bridge = soak.ProcessIdentity(
                                    bridge_identity.pid,
                                    int(bridge_identity.start_identity.rsplit("=", 1)[1]),
                                )
                            else:
                                data = _parse_bridge_data(
                                    raw,
                                    expected_nonce=handshake.nonce,
                                    expected_launcher_pid=process.pid,
                                    expected_bridge_pid=handshake.bridge_pid,
                                    after_sequence=bridge_sequence,
                                )
                                bridge_sequence = data.sequence
                        if bridge is not None:
                            try:
                                roles, _tree = self._load_roles(broad, launcher, bridge)
                            except ValueError as exc:
                                # Kept, not swallowed. The refusal below used to say only
                                # that roles were missing, so the classifier's own reason --
                                # which names the process and the topology it rejected --
                                # was discarded at the one place it could have been read.
                                roles = None
                                roles_refusal = str(exc)
                        if roles is None:
                            time.sleep(0.1)
                    roles_refusal = locals().get("roles_refusal", "")
                    if roles is None or handshake is None or bridge is None or bridge_guard is None:
                        # Name WHICH of the four preconditions is missing. The bare
                        # sentence sends the next turn to read the whole startup path,
                        # and it has: the run gets further after every fix and stops here
                        # again, each time for a different reason the message did not say.
                        missing = ", ".join(
                            name
                            for name, value in (
                                ("roles", roles),
                                ("handshake", handshake),
                                ("bridge", bridge),
                                ("bridge_guard", bridge_guard),
                            )
                            if value is None
                        )
                        detail = f"; last classifier refusal: {roles_refusal}" if roles_refusal else ""
                        raise _RunnerFoundationError(
                            "source stack did not reach the exact four-role startup cut; "
                            f"still missing: {missing}{detail}"
                        )

                    _validate_short_soak_runtime_schedule(report_interval_s, time.time())

                    start = time.monotonic()
                    next_sample = 0.0
                    event_index = 0
                    epochs = {role: 0 for role in soak.ROLES}
                    current = dict(roles)
                    last_state: dict[str, object] | None = None
                    last_health = 0.0
                    while True:
                        now = time.monotonic()
                        elapsed = now - start
                        for raw in self._pipe_records(bridge_pipe, bridge_buffer):
                            data = _parse_bridge_data(
                                raw,
                                expected_nonce=handshake.nonce,
                                expected_launcher_pid=process.pid,
                                expected_bridge_pid=handshake.bridge_pid,
                                after_sequence=bridge_sequence,
                            )
                            bridge_sequence = data.sequence
                            bridge_guard.observe(
                                locked.identity_for_pid(data.bridge_pid),
                                restart_count=data.restart_count,
                            )
                        if elapsed >= next_sample or (
                            event_index < len(selected.events) and elapsed >= selected.events[event_index].at_s
                        ):
                            current, tree = self._load_roles(broad, launcher, bridge)
                            role_rows = {}
                            for role, identity in current.items():
                                observations.add(identity)
                                role_rows[role] = (epochs[role], tree[identity])
                            evidence.append(
                                "samples.jsonl",
                                soak.stack_sample(
                                    elapsed,
                                    role_rows,
                                    wall_time=datetime.now(UTC).isoformat(),
                                ),
                            )
                            next_sample = max(next_sample + soak.SAMPLE_INTERVAL_S, elapsed + 0.001)

                        state = self._periodic_cut(data_dir)
                        active = None if state is None else state["active"]
                        if type(active) is dict and active["status"] == "DELIVERING":
                            delivery_state = json.loads(json.dumps(state))
                            assistant_id = current["assistant"]
                            assistant_observation = locked.observe_assistant(
                                assistant_id.pid,
                                expected_launcher_pid=process.pid,
                            )
                            artifact = active["artifact"]
                            sink.accept_one(
                                assistant_observation=assistant_observation,
                                expected_launcher_pid=process.pid,
                                expected_assistant_generation=epochs["assistant"] + 1,
                                expected_slot_id=active["slot_id"],
                                expected_generation_id=active["generation_id"],
                                expected_owner_token=active["owner_token"],
                                expected_artifact_sha256=artifact["sha256"],
                            )
                            ledger = evidence._json_lines("periodic-receipts.jsonl")[-1]
                            photo, _metadata = evidence._read(ledger["filename"])
                            terminal_deadline = time.monotonic() + _ARTIFACT_IO_TIMEOUT_S
                            terminal_state = None
                            while time.monotonic() < terminal_deadline:
                                candidate_state = self._periodic_cut(data_dir)
                                terminal = None if candidate_state is None else candidate_state["last_terminal"]
                                if (
                                    candidate_state is not None
                                    and candidate_state["active"] is None
                                    and type(terminal) is dict
                                    and terminal["status"] == "SUCCEEDED"
                                    and terminal["slot_id"] == active["slot_id"]
                                    and terminal["generation_id"] == active["generation_id"]
                                    and terminal["destination_fingerprint"] == active["destination_fingerprint"]
                                    and terminal["artifact_sha256"] == artifact["sha256"]
                                ):
                                    terminal_state = candidate_state
                                    break
                                time.sleep(0.05)
                            if terminal_state is None:
                                raise _RunnerFoundationError("ACK did not reach durable successful periodic state")

                            health_deadline = time.monotonic() + _POST_ACK_HEALTH_TIMEOUT_S
                            last_state = None
                            while time.monotonic() < health_deadline:
                                candidate_state = self._periodic_cut(data_dir)
                                if candidate_state is not None:
                                    try:
                                        _validate_joined_receipt(
                                            ledger_record=ledger,
                                            delivery_state_payload=delivery_state,
                                            terminal_state_payload=candidate_state,
                                            artifact_bytes=photo,
                                            assistant_observation=assistant_observation,
                                            expected_launcher_pid=process.pid,
                                        )
                                    except _RunnerFoundationError:
                                        pass
                                    else:
                                        last_state = candidate_state
                                        break
                                time.sleep(0.05)
                            if last_state is None:
                                raise _RunnerFoundationError("durable terminal receipt did not reach ready health")
                            cut = (dict(ledger), delivery_state, last_state, photo, assistant_observation)
                            if not assistant_fault_injected:
                                pre_assistant_fault_cut = cut
                            elif post_assistant_fault_cut is None:
                                post_assistant_fault_cut = cut
                            last_health = float(last_state["health"]["updated_at"])

                        if event_index < len(selected.events) and elapsed >= selected.events[event_index].at_s:
                            event = selected.events[event_index]
                            if event.target == "assistant":
                                if pre_assistant_fault_cut is None:
                                    raise _RunnerFoundationError("assistant fault lacks a durable pre-fault receipt")
                                assistant_fault_injected = True
                            old = current[event.target]
                            expected = locked.identity_for_pid(old.pid)
                            locked.signal_exact(expected, signal.SIGTERM)
                            recovery_start = elapsed
                            prior_bridge_sequence = bridge_sequence
                            prior_health = last_health
                            recovery_deadline = time.monotonic() + _RECOVERY_TIMEOUT_S
                            replacement_roles = None
                            replacement_tree = None
                            while time.monotonic() < recovery_deadline:
                                for raw in self._pipe_records(bridge_pipe, bridge_buffer):
                                    data = _parse_bridge_data(
                                        raw,
                                        expected_nonce=handshake.nonce,
                                        expected_launcher_pid=process.pid,
                                        expected_bridge_pid=handshake.bridge_pid,
                                        after_sequence=bridge_sequence,
                                    )
                                    bridge_sequence = data.sequence
                                try:
                                    candidate, candidate_tree = self._load_roles(broad, launcher, bridge)
                                except ValueError:
                                    time.sleep(0.1)
                                    continue
                                if candidate[event.target] != old:
                                    if event.target == "engine" and bridge_sequence <= prior_bridge_sequence:
                                        time.sleep(0.1)
                                        continue
                                    if event.target == "assistant":
                                        health_state = self._periodic_cut(data_dir)
                                        if (
                                            health_state is None
                                            or health_state["health"]["status"] != "ready"
                                            or float(health_state["health"]["updated_at"]) <= prior_health
                                        ):
                                            time.sleep(0.1)
                                            continue
                                    replacement_roles, replacement_tree = candidate, candidate_tree
                                    break
                                time.sleep(0.1)
                            if replacement_roles is None or replacement_tree is None:
                                # Name WHICH child. The bare sentence leaves the reader to
                                # guess between three roles with three different meanings:
                                # a bridge that cannot recover is a defect, an engine that
                                # does not is a deliberate permanent HOLD, and an assistant
                                # is a third thing again. Guessing between them is exactly
                                # what a refusal should make unnecessary.
                                raise _RunnerFoundationError(
                                    f"faulted {event.target} did not recover within the reviewed ceiling"
                                )
                            epochs[event.target] += 1
                            current = replacement_roles
                            recovered_elapsed = time.monotonic() - start
                            role_rows = {
                                role: (epochs[role], replacement_tree[identity]) for role, identity in current.items()
                            }
                            evidence.append(
                                "samples.jsonl",
                                soak.stack_sample(
                                    recovered_elapsed,
                                    role_rows,
                                    wall_time=datetime.now(UTC).isoformat(),
                                ),
                            )
                            new_state = self._periodic_cut(data_dir)
                            new_health = 0.0 if new_state is None else float(new_state["health"]["updated_at"])
                            replacement = current[event.target]
                            evidence.append(
                                "faults.jsonl",
                                {
                                    "target": event.target,
                                    "scheduled_s": float(event.at_s),
                                    "observed_s": recovery_start,
                                    "pre_pid": old.pid,
                                    "pre_started_ns": old.started_ns,
                                    "recheck_pid": expected.pid,
                                    "recheck_started_ns": old.started_ns,
                                    "replacement_pid": replacement.pid,
                                    "replacement_started_ns": replacement.started_ns,
                                    "ready": True,
                                    "recovery_s": recovered_elapsed - recovery_start,
                                    "bridge_data_resumed": (
                                        event.target != "engine" or bridge_sequence > prior_bridge_sequence
                                    ),
                                    "newer_h3_health": event.target != "assistant" or new_health > prior_health,
                                    "signal": soak.FAULT_SIGNAL,
                                    "injection_method": soak.FAULT_INJECTION_METHOD,
                                },
                            )
                            event_index += 1
                            next_sample = max(next_sample, recovered_elapsed + 0.001)
                        if elapsed >= selected.duration_s:
                            break
                        time.sleep(min(0.1, max(0.001, next_sample - (time.monotonic() - start))))

                    if pre_assistant_fault_cut is None or post_assistant_fault_cut is None:
                        raise _RunnerFoundationError("short qualification lacks exact pre/post fault receipts")
                    shutdown_start = time.monotonic()
                    locked.signal_exact(launcher_identity, signal.SIGTERM)
                    return_code = _wait_and_reap_owned_session(
                        process,
                        observer=locked,
                        expected=launcher_identity,
                        owner=owner_identity,
                        timeout_s=_SHUTDOWN_TIMEOUT_S,
                    )
                    launcher_settled = True
                    shutdown_elapsed = time.monotonic() - shutdown_start
                    graceful = return_code == 0 and shutdown_elapsed <= _SHUTDOWN_TIMEOUT_S
                    if (
                        _source_fixture_seal(
                            config_dir,
                            expected_readings_per_sample=source_readings_per_sample,
                        )
                        != source_runtime_seal
                    ):
                        raise _RunnerFoundationError("passive source fixture changed during execution")
        finally:
            with _block_termination_signals():
                try:
                    if process is not None and launcher_identity is not None and not launcher_settled:
                        if process.returncode is None:
                            _force_settle_owned_session(
                                process,
                                observer=locked,
                                expected=launcher_identity,
                                owner=owner_identity,
                            )
                        else:
                            _settle_adopted_owner_descendants(
                                observer=locked,
                                owner=owner_identity,
                                deadline=time.monotonic() + _PROCESS_GROUP_GRACE_S,
                            )
                        launcher_settled = True
                    if sink is not None:
                        sink.close()
                    if artifact_pair is not None:
                        artifact_pair.close()
                    if bridge_pipe is not None:
                        bridge_pipe.close()
                finally:
                    source_snapshot_context.__exit__(*sys.exc_info())

        collector.observe(_ShaBoundary.AFTER_SOURCE_SHUTDOWN)
        survivors = soak.surviving_recorded_identities(tuple(broad.snapshot()), observations)
        assert pre_assistant_fault_cut is not None and post_assistant_fault_cut is not None
        all_ledger_records = tuple(evidence._json_lines("periodic-receipts.jsonl"))
        return _OwnedRunResult(
            pre_ledger_record=pre_assistant_fault_cut[0],
            pre_delivery_state_payload=pre_assistant_fault_cut[1],
            pre_terminal_state_payload=pre_assistant_fault_cut[2],
            pre_artifact_bytes=pre_assistant_fault_cut[3],
            pre_assistant_observation=pre_assistant_fault_cut[4],
            post_ledger_record=post_assistant_fault_cut[0],
            post_delivery_state_payload=post_assistant_fault_cut[1],
            post_terminal_state_payload=post_assistant_fault_cut[2],
            post_artifact_bytes=post_assistant_fault_cut[3],
            post_assistant_observation=post_assistant_fault_cut[4],
            expected_launcher_pid=launcher_identity.pid,
            report_interval_s=report_interval_s,
            ledger_records=all_ledger_records,
            observations=tuple(observations),
            survivors=tuple(survivors),
            graceful=graceful,
            shutdown_elapsed=shutdown_elapsed,
            collector=collector,
        )

    def _finish_owned(self, evidence: Any, result: _OwnedRunResult) -> None:
        evidence.record_shutdown(
            {
                "graceful_requested": True,
                "launcher_exited": result.graceful,
                "elapsed_s": result.shutdown_elapsed,
                "observed_identities": [
                    {"pid": item.pid, "started_ns": item.started_ns}
                    for item in sorted(result.observations, key=lambda value: (value.pid, value.started_ns))
                ],
                "survivors": [
                    {"pid": item.pid, "started_ns": item.started_ns}
                    for item in sorted(result.survivors, key=lambda value: (value.pid, value.started_ns))
                ],
            }
        )
        result.collector.observe(_ShaBoundary.BEFORE_TERMINAL_ACCEPTANCE)
        _validate_clean_sha_chain(result.collector.observations)
        self._restore_subreaper()
        evidence.seal()
        evidence.finish_pass()


__all__: tuple[str, ...] = ()
