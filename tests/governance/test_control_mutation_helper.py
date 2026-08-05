"""Prevention ``CONTROL-WITHOUT-VERIFIED-MUTATION-302``.

`tests/support/control_mutation.py` exists so that a red-before control cannot
report a comforting result while having changed nothing.  These nodes hold it
to that, because a helper whose refusals are untested is itself a guard nobody
has attacked.

The node that matters most is the no-op one.  On 2026-08-05 a control's string
anchor matched OC-008's wording (`89 of the 135 entries, counted by path`) and
not OC-031's (`89 of the 135 counted by path`).  It replaced nothing, the suite
ran unchanged, and the pass was recorded as evidence that a guard held.  Nothing
in the output distinguished it from a control that had reverted production and
found the guard genuinely covering.  That is why the check has to be a refusal
rather than a warning: the caller cannot tell the two apart afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.control_mutation import (
    ControlNotApplied,
    ControlNotRestored,
    control_mutation,
)

PRODUCTION = "if descriptor is not None and descriptor.legacy:\n    descriptor = None\n"


def _target(tmp_path: Path) -> Path:
    path = tmp_path / "production.py"
    path.write_bytes(PRODUCTION.encode("utf-8"))
    return path


def test_a_control_that_matches_nothing_refuses_instead_of_reporting_a_pass(tmp_path: Path) -> None:
    """The 2026-08-05 failure, as a behaviour.

    The old wording is gone and the anchor no longer matches.  Without this
    refusal the body would run against untouched production and its green
    result would be recorded as a control.
    """

    path = _target(tmp_path)
    with pytest.raises(ControlNotApplied, match="matched 0 time"):
        with control_mutation(path, old="descriptor.deprecated_flag", new="False"):
            pytest.fail("the body must never run when the anchor did not match")

    assert path.read_bytes() == PRODUCTION.encode("utf-8")


def test_a_replacement_identical_to_its_anchor_refuses(tmp_path: Path) -> None:
    """A copy-paste control that reverts nothing is the same silent failure."""

    path = _target(tmp_path)
    with pytest.raises(ControlNotApplied, match="identical to its anchor"):
        with control_mutation(path, old="descriptor.legacy", new="descriptor.legacy"):
            pytest.fail("the body must never run for a no-op replacement")


def test_an_ambiguous_anchor_refuses_rather_than_reverting_an_arbitrary_one(tmp_path: Path) -> None:
    """Two matches means the control does not know what it reverted."""

    path = tmp_path / "production.py"
    path.write_bytes(b"value = 1\nvalue = 1\n")
    with pytest.raises(ControlNotApplied, match="matched 2 time"):
        with control_mutation(path, old="value = 1", new="value = 2"):
            pytest.fail("the body must never run for an ambiguous anchor")


def test_a_control_that_applies_yields_and_the_target_really_changed(tmp_path: Path) -> None:
    """The positive case, asserted on the BYTES rather than on the intent."""

    path = _target(tmp_path)
    original = path.read_bytes()
    with control_mutation(path, old="descriptor.legacy", new="False") as applied:
        on_disk = path.read_bytes()
        assert on_disk != original, "the helper yielded without changing the file"
        assert b"descriptor.legacy" not in on_disk
        assert applied.original == original
        assert applied.mutated == on_disk
        assert applied.byte_delta == len(on_disk) - len(original)

    assert path.read_bytes() == original, "the target was not restored byte-identical"


def test_restoration_survives_a_failing_body(tmp_path: Path) -> None:
    """A control whose body fails is the NORMAL case -- red-before is the point.

    The target must still come back, or every later measurement in the session
    is made against a modified tree.
    """

    path = _target(tmp_path)
    original = path.read_bytes()
    with pytest.raises(RuntimeError):
        with control_mutation(path, old="descriptor.legacy", new="False"):
            raise RuntimeError("the guard went red, which is what a control is for")

    assert path.read_bytes() == original


def test_a_failed_restore_is_raised_and_not_swallowed(tmp_path: Path) -> None:
    """If the tree cannot be put back, the session must be told loudly."""

    path = _target(tmp_path)
    original = path.read_bytes()
    real_write = Path.write_bytes
    calls: list[int] = []

    def sabotage(self: Path, data: bytes) -> int:
        calls.append(1)
        # Let the mutation write through; corrupt only the restore.
        payload = data if len(calls) == 1 else b"not the original\n"
        return real_write(self, payload)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "write_bytes", sabotage)
        with pytest.raises(ControlNotRestored):
            with control_mutation(path, old="descriptor.legacy", new="False"):
                pass

    real_write(path, original)


def test_a_write_that_lands_is_restored_even_if_the_verifying_read_fails(tmp_path: Path) -> None:
    """The restoration scope must open BEFORE the write, not after it.

    Codex found this on `b0a29cb1`: the write landed, the verifying `read_bytes`
    raised, and the function returned without ever entering `try/finally` --
    leaving the target mutated and silently contaminating every later
    measurement in the session. A fail-closed restoration contract that can be
    escaped by a transient read error is not fail-closed.
    """

    path = tmp_path / "production.py"
    path.write_bytes(b"value = 1\n")
    original = path.read_bytes()
    real_read = Path.read_bytes
    seen: list[int] = []

    def flaky_read(self: Path) -> bytes:
        seen.append(1)
        if len(seen) == 2:  # the read immediately after the mutation write
            raise OSError("transient filesystem error")
        return real_read(self)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "read_bytes", flaky_read)
        with pytest.raises(OSError, match="transient"):
            with control_mutation(path, old="value = 1", new="value = 2"):
                pytest.fail("the body must not run when verification failed")

    assert real_read(path) == original, "the target was left mutated after a failed verification"


def test_a_partial_revert_is_refused_when_the_control_names_what_it_removes(tmp_path: Path) -> None:
    """The second 2026-08-05 failure class, and the one the anchor count misses.

    Reverting a CSV header while leaving the data rows nine fields wide matched
    its anchor exactly once and changed bytes, so no count check could catch it.
    It produced 1 of 7 red instead of 6 of 7 -- indistinguishable from a weak
    guard unless you already suspect the control.
    """

    path = tmp_path / "writer.py"
    path.write_bytes(b'HEADER = ["ts", "descriptor_hash"]\nROW = [ts, descriptor_hash]\n')
    original = path.read_bytes()

    with pytest.raises(ControlNotApplied, match="reverts only part"):
        with control_mutation(
            path,
            old='HEADER = ["ts", "descriptor_hash"]',
            new='HEADER = ["ts"]',
            expect_absent=["descriptor_hash"],
        ):
            pytest.fail("the body must not run for a partial revert")

    assert path.read_bytes() == original

    # The COMPLETE revert of the same behaviour is accepted.
    with control_mutation(
        path,
        old='HEADER = ["ts", "descriptor_hash"]\nROW = [ts, descriptor_hash]',
        new='HEADER = ["ts"]\nROW = [ts]',
        expect_absent=["descriptor_hash"],
    ):
        assert b"descriptor_hash" not in path.read_bytes()

    assert path.read_bytes() == original


def test_expect_absent_is_opt_in_and_does_not_change_existing_controls(tmp_path: Path) -> None:
    """Silence must keep meaning what it meant.

    If omitting `expect_absent` started refusing controls, every existing caller
    would break at once and the pressure would be to stop using the helper --
    which is worse than the failure it prevents.
    """

    path = tmp_path / "production.py"
    path.write_bytes(b"alpha = 1\nalpha_helper = 1\n")
    with control_mutation(path, old="alpha = 1", new="alpha = 2"):
        assert b"alpha_helper = 1" in path.read_bytes()


def test_crlf_bytes_are_not_rewritten_by_the_round_trip(tmp_path: Path) -> None:
    """Newline translation is how a 'restored' file silently stops matching.

    The helper works in bytes for this reason; a text-mode round trip on Windows
    would rewrite every line ending in a file it is supposed to leave alone.
    """

    path = tmp_path / "crlf.py"
    path.write_bytes(b"alpha = 1\r\nbeta = 2\r\n")
    original = path.read_bytes()

    with control_mutation(path, old="beta = 2", new="beta = 3"):
        assert b"\r\n" in path.read_bytes()

    assert path.read_bytes() == original
    assert b"\r\n" in path.read_bytes()
