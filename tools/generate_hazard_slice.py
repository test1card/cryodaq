"""Generate the bounded CryoDAQ hazard-review universe."""

from __future__ import annotations

import argparse
import ast
import subprocess
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath

DEFAULT_BASE = "f5d6434d20dffae62c9f03fbc12f68b03f48351b"
OUTPUT = "docs/HAZARD_SLICE.md"
SELF = "tools/generate_hazard_slice.py"

HAZARD_SYMBOLS = (
    "DEVICE_REPORTED_OFF",
    "PHYSICAL_STATE_UNKNOWN",
    "SourceOffEvidence",
    "SourceOffResult",
    "VerifiedOffSource",
    "_active_sources",
    "_fault",
    "_has_fresh_keithley_data",
    "emergency_off",
    "start_source",
    "stop_source",
    "verified_off",
)

DATA_FLOW_PREFIXES = (
    "src/cryodaq/channels/",
    "src/cryodaq/drivers/",
)
DATA_FLOW_PATHS = {
    "config/alarms_v3.yaml",
    "config/channels.yaml",
    "config/channel_descriptors.local.yaml.example",
    "config/channel_descriptors.yaml",
    "config/cooldown.yaml",
    "config/housekeeping.yaml",
    "config/instruments.local.yaml.example",
    "config/instruments.yaml",
    "config/interlocks.yaml",
    "config/physical_alarms.yaml",
    "config/safety.yaml",
    "src/cryodaq/core/alarm_config.py",
    "src/cryodaq/core/alarm_providers.py",
    "src/cryodaq/core/alarm_v2.py",
    "src/cryodaq/core/broker.py",
    "src/cryodaq/core/channel_manager.py",
    "src/cryodaq/core/channel_state.py",
    "src/cryodaq/core/descriptor_transport.py",
    "src/cryodaq/core/disk_monitor.py",
    "src/cryodaq/core/event_bus.py",
    "src/cryodaq/core/event_logger.py",
    "src/cryodaq/core/housekeeping.py",
    "src/cryodaq/core/interlock.py",
    "src/cryodaq/core/physical_alarms_config.py",
    "src/cryodaq/core/physical_policy.py",
    "src/cryodaq/core/rate_estimator.py",
    "src/cryodaq/core/safety_broker.py",
    "src/cryodaq/core/safety_manager.py",
    "src/cryodaq/core/safety_pattern_liveness.py",
    "src/cryodaq/core/scheduler.py",
    "src/cryodaq/core/smu_channel.py",
    "src/cryodaq/engine.py",
    "src/cryodaq/analytics/cooldown_predictor.py",
    "src/cryodaq/analytics/cooldown_service.py",
    "src/cryodaq/engine_wiring/runtime_tasks.py",
    "src/cryodaq/engine_wiring/supervision.py",
    "src/cryodaq/storage/channel_descriptors.py",
    "src/cryodaq/storage/broker_replay.py",
    "src/cryodaq/storage/descriptor_archive.py",
    "src/cryodaq/storage/persistence_spool.py",
    "src/cryodaq/storage/replay.py",
    "src/cryodaq/storage/sqlite_writer.py",
    "src/cryodaq/replay_engine/legacy_channel_maps.py",
    "src/cryodaq/replay_engine/sources.py",
}

IPC_PATHS = {
    "src/cryodaq/core/command_authority.py",
    "src/cryodaq/core/command_reply_contract.py",
    "src/cryodaq/core/descriptor_transport.py",
    "src/cryodaq/core/safe_command_ipc.py",
    "src/cryodaq/core/zmq_bridge.py",
    "src/cryodaq/core/zmq_endpoints.py",
    "src/cryodaq/core/zmq_subprocess.py",
    "src/cryodaq/engine.py",
    "src/cryodaq/engine_wiring/operator_snapshot_publisher.py",
    "src/cryodaq/gui/state/operator_snapshot_ingress.py",
    "src/cryodaq/gui/zmq_client.py",
    "src/cryodaq/launcher.py",
    "src/cryodaq/operator_snapshot_transport.py",
    "src/cryodaq/replay_engine/server.py",
}

CALLBACK_REGISTRY_PATHS = {
    "src/cryodaq/core/broker.py",
    "src/cryodaq/core/disk_monitor.py",
    "src/cryodaq/core/event_bus.py",
    "src/cryodaq/core/event_logger.py",
    "src/cryodaq/core/interlock.py",
    "src/cryodaq/core/safety_broker.py",
    "src/cryodaq/core/safety_manager.py",
    "src/cryodaq/drivers/registry.py",
    "src/cryodaq/engine.py",
    "src/cryodaq/engine_wiring/runtime_tasks.py",
    "src/cryodaq/engine_wiring/supervision.py",
    "src/cryodaq/storage/sqlite_writer.py",
}

OFF_TRUTH_PATHS = {
    "src/cryodaq/drivers/contracts.py",
    "src/cryodaq/engine.py",
    "src/cryodaq/engine_wiring/operator_safety_snapshot.py",
    "src/cryodaq/engine_wiring/operator_snapshot_authorities.py",
    "src/cryodaq/engine_wiring/operator_snapshot_composer.py",
    "src/cryodaq/engine_wiring/operator_snapshot_live_authorities.py",
    "src/cryodaq/engine_wiring/operator_snapshot_production.py",
    "src/cryodaq/engine_wiring/operator_snapshot_publisher.py",
    "src/cryodaq/gui/shell/bottom_status_bar.py",
    "src/cryodaq/gui/shell/main_window_v2.py",
    "src/cryodaq/gui/shell/overlays/keithley_panel.py",
    "src/cryodaq/gui/shell/top_watch_bar.py",
    "src/cryodaq/gui/shell/views/operator_display.py",
    "src/cryodaq/gui/state/operator_snapshot_ingress.py",
    "src/cryodaq/gui/state/operator_view_models.py",
    "src/cryodaq/launcher.py",
    "src/cryodaq/operator_snapshot.py",
    "src/cryodaq/operator_snapshot_transport.py",
    "src/cryodaq/replay_engine/operator_snapshot_session.py",
    "src/cryodaq/storage/operator_snapshot_revision.py",
}

LIFECYCLE_PATHS = {
    "create_shortcut.py",
    "start.bat",
    "start.sh",
    "start_mock.bat",
    "start_mock.sh",
    "src/cryodaq/__main__.py",
    "src/cryodaq/_frozen_main.py",
    "src/cryodaq/core/shutdown_settlement.py",
    "src/cryodaq/core/zmq_bridge.py",
    "src/cryodaq/core/zmq_endpoints.py",
    "src/cryodaq/core/zmq_subprocess.py",
    "src/cryodaq/engine.py",
    "src/cryodaq/gui/app.py",
    "src/cryodaq/instance_lock.py",
    "src/cryodaq/launcher.py",
    "tsp/cryodaq_wdog.lua",
}

FROZEN_PREFIXES = ("build_scripts/",)
FROZEN_PATHS = {
    "pyproject.toml",
    "requirements-lock.txt",
    "src/cryodaq/_frozen_main.py",
    "src/cryodaq/drivers/registry.py",
    "src/cryodaq/paths.py",
    "tests/test_frozen_entry.py",
    "tests/test_paths_frozen.py",
    "tests/test_pyinstaller_spec.py",
    "tests/test_windows_onedir_smoke_contract.py",
    "tsp/cryodaq_wdog.lua",
}

GOVERNANCE_DOCS = {
    "AGENTS.md",
    "docs/CLAIM_CORRECTIONS.md",
    "docs/DECISIONS.md",
    "docs/MONTANA_IMPLEMENTATION_AGENT_SPEC.md",
    "docs/OPEN_CELLS.md",
    "docs/ORCHESTRATION.md",
}
GUARD_NAME_MARKERS = ("conformance", "guard", "seal", "sweep")
GUARD_CONTENT_MARKERS = (
    "ast.parse(",
    "ast.walk(",
    "git ls-files",
    "guard_coverage",
    "KNOWN_PRODUCTION_VIOLATIONS",
    "_REGEX_METHODS",
)
GOVERNANCE_TOOL_MARKERS = (
    "agent_context",
    "candidate",
    "ci_",
    "governance",
    "guard",
    "red_reproduction",
    "standing_lane",
)

EDGE_ORDER = (
    "hazard-symbol seed",
    "import consumer",
    "data-flow/config/identity input",
    "IPC/message-bus path",
    "callback/registry path",
    "OFF evidence/operator truth",
    "launcher/shutdown/process-death path",
    "dynamic/frozen-build path",
    "changed guard/governance evidence",
    "manifest governance",
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _module_name(path: str) -> str | None:
    pure = PurePosixPath(path)
    if pure.suffix != ".py":
        return None
    if path.startswith("src/"):
        parts = list(pure.with_suffix("").parts[1:])
    elif path.startswith(("tests/", "tools/", "scripts/", "build_scripts/")):
        parts = list(pure.with_suffix("").parts)
    else:
        return None
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolved_module(candidate: str, modules: dict[str, str]) -> str | None:
    parts = candidate.split(".")
    while parts:
        name = ".".join(parts)
        if name in modules:
            return modules[name]
        parts.pop()
    return None


def _imports(path: str, text: str, modules: dict[str, str]) -> set[str]:
    tree = ast.parse(text, filename=path)
    current = _module_name(path) or ""
    package = current if path.endswith("/__init__.py") else current.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        candidates: list[str] = []
        if isinstance(node, ast.Import):
            candidates.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parent = package.split(".") if package else []
                keep = max(0, len(parent) - node.level + 1)
                base = ".".join(parent[:keep])
                imported = ".".join(part for part in (base, node.module or "") if part)
            else:
                imported = node.module or ""
            if imported:
                candidates.append(imported)
                candidates.extend(f"{imported}.{alias.name}" for alias in node.names if alias.name != "*")
        for candidate in candidates:
            resolved = _resolved_module(candidate, modules)
            if resolved and resolved != path:
                found.add(resolved)
    return found


def _identifiers(path: str, text: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(text, filename=path)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def _is_guard_test(path: str, text: str) -> bool:
    if not path.startswith("tests/"):
        return False
    if path.startswith(("tests/governance/", "tests/docs/", "tests/driver_conformance/")):
        return True
    name = PurePosixPath(path).name.lower()
    return any(marker in name for marker in GUARD_NAME_MARKERS) or any(
        marker in text for marker in GUARD_CONTENT_MARKERS
    )


def _is_governance_surface(path: str) -> bool:
    if path.startswith((".github/workflows/", "governance/")) or path in GOVERNANCE_DOCS:
        return True
    return path.startswith("tools/") and any(marker in PurePosixPath(path).name for marker in GOVERNANCE_TOOL_MARKERS)


def _render(base: str, target: str, entries: dict[str, set[str]], changed: set[str]) -> str:
    lines = [
        "# Hazard review slice",
        "",
        "This file declares the bounded review universe for the final CryoDAQ hazard round.",
        "Changed entries are reviewed exhaustively; unchanged entries are context needed to",
        "trace their data, control, evidence, and operator-truth paths. A path absent from this",
        "manifest is outside that round by declaration, not proven irrelevant to every possible",
        "future hazard analysis.",
        "",
        "## Frozen comparison",
        "",
        f"- Base: `{base}`",
        f"- Target: `{target}`",
        f"- Generator: `{SELF}`",
        "- Changed means present at the target and selected by",
        "  `git diff --name-only --diff-filter=ACMR <base>...<target>`, plus the two",
        "  manifest-lane files while they are untracked during their first generation.",
        "",
        "## Method",
        "",
        "The generator parses local Python imports and starts from source modules containing",
        "the declared actuation/OFF-evidence symbols. It follows the transitive consumer",
        "direction. It then adds bounded semantic edges that imports cannot represent:",
        "",
        "1. **Data flow/config/identity input** — driver readings and transports, descriptor",
        "   binding, channel maps, safety/alarm/interlock configuration, broker/scheduler",
        "   publication, persistence feedback, and the clocks used by safety predicates.",
        "2. **IPC/message bus** — GUI and launcher command producers, ZMQ request/reply and",
        "   publish/subscribe bridges, descriptor and operator-snapshot envelopes, and replay",
        "   command handling.",
        "3. **Callbacks/registries** — broker overflow, persistence-failure, supervision and",
        "   interlock callbacks, plus driver/runtime-binding registration.",
        "4. **OFF evidence/operator truth** — typed OFF results through SafetyManager, shutdown",
        "   receipts, operator snapshots, replay, persistence, and visible operator state.",
        "5. **Launcher/shutdown/process death** — source and frozen entry points, signal/process",
        "   ownership, shutdown settlement, instance locks, and launcher receipts.",
        "6. **Dynamic/frozen build** — the PyInstaller spec and hooks, entry-point metadata,",
        "   driver registry, frozen path resolution, and ONEDIR contract tests.",
        "7. **Changed guard/governance evidence** — changed governance/docs test trees, changed",
        "   static guard/seal/contract/conformance tests, their CI/governance runners and",
        "   workflows, and the claim-correction/governing documents that define what green",
        "   evidence means.",
        "",
        "These are path-semantic edges, deliberately not the full dependency closure. Generic",
        "logging, formatting, and unrelated presentation dependencies are not added merely",
        "because a selected module imports them.",
        "",
        "## Blind spots and required human work",
        "",
        "- The AST graph sees ordinary Python imports only. Dynamic imports, reflection, native",
        "  extensions, subprocess protocols, shell indirection, and dependency injection are",
        "  not inferred. A reviewer must inspect the frozen-build spec, entry points, registries,",
        "  subprocess launch arguments, and runtime callback registration.",
        "- The semantic edge sets are curated from the production wiring at the target. They are",
        "  mechanically enumerated once declared, but declaration is a human judgement. A",
        "  reviewer must compare every changed telemetry producer, command producer, topic,",
        "  callback registration, descriptor/config loader, and shutdown owner against these",
        "  sets; renamed or newly introduced paths can otherwise escape.",
        "- This is not interprocedural taint analysis. It does not prove which tuple field,",
        "  timestamp, status, descriptor, or receipt value reaches a predicate. The adversarial",
        "  round must trace actual values from readings and commands to energizing writes, and",
        "  from OFF outcomes to persisted receipts and operator truth.",
        "- Static guard detection is bounded by governance/docs directories, filename markers,",
        "  and known AST/repository-scan markers. A novel guard shape needs human classification.",
        "- The three-dot Git comparison uses the merge base. It reports PR change membership,",
        "  not authorship, review quality, or whether a changed line is behaviorally reachable.",
        "- The manifest cannot close physical hardware, target-Windows, frozen-artifact,",
        "  independent final-element, or laboratory acceptance gates.",
        "",
        "## Re-run",
        "",
        "Check out the frozen target so it is `HEAD`, then run:",
        "",
        "```powershell",
        f'$env:PYTHONPATH = "$PWD\\src"; python {SELF} --base {base} --target <target-sha>',
        f'$env:PYTHONPATH = "$PWD\\src"; python {SELF} --base {base} --target <target-sha> --check',
        "```",
        "",
        "The generator refuses a target other than the checked-out `HEAD`, so the AST and",
        "non-Python path inventory cannot silently describe different bytes.",
        "",
        "## Declared entries",
        "",
        "| Path | Inclusion edge(s) | Changed by PR? |",
        "| --- | --- | --- |",
    ]
    order = {reason: index for index, reason in enumerate(EDGE_ORDER)}
    for path in sorted(entries):
        reasons = sorted(entries[path], key=lambda reason: order[reason])
        lines.append(f"| `{path}` | {'; '.join(reasons)} | {'yes' if path in changed else 'no'} |")
    lines.append("")
    return "\n".join(lines)


def generate(root: Path, base_ref: str, target_ref: str) -> str:
    base = _git(root, "rev-parse", f"{base_ref}^{{commit}}")
    target = _git(root, "rev-parse", f"{target_ref}^{{commit}}")
    head = _git(root, "rev-parse", "HEAD")
    if target != head:
        raise SystemExit(f"target {target} is not checked-out HEAD {head}; check out the frozen target first")

    target_paths = set(_git(root, "ls-tree", "-r", "--name-only", target).splitlines())
    paths = set(target_paths)
    paths.update(path for path in (SELF, OUTPUT) if (root / path).is_file())
    changed = set(_git(root, "diff", "--name-only", "--diff-filter=ACMR", f"{base}...{target}").splitlines())
    changed.update(path for path in (SELF, OUTPUT) if path not in target_paths)

    texts: dict[str, str] = {}
    for path in paths:
        if path.endswith(".py"):
            texts[path] = (root / path).read_text(encoding="utf-8")

    modules = {name: path for path in texts if (name := _module_name(path))}
    reverse_imports: dict[str, set[str]] = defaultdict(set)
    for consumer, text in texts.items():
        for dependency in _imports(consumer, text, modules):
            reverse_imports[dependency].add(consumer)

    entries: dict[str, set[str]] = defaultdict(set)
    seeds = {
        path
        for path, text in texts.items()
        if path.startswith("src/cryodaq/") and set(HAZARD_SYMBOLS) & _identifiers(path, text)
    }
    for path in seeds:
        entries[path].add("hazard-symbol seed")

    queue = deque(seeds)
    consumers = set(seeds)
    while queue:
        for consumer in reverse_imports.get(queue.popleft(), set()):
            if consumer not in consumers:
                consumers.add(consumer)
                queue.append(consumer)
    for path in consumers - seeds:
        entries[path].add("import consumer")

    for path in paths:
        if path in DATA_FLOW_PATHS or path.startswith(DATA_FLOW_PREFIXES):
            entries[path].add("data-flow/config/identity input")
        if path in IPC_PATHS:
            entries[path].add("IPC/message-bus path")
        if path in CALLBACK_REGISTRY_PATHS:
            entries[path].add("callback/registry path")
        if path in OFF_TRUTH_PATHS:
            entries[path].add("OFF evidence/operator truth")
        if path in LIFECYCLE_PATHS:
            entries[path].add("launcher/shutdown/process-death path")
        if path in FROZEN_PATHS or path.startswith(FROZEN_PREFIXES):
            entries[path].add("dynamic/frozen-build path")
        if path in changed and (_is_governance_surface(path) or _is_guard_test(path, texts.get(path, ""))):
            entries[path].add("changed guard/governance evidence")

    entries[SELF].add("manifest governance")
    entries[OUTPUT].add("manifest governance")

    # OUTPUT is the artifact this generator writes, not a citation it must already find
    # on disk; excluding it lets the manifest bootstrap at a fresh SHA. Every other
    # selected path is still required to exist, so a dead citation still fails here.
    missing = sorted(path for path in entries if path != OUTPUT and not (root / path).is_file())
    if missing:
        raise SystemExit("selected paths do not exist:\n" + "\n".join(missing))
    return _render(base, target, entries, changed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE, help="PR base revision")
    parser.add_argument("--target", default="HEAD", help="frozen target revision (must equal HEAD)")
    parser.add_argument("--output", default=OUTPUT, help="repo-relative Markdown output")
    parser.add_argument("--check", action="store_true", help="fail if the output is not current")
    args = parser.parse_args()

    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel"))
    output = root / args.output
    rendered = generate(root, args.base, args.target)
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"{args.output} is stale; regenerate it")
        print(f"{args.output} is current")
        return 0
    output.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
