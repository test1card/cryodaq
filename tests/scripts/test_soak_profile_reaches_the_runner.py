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
import re
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
    """The short profile must pass both refusals AND reach the evidence contract.

    WHAT THE BOUNDARY IS. Past the two refusals, `_run_owned` inspects the host
    before it first touches `evidence`: it enumerates the process tree through a
    psutil build locked to one exact version, captures the running interpreter
    into a sealed `.venv/bin/python` snapshot, materializes the passive fixture
    through a validation child, and seals that fixture with POSIX-only owner and
    mode checks. None of those steps is the selection check, and which one
    speaks first depends on the host.

    WHY THE PREVIOUS VERSION PROVED NOTHING ON WINDOWS. It handed `object()` to
    `_run_owned` and accepted any `_RunnerFoundationError` whose message was
    neither refusal. On Windows the locked observer's `create_time(monotonic=..)`
    call is unsupported -- TypeError wrapped into "process start identity is
    unavailable" -- so a host condition fired BEFORE the evidence boundary and
    the test passed without ever observing the side effect it names. On Ubuntu
    the same flow ran one step further and died on `AttributeError` because
    `object()` has no `write_manifest`. One dummy, two platforms, two accidents.

    WHAT IS DOUBLED, WHAT STAYS REAL. The four host-inspecting producers between
    the refusals and `write_manifest` are replaced with inert stand-ins so the
    flow reaches the evidence boundary on every platform. Deliberately real:
    both profile refusals, `_CleanShaCollector`'s Git-worktree check, the
    short-soak schedule alignment, and the actual `git rev-parse HEAD`. The
    evidence double records the manifest payload and raises a dedicated
    sentinel, so the only way this test passes is production crossing the whole
    boundary with the selected profile.
    """

    from contextlib import contextmanager

    class _ManifestBoundaryReached(Exception):
        """Raised by the evidence double exactly at `evidence.write_manifest`."""

    manifests: list[dict] = []

    class _RecordingEvidence:
        def write_manifest(self, payload: dict) -> None:
            manifests.append(payload)
            raise _ManifestBoundaryReached("short profile reached the evidence contract")

    class _OwnerlessProcessObserver:
        """Stands in for `_LockedPsutilObserver`: host inspection, not selection."""

        def __init__(self, psutil_module: object) -> None:
            self._psutil_module = psutil_module

        def identity_for_pid(self, pid: int) -> tuple[str, int]:
            return ("test-owner", pid)

        def descendants(self, owner: tuple[str, int], *, include_zombies: bool = False) -> tuple:
            return ()

    snapshot_shas: list[str] = []

    @contextmanager
    def _still_snapshot(git_sha: str):
        snapshot_shas.append(git_sha)
        yield object()

    sealed_fixture_payload = {"schema": "cryodaq-soak-source-fixture/v1", "fixture": "test-double"}

    class _StillSealedFixture:
        payload = sealed_fixture_payload

    def _still_materialized(config_dir: Path, *, report_interval_s: int, source_snapshot: object) -> int:
        assert type(report_interval_s) is int and report_interval_s > 0
        return 1

    def _still_sealed(config_dir: Path, *, expected_readings_per_sample: int) -> _StillSealedFixture:
        assert type(expected_readings_per_sample) is int and expected_readings_per_sample > 0
        return _StillSealedFixture()

    monkeypatch.setattr(runner, "_LockedPsutilObserver", _OwnerlessProcessObserver)
    monkeypatch.setattr(runner, "_sealed_execution_snapshot", _still_snapshot)
    monkeypatch.setattr(runner, "_materialize_complete_soak_config", _still_materialized)
    monkeypatch.setattr(runner, "_source_fixture_seal", _still_sealed)

    instance = _runner_at_the_selection_boundary(monkeypatch)
    selected = soak.profile("short")

    # The sentinel class IS the assertion that neither refusal fired: both
    # refusals raise `_RunnerFoundationError`, which is not this sentinel.
    with pytest.raises(_ManifestBoundaryReached):
        instance._run_owned(_RecordingEvidence(), selected)

    assert len(manifests) == 1, "the boundary must publish exactly one manifest"
    manifest = manifests[0]
    assert manifest["profile"] == "short"
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["git_sha"]) is not None, manifest["git_sha"]
    assert snapshot_shas == [manifest["git_sha"]], "the sealed snapshot and manifest must name one commit"
    assert manifest["thresholds"] == soak.effective_thresholds(soak.profile("short"))
    assert manifest["periodic_schedule"]["expected_receipts"] == 2
    assert manifest["source_fixture"] == sealed_fixture_payload
    assert manifest["dirty"] is False


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
