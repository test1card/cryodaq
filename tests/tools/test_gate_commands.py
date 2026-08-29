"""Guards for tools/gate_commands.py.

The failure being prevented is not "someone ran the wrong command once". It is
that a REMEMBERED approximation of a gate is a different measurement whose
difference is invisible in its output. Three gates cost a full CI cycle each in
one session that way, and the format selection in use covered 70 files where the
gate covers 728.

So these guards falsify the tool going stale against the workflow: if the gate's
lint paths, format base, or partition matrix move and the tool keeps reporting the
old ones, the tool becomes exactly the remembered approximation it exists to
replace, and that must redden.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools.gate_commands import GateCommandsError, gate_facts

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "main.yml"


def test_the_tool_reports_the_workflows_own_lint_command() -> None:
    """The lint command must be the gate's, character for character.

    `ruff check .` reports `plugins/`, which CI does not lint - noisier than the
    gate and weaker at the same time, because it can be red where CI is green.
    """

    facts = gate_facts()
    text = WORKFLOW.read_text(encoding="utf-8")
    assert facts["lint_command"] in text
    assert facts["lint_command"].startswith("ruff check")
    assert "src/" in facts["lint_command"] and "tests/" in facts["lint_command"]


def test_the_format_base_is_the_workflows_own_and_is_a_real_commit() -> None:
    """A remembered base is a different file set.

    Measured 2026-08-29: `origin/master..HEAD` yields 70 files where the gate's
    `FORMAT_BASE...HEAD` yields 728. Checking the wrong tenth is not checking.
    """

    facts = gate_facts()
    assert re.fullmatch(r"[0-9a-f]{40}", str(facts["format_base"]))
    assert f"FORMAT_BASE={facts['format_base']}" in WORKFLOW.read_text(encoding="utf-8")
    # three-dot: the gate diffs from the merge base, not from the tip
    assert f"{facts['format_base']}...HEAD" in str(facts["format_selection"])


def test_the_partition_list_is_the_whole_matrix() -> None:
    """A module-name grep answers a different question than the partition does.

    `grep -rl <module> tests/` returns the tests that NAME a module, which is not
    the set that EXERCISES a change. `tests/gui` - 2295 tests - was never run that
    way, and two failures rode on three pushed heads.
    """

    facts = gate_facts()
    suites = facts["suites"]
    assert isinstance(suites, list) and suites
    text = WORKFLOW.read_text(encoding="utf-8")
    for suite in suites:
        assert f"'{suite}'" in text or f'"{suite}"' in text or suite in text
    assert len(set(suites)) == len(suites), "the matrix lists a partition twice"


def test_an_unreadable_workflow_refuses_rather_than_defaulting(tmp_path: Path) -> None:
    """Fail closed.

    Substituting a remembered value for a workflow that cannot be read would
    recreate the exact defect: a plausible answer that is not the gate's.
    """

    with pytest.raises(GateCommandsError):
        gate_facts(tmp_path / "absent.yml")


def test_a_workflow_without_a_format_base_refuses(tmp_path: Path) -> None:
    """A partial workflow must not yield a partial answer that looks whole."""

    partial = tmp_path / "main.yml"
    partial.write_text(
        "jobs:\n  test:\n    strategy:\n      matrix:\n"
        "        os: [ubuntu-latest]\n        suite: [core]\n"
        "    steps:\n      - name: Lint\n        run: ruff check --no-cache src/ tests/\n",
        encoding="utf-8",
    )
    with pytest.raises(GateCommandsError):
        gate_facts(partial)


def test_the_emitted_partition_command_is_the_runner_ci_uses() -> None:
    """The tool must not invent a selection mechanism.

    My first version emitted `pytest -m 'suite_core'`. There is no such marker:
    CI runs `tools.ci_candidate_evidence run --suite <name>`. Emitting a plausible
    command that does not select what the gate selects would have written a NEW
    approximation into the very tool meant to end them.
    """

    import subprocess
    import sys as _sys

    printed = subprocess.run(
        [_sys.executable, "-m", "tools.gate_commands"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "tools.ci_candidate_evidence run --suite" in printed
    assert "-m 'suite_" not in printed, "the tool invented a pytest marker again"
    workflow = open(WORKFLOW, encoding="utf-8").read()
    assert "tools.ci_candidate_evidence run" in workflow


def test_the_emitted_partition_command_carries_every_required_argument() -> None:
    """An emitted command that cannot run is the defect this tool exists to remove.

    Measured 2026-08-29: the emission omitted `--artifact-name`, which the runner
    declares REQUIRED, so running it verbatim exited with a usage error.

    The required set is read out of the RUNNER'S OWN source rather than listed
    here, for the same reason the tool reads the workflow instead of remembering
    it: a remembered argument list is a different object from the parser, and the
    difference is invisible until the command is run.
    """

    import io as _io
    from contextlib import redirect_stdout

    from tools.gate_commands import main as emit

    runner = (REPO_ROOT / "tools" / "ci_candidate_evidence.py").read_text(encoding="utf-8")
    # The boundary matters: `protected_run.add_argument` CONTAINS `run.add_argument`,
    # and without it this guard reports the protected-run subcommand's arguments as
    # missing from a run command that never needed them.
    required = set(
        re.findall(
            r'(?<![_A-Za-z])run\.add_argument\(\s*"(--[a-z-]+)"[^)]*required=True',
            runner,
        )
    )
    assert required, "no required arguments were found on the runner's run subcommand"
    assert "--producer-root" not in required, "the protected-run subcommand's arguments leaked into the run set"

    buffer = _io.StringIO()
    with redirect_stdout(buffer):
        emit([])
    emitted = buffer.getvalue()

    assert "ci_candidate_evidence run" in emitted, "no partition command was emitted at all"
    missing = sorted(name for name in required if name not in emitted)
    assert missing == [], f"the emitted partition command cannot run; it omits {missing}"


def test_every_partition_has_a_command_that_can_actually_run_here() -> None:
    """Codex P1 at 1608b8602: the emitted commands could not run locally at all.

    They routed local reproduction through the evidence publisher, which calls
    `_github_environment()` and refuses without Actions-only identity variables -
    so the tool's advertised "run these" partition commands exited before running
    a single test in the very workflow they exist to support.

    Measured 2026-08-29 with no Actions identity present:
    `python -m tools.ci_candidate_runner --suite remaining --root .` with
    CRYODAQ_CANDIDATE_PYTEST_BASETEMP bound ran the real partition - 3648 passed,
    51 skipped, 758 deselected. That is the supported local invocation.
    """

    import io as _io
    from contextlib import redirect_stdout

    from tools.gate_commands import main as emit

    buffer = _io.StringIO()
    with redirect_stdout(buffer):
        emit([])
    emitted = buffer.getvalue()

    facts = gate_facts()
    for suite in facts["suites"]:
        assert f"ci_candidate_runner --suite {suite} --root" in emitted, (
            f"no locally runnable command is emitted for the {suite} partition"
        )
    assert "CRYODAQ_CANDIDATE_PYTEST_BASETEMP" in emitted, (
        "the local command omits the basetemp binding and refuses without it"
    )
    assert "Actions-only execution identity" in emitted, (
        "the publisher command is presented without saying it cannot run here"
    )


def test_the_printed_matrix_can_be_run_sequentially_in_one_shell() -> None:
    """Codex P2 at 1608b8602: every printed command shared one export destination.

    `export_candidate()` requires its destination to be absent or empty, so the
    second suite was rejected. CI never sees this - each matrix job is a separate
    runner with its own RUNNER_TEMP - which is exactly why it had to be found by
    reading rather than by the gate going red.
    """

    import io as _io
    import re as _re
    from contextlib import redirect_stdout

    from tools.gate_commands import main as emit

    buffer = _io.StringIO()
    with redirect_stdout(buffer):
        emit([])
    emitted = buffer.getvalue()

    for flag in ("--destination", "--output"):
        paths = _re.findall(rf"{flag} (\S+)", emitted)
        assert paths, f"no {flag} was emitted at all"
        assert len(paths) == len(set(paths)), (
            f"{flag} repeats a path across partitions: {paths} - "
            "running the printed matrix in one shell would be refused"
        )

    basetemps = _re.findall(r"CRYODAQ_CANDIDATE_PYTEST_BASETEMP=(\S+)", emitted)
    assert basetemps and len(basetemps) == len(set(basetemps)), f"the local commands share a basetemp: {basetemps}"


def test_the_remaining_partition_emits_both_of_its_halves() -> None:
    """Codex P1 at 8314e9273: only half of `remaining` was emitted.

    `ci_candidate_runner` deselects every git-index selection and reaches the
    active-checkout runner only on protected runs, while CI runs
    `ci_active_checkout_runner` as a separate workflow step. Emitting one half and
    calling it the partition means a red in docs freshness, formatter policy or red
    reproduction can pass unnoticed.

    Both halves are checked against the workflow's OWN invocation rather than a
    remembered argument list, for the same reason the rest of this module exists.
    """

    import io as _io
    from contextlib import redirect_stdout

    from tools.gate_commands import main as emit

    buffer = _io.StringIO()
    with redirect_stdout(buffer):
        emit([])
    emitted = buffer.getvalue()

    assert "ci_candidate_runner --suite remaining --root" in emitted
    assert "ci_active_checkout_runner" in emitted, "the exact-checkout half of `remaining` is not emitted at all"

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "ci_active_checkout_runner" in workflow, (
        "the workflow no longer runs the active-checkout half; re-check this emission"
    )
    for flag in ("--trusted-base", "--basetemp", "--suite remaining"):
        assert flag in emitted, f"the active-checkout command omits {flag}"
    assert ".venv/bin/python" in emitted, (
        "the interpreter alias the active-checkout runner refuses without is not emitted"
    )
