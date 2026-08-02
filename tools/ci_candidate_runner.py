"""Run one GitHub Actions test partition from an exported candidate tree."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.check_python_compile import compile_python_tree
from tools.ci_candidate_evidence import (
    FAILURE_RECEIPT_INDEX_ENV,
    FAILURE_RECEIPT_SUITE_ENV,
    PHASE_DIAGNOSIS_PREFIX,
    CiCandidateEvidenceError,
    _extract_failure_receipt_payloads,
)
from tools.ci_guard_execution import (
    RECEIPT_PREFIX,
    GuardExecutionError,
    active_guard_specs,
    canonical_receipt,
    checkout_execution_selection,
    current_guard_platform,
    empty_guard_receipt,
)
from tools.ci_guard_execution import (
    suite_for_node as _guard_suite_for_node,
)

_PYTEST = (
    sys.executable,
    "-B",
    "-m",
    "pytest",
    "-p",
    "tools.ci_candidate_evidence",
    "-p",
    "pytest_asyncio.plugin",
    "-p",
    "pytest_timeout",
    "-p",
    "no:cacheprovider",
)
_TAIL = ("--tb=short", "-v", "--timeout=120", "--timeout-method=thread")
_PROTECTED_PYTEST_BOOTSTRAP = """
import importlib
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import pytest

producer_root = Path(sys.argv[1]).resolve(strict=True)
candidate_root = Path(sys.argv[2]).resolve(strict=True)
strict = sys.argv[3] == "1"
pytest_args = sys.argv[4:]
sys.path.insert(0, str(producer_root))
population_plugin = importlib.import_module("tools.ci_candidate_evidence")
guard_plugin = importlib.import_module("tools.ci_guard_execution") if strict else None
sys.path.pop(0)
for module_name in tuple(sys.modules):
    if module_name == "tools" or module_name.startswith("tools."):
        sys.modules.pop(module_name, None)
sys.path[:0] = [str(candidate_root), str(candidate_root / "src")]
os.chdir(candidate_root)
plugins = [population_plugin]
if guard_plugin is not None:
    plugins.insert(0, guard_plugin)
raise SystemExit(pytest.main(pytest_args, plugins=plugins))
""".strip()
_RECEIPT_FIELDS = frozenset({"payload", "sha256"})
_PAYLOAD_FIELDS = frozenset(
    {
        "concrete_nodes",
        "deselected_nodes",
        "expected_guards",
        "expected_guard_platforms",
        "platform",
        "result",
        "schema_version",
        "suite",
        "violations",
        "warnings",
    }
)


def _emit_phase_diagnosis(
    *,
    suite: str,
    phase: str,
    reason: str,
    expected_blobs: dict[str, str] | None = None,
    actual_blobs: dict[str, str] | None = None,
    affected_receipt_ids: tuple[str, ...] = (),
    remediation: str,
) -> None:
    """Emit one parseable failure diagnosis before pytest can emit a receipt."""

    payload = {
        "actual_blobs": actual_blobs or {},
        "affected_receipt_ids": list(affected_receipt_ids),
        "expected_blobs": expected_blobs or {},
        "phase": phase,
        "reason": reason,
        "remediation": remediation,
        "suite": suite,
    }
    print(
        f"{PHASE_DIAGNOSIS_PREFIX}{json.dumps(payload, sort_keys=True, separators=(',', ':'))}",
        file=sys.stderr,
        flush=True,
    )


def _guard_blob_diagnosis(error: Exception) -> tuple[dict[str, str], dict[str, str], tuple[str, ...]]:
    """Extract the blob mismatch binding from governance's fail-closed error."""

    import re

    match = re.search(
        r"(?P<record>[A-Z0-9-]+) guard-source-blob-mismatch path=(?P<path>\S+) "
        r"expected=(?P<expected>[0-9a-f]{40}) actual=(?P<actual>[0-9a-f]{40})",
        str(error),
    )
    if match is None:
        return {}, {}, ()
    return (
        {match["path"]: match["expected"]},
        {match["path"]: match["actual"]},
        (f"guard:{match['record']}",),
    )


def _validate_candidate_population_receipt(output: str, *, suite: str, index: int) -> None:
    """Require each ordinary pytest invocation to account for its population."""

    receipts = _extract_failure_receipt_payloads(output, suite=suite)
    if len(receipts) != 1:
        raise CiCandidateEvidenceError(
            f"candidate pytest invocation {index} emitted {len(receipts)} population receipts instead of one"
        )
    if receipts[0]["invocation_index"] != index:
        raise CiCandidateEvidenceError(
            f"candidate population receipt index {receipts[0]['invocation_index']} does not match invocation {index}"
        )


_SELECTIONS: dict[str, tuple[tuple[str, ...], ...]] = {
    "core": (("tests/core", "tests/health", "tests/engine_wiring"),),
    "gui": (
        ("tests/gui/test_app_palette.py",),
        (
            "tests/gui/shell/operator_components/test_freshness_and_card.py",
            "tests/gui/shell/views/test_operator_display.py",
        ),
        (
            "tests/gui",
            "--deselect",
            "tests/gui/test_app_palette.py",
            "--deselect",
            "tests/gui/shell/operator_components/test_freshness_and_card.py",
            "--deselect",
            "tests/gui/shell/views/test_operator_display.py",
        ),
    ),
    "agents": (
        (
            "tests/agents",
            "tests/periodic",
            "tests/reporting",
            "tests/notifications",
        ),
    ),
    "remaining": (
        (
            "tests/",
            "--ignore=tests/core",
            "--ignore=tests/health",
            "--ignore=tests/engine_wiring",
            "--ignore=tests/gui",
            "--ignore=tests/agents",
            "--ignore=tests/periodic",
            "--ignore=tests/reporting",
            "--ignore=tests/notifications",
        ),
    ),
}


def suite_for_node(node: str) -> str:
    """Preserve the candidate-runner partition lookup API."""

    return _guard_suite_for_node(node)


def _write_response_file(path: Path, arguments: tuple[str, ...]) -> None:
    if any("\n" in argument or "\r" in argument for argument in arguments):
        raise ValueError("pytest response-file arguments must each occupy exactly one line")
    path.write_text("".join(f"{argument}\n" for argument in arguments), encoding="utf-8", newline="\n")


def _suite_commands(
    suite: str,
    *,
    root: Path,
    basetemp: Path | None,
    active_nodes: tuple[str, ...] = (),
) -> tuple[tuple[str, ...], ...]:
    selections = _SELECTIONS.get(suite)
    if selections is None:
        raise ValueError(f"unknown candidate suite: {suite}")
    if basetemp is None:
        raw = os.environ.get("CRYODAQ_CANDIDATE_PYTEST_BASETEMP")
        if not raw:
            raise ValueError("candidate pytest basetemp is not bound")
        basetemp = Path(raw)
    resolved_root = root.resolve(strict=True)
    resolved_base = basetemp.resolve(strict=False)
    try:
        resolved_base.relative_to(resolved_root)
    except ValueError:
        pass
    else:
        raise ValueError("candidate pytest basetemp must be outside the exported tree")
    resolved_base.mkdir(parents=True, exist_ok=True)
    if suite == "remaining":
        checkout_files, checkout_nodes = checkout_execution_selection(root, suite)
        checkout_file_set = set(checkout_files)
        selections = tuple(
            (*selection, *(f"--ignore={path}" for path in checkout_files)) if index == len(selections) else selection
            for index, selection in enumerate(selections, start=1)
        )
        excluded_nodes = tuple(node for node in checkout_nodes if node.split("::", 1)[0] not in checkout_file_set)
        selections = tuple(
            (*arguments, *(argument for node in excluded_nodes for argument in ("--deselect", node)))
            if index == len(selections)
            else arguments
            for index, arguments in enumerate(selections, start=1)
        )
    ordinary_response: tuple[str, ...] = ()
    if active_nodes:
        deselect_file = resolved_base / f"{suite}-ordinary-deselect-active-guards.args"
        deselect_arguments = tuple(argument for node in active_nodes for argument in ("--deselect", node))
        _write_response_file(deselect_file, deselect_arguments)
        ordinary_response = (f"@{deselect_file}",)
    return tuple(
        _PYTEST + ("--basetemp", str(resolved_base / f"{suite}-{index}")) + selection + ordinary_response + _TAIL
        for index, selection in enumerate(selections, start=1)
    )


def _strict_guard_command(
    suite: str,
    *,
    active_nodes: tuple[str, ...],
    basetemp: Path,
    execution_root: str = "exported-commit",
    pytest_command: tuple[str, ...] = _PYTEST,
) -> tuple[str, ...] | None:
    """Build the Windows-safe exact active-guard command for one suite."""

    if not active_nodes:
        return None
    argsfile = basetemp / f"{suite}-active-guards.args"
    _write_response_file(argsfile, active_nodes)
    return (
        pytest_command
        + (
            "-p",
            "tools.ci_guard_execution",
            "--cryodaq-active-guard-suite",
            suite,
            "--cryodaq-active-guard-execution-root",
            execution_root,
            "-W",
            "error",
            "--basetemp",
            str(basetemp / f"{suite}-active-guards"),
            f"@{argsfile}",
        )
        + _TAIL
    )


def _protected_pytest_command(
    command: tuple[str, ...],
    *,
    root: Path,
    producer_root: Path,
    strict: bool,
) -> tuple[str, ...]:
    """Load receipt plugins from the pinned producer, never from the candidate."""

    resolved_root = root.resolve(strict=True)
    resolved_producer = producer_root.resolve(strict=True)
    try:
        resolved_producer.relative_to(resolved_root)
    except ValueError:
        pass
    else:
        raise ValueError("protected producer must be outside the candidate tree")
    for relative in ("tools/ci_candidate_evidence.py", "tools/ci_guard_execution.py"):
        if not (resolved_producer / relative).is_file():
            raise ValueError(f"protected producer input is missing: {relative}")
    if command[:4] != (sys.executable, "-B", "-m", "pytest"):
        raise ValueError("protected producer received an unexpected pytest command")
    arguments = list(command[4:])
    for plugin in ("tools.ci_candidate_evidence", "tools.ci_guard_execution"):
        while plugin in arguments:
            offset = arguments.index(plugin)
            if offset == 0 or arguments[offset - 1] != "-p":
                raise ValueError(f"protected pytest plugin argument is malformed: {plugin}")
            del arguments[offset - 1 : offset + 1]
    return (
        sys.executable,
        "-B",
        "-I",
        "-X",
        "utf8=1",
        "-c",
        _PROTECTED_PYTEST_BOOTSTRAP,
        str(resolved_producer),
        str(resolved_root),
        "1" if strict else "0",
        *arguments,
    )


def _validate_strict_guard_receipt(
    output: str,
    *,
    suite: str,
    expected: tuple[str, ...],
    expected_platforms: dict[str, str | None],
    platform: str,
) -> None:
    lines = [line[len(RECEIPT_PREFIX) :] for line in output.splitlines() if line.startswith(RECEIPT_PREFIX)]
    if len(lines) != 1:
        raise GuardExecutionError(f"strict guard execution emitted {len(lines)} receipts instead of one")
    raw = lines[0]
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise GuardExecutionError(f"strict guard receipt is not canonical JSON: {exc}") from exc
    if not isinstance(envelope, dict) or set(envelope) != _RECEIPT_FIELDS:
        raise GuardExecutionError("strict guard receipt envelope shape is not exact")
    payload = envelope.get("payload")
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
        raise GuardExecutionError("strict guard receipt payload shape is not exact")
    if raw != canonical_receipt(payload):
        raise GuardExecutionError("strict guard receipt digest or canonical encoding is invalid")
    if payload.get("schema_version") != 3 or payload.get("suite") != suite or payload.get("platform") != platform:
        raise GuardExecutionError("strict guard receipt schema or suite is misbound")
    if payload.get("expected_guards") != list(expected):
        raise GuardExecutionError("strict guard receipt does not bind the exact expected guard set")
    if payload.get("expected_guard_platforms") != expected_platforms:
        raise GuardExecutionError("strict guard receipt does not bind exact guard platforms")
    if payload.get("result") != "passed":
        raise GuardExecutionError("strict guard receipt reports failure")
    for field in ("deselected_nodes", "violations", "warnings"):
        if payload.get(field) != []:
            raise GuardExecutionError(f"strict guard receipt retains {field}")
    concrete = payload.get("concrete_nodes")
    if not isinstance(concrete, list) or not concrete:
        raise GuardExecutionError("strict guard receipt has no concrete executed nodes")
    expected_set = set(expected)
    bound: set[str] = set()
    nodeids: set[str] = set()
    for item in concrete:
        if not isinstance(item, dict) or set(item) != {"guards", "markers", "nodeid", "phases", "was_xfail"}:
            raise GuardExecutionError("strict guard concrete-node shape is not exact")
        guards = item.get("guards")
        nodeid = item.get("nodeid")
        phases = item.get("phases")
        if (
            not isinstance(guards, list)
            or not guards
            or any(guard not in expected_set for guard in guards)
            or not isinstance(nodeid, str)
            or nodeid in nodeids
        ):
            raise GuardExecutionError("strict guard concrete-node identity is invalid")
        markers = item.get("markers")
        if not isinstance(markers, list) or item.get("was_xfail") is not False:
            raise GuardExecutionError("strict guard concrete node marker receipt is invalid")
        scopes = {expected_platforms[guard] for guard in guards}
        if len(scopes) != 1:
            raise GuardExecutionError("strict guard concrete node has conflicting platform scopes")
        scope = scopes.pop()
        skipif_count = 0
        normalized: list[dict[str, Any]] = []
        for marker in markers:
            if not isinstance(marker, dict):
                raise GuardExecutionError("strict guard marker receipt is not an exact mapping")
            if marker.get("name") == "filterwarnings":
                if set(marker) != {"name", "filters"}:
                    raise GuardExecutionError("strict guard warning-filter receipt shape is invalid")
                filters = marker.get("filters")
                if (
                    not isinstance(filters, list)
                    or not filters
                    or any(not isinstance(value, str) or value.split(":", 1)[0].strip() != "error" for value in filters)
                ):
                    raise GuardExecutionError("strict guard warning filter is suppressive or malformed")
            elif marker.get("name") == "skipif":
                if set(marker) != {"name", "condition", "reason", "target_platform"}:
                    raise GuardExecutionError("strict guard skipif receipt shape is invalid")
                if (
                    scope is None
                    or scope != platform
                    or marker.get("target_platform") != scope
                    or marker.get("condition") is not False
                    or not isinstance(marker.get("reason"), str)
                    or not marker["reason"].strip()
                ):
                    raise GuardExecutionError("strict guard skipif is not false on its bound platform")
                skipif_count += 1
            else:
                raise GuardExecutionError("strict guard marker receipt contains an unknown marker")
            normalized.append(marker)
        normalized.sort(key=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")))
        if markers != normalized:
            raise GuardExecutionError("strict guard marker receipt is not canonically ordered")
        if (scope is None and skipif_count != 0) or (scope is not None and skipif_count != 1):
            raise GuardExecutionError("strict guard skipif count does not match its platform scope")
        if phases != {phase: ["passed"] for phase in ("setup", "call", "teardown")}:
            raise GuardExecutionError("strict guard concrete node lacks exactly one passing phase receipt")
        if not any(nodeid == guard or nodeid.startswith(f"{guard}[") for guard in guards):
            raise GuardExecutionError("strict guard concrete node is not bound to its declared guard")
        nodeids.add(nodeid)
        bound.update(guards)
    if bound != expected_set:
        raise GuardExecutionError("strict guard receipt omits an expected guard")


def _command_environment(*, basetemp: Path, suite: str, index: int) -> dict[str, str]:
    root = basetemp.parent / "command-state" / suite / str(index)
    runtime = root / "runtime"
    temp = root / "tmp"
    cache = root / "cache"
    pycache = root / "pycache"
    for path in (runtime, temp, cache, pycache):
        path.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    for key in (
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "GH_TOKEN",
        "GITHUB_ENV",
        "GITHUB_OUTPUT",
        "GITHUB_PATH",
        "GITHUB_STATE",
        "GITHUB_STEP_SUMMARY",
        "GITHUB_TOKEN",
    ):
        environment.pop(key, None)
    environment.update(
        {
            "COVERAGE_FILE": str(cache / ".coverage"),
            "CRYODAQ_STATE_ROOT": str(runtime),
            FAILURE_RECEIPT_INDEX_ENV: str(index),
            FAILURE_RECEIPT_SUITE_ENV: suite,
            "MPLCONFIGDIR": str(cache / "matplotlib"),
            "NUMBA_CACHE_DIR": str(cache / "numba"),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONPYCACHEPREFIX": str(pycache),
            "TEMP": str(temp),
            "TMP": str(temp),
            "TMPDIR": str(temp),
            "XDG_CACHE_HOME": str(cache / "xdg"),
        }
    )
    return environment


def _relay_strict_output(completed: subprocess.CompletedProcess[str]) -> str:
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n", flush=True)
    if stderr:
        print(stderr, end="" if stderr.endswith("\n") else "\n", file=sys.stderr, flush=True)
    return stdout + stderr


def run_suite(
    suite: str,
    *,
    root: Path,
    basetemp: Path | None = None,
    protected_producer_root: Path | None = None,
    candidate_git_repository: Path | None = None,
    candidate_git_revision: str | None = None,
) -> int:
    try:
        manifest = compile_python_tree(root)
    except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
        _emit_phase_diagnosis(
            suite=suite,
            phase="compile",
            reason=str(exc),
            remediation="Repair the candidate source so it compiles before pytest starts.",
        )
        print(f"candidate-suite={suite} compile-failure={exc}", file=sys.stderr, flush=True)
        return 1
    print(f"candidate-suite={suite} compiled-sources={len(manifest)}", flush=True)
    try:
        platform = current_guard_platform()
        # A protected run executes this module from the JUDGE checkout against a
        # sealed export, so neither location can supply the candidate's history.
        # The candidate's real repository is passed in explicitly, and when it is
        # present the protected path REQUIRES object resolution rather than
        # accepting the sealed export's unresolved tier.
        active_specs = active_guard_specs(
            root,
            suite,
            platform=platform,
            git_repository=candidate_git_repository,
            # Keyed on the protected path ALONE. Conditioning this on the repository
            # also being present would mean a missing repository silently downgrades
            # to the unresolved tier -- the precise fallback this must refuse.
            require_git_resolution=protected_producer_root is not None,
        )
        active_nodes = tuple(spec.node for spec in active_specs)
        active_platforms = {spec.node: spec.platform for spec in active_specs}
        commands = _suite_commands(
            suite,
            root=root,
            basetemp=basetemp,
            active_nodes=active_nodes,
        )
        raw_guard_basetemp = str(basetemp) if basetemp is not None else os.environ["CRYODAQ_CANDIDATE_PYTEST_BASETEMP"]
        guard_basetemp = Path(raw_guard_basetemp).resolve(strict=False)
        guard_command = _strict_guard_command(
            suite,
            active_nodes=active_nodes,
            basetemp=guard_basetemp,
        )
    except (KeyError, OSError, UnicodeError, ValueError) as exc:
        expected_blobs, actual_blobs, affected = _guard_blob_diagnosis(exc)
        _emit_phase_diagnosis(
            suite=suite,
            phase="guard-setup",
            reason=str(exc),
            expected_blobs=expected_blobs,
            actual_blobs=actual_blobs,
            affected_receipt_ids=affected,
            remediation=(
                "Restore the guard bytes bound by the closure receipt, or reopen the affected prevention "
                "with new evidence."
                if affected
                else "Repair the guard registry or runner setup before pytest starts."
            ),
        )
        print(f"candidate-suite={suite} guard-setup-failure={exc}", file=sys.stderr, flush=True)
        return 1
    if guard_command is None:
        print(f"{RECEIPT_PREFIX}{empty_guard_receipt(suite, platform=platform)}", flush=True)
    all_commands: tuple[tuple[tuple[str, ...], bool], ...]
    if guard_command is None:
        all_commands = tuple((command, False) for command in commands)
    else:
        all_commands = ((guard_command, True),) + tuple((command, False) for command in commands)
    if protected_producer_root is not None:
        try:
            all_commands = tuple(
                (
                    _protected_pytest_command(
                        command,
                        root=root,
                        producer_root=protected_producer_root,
                        strict=is_strict,
                    ),
                    is_strict,
                )
                for command, is_strict in all_commands
            )
        except (OSError, ValueError) as exc:
            _emit_phase_diagnosis(
                suite=suite,
                phase="guard-setup",
                reason=str(exc),
                remediation="Restore the pinned protected producer checkout before pytest starts.",
            )
            return 1
    failures: list[tuple[int, int]] = []
    for index, (command, is_strict) in enumerate(all_commands, start=1):
        print(f"candidate-suite={suite} command={index}/{len(all_commands)}", flush=True)
        environment = _command_environment(basetemp=guard_basetemp, suite=suite, index=index)
        if is_strict:
            completed: subprocess.CompletedProcess[Any] = subprocess.run(
                command,
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            output = _relay_strict_output(completed)
            if completed.returncode == 0:
                try:
                    _validate_strict_guard_receipt(
                        output,
                        suite=suite,
                        expected=active_nodes,
                        expected_platforms=active_platforms,
                        platform=platform,
                    )
                except (GuardExecutionError, TypeError, ValueError) as exc:
                    print(f"candidate-suite={suite} invalid-guard-receipt={exc}", file=sys.stderr, flush=True)
                    failures.append((index, 1))
                    continue
        else:
            completed = subprocess.run(
                command,
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            output = _relay_strict_output(completed)
        try:
            _validate_candidate_population_receipt(output, suite=suite, index=index)
        except CiCandidateEvidenceError as exc:
            _emit_phase_diagnosis(
                suite=suite,
                phase="pytest",
                reason=str(exc),
                affected_receipt_ids=(f"pytest:{index}",),
                remediation="Restore one complete candidate population receipt for this pytest invocation.",
            )
            failures.append((index, 1))
            continue
        if completed.returncode != 0:
            failures.append((index, completed.returncode))
    if failures:
        print(f"candidate-suite={suite} failures={failures!r}", file=sys.stderr, flush=True)
        return failures[0][1] or 1
    if protected_producer_root is not None:
        if candidate_git_repository is None or candidate_git_revision is None:
            print(f"candidate-suite={suite} checkout-guard-setup-failure=missing Git checkout binding", file=sys.stderr)
            return 1
        from tools import ci_active_checkout_runner

        checkout_result = ci_active_checkout_runner.run_suite(
            suite,
            root=candidate_git_repository,
            revision=candidate_git_revision,
            basetemp=guard_basetemp / "git-index",
            protected_producer_root=protected_producer_root,
        )
        if checkout_result:
            return checkout_result
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=sorted(_SELECTIONS), required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--protected-producer-root", type=Path)
    parser.add_argument("--candidate-git-repository", type=Path)
    parser.add_argument("--candidate-git-revision")
    args = parser.parse_args(argv)
    return run_suite(
        args.suite,
        root=args.root,
        protected_producer_root=args.protected_producer_root,
        candidate_git_repository=args.candidate_git_repository,
        candidate_git_revision=args.candidate_git_revision,
    )


if __name__ == "__main__":
    raise SystemExit(main())
