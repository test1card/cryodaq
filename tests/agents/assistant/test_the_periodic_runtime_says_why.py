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

import asyncio
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


def test_a_credential_bearing_reason_can_actually_BE_WRITTEN(tmp_path) -> None:
    """Stopping at the text was the mistake: the WRITER is what decides.

    periodic_state refuses any text matching `api.telegram.org/bot`, credential or not, and
    _write_runtime_failed_health swallows the refusal -- so a reason that merely mentioned
    the URL left the health record STALE and said nothing at all. Redacting the secret was
    not enough; the whole prohibited locator has to go. This drives the real writer, which
    is the only thing that proves it.
    """

    from cryodaq.periodic_state import load_periodic_state, set_periodic_health, write_periodic_state

    token = "bot7701234567:AAEhBPqZzXyWvUtSrQpOnMlKjIhGfEdCbA9"
    cause = RuntimeError(f"POST https://api.telegram.org/{token}/sendPhoto failed with 401")
    text = periodic_png._runtime_failed_text(cause, "the coordinator could not be constructed")

    assert token not in text, text
    assert "api.telegram.org/bot" not in text, text
    assert "<telegram-url-removed>" in text, text
    assert "401" in text, "everything that is not the locator must survive"

    # And the writer accepts it, which is the property that actually matters.
    state = load_periodic_state(tmp_path)
    candidate = set_periodic_health(
        state, status="degraded_runtime", code="periodic_runtime_failed", text=text, now=1.0
    )
    write_periodic_state(tmp_path, candidate)
    assert text in load_periodic_state(tmp_path).payload["health"]["error_text"]


def test_a_very_long_exception_cannot_fill_the_health_record() -> None:
    text = periodic_png._runtime_failed_text(RuntimeError("x" * 5000), "construction failed")
    assert len(text) < 400, len(text)
    assert text.endswith("…")


@pytest.mark.parametrize(
    ("persisted_code", "preserved"),
    [
        ("periodic_live_source_stopped", True),
        ("periodic_projection_incomplete", False),
        ("periodic_tls_verification_disabled", False),
        ("periodic_runtime_failed", False),
        (None, False),
    ],
)
def test_only_the_live_source_reason_is_preserved(tmp_path, persisted_code, preserved) -> None:
    """Exactly one code belongs to the path this branch defers to.

    Preserving every other nonempty code was too generous: a coordinator can stop leaving
    an earlier, unrelated code behind, and keeping one of those would hide the runtime
    failure that actually happened behind a stale status.
    """

    from cryodaq.periodic_state import load_periodic_state, set_periodic_health, write_periodic_state

    if persisted_code is not None:
        state = load_periodic_state(tmp_path)
        candidate = set_periodic_health(
            state,
            status="degraded_source" if persisted_code != "periodic_runtime_failed" else "degraded_runtime",
            code=persisted_code,
            text="something the monitor or an earlier step wrote",
            now=1.0,
        )
        write_periodic_state(tmp_path, candidate)

    supervisor = object.__new__(periodic_png.PeriodicPngSupervisor)
    supervisor._data_dir = tmp_path

    async def _run_blocking(func, *args, **kwargs):
        return func(*args, **kwargs)

    supervisor._run_blocking = _run_blocking

    assert asyncio.run(supervisor._monitor_left_a_reason()) is preserved, persisted_code


def test_a_persisting_failure_does_not_write_a_line_every_second(caplog) -> None:
    """Drive the PRODUCTION limiter, not a copy of it.

    The first version rebuilt the rule inside the test, so deleting the production limiter
    left the test green -- which is the failure this whole module exists to stop happening
    to somebody else.
    """

    supervisor = object.__new__(periodic_png.PeriodicPngSupervisor)
    supervisor._clock = _Clock()
    supervisor._last_runtime_failure_log = None

    with caplog.at_level(logging.ERROR, logger=periodic_png.__name__):
        for _ in range(60):
            supervisor._log_runtime_failure("the monitor reported a failure", None)
            supervisor._clock.monotonic_value += 1.0
        assert len(caplog.records) == 1, (
            f"a persisting reason must not repeat every second; wrote {len(caplog.records)}"
        )

        supervisor._clock.monotonic_value += periodic_png._RUNTIME_FAILED_LOG_INTERVAL_S
        supervisor._log_runtime_failure("the monitor reported a failure", None)
        assert len(caplog.records) == 2, "but it must still be repeated occasionally, or it looks resolved"

        supervisor._log_runtime_failure("the configuration changed", None)
        assert len(caplog.records) == 3, "and a DIFFERENT reason is never suppressed"


def test_every_caller_goes_through_the_limiter() -> None:
    """A second door into the log is the same flood by another name.

    The configuration-loader handler logged directly and bypassed the limit, so a reload
    failing once a second wrote once a second.
    """

    import inspect

    source = inspect.getsource(periodic_png)
    direct = source.count("_log.error(")
    assert direct == 1, f"only the limiter may call the error logger; found {direct} call sites"
    assert "_log.error(" in inspect.getsource(periodic_png.PeriodicPngSupervisor._log_runtime_failure)


def test_each_branch_puts_its_own_name_into_the_durable_text(tmp_path, caplog) -> None:
    """Identical exceptions from different branches must not read identically.

    Both handlers passed only the cause, leaving the branch label empty, so the same
    exception type from two places produced the same durable sentence.

    Checked by RUNNING the handler, not by reading it. The first version asserted that
    `because=` appeared in the source, which an empty string satisfies -- so the exact
    defect under discussion left the test green.
    """

    supervisor = object.__new__(periodic_png.PeriodicPngSupervisor)
    supervisor._clock = _Clock()
    supervisor._last_runtime_failure_log = None
    supervisor._config_dir = tmp_path / "config"
    supervisor._leader_fd = None

    async def _sleep_or_stop(_seconds: float) -> None:
        return None

    supervisor._sleep_or_stop = _sleep_or_stop

    with caplog.at_level(logging.ERROR, logger=periodic_png.__name__):
        asyncio.run(supervisor._handle_config_loader_failure(0, ValueError("bad yaml")))

    assert caplog.records, "the loader failure must say something"
    said = caplog.records[-1].getMessage()
    assert "because=" in said and "unstated" not in said, said
    assert str(tmp_path / "config") in said or "configuration" in said, said

    # And two branches with the SAME exception must still read differently in durable text.
    loader = periodic_png._runtime_failed_text(ValueError("x"), "the configuration could not be loaded from /a")
    constructed = periodic_png._runtime_failed_text(ValueError("x"), "the coordinator could not be constructed")
    assert loader != constructed


def test_the_module_can_be_heard_at_all() -> None:
    """It had no logger, which is why none of the above could reach a file."""

    assert isinstance(periodic_png._log, logging.Logger)
    assert periodic_png._log.name == periodic_png.__name__
