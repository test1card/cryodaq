from __future__ import annotations

import signal
import subprocess
from pathlib import Path

import pytest

from scripts import soak_mock_stack_runner as runner


class _NoSuchProcess(Exception):
    pass


class _AccessDenied(Exception):
    pass


class _TimeoutExpired(Exception):
    pass


class _FakeProcess:
    def __init__(
        self,
        module,
        pid: int,
        *,
        created: float,
        parent: int,
        argv: tuple[str, ...],
        status: str = "running",
    ) -> None:
        self.module = module
        self.pid = pid
        self.created = created
        self.parent = parent
        self.argv = argv
        self.current_status = status
        self.signals: list[int] = []
        self.reuse_after_signal: float | None = None

    def create_time(self) -> float:
        return self.created

    def status(self) -> str:
        return self.current_status

    def ppid(self) -> int:
        return self.parent

    def cmdline(self) -> list[str]:
        return list(self.argv)

    def send_signal(self, signum: int) -> None:
        self.signals.append(signum)
        if self.reuse_after_signal is not None:
            self.created = self.reuse_after_signal

    def wait(self, *, timeout: float) -> None:
        assert 0 < timeout <= 20
        self.module.processes.pop(self.pid, None)


class _FakePsutil:
    __version__ = "7.2.2"
    NoSuchProcess = _NoSuchProcess
    AccessDenied = _AccessDenied
    TimeoutExpired = _TimeoutExpired
    STATUS_ZOMBIE = "zombie"

    def __init__(self) -> None:
        self.processes: dict[int, _FakeProcess] = {}

    def Process(self, pid: int) -> _FakeProcess:  # noqa: N802 - psutil API spelling
        try:
            return self.processes[pid]
        except KeyError:
            raise self.NoSuchProcess(pid) from None

    def add_assistant(
        self,
        *,
        pid: int = 20,
        parent: int = 10,
        created: float = 123.5,
        status: str = "running",
    ) -> _FakeProcess:
        process = _FakeProcess(
            self,
            pid,
            created=created,
            parent=parent,
            argv=("python", "-m", "cryodaq.agents.assistant_bootstrap"),
            status=status,
        )
        self.processes[pid] = process
        return process


def test_locked_observer_binds_exact_assistant_identity_signals_and_settles() -> None:
    module = _FakePsutil()
    process = module.add_assistant()
    observer = runner._LockedPsutilObserver(module)

    observed = observer.observe_assistant(20, expected_launcher_pid=10)
    assert observed.identity == runner._ProcessIdentity(20, "psutil-7.2.2:ctime-ns=123500000000")
    observer.signal_exact(observed.identity, signal.SIGTERM)
    assert process.signals == [signal.SIGTERM]
    observer.wait_gone(observed.identity, timeout_s=5)
    assert 20 not in module.processes


def test_locked_observer_rejects_version_role_parent_pid_reuse_and_nonterm_signal() -> None:
    module = _FakePsutil()
    process = module.add_assistant()
    observer = runner._LockedPsutilObserver(module)
    identity = observer.identity_for_pid(20)

    module.__version__ = "7.2.1"
    with pytest.raises(runner._RunnerActivationDisabled, match="version"):
        runner._LockedPsutilObserver(module)
    module.__version__ = "7.2.2"

    with pytest.raises(runner._RunnerFoundationError, match="direct launcher"):
        observer.observe_assistant(20, expected_launcher_pid=99)
    process.argv = ("python", "-m", "cryodaq.engine")
    with pytest.raises(runner._RunnerFoundationError, match="assistant"):
        observer.observe_assistant(20, expected_launcher_pid=10)
    process.argv = ("python", "-m", "cryodaq.agents.assistant_bootstrap")
    process.created = 124.0
    with pytest.raises(runner._RunnerFoundationError, match="changed"):
        observer.signal_exact(identity, signal.SIGTERM)
    with pytest.raises(runner._RunnerFoundationError, match="only"):
        observer.signal_exact(observer.identity_for_pid(20), signal.SIGINT)


def test_locked_observer_rejects_zombie_missing_and_unbounded_wait() -> None:
    module = _FakePsutil()
    process = module.add_assistant(status="zombie")
    observer = runner._LockedPsutilObserver(module)
    with pytest.raises(runner._RunnerFoundationError, match="not live"):
        observer.identity_for_pid(20)
    module.processes.pop(20)
    with pytest.raises(runner._RunnerFoundationError, match="unavailable"):
        observer.identity_for_pid(20)
    process.current_status = "running"
    module.processes[20] = process
    with pytest.raises(runner._RunnerFoundationError, match="bound"):
        observer.wait_gone(observer.identity_for_pid(20), timeout_s=21)
    identity = observer.identity_for_pid(20)
    module.processes.pop(20)
    observer.wait_gone(identity, timeout_s=5)


def test_locked_observer_dependency_is_dev_only_and_exactly_pinned() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    lock = Path("requirements-lock.txt").read_text(encoding="utf-8")
    assert '"psutil>=7.2.2,<7.3"' in pyproject
    assert "psutil==7.2.2\n" in lock
    base_dependencies = pyproject.split("[project.optional-dependencies]", 1)[0]
    assert "psutil" not in base_dependencies


def test_exact_child_role_rejects_extra_duplicate_and_leading_tokens() -> None:
    assert runner._exact_child_role(("python", "-m", "cryodaq.agents.assistant_bootstrap")) == "assistant"
    assert runner._exact_child_role(("python", "-m", "cryodaq.engine")) == "engine"
    assert runner._exact_child_role(("python", "--mode=assistant")) == "assistant"
    assert runner._exact_child_role(("python", "--mode=engine")) == "engine"
    # Real mock-stack children (launcher.py appends "--mock" only to the
    # engine command, never to the assistant command).
    assert runner._exact_child_role(("python", "-m", "cryodaq.engine", "--mock")) == "engine"
    assert runner._exact_child_role(("CryoDAQ.exe", "--mode=engine", "--mock")) == "engine"

    for argv in (
        ("python", "-m", "cryodaq.agents.assistant_bootstrap", "--evil"),
        ("python", "-m", "cryodaq.agents.assistant_bootstrap", "-m", "cryodaq.engine"),
        ("python", "extra.py", "--mode=assistant"),
        ("python", "-m", "cryodaq.agents.assistant_bootstrap", "--mode=assistant"),
        ("python", "-m", "cryodaq.agents.assistant_bootstrap", "--mock"),
        ("python", "--mode=assistant", "--mock"),
        ("python", "-m", "cryodaq.engine", "--mock", "--mock"),
        ("python", "--mode=engine", "--evil", "--mock"),
        ("python", "-m", "cryodaq.engine", "--mock", "-m", "cryodaq.engine"),
    ):
        with pytest.raises(runner._RunnerFoundationError, match="not an exact allowlisted role"):
            runner._exact_child_role(argv)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(("git", *args), cwd=repo, check=True, capture_output=True, text=True)


def test_clean_sha_collector_requires_order_same_sha_and_no_untracked_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "soak@example.invalid")
    _git(repo, "config", "user.name", "Soak Test")
    tracked = repo / "tracked.txt"
    tracked.write_text("one\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "initial")

    collector = runner._CleanShaCollector(repo)
    first = collector.observe(runner._ShaBoundary.BEFORE_COLLECTION)
    assert first.clean is True
    with pytest.raises(runner._RunnerFoundationError, match="out of order"):
        collector.observe(runner._ShaBoundary.AFTER_EXECUTION)
    collector.observe(runner._ShaBoundary.BETWEEN_COLLECTION_AND_EXECUTION)
    (repo / "untracked.txt").write_text("drift\n", encoding="utf-8")
    with pytest.raises(runner._RunnerFoundationError, match="drift"):
        collector.observe(runner._ShaBoundary.AFTER_EXECUTION)
