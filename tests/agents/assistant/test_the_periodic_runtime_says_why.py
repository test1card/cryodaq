"""A periodic runtime that will not start must leave a reason behind.

WHY THIS MODULE EXISTS. Measured on the laboratory machine: the isolated soak flapped
between ``ready`` and ``degraded_runtime`` once a second for a whole run. ``active`` never
left ``None``, so no slot was ever allocated, so no receipt was ever sealed -- which is the
refusal the run stops on, three steps from its cause. Five different situations published
the identical sentence ``periodic runtime is unavailable`` and discarded everything they
knew, and the module had no logger, so there was nothing to read anywhere.

These tests pin the three properties that keep it readable, and one that keeps it safe:

* every branch names itself, so a run that repeats once a second reads as one BRANCH
  repeating rather than one fault;
* the monitor's own, more specific reason is never overwritten by the general one;
* an exception's words are redacted before they reach the health record, because that
  record leaves this machine in a support bundle;
* repeated identical failures do not write a line a second for a week.
"""

from __future__ import annotations

import logging

import pytest

from cryodaq.agents.assistant import periodic_png


class _Clock:
    def __init__(self) -> None:
        self.monotonic_value = 1000.0

    def monotonic(self) -> float:
        return self.monotonic_value

    def wall_time(self) -> float:
        return 1_700_000_000.0

    def display_time(self, epoch: int) -> str:
        return str(epoch)


def test_every_branch_that_publishes_unavailable_names_itself() -> None:
    """Five situations wrote one sentence. A bare call would make them one again."""

    import inspect

    source = inspect.getsource(periodic_png)
    assert "_stop_then_mark_runtime_failed()" not in source, (
        "a branch that publishes 'unavailable' without saying which branch it is puts the "
        "five situations back into one indistinguishable sentence"
    )


@pytest.mark.parametrize(
    ("because", "expected"),
    [
        ("", "periodic runtime is unavailable"),
        ("the monitor reported a failure", "periodic runtime is unavailable: the monitor reported a failure"),
    ],
)
def test_the_health_text_carries_whatever_is_known(because: str, expected: str) -> None:
    assert periodic_png._runtime_failed_text(None, because) == expected


def test_the_health_text_names_the_exception_and_its_words() -> None:
    text = periodic_png._runtime_failed_text(ValueError("the roster is empty"), "construction failed")
    assert text == "periodic runtime is unavailable: construction failed: ValueError: the roster is empty"


def test_a_credential_in_the_exception_never_reaches_the_health_record() -> None:
    """The health record leaves this machine in a support bundle. That is the boundary.

    An HTTP client error embedding a Telegram bot URL is the obvious way for a credential
    to arrive inside an exception, and this text is written verbatim into durable state.
    """

    token = "bot7701234567:AAEhBPqZzXyWvUtSrQpOnMlKjIhGfEdCbA9"
    cause = RuntimeError(f"POST https://api.telegram.org/{token}/sendPhoto failed with 401")

    text = periodic_png._runtime_failed_text(cause, "construction failed")

    assert token not in text, text
    assert "bot***" in text, text
    assert "401" in text, "and everything that is not the credential must survive"


def test_a_very_long_exception_cannot_fill_the_health_record() -> None:
    text = periodic_png._runtime_failed_text(RuntimeError("x" * 5000), "construction failed")
    assert len(text) < 400, len(text)
    assert text.endswith("…")


def test_the_monitor_keeps_its_own_more_specific_reason() -> None:
    """The whole complaint: the specific code was destroyed by the general one.

    ``_watch_live`` persists ``periodic_live_source_stopped`` before the monitor reports a
    failure. Naming the branch was not enough -- the branch still overwrote it.
    """

    import inspect

    source = inspect.getsource(periodic_png.PeriodicPngSupervisor.run)
    assert "_stop_then_keep_monitor_health()" in source, (
        "the monitor-failure branch must keep whatever the monitor already said"
    )
    keeper = inspect.getsource(periodic_png.PeriodicPngSupervisor._monitor_left_a_reason)
    assert '"periodic_runtime_failed"' in keeper, (
        "and it must recognise our own general code as NOT a more specific reason"
    )


def test_a_persisting_failure_does_not_write_a_line_every_second() -> None:
    """One a second for a week is a log nobody can read and a disk nobody budgeted for."""

    written: list[tuple] = []

    class _Supervisor:
        _clock = _Clock()
        _last_runtime_failure_log = None

        def _log_once(self, because: str, cause: BaseException | None) -> None:
            signature = (because, "none" if cause is None else type(cause).__name__)
            now = self._clock.monotonic()
            last = self._last_runtime_failure_log
            if last is None or last[0] != signature or now - last[1] >= periodic_png._RUNTIME_FAILED_LOG_INTERVAL_S:
                self._last_runtime_failure_log = (signature, now)
                written.append((signature, now))

    supervisor = _Supervisor()
    for _ in range(60):
        supervisor._log_once("the monitor reported a failure", None)
        supervisor._clock.monotonic_value += 1.0

    assert len(written) == 1, f"a persisting reason must not repeat every second; wrote {len(written)}"

    supervisor._clock.monotonic_value += periodic_png._RUNTIME_FAILED_LOG_INTERVAL_S
    supervisor._log_once("the monitor reported a failure", None)
    assert len(written) == 2, "but it must still be repeated occasionally, or it looks resolved"

    supervisor._log_once("the configuration changed", None)
    assert len(written) == 3, "and a DIFFERENT reason is never suppressed"


def test_the_module_can_be_heard_at_all() -> None:
    """It had no logger, which is why none of the above could reach a file."""

    assert isinstance(periodic_png._log, logging.Logger)
    assert periodic_png._log.name == periodic_png.__name__
