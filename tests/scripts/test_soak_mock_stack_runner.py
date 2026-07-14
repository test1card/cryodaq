from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from scripts import soak_mock_stack as soak
from scripts import soak_mock_stack_runner as runner

_POSIX_EVIDENCE = pytest.mark.skipif(runner.os.name != "posix", reason="Evidence capability is POSIX-only")


def _evidence(payload: bytes, *, complete: bool = True) -> runner._StreamEvidence:
    return runner._StreamEvidence(
        len(payload),
        f"sha256:{hashlib.sha256(payload).hexdigest()}",
        complete,
    )


def _collection() -> bytes:
    return ("\n".join((*runner._EXACT_NODE_IDS, "6 tests collected in 0.12s")) + "\n").encode()


def _completed(payload: bytes, *, stderr: bytes = b"", exit_code: int = 0) -> runner._CompletedCommand:
    return runner._CompletedCommand(_evidence(payload), payload, _evidence(stderr), stderr, exit_code)


def _manifest(git_sha: str = "a" * 40) -> dict[str, object]:
    selected = soak.profile("short")
    return {
        "profile": "short",
        "git_sha": git_sha,
        "dirty": False,
        "platform": "test-posix",
        "python": "test-python",
        "source_command": ["python", "-m", "cryodaq.launcher", "--mock", "--tray"],
        "thresholds": soak.effective_thresholds(selected),
        "fatal_log_allowlist": [],
        "capture_policy": "allowlisted-test-schema/v1",
    }


class _Observer:
    def identity_for_pid(self, pid: int) -> runner._ProcessIdentity:
        return runner._ProcessIdentity(pid, "test:start=1")


def _install_execution_fakes(monkeypatch: pytest.MonkeyPatch, collector: type[object]) -> None:
    monkeypatch.setattr(runner, "_require_posix_exact_six", lambda: None)
    monkeypatch.setattr(runner, "_LockedPsutilObserver", lambda _module: _Observer())
    monkeypatch.setattr(runner, "_CleanShaCollector", collector)

    class Snapshot:
        def assert_sealed(self) -> None:
            return None

    @contextmanager
    def sealed(git_sha: str):
        assert git_sha == "a" * 40
        yield Snapshot()

    monkeypatch.setattr(runner, "_sealed_execution_snapshot", sealed)


@contextmanager
def _head_snapshot():
    git_sha = runner.subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=runner._REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with runner._sealed_execution_snapshot(git_sha) as snapshot:
        yield snapshot


def test_fixed_commands_and_exact_ordered_six_are_not_caller_selected() -> None:
    assert runner._COLLECTION_ARGV == (
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
        "tests/integration/test_periodic_png_multiprocess.py",
    )
    assert runner._EXECUTION_ARGV == (
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
        "tests/integration/test_periodic_png_multiprocess.py",
    )
    assert len(runner._EXACT_NODE_IDS) == len(set(runner._EXACT_NODE_IDS)) == 6
    assert (
        runner._parse_exact_collection(
            stdout_evidence=_evidence(_collection()),
            stdout=_collection(),
            stderr_evidence=_evidence(b""),
            stderr=b"",
            exit_code=0,
        )
        == runner._EXACT_NODE_IDS
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda lines: lines[::-1],
        lambda lines: lines[:-1],
        lambda lines: (*lines, lines[-1]),
        lambda lines: (*lines, "tests/other.py::test_extra"),
    ],
)
def test_collection_mismatch_never_creates_exact_six(mutate) -> None:
    nodes = tuple(mutate(runner._EXACT_NODE_IDS))
    payload = ("\n".join((*nodes, "6 tests collected in 0.1s")) + "\n").encode()
    with pytest.raises(runner._RunnerFoundationError):
        runner._parse_exact_collection(
            stdout_evidence=_evidence(payload),
            stdout=payload,
            stderr_evidence=_evidence(b""),
            stderr=b"",
            exit_code=0,
        )


@pytest.mark.parametrize(
    ("payload", "exit_code"),
    [
        (b"...... [100%]\n6 passed in 1.20s\n", 1),
        (b".....s\n5 passed, 1 skipped in 1.20s\n", 0),
        (b"......\n6 passed, 1 deselected in 1.20s\n", 0),
        (b"......\n6 passed in 1.20s\nextra\n", 0),
    ],
)
def test_execution_requires_complete_exact_six_result(payload: bytes, exit_code: int) -> None:
    with pytest.raises(runner._RunnerFoundationError):
        runner._validate_exact_execution(
            stdout_evidence=_evidence(payload),
            stdout=payload,
            stderr_evidence=_evidence(b""),
            stderr=b"",
            exit_code=exit_code,
        )


def test_exact_execution_parser_accepts_only_complete_bound_bytes() -> None:
    payload = b"...... [100%]\n6 passed in 1.20s\n"
    runner._validate_exact_execution(
        stdout_evidence=_evidence(payload),
        stdout=payload,
        stderr_evidence=_evidence(b""),
        stderr=b"",
        exit_code=0,
    )
    with pytest.raises(runner._RunnerFoundationError, match="complete"):
        runner._validate_exact_execution(
            stdout_evidence=_evidence(payload, complete=False),
            stdout=payload,
            stderr_evidence=_evidence(b""),
            stderr=b"",
            exit_code=0,
        )

    with pytest.raises(runner._RunnerFoundationError, match="stderr"):
        runner._validate_exact_execution(
            stdout_evidence=_evidence(payload),
            stdout=payload,
            stderr_evidence=_evidence(b"warning\n"),
            stderr=b"warning\n",
            exit_code=0,
        )


def test_bounded_stream_digest_hashes_incrementally_and_overflow_is_terminal() -> None:
    digest = runner._BoundedStreamDigest(limit=5)
    digest.feed(b"ab")
    digest.feed(b"cde")
    evidence = digest.finalize()
    assert evidence.byte_count == 5
    assert evidence.sha256 == f"sha256:{hashlib.sha256(b'abcde').hexdigest()}"
    assert evidence.output_complete is True
    with pytest.raises(runner._RunnerFoundationError, match="finalized"):
        digest.feed(b"x")

    overflow = runner._BoundedStreamDigest(limit=4)
    with pytest.raises(runner._RunnerFoundationError, match="exceeded"):
        overflow.feed(b"abcde")
    assert overflow.finalize().output_complete is False


def test_worktree_proof_requires_exact_venv_and_import_tree(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    exact_python = root / ".venv/bin/python"
    imported = root / "src/cryodaq/__init__.py"
    proof = runner._WorktreeImportProof(root, exact_python, "sha256:" + "a" * 64, imported)
    assert proof.interpreter == exact_python.resolve()
    with pytest.raises(runner._RunnerFoundationError, match="exact worktree"):
        runner._WorktreeImportProof(root, root / "python", "sha256:" + "a" * 64, imported)
    with pytest.raises(runner._RunnerFoundationError, match="inside"):
        runner._WorktreeImportProof(root, exact_python, "sha256:" + "a" * 64, tmp_path / "other.py")


def test_clean_sha_chain_is_full_ordered_same_sha_and_fail_closed() -> None:
    sha = "a" * 40
    observations = tuple(runner._CleanShaObservation(boundary, sha, True) for boundary in runner._ShaBoundary)
    assert runner._validate_clean_sha_chain(observations) == sha
    with pytest.raises(runner._RunnerFoundationError, match="out of order"):
        runner._validate_clean_sha_chain(observations[::-1])
    dirty = (*observations[:-1], runner._CleanShaObservation(observations[-1].boundary, sha, False))
    with pytest.raises(runner._RunnerFoundationError, match="drift"):
        runner._validate_clean_sha_chain(dirty)
    changed = (*observations[:-1], runner._CleanShaObservation(observations[-1].boundary, "b" * 40, True))
    with pytest.raises(runner._RunnerFoundationError, match="changed"):
        runner._validate_clean_sha_chain(changed)


def test_exact_six_sha_chain_is_three_ordered_same_sha() -> None:
    sha = "a" * 40
    boundaries = (
        runner._ShaBoundary.BEFORE_COLLECTION,
        runner._ShaBoundary.BETWEEN_COLLECTION_AND_EXECUTION,
        runner._ShaBoundary.AFTER_EXECUTION,
    )
    observations = tuple(runner._CleanShaObservation(boundary, sha, True) for boundary in boundaries)
    assert runner._validate_clean_sha_chain(observations, expected=boundaries) == sha
    with pytest.raises(runner._RunnerFoundationError, match="out of order"):
        runner._validate_clean_sha_chain(observations[::-1], expected=boundaries)
    drifted = (*observations[:-1], runner._CleanShaObservation(boundaries[-1], "b" * 40, True))
    with pytest.raises(runner._RunnerFoundationError, match="changed"):
        runner._validate_clean_sha_chain(drifted, expected=boundaries)


@_POSIX_EVIDENCE
def test_exact_six_execution_writes_one_runner_owned_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    evidence = soak.Evidence(tmp_path / "evidence")
    evidence.write_manifest(_manifest())
    seen_commands: list[tuple[str, ...]] = []
    seen_boundaries: list[runner._ShaBoundary] = []

    class Collector:
        def __init__(self, repo_root: Path) -> None:
            assert repo_root == runner._REPO_ROOT

        def observe(self, boundary: runner._ShaBoundary) -> runner._CleanShaObservation:
            seen_boundaries.append(boundary)
            return runner._CleanShaObservation(boundary, "a" * 40, True)

    def execute(argv: tuple[str, ...], *, observer: object, snapshot: object) -> runner._CompletedCommand:
        assert isinstance(observer, _Observer) and snapshot is not None
        seen_commands.append(argv)
        return _completed(_collection() if argv == runner._COLLECTION_ARGV else b"...... [100%]\n6 passed in 1.20s\n")

    _install_execution_fakes(monkeypatch, Collector)
    monkeypatch.setattr(runner, "_execute_bounded_process", execute)
    payload = runner._collect_and_execute_exact_six(evidence)

    assert seen_commands == [runner._COLLECTION_ARGV, runner._EXECUTION_ARGV]
    assert seen_boundaries == [runner._ShaBoundary.BEFORE_COLLECTION]
    assert json.loads((evidence.directory / "exact-six-result.json").read_text()) == payload
    assert evidence.state is soak.RunState.MANIFEST_FINALIZED
    assert "execution-produced exact-six runner authority is unavailable" in inspect.getsource(
        soak.Evidence._build_ledger
    )


@pytest.mark.parametrize(
    "failure",
    [
        runner._RunnerFoundationError("exact-six command timed out"),
        runner._RunnerFoundationError("stream output exceeded the reviewed bound"),
        KeyboardInterrupt(),
    ],
)
@_POSIX_EVIDENCE
def test_failed_or_cancelled_execution_never_hands_off_authority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: BaseException
) -> None:
    evidence = soak.Evidence(tmp_path / "evidence")
    evidence.write_manifest(_manifest())

    class Collector:
        def __init__(self, repo_root: Path) -> None:
            del repo_root

        def observe(self, boundary: runner._ShaBoundary) -> runner._CleanShaObservation:
            return runner._CleanShaObservation(boundary, "a" * 40, True)

    def execute(argv: tuple[str, ...], *, observer: object, snapshot: object) -> runner._CompletedCommand:
        del argv, observer, snapshot
        raise failure

    _install_execution_fakes(monkeypatch, Collector)
    monkeypatch.setattr(runner, "_execute_bounded_process", execute)
    with pytest.raises(type(failure)):
        runner._collect_and_execute_exact_six(evidence)
    assert not (evidence.directory / "exact-six-result.json").exists()


def test_sealed_snapshot_drift_stops_before_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[tuple[str, ...]] = []

    class Collector:
        def __init__(self, repo_root: Path) -> None:
            assert repo_root == runner._REPO_ROOT

        def observe(self, boundary: runner._ShaBoundary) -> runner._CleanShaObservation:
            return runner._CleanShaObservation(boundary, "a" * 40, True)

    class Sink:
        def _accept_exact_six_result(self, authority: object) -> None:
            del authority
            raise AssertionError("drifted execution must not issue authority")

    class Snapshot:
        def assert_sealed(self) -> None:
            raise runner._RunnerFoundationError("sealed exact-six snapshot changed during execution")

    @contextmanager
    def sealed(_git_sha: str):
        yield Snapshot()

    def execute(argv: tuple[str, ...], *, observer: object, snapshot: object) -> runner._CompletedCommand:
        del observer, snapshot
        commands.append(argv)
        return _completed(_collection())

    _install_execution_fakes(monkeypatch, Collector)
    monkeypatch.setattr(runner, "_sealed_execution_snapshot", sealed)
    monkeypatch.setattr(runner, "_execute_bounded_process", execute)
    with pytest.raises(runner._RunnerFoundationError, match="snapshot changed"):
        runner._collect_and_execute_exact_six(Sink())
    assert commands == [runner._COLLECTION_ARGV]


def test_authority_has_no_recoverable_closure_issuer_and_object_new_is_unregistered() -> None:
    assert runner._collect_and_execute_exact_six.__closure__ is None
    with pytest.raises(runner._RunnerFoundationError, match="caller-constructed"):
        runner._ExactSixAuthority()
    fabricated = object.__new__(runner._ExactSixAuthority)
    with pytest.raises(runner._RunnerFoundationError, match="unregistered"):
        runner._consume_exact_six_authority(fabricated, object())


@_POSIX_EVIDENCE
def test_exact_six_authority_rejects_forgery_cross_evidence_and_replay(tmp_path: Path) -> None:
    forged = soak.Evidence(tmp_path / "forged")
    forged.write_manifest(_manifest())
    with pytest.raises(RuntimeError, match="execution-produced runner authority"):
        forged._accept_exact_six_result(object())
    assert forged.state is soak.RunState.FAIL

    fabricated = object.__new__(runner._ExactSixAuthority)
    unregistered = soak.Evidence(tmp_path / "unregistered")
    unregistered.write_manifest(_manifest())
    with pytest.raises(runner._RunnerFoundationError, match="unregistered"):
        unregistered._accept_exact_six_result(fabricated)

    captured: list[runner._ExactSixAuthority] = []

    class Sink:
        def _accept_exact_six_result(self, authority: runner._ExactSixAuthority) -> None:
            captured.append(authority)

    class Collector:
        def __init__(self, repo_root: Path) -> None:
            del repo_root

        def observe(self, boundary: runner._ShaBoundary) -> runner._CleanShaObservation:
            return runner._CleanShaObservation(boundary, "a" * 40, True)

    def execute(argv: tuple[str, ...], *, observer: object, snapshot: object) -> runner._CompletedCommand:
        del observer, snapshot
        return _completed(_collection() if argv == runner._COLLECTION_ARGV else b"...... [100%]\n6 passed in 1.20s\n")

    sink = Sink()
    with pytest.MonkeyPatch.context() as patcher:
        _install_execution_fakes(patcher, Collector)
        patcher.setattr(runner, "_execute_bounded_process", execute)
        runner._collect_and_execute_exact_six(sink)
    authority = captured[0]
    with pytest.raises(runner._RunnerFoundationError, match="another Evidence"):
        runner._consume_exact_six_authority(authority, object())
    runner._consume_exact_six_authority(authority, sink)
    with pytest.raises(runner._RunnerFoundationError, match="spent"):
        runner._consume_exact_six_authority(authority, sink)


def test_process_group_cleanup_refuses_reused_leader_before_any_probe_or_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations: list[tuple[int, int]] = []

    class Process:
        pid = 123

    class ReusedObserver:
        def identity_for_pid(self, pid: int) -> runner._ProcessIdentity:
            return runner._ProcessIdentity(pid, "test:start=reused")

    monkeypatch.setattr(runner.os, "killpg", lambda pid, signum: operations.append((pid, signum)), raising=False)
    with pytest.raises(runner._RunnerFoundationError, match="identity changed"):
        runner._settle_process_group(  # type: ignore[arg-type]
            Process(),
            observer=ReusedObserver(),  # type: ignore[arg-type]
            expected=runner._ProcessIdentity(123, "test:start=original"),
        )
    assert operations == []


@pytest.mark.parametrize("stage", ["grace", "signal", "wait"])
def test_cleanup_retries_to_settlement_before_propagating_cancellation(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    child = runner._ProcessIdentity(2, "child")
    state = {"live": stage != "wait", "interrupted": False}

    class Observer:
        def descendants(self, _expected: object) -> tuple[runner._ProcessIdentity, ...]:
            return (child,) if state["live"] else ()

        def signal_exact_for_cleanup(self, _identity: object, _signum: int) -> None:
            if stage == "signal" and not state["interrupted"]:
                state["interrupted"] = True
                raise KeyboardInterrupt
            state["live"] = False

    original_sleep = runner.time.sleep

    def sleep(duration: float) -> None:
        if stage == "grace" and not state["interrupted"]:
            state["interrupted"] = True
            state["live"] = False
            raise KeyboardInterrupt
        original_sleep(duration)

    group_calls = 0

    def settle_group(*_args: object, **_kwargs: object) -> None:
        nonlocal group_calls
        group_calls += 1
        if stage == "wait" and not state["interrupted"]:
            state["interrupted"] = True
            raise KeyboardInterrupt

    monkeypatch.setattr(runner.time, "sleep", sleep)
    monkeypatch.setattr(runner, "_settle_process_group", settle_group)
    with pytest.raises(KeyboardInterrupt):
        runner._settle_owned_tree(object(), observer=Observer(), expected=object())  # type: ignore[arg-type]
    assert state == {"live": False, "interrupted": True}
    assert group_calls >= 1


def test_native_windows_exact_six_authority_is_fail_closed(tmp_path: Path) -> None:
    if runner.os.name != "nt":
        pytest.skip("native Windows contract")
    with pytest.raises(runner._RunnerActivationDisabled, match="Linux subreaper"):
        runner._collect_and_execute_exact_six(object())


def test_exact_six_root_and_environment_are_not_caller_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    assert tuple(inspect.signature(runner._collect_and_execute_exact_six).parameters) == ("evidence",)
    monkeypatch.setenv("PYTHONPATH", "attacker")
    monkeypatch.setenv("PYTHONHOME", "attacker")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k attacker")
    monkeypatch.setenv("PYTEST_PLUGINS", "attacker_plugin")
    monkeypatch.setenv("GIT_DIR", "attacker-git")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "alias.status")
    monkeypatch.setenv("LD_PRELOAD", "attacker.so")
    monkeypatch.setenv("PYTHONOPTIMIZE", "2")
    monkeypatch.setenv("QT_PLUGIN_PATH", "attacker-qt")
    monkeypatch.setenv("CRYODAQ_CONFIG", "attacker-config")
    root = Path("/snapshot").resolve()
    site_packages = Path("/site-packages").resolve()
    environment = runner._controlled_test_environment(root, site_packages)
    assert set(environment) == {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONNOUSERSITE",
        "PYTHONPATH",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "TMPDIR",
        "TZ",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
    }
    assert environment["PYTHONPATH"] == os.pathsep.join((str(root / "src"), str(root), str(site_packages)))


def test_sealed_snapshot_detects_executable_content_race(tmp_path: Path) -> None:
    interpreter = tmp_path / ".venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"pinned-python")
    snapshot = runner._ExecutionSnapshot(tmp_path, interpreter, {}, runner._tree_sha256(tmp_path))
    interpreter.write_bytes(b"replaced-python")
    with pytest.raises(runner._RunnerFoundationError, match="snapshot changed"):
        snapshot.assert_sealed()


@_POSIX_EVIDENCE
def test_running_executable_capture_ignores_path_replacement_during_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected = tmp_path / ".venv/bin/python"
    expected.parent.mkdir(parents=True)
    expected.symlink_to(runner.sys.executable)
    destination = tmp_path / "captured-python"
    real_read = runner.os.read
    replaced = False

    def racing_read(fd: int, size: int) -> bytes:
        nonlocal replaced
        if not replaced:
            replaced = True
            expected.unlink()
            expected.write_text("#!/bin/sh\nexit 99\n")
            expected.chmod(0o500)
        return real_read(fd, size)

    monkeypatch.setattr(runner.os, "read", racing_read)
    captured = runner._copy_running_executable(expected, destination)
    assert replaced
    assert captured == runner._hash_regular_file(destination)
    assert captured == runner._hash_regular_file(Path("/proc/self/exe"))
    assert destination.read_bytes() != expected.read_bytes()


@_POSIX_EVIDENCE
def test_controlled_environment_genuinely_collects_strict_exact_six() -> None:
    import psutil

    with _head_snapshot() as snapshot:
        completed = runner._execute_bounded_process(
            runner._COLLECTION_ARGV,
            observer=runner._LockedPsutilObserver(psutil),
            snapshot=snapshot,
            timeout_s=30,
        )
    runner._parse_exact_collection(
        stdout_evidence=completed.stdout_evidence,
        stdout=completed.stdout,
        stderr_evidence=completed.stderr_evidence,
        stderr=completed.stderr,
        exit_code=completed.exit_code,
    )


@_POSIX_EVIDENCE
def test_controlled_environment_genuinely_executes_strict_exact_six() -> None:
    import psutil

    with _head_snapshot() as snapshot:
        completed = runner._execute_bounded_process(
            runner._EXECUTION_ARGV,
            observer=runner._LockedPsutilObserver(psutil),
            snapshot=snapshot,
            timeout_s=60,
        )
    runner._validate_exact_execution(
        stdout_evidence=completed.stdout_evidence,
        stdout=completed.stdout,
        stderr_evidence=completed.stderr_evidence,
        stderr=completed.stderr,
        exit_code=completed.exit_code,
    )


@pytest.mark.parametrize("holds_output", [False, True])
@_POSIX_EVIDENCE
def test_real_supervisor_rejects_and_settles_survivor_after_test_leader_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    holds_output: bool,
) -> None:
    interpreter = tmp_path / ".venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(runner.sys.executable)
    pid_path = tmp_path / "survivor.pid"
    redirection = "" if holds_output else ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL"
    code = (
        "import pathlib, subprocess, sys; "
        f"p=subprocess.Popen([sys.executable, '-c', 'import os,time; os.setsid(); time.sleep(60)']{redirection}); "
        f"pathlib.Path({str(pid_path)!r}).write_text(str(p.pid))"
    )
    argv = (".venv/bin/python", "-c", code)
    monkeypatch.setattr(runner, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(runner, "_COLLECTION_ARGV", argv)
    import psutil

    observer = runner._LockedPsutilObserver(psutil)
    site_packages = Path(psutil.__file__).resolve().parents[1]
    snapshot = runner._ExecutionSnapshot(
        tmp_path,
        interpreter,
        runner._controlled_test_environment(tmp_path, site_packages),
        runner._tree_sha256(tmp_path),
    )
    marker = "timed out" if holds_output else "descendants"
    with pytest.raises(runner._RunnerFoundationError, match=marker):
        runner._execute_bounded_process(argv, observer=observer, snapshot=snapshot, timeout_s=0.5)
    survivor_pid = int(pid_path.read_text())
    deadline = runner.time.monotonic() + 3
    while psutil.pid_exists(survivor_pid) and runner.time.monotonic() < deadline:
        runner.time.sleep(0.05)
    assert not psutil.pid_exists(survivor_pid)


@_POSIX_EVIDENCE
def test_supervisor_reexec_is_bound_to_open_executable_after_path_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    interpreter = tmp_path / ".venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(runner.sys.executable)
    argv = (".venv/bin/python", "-c", "print('pinned-executable')")
    monkeypatch.setattr(runner, "_COLLECTION_ARGV", argv)
    import psutil

    locked = runner._LockedPsutilObserver(psutil)

    class ReplacingObserver:
        replaced = False

        def identity_for_pid(self, pid: int) -> runner._ProcessIdentity:
            identity = locked.identity_for_pid(pid)
            if not self.replaced:
                interpreter.unlink()
                interpreter.write_text("#!/bin/sh\nexit 99\n")
                interpreter.chmod(0o500)
                self.replaced = True
            return identity

        def __getattr__(self, name: str) -> object:
            return getattr(locked, name)

    site_packages = Path(psutil.__file__).resolve().parents[1]
    snapshot = runner._ExecutionSnapshot(
        tmp_path,
        interpreter,
        runner._controlled_test_environment(tmp_path, site_packages),
        runner._tree_sha256(tmp_path),
    )
    completed = runner._execute_bounded_process(
        argv,
        observer=ReplacingObserver(),  # type: ignore[arg-type]
        snapshot=snapshot,
        timeout_s=5,
    )
    assert completed.exit_code == 0
    assert completed.stdout == b"pinned-executable\n"


@_POSIX_EVIDENCE
def test_exact_six_publication_collision_never_overwrites_racer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence = soak.Evidence(tmp_path / "collision")
    evidence.write_manifest(_manifest())

    class Collector:
        def __init__(self, repo_root: Path) -> None:
            del repo_root

        def observe(self, boundary: runner._ShaBoundary) -> runner._CleanShaObservation:
            return runner._CleanShaObservation(boundary, "a" * 40, True)

    def execute(argv: tuple[str, ...], *, observer: object, snapshot: object) -> runner._CompletedCommand:
        del observer, snapshot
        return _completed(_collection() if argv == runner._COLLECTION_ARGV else b"...... [100%]\n6 passed in 1.20s\n")

    original_link = soak.os.link

    def collide(
        source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
        follow_symlinks: bool,
    ) -> None:
        fd = soak.os.open(
            destination,
            soak.os.O_WRONLY | soak.os.O_CREAT | soak.os.O_EXCL,
            0o600,
            dir_fd=dst_dir_fd,
        )
        try:
            soak.os.write(fd, b"racer-wins\n")
            soak.os.fsync(fd)
        finally:
            soak.os.close(fd)
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    _install_execution_fakes(monkeypatch, Collector)
    monkeypatch.setattr(runner, "_execute_bounded_process", execute)
    monkeypatch.setattr(soak.os, "link", collide)
    with pytest.raises(RuntimeError, match="write-once"):
        runner._collect_and_execute_exact_six(evidence)
    assert (evidence.directory / "exact-six-result.json").read_bytes() == b"racer-wins\n"
    assert evidence.state is soak.RunState.FAIL


def test_process_identity_requires_pid_and_os_start_identity() -> None:
    identity = runner._ProcessIdentity(123, "darwin:start=123.25")
    assert identity.pid == 123
    with pytest.raises(runner._RunnerFoundationError):
        runner._ProcessIdentity(0, "start")
    with pytest.raises(runner._RunnerFoundationError):
        runner._ProcessIdentity(123, "")
    with pytest.raises(TypeError):
        runner._ProcessIdentity(123, 1)  # type: ignore[arg-type]
    with pytest.raises(runner._RunnerFoundationError):
        runner._ProcessIdentity(123, "start\nreused")


def test_cleanup_contract_is_once_only_and_records_forced_cleanup() -> None:
    identities = (runner._ProcessIdentity(10, "start-a"), runner._ProcessIdentity(11, "start-b"))
    cleanup = runner._CancellationCleanupContract(10, identities[0], identities)
    assert cleanup.request().phase is runner._CleanupPhase.REQUESTED
    with pytest.raises(runner._RunnerFoundationError, match="only once"):
        cleanup.request()
    final = cleanup.complete(forced=True)
    assert final.phase is runner._CleanupPhase.COMPLETE
    assert final.forced is True
    assert final.leader == identities[0]
    assert final.descendants == identities
    with pytest.raises(runner._RunnerFoundationError):
        cleanup.complete(forced=False)


def test_cleanup_rejects_duplicate_pid_epochs_and_ambiguous_leader() -> None:
    leader = runner._ProcessIdentity(10, "start-a")
    other_epoch = runner._ProcessIdentity(10, "start-b")
    child = runner._ProcessIdentity(11, "shared-start")

    with pytest.raises(runner._RunnerFoundationError, match="PIDs must be unique"):
        runner._CancellationCleanupContract(10, leader, (leader, other_epoch))
    with pytest.raises(runner._RunnerFoundationError, match="exactly one declared leader"):
        runner._CancellationCleanupContract(10, leader, (child,))
    with pytest.raises(runner._RunnerFoundationError, match="exactly one declared leader"):
        runner._CancellationCleanupContract(10, leader, (leader, leader, child))
    # Start identity is opaque observer evidence; distinct PIDs may share its
    # text while compound identities remain unambiguous.
    same_start_child = runner._ProcessIdentity(11, "start-a")
    contract = runner._CancellationCleanupContract(10, leader, (leader, same_start_child))
    assert contract.evidence().descendants == (leader, same_start_child)


def test_pid_reuse_recheck_is_terminal_and_cannot_complete_cleanup() -> None:
    leader = runner._ProcessIdentity(10, "start-a")
    child = runner._ProcessIdentity(11, "start-b")
    cleanup = runner._CancellationCleanupContract(10, leader, (leader, child))
    cleanup.request()
    cleanup.record_identity_recheck(leader)
    cleanup.record_identity_recheck(child)

    reused = runner._ProcessIdentity(11, "start-reused")
    with pytest.raises(runner._RunnerFoundationError, match="do not signal or reap"):
        cleanup.record_identity_recheck(reused)
    assert cleanup.evidence().phase is runner._CleanupPhase.TERMINAL_IDENTITY_MISMATCH
    with pytest.raises(runner._RunnerFoundationError, match="requested before completion"):
        cleanup.complete(forced=True)


def test_nonce_provenance_is_immutable_validated_and_non_authoritative() -> None:
    provenance = runner._RunProvenance("a" * 32, "sha256:" + "b" * 64, "darwin")
    assert provenance.run_id == "a" * 32
    with pytest.raises(Exception):
        provenance.run_id = "c" * 32  # type: ignore[misc]
    assert not hasattr(runner, "_RunnerAuthority")
    assert not hasattr(runner, "Evidence")


def test_runner_activation_remains_hard_disabled_and_module_has_no_execution_imports() -> None:
    with pytest.raises(runner._RunnerActivationDisabled, match="R2/R3"):
        runner._PosixSoakRunner().run()

    source = Path("scripts/soak_mock_stack_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    # The activation prerequisite may collect Git/process identity and perform
    # exact-identity cleanup. CLI, network transports, and terminal PASS stay
    # fused until the complete executor is accepted.
    assert not imports & {"argparse", "urllib", "requests", "httpx", "aiohttp"}
    assert runner.__all__ == ()
    assert not hasattr(runner, "main")
