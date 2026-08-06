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

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.control_mutation import (
    ControlNotApplied,
    ControlNotRestored,
    ControlTargetChanged,
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
    real_write = Path.write_bytes
    written: list[int] = []

    def counting_write(self: Path, data: bytes) -> int:
        written.append(1)
        return real_write(self, data)

    failed_once: list[int] = []

    def flaky_read(self: Path) -> bytes:
        # Fail exactly ONCE, on the first read after the mutation write --
        # whichever ordinal that is. Counting raw calls made this test brittle:
        # adding the pre-write compare shifted the index and it would have
        # sabotaged the wrong read. Failing repeatedly is also wrong: it would
        # break the restore itself and assert something this node is not about.
        if written and not failed_once:
            failed_once.append(1)
            raise OSError("transient filesystem error")
        return real_read(self)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "write_bytes", counting_write)
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


def test_a_restored_file_is_not_shadowed_by_the_mutant_bytecode(tmp_path: Path) -> None:
    """The sharpest escape found so far, and it needs a real interpreter to see.

    Source-timestamp `.pyc` invalidation compares mtime AND SIZE. A control
    whose replacement is the same length as its anchor, restored inside the same
    timestamp second, leaves both unchanged -- so a `.pyc` written from the
    MUTANT during the control body stays valid, and the next process loads the
    mutant while `read_bytes()` on the source reads correct. Every later
    measurement in the session is then made against code nobody can see on disk.

    Codex reproduced this on `6c27f0ee`. This node reproduces it through actual
    child interpreters rather than reasoning about the loader.
    """

    module = tmp_path / "victim.py"
    module.write_bytes(b"VALUE = 1\n")
    program = f"import sys; sys.path.insert(0, {str(tmp_path)!r}); import victim; print(victim.VALUE)"

    def child() -> str:
        done = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, check=True)
        return done.stdout.strip()

    assert child() == "1", "premise: the child must see the original value"

    with control_mutation(module, old="VALUE = 1", new="VALUE = 2") as applied:
        assert len(applied.mutated) == len(applied.original), (
            "premise: the replacement must be the same length, or the size check would catch it"
        )
        assert child() == "2", "premise: the child must see the mutant and cache bytecode for it"

    assert module.read_bytes() == b"VALUE = 1\n"
    assert child() == "1", "a child interpreter still loaded the mutant from cached bytecode after restore"


def test_an_edit_landing_before_the_mutation_write_is_preserved(tmp_path: Path) -> None:
    """The window at the OTHER end, which the restoration check cannot see.

    Guarding only the restore protected the wrong side: another writer landing
    between the helper's read and its write was erased by the mutation itself,
    and the control then measured -- and dutifully restored -- a file whose real
    content it had already destroyed. Codex reproduced it after the restore-side
    fix.
    """

    path = tmp_path / "shared.py"
    path.write_bytes(b"value = 1\n")
    original = path.read_bytes()
    real_read = Path.read_bytes
    reads: list[int] = []

    def read_then_let_someone_else_write(self: Path) -> bytes:
        data = real_read(self)
        reads.append(1)
        if len(reads) == 1:  # the helper's initial read of the original
            real_write = Path.write_bytes
            real_write(path, b"value = 3  # concurrent\n")
        return data

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "read_bytes", read_then_let_someone_else_write)
        with pytest.raises(ControlTargetChanged):
            with control_mutation(path, old="value = 1", new="value = 2"):
                pytest.fail("the body must not run once the target has moved under us")

    assert real_read(path) == b"value = 3  # concurrent\n", (
        "the mutation erased a concurrent edit that landed after the helper's read"
    )
    assert real_read(path) != original


def test_a_concurrent_edit_is_preserved_rather_than_overwritten(tmp_path: Path) -> None:
    """Restoring over someone else's work and calling it success is worse than failing.

    The helper restores only what it put there. Anything else on disk means a
    second author, and their bytes are left for adjudication.
    """

    path = tmp_path / "shared.py"
    path.write_bytes(b"value = 1\n")

    with pytest.raises(ControlTargetChanged):
        with control_mutation(path, old="value = 1", new="value = 2"):
            path.write_bytes(b"value = 3  # concurrent author\n")

    assert path.read_bytes() == b"value = 3  # concurrent author\n", (
        "the helper overwrote a concurrent edit with its own stale snapshot"
    )


def test_a_relative_target_survives_the_body_changing_directory(tmp_path: Path) -> None:
    """A relative path is re-resolved at every use, and cwd is process-global.

    Reproduced by Codex: a control on `a/x.py` whose body chdirs into `b` exits
    reporting success, with `a/x.py` still mutated and a helpfully created
    `b/x.py` holding the original bytes.
    """

    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    target = first / "x.py"
    target.write_bytes(b"value = 1\n")

    origin = Path.cwd()
    os.chdir(tmp_path)
    try:
        with control_mutation(Path("a/x.py"), old="value = 1", new="value = 2"):
            os.chdir(second)
            assert (first / "x.py").read_bytes() == b"value = 2\n"
    finally:
        os.chdir(origin)

    assert target.read_bytes() == b"value = 1\n", "the original target was left mutated"
    assert not (second / "x.py").exists(), "the helper wrote the restore into the wrong directory"


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
