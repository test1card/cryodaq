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

Successive review rounds each found a mutation an earlier version of this file
survived. Every one is kept here as a test rather than as prose, because each is
a distinct way the jobs go blind again underneath a green guard:

- the package line present *somewhere* in the file, while one job alone is gutted;
- the step present by NAME, while its script is replaced;
- the script bound as TEXT, while the `dpkg` probe is neutered so that nothing is
  ever marked missing;
- the script exercised under `bash -c`, while production runs it through the
  `bash -el` login shell whose `~/.bash_logout` is what turned four successful
  installs into four failed jobs in run 32306229771;
- the step present and correct, but ORDERED after the command that needs it;
- `apt-get` reached, but with `--simulate`, so nothing is installed;
- every package probed together, hiding a script that only ever probes one;
- the first install failing, with the documented refresh-and-retry branch never
  exercised;
- `continue-on-error: true` added, so a failed install no longer stops the job;
- a NEW nightly job added with no step at all, outside a hand-maintained list.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

MAIN_WORKFLOW = ".github/workflows/main.yml"
NIGHTLY_WORKFLOW = ".github/workflows/nightly.yml"

QT_STEP_NAME = "Install Qt offscreen system libraries (Linux)"
CANONICAL_JOB = "test"

QT_PACKAGES = ("libegl1", "libgl1", "libxkbcommon0", "libdbus-1-3")
QT_PACKAGE_LINE = "for package in " + " ".join(QT_PACKAGES) + "; do"

#: EVERY nightly job is classified, and the guard fails when one appears that is
#: not. A hand-maintained list of only the Qt-dependent jobs cannot see a new job
#: at all: it would simply never be inspected, which is the same silence the
#: original defect had. `mock-soak` is False because it was green throughout run
#: 33247186128 without Qt libraries, so requiring them there would prevent
#: nothing.
NIGHTLY_JOB_NEEDS_QT = {
    "golden-replay": True,
    "mock-stack-short-soak": True,
    "mock-soak": False,
}

#: The workflows run every step through a LOGIN shell, and that is not
#: incidental. The step's own comments record run 32306229771, where all four
#: Linux jobs installed the library, printed their success line and then reported
#: failure, because `~/.bash_logout` runs `clear_console` at SHLVL 1 and its
#: status replaced the script's own. Exercising the script any other way cannot
#: observe that class of defect at all.
WORKFLOW_SHELL = "bash -el {0}"

#: Flags under which apt-get reports success while installing nothing.
SIMULATION_FLAGS = frozenset({"--simulate", "-s", "--dry-run", "--just-print", "--no-act", "--recon"})


def _workflow(relative: str) -> dict:
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))


def _steps(workflow: dict, job_id: str, relative: str) -> list[dict]:
    jobs = workflow["jobs"]
    assert job_id in jobs, f"{relative} has no job {job_id!r}; jobs are {sorted(jobs)}"
    return list(jobs[job_id]["steps"])


def _qt_step_index(steps: list[dict], job_id: str, relative: str) -> int:
    found = [i for i, step in enumerate(steps) if str(step.get("name", "")) == QT_STEP_NAME]
    assert len(found) == 1, (
        f"job {job_id!r} in {relative} carries {len(found)} steps named {QT_STEP_NAME!r}, "
        "expected exactly 1. Without it the job dies during collection on "
        "`ImportError: libEGL.so.1` and reports a red that has measured nothing at all."
    )
    return found[0]


def _qt_step(workflow: dict, job_id: str, relative: str) -> dict:
    steps = _steps(workflow, job_id, relative)
    return steps[_qt_step_index(steps, job_id, relative)]


def _canonical_step() -> dict:
    return _qt_step(_workflow(MAIN_WORKFLOW), CANONICAL_JOB, MAIN_WORKFLOW)


def _qt_dependent_jobs() -> tuple[str, ...]:
    return tuple(job for job, needs in NIGHTLY_JOB_NEEDS_QT.items() if needs)


def test_every_nightly_job_is_classified_for_qt() -> None:
    """A new job must not be able to join the workflow uninspected.

    The guarded set is derived from this classification, so an unclassified job
    fails here rather than silently falling outside every other assertion in
    this file.
    """
    declared = set(NIGHTLY_JOB_NEEDS_QT)
    actual = set(_workflow(NIGHTLY_WORKFLOW)["jobs"])

    assert actual == declared, (
        "every nightly job must be explicitly classified as needing Qt libraries or not. "
        f"unclassified: {sorted(actual - declared)}; "
        f"classified but absent: {sorted(declared - actual)}. "
        "An unclassified job is inspected by no other guard here, which is exactly the silence "
        "that let run 33247186128 report red while measuring nothing."
    )


def test_canonical_qt_step_still_installs_the_evidenced_package_set() -> None:
    """Anchor the content itself, since every copy is compared against it."""
    canonical = _canonical_step()
    assert QT_PACKAGE_LINE in canonical["run"], (
        f"the canonical {QT_STEP_NAME!r} step in {MAIN_WORKFLOW} no longer runs "
        f"{QT_PACKAGE_LINE!r}. If the set genuinely needs to change, change it here and in every "
        "Qt-dependent nightly job in the same commit, and record the run that measured it."
    )


def test_qt_dependent_nightly_steps_equal_the_canonical_step_entirely() -> None:
    """WHOLE-mapping equality, so no behaviour-bearing key can be added.

    Comparing a chosen list of fields let `continue-on-error: true` be added to a
    copy while every assertion stayed green; Actions would then walk on into the
    command that needs the libraries after the install had already failed.
    """
    canonical = _canonical_step()
    nightly = _workflow(NIGHTLY_WORKFLOW)

    for job_id in _qt_dependent_jobs():
        step = _qt_step(nightly, job_id, NIGHTLY_WORKFLOW)
        assert step == canonical, (
            f"nightly job {job_id!r} has a {QT_STEP_NAME!r} step that is not identical to the "
            f"canonical step in {MAIN_WORKFLOW} job {CANONICAL_JOB!r}. The canonical one is the "
            "only version with standing evidence that it works, and a divergent copy is how this "
            f"job went blind in run 33247186128.\n  nightly keys:   {sorted(step)}\n"
            f"  canonical keys: {sorted(canonical)}"
        )


def test_the_install_step_precedes_every_step_that_runs_python() -> None:
    """Position, not merely presence.

    An unchanged step moved to the end of the job leaves every content assertion
    green while the lane that needs the libraries has already run and failed.
    """
    nightly = _workflow(NIGHTLY_WORKFLOW)

    for job_id in _qt_dependent_jobs():
        steps = _steps(nightly, job_id, NIGHTLY_WORKFLOW)
        install_at = _qt_step_index(steps, job_id, NIGHTLY_WORKFLOW)
        consumers = [
            (i, str(step.get("name", "")))
            for i, step in enumerate(steps)
            if "python" in str(step.get("run", "")) or "pytest" in str(step.get("run", ""))
        ]
        assert consumers, f"job {job_id!r} runs no python at all; this guard is inspecting the wrong job"

        first_at, first_name = min(consumers)
        assert install_at < first_at, (
            f"in nightly job {job_id!r} the {QT_STEP_NAME!r} step is at index {install_at}, after "
            f"{first_name!r} at index {first_at}. The libraries must be present BEFORE anything "
            "imports PySide6, or the job dies at collection exactly as it did in run 33247186128."
        )


def test_the_workflow_shell_is_the_login_shell_these_tests_reproduce() -> None:
    """Bind the shell the executed-script guards below are entitled to assume.

    Those guards run the script through `bash -el` because that is what the
    workflows do. If a workflow moved to a non-login shell the reproduction would
    silently stop matching production, so the assumption is asserted rather than
    left implicit.
    """
    targets = [(MAIN_WORKFLOW, CANONICAL_JOB)]
    targets += [(NIGHTLY_WORKFLOW, job) for job in _qt_dependent_jobs()]

    for relative, job_id in targets:
        workflow = _workflow(relative)
        shell = workflow["jobs"][job_id].get("defaults", {}).get("run", {}).get("shell")
        assert shell == WORKFLOW_SHELL, (
            f"{relative} job {job_id!r} runs steps under shell {shell!r}, not {WORKFLOW_SHELL!r}. "
            "The executed-script guards in this file reproduce the login shell deliberately."
        )


def _write_stub(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _stub_tree(tmp_path: Path, missing: tuple[str, ...], fail_first_install: bool) -> tuple[dict, Path]:
    """A PATH where dpkg reports a chosen SUBSET absent and apt-get records argv.

    `sudo` execs its arguments rather than being special-cased, so the script's
    real `sudo apt-get ...` invocation is followed all the way through.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "apt-invocations.txt"
    marker = tmp_path / "first-install-consumed"

    wanted = " ".join(missing) if missing else "__none_missing__"
    _write_stub(
        bin_dir / "dpkg",
        f'#!/bin/sh\nfor want in {wanted}; do\n  if [ "$2" = "$want" ]; then exit 1; fi\ndone\nexit 0\n',
    )
    _write_stub(bin_dir / "sudo", '#!/bin/sh\nexec "$@"\n')

    fail_clause = ""
    if fail_first_install:
        fail_clause = (
            'case " $* " in\n'
            '  *" install "*)\n'
            f'    if [ ! -f "{marker.as_posix()}" ]; then\n'
            f'      : > "{marker.as_posix()}"\n'
            "      exit 100\n"
            "    fi\n"
            "    ;;\n"
            "esac\n"
        )
    _write_stub(
        bin_dir / "apt-get",
        f'#!/bin/sh\necho "$@" >> "{log.as_posix()}"\n{fail_clause}exit 0\n',
    )

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir.as_posix()}{os.pathsep}{env.get('PATH', '')}"
    return env, log


def _apt_invocations(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [line.split() for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def _real_installs(invocations: list[list[str]]) -> list[list[str]]:
    """Only invocations that would really install something.

    `apt-get --simulate install -y ...` logs the package names and succeeds while
    installing nothing, which is indistinguishable from a real install if the
    recorded argv is searched as flat text.
    """
    return [argv for argv in invocations if "install" in argv and not (SIMULATION_FLAGS & set(argv))]


def _run_canonical_script(
    tmp_path: Path,
    missing: tuple[str, ...],
    fail_first_install: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    """Run the step's script the way the workflow runs it: `bash -el <file>`."""
    bash = shutil.which("bash")
    assert bash is not None, (
        "bash is required to exercise the install step's own script; it is present on both "
        "runner images this partition uses."
    )
    script = tmp_path / "step.sh"
    script.write_text(_canonical_step()["run"], encoding="utf-8", newline="\n")

    env, log = _stub_tree(tmp_path, missing, fail_first_install)
    completed = subprocess.run(
        [bash, "-el", script.as_posix()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    return completed, _apt_invocations(log)


@pytest.mark.parametrize("package", QT_PACKAGES)
def test_each_package_alone_reaches_a_real_install(tmp_path: Path, package: str) -> None:
    """One package absent at a time, because uniform outcomes hide a fixed list.

    A script that probed only `libegl1` and then hardcoded all four names into
    `missing` passes a test that reports every package absent together, while a
    runner with `libegl1` present and a sibling absent skips apt entirely.
    """
    completed, invocations = _run_canonical_script(tmp_path, missing=(package,))

    assert completed.returncode == 0, (
        f"the step's script failed under stubbed tools:\n{completed.stdout}\n{completed.stderr}"
    )
    installs = _real_installs(invocations)
    assert installs, (
        f"{package!r} was reported absent and no real apt-get install followed. The probe is not "
        f"accumulating into `missing`, so the install path is dead. apt-get saw: {invocations!r}"
    )
    assert any(package in argv for argv in installs), (
        f"{package!r} was reported absent but never reached a real install: {installs!r}"
    )


def test_all_missing_packages_reach_one_real_install(tmp_path: Path) -> None:
    completed, invocations = _run_canonical_script(tmp_path, missing=QT_PACKAGES)

    assert completed.returncode == 0, completed.stderr
    installs = _real_installs(invocations)
    assert installs, f"no real, non-simulated install occurred; apt-get saw: {invocations!r}"
    assert any(all(package in argv for package in QT_PACKAGES) for argv in installs), (
        f"no single real install carried the whole package set: {installs!r}"
    )


def test_the_documented_refresh_and_retry_branch_really_installs(tmp_path: Path) -> None:
    """Exercise the fallback the step documents, not only the happy path.

    The comments record run 32303335407, where the index already on the image did
    not satisfy the request. If that branch stopped installing, the step would
    still report success while the libraries stayed absent.
    """
    completed, invocations = _run_canonical_script(tmp_path, missing=QT_PACKAGES, fail_first_install=True)

    assert completed.returncode == 0, (
        f"the script did not recover when the first install failed:\n{completed.stdout}\n{completed.stderr}"
    )
    assert any("update" in argv for argv in invocations), (
        f"the first install failed and no index refresh followed: {invocations!r}"
    )
    installs = _real_installs(invocations)
    assert len(installs) >= 2, f"no retry install after the refresh: {invocations!r}"
    assert any(all(package in argv for package in QT_PACKAGES) for argv in installs[1:]), (
        f"the retry install did not carry the package set: {installs!r}"
    )


def test_the_step_skips_the_network_when_every_package_is_present(tmp_path: Path) -> None:
    """A probe that always reported missing would also be wrong.

    Without this, a script that installed unconditionally would satisfy every
    test above while reintroducing the bounded-network stall the step's own
    comments record having cost two pull requests' evidence.
    """
    completed, invocations = _run_canonical_script(tmp_path, missing=())

    assert completed.returncode == 0, completed.stderr
    assert invocations == [], f"apt-get was invoked although dpkg reported every package present: {invocations!r}"
    assert "already present" in completed.stdout, completed.stdout


def test_the_step_script_never_calls_exit() -> None:
    """The rule the step's own comments open with, asserted on both platforms.

    Under `bash -el` at SHLVL 1 the runner's `~/.bash_logout` runs
    `clear_console`, which FAILS when there is no terminal, and its status then
    replaces the argument of an explicit `exit`. Run 32306229771 lost all four
    Linux jobs that way: each installed the library in about seven seconds,
    printed its success line, and reported failure.

    Executing the script cannot catch this everywhere. The condition is a
    property of the Ubuntu runner image, so on a Windows runner -- which this
    partition also uses -- appending `exit 0` leaves the executed-script guards
    green. This assertion is structural for exactly that reason, and it holds on
    both platforms.
    """
    script = _canonical_step()["run"]
    offenders = [
        (number, line)
        for number, line in enumerate(script.splitlines(), start=1)
        if not line.lstrip().startswith("#") and "exit" in line.split()
    ]
    assert not offenders, (
        "the install step's script calls `exit`, which its own comments forbid: at SHLVL 1 under "
        "the login shell, ~/.bash_logout's failing `clear_console` replaces that status and the "
        f"job reports failure after a successful install. Offending lines: {offenders}"
    )
