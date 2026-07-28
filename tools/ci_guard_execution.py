"""Strict execution proof for active governance guards.

The ordinary CI partitions execute every non-guard test. This plugin runs one
exact execution cut for every non-expired guard whose registry record is
``open``, ``reopened``, or ``closed``. An active guard is evidence only when
every concrete parametrization completes setup, call, and teardown with a
passing outcome and without conditional markers, deselection, or warnings.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from tools.ci_execution_roots import checkout_execution_selection as _checkout_execution_selection
from tools.governance_contract import validate_registry

ACTIVE_GUARD_STATUSES = frozenset({"open", "reopened", "closed"})
DEFAULT_CI_SUITES = ("agents", "core", "gui", "remaining")
GUARD_PLATFORMS = frozenset({"posix", "windows"})
FORBIDDEN_GUARD_MARKERS = frozenset({"skip", "timeout", "xfail"})
RECEIPT_PREFIX = "CRYODAQ_ACTIVE_GUARD_RECEIPT "
_PHASES = ("setup", "call", "teardown")
_STATE_ATTRIBUTE = "_cryodaq_active_guard_execution"


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that refuses every duplicate mapping key."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class GuardExecutionError(ValueError):
    """Raised when strict guard execution cannot be bound unambiguously."""


@dataclass(frozen=True, slots=True)
class GuardSpec:
    """One exact registry guard and its executable platform boundary."""

    node: str
    ci_partition: str
    platform: str | None


def current_guard_platform() -> str:
    """Return the registry platform name for this interpreter."""

    return "windows" if os.name == "nt" else "posix"


def suite_for_node(node: str) -> str:
    """Return the one default matrix suite that owns an exact pytest node."""

    path = node.split("::", 1)[0]
    if path.startswith(("tests/core/", "tests/health/", "tests/engine_wiring/")):
        return "core"
    if path.startswith("tests/gui/"):
        return "gui"
    if path.startswith(("tests/agents/", "tests/periodic/", "tests/reporting/", "tests/notifications/")):
        return "agents"
    if not path.startswith("tests/"):
        raise GuardExecutionError(f"candidate guard is not a pytest node: {node}")
    return "remaining"


def _registry(root: Path) -> dict[str, Any]:
    path = root / "governance" / "agent_preventions.yaml"
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise GuardExecutionError(f"cannot read canonical prevention registry: {exc}") from exc
    return validate_registry(payload)


def checkout_execution_selection(root: Path, suite: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the registry-bound exact-checkout files and nodes for one suite."""

    if suite not in DEFAULT_CI_SUITES:
        raise GuardExecutionError(f"guard suite is not a default CI partition: {suite!r}")
    selection = _checkout_execution_selection(suite)
    if selection is None:
        return (), ()
    return selection.files, selection.nodes


def active_guard_specs(
    root: Path,
    suite: str,
    *,
    platform: str | None = None,
    execution_root: str = "exported-commit",
) -> tuple[GuardSpec, ...]:
    """Return exact active guards applicable to one suite and platform."""

    if suite not in DEFAULT_CI_SUITES:
        raise GuardExecutionError(f"guard suite is not a default CI partition: {suite!r}")
    selected_platform = current_guard_platform() if platform is None else platform
    if selected_platform not in GUARD_PLATFORMS:
        raise GuardExecutionError(f"guard platform is invalid: {selected_platform!r}")
    if execution_root not in {"exported-commit", "git-index"}:
        raise GuardExecutionError(f"guard execution root is invalid: {execution_root!r}")
    payload = _registry(root)
    assignments: list[GuardSpec] = []
    for record in payload["records"]:
        assignments.extend(
            GuardSpec(
                node=guard["node"],
                ci_partition=guard["ci_partition"],
                platform=guard.get("platform"),
            )
            for guard in record["guards"]
        )
    assignments.extend(
        GuardSpec(
            node=pair["guard"],
            ci_partition=pair["ci_partition"],
            platform=pair.get("platform"),
        )
        for pair in payload["false_green_pairs"]
    )
    mismatches = []
    for spec in assignments:
        actual = suite_for_node(spec.node)
        if spec.ci_partition != actual:
            mismatches.append((spec.node, spec.ci_partition, actual))
    if mismatches:
        raise GuardExecutionError(f"registry guard partition mismatch: {sorted(mismatches)}")

    active = [
        GuardSpec(guard["node"], guard["ci_partition"], guard.get("platform"))
        for record in payload["records"]
        if record["status"] in ACTIVE_GUARD_STATUSES
        for guard in record["guards"]
        if guard["ci_partition"] == suite and guard.get("platform") in {None, selected_platform}
    ]
    active.extend(
        GuardSpec(pair["guard"], pair["ci_partition"], pair.get("platform"))
        for pair in payload["false_green_pairs"]
        if pair["status"] in ACTIVE_GUARD_STATUSES
        and pair["ci_partition"] == suite
        and pair.get("platform") in {None, selected_platform}
    )
    _, git_index_nodes = checkout_execution_selection(root, suite)
    if execution_root == "git-index":
        active = [spec for spec in active if spec.node in git_index_nodes]
    else:
        active = [spec for spec in active if spec.node not in git_index_nodes]
    by_node: dict[str, GuardSpec] = {}
    for spec in active:
        previous = by_node.get(spec.node)
        if previous is not None and previous != spec:
            raise GuardExecutionError(f"guard has conflicting runtime/pair platform declarations: {spec.node}")
        by_node[spec.node] = spec
    return tuple(sorted(by_node.values(), key=lambda spec: spec.node))


def active_guard_nodes(
    root: Path,
    suite: str,
    *,
    platform: str | None = None,
) -> tuple[str, ...]:
    """Return sorted, deduplicated active nodes for one suite and platform."""

    return tuple(
        spec.node
        for spec in active_guard_specs(
            root,
            suite,
            platform=platform,
        )
    )


def canonical_receipt(payload: dict[str, Any]) -> str:
    """Return a canonical, self-digesting JSON receipt."""

    payload_raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    envelope = {
        "payload": payload,
        "sha256": f"sha256:{hashlib.sha256(payload_raw).hexdigest()}",
    }
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def empty_guard_receipt(suite: str, *, platform: str | None = None) -> str:
    """Return the deterministic receipt for a suite with no active guards."""

    if suite not in DEFAULT_CI_SUITES:
        raise GuardExecutionError(f"guard suite is not a default CI partition: {suite!r}")
    selected_platform = current_guard_platform() if platform is None else platform
    if selected_platform not in GUARD_PLATFORMS:
        raise GuardExecutionError(f"guard platform is invalid: {selected_platform!r}")
    return canonical_receipt(
        {
            "concrete_nodes": [],
            "deselected_nodes": [],
            "expected_guards": [],
            "expected_guard_platforms": {},
            "platform": selected_platform,
            "result": "passed",
            "schema_version": 3,
            "suite": suite,
            "violations": [],
            "warnings": [],
        }
    )


def _normalized_nodeid(nodeid: str) -> str:
    return nodeid.replace(chr(92), "/")


def _matches(guard: str, concrete: str) -> bool:
    if concrete == guard:
        return True
    return "[" not in guard.rsplit("::", 1)[-1] and concrete.startswith(f"{guard}[")


def _normalized_marker_details(
    item: pytest.Item,
    *,
    platform_scope: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    details: list[dict[str, Any]] = []
    violations: list[str] = []
    markers = list(item.iter_markers())
    forbidden = sorted({marker.name for marker in markers} & FORBIDDEN_GUARD_MARKERS)
    if forbidden:
        violations.append(f"forbidden conditional markers {forbidden!r}")

    for marker in (item for item in markers if item.name == "filterwarnings"):
        filters = list(marker.args)
        if (
            marker.kwargs
            or not filters
            or any(not isinstance(value, str) or value.split(":", 1)[0].strip() != "error" for value in filters)
        ):
            violations.append("filterwarnings must contain only positional error-action filters")
            continue
        details.append({"filters": filters, "name": "filterwarnings"})

    skipif_markers = [marker for marker in markers if marker.name == "skipif"]
    if platform_scope is None:
        if skipif_markers:
            violations.append("skipif requires an exact platform-scoped registry guard")
    elif len(skipif_markers) != 1:
        violations.append("platform-scoped guard must have exactly one skipif marker")
    else:
        marker = skipif_markers[0]
        reason = marker.kwargs.get("reason")
        if (
            len(marker.args) != 1
            or marker.args[0] is not False
            or set(marker.kwargs) != {"reason"}
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            violations.append("platform skipif must be false on its target and have one nonempty reason")
        else:
            details.append(
                {
                    "condition": False,
                    "name": "skipif",
                    "reason": reason,
                    "target_platform": platform_scope,
                }
            )

    details.sort(key=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")))
    return details, violations


class _GuardState:
    def __init__(
        self,
        *,
        suite: str,
        expected: tuple[GuardSpec, ...],
        platform: str,
        collect_only: bool,
    ) -> None:
        self.suite = suite
        self.platform = platform
        self.expected_specs = expected
        self.expected = tuple(spec.node for spec in expected)
        self.platform_by_guard = {spec.node: spec.platform for spec in expected}
        self.collect_only = collect_only
        self.guard_to_concrete: dict[str, set[str]] = {guard: set() for guard in self.expected}
        self.concrete_to_guards: dict[str, set[str]] = defaultdict(set)
        self.markers: dict[str, list[dict[str, Any]]] = {}
        self.marker_violations: dict[str, list[str]] = defaultdict(list)
        self.phases: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        self.was_xfail: set[str] = set()
        self.deselected: set[str] = set()
        self.unexpected: set[str] = set()
        self.warnings: list[dict[str, str]] = []
        self.receipt: str | None = None

    def bind_item(self, item: pytest.Item) -> None:
        nodeid = _normalized_nodeid(item.nodeid)
        matches = tuple(guard for guard in self.expected if _matches(guard, nodeid))
        if not matches:
            self.unexpected.add(nodeid)
            return
        for guard in matches:
            self.guard_to_concrete[guard].add(nodeid)
            self.concrete_to_guards[nodeid].add(guard)
        platforms = {self.platform_by_guard[guard] for guard in matches}
        if len(platforms) != 1:
            self.marker_violations[nodeid].append("matched guards have conflicting platform scopes")
            return
        details, violations = _normalized_marker_details(
            item,
            platform_scope=platforms.pop(),
        )
        self.markers[nodeid] = details
        self.marker_violations[nodeid].extend(violations)

    def violations(self) -> list[str]:
        violations: list[str] = []
        if self.collect_only:
            violations.append("collection-only execution cannot prove an active guard")
        if not self.expected:
            violations.append("strict guard execution has no active guards")
        for guard, concrete in sorted(self.guard_to_concrete.items()):
            if not concrete:
                violations.append(f"guard was not selected: {guard}")
        for nodeid in sorted(self.deselected):
            violations.append(f"guard was deselected: {nodeid}")
        for nodeid in sorted(self.unexpected):
            violations.append(f"unexpected or wrong-suite test was selected: {nodeid}")
        for nodeid, reasons in sorted(self.marker_violations.items()):
            violations.extend(f"guard marker policy violation: {reason}: {nodeid}" for reason in reasons)
        for nodeid in sorted(self.concrete_to_guards):
            outcomes = self.phases.get(nodeid, {})
            for phase in _PHASES:
                reports = outcomes.get(phase, [])
                if reports != ["passed"]:
                    rendered = reports if reports else ["missing"]
                    violations.append(f"guard phase reports are not exactly one pass: {nodeid} {phase}={rendered!r}")
            if nodeid in self.was_xfail:
                violations.append(f"guard produced an xfail/xpass outcome: {nodeid}")
        for warning in self.warnings:
            violations.append(
                f"guard execution emitted warning: {warning['when']}:{warning['nodeid']}:{warning['category']}"
            )
        return sorted(set(violations))

    def build_receipt(self) -> str:
        violations = self.violations()
        concrete = [
            {
                "guards": sorted(self.concrete_to_guards[nodeid]),
                "markers": self.markers.get(nodeid, []),
                "nodeid": nodeid,
                "phases": {phase: list(self.phases.get(nodeid, {}).get(phase, [])) for phase in _PHASES},
                "was_xfail": nodeid in self.was_xfail,
            }
            for nodeid in sorted(self.concrete_to_guards)
        ]
        return canonical_receipt(
            {
                "concrete_nodes": concrete,
                "deselected_nodes": sorted(self.deselected),
                "expected_guards": list(self.expected),
                "expected_guard_platforms": self.platform_by_guard,
                "platform": self.platform,
                "result": "failed" if violations else "passed",
                "schema_version": 3,
                "suite": self.suite,
                "violations": violations,
                "warnings": sorted(
                    self.warnings,
                    key=lambda item: (item["when"], item["nodeid"], item["category"]),
                ),
            }
        )


_ACTIVE_STATE: _GuardState | None = None


def _state(config: pytest.Config) -> _GuardState:
    state = getattr(config, _STATE_ATTRIBUTE, None)
    if not isinstance(state, _GuardState):
        raise GuardExecutionError("strict guard execution state is not configured")
    return state


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("cryodaq-active-guards")
    group.addoption(
        "--cryodaq-active-guard-suite",
        action="store",
        choices=DEFAULT_CI_SUITES,
        dest="cryodaq_active_guard_suite",
        help="Require executed-pass receipts for active guards in one default CI suite.",
    )
    group.addoption(
        "--cryodaq-active-guard-execution-root",
        action="store",
        choices=("exported-commit", "git-index"),
        default="exported-commit",
        dest="cryodaq_active_guard_execution_root",
        help="Bind strict guard execution to its declared filesystem authority.",
    )


def pytest_configure(config: pytest.Config) -> None:
    global _ACTIVE_STATE
    config.addinivalue_line("markers", "timeout(...): forbidden on active governance guards")
    suite = config.getoption("cryodaq_active_guard_suite")
    if suite is None:
        raise pytest.UsageError("--cryodaq-active-guard-suite is required")
    root = Path(config.rootpath).resolve(strict=True)
    platform = current_guard_platform()
    execution_root = config.getoption("cryodaq_active_guard_execution_root")
    state = _GuardState(
        suite=suite,
        expected=active_guard_specs(root, suite, platform=platform, execution_root=execution_root),
        platform=platform,
        collect_only=bool(config.option.collectonly),
    )
    setattr(config, _STATE_ATTRIBUTE, state)
    _ACTIVE_STATE = state


def pytest_deselected(items: list[pytest.Item]) -> None:
    if _ACTIVE_STATE is None:
        return
    for item in items:
        nodeid = _normalized_nodeid(item.nodeid)
        if any(_matches(guard, nodeid) for guard in _ACTIVE_STATE.expected):
            _ACTIVE_STATE.deselected.add(nodeid)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_collection_modifyitems(
    session: pytest.Session,
    config: pytest.Config,
    items: list[pytest.Item],
) -> Any:
    del session, config
    if _ACTIVE_STATE is None:
        yield
        return
    before = {
        _normalized_nodeid(item.nodeid)
        for item in items
        if any(_matches(guard, _normalized_nodeid(item.nodeid)) for guard in _ACTIVE_STATE.expected)
    }
    yield
    after = {_normalized_nodeid(item.nodeid) for item in items}
    _ACTIVE_STATE.deselected.update(before - after)


def pytest_collection_finish(session: pytest.Session) -> None:
    state = _state(session.config)
    for item in session.items:
        state.bind_item(item)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if _ACTIVE_STATE is None:
        return
    nodeid = _normalized_nodeid(report.nodeid)
    if nodeid not in _ACTIVE_STATE.concrete_to_guards:
        return
    _ACTIVE_STATE.phases[nodeid][report.when].append(report.outcome)
    if hasattr(report, "wasxfail"):
        _ACTIVE_STATE.was_xfail.add(nodeid)


def pytest_warning_recorded(
    warning_message: Any,
    when: str,
    nodeid: str,
    location: tuple[str, int, str] | None,
) -> None:
    del location
    if _ACTIVE_STATE is None:
        return
    normalized = _normalized_nodeid(nodeid or "")
    if not any(_matches(guard, normalized) for guard in _ACTIVE_STATE.expected):
        return
    category = getattr(warning_message, "category", Warning)
    _ACTIVE_STATE.warnings.append(
        {
            "category": getattr(category, "__name__", str(category)),
            "nodeid": normalized,
            "when": str(when),
        }
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int | pytest.ExitCode) -> None:
    state = _state(session.config)
    state.receipt = state.build_receipt()
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    line = f"{RECEIPT_PREFIX}{state.receipt}"
    if reporter is None:
        print(line, flush=True)
    else:
        reporter.write_line(line)
    envelope = json.loads(state.receipt)
    if envelope["payload"]["result"] == "failed" and int(exitstatus) == int(pytest.ExitCode.OK):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_unconfigure(config: pytest.Config) -> None:
    global _ACTIVE_STATE
    if _ACTIVE_STATE is getattr(config, _STATE_ATTRIBUTE, None):
        _ACTIVE_STATE = None
