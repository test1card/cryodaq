"""Small files are microseconds on a healthy disk and unbounded on a hung mount.

Two loops read them synchronously: the query handler, which carries a question
under a strict deadline chain, and the periodic coordinator, which carries the
report's heartbeat and its alarm refresh. A stalled read on either does not time
out — it stops every deadline above it from firing, so nothing can even report
that something is wrong.

Losing the memory or the caption for one cycle is a worse answer. Losing the
loop is no answer at all.
"""

from __future__ import annotations

import ast
import inspect
import textwrap


def _calls(func) -> list[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    return [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call)]


def test_the_transcript_is_read_off_the_query_loop() -> None:
    from cryodaq.agents.assistant.query.agent import AssistantQueryAgent

    calls = _calls(AssistantQueryAgent._conversation_transcript)
    assert any("to_thread" in call for call in calls), "the read runs on the event loop"
    assert any("wait_for" in call for call in calls), (
        "the read is off the loop but unbounded, so a hung mount holds a worker forever"
    )


def test_remembering_is_also_off_the_query_loop() -> None:
    from cryodaq.agents.assistant.query.agent import AssistantQueryAgent

    source = inspect.getsource(AssistantQueryAgent._handle_query_inner)
    at = source.index("_conversation.remember")
    window = source[max(at - 400, 0) : at + 200]
    assert "to_thread" in window and "wait_for" in window


def test_the_summary_note_is_read_off_the_report_loop() -> None:
    from cryodaq.agents.assistant.periodic_png import PeriodicPngCoordinator

    calls = _calls(PeriodicPngCoordinator._read_summary_note)
    assert any("wait_for" in call for call in calls)
    assert any("_run_blocking" in call for call in calls), (
        "the note is read on the loop that also carries the report's heartbeat"
    )


def test_the_payload_no_longer_reads_the_note_itself() -> None:
    """It is handed the value, so building a payload cannot touch the disk."""
    from cryodaq.agents.assistant.periodic_png import PeriodicPngCoordinator

    calls = _calls(PeriodicPngCoordinator._input_payload)
    assert not [call for call in calls if "read_summary" in call]


def test_every_one_of_these_deadlines_is_finite_and_short() -> None:
    from cryodaq.agents.assistant.periodic_png import _SUMMARY_READ_TIMEOUT_S
    from cryodaq.agents.assistant.query.agent import _CONVERSATION_IO_TIMEOUT_S

    for name, value in (
        ("_CONVERSATION_IO_TIMEOUT_S", _CONVERSATION_IO_TIMEOUT_S),
        ("_SUMMARY_READ_TIMEOUT_S", _SUMMARY_READ_TIMEOUT_S),
    ):
        assert 0 < value <= 30, f"{name}={value} is not a bound on a small local read"
