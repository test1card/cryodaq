"""My own fix for the caption's note was worse than the defect it replaced.

Review found four things in it. The one that mattered most:

A FRACTION-OF-OVERLAP BAR REFUSES EVERY NOTE THAT CAN EXIST. The agent's hour
runs from process start and the report's slot runs from the clock, so they are
offset by construction — and the newest note in existence when a chart freezes
is always the PREVIOUS cycle's. For an agent phased at HH:10, that note
describes HH-2:10..HH-1:10 while the chart shows HH-1:00..HH:00: ten minutes of
overlap out of sixty. A half-overlap bar refuses it, refuses its successor for
the same reason, and the operator silently never sees a summary at all —
indistinguishable from an agent with nothing to say.

The rule is now that the two periods must TOUCH.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from cryodaq.agents.assistant.shared.summary_note import read_summary, write_summary

_H = 3600.0


def _raw(root: Path, record: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "last_summary.json").write_text(json.dumps(record), encoding="utf-8")


def test_the_offset_cycle_that_used_to_be_refused_forever(tmp_path: Path) -> None:
    """The exact arithmetic of the report: agent at HH:10, chart at HH:00."""
    hh = time.time()
    chart_start, chart_end = hh - _H, hh
    note_start, note_end = hh - 2 * _H + 600, hh - _H + 600  # HH-2:10 .. HH-1:10

    write_summary(tmp_path, "слова агента", window_start=note_start, window_end=note_end)

    assert read_summary(tmp_path, window_start=chart_start, window_end=chart_end) == "слова агента", (
        "the freshest note that can exist is refused, every hour, silently"
    )


def test_a_note_entirely_before_the_charted_hour_is_still_refused(tmp_path: Path) -> None:
    hh = time.time()
    write_summary(tmp_path, "позапрошлый час", window_start=hh - 3 * _H, window_end=hh - 2 * _H)

    assert read_summary(tmp_path, window_start=hh - _H, window_end=hh) == ""


def test_a_note_that_had_not_started_when_the_chart_ended_is_refused(tmp_path: Path) -> None:
    hh = time.time()
    write_summary(tmp_path, "из будущего окна", window_start=hh, window_end=hh + _H)

    assert read_summary(tmp_path, window_start=hh - _H, window_end=hh) == ""


def test_the_touching_boundary_is_inclusive_on_the_side_that_matters(tmp_path: Path) -> None:
    """A note ending exactly where the chart begins still describes the run."""
    hh = time.time()
    write_summary(tmp_path, "ровно встык", window_start=hh - 2 * _H, window_end=hh - _H)

    assert read_summary(tmp_path, window_start=hh - _H, window_end=hh) == "ровно встык"


def test_a_non_finite_requested_window_refuses_rather_than_falls_open(tmp_path: Path) -> None:
    """It used to arrive as None and drop the check entirely."""
    hh = time.time()
    write_summary(tmp_path, "прошлый час", window_start=hh - 3 * _H, window_end=hh - 2 * _H)

    assert read_summary(tmp_path, window_start=math.nan, window_end=hh) == ""
    assert read_summary(tmp_path, window_start=hh - _H, window_end=math.inf) == ""


def test_a_note_with_a_corrupt_window_is_refused(tmp_path: Path) -> None:
    hh = time.time()
    _raw(tmp_path, {"ts": hh, "text": "кривое", "window_start": None, "window_end": hh})

    assert read_summary(tmp_path, window_start=hh - _H, window_end=hh) == ""


def test_age_only_callers_are_unaffected(tmp_path: Path) -> None:
    hh = time.time()
    write_summary(tmp_path, "без окна в запросе", window_start=hh - _H, window_end=hh)

    assert read_summary(tmp_path) == "без окна в запросе"


async def test_the_write_runs_off_the_callers_loop(tmp_path: Path) -> None:
    """`mkdir`, `write_text` and `replace` are syscalls: on a stalled mount they
    do not raise and cannot be interrupted, so the loop stops inside a `try`
    whose `except` can never run."""
    import ast
    import inspect
    import textwrap

    from cryodaq.agents.assistant.shared import summary_note

    source = inspect.getsource(summary_note.write_summary_async)
    calls = [ast.unparse(n) for n in ast.walk(ast.parse(textwrap.dedent(source))) if isinstance(n, ast.Call)]
    assert any("to_thread" in call for call in calls)
    assert any("wait_for" in call for call in calls)

    from cryodaq.agents.assistant.shared.summary_note import write_summary_async

    await write_summary_async(tmp_path, "через поток", window_start=1.0, window_end=2.0)
    assert read_summary(tmp_path) == "через поток"


def test_the_agent_waits_for_the_audit_to_SETTLE_not_merely_to_start() -> None:
    """A failed settlement only appends to `errors`; with no targets left the
    outcomes mapping is empty, so the first version of this gate read as
    "not failed" and published an unaudited note."""
    import inspect

    from cryodaq.agents.assistant.live import agent as module

    source = inspect.getsource(module.AssistantLiveAgent)
    at = source.index("write_summary_async(")
    guard = source[source.rindex("audit_settled", 0, at) - 400 : at]
    assert 'startswith("audit_")' in guard, "a failed audit settlement can still publish"
    assert "summary_is_publishable" in guard
