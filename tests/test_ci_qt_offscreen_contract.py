"""The nightly Qt-dependent jobs must install the libraries Qt loads at import.

Run 33247186128 is why this file exists. Both acceptance-criteria guards in the
nightly workflow -- the golden-run replay regression, which is how a
misrepresented dataset is caught, and the short mock-stack soak, which is how
memory growth and lag are caught -- failed on `ImportError: libEGL.so.1`. Neither
failed an assertion: the replay lane reported `36 errors during collection` and
ran none of its 9296 collected-then-deselected nodes, and the soak never brought
the stack up, recording `still missing: roles, handshake, bridge, bridge_guard`.
Five consecutive nightly runs across three commits, the oldest 2026-08-25, were
red this way. A job in that state is not failing loudly; it is BLIND, and a blind
guard is indistinguishable from a passing one on the summary line.

`main.yml` had the install step and stayed green throughout, so the defect was
divergence between the two workflows, not a missing discovery. These guards bind
that pairing.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

#: Copied from the step, not restated. Asserting the whole line rather than the
#: package names individually is deliberate: it fails both when the step is
#: dropped and when one workflow's package list drifts away from the other's.
QT_PACKAGE_LINE = "for package in libegl1 libgl1 libxkbcommon0 libdbus-1-3; do"

QT_STEP_NAME = "Install Qt offscreen system libraries (Linux)"

#: The nightly jobs that import PySide6, transitively, through the launcher.
#: `mock-soak` is deliberately absent -- it was green throughout run 33247186128
#: and needs no Qt libraries, so requiring them there would buy nothing.
QT_DEPENDENT_NIGHTLY_JOBS = ("golden-replay", "mock-stack-short-soak")


def _workflow(relative: str) -> dict:
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))


def test_qt_dependent_nightly_jobs_install_qt_libraries() -> None:
    """Presence per JOB, because the workflow-wide check cannot see this.

    A file-level containment assertion passes as soon as one job carries the
    step, which is exactly the half-fixed state a hand edit produces when a
    workflow has more than one job that needs it.
    """
    jobs = _workflow(".github/workflows/nightly.yml")["jobs"]

    for job_id in QT_DEPENDENT_NIGHTLY_JOBS:
        assert job_id in jobs, f"nightly.yml has no job {job_id!r}; jobs are {sorted(jobs)}"
        step_names = [str(step.get("name", "")) for step in jobs[job_id]["steps"]]
        assert QT_STEP_NAME in step_names, (
            f"nightly job {job_id!r} imports PySide6 but has no {QT_STEP_NAME!r} step. "
            "Without it the job dies during collection on `ImportError: libEGL.so.1` "
            "and reports a red that has measured nothing at all. Its steps are: "
            f"{step_names}"
        )


def test_qt_library_list_is_identical_in_both_workflows() -> None:
    """The nightly list must not drift from the list main.yml proves works.

    main.yml's Linux jobs are the standing evidence that this exact set is
    sufficient; a nightly copy that quietly loses a package would reintroduce
    the same blindness under a different library name.
    """
    for relative in (".github/workflows/main.yml", ".github/workflows/nightly.yml"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert QT_PACKAGE_LINE in text, (
            f"{relative} no longer installs exactly {QT_PACKAGE_LINE!r}. "
            "If the set genuinely needs to change, change it in both workflows in "
            "the same commit and update this guard with the run that measured it."
        )
