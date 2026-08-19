from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools import ci_active_checkout_runner, ci_candidate_runner, ci_guard_execution
from tools.ci_execution_roots import ExecutionSelection
from tools.ci_guard_execution import (
    RECEIPT_PREFIX,
    GuardExecutionError,
    GuardSpec,
    active_guard_nodes,
    active_guard_specs,
    current_guard_platform,
    empty_guard_receipt,
)
from tools.governance_contract import (
    GovernanceContractError,
    _git_blob_id,
    closure_semantics_sha256,
    validate_registry,
)

ROOT = Path(__file__).resolve().parents[2]


def _guard_source_blobs(record: dict) -> dict[str, str]:
    paths = {guard["node"].split("::", 1)[0] for guard in record["guards"]}
    return {path: _git_blob_id((ROOT / path).read_bytes()) for path in sorted(paths)}


def _registry(
    node: str,
    *,
    status: str = "open",
    partition: str = "remaining",
    platform: str | None = None,
) -> dict:
    pending = "pending"
    scope = "campaign_local" if status == "expired" else "repository"
    record = {
        "id": "STRICT-GUARD-TEST-001",
        "status": status,
        "scope": scope,
        "authority_source": "test authority",
        "applies_to": "strict execution test fixture",
        "classification": "false_green",
        "correction_owner": "reviewer",
        "guard_owner": "reviewer",
        "disposition_owner": "reviewer",
        "consequence": "A nonexecuted guard could look green.",
        "invariant": "Every active guard executes and passes unconditionally.",
        "rule_refs": ["test policy"],
        "guards": [
            {
                "node": node,
                "ci_partition": partition,
                **({"platform": platform} if platform is not None else {}),
            }
        ],
        "red_evidence": (
            {"locator": "git:" + "1" * 40, "sha256": "sha256:" + "1" * 64}
            if status in {"closed", "expired"}
            else pending
        ),
        "green_evidence": (
            {"locator": "git:" + "2" * 40, "sha256": "sha256:" + "2" * 64}
            if status in {"closed", "expired"}
            else pending
        ),
    }
    if status == "expired":
        record.update(
            expires_when="fixture campaign ends",
            expiry_disposition="fixture no longer applies",
        )
    if status in {"closed", "expired"}:
        record["guard_source_blobs"] = _guard_source_blobs(record)
        record["closure_semantics_sha256"] = closure_semantics_sha256(record)
    return {
        "schema_version": 2,
        "registry_id": "STRICT-GUARD-TEST-REGISTRY",
        "status_definitions": {
            "open": "Required correction or evidence is incomplete.",
            "reopened": "A previously disposed invariant lost, weakened, skipped, or misbound enforcement.",
            "closed": "Invariant and guard are green with immutable reviewer-bound evidence.",
            "expired": (
                "Campaign-local coordination no longer applies after its named expiry and immutable final disposition."
            ),
        },
        "scope_definitions": {
            "repository": "Universal developer-agent, evidence, review, or publication invariant.",
            "product_contract": (
                "Durable CryoDAQ runtime or test invariant independent of the current campaign mechanics."
            ),
            "campaign_local": (
                "Temporary branch, worktree, lane, ordering, freeze, or completion rule with an explicit expiry."
            ),
        },
        "ownership_semantics": {
            "correction_owner": (
                "Default durable role that maintains the affected runtime, governance, evidence, or integration state "
                "outside an active campaign override."
            ),
            "guard_owner": (
                "Default durable implementation role that maintains the machine-testable guard outside an active "
                "campaign override."
            ),
            "disposition_owner": "Reviewer; no author self-closes its correction or guard.",
            "campaign_edit_owner_override": (
                "Exact campaign-local path or node assignment that supersedes durable owners for authoring only and "
                "expires with the campaign."
            ),
            "edit_owner_precedence": (
                "Active exact campaign override, then durable owner; every active path and guard node resolves to "
                "exactly one editor."
            ),
            "allowed_owners": ["reviewer", "primary", "cli", "each_agent"],
        },
        "campaign_expiry_semantics": {
            "required_terminal_status": "expired",
            "immutable_final_disposition": "required",
            "history_retention": "permanent_non_authoritative",
            "may_authorize_after_expiry": False,
        },
        "durable_product_contract_authority": "test authority",
        "policy_refs": ["test policy"],
        "default_ci_jobs": {
            "agents": ["test (ubuntu-latest, agents)", "test (windows-latest, agents)"],
            "core": ["test (ubuntu-latest, core)", "test (windows-latest, core)"],
            "gui": ["test (ubuntu-latest, gui)", "test (windows-latest, gui)"],
            "remaining": ["test (ubuntu-latest, remaining)", "test (windows-latest, remaining)"],
        },
        "false_green_pair_semantics": {
            "status": "required_and_linked",
            "scope": "inherited_from_runtime_prevention_id",
            "guard_identity": "exact_runtime_guard_link",
            "correction_owner": "inherited_from_runtime_prevention_id",
            "guard_owner": "inherited_from_runtime_prevention_id",
            "disposition_owner": "reviewer",
            "close_requires_runtime_closed": True,
            "close_requires_immutable_red_and_green_evidence": True,
            "guard_removed_skipped_xfailed_deselected_or_nondefault": "reopen",
        },
        "false_green_pairs": [],
        "records": [record],
    }


def _write_registry(
    root: Path,
    node: str,
    *,
    status: str = "open",
    partition: str = "remaining",
    platform: str | None = None,
) -> None:
    path = root / "governance" / "agent_preventions.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            _registry(node, status=status, partition=partition, platform=platform),
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )


def _write_test(root: Path, node: str, source: str) -> None:
    path = root / node.split("::", 1)[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8", newline="\n")


def _strict_environment() -> dict[str, str]:
    environment = os.environ.copy()
    prior = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(part for part in (str(ROOT), prior) if part)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return environment


def test_active_checkout_pytest_command_uses_entry_point_plugins_once(tmp_path: Path) -> None:
    test_file = tmp_path / "test_async.py"
    test_file.write_text(
        "import pytest\n\n@pytest.mark.asyncio\nasync def test_async(): pass\n",
        encoding="utf-8",
        newline="\n",
    )
    environment = os.environ.copy()
    prior = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(part for part in (str(ROOT), prior) if part)
    environment.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)

    control = subprocess.run(
        (sys.executable, "-B", "-m", "pytest", "-q", str(test_file)),
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        check=False,
        timeout=60,
    )
    assert control.returncode == 0, control.stdout + control.stderr
    assert "1 passed" in control.stdout

    completed = subprocess.run(
        ci_active_checkout_runner._PYTEST + ("-q", str(test_file), *ci_candidate_runner._TAIL),
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


def test_active_checkout_strict_guard_uses_entry_point_plugins_once(tmp_path: Path) -> None:
    node = "tests/governance/test_agent_formatter_gate.py::test_mutating_formatter_wrapper_is_absent"
    _write_registry(tmp_path, node)
    _write_test(
        tmp_path,
        node,
        "import pytest\n\n@pytest.mark.asyncio\nasync def test_mutating_formatter_wrapper_is_absent(): pass\n",
    )
    environment = os.environ.copy()
    prior = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(part for part in (str(ROOT), prior) if part)
    environment.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
    basetemp = tmp_path.parent / f"{tmp_path.name}-active-state"
    basetemp.mkdir()
    command = ci_candidate_runner._strict_guard_command(
        "remaining",
        active_nodes=(node,),
        basetemp=basetemp,
        execution_root="git-index",
        pytest_command=ci_active_checkout_runner._PYTEST,
    )

    assert command is not None
    completed = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        check=False,
        timeout=60,
    )
    payload = _receipt(completed)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert payload["result"] == "passed"


def test_file_selected_guard_runs_only_from_git_index() -> None:
    """Use the live default-CI selection; no synthetic registry or root is valid evidence."""
    node = "tests/docs/test_docs_freshness.py::test_oc013_physical_off_gate_retag_mutant_is_red"
    selected_files, selected_nodes = ci_guard_execution.checkout_execution_selection(ROOT, "remaining")
    assert "tests/docs/test_docs_freshness.py" in selected_files
    assert node not in selected_nodes

    platform = current_guard_platform()
    git_index = active_guard_specs(ROOT, "remaining", platform=platform, execution_root="git-index")
    exported = active_guard_specs(ROOT, "remaining", platform=platform, execution_root="exported-commit")
    assert any(spec.node == node for spec in git_index)
    assert all(spec.node != node for spec in exported)


def _run_strict(
    root: Path,
    *,
    suite: str,
    selected: tuple[str, ...],
    extra: tuple[str, ...] = (),
    warnings_as_errors: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-B",
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-p",
        "tools.ci_guard_execution",
        "--cryodaq-active-guard-suite",
        suite,
        "--rootdir",
        str(root),
        "--basetemp",
        str(root.parent / f"{root.name}-pytest-state"),
    ]
    if warnings_as_errors:
        command.extend(("-W", "error"))
    command.extend(selected)
    command.extend(extra)
    return subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_strict_environment(),
        check=False,
        timeout=60,
    )


def _receipt(completed: subprocess.CompletedProcess[str]) -> dict:
    lines = [
        line[len(RECEIPT_PREFIX) :]
        for line in (completed.stdout + completed.stderr).splitlines()
        if line.startswith(RECEIPT_PREFIX)
    ]
    assert len(lines) == 1, completed.stdout + completed.stderr
    envelope = json.loads(lines[0])
    payload_raw = json.dumps(
        envelope["payload"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert envelope["sha256"] == f"sha256:{hashlib.sha256(payload_raw).hexdigest()}"
    return envelope["payload"]


def test_active_guard_exact_execution_receipt_is_self_digesting_and_complete(tmp_path: Path) -> None:
    node = "tests/test_guard_cases.py::test_guard"
    source = """\
import pytest

@pytest.mark.parametrize("value", ("one", "two"))
def test_guard(value):
    assert value in {"one", "two"}
"""
    _write_registry(tmp_path, node)
    _write_test(tmp_path, node, source)

    completed = _run_strict(tmp_path, suite="remaining", selected=(node,))
    payload = _receipt(completed)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert payload["result"] == "passed"
    assert payload["expected_guards"] == [node]
    assert [item["nodeid"] for item in payload["concrete_nodes"]] == [
        f"{node}[one]",
        f"{node}[two]",
    ]
    assert all(
        item["phases"] == {"setup": ["passed"], "call": ["passed"], "teardown": ["passed"]}
        for item in payload["concrete_nodes"]
    )
    assert payload["violations"] == []


def test_error_only_warning_filter_is_bound_in_the_strict_receipt(tmp_path: Path) -> None:
    node = "tests/test_guard_cases.py::test_guard"
    _write_registry(tmp_path, node)
    _write_test(
        tmp_path,
        node,
        "import pytest\n"
        "@pytest.mark.filterwarnings('error::pytest.PytestUnraisableExceptionWarning')\n"
        "def test_guard(): pass\n",
    )

    completed = _run_strict(tmp_path, suite="remaining", selected=(node,))
    payload = _receipt(completed)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert payload["schema_version"] == 3
    assert payload["expected_guard_platforms"] == {node: None}
    assert payload["concrete_nodes"][0]["markers"] == [
        {
            "filters": ["error::pytest.PytestUnraisableExceptionWarning"],
            "name": "filterwarnings",
        }
    ]


def test_platform_guard_runs_only_on_owner_and_binds_false_skipif(tmp_path: Path) -> None:
    node = "tests/test_guard_cases.py::test_guard"
    platform = current_guard_platform()
    other = "posix" if platform == "windows" else "windows"
    condition = "os.name != 'nt'" if platform == "windows" else "os.name == 'nt'"
    _write_registry(tmp_path, node, platform=platform)
    _write_test(
        tmp_path,
        node,
        "import os\nimport pytest\n"
        f"@pytest.mark.skipif({condition}, reason='exact owner platform')\n"
        "def test_guard(): pass\n",
    )

    assert active_guard_nodes(tmp_path, "remaining", platform=platform) == (node,)
    assert active_guard_nodes(tmp_path, "remaining", platform=other) == ()
    completed = _run_strict(tmp_path, suite="remaining", selected=(node,))
    payload = _receipt(completed)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert payload["platform"] == platform
    assert payload["expected_guard_platforms"] == {node: platform}
    assert payload["concrete_nodes"][0]["markers"] == [
        {
            "condition": False,
            "name": "skipif",
            "reason": "exact owner platform",
            "target_platform": platform,
        }
    ]


def test_platform_guard_without_exact_false_skipif_fails_closed(tmp_path: Path) -> None:
    node = "tests/test_guard_cases.py::test_guard"
    platform = current_guard_platform()
    scenarios = {
        "missing": "def test_guard(): pass\n",
        "truthy-non-bool": (
            "import pytest\n@pytest.mark.skipif(0, reason='not an exact bool')\ndef test_guard(): pass\n"
        ),
        "empty-reason": ("import pytest\n@pytest.mark.skipif(False, reason='')\ndef test_guard(): pass\n"),
    }
    for name, source in scenarios.items():
        root = tmp_path / name
        root.mkdir()
        _write_registry(root, node, platform=platform)
        _write_test(root, node, source)
        completed = _run_strict(root, suite="remaining", selected=(node,))
        payload = _receipt(completed)
        assert completed.returncode != 0, name
        assert payload["result"] == "failed"
        assert any("guard marker policy violation" in value for value in payload["violations"])


def test_active_guard_execution_rejects_skip_xfail_deselection_collect_only_and_warnings(
    tmp_path: Path,
) -> None:
    node = "tests/test_guard_cases.py::test_guard"
    scenarios = {
        "skip": (
            "import pytest\n@pytest.mark.skip(reason='conditional')\ndef test_guard(): pass\n",
            (),
            True,
            "forbidden conditional markers ['skip']",
        ),
        "skipif-false": (
            "import pytest\n@pytest.mark.skipif(False, reason='conditional')\ndef test_guard(): pass\n",
            (),
            True,
            "skipif requires an exact platform-scoped registry guard",
        ),
        "xfail": (
            "import pytest\n@pytest.mark.xfail(reason='conditional')\ndef test_guard(): assert False\n",
            (),
            True,
            "xfail/xpass outcome",
        ),
        "filterwarnings": (
            "import pytest\n@pytest.mark.filterwarnings('ignore:never')\ndef test_guard(): pass\n",
            (),
            True,
            "filterwarnings must contain only positional error-action filters",
        ),
        "timeout": (
            "import pytest\n@pytest.mark.timeout(600)\ndef test_guard(): pass\n",
            (),
            True,
            "forbidden conditional markers ['timeout']",
        ),
        "dynamic-skip": (
            "import pytest\ndef test_guard(): pytest.skip('dynamic')\n",
            (),
            True,
            "call=['skipped']",
        ),
        "dynamic-xfail": (
            "import pytest\ndef test_guard(): pytest.xfail('dynamic')\n",
            (),
            True,
            "xfail/xpass outcome",
        ),
        "setup-failure": (
            "import pytest\n@pytest.fixture\ndef broken(): raise RuntimeError('setup')\ndef test_guard(broken): pass\n",
            (),
            True,
            "setup=['failed']",
        ),
        "call-failure": (
            "def test_guard(): assert False\n",
            (),
            True,
            "call=['failed']",
        ),
        "teardown-failure": (
            "import pytest\n"
            "@pytest.fixture\n"
            "def broken():\n"
            "    yield\n"
            "    raise RuntimeError('teardown')\n"
            "def test_guard(broken): pass\n",
            (),
            True,
            "teardown=['failed']",
        ),
        "deselected": (
            "def test_guard(): pass\n",
            ("--deselect", node),
            True,
            "guard was deselected",
        ),
        "collect-only": (
            "def test_guard(): pass\n",
            ("--collect-only",),
            True,
            "collection-only execution cannot prove",
        ),
        "warning": (
            "import warnings\ndef test_guard(): warnings.warn('guard warning', UserWarning)\n",
            (),
            False,
            "guard execution emitted warning",
        ),
    }
    for name, (source, extra, warnings_as_errors, expected) in scenarios.items():
        root = tmp_path / name
        root.mkdir()
        _write_registry(root, node)
        _write_test(root, node, source)
        completed = _run_strict(
            root,
            suite="remaining",
            selected=(node,),
            extra=extra,
            warnings_as_errors=warnings_as_errors,
        )
        payload = _receipt(completed)
        assert completed.returncode != 0, name
        assert payload["result"] == "failed"
        assert any(expected in violation for violation in payload["violations"]), (name, payload)


def test_active_guard_execution_rejects_partial_parameterization_and_wrong_suite_selection(
    tmp_path: Path,
) -> None:
    node = "tests/test_guard_cases.py::test_guard"
    parametrized = tmp_path / "partial"
    parametrized.mkdir()
    _write_registry(parametrized, node)
    _write_test(
        parametrized,
        node,
        "import pytest\n@pytest.mark.parametrize('value', ('one', 'two'))\ndef test_guard(value): pass\n",
    )
    partial = _run_strict(
        parametrized,
        suite="remaining",
        selected=(node,),
        extra=("--deselect", f"{node}[two]"),
    )
    partial_payload = _receipt(partial)
    assert partial.returncode != 0
    assert f"guard was deselected: {node}[two]" in partial_payload["violations"]

    wrong_suite = tmp_path / "wrong-suite"
    wrong_suite.mkdir()
    wrong_node = "tests/gui/test_wrong_suite.py::test_wrong_suite"
    _write_registry(wrong_suite, node)
    _write_test(wrong_suite, node, "def test_guard(): pass\n")
    _write_test(wrong_suite, wrong_node, "def test_wrong_suite(): pass\n")
    wrong = _run_strict(wrong_suite, suite="remaining", selected=(node, wrong_node))
    wrong_payload = _receipt(wrong)
    assert wrong.returncode != 0
    assert f"unexpected or wrong-suite test was selected: {wrong_node}" in wrong_payload["violations"]


def test_active_guard_execution_detects_silent_collection_deletion_and_duplicate_phase_reports(
    tmp_path: Path,
) -> None:
    node = "tests/test_guard_cases.py::test_guard"
    deleted = tmp_path / "deleted"
    deleted.mkdir()
    _write_registry(deleted, node)
    _write_test(
        deleted,
        node,
        "import pytest\n@pytest.mark.parametrize('value', ('good', 'bad'))\ndef test_guard(value): pass\n",
    )
    (deleted / "conftest.py").write_text(
        "def pytest_collection_modifyitems(items):\n"
        "    items[:] = [item for item in items if not item.nodeid.endswith('[bad]')]\n",
        encoding="utf-8",
        newline="\n",
    )
    removed = _run_strict(deleted, suite="remaining", selected=(node,))
    removed_payload = _receipt(removed)
    assert removed.returncode != 0
    assert f"guard was deselected: {node}[bad]" in removed_payload["violations"]

    duplicated = tmp_path / "duplicated"
    duplicated.mkdir()
    _write_registry(duplicated, node)
    _write_test(duplicated, node, "def test_guard(): pass\n")
    (duplicated / "conftest.py").write_text(
        "from tools import ci_guard_execution\n\n"
        "def pytest_runtest_logreport(report):\n"
        "    ci_guard_execution.pytest_runtest_logreport(report)\n",
        encoding="utf-8",
        newline="\n",
    )
    duplicate = _run_strict(duplicated, suite="remaining", selected=(node,))
    duplicate_payload = _receipt(duplicate)
    assert duplicate.returncode != 0
    assert any("setup=['passed', 'passed']" in violation for violation in duplicate_payload["violations"])


def test_active_guard_registry_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    node = "tests/test_guard_cases.py::test_guard"
    _write_registry(tmp_path, node)
    path = tmp_path / "governance" / "agent_preventions.yaml"
    text = path.read_text(encoding="utf-8")
    assert "  status: open\n  scope:" in text
    path.write_text(
        text.replace("  status: open\n  scope:", "  status: open\n  status: closed\n  scope:", 1),
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(GuardExecutionError, match="duplicate key 'status'"):
        active_guard_nodes(tmp_path, "remaining")


def test_open_reopened_and_closed_guards_execute_while_expired_does_not(tmp_path: Path) -> None:
    node = "tests/governance/test_active_guard_execution.py::test_active_guard_registry_rejects_duplicate_yaml_keys"
    for status in ("open", "reopened", "closed"):
        root = tmp_path / status
        _write_registry(root, node, status=status)
        assert active_guard_nodes(root, "remaining") == (node,)

    expired = tmp_path / "expired"
    _write_registry(expired, node, status="expired")
    assert active_guard_nodes(expired, "remaining") == ()
    envelope = json.loads(empty_guard_receipt("remaining"))
    assert envelope["payload"] == {
        "concrete_nodes": [],
        "deselected_nodes": [],
        "expected_guards": [],
        "expected_guard_platforms": {},
        "platform": current_guard_platform(),
        "result": "passed",
        "schema_version": 3,
        "suite": "remaining",
        "violations": [],
        "warnings": [],
    }


def test_file_selected_active_guard_routes_to_git_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    node = "tests/test_guard_cases.py::test_guard"
    _write_registry(tmp_path, node)
    _write_test(tmp_path, node, "def test_guard(): pass\n")
    monkeypatch.setattr(
        "tools.ci_guard_execution._checkout_execution_selection",
        lambda _suite: ExecutionSelection("git-index", "remaining", ("tests/test_guard_cases.py",), ()),
    )

    assert active_guard_specs(tmp_path, "remaining", execution_root="exported-commit") == ()
    assert active_guard_specs(tmp_path, "remaining", execution_root="git-index") == (
        GuardSpec(node, "remaining", None),
    )


def test_protected_checkout_runner_detaches_exported_candidate_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Judge-owned checkout runs must not inherit the sealed export's poisoned environment.

    The population-receipt plugin fails closed without a per-invocation index
    only the exported partition accounting owns, and disabled plugin autoload
    withdraws the entry-point plugins the checkout tests rely on.
    """

    from tools.ci_candidate_evidence import FAILURE_RECEIPT_INDEX_ENV, FAILURE_RECEIPT_SUITE_ENV

    producer = tmp_path / "producer"
    (producer / "tools").mkdir(parents=True)
    (producer / "tools" / "ci_candidate_evidence.py").write_text("# pinned\n", encoding="utf-8", newline="\n")
    (producer / "tools" / "ci_guard_execution.py").write_text("# pinned\n", encoding="utf-8", newline="\n")
    repository = tmp_path / "candidate"
    repository.mkdir()
    monkeypatch.setattr(ci_active_checkout_runner, "_verify_checkout", lambda *_args: None)
    monkeypatch.setattr(ci_active_checkout_runner, "compile_python_tree", lambda _root: {})
    monkeypatch.setattr(
        ci_active_checkout_runner,
        "compare_red_reproduction_bindings",
        lambda *_args, **_kwargs: {"outcome": "passed"},
    )
    monkeypatch.setattr(ci_active_checkout_runner, "active_guard_specs", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        "tools.ci_guard_execution._checkout_execution_selection",
        lambda _suite: ExecutionSelection("git-index", "remaining", ("tests/test_docs.py",), ()),
    )
    monkeypatch.setenv(FAILURE_RECEIPT_SUITE_ENV, "remaining")
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("CRYODAQ_EXPORTED_CANDIDATE", "1")
    # An inherited PYTHONPATH is poison twice over: it binds the judge's tree
    # instead of the candidate's, and its absence leaves the candidate's
    # src-layout package unimportable. The checkout environment must pin the
    # candidate's own root and src, exactly as the sealed candidate runner's
    # bootstrap does (tools/ci_candidate_runner.py).
    monkeypatch.setenv("PYTHONPATH", "/poison/judge/src")
    monkeypatch.delenv(FAILURE_RECEIPT_INDEX_ENV, raising=False)
    captured: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def fake_run(
        command: tuple[str, ...], *, root: Path, environment: dict[str, str], capture_output: bool
    ) -> subprocess.CompletedProcess[str]:
        captured.append((tuple(command), environment))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ci_active_checkout_runner, "_run_candidate_process", fake_run)

    assert (
        ci_active_checkout_runner.run_suite(
            "remaining",
            root=repository,
            revision="0" * 40,
            basetemp=tmp_path / "basetemp",
            trusted_base="a" * 40,
            protected_producer_root=producer,
        )
        == 0
    )
    assert len(captured) == 1
    command, environment = captured[0]
    # The pinned producer bootstrap drives pytest; candidate plugins are never loaded.
    assert command[1:6] == ("-B", "-I", "-X", "utf8=1", "-c")
    assert str(producer.resolve()) in command
    assert str(repository.resolve()) in command
    assert FAILURE_RECEIPT_SUITE_ENV not in environment
    assert FAILURE_RECEIPT_INDEX_ENV not in environment
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" not in environment
    assert "CRYODAQ_EXPORTED_CANDIDATE" not in environment
    resolved = repository.resolve()
    assert environment["PYTHONPATH"] == os.pathsep.join((str(resolved), str(resolved / "src")))


def test_false_green_expiry_cannot_outlive_runtime_or_expire_durable_scope() -> None:
    node = (
        "tests/governance/test_active_guard_execution.py"
        "::test_active_guard_nodes_deduplicate_runtime_and_false_green_mappings"
    )
    active_pair = {
        "id": "STRICT-GUARD-FALSE-GREEN-001",
        "status": "open",
        "scope": "campaign_local",
        "runtime_prevention_id": "STRICT-GUARD-TEST-001",
        "guard": node,
        "ci_partition": "remaining",
        "red_evidence": "pending",
        "green_evidence": "pending",
    }
    expired_runtime = _registry(node, status="expired")
    expired_runtime["false_green_pairs"] = [active_pair]
    with pytest.raises(GovernanceContractError, match="remains active"):
        validate_registry(expired_runtime)

    durable_pair = dict(active_pair)
    durable_pair.update(
        status="expired",
        scope="repository",
        red_evidence="sha256:" + "2" * 64,
        green_evidence="sha256:" + "3" * 64,
    )
    closed_runtime = _registry(node, status="closed")
    closed_runtime["false_green_pairs"] = [durable_pair]
    with pytest.raises(GovernanceContractError, match="campaign-local"):
        validate_registry(closed_runtime)


def test_candidate_runner_response_file_executes_exact_active_guards(tmp_path: Path) -> None:
    node = "tests/test_guard_cases.py::test_guard"
    _write_registry(tmp_path, node)
    _write_test(tmp_path, node, "def test_guard(): pass\n")
    basetemp = tmp_path.parent / f"{tmp_path.name}-candidate-state"
    basetemp.mkdir()

    command = ci_candidate_runner._strict_guard_command(
        "remaining",
        active_nodes=(node,),
        basetemp=basetemp,
    )

    assert command is not None
    response_files = [argument for argument in command if argument.startswith("@")]
    assert len(response_files) == 1
    assert Path(response_files[0][1:]).read_text(encoding="utf-8") == f"{node}\n"
    completed = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_strict_environment(),
        check=False,
        timeout=60,
    )
    payload = _receipt(completed)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert payload["result"] == "passed"


def test_active_guard_nodes_deduplicate_runtime_and_false_green_mappings(tmp_path: Path) -> None:
    node = "tests/test_guard_cases.py::test_guard"
    payload = _registry(node)
    payload["false_green_pairs"] = [
        {
            "id": "STRICT-GUARD-FALSE-GREEN-001",
            "status": "open",
            "scope": "repository",
            "runtime_prevention_id": "STRICT-GUARD-TEST-001",
            "guard": node,
            "ci_partition": "remaining",
            "red_evidence": "pending",
            "green_evidence": "pending",
        }
    ]
    registry = tmp_path / "governance" / "agent_preventions.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )

    assert active_guard_nodes(tmp_path, "remaining") == (node,)


def test_candidate_runner_executes_each_active_parameter_once_and_deselects_it_from_ordinary_suite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    node = "tests/test_guard_cases.py::test_guard"
    _write_registry(root, node)
    _write_test(
        root,
        node,
        "import os\n"
        "from pathlib import Path\n"
        "import pytest\n\n"
        "def _record(value):\n"
        "    path = Path(os.environ['CRYODAQ_GUARD_COUNTER'])\n"
        "    with path.open('a', encoding='utf-8') as stream:\n"
        "        stream.write(value + '\\n')\n\n"
        "@pytest.mark.parametrize('value', ('one', 'two'))\n"
        "def test_guard(value):\n"
        "    _record('guard:' + value)\n\n"
        "def test_ordinary():\n"
        "    _record('ordinary')\n",
    )
    counter = tmp_path / "guard-events.txt"
    state = tmp_path / "candidate-state"
    monkeypatch.setenv("CRYODAQ_GUARD_COUNTER", str(counter))
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    prior = os.environ.get("PYTHONPATH")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(part for part in (str(ROOT), prior) if part))

    assert ci_candidate_runner.run_suite("remaining", root=root, basetemp=state) == 0
    assert counter.read_text(encoding="utf-8").splitlines() == [
        "guard:one",
        "guard:two",
        "ordinary",
    ]
    assert (state / "remaining-active-guards.args").read_text(encoding="utf-8").splitlines() == [node]
    assert (state / "remaining-ordinary-deselect-active-guards.args").read_text(encoding="utf-8").splitlines() == [
        "--deselect",
        node,
    ]


def test_release_selection_runs_strictly_and_refuses_skip_marker(tmp_path: Path) -> None:
    """The release suite registers no guards, so its whole selection must be fed
    to the strict active-guard runner as required files; a skip/xfail marker on
    it must be a red strict receipt, never a silent green (PR #70 finding).
    """
    files, nodes = ci_guard_execution.checkout_execution_selection(ROOT, "release")
    assert files, "release suite selects no files"
    assert not nodes

    basetemp = tmp_path / "release-strict-state"
    basetemp.mkdir()
    command = ci_candidate_runner._strict_guard_command(
        "release",
        active_nodes=(),
        basetemp=basetemp,
        execution_root="git-index",
        pytest_command=ci_active_checkout_runner._PYTEST,
        required_files=files,
    )
    assert command is not None, "release strict command must exist despite zero registered guards"
    assert "tools.ci_guard_execution" in command
    required_offset = command.index("--cryodaq-active-guard-required-files")
    assert command[required_offset + 1] in files

    fixture = "tests/release/test_required_fixture.py"
    node = f"{fixture}::test_guard"
    root = tmp_path / "release-fixture"
    root.mkdir()
    # A non-release registry guard proves the release suite itself stays guard-free
    # while its selection is still enforced through required files.
    _write_registry(root, "tests/core/test_guard.py::test_guard", partition="core")
    _write_test(root, node, "def test_guard(): pass\n")
    passed = _run_strict(
        root,
        suite="release",
        selected=(fixture,),
        extra=("--cryodaq-active-guard-required-files", fixture),
    )
    passed_payload = _receipt(passed)
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert passed_payload["result"] == "passed"

    _write_test(root, node, "import pytest\n@pytest.mark.skip(reason='conditional')\ndef test_guard(): pass\n")
    skipped = _run_strict(
        root,
        suite="release",
        selected=(fixture,),
        extra=("--cryodaq-active-guard-required-files", fixture),
    )
    skipped_payload = _receipt(skipped)
    assert skipped.returncode != 0
    assert skipped_payload["result"] == "failed"
    assert any("forbidden conditional markers ['skip']" in value for value in skipped_payload["violations"])


def test_candidate_runner_rejects_real_zero_exit_without_session_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = "tests/test_guard_cases.py::test_guard"
    _write_registry(tmp_path, node)
    _write_test(tmp_path, node, "import os\ndef test_guard(): os._exit(0)\n")
    monkeypatch.setattr(ci_candidate_runner, "_suite_commands", lambda *_args, **_kwargs: ())
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    prior = os.environ.get("PYTHONPATH")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(part for part in (str(ROOT), prior) if part))

    result = ci_candidate_runner.run_suite(
        "remaining",
        root=tmp_path,
        basetemp=tmp_path.parent / f"{tmp_path.name}-zero-exit-state",
    )

    assert result == 1


def test_candidate_runner_rejects_failed_receipt_even_when_later_hook_resets_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = "tests/test_guard_cases.py::test_guard"
    _write_registry(tmp_path, node)
    _write_test(
        tmp_path,
        node,
        "import pytest\n@pytest.mark.skip(reason='conditional')\ndef test_guard(): pass\n",
    )
    (tmp_path / "conftest.py").write_text(
        "import pytest\n\n"
        "@pytest.hookimpl(hookwrapper=True, tryfirst=True)\n"
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    yield\n"
        "    session.exitstatus = 0\n",
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setattr(ci_candidate_runner, "_suite_commands", lambda *_args, **_kwargs: ())
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    prior = os.environ.get("PYTHONPATH")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(part for part in (str(ROOT), prior) if part))

    result = ci_candidate_runner.run_suite(
        "remaining",
        root=tmp_path,
        basetemp=tmp_path.parent / f"{tmp_path.name}-reset-exit-state",
    )

    assert result == 1


def test_sealed_checkout_runner_runs_without_trusted_base_authority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The sealed candidate runner reaches the checkout runner without the trusted base.

    ``tools.ci_candidate_runner`` calls ``ci_active_checkout_runner.run_suite``
    without ``trusted_base``: the bootstrap strips producer authority before
    candidate code runs, and the producer has already receipt-bound the same
    comparison.  The checkout runner must skip the comparison there rather than
    demand authority the sealed path can never hold.
    """

    repository = tmp_path / "candidate"
    repository.mkdir()
    monkeypatch.setattr(ci_active_checkout_runner, "_verify_checkout", lambda *_args: None)
    monkeypatch.setattr(ci_active_checkout_runner, "compile_python_tree", lambda _root: {})
    monkeypatch.setattr(ci_active_checkout_runner, "active_guard_specs", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        "tools.ci_guard_execution._checkout_execution_selection",
        lambda _suite: ExecutionSelection("git-index", "remaining", ("tests/test_docs.py",), ()),
    )

    def forbidden_compare(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("sealed checkout run must not demand trusted-base authority")

    monkeypatch.setattr(ci_active_checkout_runner, "compare_red_reproduction_bindings", forbidden_compare)

    def fake_run(
        command: tuple[str, ...], *, root: Path, environment: dict[str, str], capture_output: bool
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ci_active_checkout_runner, "_run_candidate_process", fake_run)

    assert (
        ci_active_checkout_runner.run_suite(
            "remaining",
            root=repository,
            revision="0" * 40,
            basetemp=tmp_path / "basetemp",
        )
        == 0
    )
