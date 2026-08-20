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
