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
from pathlib import Path

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


def test_settlement_baseexception_preserves_primary_closes_drain_and_refuses_root(
    tmp_path: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup interruption cannot mask the run failure or leave evidence ownership live."""

    (state_root / "logs" / "engine.stderr.log").write_bytes(b"MUST NOT READ ENGINE STDERR\n")
    (state_root / "logs" / "assistant.log").write_bytes(b"MUST NOT READ ASSISTANT LOG\n")
    traversals: list[str] = []

    def under_state_root(value: object) -> bool:
        return isinstance(value, (str, os.PathLike)) and Path(value).is_relative_to(state_root)

    real_read_bytes = Path.read_bytes
    real_lstat = runner.os.lstat
    real_stat = runner.os.stat
    real_open = runner.os.open
    real_scandir = runner.os.scandir

    def guarded_read_bytes(path: Path) -> bytes:
        if under_state_root(path):
            traversals.append(f"read_bytes:{path}")
            raise AssertionError("the unsettled child-writable root was read")
        return real_read_bytes(path)

    def guarded_lstat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if under_state_root(path):
            traversals.append(f"lstat:{path}")
            raise AssertionError("the unsettled child-writable root was measured")
        return real_lstat(path, *args, **kwargs)  # type: ignore[arg-type]

    def guarded_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if under_state_root(path):
            traversals.append(f"stat:{path}")
            raise AssertionError("the unsettled child-writable root was measured")
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    def guarded_open(path: object, *args: object, **kwargs: object) -> int:
        if under_state_root(path):
            traversals.append(f"open:{path}")
            raise AssertionError("the unsettled child-writable root was opened")
        return real_open(path, *args, **kwargs)  # type: ignore[arg-type]

    def guarded_scandir(path: object):
        if under_state_root(path):
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
    caught: BaseException | None = None

    def interrupt_settlement() -> None:
        raise SettlementInterrupted("MUST NOT LEAK SETTLEMENT DETAIL")

    try:
        with runner._launcher_log_capture(
            evidence,
            tmp_path / "launcher-baseexception.txt",
            settle_writer=interrupt_settlement,
            state_root=state_root,
        ) as writer:
            writer.write(b"launcher output\n")
            raise ValueError("primary run failure")
    except BaseException as error:
        caught = error

    production_closed_writer = writer is not None and writer.closed
    production_settled_drain = len(created_drains) == 1 and not created_drains[0]._thread.is_alive()
    if writer is not None and not writer.closed:
        writer.close()
    for drain in created_drains:
        drain._thread.join(timeout=1)

    assert type(caught) is ValueError and str(caught) == "primary run failure"
    notes = tuple(getattr(caught, "__notes__", ()))
    assert any("launcher writer settlement failed: SettlementInterrupted" in note for note in notes)
    assert "MUST NOT LEAK SETTLEMENT DETAIL" not in "\n".join(notes)
    assert production_closed_writer, "production left the parent write end open after cleanup interruption"
    assert production_settled_drain, "production left the launcher-log drain thread alive"
    assert traversals == [], "no syscall may enter a root whose writer settlement was interrupted"
    assert evidence.logs[runner._ENGINE_STDERR_EVIDENCE_NAME] == runner._UNSETTLED_CHILD_WRITER_LOG_REFUSAL_MARKER
    assert evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME] == runner._UNSETTLED_CHILD_WRITER_LOG_REFUSAL_MARKER
    assert "MUST NOT READ" not in "".join(evidence.logs.values())


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
    """More rotations than the configured handler retains are not safe to enumerate."""

    logs = state_root / "logs"
    for day in range(1, ASSISTANT_LOG_BACKUP_COUNT + 2):
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
