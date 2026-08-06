"""Apply a red-before control and REFUSE to run it unless the target changed.

A red-before control is the only evidence that a guard guards anything.  Three
of them on 2026-08-05 were subtly wrong, and every one reported something
reassuring:

* reverting only a CSV header left the data rows nine fields wide, so 1 of 7
  went red instead of 6 of 7 -- which reads as a weak guard rather than a
  partial revert;
* reverting only a loader's BASE class produced a fail-closed refusal instead
  of the silent substitution the test claimed to prove -- red for the wrong
  reason;
* a string replacement matched one register row's wording and not the other's,
  so it mutated NOTHING and reported a pass.

The third is the dangerous one, because a control that changes nothing produces
exactly the output of a control that changed everything and found no defect.
The failure is silent by construction.

So this helper refuses rather than reports.  It will not yield unless the bytes
on disk actually differ from the bytes that were there before, and it will not
return quietly unless the file was restored byte-identical afterwards.  Callers
cannot opt out of either check; that is the whole point.

Bytes, not text, deliberately.  Reading and rewriting through the text layer is
how newline translation silently rewrites a file this helper is supposed to
leave untouched -- the same measurement-layer class as the failures above.

Usage::

    with control_mutation(target, old=PRODUCTION_LINE, new=REVERTED_LINE):
        result = run_the_suite()
    assert result.failed, "the guard did not notice the reverted production code"
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "AppliedControl",
    "ControlNotApplied",
    "ControlNotRestored",
    "ControlTargetChanged",
    "control_mutation",
]


class ControlNotApplied(AssertionError):
    """The control did not change the target, so any result from it is void.

    Deliberately an ``AssertionError``: a control that did not apply is not an
    infrastructure hiccup to be logged and stepped over, it invalidates the
    conclusion the caller was about to draw.
    """


class ControlNotRestored(AssertionError):
    """The target was left modified. The working tree is now untrustworthy."""


class ControlTargetChanged(AssertionError):
    """Someone else edited the target while the control held it.

    Restoring would destroy their work and then report success, so the helper
    refuses and leaves the file exactly as found for adjudication.  A control
    that quietly overwrote a concurrent author would be a worse outcome than
    the measurement it was protecting.
    """


def _invalidate_bytecode(path: Path) -> None:
    """Drop any cached ``.pyc`` for ``path``.

    Source-timestamp invalidation compares mtime AND SIZE.  A control whose
    replacement is the same length as its anchor -- ``VALUE = 1`` to
    ``VALUE = 2`` -- restored inside the same timestamp second leaves both
    unchanged, so a ``.pyc`` written from the MUTANT during the control body is
    still considered valid afterwards and the next interpreter loads the mutant
    while the source on disk reads correct.  Codex reproduced exactly that.

    Every cache tag is removed, not just this interpreter's.  A control can run
    under one supported Python and launch a child under another --
    `cache_from_source()` names only the RUNNING interpreter's tag, so a helper
    on 3.12 left `victim.cpython-314.pyc` in place and the next 3.14 child
    loaded the mutant. Codex reproduced that after the single-tag fix, which is
    why this globs the whole `__pycache__` entry for the stem instead.
    """

    for cached in path.parent.glob(f"__pycache__/{path.stem}.*.pyc"):
        with contextlib.suppress(OSError):
            os.remove(cached)
    # Legacy same-directory `.pyc`, and any cache this interpreter would name
    # that the glob above cannot see.
    with contextlib.suppress(NotImplementedError, ValueError, OSError):
        os.remove(importlib.util.cache_from_source(str(path)))


@dataclass(frozen=True, slots=True)
class AppliedControl:
    """What the control actually did, for callers that want to assert on it."""

    path: Path
    original: bytes
    mutated: bytes

    @property
    def byte_delta(self) -> int:
        return len(self.mutated) - len(self.original)


@contextmanager
def control_mutation(
    path: Path,
    *,
    old: str,
    new: str,
    occurrences: int = 1,
    expect_absent: Sequence[str] = (),
    encoding: str = "utf-8",
) -> Iterator[AppliedControl]:
    """Replace ``old`` with ``new`` in ``path`` for the body, then restore.

    Raises `ControlNotApplied` -- before running anything -- if the anchor does
    not appear exactly ``occurrences`` times, or if the replacement leaves the
    file's bytes unchanged.  Raises `ControlNotRestored` if the original bytes
    are not back on disk afterwards.

    ``expect_absent`` addresses a DIFFERENT failure from the anchor count: a
    control that applies cleanly but reverts only part of the behaviour.
    Reverting a CSV header while leaving the data rows nine fields wide matched
    its anchor once, changed bytes, and produced 1 of 7 red instead of 6 of 7 --
    which reads as a weak guard rather than a partial revert.  Naming the
    symbols the revert is supposed to remove turns that into a refusal: each
    string must not appear anywhere in the mutated file.

    A restore failure raised from the ``finally`` block will displace an
    exception in flight from the body.  That is the intended precedence: a
    modified working tree invalidates every later measurement in the session,
    whereas the body's failure is usually the result the caller wanted.
    """

    if occurrences < 1:
        raise ValueError("a control must replace at least one occurrence")

    # Resolve ONCE, before anything else.  A relative path is re-resolved
    # against the process working directory at every use, so a control body
    # that chdirs -- or any code it calls that does -- would leave the mutant in
    # place and helpfully write the "restored" original into a file of the same
    # name in the new directory. Codex reproduced that too.
    path = Path(path).resolve()

    original = path.read_bytes()
    text = original.decode(encoding)
    found = text.count(old)
    if found != occurrences:
        raise ControlNotApplied(
            f"control anchor matched {found} time(s) in {path}, expected {occurrences}; "
            "the control would have measured nothing and reported a pass"
        )
    if old == new:
        raise ControlNotApplied(f"control replacement is identical to its anchor in {path}")

    mutated = text.replace(old, new, occurrences).encode(encoding)
    if mutated == original:
        raise ControlNotApplied(f"control replacement left {path} byte-identical")

    # The restoration scope opens BEFORE the write.  If the write lands and the
    # verifying read then fails -- a transient filesystem error is enough --
    # returning here would leave the target mutated and silently contaminate
    # every later measurement in the session.  Nothing between here and the
    # `finally` may exit by any other route.
    # Bound before the try so the restore can still recognise its own write if
    # the verifying read below raises.
    on_disk = mutated
    try:
        # Write only if the target is still what was read.  The restoration
        # check alone protected the wrong end: another writer landing between
        # the read above and this write was erased before anything could notice,
        # and the control then measured -- and restored -- a file whose real
        # content it had destroyed. This narrows that window to the gap between
        # these two adjacent statements; it does NOT close it, because there is
        # no atomic compare-and-write here, and pretending otherwise would be
        # the same overclaim this helper exists to prevent.
        if path.read_bytes() != original:
            raise ControlTargetChanged(
                f"{path} changed between the control's read and its write; refusing to mutate. "
                "Reconcile the file before trusting any measurement from this session."
            )
        path.write_bytes(mutated)
        _invalidate_bytecode(path)
        on_disk = path.read_bytes()
        if on_disk == original:
            raise ControlNotApplied(f"control wrote {path} but the bytes on disk did not change")

        residue = [needle for needle in expect_absent if needle in on_disk.decode(encoding)]
        if residue:
            raise ControlNotApplied(
                f"control applied to {path} but left {residue} in place; it reverts only part of the "
                "behaviour, so a small red set means an incomplete control rather than a weak guard"
            )

        yield AppliedControl(path=path, original=original, mutated=on_disk)
    finally:
        # Restore only what THIS control put there.  If the bytes on disk are
        # neither the mutant nor already the original, someone else edited the
        # file while the control held it -- restoring would destroy their work
        # and then report success.  Refuse, and leave the path exactly as found
        # so it can be adjudicated.
        current = path.read_bytes()
        if current not in (on_disk, original):
            raise ControlTargetChanged(
                f"{path} was edited by something else while the control held it; refusing to overwrite. "
                "The file is left as found -- reconcile it before trusting any measurement from this session."
            )
        path.write_bytes(original)
        _invalidate_bytecode(path)
        if path.read_bytes() != original:
            raise ControlNotRestored(f"{path} was not restored byte-identical; the working tree is modified")
