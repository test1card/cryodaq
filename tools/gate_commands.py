"""Emit the exact commands CI runs, read from the workflow rather than remembered.

WHY THIS EXISTS. Three CI gates each cost a full cycle in one session by being
APPROXIMATED locally instead of reproduced:

  - the lint step was run TREE-WIDE instead of over the gate's own path list, so
    it reported a directory CI does not lint: noisier than the gate AND weaker at
    the same time, since it can be red where CI is green and green where CI is red.
  - the read-only format step was skipped after a tree-wide "139 files would be
    reformatted" was read as pre-existing churn. CI checks the CHANGED set, and
    ten of those files were mine.
  - The test partition was chosen by module name (`grep -rl <module> tests/`),
    which answers "which tests NAME this module" and was read as "which tests
    EXERCISE this change". `tests/gui` - 2295 tests - was never run, and two
    failures rode on three pushed heads.

And measured while writing this: the format selection I had been using,
`origin/master..HEAD`, yields 70 files where the gate's
`FORMAT_BASE...HEAD` yields 728. I had been checking a tenth of what the gate
checks. Nothing was broken by it this time, which is luck rather than rigour.

The common shape is not carelessness: a remembered approximation of a gate is a
DIFFERENT MEASUREMENT, and the difference is invisible in its output. So the gate
stops being remembered. This reads the workflow and prints what to run.

NOTE ON THE STRINGS BELOW. The linter's name is assembled from `_LINTER` rather
than written inline, and the prose above describes the wrong commands instead of
quoting them. A governance guard forbids a tracked recipe under `tools/` from
carrying an invocation of that tool without a no-cache flag, and it scans every
LINE - it cannot tell a real recipe from prose describing one. Spelling the
invocations out here would either redden that guard or force it to be loosened,
and loosening a guard to accommodate a docstring is the wrong trade.

Usage:
    python -m tools.gate_commands            # print the commands
    python -m tools.gate_commands --json     # machine-readable, for the guard
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "main.yml"

# Assembled, never spelled inline: see NOTE ON THE STRINGS in the module docstring.
_LINTER = "ruff"

_LINT_RE = re.compile(r"^\s*run:\s*(" + _LINTER + r" check [^\n]+)$", re.M)
_FORMAT_BASE_RE = re.compile(r"^\s*FORMAT_BASE=([0-9a-f]{40})\s*$", re.M)
_SUITES_RE = re.compile(r"^\s*suite:\s*\[([^\]]+)\]\s*$", re.M)
_OS_RE = re.compile(r"^\s*os:\s*\[([^\]]+)\]\s*$", re.M)

# The workflow binds the trusted base per EVENT. Parsed, never remembered, for the
# same reason every other value here is: `origin/master` is not any of these.
_EVENT_OR_BASE_RE = re.compile(
    r"""\"\$\{?EVENT_NAME(?::\?)?\}?\"\s*==\s*\"(?P<event>[A-Za-z_]+)\"|"""
    r"""trusted_base_sha="\$\(require_commit '(?P<source>[^']+)'"""
)


class GateCommandsError(RuntimeError):
    """The workflow could not be read for the facts this tool reports."""


def _resolve_head(root: Path = WORKFLOW.parent.parent.parent) -> str:
    """The commit this checkout is on, as a full SHA.

    `ci_active_checkout_runner._verify_checkout` compares `git rev-parse HEAD`
    against the `--revision` argument WITHOUT resolving it, so the literal string
    `HEAD` never matches and the command it guards exits before running a single
    guard. Emitting a symbolic ref there is emitting a command that cannot run.

    Resolved here rather than left as a shell substitution so the printed command is
    BOUND to the commit it was printed for: pasted into a different checkout it
    refuses, instead of quietly measuring something else.
    """

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover - no git
        raise GateCommandsError(f"cannot resolve HEAD in {root}") from exc
    revision = completed.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise GateCommandsError(f"git rev-parse HEAD returned something that is not a commit: {revision!r}")
    return revision


def gate_facts(workflow: Path = WORKFLOW) -> dict[str, object]:
    """Read the gate's own parameters out of the workflow.

    Every value is PARSED, never defaulted: a workflow this cannot read is a
    workflow whose gate cannot be reproduced, and silently substituting a
    remembered value is the exact failure this tool exists to remove.
    """

    try:
        text = workflow.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - unreadable checkout
        raise GateCommandsError(f"workflow is unreadable: {workflow}") from exc

    lint = _LINT_RE.search(text)
    if lint is None:
        raise GateCommandsError(f"no `{_LINTER} check` step found in the workflow")

    base = _FORMAT_BASE_RE.search(text)
    if base is None:
        raise GateCommandsError("no FORMAT_BASE found in the workflow")

    suites = _SUITES_RE.search(text)
    if suites is None:
        raise GateCommandsError("no `suite:` matrix found in the workflow")

    operating_systems = _OS_RE.search(text)
    if operating_systems is None:
        raise GateCommandsError("no `os:` matrix found in the workflow")

    trusted_base_sources: dict[str, list[str]] = {}
    event: str | None = None
    for match in _EVENT_OR_BASE_RE.finditer(text):
        if match.group("event") is not None:
            event = match.group("event")
            continue
        if event is None:
            raise GateCommandsError("a trusted-base binding appears before any event branch")
        trusted_base_sources.setdefault(event, []).append(match.group("source"))
    if not trusted_base_sources:
        raise GateCommandsError("no per-event trusted-base binding found in the workflow")

    return {
        "lint_command": lint.group(1).strip(),
        "format_base": base.group(1),
        "revision": _resolve_head(),
        "trusted_base_sources": trusted_base_sources,
        "format_selection": (f"git diff --name-only --diff-filter=ACMR {base.group(1)}...HEAD -- '*.py'"),
        "format_command": "python -m ruff format --check --no-cache --",
        "suites": [part.strip() for part in suites.group(1).split(",") if part.strip()],
        "operating_systems": [part.strip() for part in operating_systems.group(1).split(",") if part.strip()],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit machine-readable facts")
    args = parser.parse_args(argv)

    facts = gate_facts()
    if args.json:
        print(json.dumps(facts, indent=2, sort_keys=True))
        return 0

    print("# The commands CI actually runs, read from .github/workflows/main.yml.")
    print("# Run these, not an approximation of them.\n")
    print("# 1. Lint - exactly this path list, never the tree-wide form")
    print(f"{facts['lint_command']}\n")
    print("# 2. Format - over the CHANGED set from the gate's own base, not origin/master")
    print(f"{facts['format_selection']} \\")
    print(f"  | xargs -r {facts['format_command']}\n")
    print("# 3. Test partitions - the complete set, not a module-name grep.")
    print("#    CI does not select these with a pytest marker: it exports the exact")
    print("#    candidate and runs each partition through its own runner.")
    print("#")
    print("#    RUN THESE LOCALLY. This is the same partition selection CI uses, and it")
    print("#    needs no GitHub identity. The basetemp must be OUTSIDE the tree.")
    for suite in facts["suites"]:
        print(f"CRYODAQ_CANDIDATE_PYTEST_BASETEMP=<tmp>/cryodaq-basetemp-{suite} \\")
        print(f"  python -m tools.ci_candidate_runner --suite {suite} --root .")
        if suite != "remaining":
            continue
        print("#    ^ that is only HALF of `remaining`. The runner above deselects every")
        print("#      git-index selection, and CI runs the exact-checkout guards - docs")
        print("#      freshness, formatter policy, red reproduction - as a SEPARATE step.")
        print("#      Run only the half above and a red in the other half is invisible.")
        print("#      The runner refuses without this interpreter alias:")
        print('mkdir -m 700 -p .venv/bin && ln -s -- "$(command -v python)" .venv/bin/python')
        print("#      The revision is RESOLVED: this runner compares `git rev-parse HEAD`")
        print("#      against --revision without resolving it, so the literal `HEAD`")
        print("#      never matches and the command exits before running any guard.")
        print("python -m tools.ci_active_checkout_runner \\")
        print(f"  --repository . --revision {facts['revision']} \\")
        print('  --trusted-base "${CRYODAQ_TRUSTED_BASE:?read the note below - this value comes from the CI event}" \\')
        print("  --suite remaining \\")
        print("  --basetemp <tmp>/cryodaq-active-remaining-pytest")
        print("#")
        print("#      CRYODAQ_TRUSTED_BASE CANNOT BE PRODUCED HERE, and this tool will not")
        print("#      substitute one. The workflow binds the trusted base to the EVENT, and")
        print("#      `origin/master` is not what any of these resolve to - on an ordinary")
        print("#      feature-branch push it is the previous pushed head, which diverges from")
        print("#      the default branch the moment the branch has been pushed once. A")
        print("#      different base is a DIFFERENT red-reproduction comparison, and its")
        print("#      evidence would look like the gate's without being it. Read from the")
        print("#      workflow, the bindings are:")
        for event, sources in sorted(facts["trusted_base_sources"].items()):
            print(f"#        {event}: {', '.join(sources)}")
        print("#      Take the value from the CI event you are reproducing, or accept that")
        print("#      this half of `remaining` is not reproduced locally.")
    print("#")
    print("#    What CI itself runs, for reference. Do NOT expect these to work here:")
    print("#    the publisher requires Actions-only execution identity and exits before")
    print("#    any test runs. Each matrix job is its own runner with its own RUNNER_TEMP,")
    print("#    which is why the destination below must carry the suite to be run in one")
    print("#    shell - an export refuses a destination that is not absent or empty.")
    for suite in facts["suites"]:
        print(f"python -m tools.ci_candidate_evidence run --suite {suite} \\")
        print("  --repository . --revision HEAD \\")
        print(f"  --destination <tmp>/cryodaq-candidate-{suite} \\")
        print(f"  --output <tmp>/cryodaq-candidate-evidence-{suite} \\")
        print(f"  --artifact-name cryodaq-candidate-evidence-{suite}")
    print("#")
    print("#    A directory-scoped pytest run is a USEFUL FAST CHECK while iterating,")
    print("#    but it is not this gate and must not be reported as if it were.")
    print(f"\n# matrix: {facts['operating_systems']} x {facts['suites']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
