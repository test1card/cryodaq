"""The profile the entry point selects must be the profile the runner runs.

WHY THIS MODULE EXISTS. Until this change the profile was never passed. `main()` computed
one, used it to name the evidence directory and to decide the activation refusal, and then
called `runner._PosixSoakRunner().run(evidence)` — a runner that selected `short` for
itself.

HOW THAT WAS SEEN, stated exactly, because it cannot be reproduced through this entry
point: the activation refusal was lifted on a THROWAWAY commit that was never pushed, and
a run asked for the `12h` profile then stopped at elapsed 185.0 s on the SHORT profile's
fault schedule, under the long profile's name. Through the entry point as it stands, a
non-short profile returns 3 and never reaches the runner at all.

Nothing here lifts the activation refusal. These tests are about one thing only: the
profile reaches the runner, and asking for the short one still behaves exactly as before.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "soak_mock_stack.py"
_SPEC = importlib.util.spec_from_file_location("soak_mock_stack_profile_pass", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
soak = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = soak
_SPEC.loader.exec_module(soak)

from scripts import soak_mock_stack_runner as runner  # noqa: E402

# The evidence directory needs POSIX capabilities, so the one test that builds a real
# Evidence is skipped elsewhere. Windows skipping it is exactly why the fix has to be
# run on the laboratory machine before it is pushed.
_POSIX_EVIDENCE = pytest.mark.skipif(os.name != "posix", reason="evidence capability is POSIX-only")


def test_the_runner_still_defaults_to_the_short_profile() -> None:
    """Every existing caller passes no profile, and must keep working unchanged.

    Two tests in the neighbouring module call `run(evidence)` with one argument. The
    default is what keeps them, and the entry point's own behaviour, identical.
    """

    import inspect

    signature = inspect.signature(runner._PosixSoakRunner.run)
    assert list(signature.parameters) == ["self", "evidence", "selected"]
    assert signature.parameters["selected"].default is None


def test_a_profile_that_is_not_the_registered_object_is_refused() -> None:
    """The check is stricter than the one it replaced, not looser.

    The old line compared `selected.name` against the literal it had just asked for, which
    cannot fail. This asks whether the object IS the registered profile, so a look-alike
    built by hand is refused too.
    """

    from dataclasses import replace

    genuine = soak.profile("short")
    impostor = replace(genuine, duration_s=genuine.duration_s)

    assert impostor == genuine, "the look-alike must be EQUAL, or the test proves nothing"
    assert impostor is not genuine
    assert soak.PROFILES.get(impostor.name) is genuine
    assert soak.PROFILES.get(impostor.name) is not impostor


def test_the_long_cadence_is_a_sibling_and_the_short_one_is_untouched() -> None:
    """The short chooser must be the SAME function it was, so short behaviour cannot move.

    The short chooser solves a reservation puzzle for a 15-minute run: one report boundary
    450-600 s in, and the next one at 1050 s or later. A long run needs none of that, so it
    gets its own chooser rather than an edit to this one.
    """

    interval_s, offset_s = runner._select_short_soak_report_schedule(1_700_000_000.0)
    assert 450 <= offset_s <= 600
    assert offset_s + interval_s >= 1050

    long_interval_s, long_offset_s = runner._select_long_soak_report_schedule(1_700_000_000.0)
    assert long_interval_s == runner._LONG_SOAK_REPORT_INTERVAL_S == 3600
    assert 0 < long_offset_s <= long_interval_s


def test_the_long_validator_refuses_a_malformed_interval_but_invents_no_reservation() -> None:
    """It must check the shape of the numbers and nothing else.

    The short validator refuses when startup latency ate a 15-minute run's only report.
    A run measured in hours cannot deserve that refusal, so this one must not make it.
    """

    with pytest.raises(runner._RunnerFoundationError, match="long-soak report interval is invalid"):
        runner._validate_long_soak_runtime_schedule(30, 1_700_000_000.0)
    with pytest.raises(runner._RunnerFoundationError, match="long-soak runtime epoch is invalid"):
        runner._validate_long_soak_runtime_schedule(3600, float("nan"))

    # Every ordinary moment is accepted; the short validator would refuse most of them.
    for now in (1_700_000_000.0, 1_700_000_123.0, 1_700_003_599.0):
        assert 0 < runner._validate_long_soak_runtime_schedule(3600, now) <= 3600


@_POSIX_EVIDENCE
def test_main_hands_the_runner_the_profile_it_selected(tmp_path, monkeypatch) -> None:
    """The defect itself: the entry point used to select a profile and then not pass it."""

    received: list = []

    class RecordingRunner:
        @staticmethod
        def require_platform() -> None:
            return None

        def run(self, evidence, selected=None) -> None:
            received.append(selected)
            raise RuntimeError("deterministic runner stop")

    monkeypatch.setattr(runner, "_PosixSoakRunner", RecordingRunner)
    assert soak.main(["--profile", "short", "--evidence-dir", str(tmp_path / "run")]) == 1
    assert received, "the runner was never called"
    assert received[0] is soak.profile("short"), (
        "the runner must receive the profile the entry point selected, not choose its own"
    )


def test_the_manifest_reports_the_profile_that_ran_and_counts_its_receipts() -> None:
    """The manifest used to name the short profile and claim two receipts, as literals.

    The thresholds beside those lines already read the selected profile, so a manifest could
    have described a run that did not happen. Nothing reaches that state while the entry
    point refuses every profile but the short one, which is exactly why it has to be right
    BEFORE the refusal is lifted rather than after.

    The short profile's own answer is pinned to 2 so its manifest cannot move: its chooser
    places one boundary inside the 900-second run and the next past the end.
    """

    short = soak.profile("short")
    assert runner._expected_report_receipts(short, 600, 500) == 2
    assert runner._expected_report_receipts(short, 3600, 1) == 2, (
        "the short answer must not depend on the interval, or its manifest could move"
    )

    twelve_hour = soak.profile("12h")
    assert twelve_hour.duration_s == 12 * 3600

    # Twelve hours at an hourly cadence crosses twelve boundaries, and the offset inside
    # the first hour does not change that. I first wrote 13 for the second line; the test
    # caught my arithmetic, which is what it is for.
    assert runner._expected_report_receipts(twelve_hour, 3600, 3600) == 12
    assert runner._expected_report_receipts(twelve_hour, 3600, 1) == 12

    # A case that actually distinguishes: halve the cadence and the count halves.
    assert runner._expected_report_receipts(twelve_hour, 7200, 7200) == 6

    with pytest.raises(runner._RunnerFoundationError, match="report interval must be positive"):
        runner._expected_report_receipts(twelve_hour, 0, 0)
