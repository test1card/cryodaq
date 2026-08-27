"""A diagnosis that does not reach the evidence bundle diagnoses nothing.

WHY THIS MODULE EXISTS. The periodic live source was taught to name the condition that
took its authority, and the line it writes goes to the assistant's own log. The launcher
sends the assistant child's stderr to the null device, and `setup_logging("assistant")`
writes `logs/assistant.log` under the writable state root -- which for a soak run is the
runner's temporary directory, deleted when the run ends. So the diagnosis existed and
was unreachable: the bundle a week-long run leaves behind never held it.

These tests bind the ARTIFACT BOUNDARY, not the log call. A test that only checked the
logger would have stayed green through exactly this failure.
"""

from __future__ import annotations

import errno
import os
import threading
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

# The retention bound comes from the AUTHORITATIVE rotating-log contract in
# cryodaq.logging_setup -- the module whose TimedRotatingFileHandler produces
# these rotations -- not from the runner's re-export of it, so this guard
# cannot stay green while production retention and the refusal boundary drift
# apart (PR #102 cold review F1).
from cryodaq.logging_setup import ASSISTANT_LOG_BACKUP_COUNT
from scripts import soak_mock_stack_runner as runner


class _Evidence:
    """The narrow part of the evidence writer these publishers use."""

    def __init__(self) -> None:
        self.logs: dict[str, str] = {}

    def write_log(self, name: str, text: str) -> None:
        self.logs[name] = text


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    (tmp_path / "logs").mkdir(parents=True)
    return tmp_path


def test_the_assistant_log_is_published(state_root: Path) -> None:
    written = (
        "2026-08-20 08:14:02 WARNING Periodic live source lost authority: "
        "because=the receive loop stopped: a frame was rejected as malformed, "
        "out of sequence, or counter-inconsistent\n"
    )
    (state_root / "logs" / "assistant.log").write_text(written, encoding="utf-8")

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    assert runner._ASSISTANT_LOG_EVIDENCE_NAME in evidence.logs
    assert "lost authority" in evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "out of sequence" in evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]


def test_an_absent_log_is_said_rather_than_skipped(state_root: Path) -> None:
    """A missing file must not look like a publisher that silently did nothing."""

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    assert evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME] == runner._ASSISTANT_LOG_ABSENT_MARKER


def test_a_long_log_keeps_its_END(state_root: Path) -> None:
    """The bound protects the bundle's size; it must not choose which half survives.

    The reason that CHANGED is written last, so the tail is the diagnosis.
    """

    filler = "x" * (runner._MAX_LAUNCHER_LOG_BYTES + 4096)
    (state_root / "logs" / "assistant.log").write_text(filler + "\nTHE LAST LINE\n", encoding="utf-8")

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "THE LAST LINE" in published
    assert len(published.encode("utf-8")) <= runner._MAX_LAUNCHER_LOG_BYTES
    assert published.startswith(runner._TRUNCATED_LAUNCHER_LOG_MARKER.decode("utf-8"))


def test_the_published_log_is_redacted(state_root: Path) -> None:
    """It rides in a bundle that leaves the machine, so it goes through the redactor."""

    from scripts.soak_mock_stack import redact_text

    secret = "https://api.telegram.org/bot123456:AAHfakefakefakefakefakefakefake/sendMessage"
    written = f"posting to {secret}\n"
    # Written as BYTES: `write_text` rewrites the line ending on Windows, and a test that
    # compares against the string it passed would be measuring the writer.
    (state_root / "logs" / "assistant.log").write_bytes(written.encode("utf-8"))

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert published == redact_text(written)
    assert "AAHfakefakefake" not in published


def test_the_success_path_publishes_it(tmp_path: Path, state_root: Path) -> None:
    """A soak that finishes normally must still carry the assistant's own account."""

    (state_root / "logs" / "assistant.log").write_bytes(b"finished cleanly\n")
    evidence = _Evidence()

    with runner._launcher_log_capture(evidence, tmp_path / "launcher.txt", state_root=state_root) as writer:
        writer.write(b"running\n")

    assert "finished cleanly" in evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]


def test_the_FAILURE_path_publishes_it(tmp_path: Path, state_root: Path) -> None:
    """And a soak that fails must carry it MOST of all -- that is the run being diagnosed.

    Driven by making the block raise, not by reading the source: an ordering assertion
    over source text matched the word "raises" inside the docstring and passed while the
    publish was after the re-raise.
    """

    (state_root / "logs" / "assistant.log").write_bytes(b"stopped because the receive loop ended\n")
    evidence = _Evidence()

    with pytest.raises(RuntimeError, match="the soak failed"):
        with runner._launcher_log_capture(evidence, tmp_path / "launcher.txt", state_root=state_root) as writer:
            writer.write(b"running\n")
            raise RuntimeError("the soak failed")

    assert runner._ASSISTANT_LOG_EVIDENCE_NAME in evidence.logs, (
        "a failing soak published no assistant log, which is the run that needed it"
    )
    assert "receive loop ended" in evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]


@pytest.mark.parametrize("topology", ("hard-link", "symbolic-link", "fifo"))
def test_launcher_capture_refuses_unowned_engine_stderr_topology(tmp_path: Path, topology: str) -> None:
    """The real capture path never publishes bytes supplied by an external owner."""

    state_root = tmp_path / "state"
    logs = state_root / "logs"
    logs.mkdir(parents=True)
    external = tmp_path / "outside-state-root.log"
    secret = f"EXTERNAL {topology.upper()} ENGINE STDERR MUST NOT PUBLISH\n".encode()
    external.write_bytes(secret)
    engine_log = logs / "engine.stderr.log"
    writer: threading.Thread | None = None

    if topology == "hard-link":
        os.link(external, engine_log)
        expected_marker_name = "_ENGINE_STDERR_HARD_LINKED_MARKER"
    elif topology == "symbolic-link":
        try:
            os.symlink(external, engine_log)
        except (OSError, NotImplementedError):  # pragma: no cover - unprivileged Windows
            pytest.skip("this platform does not allow creating a symbolic link here")
        expected_marker_name = "_ENGINE_STDERR_REFUSED_MARKER"
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("this platform cannot create a filesystem fifo")
        os.mkfifo(engine_log)
        expected_marker_name = "_ENGINE_STDERR_NOT_REGULAR_MARKER"

        def offer_external_bytes() -> None:
            deadline = runner.time.monotonic() + 1.0
            while runner.time.monotonic() < deadline:
                try:
                    descriptor = os.open(engine_log, os.O_WRONLY | os.O_NONBLOCK)
                except OSError as error:
                    if error.errno != errno.ENXIO:
                        raise
                    runner.time.sleep(0.01)
                    continue
                try:
                    os.write(descriptor, secret)
                finally:
                    os.close(descriptor)
                return

        writer = threading.Thread(target=offer_external_bytes, daemon=True)
        writer.start()

    evidence = _Evidence()
    with runner._launcher_log_capture(
        evidence,
        tmp_path / f"launcher-engine-{topology}.txt",
        state_root=state_root,
    ) as launcher_writer:
        launcher_writer.write(b"launcher output\n")

    if writer is not None:
        writer.join(timeout=2)
        assert not writer.is_alive(), "the fifo control writer did not reach a terminal state"
    published = evidence.logs[runner._ENGINE_STDERR_EVIDENCE_NAME]
    assert secret.decode().strip() not in published
    assert published == getattr(runner, expected_marker_name)


def test_launcher_capture_reads_only_the_bounded_engine_stderr_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The engine log is bounded at descriptor read time, not after a whole-file read."""

    state_root = tmp_path / "state"
    logs = state_root / "logs"
    logs.mkdir(parents=True)
    engine_log = logs / "engine.stderr.log"
    line = b"x" * 100 + b"\n"
    redaction_context_bytes = 64 * 1024
    read_bound = runner._MAX_LAUNCHER_LOG_BYTES + redaction_context_bytes
    engine_log.write_bytes(line * (read_bound // len(line) + 100) + b"ENGINE STDERR END\n")
    real_read_bytes = Path.read_bytes
    real_bounded_read = runner._read_regular_file_no_follow
    requested_bounds: list[int] = []

    def forbid_engine_whole_file_read(path: Path) -> bytes:
        if path == engine_log:
            raise AssertionError("engine stderr was read before applying the retention bound")
        return real_read_bytes(path)

    def observe_bounded_read(directory_descriptor: int | None, path: Path | str, *, maximum_bytes: int):
        if str(path).endswith("engine.stderr.log"):
            requested_bounds.append(maximum_bytes)
        return real_bounded_read(directory_descriptor, path, maximum_bytes=maximum_bytes)

    monkeypatch.setattr(Path, "read_bytes", forbid_engine_whole_file_read)
    monkeypatch.setattr(runner, "_read_regular_file_no_follow", observe_bounded_read)
    evidence = _Evidence()

    with runner._launcher_log_capture(
        evidence,
        tmp_path / "launcher-bounded-engine-stderr.txt",
        state_root=state_root,
    ) as launcher_writer:
        launcher_writer.write(b"launcher output\n")

    published = evidence.logs[runner._ENGINE_STDERR_EVIDENCE_NAME]
    assert runner._ENGINE_STDERR_REDACTION_CONTEXT_BYTES == redaction_context_bytes
    assert requested_bounds == [read_bound], "the descriptor read must remain explicitly bounded"
    assert "ENGINE STDERR END" in published
    assert published.startswith(runner._TRUNCATED_LAUNCHER_LOG_MARKER.decode())
    assert len(published.encode()) <= runner._MAX_LAUNCHER_LOG_BYTES


def test_unsettled_writer_refuses_child_writable_logs_without_traversal(
    tmp_path: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed owner settlement makes every pathname under its state root untrusted."""

    (state_root / "logs" / "engine.stderr.log").write_bytes(b"MUST NOT READ ENGINE STDERR\n")
    (state_root / "logs" / "assistant.log").write_bytes(b"MUST NOT READ ASSISTANT LOG\n")
    traversals: list[str] = []

    def forbidden_read_bytes(path: Path) -> bytes:
        traversals.append(f"read:{path}")
        raise AssertionError("the unsettled child-writable root was read")

    def forbidden_lstat(path: object, **_kwargs: object) -> os.stat_result:
        traversals.append(f"lstat:{path}")
        raise AssertionError("the unsettled child-writable root was measured")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    monkeypatch.setattr(runner.os, "lstat", forbidden_lstat)
    evidence = _Evidence()

    def fail_settlement() -> None:
        raise RuntimeError("owned writer did not settle")

    with pytest.raises(ValueError, match="primary") as raised:
        with runner._launcher_log_capture(
            evidence,
            tmp_path / "launcher.txt",
            settle_writer=fail_settlement,
            state_root=state_root,
        ) as writer:
            writer.write(b"launcher output\n")
            raise ValueError("primary")

    assert traversals == [], "no syscall may enter a root whose writer is still live"
    assert evidence.logs[runner._ENGINE_STDERR_EVIDENCE_NAME] == runner._UNSETTLED_CHILD_WRITER_LOG_REFUSAL_MARKER
    assert evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME] == runner._UNSETTLED_CHILD_WRITER_LOG_REFUSAL_MARKER
    assert "MUST NOT READ" not in "".join(evidence.logs.values())
    assert len(runner._UNSETTLED_CHILD_WRITER_LOG_REFUSAL_MARKER.encode("utf-8")) <= 512
    assert any("launcher writer settlement failed" in note for note in (raised.value.__notes__ or ()))


def test_settlement_baseexception_preserves_primary_refuses_root_and_defers_drain_until_writer_settles(
    tmp_path: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live child-style writer keeps drain ownership pending until outer settlement."""

    (state_root / "logs" / "engine.stderr.log").write_bytes(b"MUST NOT READ ENGINE STDERR\n")
    (state_root / "logs" / "assistant.log").write_bytes(b"MUST NOT READ ASSISTANT LOG\n")
    traversals: list[str] = []
    settlement_failed = False

    def under_state_root(value: object) -> bool:
        return isinstance(value, (str, os.PathLike)) and Path(value).is_relative_to(state_root)

    real_read_bytes = Path.read_bytes
    real_lstat = runner.os.lstat
    real_stat = runner.os.stat
    real_open = runner.os.open
    real_scandir = runner.os.scandir

    def guarded_read_bytes(path: Path) -> bytes:
        if settlement_failed and under_state_root(path):
            traversals.append(f"read_bytes:{path}")
            raise AssertionError("the unsettled child-writable root was read")
        return real_read_bytes(path)

    def guarded_lstat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if settlement_failed and under_state_root(path):
            traversals.append(f"lstat:{path}")
            raise AssertionError("the unsettled child-writable root was measured")
        return real_lstat(path, *args, **kwargs)  # type: ignore[arg-type]

    def guarded_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if settlement_failed and under_state_root(path):
            traversals.append(f"stat:{path}")
            raise AssertionError("the unsettled child-writable root was measured")
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    def guarded_open(path: object, *args: object, **kwargs: object) -> int:
        if settlement_failed and under_state_root(path):
            traversals.append(f"open:{path}")
            raise AssertionError("the unsettled child-writable root was opened")
        return real_open(path, *args, **kwargs)  # type: ignore[arg-type]

    def guarded_scandir(path: object):
        if settlement_failed and under_state_root(path):
            traversals.append(f"scandir:{path}")
            raise AssertionError("the unsettled child-writable root was enumerated")
        return real_scandir(path)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(runner.os, "lstat", guarded_lstat)
    monkeypatch.setattr(runner.os, "stat", guarded_stat)
    monkeypatch.setattr(runner.os, "open", guarded_open)
    monkeypatch.setattr(runner.os, "scandir", guarded_scandir)

    created_drains: list[runner._BoundedLauncherLogDrain] = []

    class ObservedDrain(runner._BoundedLauncherLogDrain):
        def __init__(self) -> None:
            super().__init__()
            created_drains.append(self)

    class SettlementInterrupted(BaseException):
        pass

    monkeypatch.setattr(runner, "_BoundedLauncherLogDrain", ObservedDrain)
    evidence = _Evidence()
    writer = None
    retained_writer_fd: int | None = None
    caught: BaseException | None = None

    def interrupt_settlement() -> None:
        nonlocal settlement_failed
        settlement_failed = True
        raise SettlementInterrupted("MUST NOT LEAK SETTLEMENT DETAIL")

    try:
        with runner._launcher_log_capture(
            evidence,
            tmp_path / "launcher-baseexception.txt",
            settle_writer=interrupt_settlement,
            state_root=state_root,
        ) as writer:
            retained_writer_fd = os.dup(writer.fileno())
            writer.write(b"launcher output\n")
            raise ValueError("primary run failure")
    except BaseException as error:
        caught = error

    production_closed_writer = writer is not None and writer.closed
    production_pending_drain = len(created_drains) == 1 and created_drains[0]._thread.is_alive()
    if writer is not None and not writer.closed:
        writer.close()
    if retained_writer_fd is not None:
        os.close(retained_writer_fd)
        retained_writer_fd = None
    for drain in created_drains:
        drain._thread.join(timeout=1)

    settled_after_outer_writer = len(created_drains) == 1 and not created_drains[0]._thread.is_alive()
    assert type(caught) is ValueError and str(caught) == "primary run failure"
    notes = tuple(getattr(caught, "__notes__", ()))
    assert notes == ("launcher writer settlement failed: SettlementInterrupted",)
    assert "MUST NOT LEAK SETTLEMENT DETAIL" not in "\n".join(notes)
    assert production_closed_writer, "production left the parent write end open after cleanup interruption"
    assert production_pending_drain, "a retained child-style writer did not retain drain ownership"
    assert settled_after_outer_writer, "the drain did not settle after outer lifecycle ownership closed"
    assert traversals == [], "no syscall may enter a root whose writer settlement was interrupted"
    assert evidence.logs[runner._ENGINE_STDERR_EVIDENCE_NAME] == runner._UNSETTLED_CHILD_WRITER_LOG_REFUSAL_MARKER
    assert evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME] == runner._UNSETTLED_CHILD_WRITER_LOG_REFUSAL_MARKER
    assert "MUST NOT READ" not in "".join(evidence.logs.values())


@pytest.mark.parametrize(
    ("boundary", "expected_note"),
    (
        ("drain_finish", "launcher diagnostic capture failed: CleanupInterrupted"),
        ("launcher_publish", "launcher diagnostic capture failed: CleanupInterrupted"),
        ("engine_refusal", "engine stderr refusal capture failed: CleanupInterrupted"),
        ("assistant_refusal", "assistant log refusal capture failed: CleanupInterrupted"),
    ),
)
def test_post_settlement_baseexception_cannot_replace_primary(
    tmp_path: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    expected_note: str,
) -> None:
    """Every cleanup boundary after settlement preserves the original failure."""

    class SettlementInterrupted(BaseException):
        pass

    class CleanupInterrupted(BaseException):
        pass

    class BoundaryEvidence(_Evidence):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[str] = []

        def write_log(self, name: str, text: str) -> None:
            self.calls.append(name)
            target = {
                "engine_refusal": runner._ENGINE_STDERR_EVIDENCE_NAME,
                "assistant_refusal": runner._ASSISTANT_LOG_EVIDENCE_NAME,
            }.get(boundary)
            if name == target:
                raise CleanupInterrupted("MUST NOT LEAK CLEANUP DETAIL")
            super().write_log(name, text)

    if boundary == "drain_finish":

        class InterruptedDrain(runner._BoundedLauncherLogDrain):
            def finish(self) -> tuple[bytes, int]:
                super().finish()
                raise CleanupInterrupted("MUST NOT LEAK CLEANUP DETAIL")

        monkeypatch.setattr(runner, "_BoundedLauncherLogDrain", InterruptedDrain)
    elif boundary == "launcher_publish":

        def interrupt_launcher_publish(*_args: object, **_kwargs: object) -> None:
            raise CleanupInterrupted("MUST NOT LEAK CLEANUP DETAIL")

        monkeypatch.setattr(runner, "_publish_launcher_log", interrupt_launcher_publish)

    refusal_boundary = boundary in {"engine_refusal", "assistant_refusal"}

    def settle_writer() -> None:
        if refusal_boundary:
            raise SettlementInterrupted("MUST NOT LEAK SETTLEMENT DETAIL")

    evidence = BoundaryEvidence()
    caught: BaseException | None = None
    try:
        with runner._launcher_log_capture(
            evidence,
            tmp_path / f"launcher-{boundary}.txt",
            settle_writer=settle_writer,
            state_root=state_root if refusal_boundary else None,
        ) as writer:
            writer.write(b"launcher output\n")
            raise ValueError("primary run failure")
    except BaseException as error:
        caught = error

    assert type(caught) is ValueError and str(caught) == "primary run failure"
    notes = tuple(getattr(caught, "__notes__", ()))
    assert expected_note in notes
    assert "MUST NOT LEAK" not in "\n".join(notes)
    if refusal_boundary:
        assert evidence.calls == [
            runner._ENGINE_STDERR_EVIDENCE_NAME,
            runner._ASSISTANT_LOG_EVIDENCE_NAME,
        ]
        successful_name = (
            runner._ASSISTANT_LOG_EVIDENCE_NAME if boundary == "engine_refusal" else runner._ENGINE_STDERR_EVIDENCE_NAME
        )
        assert evidence.logs[successful_name] == runner._UNSETTLED_CHILD_WRITER_LOG_REFUSAL_MARKER


def test_cleanup_failure_accumulator_retains_first_without_primary_and_attempts_all() -> None:
    """No-primary teardown retains its first exact failure and sanitizes later failures."""

    class FirstCleanupFailure(BaseException):
        pass

    class SecondCleanupFailure(BaseException):
        pass

    calls: list[str] = []
    first = FirstCleanupFailure("FIRST CLEANUP SECRET DETAIL")
    second = SecondCleanupFailure("SECOND CLEANUP SECRET DETAIL")
    cleanup = runner._CleanupFailureAccumulator(primary=None)

    def fail_first() -> None:
        calls.append("first")
        raise first

    def fail_second() -> None:
        calls.append("second")
        raise second

    def finish_third() -> None:
        calls.append("third")

    assert not cleanup.attempt("first owner cleanup failed", fail_first)
    assert not cleanup.attempt("second owner cleanup failed", fail_second)
    assert cleanup.attempt("third owner cleanup failed", finish_third)

    with pytest.raises(FirstCleanupFailure) as caught:
        cleanup.raise_if_no_primary()

    assert calls == ["first", "second", "third"]
    assert caught.value is first
    assert type(caught.value) is FirstCleanupFailure
    assert str(caught.value) == "FIRST CLEANUP SECRET DETAIL"
    notes = tuple(getattr(caught.value, "__notes__", ()))
    assert notes == ("second owner cleanup failed: SecondCleanupFailure",)
    assert "FIRST CLEANUP SECRET DETAIL" not in "\n".join(notes)
    assert "SECOND CLEANUP SECRET DETAIL" not in "\n".join(notes)


def test_signal_mask_acquisition_failure_preserves_primary_and_attempts_all_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed mask enter is one accumulated failure, not a cleanup-wide gate."""

    class PrimaryFailure(BaseException):
        pass

    class MaskAcquisitionFailure(BaseException):
        pass

    primary = PrimaryFailure("PRIMARY SECRET")
    calls: list[str] = []

    class FailingMask:
        def __enter__(self) -> None:
            calls.append("mask_enter")
            raise MaskAcquisitionFailure("MASK SECRET")

        def __exit__(self, *_exc: object) -> bool:
            calls.append("mask_exit")
            return False

    class CloseOwner:
        def __init__(self, name: str) -> None:
            self._name = name

        def close(self) -> None:
            calls.append(self._name)

    class TemporaryOwner:
        def cleanup(self) -> None:
            calls.append("source_temporary")

    class SnapshotOwner:
        def __exit__(self, *_exc: object) -> bool:
            calls.append("source_snapshot")
            return False

    monkeypatch.setattr(runner, "_block_termination_signals", lambda: FailingMask())

    settled = runner._cleanup_owned_run(
        primary_info=(type(primary), primary, None),
        process=None,
        launcher_identity=None,
        launcher_settled=True,
        locked=object(),
        owner_identity=object(),
        sink=CloseOwner("sink"),
        artifact_pair=CloseOwner("artifact_pair"),
        bridge_pipe=CloseOwner("bridge_pipe"),
        source_temporary=TemporaryOwner(),
        source_snapshot_context=SnapshotOwner(),
    )

    assert settled
    assert calls == [
        "mask_enter",
        "sink",
        "artifact_pair",
        "bridge_pipe",
        "source_temporary",
        "source_snapshot",
    ]
    assert tuple(getattr(primary, "__notes__", ())) == (
        "termination signal mask acquisition failed: MaskAcquisitionFailure",
    )
    assert "MASK SECRET" not in "\n".join(primary.__notes__)


@pytest.mark.parametrize("earlier_cleanup_failure", (False, True))
def test_signal_mask_restoration_failure_obeys_no_primary_first_failure_order(
    monkeypatch: pytest.MonkeyPatch,
    earlier_cleanup_failure: bool,
) -> None:
    """Mask restoration is exact only when no earlier cleanup failure owns exit."""

    class FirstCleanupFailure(BaseException):
        pass

    class MaskRestorationFailure(BaseException):
        pass

    first = FirstCleanupFailure("FIRST CLEANUP SECRET")
    restoration = MaskRestorationFailure("MASK RESTORATION SECRET")
    calls: list[str] = []

    class FailingRestoreMask:
        def __enter__(self) -> None:
            calls.append("mask_enter")

        def __exit__(self, *_exc: object) -> bool:
            calls.append("mask_exit")
            raise restoration

    class Sink:
        def close(self) -> None:
            calls.append("sink")
            if earlier_cleanup_failure:
                raise first

    class SnapshotOwner:
        def __exit__(self, *_exc: object) -> bool:
            calls.append("source_snapshot")
            return False

    monkeypatch.setattr(runner, "_block_termination_signals", lambda: FailingRestoreMask())

    caught: BaseException | None = None
    try:
        runner._cleanup_owned_run(
            primary_info=(None, None, None),
            process=None,
            launcher_identity=None,
            launcher_settled=True,
            locked=object(),
            owner_identity=object(),
            sink=Sink(),
            artifact_pair=None,
            bridge_pipe=None,
            source_temporary=None,
            source_snapshot_context=SnapshotOwner(),
        )
    except BaseException as error:
        caught = error

    assert calls == ["mask_enter", "sink", "source_snapshot", "mask_exit"]
    if earlier_cleanup_failure:
        assert caught is first
        assert tuple(getattr(caught, "__notes__", ())) == (
            "termination signal mask restoration failed: MaskRestorationFailure",
        )
        assert "MASK RESTORATION SECRET" not in "\n".join(caught.__notes__)
    else:
        assert caught is restoration
        assert not getattr(caught, "__notes__", ())


def test_run_owned_no_primary_cleanup_attempts_all_and_retains_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive `_run_owned` with no active primary and exercise every cleanup owner."""

    test_run_owned_settles_session_before_state_root_cleanup_and_preserves_primary(
        tmp_path,
        monkeypatch,
        cleanup_boundary="no-primary",
        final_settlement_fails=False,
        no_primary=True,
    )


@pytest.mark.parametrize(
    ("cleanup_boundary", "final_settlement_fails", "no_primary"),
    (
        pytest.param("source-root", False, False, id="source-root"),
        pytest.param("final-settlement", True, False, id="final-settlement"),
        pytest.param("sink", False, False, id="sink"),
        pytest.param("artifact-pair", False, False, id="artifact-pair"),
        pytest.param("bridge-pipe", False, False, id="bridge-pipe"),
        pytest.param("snapshot-exit", False, False, id="snapshot-exit"),
    ),
)
def test_run_owned_settles_session_before_state_root_cleanup_and_preserves_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_boundary: str,
    final_settlement_fails: bool,
    no_primary: bool,
) -> None:
    """The real owner lifecycle must not tear down a root while its child can write."""

    from scripts import soak_mock_stack as soak

    class PrimaryFailure(ValueError):
        pass

    class SettlementInterrupted(BaseException):
        pass

    class CleanupInterrupted(BaseException):
        pass

    class BodyComplete(BaseException):
        pass

    class FirstCleanupFailure(BaseException):
        pass

    class LaterCleanupFailure(BaseException):
        pass

    first_cleanup_failure = FirstCleanupFailure("FIRST OWNER CLEANUP SECRET")
    child_writer = {"fd": None, "live": False}
    cleanup_saw_live_writer: list[bool] = []
    source_temporaries: list[ObservedTemporaryDirectory] = []
    cleanup_calls: list[str] = []
    snapshot_creations = 0
    settlement_calls: list[int] = []
    real_temporary_directory = runner.tempfile.TemporaryDirectory

    class ObservedTemporaryDirectory:
        def __init__(
            self,
            *,
            prefix: str,
            delete: bool = True,
            **kwargs: object,
        ) -> None:
            self._source = prefix == "cryodaq-source-soak-"
            self._delete = delete
            self._inner = real_temporary_directory(prefix=prefix, delete=False, **kwargs)
            if self._source:
                source_temporaries.append(self)

        def __enter__(self) -> str:
            return self._inner.__enter__()

        def __exit__(self, *_exc: object) -> bool:
            if self._source:
                if self._delete:
                    self.cleanup()
            else:
                self._inner.cleanup()
            return False

        def cleanup(self) -> None:
            if self._source:
                cleanup_calls.append("source_root")
                cleanup_saw_live_writer.append(child_writer["live"])
            self._inner.cleanup()
            if self._source and no_primary:
                raise LaterCleanupFailure("MUST NOT LEAK SOURCE ROOT DETAIL")
            if self._source and cleanup_boundary == "source-root":
                raise CleanupInterrupted("MUST NOT LEAK TEMP CLEANUP DETAIL")

    class StillSnapshot:
        root = tmp_path / "snapshot"
        interpreter = Path(runner.sys.executable)
        environment: dict[str, str] = {}

        def __init__(self) -> None:
            nonlocal snapshot_creations
            snapshot_creations += 1
            self._source = snapshot_creations == 2

        def __enter__(self) -> StillSnapshot:
            self.root.mkdir(exist_ok=True)
            return self

        def __exit__(self, *_exc: object) -> bool:
            if self._source:
                cleanup_calls.append("snapshot_exit")
                if no_primary:
                    raise LaterCleanupFailure("MUST NOT LEAK SNAPSHOT DETAIL")
                if cleanup_boundary == "snapshot-exit":
                    raise CleanupInterrupted("MUST NOT LEAK SNAPSHOT EXIT DETAIL")
            return False

    @contextmanager
    def still_snapshot(_sha: str):
        snapshot = StillSnapshot()
        with snapshot:
            yield snapshot

    fixture_payload = {"schema": "test-source-fixture"}

    class StillSeal:
        payload = fixture_payload

    def materialize(config_dir: Path, **_kwargs: object) -> int:
        config_dir.mkdir(parents=True, exist_ok=True)
        return 1

    class OwnerObserver:
        def __init__(self, _module: object) -> None:
            pass

        def identity_for_pid(self, pid: int) -> tuple[str, int]:
            return ("owner", pid)

        def descendants(self, _owner: object, *, include_zombies: bool = False) -> tuple[()]:
            assert include_zombies
            return ()

    class BroadObserver:
        def __init__(self, _module: object) -> None:
            pass

        def snapshot(self) -> tuple[()]:
            return ()

    class Collector:
        def __init__(self, _root: Path) -> None:
            pass

        def observe(self, _boundary: object) -> None:
            pass

    class ExactSix:
        def execute(self, _evidence: object, *, collector: object) -> dict[str, object]:
            assert isinstance(collector, Collector)
            return {"command": ["exact-six"], "git_sha": "a" * 40, "exit_code": 0, "status": "passed"}

    class Evidence(_Evidence):
        def __init__(self) -> None:
            super().__init__()
            self.directory = tmp_path / "evidence"
            self.directory.mkdir()

        def write_manifest(self, _payload: dict[str, object]) -> None:
            pass

        def write_prerequisites(self, _payload: dict[str, object]) -> None:
            pass

        def begin_run(self) -> None:
            pass

        def _sha256(self, _name: str) -> str:
            return "b" * 64

    class BridgePipe:
        nonce = "bridge-nonce"

        @classmethod
        def create(cls) -> BridgePipe:
            return cls()

        def child_environment(self) -> dict[str, str]:
            return {}

        def child_pass_fds(self) -> tuple[()]:
            return ()

        def close_parent_write_end(self) -> None:
            if no_primary:
                raise BodyComplete
            raise PrimaryFailure("primary production failure")

        def close(self) -> None:
            cleanup_calls.append("bridge_pipe")
            if no_primary:
                raise LaterCleanupFailure("MUST NOT LEAK BRIDGE CLOSE DETAIL")
            if cleanup_boundary == "bridge-pipe":
                raise CleanupInterrupted("MUST NOT LEAK BRIDGE CLOSE DETAIL")

    class ArtifactPair:
        runner = object()
        nonce = "artifact-nonce"

        @classmethod
        def create(cls) -> ArtifactPair:
            return cls()

        def child_environment(self) -> dict[str, str]:
            return {}

        def child_pass_fds(self) -> tuple[()]:
            return ()

        def close_launcher_end(self) -> None:
            pass

        def close(self) -> None:
            cleanup_calls.append("artifact_pair")
            if no_primary:
                raise LaterCleanupFailure("MUST NOT LEAK ARTIFACT CLOSE DETAIL")
            if cleanup_boundary == "artifact-pair":
                raise CleanupInterrupted("MUST NOT LEAK ARTIFACT CLOSE DETAIL")

    class Sink:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def close(self) -> None:
            cleanup_calls.append("sink")
            if no_primary:
                raise first_cleanup_failure
            if cleanup_boundary == "sink":
                raise CleanupInterrupted("MUST NOT LEAK SINK CLOSE DETAIL")

    process = SimpleNamespace(pid=424242, returncode=None)
    identity = SimpleNamespace(start_identity="pid=424242")

    def spawn_source(*, stdout: object, **_kwargs: object) -> tuple[object, object]:
        child_writer["fd"] = os.dup(stdout.fileno())  # type: ignore[attr-defined]
        child_writer["live"] = True
        return process, identity

    def force_settle(*_args: object, **_kwargs: object) -> None:
        settlement_calls.append(len(settlement_calls) + 1)
        if not no_primary and (len(settlement_calls) == 1 or final_settlement_fails):
            raise SettlementInterrupted("MUST NOT LEAK FINAL SETTLEMENT DETAIL")
        descriptor = child_writer["fd"]
        assert isinstance(descriptor, int)
        os.close(descriptor)
        child_writer["fd"] = None
        child_writer["live"] = False
        process.returncode = 1

    monkeypatch.setattr(runner.tempfile, "TemporaryDirectory", ObservedTemporaryDirectory)
    monkeypatch.setattr(runner, "_sealed_execution_snapshot", still_snapshot)
    monkeypatch.setattr(runner, "_materialize_complete_soak_config", materialize)
    monkeypatch.setattr(runner, "_source_fixture_seal", lambda *_args, **_kwargs: StillSeal())
    monkeypatch.setattr(runner, "_LockedPsutilObserver", OwnerObserver)
    monkeypatch.setattr(soak, "PsutilObserver", BroadObserver)
    monkeypatch.setattr(runner, "_CleanShaCollector", Collector)
    monkeypatch.setattr(runner, "_select_short_soak_report_schedule", lambda _now: (600, 500))
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="a" * 40),
    )
    monkeypatch.setattr(runner, "_EXACT_SIX_EXECUTIONS", ExactSix())
    monkeypatch.setattr(runner, "_BridgeHandshakePipe", BridgePipe)
    monkeypatch.setattr(runner, "_ArtifactCapabilityPair", ArtifactPair)
    monkeypatch.setattr(runner, "_ArtifactReceiptSink", Sink)
    monkeypatch.setattr(runner, "_source_environment", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(runner, "_spawn_gated_source", spawn_source)
    monkeypatch.setattr(runner, "_force_settle_owned_session", force_settle)
    monkeypatch.setattr(runner, "_block_termination_signals", nullcontext)
    if no_primary:

        @contextmanager
        def body_completion_capture(*_args: object, **_kwargs: object):
            with runner.tempfile.TemporaryFile(mode="w+b") as log:
                try:
                    yield log
                except BodyComplete:
                    # Suppression completes `_run_owned`'s body with no active exception;
                    # its REAL finally block must now run the no-primary cleanup path.
                    pass

        monkeypatch.setattr(runner, "_launcher_log_capture", body_completion_capture)

    caught: BaseException | None = None
    try:
        runner._PosixSoakRunner()._run_owned(Evidence(), soak.profile("short"))
    except BaseException as error:
        caught = error
    finally:
        descriptor = child_writer["fd"]
        if isinstance(descriptor, int):
            os.close(descriptor)
            child_writer["fd"] = None
            child_writer["live"] = False
        for source_temporary in source_temporaries:
            source_temporary._inner.cleanup()

    if no_primary:
        assert caught is first_cleanup_failure
        assert cleanup_saw_live_writer == [False]
        assert cleanup_calls == ["sink", "artifact_pair", "bridge_pipe", "source_root", "snapshot_exit"]
        assert settlement_calls == [1]
        notes = tuple(getattr(caught, "__notes__", ()))
        assert notes == (
            "artifact capability pair cleanup failed: LaterCleanupFailure",
            "bridge handshake pipe cleanup failed: LaterCleanupFailure",
            "source temporary cleanup failed: LaterCleanupFailure",
            "source snapshot cleanup failed: LaterCleanupFailure",
        )
        assert "MUST NOT LEAK" not in "\n".join(notes)
        assert "FIRST OWNER CLEANUP SECRET" not in "\n".join(notes)
        return

    assert type(caught) is PrimaryFailure and str(caught) == "primary production failure"
    expected_cleanup_observations = [] if final_settlement_fails else [False]
    assert cleanup_saw_live_writer == expected_cleanup_observations, (
        "state-root cleanup ran before the retained writer settled"
    )
    expected_cleanup_calls = ["sink", "artifact_pair", "bridge_pipe"]
    if not final_settlement_fails:
        expected_cleanup_calls.append("source_root")
    expected_cleanup_calls.append("snapshot_exit")
    assert cleanup_calls == expected_cleanup_calls, "every eligible owner must receive one close attempt"
    assert settlement_calls == [1, 2]
    notes = tuple(getattr(caught, "__notes__", ()))
    assert "launcher writer settlement failed: SettlementInterrupted" in notes
    if final_settlement_fails:
        assert "final launcher settlement failed: SettlementInterrupted" in notes
        assert not any(note.startswith("source temporary cleanup failed:") for note in notes)
    elif cleanup_boundary == "source-root":
        assert "source temporary cleanup failed: CleanupInterrupted" in notes
    else:
        expected_subject = {
            "sink": "artifact receipt sink cleanup failed",
            "artifact-pair": "artifact capability pair cleanup failed",
            "bridge-pipe": "bridge handshake pipe cleanup failed",
            "snapshot-exit": "source snapshot cleanup failed",
        }[cleanup_boundary]
        assert f"{expected_subject}: CleanupInterrupted" in notes
        assert not any(note.startswith("source temporary cleanup failed:") for note in notes)
    assert "MUST NOT LEAK" not in "\n".join(notes)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction ABA contract")
def test_unsettled_writer_cannot_publish_a_junction_aba_stream(
    tmp_path: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Observe the forbidden effect: external bytes must not enter retained evidence.

    Before the fix, the failed settlement still entered the publisher. The wrappers
    below then perform a real Windows junction ABA: selection is made in the original
    directory, the read resolves through an external junction, and the original
    directory is restored before the publisher's after-check. That exact production
    path published the external stream while both directory identities compared equal.
    """

    import _winapi

    logs = state_root / "logs"
    (logs / "assistant.log").write_bytes(b"INTERNAL LOG\n")
    saved_logs = state_root / "logs-saved"
    external = tmp_path / "external-logs"
    external.mkdir()
    secret = b"EXTERNAL JUNCTION ABA STREAM MUST NOT PUBLISH\n"
    (external / "assistant.log").write_bytes(secret)

    real_files = runner._assistant_log_files
    real_read = runner._read_regular_file_no_follow

    def select_then_swap(root: Path):
        selected = real_files(root)
        logs.rename(saved_logs)
        _winapi.CreateJunction(str(external), str(logs))
        return selected

    def read_then_restore(directory_descriptor: int | None, path: Path | str, *, maximum_bytes: int):
        result = real_read(directory_descriptor, path, maximum_bytes=maximum_bytes)
        os.rmdir(logs)
        saved_logs.rename(logs)
        return result

    monkeypatch.setattr(runner, "_assistant_log_files", select_then_swap)
    monkeypatch.setattr(runner, "_read_regular_file_no_follow", read_then_restore)
    evidence = _Evidence()

    def fail_settlement() -> None:
        raise RuntimeError("owned writer did not settle")

    with pytest.raises(ValueError, match="primary"):
        with runner._launcher_log_capture(
            evidence,
            tmp_path / "launcher-aba.txt",
            settle_writer=fail_settlement,
            state_root=state_root,
        ):
            raise ValueError("primary")

    assert secret.decode("ascii").strip() not in "".join(evidence.logs.values())
    assert evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME] == runner._UNSETTLED_CHILD_WRITER_LOG_REFUSAL_MARKER


@pytest.mark.skipif(os.name != "nt", reason="Windows pathname open identity contract")
def test_windows_leaf_open_must_match_the_enumerated_file(
    state_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The descriptor must name the same file that the pre-open lstat measured."""

    internal = state_root / "logs" / "assistant.log"
    internal.write_bytes(b"INTERNAL LOG\n")
    external = tmp_path / "external-secret.log"
    secret = b"EXTERNAL LEAF ABA STREAM MUST NOT PUBLISH\n"
    external.write_bytes(secret)
    real_open = runner.os.open

    def redirect_leaf_open(path: object, flags: int, **kwargs: object) -> int:
        if Path(path) == internal:
            return real_open(external, flags)
        return real_open(path, flags, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runner.os, "open", redirect_leaf_open)
    evidence = _Evidence()

    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert secret.decode("ascii").strip() not in published
    assert published == runner._ASSISTANT_LOG_REPLACED_OR_UNREADABLE_MARKER


def test_a_rotated_day_is_not_left_behind(state_root: Path) -> None:
    """`setup_logging` rotates the assistant log daily and keeps dated backups.

    On a multi-day run the decisive line is written on the day it happened and often
    never repeats. Reading only the active file retains the last day and deletes the
    cause -- the same evidence loss this publisher exists to stop, one layer down.
    """

    logs = state_root / "logs"
    (logs / "assistant.log.2026-08-14").write_bytes(b"THE CAUSE, written on day one\n")
    (logs / "assistant.log.2026-08-17").write_bytes(b"a quiet middle day\n")
    (logs / "assistant.log").write_bytes(b"the last day, which says nothing\n")

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "THE CAUSE, written on day one" in published, "the rotated day was dropped"
    assert "the last day" in published


def test_the_rotated_stream_is_ordered_oldest_first(state_root: Path) -> None:
    """The bound keeps the END, so the newest must be last or the bound drops the wrong half."""

    logs = state_root / "logs"
    (logs / "assistant.log.2026-08-14").write_bytes(b"FIRST\n")
    (logs / "assistant.log").write_bytes(b"LAST\n")

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert published.index("FIRST") < published.index("LAST")


def test_rotated_log_reads_never_exceed_the_global_retained_tail(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the publisher over two rotated files, observing its real descriptor reads."""

    logs = state_root / "logs"
    oldest_line = b"OLDEST-" + b"x" * 100 + b"\n"
    (logs / "assistant.log.2026-08-14").write_bytes(oldest_line * (runner._MAX_LAUNCHER_LOG_BYTES // len(oldest_line)))
    newest_line = b"y" * 100 + b"\n"
    (logs / "assistant.log").write_bytes(
        newest_line * (runner._MAX_LAUNCHER_LOG_BYTES // len(newest_line)) + b"NEWEST-ACTIVE-CONTENT\n"
    )
    original = runner._read_regular_file_no_follow
    requested: list[int] = []

    def observe(directory_descriptor: int | None, path: Path | str, *, maximum_bytes: int):
        result = original(directory_descriptor, path, maximum_bytes=maximum_bytes)
        if result is not None:
            requested.append(len(result[0]))
        return result

    monkeypatch.setattr(runner, "_read_regular_file_no_follow", observe)
    evidence = _Evidence()

    runner._publish_assistant_log(evidence, state_root)

    assert sum(requested) <= runner._MAX_LAUNCHER_LOG_BYTES
    assert "NEWEST-ACTIVE-CONTENT" in evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]


def test_a_refusal_notice_survives_active_log_truncation(state_root: Path, tmp_path: Path) -> None:
    """A bounded payload must retain the warning that another enumerated log was refused.

    The active filler is line-based, like a real assistant log, because a tail that
    begins inside a record is discarded whole rather than published half-identified.
    """

    import os

    secret = tmp_path / "not-for-the-bundle.txt"
    secret.write_bytes(b"HARD-LINKED SECRET\n")
    os.link(secret, state_root / "logs" / "assistant.log.2026-08-14")
    filler = b"x" * 100 + b"\n"
    (state_root / "logs" / "assistant.log").write_bytes(
        filler * (runner._MAX_LAUNCHER_LOG_BYTES // len(filler)) + b"ACTIVE LOG END\n"
    )
    evidence = _Evidence()

    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "HARD-LINKED SECRET" not in published
    assert runner._ASSISTANT_LOG_REFUSED_MARKER not in published, (
        "the hard link must be named by its own truthful reason, not the symlink text"
    )
    assert "st_nlink != 1" in published
    assert runner._TRUNCATED_LAUNCHER_LOG_MARKER.decode("utf-8") in published
    assert "ACTIVE LOG END" in published


def test_a_symbolic_link_is_refused_rather_than_followed(state_root: Path, tmp_path: Path) -> None:
    """The measured process can write that directory, so its topology is not trusted.

    Replacing the log with a link to any runner-readable file would otherwise copy that
    file into the retained bundle.
    """

    import os

    secret = tmp_path / "not-for-the-bundle.txt"
    secret.write_bytes(b"SOMETHING THE BUNDLE MUST NOT CARRY\n")
    link = state_root / "logs" / "assistant.log"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):  # pragma: no cover - unprivileged Windows
        pytest.skip("this platform does not allow creating a symbolic link here")

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "SOMETHING THE BUNDLE MUST NOT CARRY" not in published
    assert published == runner._ASSISTANT_LOG_REFUSED_MARKER, (
        "a refused path must SAY it was refused, or it reads as an absent log"
    )


def test_a_hard_link_is_refused_rather_than_copied(state_root: Path, tmp_path: Path) -> None:
    """A hard link has no unsafe pathname component, so the descriptor must reject it."""

    import os

    secret = tmp_path / "not-for-the-bundle.txt"
    secret.write_bytes(b"HARD-LINKED SECRET\n")
    os.link(secret, state_root / "logs" / "assistant.log")

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "HARD-LINKED SECRET" not in published
    assert runner._ASSISTANT_LOG_REFUSED_MARKER not in published, (
        "a hard link is not a symbolic link; the generic symlink text would claim a condition nobody observed"
    )
    assert "st_nlink != 1" in published, "the refusal must name the hard-linked reason it actually hit"


def test_a_linked_logs_directory_is_refused_rather_than_traversed(state_root: Path, tmp_path: Path) -> None:
    """The directory is child-writable too, so validating only a final leaf is insufficient."""

    import os

    external = tmp_path / "external-logs"
    external.mkdir()
    (external / "assistant.log").write_bytes(b"OUTSIDE THE ISOLATED ROOT\n")
    logs = state_root / "logs"
    logs.rmdir()
    try:
        os.symlink(external, logs, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - unprivileged Windows
        pytest.skip("this platform does not allow creating a directory symbolic link here")

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "OUTSIDE THE ISOLATED ROOT" not in published
    assert runner._ASSISTANT_LOG_REFUSED_MARKER not in published, (
        "the logs DIRECTORY was refused, not a log leaf; the symlink-leaf text would misname it"
    )
    assert "logs directory" in published


def test_directory_open_failure_is_refused_without_pathname_fallback(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed descriptor open must not restore child-controlled pathname traversal."""

    (state_root / "logs" / "assistant.log").write_bytes(b"MUST NOT BE READ AFTER OPEN FAILURE\n")

    def refuse_directory_access(*_args: object, **_kwargs: object) -> int:
        raise OSError("simulated directory-open failure")

    # Patch what production CALLS. The enumeration moved from `os.listdir` to
    # `os.scandir` in this change, and this guard kept patching `listdir`: it intercepted
    # nothing, the enumeration succeeded, and the log content was published even though
    # the test believed it had simulated a directory-open failure. A guard that cannot
    # reach the production call proves nothing.
    if os.name == "nt":
        monkeypatch.setattr(runner.os, "scandir", refuse_directory_access)
    else:
        monkeypatch.setattr(runner.os, "open", refuse_directory_access)
    evidence = _Evidence()

    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "MUST NOT BE READ AFTER OPEN FAILURE" not in published
    assert runner._ASSISTANT_LOG_REFUSED_MARKER not in published, "an open failure is not an observed symbolic link"
    assert "logs directory" in published


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
def test_a_junction_logs_directory_is_refused_rather_than_traversed(state_root: Path, tmp_path: Path) -> None:
    """A Windows junction is not a symlink but can redirect the child-controlled directory."""

    import _winapi

    external = tmp_path / "external-logs"
    external.mkdir()
    (external / "assistant.log").write_bytes(b"OUTSIDE THE ISOLATED ROOT THROUGH JUNCTION\n")
    logs = state_root / "logs"
    logs.rmdir()
    _winapi.CreateJunction(str(external), str(logs))
    assert os.path.isjunction(logs)

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "OUTSIDE THE ISOLATED ROOT THROUGH JUNCTION" not in published
    assert runner._ASSISTANT_LOG_REFUSED_MARKER not in published
    assert "logs directory" in published


def test_pathname_log_traversal_selection_is_patchable_without_changing_os() -> None:
    """The Windows branch must be selectable without creating a hybrid process."""

    assert runner._assistant_log_uses_pathname_traversal(platform="nt")
    assert not runner._assistant_log_uses_pathname_traversal(platform="posix")


def test_a_logs_directory_swapped_during_the_read_is_refused_not_published(monkeypatch, tmp_path) -> None:
    """Where the read cannot be anchored, prove afterwards that nothing was swapped.

    Review found the hole and it is real: without descriptor-relative open, a child of the
    measured run can replace `logs` between the moment it is validated and the moment a
    leaf is read. That window cannot be closed on such a platform. What can be done is to
    notice, and to publish nothing rather than a stream that may have come from elsewhere.
    """

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "assistant.log").write_text("lost authority: out of sequence\n", encoding="utf-8")

    monkeypatch.setattr(runner, "_assistant_log_uses_pathname_traversal", lambda: True)
    identities = iter([(1, 111), (1, 222)])
    monkeypatch.setattr(runner, "_directory_identity", lambda _directory: next(identities))

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, tmp_path)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert published == runner._ASSISTANT_LOG_REPLACED_MARKER
    assert "lost authority" not in published, "a read from a swapped directory must not be published"


def test_an_unchanged_logs_directory_still_publishes(monkeypatch, tmp_path) -> None:
    """The proof must not refuse the ordinary case, or it has only broken the publisher."""

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "assistant.log").write_text("lost authority: out of sequence\n", encoding="utf-8")

    monkeypatch.setattr(runner, "_assistant_log_uses_pathname_traversal", lambda: True)
    monkeypatch.setattr(runner, "_directory_identity", lambda _directory: (1, 111))

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, tmp_path)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "lost authority" in published
    assert published != runner._ASSISTANT_LOG_REPLACED_MARKER


def _log_cut_inside_last_bytes(record: bytes, *, suffix_kept: int, bound: int) -> bytes:
    """A log whose retained-tail cutoff lands exactly ``suffix_kept`` bytes before the
    record's end -- so the identifying prefix of any secret inside it is DISCARDED by the
    bounded read before the redactor ever sees the bytes.

    ``bound`` must be the publisher's byte budget for THIS file's read.
    """

    end = b"\nEND-MARKER\n"
    padding = bound - suffix_kept - len(end)
    assert padding >= 0, "bound too small for the requested split"
    return b"f" * 64 + record + b"a" * padding + end


def test_a_directory_holding_the_leaf_name_is_refused_as_not_regular(state_root: Path) -> None:
    """A non-regular LEAF is its own condition and must not wear the symlink wording."""

    (state_root / "logs" / "assistant.log").mkdir()

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert runner._ASSISTANT_LOG_REFUSED_MARKER not in published, (
        "nothing observed here was a symbolic link; that text claims a condition nobody saw"
    )
    assert "directory, reparse point, device, or fifo" in published


def test_a_leaf_that_vanishes_mid_walk_is_named_as_replaced_or_unreadable(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A topology race between existence and open is not an observed symbolic link."""

    (state_root / "logs" / "assistant.log").write_bytes(b"GONE BEFORE THE OPEN\n")
    real_open = os.open

    def race_leaf_open(path: object, flags: int, **kwargs: object) -> int:
        if str(path).endswith("assistant.log"):
            raise OSError(errno.ENOENT, "raced away between lstat and open", str(path))
        return real_open(path, flags, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runner.os, "open", race_leaf_open)

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "GONE BEFORE THE OPEN" not in published
    assert runner._ASSISTANT_LOG_REFUSED_MARKER not in published
    assert "removed, replaced, or made unreadable" in published


def test_an_unreadable_regular_file_is_reported_as_opened_but_unreadable(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An I/O failure AFTER a clean open is yet another truth, not the symlink text."""

    (state_root / "logs" / "assistant.log").write_bytes(b"UNREADABLE BUT REAL\n")

    def explode_fdopen(*_args: object, **_kwargs: object) -> int:
        raise OSError("simulated read failure after open")

    monkeypatch.setattr(runner.os, "fdopen", explode_fdopen)

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "UNREADABLE BUT REAL" not in published
    assert runner._ASSISTANT_LOG_REFUSED_MARKER not in published
    # Bound to the marker CONSTANT, not to a hand-typed phrase from it. A substring test
    # here says the wording is right; equality says the right marker was chosen, which is
    # the property -- and it cannot drift out of step with the production text the way the
    # phrase "could not be read" already had.
    assert published == runner._ASSISTANT_LOG_OPENED_BUT_UNREADABLE_MARKER


@pytest.mark.parametrize(
    ("case", "record", "needle"),
    [
        (
            "bearer",
            b"Authorization: Bearer " + b"k" * 70 + b"leakme017Ab\n",
            b"leakme017Ab",
        ),
        (
            "query",
            b"GET https://api.example.test/v1?token=" + b"k" * 70 + b"leakme018Cd&x=1\n",
            b"leakme018Cd",
        ),
        (
            "assignment-equals",
            b"password = " + b"k" * 70 + b"leakme019Eg\n",
            b"leakme019Eg",
        ),
        (
            "assignment-colon",
            b"api_key: " + b"k" * 70 + b"leakme020Fj\n",
            b"leakme020Fj",
        ),
        (
            "bot-token",
            b"Bot token 123456789:AAH" + b"B" * 70 + b"leakme021Gk sent\n",
            b"leakme021Gk",
        ),
    ],
)
def test_a_tail_cutoff_inside_a_secret_cannot_publish_the_unidentifiable_half(
    state_root: Path, monkeypatch: pytest.MonkeyPatch, case: str, record: bytes, needle: bytes
) -> None:
    """The bounded read must never start mid-record.

    The redactor can only recognize a secret whose identifying prefix it sees. A tail
    slice beginning inside ``Authorization: Bearer ...`` leaves the bare credential in
    the bundle while every detector stays green, because the keyword went over the
    cutoff. So each truncated read is aligned to the next record boundary first, and a
    record too long to align within the budget is discarded whole instead of guessed.
    """

    del case  # only the record shape matters here
    bound = 2048
    monkeypatch.setattr(runner, "_MAX_LAUNCHER_LOG_BYTES", bound)
    # The cutoff lands 70 bytes before the needle -- deep inside the value, far past the
    # identifying prefix AND past the truncation marker's own re-trim of the slice front.
    cutoff_gap = 70
    suffix_kept = 1 + len(needle) + cutoff_gap  # newline + needle + the gap the leak needs
    (state_root / "logs" / "assistant.log").write_bytes(
        _log_cut_inside_last_bytes(record, suffix_kept=suffix_kept, bound=bound)
    )

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert needle.decode("ascii") not in published, (
        "a secret suffix whose prefix was cut off sailed past the redactor into the bundle"
    )
    assert "END-MARKER" in published, "complete records after the cutoff must still be retained"
    assert len(published.encode("utf-8")) <= bound
    assert published.startswith(runner._TRUNCATED_LAUNCHER_LOG_MARKER.decode("utf-8"))


def test_a_rotated_file_cutoff_is_aligned_too(state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every per-file read boundary gets the same alignment, not just the active one."""

    bound = 2048
    monkeypatch.setattr(runner, "_MAX_LAUNCHER_LOG_BYTES", bound)
    active = b"NEWEST-ACTIVE\n"
    (state_root / "logs" / "assistant.log").write_bytes(active)
    record = b"Authorization: Bearer " + b"k" * 70 + b"rotatedleak022Zm\n"
    (state_root / "logs" / "assistant.log.2026-08-14").write_bytes(
        _log_cut_inside_last_bytes(record, suffix_kept=1 + len(b"rotatedleak022Zm") + 70, bound=bound - len(active))
    )

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "rotatedleak022Zm" not in published
    assert "NEWEST-ACTIVE" in published
    assert "END-MARKER" in published


def test_a_record_longer_than_the_budget_is_discarded_whole_and_said(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When alignment cannot prove where the safe boundary is, nothing is guessed.

    A tail with no line break anywhere inside it could carry the undetectable half of a
    credential, so it is withheld -- audibly, not silently.
    """

    bound = 512
    monkeypatch.setattr(runner, "_MAX_LAUNCHER_LOG_BYTES", bound)
    (state_root / "logs" / "assistant.log").write_bytes(b"x" * 600)

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "xxxx" not in published, "an unalignable record must not ship half-cut"
    assert "no complete following record" in published
    assert published != runner._ASSISTANT_LOG_ABSENT_MARKER, "the log existed; absent would be a lie"


def test_an_oversized_newline_terminated_record_is_not_absent_at_the_production_bound(
    state_root: Path,
) -> None:
    """A final newline is not evidence that a complete retained record exists after it."""

    bound = runner._MAX_LAUNCHER_LOG_BYTES
    record_prefix = b"OVERSIZED-RECORD-MUST-NOT-PUBLISH:"
    source = state_root / "logs" / "assistant.log"
    source.write_bytes(record_prefix + b"x" * (bound - len(record_prefix)) + b"\n")
    assert source.stat().st_size == bound + 1

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert published == runner._ASSISTANT_LOG_RECORD_SPANS_BOUNDARY_MARKER
    assert record_prefix.decode("ascii") not in published
    assert published != runner._ASSISTANT_LOG_ABSENT_MARKER


def test_the_full_production_bound_also_aligns_before_redaction(state_root: Path) -> None:
    """The same geometry at the REAL 8 MiB production bound, not a shrunk stand-in."""

    bound = runner._MAX_LAUNCHER_LOG_BYTES
    (state_root / "logs" / "assistant.log").write_bytes(
        _log_cut_inside_last_bytes(
            b"Authorization: Bearer " + b"k" * 70 + b"fullsizeleak023Zn\n",
            suffix_kept=1 + len(b"fullsizeleak023Zn") + 70,
            bound=bound,
        )
    )

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "fullsizeleak023Zn" not in published
    assert "END-MARKER" in published
    assert len(published.encode("utf-8")) <= bound


def test_rotated_log_enumeration_streams_exact_dated_names_only(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child-created lookalike must not displace a genuine dated rotation."""

    logs = state_root / "logs"
    (logs / "assistant.log.2026-08-14").write_bytes(b"DATED BACKUP\n")
    (logs / "assistant.log.zzzz").write_bytes(b"LOOKALIKE MUST NOT PUBLISH\n")
    (logs / "assistant.log.2026-8-14").write_bytes(b"NONCANONICAL MUST NOT PUBLISH\n")
    (logs / "assistant.log").write_bytes(b"ACTIVE\n")

    def listdir_must_not_run(*_args: object, **_kwargs: object) -> list[str]:
        raise AssertionError("rotated-log enumeration must stream with scandir")

    monkeypatch.setattr(runner.os, "listdir", listdir_must_not_run)
    evidence = _Evidence()

    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "DATED BACKUP" in published
    assert "ACTIVE" in published
    assert "LOOKALIKE MUST NOT PUBLISH" not in published
    assert "NONCANONICAL MUST NOT PUBLISH" not in published


def test_too_many_rotated_logs_refuse_the_child_writable_directory(state_root: Path) -> None:
    """More than retention plus one interrupted-rollover residue must refuse."""

    logs = state_root / "logs"
    for day in range(1, ASSISTANT_LOG_BACKUP_COUNT + 3):
        (logs / f"assistant.log.2026-08-{day:02d}").write_bytes(b"MUST NOT PUBLISH\n")
    (logs / "assistant.log").write_bytes(b"ACTIVE MUST NOT PUBLISH\n")
    evidence = _Evidence()

    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "could not be opened" not in published
    assert published == runner._ASSISTANT_LOG_ROTATION_CEILING_MARKER


def test_more_nonmatching_entries_than_the_enumeration_ceiling_refuse_the_directory(
    state_root: Path,
) -> None:
    """Unrelated names alone must exhaust the total enumeration ceiling.

    The child-writable logs directory can hold arbitrarily many entries the rotation
    regex never matches. An enumeration that counts only MATCHING candidates walks all
    of them without a total-work bound and delays retention of log-assistant.txt behind
    that traversal, so the ceiling must count every entry and refuse closed.
    """

    logs = state_root / "logs"
    for index in range(257):
        (logs / f"unrelated-noise-{index:04d}.bin").write_bytes(b"MUST NOT PUBLISH\n")
    (logs / "assistant.log").write_bytes(b"ACTIVE MUST NOT PUBLISH\n")

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "MUST NOT PUBLISH" not in published, (
        "an over-ceiling directory was read anyway; enumeration still counted only matching names"
    )
    assert "could not be opened" not in published
    assert published == runner._ASSISTANT_LOG_DIRECTORY_ENTRY_CEILING_MARKER


def test_an_ordinary_logs_directory_with_noise_still_publishes(state_root: Path) -> None:
    """Bounded rotations beside unrelated names remain publishable."""

    logs = state_root / "logs"
    (logs / "assistant.log.2026-08-14").write_bytes(b"THE CAUSE, written on day one\n")
    (logs / "engine.stderr.log").write_bytes(b"a differently named run artifact\n")
    (logs / "unrelated-noise.bin").write_bytes(b"NOISE\n")
    (logs / "assistant.log").write_bytes(b"the last day\n")

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "THE CAUSE, written on day one" in published
    assert "the last day" in published
    assert published.index("THE CAUSE") < published.index("the last day")


def test_a_directory_at_exactly_the_enumeration_ceiling_still_publishes(
    state_root: Path,
) -> None:
    """Fail-closed fires when the ceiling is EXCEEDED, not when it is reached.

    Filling the directory to exactly ``_MAX_ASSISTANT_LOG_DIRECTORY_ENTRIES`` mixed
    entries pins the boundary from the safe side: an implementation that refuses at
    equality would break ordinary retention without any hostile directory present.
    """

    assert runner._MAX_ASSISTANT_LOG_DIRECTORY_ENTRIES == 256

    logs = state_root / "logs"
    for index in range(runner._MAX_ASSISTANT_LOG_DIRECTORY_ENTRIES - 2):
        (logs / f"unrelated-noise-{index:04d}.bin").write_bytes(b"NOISE\n")
    (logs / "assistant.log.2026-08-14").write_bytes(b"THE CAUSE, written on day one\n")
    (logs / "assistant.log").write_bytes(b"the last day\n")
    total_entries = len(list(logs.iterdir()))
    assert total_entries == runner._MAX_ASSISTANT_LOG_DIRECTORY_ENTRIES

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "THE CAUSE, written on day one" in published
    assert "the last day" in published
