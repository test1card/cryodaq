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
divergence between the two workflows, not a missing discovery.

The binding is PER JOB and BY CONTENT, and the reason is a hole review found in
the first version of this file. That version asserted the package line was
present somewhere in `nightly.yml`. Shortening the loop in ONE job then left both
assertions green: the per-job check only looked for the step's NAME, and the
file-wide check still found the intact line in the OTHER job. The replay lane
could go blind again under a green guard. Each job's step is now compared
against the canonical `main.yml` step field by field.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

MAIN_WORKFLOW = ".github/workflows/main.yml"
NIGHTLY_WORKFLOW = ".github/workflows/nightly.yml"

QT_STEP_NAME = "Install Qt offscreen system libraries (Linux)"

#: The job in `main.yml` whose step is the standing evidence that this exact set
#: of packages is sufficient: its Linux legs were green through run 33247186128.
CANONICAL_JOB = "test"

#: Copied from the step, not restated, so that a silent narrowing of the list in
#: the canonical step itself is caught rather than propagated to the copies.
QT_PACKAGE_LINE = "for package in libegl1 libgl1 libxkbcommon0 libdbus-1-3; do"

#: The nightly jobs that import PySide6, transitively, through the launcher.
#: `mock-soak` is deliberately absent -- it was green throughout run 33247186128
#: and needs no Qt libraries, so requiring them there would buy nothing.
QT_DEPENDENT_NIGHTLY_JOBS = ("golden-replay", "mock-stack-short-soak")

#: Compared field by field rather than by the whole mapping, so that an
#: unrelated future key on one side names itself instead of failing opaquely.
BOUND_STEP_FIELDS = ("run", "if", "timeout-minutes", "env")


def _workflow(relative: str) -> dict:
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))


def _qt_step(workflow: dict, job_id: str, relative: str) -> dict:
    jobs = workflow["jobs"]
    assert job_id in jobs, f"{relative} has no job {job_id!r}; jobs are {sorted(jobs)}"
    steps = [step for step in jobs[job_id]["steps"] if str(step.get("name", "")) == QT_STEP_NAME]
    assert len(steps) == 1, (
        f"job {job_id!r} in {relative} carries {len(steps)} steps named {QT_STEP_NAME!r}, expected exactly 1. "
        "Without it the job dies during collection on `ImportError: libEGL.so.1` and reports a red "
        "that has measured nothing at all."
    )
    return steps[0]


def test_canonical_qt_step_still_installs_the_evidenced_package_set() -> None:
    """Anchor the content itself, since the copies are compared against it.

    Every other assertion here compares a nightly job to this step. If the
    canonical step quietly lost a package, the copies would still match it and
    every check would stay green while all three jobs went blind together.
    """
    canonical = _qt_step(_workflow(MAIN_WORKFLOW), CANONICAL_JOB, MAIN_WORKFLOW)

    assert QT_PACKAGE_LINE in canonical["run"], (
        f"the canonical {QT_STEP_NAME!r} step in {MAIN_WORKFLOW} no longer runs {QT_PACKAGE_LINE!r}. "
        "If the set genuinely needs to change, change it here and in every job listed in "
        "QT_DEPENDENT_NIGHTLY_JOBS in the same commit, and record the run that measured it."
    )


def test_qt_dependent_nightly_jobs_match_the_canonical_step() -> None:
    """Per job and by CONTENT, because neither weaker form catches a half-fix.

    Checking only the step name lets the script be gutted underneath it.
    Checking the package line file-wide passes as soon as any ONE job still
    carries it, which is exactly the state that leaves the other job blind.
    """
    canonical = _qt_step(_workflow(MAIN_WORKFLOW), CANONICAL_JOB, MAIN_WORKFLOW)
    nightly = _workflow(NIGHTLY_WORKFLOW)

    for job_id in QT_DEPENDENT_NIGHTLY_JOBS:
        step = _qt_step(nightly, job_id, NIGHTLY_WORKFLOW)
        for field in BOUND_STEP_FIELDS:
            assert step.get(field) == canonical.get(field), (
                f"nightly job {job_id!r} has a {QT_STEP_NAME!r} step whose {field!r} differs from the "
                f"canonical step in {MAIN_WORKFLOW} job {CANONICAL_JOB!r}. The two must stay identical: "
                "the canonical one is the only version with standing evidence that it works, and a "
                "divergent copy is how this job went blind in run 33247186128.\n"
                f"  nightly:   {step.get(field)!r}\n"
                f"  canonical: {canonical.get(field)!r}"
            )
