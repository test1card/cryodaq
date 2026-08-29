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


def _emit() -> str:
    import io as _io
    from contextlib import redirect_stdout

    from tools.gate_commands import main as emit

    buffer = _io.StringIO()
    with redirect_stdout(buffer):
        emit([])
    return buffer.getvalue()


def _invocation(emitted: str, first_line_starts_with: str) -> str:
    """Rebuild one backslash-continued shell invocation out of the emitted text."""

    lines = emitted.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith(first_line_starts_with):
            continue
        collected = []
        while index < len(lines):
            current = lines[index]
            collected.append(current.rstrip().removesuffix("\\").rstrip())
            if not lines[index].rstrip().endswith("\\"):
                break
            index += 1
        return " ".join(collected)
    raise AssertionError(f"no emitted line starts with {first_line_starts_with!r}")


def test_the_emitted_active_checkout_command_is_accepted_by_the_runners_own_verifier(tmp_path: Path) -> None:
    """Codex P1: the emitted command exited before running a single guard.

    `ci_active_checkout_runner._verify_checkout` compares `git rev-parse HEAD`
    against the `--revision` argument WITHOUT resolving it, so the literal string
    `HEAD` this tool used to emit could never match. The command looked right, ran
    nothing, and its failure was indistinguishable from any other early exit.

    The previous guard only grepped the emitted text for flag names, which cannot
    tell a runnable invocation from one the runner rejects. This one feeds the
    COMPLETE invocation through the runner's own argument parser, and drives the
    runner's own `_verify_checkout` to show it accepts the emitted revision and
    rejects the literal that used to be emitted.
    """

    import shlex
    import subprocess

    from tools.ci_active_checkout_runner import _verify_checkout, build_parser

    invocation = _invocation(_emit(), "python -m tools.ci_active_checkout_runner")
    argv = shlex.split(invocation)
    assert argv[:3] == ["python", "-m", "tools.ci_active_checkout_runner"], argv[:3]

    # The runner's OWN contract, not a remembered argument list.
    args = build_parser().parse_args(argv[3:])

    repository_root = WORKFLOW.parent.parent.parent
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert args.revision == head, (
        f"the emitted --revision {args.revision!r} is not what _verify_checkout compares against ({head!r})"
    )

    # Drive the REAL verifier. A scratch repo, because _verify_checkout also demands
    # a clean tree and this working tree is not required to be one.
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for command in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "gate@example.invalid"],
        ["git", "config", "user.name", "gate"],
        ["git", "commit", "-q", "--allow-empty", "-m", "base"],
    ):
        subprocess.run(command, cwd=scratch, check=True, capture_output=True)
    scratch_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=scratch,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    _verify_checkout(scratch, scratch_head)  # a resolved SHA is accepted

    with pytest.raises(RuntimeError):
        _verify_checkout(scratch, "HEAD")  # the literal this tool used to emit


def test_the_emitted_trusted_base_is_never_a_default_branch_ref() -> None:
    """Codex P2: `origin/master` is a DIFFERENT red-reproduction comparison.

    The workflow binds `TRUSTED_BASE_SHA` to the event. On an ordinary
    feature-branch push it is `github.event.before` - the previous pushed head -
    which diverges from the default branch as soon as the branch has been pushed
    once. Substituting `origin/master` produces evidence that looks like the gate's
    without being it, which is worse than producing none.

    No single correct value can be computed in this checkout, so the tool must
    REFUSE rather than default, and must say where the value comes from.
    """

    from tools.gate_commands import gate_facts

    emitted = _emit()
    invocation = _invocation(emitted, "python -m tools.ci_active_checkout_runner")

    assert "origin/master" not in invocation, "a default-branch ref was substituted for the CI event's base"
    assert "CRYODAQ_TRUSTED_BASE:?" in invocation, (
        "the trusted base is not fail-closed: running the emitted command would use some other value"
    )

    # The bindings are READ from the workflow, so they cannot drift from it.
    sources = gate_facts()["trusted_base_sources"]
    assert isinstance(sources, dict) and sources
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for event, labels in sources.items():
        assert event in emitted, f"the emitted note does not name the {event} binding"
        for label in labels:
            assert label in workflow, f"{label!r} is not a binding this workflow actually declares"
            assert label in emitted, f"the emitted note does not carry the {event} source {label!r}"


def test_the_trusted_base_bindings_cover_every_event_the_workflow_handles() -> None:
    """A binding this tool cannot see is a binding it would silently misreport.

    The first branch writes `"${EVENT_NAME:?}"` and the rest write `"$EVENT_NAME"`.
    A pattern that reads only one of the two drops the pull_request binding without
    any symptom, which is exactly the class of error this module exists to remove.
    """

    from tools.gate_commands import gate_facts

    sources = gate_facts()["trusted_base_sources"]
    workflow = WORKFLOW.read_text(encoding="utf-8")
    declared = set(re.findall(r'EVENT_NAME(?::\?)?\}?"\s*==\s*"([A-Za-z_]+)"', workflow))
    assert declared, "the workflow no longer dispatches on EVENT_NAME; re-check this parser"
    assert set(sources) == declared, f"parsed {sorted(sources)} but the workflow handles {sorted(declared)}"


def test_the_tool_works_where_there_is_no_git_repository(tmp_path: Path) -> None:
    """CI runs this suite against an EXPORTED tree, which has no `.git`.

    Measured 2026-08-29: resolving the revision inside `gate_facts()` made all
    ELEVEN tests in this module fail at call time in CI, because
    `export_candidate()` exports a tree rather than a clone. Reading the workflow
    does not need a repository and must not require one.

    This drives the real tool with its workflow copied into a directory that is
    deliberately not a repository.
    """

    import io as _io
    import shutil
    from contextlib import redirect_stdout

    from tools import gate_commands

    workflow = tmp_path / "main.yml"
    shutil.copy2(WORKFLOW, workflow)

    facts = gate_facts(workflow)
    assert facts["lint_command"], "the workflow-derived facts must survive without a repository"
    assert facts["suites"], "the partition list must survive without a repository"
    assert facts["revision"] is None, "an absent repository must answer None, not raise"

    # and the emission must refuse rather than printing a symbolic ref
    original = gate_commands.WORKFLOW
    try:
        gate_commands.WORKFLOW = workflow
        buffer = _io.StringIO()
        with redirect_stdout(buffer):
            gate_commands.main([])
        emitted = buffer.getvalue()
    finally:
        gate_commands.WORKFLOW = original

    # The emission is backslash-continued, so the honest unit is the command BLOCK.
    # Scoped to the ACTIVE-CHECKOUT runner only: the publisher resolves its revision
    # with `rev-parse --verify {revision}^{commit}`, so `HEAD` is correct there.
    lines = emitted.splitlines()
    block: list[str] = []
    for index, line in enumerate(lines):
        if "ci_active_checkout_runner" not in line:
            continue
        cursor = index
        while cursor < len(lines):
            block.append(lines[cursor])
            if not lines[cursor].rstrip().endswith("\\"):
                break
            cursor += 1
        break
    assert block, "no active-checkout command was emitted at all"
    joined = " ".join(block)
    assert "--revision HEAD" not in joined, (
        f"a symbolic ref reached the active-checkout command, which compares it without "
        f"resolving, so the command exits before running a single guard:\n{joined}"
    )
    assert "CRYODAQ_CANDIDATE_REVISION:?" in joined, (
        f"the unresolved revision must be a parameter the shell refuses when unset:\n{joined}"
    )
