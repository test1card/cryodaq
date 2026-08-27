from __future__ import annotations

import ast
import builtins
import contextlib
import hashlib
import importlib
import inspect
import logging
import os
import socket
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cryodaq import launcher
from cryodaq.gui.zmq_client import ZmqBridge
from scripts import soak_mock_stack_runner as runner

_POSIX_HANDSHAKE = pytest.mark.skipif(
    os.name != "posix",
    reason="requires POSIX descriptor inheritance and filesystem mode semantics",
)


def _install_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[int, int, str]:
    root = tmp_path / "isolated-root"
    root.mkdir(mode=0o700)
    os.chmod(root, 0o700)
    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, True)
    nonce = "a" * 64
    monkeypatch.setenv("CRYODAQ_ROOT", str(root))
    monkeypatch.setenv(launcher._SOAK_BRIDGE_FD_ENV, str(write_fd))
    monkeypatch.setenv(launcher._SOAK_BRIDGE_NONCE_ENV, nonce)
    return read_fd, write_fd, nonce


@_POSIX_HANDSHAKE
def test_valid_posix_mock_tray_request_emits_bounded_identity_and_data_stream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    read_fd, write_fd, nonce = _install_request(monkeypatch, tmp_path)
    assert os.get_inheritable(write_fd) is True
    authority = launcher._consume_soak_bridge_handshake(
        cli_mock=True,
        tray_only=True,
        replay_requested=False,
        setup_wizard=False,
    )
    assert authority is not None
    assert os.get_inheritable(authority.fd) is False
    assert launcher._SOAK_BRIDGE_FD_ENV not in os.environ
    assert launcher._SOAK_BRIDGE_NONCE_ENV not in os.environ
    try:
        authority.emit(bridge_pid=os.getpid() + 1000, restart_count=1)
        payload = os.read(read_fd, runner._MAX_BRIDGE_HANDSHAKE_BYTES + 1)
        record = runner._parse_bridge_handshake(
            payload,
            expected_nonce=nonce,
            expected_launcher_pid=os.getpid(),
            received_before_deadline=True,
        )
        assert record.bridge_pid == os.getpid() + 1000
        assert record.restart_count == 1
        assert authority.emit_data_observed(bridge_pid=os.getpid() + 1000, restart_count=1)
        data = os.read(read_fd, runner._MAX_BRIDGE_HANDSHAKE_BYTES + 1)
        assert (
            runner._parse_bridge_data(
                data,
                expected_nonce=nonce,
                expected_launcher_pid=os.getpid(),
                expected_bridge_pid=os.getpid() + 1000,
                after_sequence=0,
            ).sequence
            == 1
        )
        assert not authority.emit_data_observed(bridge_pid=os.getpid() + 1000, restart_count=1)
        authority.close()
        with pytest.raises(OSError):
            os.fstat(write_fd)
    finally:
        os.close(read_fd)


@pytest.mark.skipif(
    not hasattr(os, "fork") or not hasattr(os, "register_at_fork"),
    reason="requires a real POSIX fork callback",
)
def test_consumed_authority_fd_is_closed_in_real_fork_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    read_fd, _write_fd, _nonce = _install_request(monkeypatch, tmp_path)
    authority = launcher._consume_soak_bridge_handshake(
        cli_mock=True,
        tray_only=True,
        replay_requested=False,
        setup_wizard=False,
    )
    assert authority is not None
    result_read, result_write = os.pipe()
    child_pid = os.fork()
    if child_pid == 0:  # pragma: no cover - assertions run in the parent
        os.close(result_read)
        try:
            os.fstat(authority.fd)
        except OSError:
            result = b"closed"
        else:
            result = b"open"
        try:
            os.write(result_write, result)
        finally:
            os.close(result_write)
            os._exit(0)

    os.close(result_write)
    try:
        assert os.read(result_read, 16) == b"closed"
        waited_pid, status = os.waitpid(child_pid, 0)
        assert waited_pid == child_pid
        assert os.waitstatus_to_exitcode(status) == 0
        assert os.fstat(authority.fd)
    finally:
        os.close(result_read)
        authority.close()
        os.close(read_fd)


@_POSIX_HANDSHAKE
def test_consumed_authority_closes_if_noninheritability_cannot_be_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    read_fd, write_fd, _nonce = _install_request(monkeypatch, tmp_path)

    def fail_set_inheritable(fd: int, inheritable: bool) -> None:
        assert fd == write_fd
        assert inheritable is False
        raise OSError("cannot set close-on-exec")

    monkeypatch.setattr(os, "set_inheritable", fail_set_inheritable)
    try:
        with pytest.raises(OSError, match="close-on-exec"):
            launcher._consume_soak_bridge_handshake(
                cli_mock=True,
                tray_only=True,
                replay_requested=False,
                setup_wizard=False,
            )
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert os.read(read_fd, 1) == b""
    finally:
        os.close(read_fd)


@_POSIX_HANDSHAKE
def test_consumed_authority_cancel_closes_pipe_and_fork_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    read_fd, write_fd, _nonce = _install_request(monkeypatch, tmp_path)
    authority = launcher._consume_soak_bridge_handshake(
        cli_mock=True,
        tray_only=True,
        replay_requested=False,
        setup_wizard=False,
    )
    assert authority is not None
    assert write_fd in launcher._SOAK_BRIDGE_ACTIVE_FDS
    authority.close()
    try:
        assert write_fd not in launcher._SOAK_BRIDGE_ACTIVE_FDS
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert os.read(read_fd, 1) == b""
    finally:
        os.close(read_fd)


@pytest.mark.parametrize(
    "arguments",
    [
        {"cli_mock": False, "tray_only": True, "replay_requested": False, "setup_wizard": False},
        {"cli_mock": True, "tray_only": False, "replay_requested": False, "setup_wizard": False},
        {"cli_mock": True, "tray_only": True, "replay_requested": True, "setup_wizard": False},
        {"cli_mock": True, "tray_only": True, "replay_requested": False, "setup_wizard": True},
    ],
)
def test_handshake_rejects_non_exact_modes_and_closes_descriptor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    arguments: dict[str, bool],
) -> None:
    read_fd, write_fd, _nonce = _install_request(monkeypatch, tmp_path)
    try:
        with pytest.raises(RuntimeError, match="restricted"):
            launcher._consume_soak_bridge_handshake(**arguments)
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert os.read(read_fd, 1) == b""
    finally:
        os.close(read_fd)


def test_partial_cancel_and_unsafe_root_fail_closed_without_descriptor_leak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    read_fd, write_fd, _nonce = _install_request(monkeypatch, tmp_path)
    monkeypatch.delenv(launcher._SOAK_BRIDGE_NONCE_ENV)
    try:
        with pytest.raises(RuntimeError, match="partial"):
            launcher._consume_soak_bridge_handshake(
                cli_mock=True,
                tray_only=True,
                replay_requested=False,
                setup_wizard=False,
            )
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert os.read(read_fd, 1) == b""
    finally:
        os.close(read_fd)


@pytest.mark.parametrize("mode", [0o000, 0o500, 0o600, 0o701, 0o710, 0o750, 0o770, 0o777])
@_POSIX_HANDSHAKE
def test_handshake_requires_exact_root_mode_0700_and_closes_rejections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: int,
) -> None:
    read_fd, write_fd, _nonce = _install_request(monkeypatch, tmp_path)
    root = Path(os.environ["CRYODAQ_ROOT"])
    os.chmod(root, mode)
    try:
        with pytest.raises(RuntimeError, match="ownership/mode"):
            launcher._consume_soak_bridge_handshake(
                cli_mock=True,
                tray_only=True,
                replay_requested=False,
                setup_wizard=False,
            )
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert os.read(read_fd, 1) == b""
    finally:
        os.chmod(root, 0o700)
        os.close(read_fd)


@_POSIX_HANDSHAKE
def test_handshake_rejects_parent_replacement_between_observation_and_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    root = parent / "isolated-root"
    root.mkdir(mode=0o700)
    replacement_parent = tmp_path / "replacement-parent"
    replacement_parent.mkdir(mode=0o700)
    replacement_root = replacement_parent / "isolated-root"
    replacement_root.mkdir(mode=0o700)
    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, True)
    monkeypatch.setenv("CRYODAQ_ROOT", str(root))
    monkeypatch.setenv(launcher._SOAK_BRIDGE_FD_ENV, str(write_fd))
    monkeypatch.setenv(launcher._SOAK_BRIDGE_NONCE_ENV, "d" * 64)
    original_real_directory_stat = launcher._real_directory_stat
    replaced = False

    def replace_parent_after_observation(path: Path):
        nonlocal replaced
        observed = original_real_directory_stat(path)
        if path == root and not replaced:
            replaced = True
            parent.rename(tmp_path / "observed-parent")
            replacement_parent.rename(parent)
        return observed

    monkeypatch.setattr(launcher, "_real_directory_stat", replace_parent_after_observation)
    try:
        with pytest.raises(RuntimeError, match="identity changed"):
            launcher._consume_soak_bridge_handshake(
                cli_mock=True,
                tray_only=True,
                replay_requested=False,
                setup_wizard=False,
            )
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert os.read(read_fd, 1) == b""
    finally:
        os.close(read_fd)

    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, True)
    monkeypatch.setenv("CRYODAQ_ROOT", str(linked))
    monkeypatch.setenv(launcher._SOAK_BRIDGE_FD_ENV, str(write_fd))
    monkeypatch.setenv(launcher._SOAK_BRIDGE_NONCE_ENV, "b" * 64)
    try:
        with pytest.raises(RuntimeError, match="root is unsafe"):
            launcher._consume_soak_bridge_handshake(
                cli_mock=True,
                tray_only=True,
                replay_requested=False,
                setup_wizard=False,
            )
        with pytest.raises(OSError):
            os.fstat(write_fd)
    finally:
        os.close(read_fd)


def _intercepted_spawn_environment(monkeypatch, start, window) -> dict[str, str]:
    """Read the environment ONE production spawn actually hands the operating system."""

    captured: dict[str, dict[str, str]] = {}

    def _capture(*_args, **kwargs):
        captured["env"] = dict(kwargs.get("env") or {})
        raise RuntimeError("spawn intercepted after its environment was built")

    monkeypatch.setattr(launcher.subprocess, "Popen", _capture)
    with contextlib.suppress(BaseException):
        start(window)
    assert "env" in captured, "the spawn was never reached; this would prove nothing"
    return captured["env"]


def _engine_window() -> SimpleNamespace:
    """The state _start_engine touches on the way to its spawn, and nothing else.

    Every field is literal. Filling the Nones with mocks made
    `_engine_unsettled_incarnation` truthy, which is the HOLD refusal, so the spawn was
    never reached and the test proved nothing -- caught by its own guard assertion.
    """

    return SimpleNamespace(
        _engine_proc=None,
        _engine_external=False,
        _replay_source=None,
        _engine_unsettled_incarnation=None,
        _check_predictor_bootstrap_hint=MagicMock(),
        _mock=True,
    )


def _assistant_window() -> SimpleNamespace:
    return SimpleNamespace(
        _assistant_proc=None,
        _assistant_enabled=True,
        _assistant_experiment_mode=False,
        _assistant_periodic_requested=False,
        _shutdown_requested=False,
    )


def _standalone_gui_window() -> SimpleNamespace:
    """The third production spawn. It was missing, and a count could not have said so."""

    return SimpleNamespace(_mock=MagicMock())


@pytest.mark.parametrize(
    ("name", "start", "build_window"),
    [
        ("engine", launcher.LauncherWindow._start_engine, _engine_window),
        ("assistant", launcher.LauncherWindow._start_assistant, _assistant_window),
        ("standalone gui", launcher.LauncherWindow._on_open_full_gui, _standalone_gui_window),
    ],
)
def test_every_production_spawn_strips_the_launcher_only_authority(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    start,
    build_window,
) -> None:
    """Bind the assertion to the spawns themselves, not to a count of helper calls.

    The launcher-only descriptor variables grant authority over the runner's evidence
    stream. A child that inherits them can write into it. Counting builder calls could not
    see a spawn that stopped using one, so each spawn is intercepted at Popen and the
    environment on its way to the operating system is read directly.
    """

    monkeypatch.setenv(launcher._SOAK_BRIDGE_FD_ENV, "9")
    monkeypatch.setenv(launcher._SOAK_BRIDGE_NONCE_ENV, "c" * 64)
    monkeypatch.setenv(launcher._SOAK_ARTIFACT_FD_ENV, "11")
    monkeypatch.setenv(launcher._SOAK_ARTIFACT_NONCE_ENV, "d" * 64)
    monkeypatch.setenv("CRYODAQ_SPAWN_CANARY", "kept")

    child = _intercepted_spawn_environment(monkeypatch, start, build_window())

    for variable in (
        launcher._SOAK_BRIDGE_FD_ENV,
        launcher._SOAK_BRIDGE_NONCE_ENV,
        launcher._SOAK_ARTIFACT_FD_ENV,
        launcher._SOAK_ARTIFACT_NONCE_ENV,
    ):
        assert variable not in child, f"{name} child inherited {variable}"
    assert child.get("CRYODAQ_SPAWN_CANARY") == "kept", (
        f"{name} child must inherit everything that is NOT launcher-only"
    )


@_POSIX_HANDSHAKE
def test_assistant_spawn_delegates_only_its_bounded_soak_artifact_grant(monkeypatch) -> None:
    """The capability-bearing assistant path must pass only its child duplicate."""

    _read_fd, artifact_fd = os.pipe()
    capability = launcher._SoakArtifactCapability(artifact_fd, "e" * 64)
    captured: dict[str, object] = {}

    def _capture(*_args, **kwargs):
        captured["env"] = dict(kwargs["env"])
        captured["pass_fds"] = tuple(kwargs.get("pass_fds", ()))
        raise RuntimeError("spawn intercepted after the capability grant was built")

    monkeypatch.setattr(launcher.subprocess, "Popen", _capture)
    window = SimpleNamespace(
        _assistant_proc=None,
        _assistant_enabled=True,
        _assistant_experiment_mode=False,
        _assistant_periodic_requested=False,
        _shutdown_requested=False,
        _soak_artifact_capability=capability,
    )
    try:
        with contextlib.suppress(RuntimeError):
            launcher.LauncherWindow._start_assistant(window)

        assert "env" in captured, "the assistant spawn was never reached"
        child = captured["env"]
        assert isinstance(child, dict)
        delegated_fd = int(child[launcher._SOAK_ARTIFACT_FD_ENV])
        assert delegated_fd != artifact_fd, "the assistant must not receive the launcher descriptor"
        assert child[launcher._SOAK_ARTIFACT_NONCE_ENV] == "e" * 64
        assert child[launcher._SOAK_ASSISTANT_GENERATION_ENV] == "1"
        assert captured["pass_fds"] == (delegated_fd,), "only the delegated descriptor may cross exec"
    finally:
        capability.close()
        os.close(_read_fd)


def test_child_environments_always_strip_launcher_only_descriptor_authority() -> None:
    environment = {
        "SAFE": "1",
        launcher._SOAK_BRIDGE_FD_ENV: "9",
        launcher._SOAK_BRIDGE_NONCE_ENV: "c" * 64,
    }
    child = launcher._without_soak_bridge_environment(environment)
    assert child == {"SAFE": "1"}
    assert environment[launcher._SOAK_BRIDGE_FD_ENV] == "9"

    # The engine's child environment is built by a named helper now, so the property is
    # checked by RUNNING that helper rather than by counting one literal. Counting the
    # literal was a proxy, and moving the call behind a function broke the proxy while
    # leaving the property intact -- which is exactly the failure a proxy invites.
    engine_child = launcher._engine_child_environment(environment)
    assert launcher._SOAK_BRIDGE_FD_ENV not in engine_child
    assert launcher._SOAK_BRIDGE_NONCE_ENV not in engine_child
    assert engine_child["SAFE"] == "1"
    assert environment[launcher._SOAK_BRIDGE_FD_ENV] == "9"


_ALLOWED_LAUNCHER_MODULE_CHAINS = {
    "asyncio": {
        ("AbstractEventLoop",),
        ("SelectorEventLoop",),
        ("new_event_loop",),
        ("set_event_loop",),
        ("sleep",),
    },
    "ctypes": {
        ("windll", "kernel32", "CloseHandle"),
        ("windll", "kernel32", "OpenProcess"),
    },
    "os": {
        ("O_ACCMODE",),
        ("O_CREAT",),
        ("O_EXCL",),
        ("O_NONBLOCK",),
        ("O_RDWR",),
        ("O_WRONLY",),
        ("SEEK_SET",),
        ("close",),
        ("dup",),
        ("environ",),
        ("environ", "get"),
        ("environ", "pop"),
        ("fdopen",),
        ("fstat",),
        ("get_inheritable",),
        ("getpid",),
        ("getuid",),
        ("kill",),
        ("lseek",),
        ("name",),
        ("open",),
        ("path", "lexists"),
        ("path", "samestat"),
        ("pipe",),
        ("register_at_fork",),
        ("set_inheritable",),
        ("write",),
    },
    "signal": {("SIGINT",), ("SIGTERM",), ("signal",)},
    "subprocess": {
        ("DEVNULL",),
        ("PIPE",),
        ("Popen",),
        ("STARTUPINFO",),
        ("TimeoutExpired",),
    },
    "sys": {("exc_info",), ("executable",), ("exit",), ("platform",), ("stderr",)},
    "webbrowser": {("open",)},
}

_ALLOWED_SELF_GETATTRIBUTES = {
    "_annunciation_status_generation",
    "_app",
    "_assistant_periodic_requested",
    "_assistant_proc",
    "_assistant_restart_pending",
    "_assistant_shutdown_authority",
    "_assistant_shutdown_path",
    "_assistant_soak_duplicate_owner",
    "_assistant_unsettled_start_failure",
    "_bridge",
    "_child_ready_pipe_owner",
    "_child_ready_stream_owner",
    "_child_ready_write_fd_owner",
    "_engine_external",
    "_engine_instance_id",
    "_engine_proc",
    "_engine_ready",
    "_engine_ready_lock",
    "_engine_ready_nonce",
    "_engine_ready_thread",
    "_engine_shutdown_capability",
    "_engine_shutdown_receipt",
    "_engine_shutdown_request_id",
    "_engine_shutdown_transport_identity",
    "_engine_shutdown_wait_deadline",
    "_engine_shutdown_worker",
    "_engine_stderr_acquisition_owner",
    "_engine_stderr_handler",
    "_engine_stderr_logger",
    "_engine_stderr_persistence_failure",
    "_engine_stderr_stream_owner",
    "_engine_stderr_thread",
    "_engine_unsettled_incarnation",
    "_external_engine_ready_receipt",
    "_gui_worker_session_epoch",
    "_last_cmd_watchdog_restart",
    "_last_health_watchdog_restart",
    "_loop",
    "_main_window",
    "_mock_thermal_simulator",
    "_periodic_status_banner",
    "_replay_ready",
    "_replay_ready_lock",
    "_replay_ready_nonce",
    "_replay_ready_thread",
    "_replay_session_id",
    "_replay_source",
    "_replay_speed",
    "_runtime_callback_epoch",
    "_runtime_callbacks_open",
    "_safety_status_generation",
    "_shutdown_last_errors",
    "_shutdown_phase",
    "_shutdown_requested",
    "_shutdown_settled",
    "_snapshot_ingress",
    "_soak_artifact_capability",
    "_soak_bridge_handshake",
    "_theme_actions",
    "_theme_active_id",
    "_theme_pending_action",
    "_tick_async_warned",
    "_tray",
}

_ALLOWED_DYNAMIC_SELF_GETATTRIBUTES = {
    ("_settle_raw_descriptor", "state_name"),
    ("_close_engine_stderr_stream", "attribute"),
    ("_invalidate_launcher_status_authority", "name"),
    ("_launcher_status_authority_is_current", "generation_attribute"),
    ("_ensure_shutdown_state", "name"),
    ("_quiesce_for_shutdown", "name"),
    ("_settle_safety_worker", "attribute"),
}


def _launcher_process_authority_violations(source: str) -> tuple[int, list[str]]:
    """Reject process authority outside the launcher's closed structural vocabulary."""

    tree = ast.parse(source, filename="src/cryodaq/launcher.py")
    annotation_nodes: set[ast.AST] = set()
    docstring_nodes: set[ast.AST] = set()
    for candidate in ast.walk(tree):
        annotations: list[ast.expr] = []
        if isinstance(candidate, ast.arg) and candidate.annotation is not None:
            annotations.append(candidate.annotation)
        elif isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)) and candidate.returns is not None:
            annotations.append(candidate.returns)
        elif isinstance(candidate, ast.AnnAssign):
            annotations.append(candidate.annotation)
        for annotation in annotations:
            annotation_nodes.update(ast.walk(annotation))
        if (
            isinstance(candidate, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and candidate.body
            and isinstance(candidate.body[0], ast.Expr)
            and isinstance(candidate.body[0].value, ast.Constant)
            and isinstance(candidate.body[0].value.value, str)
        ):
            docstring_nodes.add(candidate.body[0].value)

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def enclosing_function(node: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        parent = parents.get(node)
        while parent is not None:
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return parent
            parent = parents.get(parent)
        return None

    def attribute_chain(node: ast.Name) -> tuple[str, ...]:
        chain: list[str] = []
        current: ast.AST = node
        parent = parents.get(current)
        while isinstance(parent, ast.Attribute) and parent.value is current:
            chain.append(parent.attr)
            current = parent
            parent = parents.get(current)
        return tuple(chain)

    def semantic_scope(node: ast.AST) -> str:
        path: list[str] = []
        current = parents.get(node)
        while current is not None:
            if isinstance(current, ast.ClassDef):
                path.append(f"class:{current.name}")
            elif isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                path.append(f"function:{current.name}:{ast.dump(current.args, include_attributes=False)}")
            current = parents.get(current)
        return "/".join(reversed(path)) or "module"

    def immediate_context(node: ast.AST) -> str:
        parent = parents.get(node)
        if parent is None:
            return "<none>"
        return ast.dump(parent, include_attributes=False)

    def call_name(node: ast.Call) -> str | None:
        return node.func.id if isinstance(node.func, ast.Name) else None

    imports = sorted(
        ast.dump(node, annotate_fields=True, include_attributes=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    )
    import_digest = hashlib.sha256("\n".join(imports).encode("utf-8")).hexdigest()
    unsafe: list[str] = []

    definition_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    def qualified_definition_name(
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    ) -> str:
        names = [node.name]
        ancestor = parents.get(node)
        while ancestor is not None:
            if isinstance(ancestor, definition_types):
                names.append(ancestor.name)
            ancestor = parents.get(ancestor)
        return ".".join(reversed(names))

    qualified_definitions = [
        qualified_definition_name(node) for node in ast.walk(tree) if isinstance(node, definition_types)
    ]
    definition_counts: dict[str, int] = {}
    for name in qualified_definitions:
        definition_counts[name] = definition_counts.get(name, 0) + 1
    duplicate_definitions = sorted(name for name, count in definition_counts.items() if count > 1)
    if duplicate_definitions:
        unsafe.append("duplicate qualified definitions: " + ", ".join(duplicate_definitions))

    spawn_definitions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_spawn_child_process"
        and isinstance(parents.get(node), ast.Module)
    ]
    if len(spawn_definitions) != 1:
        unsafe.append(f"expected one top-level _spawn_child_process definition, found {len(spawn_definitions)}")
    else:
        spawn_definition_digest = hashlib.sha256(
            ast.dump(
                spawn_definitions[0],
                annotate_fields=True,
                include_attributes=False,
            ).encode("utf-8")
        ).hexdigest()
        if spawn_definition_digest != "ecd94f462f3373b4fa816d1348ffe0c358f49f0868b69260952e46f724a95540":
            unsafe.append("the complete reviewed _spawn_child_process definition changed")

    if len(imports) != 80 or import_digest != "8069275ec1216221ff3e09ce5303af2a1fc2a0202fafb84311ede476cc94a936":
        unsafe.append("the exact reviewed import vocabulary changed")

    imported_module_aliases = {
        alias.asname or alias.name.split(".", 1)[0]
        for import_node in ast.walk(tree)
        if isinstance(import_node, ast.Import)
        for alias in import_node.names
    }
    imported_module_occurrences = sorted(
        f"{semantic_scope(node)}|{'.'.join((node.id, *attribute_chain(node)))}|{immediate_context(node)}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node not in annotation_nodes and node.id in imported_module_aliases
    )
    module_occurrence_digest = hashlib.sha256("\n".join(imported_module_occurrences).encode("utf-8")).hexdigest()
    if (
        len(imported_module_occurrences) != 302
        or module_occurrence_digest != "8332dfa630ee5071ed7e5c84fced541c3eff41c3573aeb474d37c301fcfe24d8"
    ):
        unsafe.append("the exact reviewed imported-module semantic occurrences changed")

    getattr_occurrences = sorted(
        f"{semantic_scope(node)}|{ast.dump(node, include_attributes=False)}|{immediate_context(node)}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and node not in annotation_nodes and call_name(node) == "getattr"
    )
    getattr_occurrence_digest = hashlib.sha256("\n".join(getattr_occurrences).encode("utf-8")).hexdigest()
    if (
        len(getattr_occurrences) != 188
        or getattr_occurrence_digest != "88bd519a1e2880aa9056b4ea54d0a38844dbcdaf03d8ccf8066acee64febb332"
    ):
        unsafe.append("the exact reviewed getattr semantic occurrences changed")

    forbidden_names = {
        "__builtins__",
        "__import__",
        "__loader__",
        "builtins",
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "globals",
        "importlib",
        "inspect",
        "locals",
        "object",
    }
    forbidden_attributes = {
        "__bases__",
        "__class__",
        "__dict__",
        "__getattribute__",
        "__globals__",
        "__import__",
        "__mro__",
        "__self__",
        "__subclasses__",
        "breakpoint",
        "compile",
        "eval",
        "getattr",
        "getattr_static",
        "import_module",
        "modules",
        "vars",
    }
    for node in ast.walk(tree):
        if node in annotation_nodes or node in docstring_nodes:
            continue
        if isinstance(node, ast.Name) and node.id in forbidden_names:
            parent = parents.get(node)
            runtime_object_marker = (
                node.id == "object"
                and isinstance(parent, ast.Call)
                and node in parent.args
                and isinstance(parent.func, ast.Name)
                and parent.func.id in {"Signal", "Slot"}
            )
            if not runtime_object_marker:
                unsafe.append(f"line {node.lineno}: {node.id} can recover executable authority")
        elif isinstance(node, ast.Attribute) and node.attr in forbidden_attributes:
            unsafe.append(f"line {node.lineno}: .{node.attr} reflection is forbidden")

    popen_references = 0
    webbrowser_references = 0
    ctypes_process_probe_references = 0
    for node in ast.walk(tree):
        if node in annotation_nodes:
            continue
        parent = parents.get(node)
        if isinstance(node, ast.Name) and node.id in _ALLOWED_LAUNCHER_MODULE_CHAINS:
            if (
                isinstance(parent, ast.Call)
                and node in parent.args
                and call_name(parent) == "getattr"
                and node.id == "sys"
                and len(parent.args) == 3
                and isinstance(parent.args[1], ast.Constant)
                and parent.args[1].value == "frozen"
            ):
                continue
            if (
                isinstance(parent, ast.Call)
                and node in parent.args
                and call_name(parent) == "hasattr"
                and node.id == "os"
                and len(parent.args) == 2
                and isinstance(parent.args[1], ast.Constant)
                and parent.args[1].value == "register_at_fork"
            ):
                continue
            chain = attribute_chain(node)
            if chain not in _ALLOWED_LAUNCHER_MODULE_CHAINS[node.id]:
                rendered = ".".join((node.id, *chain)) if chain else node.id
                unsafe.append(f"line {node.lineno}: {rendered} is outside the reviewed module vocabulary")
                continue
            terminal: ast.AST = node
            terminal_parent = parents.get(terminal)
            while isinstance(terminal_parent, ast.Attribute) and terminal_parent.value is terminal:
                terminal = terminal_parent
                terminal_parent = parents.get(terminal)
            scope = enclosing_function(node)
            scope_name = scope.name if scope is not None else ""
            if node.id == "webbrowser":
                webbrowser_references += 1
                if not (
                    chain == ("open",)
                    and isinstance(terminal_parent, ast.Call)
                    and terminal_parent.func is terminal
                    and scope_name == "_on_open_web"
                ):
                    unsafe.append(f"line {node.lineno}: webbrowser authority moved outside _on_open_web")
            elif node.id == "ctypes":
                ctypes_process_probe_references += 1
                if not (
                    chain
                    in {
                        ("windll", "kernel32", "CloseHandle"),
                        ("windll", "kernel32", "OpenProcess"),
                    }
                    and isinstance(terminal_parent, ast.Call)
                    and terminal_parent.func is terminal
                    and scope_name == "_is_process_alive"
                ):
                    unsafe.append(f"line {node.lineno}: ctypes authority moved outside _is_process_alive")
        elif isinstance(node, ast.Name) and node.id in {"getattr", "hasattr", "setattr", "vars"}:
            if not isinstance(parent, ast.Call) or parent.func is not node:
                unsafe.append(f"line {node.lineno}: aliased {node.id} reflection is forbidden")
        elif isinstance(node, ast.Call) and call_name(node) == "getattr":
            valid = False
            if len(node.args) in {2, 3} and not node.keywords:
                target, attribute = node.args[:2]
                scope = enclosing_function(node)
                scope_name = scope.name if scope is not None else ""
                if isinstance(target, ast.Name) and target.id == "self":
                    if isinstance(attribute, ast.Constant) and attribute.value in _ALLOWED_SELF_GETATTRIBUTES:
                        valid = True
                    elif (
                        isinstance(attribute, ast.Name)
                        and (scope_name, attribute.id) in _ALLOWED_DYNAMIC_SELF_GETATTRIBUTES
                    ):
                        valid = True
                    elif (
                        isinstance(attribute, ast.IfExp)
                        and ast.unparse(attribute) == "'_tray_icon_red' if failed else '_tray_icon_yellow'"
                    ):
                        valid = True
                elif isinstance(target, ast.Name):
                    valid = (target.id, ast.unparse(attribute)) in {
                        ("_CHILD_READY_PIPE_OWNER_CONTEXT", "'owner'"),
                        ("metadata", "'st_file_attributes'"),
                        ("snapshot_ingress", "'active'"),
                        ("stat_module", "'FILE_ATTRIBUTE_REPARSE_POINT'"),
                        ("sys", "'frozen'"),
                        ("worker", "'quit'"),
                        ("worker", "'requestInterruption'"),
                        ("worker", "'wait'"),
                    }
                elif isinstance(target, ast.Attribute):
                    valid = ast.unparse(target) == "self.stream" and ast.unparse(attribute) == "'closed'"
                elif isinstance(target, ast.Call):
                    valid = (
                        ast.unparse(target) == "getattr(self, '_engine_proc', None)"
                        and ast.unparse(attribute) == "'pid'"
                    )
            if not valid:
                unsafe.append(f"line {node.lineno}: getattr is outside the reviewed reflection vocabulary")
        elif isinstance(node, ast.Call) and call_name(node) == "vars":
            valid = (
                len(node.args) == 1
                and not node.keywords
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "self"
                and isinstance(parent, ast.Attribute)
                and parent.value is node
                and parent.attr == "get"
                and isinstance(parents.get(parent), ast.Call)
                and parents[parent].func is parent
                and parents[parent].args
                and isinstance(parents[parent].args[0], ast.Constant)
                and parents[parent].args[0].value
                in {
                    "_assistant_restart_generation",
                    "_bridge_restart_fault",
                    "_bridge_restart_hold",
                    "_bridge_watchdog_generation",
                    "_main_window",
                    "_replay_session_verified",
                    "_restart_generation",
                    "_restart_giving_up",
                }
            )
            if not valid:
                unsafe.append(f"line {node.lineno}: vars is outside the reviewed state lookup vocabulary")
        elif isinstance(node, ast.Attribute) and node.attr == "Popen":
            popen_references += 1
            scope = enclosing_function(node)
            canonical_reference = (
                isinstance(parent, ast.Call)
                and parent.func is node
                and isinstance(node.value, ast.Name)
                and node.value.id == "subprocess"
                and len(spawn_definitions) == 1
                and scope is spawn_definitions[0]
            )
            if not canonical_reference:
                unsafe.append(f"line {node.lineno}: noncanonical Popen reference bypasses the spawn boundary")
        elif isinstance(node, ast.Name) and node.id == "Popen":
            popen_references += 1
            unsafe.append(f"line {node.lineno}: bare Popen reference bypasses the spawn boundary")

    if popen_references != 1:
        unsafe.append(f"expected one Popen reference, found {popen_references}")
    if webbrowser_references != 1:
        unsafe.append(f"expected one webbrowser.open reference, found {webbrowser_references}")
    if ctypes_process_probe_references != 2:
        unsafe.append(
            "expected the exact OpenProcess/CloseHandle probe pair, "
            f"found {ctypes_process_probe_references} ctypes references"
        )
    return popen_references, unsafe


def test_every_popen_environment_originates_at_an_authority_stripping_builder() -> None:
    """The sole process-creation reference must remain at the final sanitizer."""

    source = Path("src/cryodaq/launcher.py").read_text(encoding="utf-8")
    popen_count, unsafe = _launcher_process_authority_violations(source)
    assert popen_count == 1
    assert not unsafe, "launcher process authority escaped its structural vocabulary:\n" + "\n".join(unsafe)


def test_popen_inventory_discovers_an_added_spawn() -> None:
    """Module recovery, reflection, aliases, and alternate process APIs all fail closed."""

    source = Path("src/cryodaq/launcher.py").read_text(encoding="utf-8")
    original_count, original_unsafe = _launcher_process_authority_violations(source)
    assert original_count == 1
    assert not original_unsafe
    safe_variants = {
        "deferred annotation": source
        + "\n\ndef _annotation_only(value: subprocess.Popen) -> subprocess.Popen:\n    return value\n",
        "true docstring": source
        + '\n\ndef _documentation_only():\n    """subprocess.Popen and os.spawnv are discussed, not executed."""\n',
    }
    for name, variant in safe_variants.items():
        count, variant_unsafe = _launcher_process_authority_violations(variant)
        assert count == 1, name
        assert not variant_unsafe, f"{name} was mistaken for executable authority: {variant_unsafe}"

    reviewed_spawn_body = (
        '    """Spawn one launcher child from a final sanitized environment boundary."""\n'
        "\n"
        '    if "env" in popen_kwargs:\n'
        '        raise TypeError("child process environment belongs to the launcher sanitizer")\n'
        "    child_environment = _without_soak_bridge_environment(environment)\n"
        "    if assistant_artifact_grant is not None:\n"
        "        grant_snapshot = dict(assistant_artifact_grant)\n"
        "        expected_grant_keys = {\n"
        "            _SOAK_ARTIFACT_FD_ENV,\n"
        "            _SOAK_ARTIFACT_NONCE_ENV,\n"
        "            _SOAK_ASSISTANT_GENERATION_ENV,\n"
        "        }\n"
        "        if set(grant_snapshot) != expected_grant_keys or not all(\n"
        "            isinstance(value, str) for value in grant_snapshot.values()\n"
        "        ):\n"
        '            raise ValueError("assistant artifact grant must contain the exact string capability triplet")\n'
        "        child_environment.update(grant_snapshot)\n"
        "    return subprocess.Popen(command, env=child_environment, **popen_kwargs)\n"
    )
    unsafe_spawn_body = (
        '    """Duplicate the reviewed identity while bypassing descriptor sanitization."""\n'
        "\n"
        "    return subprocess.Popen(command, env=environment, **popen_kwargs)\n"
    )
    assert source.count(reviewed_spawn_body) == 1
    same_identity_spawn_substitution = source.replace(reviewed_spawn_body, unsafe_spawn_body, 1)

    mutants = {
        "direct subprocess alias": source + "\n\ndef _escape():\n    spawn = subprocess.Popen\n    spawn(['probe'])\n",
        "computed importlib recovery": source
        + (
            "\n\ndef _escape():\n"
            "    import importlib\n"
            "    module = importlib.import_module('sub' + 'process')\n"
            "    getattr(module, 'Po' + 'pen')(['probe'])\n"
        ),
        "sys.modules object reflection": source
        + (
            "\n\ndef _escape():\n"
            "    module = sys.modules['sub' + 'process']\n"
            "    object.__getattribute__(module, 'Po' + 'pen')(['probe'])\n"
        ),
        "sys.modules inspect reflection": source
        + (
            "\n\ndef _escape():\n"
            "    import inspect\n"
            "    module = sys.modules['sub' + 'process']\n"
            "    inspect.getattr_static(module, 'Po' + 'pen')(['probe'])\n"
        ),
        "globals namespace dict": source
        + "\n\ndef _escape():\n    globals()['sub' + 'process'].__dict__['Po' + 'pen'](['probe'])\n",
        "globals vars namespace": source
        + "\n\ndef _escape():\n    vars(globals()['sub' + 'process'])['Po' + 'pen'](['probe'])\n",
        "implicit builtins recovery": source
        + (
            "\n\ndef _escape():\n"
            "    built = globals()['__builtins__']\n"
            "    load = built['__im' + 'port__']\n"
            "    reflect = built['get' + 'attr']\n"
            "    reflect(load('sub' + 'process'), 'Po' + 'pen')(['probe'])\n"
        ),
        "implicit eval recovery": source
        + (
            "\n\ndef _escape():\n"
            "    built = globals()['__builtins__']\n"
            "    evaluate = built['ev' + 'al']\n"
            "    evaluate('sub' + 'process.Po' + 'pen')(['probe'])\n"
        ),
        "function globals recovery": source
        + (
            "\n\ndef _escape():\n"
            "    module = _spawn_child_process.__globals__['sub' + 'process']\n"
            "    module.Popen(['probe'])\n"
        ),
        "os spawn": source + "\n\ndef _escape():\n    os.spawnv(os.P_NOWAIT, '/probe', ['/probe'])\n",
        "os posix spawn": source + "\n\ndef _escape():\n    os.posix_spawn('/probe', ['/probe'], {})\n",
        "os system": source + "\n\ndef _escape():\n    os.system('/probe')\n",
        "logging os system alias": source + "\n\ndef _escape():\n    logging.os.system('/probe')\n",
        "threading os system alias": source + "\n\ndef _escape():\n    threading._os.system('/probe')\n",
        "assigned imported-module provenance": source
        + ("\n\ndef _escape():\n    peculiar = socket\n    peculiar.os.system('/probe')\n"),
        "dynamic getattr semantic binding": source
        + ("\n\ndef _settle_raw_descriptor(self, state_name):\n    getattr(self, state_name).system('/probe')\n"),
        "dynamic getattr function-name spoof": source
        + (
            "\n\ndef _settle_raw_descriptor(self, state_name):\n"
            "    getattr(self, state_name).system('/probe')\n"
            "_settle_raw_descriptor(socket, 'os')\n"
        ),
        "same-identity spawn body substitution": same_identity_spawn_substitution,
        "duplicate qualified spawn definition": source
        + (
            "\n\ndef _spawn_child_process(\n"
            "    command: list[str],\n"
            "    *,\n"
            "    environment: Mapping[str, str],\n"
            "    assistant_artifact_grant: Mapping[str, str] | None = None,\n"
            "    **popen_kwargs: Any,\n"
            ") -> subprocess.Popen[Any]:\n"
            "    return subprocess.Popen(command, env=environment, **popen_kwargs)\n"
        ),
        "built-in breakpoint dispatch": source + "\n\ndef _second_spawn(command):\n    return breakpoint(command)\n",
        "nested built-in owner reflection": source
        + (
            "\n\ndef _outer(environment):\n"
            "    def _nested(command):\n"
            "        load = print.__self__.__import__\n"
            "        reflect = print.__self__.getattr\n"
            "        return reflect(load('sub' + 'process'), 'Po' + 'pen')(command, env=environment)\n"
            "    return _nested\n"
        ),
        "default-argument built-in owner reflection": source
        + (
            "\n\ndef _escape(\n"
            "    command,\n"
            "    environment,\n"
            "    load=print.__self__.__import__,\n"
            "    reflect=print.__self__.getattr,\n"
            "):\n"
            "    return reflect(load('sub' + 'process'), 'Po' + 'pen')(command, env=environment)\n"
        ),
        "lambda built-in owner reflection": source
        + (
            "\n\n_escape = lambda command, environment: print.__self__.getattr(\n"
            "    print.__self__.__import__('sub' + 'process'), 'Po' + 'pen'\n"
            ")(command, env=environment)\n"
        ),
        "definition-time decorator dispatch": source + "\n\n@print.__self__.breakpoint\ndef _escape():\n    pass\n",
        "asyncio process": source + "\n\nasync def _escape():\n    await asyncio.create_subprocess_exec('/probe')\n",
        "ctypes process": source
        + (
            "\n\ndef _escape():\n"
            "    ctypes.windll.kernel32.CreateProcessW(\n"
            "        None, None, None, None, 0, 0, None, None, None, None\n"
            "    )\n"
        ),
        "from-imported os spawn": source + "\n\nfrom os import spawnv as launch\n",
    }
    for name, mutant in mutants.items():
        _count, mutant_unsafe = _launcher_process_authority_violations(mutant)
        assert mutant_unsafe, f"{name} escaped the process-authority inventory"
        if name == "same-identity spawn body substitution":
            assert _count == 1
            assert mutant_unsafe == ["the complete reviewed _spawn_child_process definition changed"]
        elif name == "duplicate qualified spawn definition":
            assert any("duplicate qualified definitions" in finding for finding in mutant_unsafe)
        elif name == "built-in breakpoint dispatch":
            assert len(mutant_unsafe) == 1
            assert "breakpoint can recover executable authority" in mutant_unsafe[0]
        elif name in {
            "nested built-in owner reflection",
            "default-argument built-in owner reflection",
            "lambda built-in owner reflection",
            "definition-time decorator dispatch",
        }:
            assert any(".__self__ reflection is forbidden" in finding for finding in mutant_unsafe), name

    independent_owner_attribute_mutants = {
        "nested owner import recovery": (
            source
            + ("\n\ndef _outer(owner):\n    def _nested():\n        return owner.__import__\n    return _nested\n"),
            "__import__",
        ),
        "default-argument owner getattr recovery": (
            source + "\n\ndef _escape(owner, reflect=owner.getattr):\n    return reflect\n",
            "getattr",
        ),
        "lambda owner vars recovery": (
            source + "\n\n_escape = lambda owner: owner.vars\n",
            "vars",
        ),
        "decorator owner eval recovery": (
            source + "\n\n@owner.eval\ndef _escape():\n    pass\n",
            "eval",
        ),
        "nested owner compile recovery": (
            source + ("\n\ndef _outer(owner):\n    def _nested():\n        return owner.compile\n    return _nested\n"),
            "compile",
        ),
        "default-argument owner breakpoint recovery": (
            source + "\n\ndef _escape(owner, dispatch=owner.breakpoint):\n    return dispatch\n",
            "breakpoint",
        ),
    }
    for name, (mutant, forbidden_attribute) in independent_owner_attribute_mutants.items():
        _count, mutant_unsafe = _launcher_process_authority_violations(mutant)
        tree = ast.parse(mutant)
        independent_occurrences = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr == forbidden_attribute
            and isinstance(node.value, ast.Name)
            and node.value.id == "owner"
        ]
        assert len(independent_occurrences) == 1, name
        expected_finding = f"line {independent_occurrences[0].lineno}: .{forbidden_attribute} reflection is forbidden"
        assert mutant_unsafe == [expected_finding], (name, mutant_unsafe)


def test_process_authority_mutants_reach_a_fake_sink_before_the_inventory_rejects_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each named reflection escape really reaches process creation when not rejected."""

    calls: list[list[str]] = []
    observed_environments: list[dict[str, str]] = []

    def sink(command: list[str], *_args, **kwargs) -> None:
        calls.append(command)
        if "env" in kwargs:
            observed_environments.append(dict(kwargs["env"]))

    fake_subprocess = SimpleNamespace(Popen=sink)
    monkeypatch.setitem(sys.modules, "subprocess", fake_subprocess)
    monkeypatch.setitem(globals(), "subprocess", fake_subprocess)
    recovered_builtins = globals()["__builtins__"]
    if isinstance(recovered_builtins, dict):
        reflected_import = recovered_builtins["__import__"]
        reflected_getattr = recovered_builtins["getattr"]
        reflected_eval = recovered_builtins["eval"]
    else:
        reflected_import = builtins.getattr(recovered_builtins, "__import__")
        reflected_getattr = builtins.getattr(recovered_builtins, "getattr")
        reflected_eval = builtins.getattr(recovered_builtins, "eval")

    attacks = {
        "importlib computed recovery": lambda: getattr(importlib.import_module("sub" + "process"), "Po" + "pen")(
            ["probe"]
        ),
        "sys.modules object reflection": lambda: object.__getattribute__(sys.modules["sub" + "process"], "Po" + "pen")(
            ["probe"]
        ),
        "sys.modules inspect reflection": lambda: inspect.getattr_static(sys.modules["sub" + "process"], "Po" + "pen")(
            ["probe"]
        ),
        "globals namespace dict": lambda: globals()["sub" + "process"].__dict__["Po" + "pen"](["probe"]),
        "globals vars namespace": lambda: vars(globals()["sub" + "process"])["Po" + "pen"](["probe"]),
        "implicit builtins import/getattr": lambda: reflected_getattr(
            reflected_import("sub" + "process"), "Po" + "pen"
        )(["probe"]),
        "implicit builtins eval": lambda: reflected_eval("sub" + "process.Po" + "pen", globals(), locals())(["probe"]),
    }
    for name, attack in attacks.items():
        calls.clear()
        observed_environments.clear()
        attack()
        assert calls == [["probe"]], f"{name} did not reach the fake process-creation sink"

    owner_environment = {
        "SAFE": "kept",
        launcher._SOAK_BRIDGE_FD_ENV: "43",
    }

    def nested_owner_attack() -> None:
        def nested(command: list[str]) -> None:
            load = print.__self__.__import__
            reflect = print.__self__.getattr
            reflect(load("sub" + "process"), "Po" + "pen")(command, env=owner_environment)

        nested(["probe"])

    def default_owner_attack(
        command: list[str],
        load=print.__self__.__import__,
        reflect=print.__self__.getattr,
    ) -> None:
        reflect(load("sub" + "process"), "Po" + "pen")(command, env=owner_environment)

    owner_attacks = {
        "nested built-in owner reflection": nested_owner_attack,
        "default-argument built-in owner reflection": lambda: default_owner_attack(["probe"]),
        "lambda built-in owner reflection": lambda: print.__self__.getattr(
            print.__self__.__import__("sub" + "process"), "Po" + "pen"
        )(["probe"], env=owner_environment),
    }
    for name, attack in owner_attacks.items():
        calls.clear()
        observed_environments.clear()
        attack()
        assert calls == [["probe"]], f"{name} did not reach the fake process-creation sink"
        assert observed_environments == [owner_environment], f"{name} did not preserve the unsafe environment"

    system_calls: list[str] = []

    def system_sink(command: str) -> int:
        system_calls.append(command)
        return 0

    monkeypatch.setattr(os, "system", system_sink)

    def assigned_module_attack() -> int:
        peculiar = socket
        return peculiar.os.system("/probe")

    def dynamic_getattr_spoof_attack() -> int:
        def _settle_raw_descriptor(self, state_name):
            return getattr(self, state_name).system("/probe")

        return _settle_raw_descriptor(socket, "os")

    namespace_alias_attacks = {
        "logging.os.system": lambda: logging.os.system("/probe"),
        "threading._os.system": lambda: threading._os.system("/probe"),
        "assigned socket module": assigned_module_attack,
        "spoofed dynamic getattr allowance": dynamic_getattr_spoof_attack,
    }
    for name, attack in namespace_alias_attacks.items():
        system_calls.clear()
        assert attack() == 0
        assert system_calls == ["/probe"], f"{name} did not reach the fake process-creation sink"

    descriptor_observations: list[dict[str, str]] = []

    def process_sink(_command, *_args, **kwargs):
        descriptor_observations.append(dict(kwargs["env"]))
        return SimpleNamespace(pid=1)

    monkeypatch.setattr(launcher.subprocess, "Popen", process_sink)
    ambient = {
        "SAFE": "kept",
        launcher._SOAK_BRIDGE_FD_ENV: "41",
        launcher._SOAK_BRIDGE_NONCE_ENV: "f" * 64,
    }
    reviewed_spawn_boundary = launcher._spawn_child_process

    def _spawn_child_process(
        command: list[str],
        *,
        environment: Mapping[str, str],
        assistant_artifact_grant: Mapping[str, str] | None = None,
        **popen_kwargs,
    ) -> object:
        del assistant_artifact_grant
        return launcher.subprocess.Popen(command, env=environment, **popen_kwargs)

    _EscapedSpawnBoundary = _spawn_child_process
    _spawn_child_process = reviewed_spawn_boundary

    def _second_spawn(command: list[str]) -> object:
        return _EscapedSpawnBoundary(command, environment=ambient)

    _spawn_child_process(["reviewed"], environment=ambient)
    _second_spawn(["escaped"])
    assert launcher._SOAK_BRIDGE_FD_ENV not in descriptor_observations[0]
    assert descriptor_observations[0]["SAFE"] == "kept"
    assert descriptor_observations[1][launcher._SOAK_BRIDGE_FD_ENV] == "41"
    assert descriptor_observations[1][launcher._SOAK_BRIDGE_NONCE_ENV] == "f" * 64

    original_breakpoint_hook = sys.breakpointhook
    breakpoint_calls: list[tuple[object, ...]] = []

    def breakpoint_sink(*arguments: object, **_keywords: object) -> str:
        breakpoint_calls.append(arguments)
        return "hook-reached"

    try:
        sys.breakpointhook = breakpoint_sink
        assert builtins.breakpoint(["probe"]) == "hook-reached"

        @print.__self__.breakpoint
        def decorated_escape() -> None:
            pass

        assert decorated_escape == "hook-reached"
    finally:
        sys.breakpointhook = original_breakpoint_hook
    assert breakpoint_calls[0] == (["probe"],)
    assert len(breakpoint_calls) == 2
    assert len(breakpoint_calls[1]) == 1
    assert callable(breakpoint_calls[1][0])
    assert sys.breakpointhook is original_breakpoint_hook


def test_popen_inventory_rejects_descriptor_reintroduction_after_sanitization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real spawn boundary strips ambient authority after every caller mutation."""

    ambient = {
        "SAFE": "kept",
        launcher._SOAK_BRIDGE_FD_ENV: "9",
        launcher._SOAK_BRIDGE_NONCE_ENV: "b" * 64,
        launcher._SOAK_ARTIFACT_FD_ENV: "11",
        launcher._SOAK_ARTIFACT_NONCE_ENV: "a" * 64,
        launcher._SOAK_ASSISTANT_GENERATION_ENV: "7",
    }

    def ambient_alias() -> dict[str, str]:
        env = launcher._without_soak_bridge_environment(ambient)
        restored = ambient
        env.update(restored)
        return env

    def environment_alias() -> dict[str, str]:
        env = launcher._without_soak_bridge_environment(ambient)
        alias = env
        alias.update(ambient)
        return env

    def bound_update() -> dict[str, str]:
        env = launcher._without_soak_bridge_environment(ambient)
        restore = env.update
        restore(ambient)
        return env

    def builtin_update() -> dict[str, str]:
        env = launcher._without_soak_bridge_environment(ambient)
        dict.update(env, ambient)
        return env

    def keyword_update() -> dict[str, str]:
        env = launcher._without_soak_bridge_environment(ambient)
        env.update(**ambient)
        return env

    def in_place_union() -> dict[str, str]:
        env = launcher._without_soak_bridge_environment(ambient)
        env.__ior__(ambient)
        return env

    def conditional_assignment() -> dict[str, str]:
        env = dict(ambient)
        if len(ambient) < 0:
            env = launcher._without_soak_bridge_environment(ambient)
        return env

    def loop_assignment() -> dict[str, str]:
        env = dict(ambient)
        for _unused in range(0):
            env = launcher._without_soak_bridge_environment(ambient)
        return env

    def try_assignment() -> dict[str, str]:
        env = dict(ambient)
        try:
            raise RuntimeError("take the unsanitized branch")
        except RuntimeError:
            pass
        else:
            env = launcher._without_soak_bridge_environment(ambient)
        return env

    captured: list[dict[str, str]] = []

    def capture(*_args, **kwargs):
        captured.append(dict(kwargs["env"]))
        return SimpleNamespace(pid=1)

    monkeypatch.setattr(launcher.subprocess, "Popen", capture)
    builders = {
        "ambient alias": ambient_alias,
        "environment alias": environment_alias,
        "bound update": bound_update,
        "dict.update": builtin_update,
        "keyword update": keyword_update,
        "__ior__": in_place_union,
        "conditional assignment": conditional_assignment,
        "loop assignment": loop_assignment,
        "try assignment": try_assignment,
    }
    protected = {
        launcher._SOAK_BRIDGE_FD_ENV,
        launcher._SOAK_BRIDGE_NONCE_ENV,
        launcher._SOAK_ARTIFACT_FD_ENV,
        launcher._SOAK_ARTIFACT_NONCE_ENV,
        launcher._SOAK_ASSISTANT_GENERATION_ENV,
    }
    for name, build_environment in builders.items():
        captured.clear()
        launcher._spawn_child_process(["probe"], environment=build_environment())
        assert captured, f"{name} never reached the operating-system spawn boundary"
        assert not protected.intersection(captured[0]), f"{name} restored launcher authority"
        assert captured[0]["SAFE"] == "kept"

    exact_grant = {
        launcher._SOAK_ARTIFACT_FD_ENV: "17",
        launcher._SOAK_ARTIFACT_NONCE_ENV: "c" * 64,
        launcher._SOAK_ASSISTANT_GENERATION_ENV: "8",
    }
    captured.clear()
    launcher._spawn_child_process(
        ["probe"],
        environment=ambient,
        assistant_artifact_grant=exact_grant,
    )
    assert captured[0] == {"SAFE": "kept", **exact_grant}

    class ShiftingGrant(Mapping[str, str]):
        """Expose the valid grant once, then forbidden authority on later traversals."""

        def __init__(self) -> None:
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            if self.iterations == 1:
                return iter(exact_grant)
            return iter({launcher._SOAK_BRIDGE_FD_ENV: "19"})

        def __len__(self) -> int:
            return len(exact_grant)

        def __getitem__(self, key: str) -> str:
            if key in exact_grant:
                return exact_grant[key]
            if key == launcher._SOAK_BRIDGE_FD_ENV:
                return "19"
            raise KeyError(key)

    captured.clear()
    shifting_grant = ShiftingGrant()
    launcher._spawn_child_process(
        ["probe"],
        environment=ambient,
        assistant_artifact_grant=shifting_grant,
    )
    assert captured[0] == {"SAFE": "kept", **exact_grant}
    assert shifting_grant.iterations == 1, "the capability mapping was traversed more than once"

    captured.clear()
    with pytest.raises(ValueError, match="exact string capability triplet"):
        launcher._spawn_child_process(
            ["probe"],
            environment=ambient,
            assistant_artifact_grant={**exact_grant, launcher._SOAK_BRIDGE_FD_ENV: "19"},
        )
    assert not captured, "an over-broad assistant grant reached Popen"


def test_bridge_pid_accessor_is_read_only_hint_and_never_a_process_handle() -> None:
    bridge = ZmqBridge()
    process = MagicMock()
    process.pid = 1234
    process.is_alive.return_value = True
    ordinary_consumer = MagicMock()
    ordinary_consumer.is_alive.return_value = True
    safe_consumer = MagicMock()
    safe_consumer.is_alive.return_value = True
    try:
        assert bridge.process_pid() is None
        bridge._process = process
        assert bridge.process_pid() is None

        bridge._process_started = True
        bridge._reply_consumer = ordinary_consumer
        bridge._safe_reply_consumer = safe_consumer
        bridge._reply_consumer_started = True
        bridge._safe_reply_consumer_started = True
        with bridge._pending_lock:
            bridge._command_admission_open = True
        assert bridge.process_pid() == 1234

        with bridge._pending_lock:
            bridge._command_admission_open = False
        assert bridge.process_pid() is None
        with bridge._pending_lock:
            bridge._command_admission_open = True
        bridge._reply_stop.set()
        assert bridge.process_pid() is None
        bridge._reply_stop.clear()

        process.is_alive.return_value = False
        assert bridge.process_pid() is None
        process.is_alive.return_value = True
        ordinary_consumer.is_alive.return_value = False
        assert bridge.process_pid() is None
        ordinary_consumer.is_alive.return_value = True

        bridge._record_generation_fatal(
            reply_queue=bridge._reply_queue,
            lane="ordinary",
            source_generation=bridge._generation,
            error=RuntimeError("synthetic terminal transport failure"),
        )
        assert bridge.process_pid() is None
    finally:
        bridge._process = None
        bridge._process_started = False
        bridge._reply_consumer = None
        bridge._safe_reply_consumer = None
        bridge._reply_consumer_started = False
        bridge._safe_reply_consumer_started = False
        bridge.close()
    assert bridge.process_pid() is None


def test_handshake_close_poison_refuses_retry_and_leaves_reused_descriptor_untouched(monkeypatch) -> None:
    read_fd, write_fd = os.pipe()
    replacement_read_fd, replacement_write_fd = os.pipe()
    launcher._guard_soak_bridge_fd_from_descendants(write_fd)
    owner = launcher._SoakBridgeHandshake(write_fd, "e" * 64)
    real_close = launcher.os.close
    close_attempts = 0

    def close_then_reuse(fd: int) -> None:
        nonlocal close_attempts
        if fd == write_fd and close_attempts == 0:
            close_attempts += 1
            real_close(write_fd)
            os.dup2(replacement_write_fd, write_fd)
            raise OSError("injected ambiguous close after descriptor reuse")
        real_close(fd)

    monkeypatch.setattr(launcher.os, "close", close_then_reuse)
    try:
        with pytest.raises(RuntimeError, match="permanently poisoned"):
            owner.close()
        assert owner._closed is False
        assert owner._fd_owner.settlement_state is launcher._OwnerSettlementState.POISONED
        assert write_fd in launcher._SOAK_BRIDGE_ACTIVE_FDS

        with pytest.raises(RuntimeError, match="unsafe retry refused"):
            owner.close()
        assert close_attempts == 1

        os.write(write_fd, b"b")
        assert os.read(replacement_read_fd, 1) == b"b"
    finally:
        monkeypatch.setattr(launcher.os, "close", real_close)
        launcher._SOAK_BRIDGE_ACTIVE_FDS.discard(write_fd)
        for fd in {read_fd, write_fd, replacement_read_fd, replacement_write_fd}:
            try:
                real_close(fd)
            except OSError:
                pass
