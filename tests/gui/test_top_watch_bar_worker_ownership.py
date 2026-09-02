"""A superseded status completion must not render, and must not clear.

`TopWatchBar._poll_fast` keeps the current worker on `_experiment_worker` and
skips while one is in flight. Its handler used not to know WHICH worker was
completing, so:

* a queued completion from a superseded poll could render stale experiment
  status over a newer result, and
* nothing ever cleared the attribute, so the slot was only freed by the worker
  reporting itself finished -- which stops being safe once settled workers are
  destroyed.

Both directions are pinned here: ours clears the slot, a stranger neither
renders nor clears.
"""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class _Bar:
    """Only the ownership contract, isolated from Qt widget construction."""

    def __init__(self) -> None:
        self._experiment_worker = None
        self._expected_app_mode_domain = "live"
        self._replay_authority = None
        self.unavailable_calls = 0
        self.rendered: list[dict] = []

    def _mark_experiment_status_unavailable(self) -> None:
        self.unavailable_calls += 1


def _handler():
    from cryodaq.gui.shell.top_watch_bar import TopWatchBar

    return TopWatchBar._on_experiment_result


def test_a_superseded_completion_neither_renders_nor_clears(qapp):
    bar = _Bar()
    current = object()
    stale = object()
    bar._experiment_worker = current

    _handler()(bar, {"ok": True}, None, stale)

    assert bar._experiment_worker is current, "a stranger freed the current worker's slot"
    assert bar.unavailable_calls == 0, "a stranger rendered over the display"
    assert bar.rendered == []


def test_our_own_completion_releases_the_slot(qapp):
    bar = _Bar()
    worker = object()
    bar._experiment_worker = worker

    _handler()(bar, {"malformed": True}, None, worker)

    assert bar._experiment_worker is None, "the slot was not released, so polling would stall"


def test_out_of_order_completions_leave_the_newer_poll_owning_the_slot(qapp):
    """A completes late, after B has started. B must keep the slot."""
    bar = _Bar()
    first = object()
    second = object()

    bar._experiment_worker = first
    bar._experiment_worker = second          # B supersedes A

    _handler()(bar, {"ok": True}, None, first)   # A's queued completion lands late
    assert bar._experiment_worker is second, "the late completion stole the slot"
    assert bar.unavailable_calls == 0

    _handler()(bar, {"malformed": True}, None, second)
    assert bar._experiment_worker is None
