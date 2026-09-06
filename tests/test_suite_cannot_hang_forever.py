"""A hanging test should fail loudly rather than consume the run in silence.

pytest-timeout was a declared dependency and was never configured. On
2026-09-06 that cost a full-suite result twice: a run sat for an hour and
forty-five minutes at 4957 passed — 314 s of CPU across 6211 s of wall clock,
`wchan: ep_poll`, zero ticks — indistinguishable from progress until it was
interrupted by hand.

WHAT `timeout = 600` DOES AND DOES NOT GIVE, corrected after review. It bounds
a test that hangs in Python and lets the run continue to the next one. It does
NOT guarantee the suite always terminates, and the first version of this module
claimed that it did:

* collection and session start are outside the per-test timer entirely;
* a native operation that does not return can stop Python's signal handler from
  ever running — the reviewer reproduced exactly that with a native mutex
  deadlock, where the plugin was active, a one-second timeout was configured,
  and only an outer process deadline ended it after five seconds;
* signal-based continuation is platform-dependent.

A hard runner deadline (`timeout 18000 pytest …`, or a CI job limit) is a
separate containment measure and the only one that actually bounds the session.
600 s is also provisional: no measurement establishes that every legitimate
individual test fits inside it. The slowest FILE here runs about 900 s, which
says nothing definitive about its slowest test.

THESE TESTS INSPECT THE RUNNING SESSION, not the configuration text. The first
version asserted that `pyproject.toml` contained the right words, and review
showed it passed under `-p no:timeout` with nothing but an "Unknown config
option: timeout" warning. Text in a file is not a plugin doing work.
"""

from __future__ import annotations

import pytest


def test_the_timeout_plugin_is_actually_active(pytestconfig: pytest.Config) -> None:
    """Configuration without the plugin loaded is no protection at all."""
    assert pytestconfig.pluginmanager.hasplugin("timeout"), (
        "pytest-timeout is not loaded in THIS session, so the configured "
        "timeout is inert — run without -p no:timeout, and keep the plugin "
        "installed"
    )


def test_the_session_has_an_effective_per_test_timeout(pytestconfig: pytest.Config) -> None:
    """Read the value the session will actually apply, not the file it came from."""
    effective = pytestconfig.getoption("timeout", default=None)
    if effective is None:
        effective = pytestconfig.getini("timeout")
    assert effective is not None, "no per-test timeout is in effect in this session"
    seconds = float(effective)
    assert seconds > 0, f"an effective timeout of {seconds} disables the guard"


def test_the_effective_timeout_is_generous_enough_not_to_fail_real_work(
    pytestconfig: pytest.Config,
) -> None:
    """It bounds hangs; it is not a speed limit.

    Too tight a value turns this guard into a flake source, which is how such
    guards get deleted. The bounds are wide on purpose — the exact number is
    provisional and the owner's to set.
    """
    effective = pytestconfig.getoption("timeout", default=None)
    if effective is None:
        effective = pytestconfig.getini("timeout")
    seconds = float(effective)
    assert seconds >= 300, f"{seconds}s is tight enough to fail slow but honest tests"
    assert seconds <= 1800, f"{seconds}s is long enough that a hang still stalls a run badly"


def test_the_repository_ships_the_configuration_that_produces_that_default() -> None:
    """The session value can come from a flag; the repository default must exist too.

    This is the one file-level check worth keeping, and on its own it proves
    nothing — which is why it is last and why the three tests above read the
    live session instead.
    """
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    with pyproject.open("rb") as handle:
        options = tomllib.load(handle)["tool"]["pytest"]["ini_options"]
    assert "timeout" in options, "removing the repository default silently restores the old behaviour"
    assert isinstance(options["timeout"], int) and options["timeout"] > 0
