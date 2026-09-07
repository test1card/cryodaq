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

AND THEY ASK THE PLUGIN, rather than re-deriving what it will do. The second
version read the command line and then the INI file, which is not the plugin's
resolution order: pytest-timeout consults `PYTEST_TIMEOUT` BETWEEN the two.
Review measured the gap on 2026-09-07 — under `PYTEST_TIMEOUT=1` the plugin
applies one second while these tests read 600 from the INI and pronounce it
generous. Re-deriving another component's decision is how a guard ends up
approving a configuration that is not in force; the fix is to call
`get_env_settings`, which is the same function the plugin itself uses.
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


def _effective_timeout_seconds(config: pytest.Config) -> float | None:
    """What the plugin will apply, resolved by the plugin's own function.

    `get_env_settings` is what pytest-timeout calls for every test, so its
    answer is the effective value by construction — command line, then
    `PYTEST_TIMEOUT`, then the INI. Reading those sources here instead would be
    a copy that can drift, and did.
    """
    try:
        from pytest_timeout import get_env_settings
    except ImportError:  # pragma: no cover - covered by the plugin-active test
        return None
    if not config.pluginmanager.hasplugin("timeout"):
        return None
    return get_env_settings(config).timeout


def test_the_session_has_an_effective_per_test_timeout(pytestconfig: pytest.Config) -> None:
    """Read the value the session will actually apply, not the file it came from."""
    seconds = _effective_timeout_seconds(pytestconfig)
    assert seconds is not None, (
        "no per-test timeout is in effect in this session — either the plugin "
        "is not loaded or nothing configures a value"
    )
    assert seconds > 0, f"an effective timeout of {seconds} disables the guard"


def test_the_effective_value_follows_the_environment_the_plugin_reads(
    pytestconfig: pytest.Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression itself: PYTEST_TIMEOUT outranks the INI, so it must be seen.

    Without this, a run under `PYTEST_TIMEOUT=1` has a one-second per-test
    budget while the guard above reports the INI's 600 and approves it.
    """
    if not pytestconfig.pluginmanager.hasplugin("timeout"):
        pytest.skip("plugin absent; the active-plugin test above owns that failure")
    monkeypatch.delenv("PYTEST_TIMEOUT", raising=False)
    baseline = _effective_timeout_seconds(pytestconfig)
    monkeypatch.setenv("PYTEST_TIMEOUT", "1")
    under_env = _effective_timeout_seconds(pytestconfig)
    if pytestconfig.getoption("timeout", default=None) is not None:
        pytest.skip("an explicit --timeout outranks the environment; nothing to prove here")
    assert under_env == 1.0, (
        f"PYTEST_TIMEOUT=1 must resolve to a one-second budget, not {under_env}; "
        f"reading the INI directly would have answered {baseline}"
    )


def test_the_effective_timeout_is_generous_enough_not_to_fail_real_work(
    pytestconfig: pytest.Config,
) -> None:
    """It bounds hangs; it is not a speed limit.

    Too tight a value turns this guard into a flake source, which is how such
    guards get deleted. The bounds are wide on purpose — the exact number is
    provisional and the owner's to set.
    """
    seconds = _effective_timeout_seconds(pytestconfig)
    assert seconds is not None, "no per-test timeout is in effect in this session"
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
