from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools import ci_candidate_runner
from tools.ci_guard_execution import (
    RECEIPT_PREFIX,
    GuardExecutionError,
    active_guard_nodes,
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
