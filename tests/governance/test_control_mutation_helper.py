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
