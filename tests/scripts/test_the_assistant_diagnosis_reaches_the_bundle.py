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

import os
from pathlib import Path

import pytest

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
    (logs / "assistant.log.2026-08-14").write_bytes(b"OLDEST-" + b"x" * runner._MAX_LAUNCHER_LOG_BYTES)
    (logs / "assistant.log").write_bytes(
        b"NEWEST-" + b"y" * runner._MAX_LAUNCHER_LOG_BYTES + b"NEWEST-ACTIVE-CONTENT\n"
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
    assert published == runner._ASSISTANT_LOG_REFUSED_MARKER


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
    assert published == runner._ASSISTANT_LOG_REFUSED_MARKER


def test_directory_open_failure_is_refused_without_pathname_fallback(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed descriptor open must not restore child-controlled pathname traversal."""

    (state_root / "logs" / "assistant.log").write_bytes(b"MUST NOT BE READ AFTER OPEN FAILURE\n")

    def refuse_directory_access(*_args: object, **_kwargs: object) -> int:
        raise OSError("simulated directory-open failure")

    if os.name == "nt":
        monkeypatch.setattr(runner.os, "listdir", refuse_directory_access)
    else:
        monkeypatch.setattr(runner.os, "open", refuse_directory_access)
    evidence = _Evidence()

    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "MUST NOT BE READ AFTER OPEN FAILURE" not in published
    assert published == runner._ASSISTANT_LOG_REFUSED_MARKER


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
    assert published == runner._ASSISTANT_LOG_REFUSED_MARKER


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

    monkeypatch.setattr(runner.os, "name", "nt")
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

    monkeypatch.setattr(runner.os, "name", "nt")
    monkeypatch.setattr(runner, "_directory_identity", lambda _directory: (1, 111))

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, tmp_path)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "lost authority" in published
    assert published != runner._ASSISTANT_LOG_REPLACED_MARKER
