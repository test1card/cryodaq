"""The profile the entry point selects must reach the runner, and be refused there honestly.

WHY THIS MODULE EXISTS. The profile was never passed. `main()` computed one, used it to
name the evidence directory and to decide the activation refusal, and then called
`runner._PosixSoakRunner().run(evidence)` — a runner that selected `short` for itself and
asserted that the name it had just asked for was the name it got, which cannot fail.

HOW THAT WAS SEEN, stated exactly, because it cannot be reproduced through this entry
point: the activation refusal was lifted on a THROWAWAY commit that was never pushed, and
a run asked for the `12h` profile then stopped at elapsed 185.0 s on the SHORT profile's
fault schedule, under the long profile's name. Through the entry point as it stands, a
non-short profile returns 3 and never reaches the runner at all.

WHAT THIS DOES NOT DO. It does not admit a long profile. The evidence contract seals
exactly two receipts -- `Evidence` rejects a manifest whose `expected_receipts` is not 2,
and the qualification refuses a ledger that is not two records long -- so a long profile
could start, fault processes for hours and never seal. The runner therefore still refuses
one, now for that reason instead of a tautology.

A NOTE ON WHAT THESE TESTS MUST DO. An earlier version of this module asserted how an
impostor profile was CONSTRUCTED and never handed it to anything, so it would have passed
with the refusal deleted. That is the failure this file exists to prevent, so every
refusal below is driven rather than described.
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

# The evidence directory needs POSIX capabilities, so the test that builds a real Evidence
# is skipped elsewhere. Windows skipping it is exactly why this file has to be run on the
# laboratory machine before it is pushed.
_POSIX_EVIDENCE = pytest.mark.skipif(os.name != "posix", reason="evidence capability is POSIX-only")


def _runner_at_the_selection_boundary(monkeypatch):
    """A real `_PosixSoakRunner`, called at the boundary the profile check lives on.

    The check is inside `_run_owned`, past the platform guard. That guard is replaced so
    the test reaches the boundary and nothing else, and `_run_owned` is then called with
    the profile directly -- the same argument the production chain now forwards.
    """

    monkeypatch.setattr(runner._PosixSoakRunner, "require_platform", staticmethod(lambda: None))
    instance = runner._PosixSoakRunner()
    instance._used = True
    return instance


def test_the_whole_chain_forwards_the_profile_and_no_link_drops_it() -> None:
    """The crash this test was written after: a parameter added at one end only.

    `run()` took the profile, handed `_DELIVERY_EVIDENCE.run(self, evidence)` two
    arguments, and that called `_run_owned(runner, evidence)`. `_run_owned` then read an
    unbound `selected` and raised `UnboundLocalError` on EVERY real invocation. No test
    caught it, because they all replace the runner or inspect helpers instead of walking
    this chain. So the chain itself is walked here.
    """

    import inspect

    run_params = list(inspect.signature(runner._PosixSoakRunner.run).parameters)
    assert run_params == ["self", "evidence", "selected"]
    assert inspect.signature(runner._PosixSoakRunner.run).parameters["selected"].default is None

    registry_run = type(runner._DELIVERY_EVIDENCE).run
    assert list(inspect.signature(registry_run).parameters) == [
        "self",
        "runner",
        "evidence",
        "selected",
    ], "the delivery registry must forward the profile, or the runner reads an unbound name"

    assert list(inspect.signature(runner._PosixSoakRunner._run_owned).parameters) == [
        "self",
        "evidence",
        "selected",
    ]

    source = inspect.getsource(runner._PosixSoakRunner.run)
    assert "_DELIVERY_EVIDENCE.run(self, evidence, selected)" in source, (
        "the call must pass the profile, not only the signature"
    )


def test_a_look_alike_profile_is_refused_by_the_runner_itself(monkeypatch) -> None:
    """A profile that answers to a registered NAME but differs in a field must be refused.

    The old check compared `selected.name` against the literal it had just asked for, which
    cannot fail. The refusal is DRIVEN here rather than described: an earlier version of
    this test only asserted how the look-alike was built and would have passed with the
    check deleted.

    The check compares by value on purpose. Identity looks stricter and is wrong: the soak
    starts as `python -m scripts.soak_mock_stack`, so the entry module is `__main__` while
    the runner imports `scripts.soak_mock_stack` -- two instances, two sets of profile
    objects, and an identity check would refuse every real run. This test found that.
    """

    from dataclasses import replace

    genuine = soak.profile("short")
    impostor = replace(genuine, duration_s=genuine.duration_s * 4)
    assert impostor.name == genuine.name, "it must pass for the short profile by NAME"
    assert impostor != genuine, "and differ in a field, which is what makes it worth refusing"

    instance = _runner_at_the_selection_boundary(monkeypatch)
    with pytest.raises(runner._RunnerFoundationError, match="not one of the reviewed profiles"):
        instance._run_owned(object(), impostor)


def test_a_long_profile_is_refused_by_the_runner_for_the_contract_reason(monkeypatch) -> None:
    """A long profile must not start, and the message must say WHY.

    The evidence contract seals exactly two receipts. A long profile admitted here would
    run for hours and fail at the seal, spending a night of machine time to produce
    nothing. The refusal names that instead of asserting a tautology.
    """

    instance = _runner_at_the_selection_boundary(monkeypatch)
    for name in ("12h", "72h"):
        with pytest.raises(runner._RunnerFoundationError, match="never seal"):
            instance._run_owned(object(), soak.profile(name))


def test_the_short_profile_passes_the_selection_boundary(monkeypatch) -> None:
    """The refusals must not swallow the profile that IS allowed.

    A file that only proves refusals would pass with a runner that refuses everything. The
    short profile therefore has to get PAST this boundary; it fails later, on the evidence
    object this test deliberately does not build.
    """

    instance = _runner_at_the_selection_boundary(monkeypatch)

    # It fails at the NEXT check, on the object standing in for Evidence, and the message
    # names that instead of either refusal. A bare `Exception` here would have hidden a
    # refusal that fired for the wrong reason, and a registered guard refuses one anyway.
    with pytest.raises(runner._RunnerFoundationError, match="process start identity is unavailable"):
        instance._run_owned(object(), soak.profile("short"))


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
