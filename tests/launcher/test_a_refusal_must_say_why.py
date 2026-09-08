"""A failure that stops acquisition has to say why.

On 2026-09-09 the stand refused to start and the entire diagnosis in both the
launcher log and the systemd journal was:

    CRITICAL Launcher construction failed; phase=engine exception=RuntimeError

The handler bound the exception and then used only `type(exc).__name__`. The
message and the traceback were discarded, so the reason the operator's stand
would not run existed nowhere. Acquisition was down for five minutes while the
cause was looked for, and it was never found from the logs — only by starting
the same code a different way.
"""

from __future__ import annotations

import logging

import pytest

from cryodaq.launcher import LauncherWindow, _LauncherConstructionHold


class _StubWindow:
    """Enough of a launcher for the construction step, with no Qt."""

    def __init__(self, *, can_settle: bool) -> None:
        self._can_settle = can_settle
        self._construction_failure_phase: str | None = None
        self.titles: list[str] = []
        self.shown = False

    def setWindowTitle(self, title: str) -> None:  # noqa: N802 - Qt's name
        self.titles.append(title)

    def show(self) -> None:
        self.shown = True


def _fail(message: str):
    def action() -> None:
        raise RuntimeError(message)

    return action


def test_the_reason_reaches_the_log(caplog: pytest.LogCaptureFixture, monkeypatch) -> None:
    monkeypatch.setattr(LauncherWindow, "_do_shutdown", lambda self: False)
    window = _StubWindow(can_settle=False)

    with caplog.at_level(logging.CRITICAL, logger="cryodaq.launcher"):
        with pytest.raises(_LauncherConstructionHold):
            LauncherWindow._run_construction_step(
                window, "engine", _fail("engine handshake never arrived")
            )

    failures = [r for r in caplog.records if "construction failed" in r.getMessage()]
    assert failures, "the refusal was not logged at all"
    record = failures[0]

    assert "engine handshake never arrived" in record.getMessage(), (
        f"only the class was logged: {record.getMessage()!r}"
    )
    assert record.exc_info is not None, "no traceback: the failing line is unknown"


def test_the_phase_is_still_named(caplog: pytest.LogCaptureFixture, monkeypatch) -> None:
    """The one thing the old message did carry must not be lost in the fix."""

    monkeypatch.setattr(LauncherWindow, "_do_shutdown", lambda self: False)
    window = _StubWindow(can_settle=False)

    with caplog.at_level(logging.CRITICAL, logger="cryodaq.launcher"):
        with pytest.raises(_LauncherConstructionHold):
            LauncherWindow._run_construction_step(window, "engine", _fail("boom"))

    assert any("phase=engine" in r.getMessage() for r in caplog.records)
    assert window._construction_failure_phase == "engine"
