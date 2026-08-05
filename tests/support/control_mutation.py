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

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

__all__ = ["AppliedControl", "ControlNotApplied", "ControlNotRestored", "control_mutation"]


class ControlNotApplied(AssertionError):
    """The control did not change the target, so any result from it is void.

    Deliberately an ``AssertionError``: a control that did not apply is not an
    infrastructure hiccup to be logged and stepped over, it invalidates the
    conclusion the caller was about to draw.
    """


class ControlNotRestored(AssertionError):
    """The target was left modified. The working tree is now untrustworthy."""


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
    encoding: str = "utf-8",
) -> Iterator[AppliedControl]:
    """Replace ``old`` with ``new`` in ``path`` for the body, then restore.

    Raises `ControlNotApplied` -- before running anything -- if the anchor does
    not appear exactly ``occurrences`` times, or if the replacement leaves the
    file's bytes unchanged.  Raises `ControlNotRestored` if the original bytes
    are not back on disk afterwards.

    A restore failure raised from the ``finally`` block will displace an
    exception in flight from the body.  That is the intended precedence: a
    modified working tree invalidates every later measurement in the session,
    whereas the body's failure is usually the result the caller wanted.
    """

    if occurrences < 1:
        raise ValueError("a control must replace at least one occurrence")

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

    path.write_bytes(mutated)
    on_disk = path.read_bytes()
    if on_disk == original:
        raise ControlNotApplied(f"control wrote {path} but the bytes on disk did not change")

    try:
        yield AppliedControl(path=path, original=original, mutated=on_disk)
    finally:
        path.write_bytes(original)
        if path.read_bytes() != original:
            raise ControlNotRestored(f"{path} was not restored byte-identical; the working tree is modified")
