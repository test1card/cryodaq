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
import sys
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

#: Tokens the step's own script must never contain. Whether a given invocation
#: simulates is decided by the apt stub below, which models apt's option grammar;
#: this list is the separate, cheap assertion that the WORKFLOW never asks for a
#: simulation in the first place, in any spelling.
FORBIDDEN_SCRIPT_TOKENS = (
    "--simulate",
    "--dry-run",
    "--just-print",
    "--no-act",
    "--recon",
    "Simulate",
    "Just-Print",
)


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


_APT_STUB_SOURCE = r"""
import os
import sys
from pathlib import Path

root = Path(os.environ["STUB_ROOT"])
log = root / "apt-invocations.txt"
installed = root / "installed"
update_seen = root / "update-seen"
require_update = os.environ.get("STUB_REQUIRE_UPDATE") == "1"

argv = sys.argv[1:]
with log.open("a", encoding="utf-8") as handle:
    handle.write(" ".join(argv) + "\n")

ALIASES = {"--simulate", "-s", "--dry-run", "--just-print", "--no-act", "--recon"}
KEYS = {
    "apt::get::simulate",
    "apt::get::just-print",
    "apt::get::dry-run",
    "apt::get::no-act",
    "apt::get::recon",
}
TRUE_VALUES = {"true", "yes", "1", "on", "y", "t"}


def is_simulation(args):
    index = 0
    while index < len(args):
        token = args[index]
        if token in ALIASES:
            return True
        if token.startswith("-") and not token.startswith("--") and "=" not in token:
            if "s" in token[1:]:
                return True
        assignment = None
        if token in ("-o", "--option"):
            index += 1
            assignment = args[index] if index < len(args) else ""
        elif token.startswith("-o") and len(token) > 2:
            assignment = token[2:]
        elif token.startswith("--option="):
            assignment = token.split("=", 1)[1]
        if assignment is not None:
            key, _, value = assignment.partition("=")
            if key.strip().lower() in KEYS and value.strip().lower() in TRUE_VALUES:
                return True
        index += 1
    return False


def packages(args):
    names = []
    skip = False
    for token in args:
        if skip:
            skip = False
            continue
        if token in ("-o", "--option"):
            skip = True
            continue
        if token.startswith("-") or token in ("install", "update", "upgrade"):
            continue
        names.append(token)
    return names


if "update" in argv:
    update_seen.write_text("seen", encoding="utf-8")
    sys.exit(0)

if "install" in argv:
    if require_update and not update_seen.exists():
        sys.exit(100)
    if is_simulation(argv):
        sys.exit(0)
    installed.mkdir(exist_ok=True)
    for name in packages(argv):
        (installed / name).write_text("installed", encoding="utf-8")
    sys.exit(0)

sys.exit(0)
"""

_DPKG_STUB_SOURCE = r"""
import os
import sys
from pathlib import Path

root = Path(os.environ["STUB_ROOT"])
installed = root / "installed"
absent = set(filter(None, os.environ.get("STUB_ABSENT", "").split()))

package = sys.argv[2] if len(sys.argv) > 2 else ""
if package in absent and not (installed / package).exists():
    sys.exit(1)
sys.exit(0)
"""


def _write_stub(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _stub_tree(tmp_path: Path, missing: tuple[str, ...], require_update: bool) -> tuple[dict, Path]:
    """A PATH whose apt-get MODELS apt, so EFFECT can be asserted instead of argv.

    Deciding whether an install really happened by reading the recorded command
    line is the inference review bypassed twice, most recently with
    `apt-get -o APT::Get::Simulate=true install`, which exits 0 and prints its
    Inst and Conf plan while changing nothing. apt's option grammar is therefore
    modelled once, here, and the tests look at what ended up installed.

    `sudo` execs its arguments rather than being special-cased, so the script's
    real `sudo apt-get ...` invocation is followed all the way through.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    helpers = tmp_path / "helpers"
    helpers.mkdir(exist_ok=True)

    apt_helper = helpers / "apt_stub.py"
    apt_helper.write_text(_APT_STUB_SOURCE, encoding="utf-8", newline="\n")
    dpkg_helper = helpers / "dpkg_stub.py"
    dpkg_helper.write_text(_DPKG_STUB_SOURCE, encoding="utf-8", newline="\n")

    interpreter = Path(sys.executable).as_posix()
    _write_stub(bin_dir / "apt-get", f'#!/bin/sh\nexec "{interpreter}" "{apt_helper.as_posix()}" "$@"\n')
    _write_stub(bin_dir / "dpkg", f'#!/bin/sh\nexec "{interpreter}" "{dpkg_helper.as_posix()}" "$@"\n')
    _write_stub(bin_dir / "sudo", '#!/bin/sh\nexec "$@"\n')

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir.as_posix()}{os.pathsep}{env.get('PATH', '')}"
    env["STUB_ROOT"] = tmp_path.as_posix()
    env["STUB_ABSENT"] = " ".join(missing)
    env["STUB_REQUIRE_UPDATE"] = "1" if require_update else "0"
    return env, tmp_path / "apt-invocations.txt"


def _apt_invocations(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [line.split() for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def _installed_packages(tmp_path: Path) -> set[str]:
    """What the run actually INSTALLED, which is the only thing that matters."""
    installed = tmp_path / "installed"
    if not installed.exists():
        return set()
    return {entry.name for entry in installed.iterdir()}


def _run_canonical_script(
    tmp_path: Path,
    missing: tuple[str, ...],
    require_update: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], set[str]]:
    """Run the step's script the way the workflow runs it: `bash -el <file>`."""
    bash = shutil.which("bash")
    assert bash is not None, (
        "bash is required to exercise the install step's own script; it is present on both "
        "runner images this partition uses."
    )
    script = tmp_path / "step.sh"
    script.write_text(_canonical_step()["run"], encoding="utf-8", newline="\n")

    env, log = _stub_tree(tmp_path, missing, require_update)
    # A LOGIN shell rebuilds PATH from its own profile, so an inherited PATH does
    # not reliably reach the script. On the hosted Windows runner the stub
    # directory was dropped exactly that way, and the failure was SILENT: the
    # script's own probe is `dpkg -s "$package" >/dev/null 2>&1`, so a missing
    # `dpkg` sends its not-found error to /dev/null and every package is marked
    # absent; the run then died on `sudo: command not found`. This wrapper sets
    # PATH AFTER the profile has run and then sources the real script, so the
    # login shell -- the property under test -- is preserved.
    bin_dir = (tmp_path / "bin").as_posix()
    wrapper = tmp_path / "run-step.sh"
    wrapper.write_text(
        f"BIN='{bin_dir}'\n"
        # A drive-letter path is not a PATH entry bash can search. The inherited
        # environment is converted at shell startup, but a path prepended INSIDE
        # the shell is not, so it is converted here or the lookup silently misses.
        'if command -v cygpath >/dev/null 2>&1; then BIN="$(cygpath -u "$BIN")"; fi\n'
        'PATH="$BIN:$PATH"\n'
        "export PATH\n"
        "for tool in dpkg apt-get sudo; do\n"
        '  command -v "$tool" >/dev/null 2>&1 || { echo "STUB_NOT_ON_PATH:$tool" >&2; exit 3; }\n'
        "done\n"
        f'. "{script.as_posix()}"\n',
        encoding="utf-8",
        newline="\n",
    )

    completed = subprocess.run(
        [bash, "-el", wrapper.as_posix()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 3, (
        "the stubbed tools never reached the script's PATH, so this run measured nothing "
        f"about the install path: {completed.stderr.strip()}"
    )
    return completed, _apt_invocations(log), _installed_packages(tmp_path)


def test_the_script_asks_for_no_simulation_in_any_spelling() -> None:
    """The cheap structural half, separate from the modelled stub.

    The stub catches a simulated install by its absent effect. This refuses to
    let the workflow ask for one at all, including the configuration-option form
    that has no standalone flag to match.
    """
    script = _canonical_step()["run"]
    body = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    for token in FORBIDDEN_SCRIPT_TOKENS:
        assert token not in body, (
            f"the install step's script contains {token!r}. apt would then report success while "
            "installing nothing, and the job would reach the Qt command without the library."
        )


@pytest.mark.parametrize("package", QT_PACKAGES)
def test_each_package_alone_is_really_installed(tmp_path: Path, package: str) -> None:
    """One package absent at a time, asserted by EFFECT rather than by argv.

    A script that probed only `libegl1` and then hardcoded all four names into
    `missing` passes a test that reports every package absent together, while a
    runner with `libegl1` present and a sibling absent skips apt entirely.
    """
    completed, invocations, installed = _run_canonical_script(tmp_path, missing=(package,))

    assert completed.returncode == 0, (
        f"the step's script failed under stubbed tools:\n{completed.stdout}\n{completed.stderr}"
    )
    assert package in installed, (
        f"{package!r} was reported absent and was never actually installed. Either the probe is not "
        "accumulating into `missing`, or apt was asked to simulate. apt-get saw: "
        f"{invocations!r}; installed: {sorted(installed)}"
    )


def test_every_missing_package_is_really_installed(tmp_path: Path) -> None:
    completed, invocations, installed = _run_canonical_script(tmp_path, missing=QT_PACKAGES)

    assert completed.returncode == 0, completed.stderr
    assert set(QT_PACKAGES) <= installed, (
        "the whole package set was reported absent but was not installed. "
        f"apt-get saw: {invocations!r}; installed: {sorted(installed)}"
    )


def test_the_refresh_precedes_the_retry_and_the_retry_really_installs(tmp_path: Path) -> None:
    """The documented fallback, asserted as an ORDER and not as a set.

    Requiring only that an update and a second install both occurred let the two
    be swapped: with a stub that failed just the first attempt, a retry placed
    BEFORE the refresh succeeded artificially. Here every install keeps failing
    until an update has been observed, so a script that retries first cannot
    recover at all, and the recorded sequence is checked explicitly.
    """
    completed, invocations, installed = _run_canonical_script(tmp_path, missing=QT_PACKAGES, require_update=True)

    assert completed.returncode == 0, (
        "the script did not recover when the cached index could not satisfy the first install:\n"
        f"{completed.stdout}\n{completed.stderr}"
    )
    assert set(QT_PACKAGES) <= installed, (
        f"the retry did not actually install the package set; installed: {sorted(installed)}"
    )

    kinds = ["update" if "update" in argv else "install" if "install" in argv else "other" for argv in invocations]
    assert kinds[:3] == ["install", "update", "install"], (
        "the fallback must be a failed install, THEN a refresh, THEN a real retry. "
        f"observed sequence: {kinds} from {invocations!r}"
    )


def test_the_step_skips_the_network_when_every_package_is_present(tmp_path: Path) -> None:
    """A probe that always reported missing would also be wrong.

    Without this, a script that installed unconditionally would satisfy every
    test above while reintroducing the bounded-network stall the step's own
    comments record having cost two pull requests' evidence.
    """
    completed, invocations, installed = _run_canonical_script(tmp_path, missing=())

    assert completed.returncode == 0, completed.stderr
    assert invocations == [], f"apt-get was invoked although dpkg reported every package present: {invocations!r}"
    assert installed == set(), f"something was installed with nothing missing: {sorted(installed)}"
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
