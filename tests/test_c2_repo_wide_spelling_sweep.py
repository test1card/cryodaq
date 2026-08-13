"""C2 AST heuristic for selected identity-spelling operations in production Python.

This filesystem guard inventories selected direct spelling-operation shapes in
``src/cryodaq/**/*.py`` and ``*.pyw``.  It follows direct identity fields,
selected local/iteration aliases, identity-keyed mappings, and local helpers
returning an identity.  It does not establish declaring-authority provenance,
follow general Python dataflow, or cover non-Python presentation code.
"""

from __future__ import annotations

import ast
import hashlib
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

_IDENTITY_WORDS = frozenset({"channel", "channel_id", "instrument_id", "source_key", "identifier"})
_GUI_IDENTITY_WORDS = frozenset({"ch", "ch_id", "channel_raw", "measurement", "short_id"})
_SHORT_ITERATION_IDENTITY_NAMES = frozenset({"ch", "ch_id"})
_STRING_OPERATIONS = frozenset({"startswith", "endswith"})
_REGEX_OPERATIONS = frozenset({"search", "match", "fullmatch"})
_IDENTITY_ITERABLE_METHODS = frozenset({"channels", "get_all_visible", "get_cold_channels", "get_temperature_channels"})


@dataclass(frozen=True, order=True)
class _Challenge:
    path: str
    scope: str
    reason: str
    fingerprint: str


@dataclass(frozen=True)
class _Site:
    path: str
    line: int
    scope: str
    reason: str
    shape: str

    @property
    def challenge(self) -> _Challenge:
        digest = hashlib.sha256(self.shape.encode("utf-8")).hexdigest()[:20]
        return _Challenge(self.path, self.scope, self.reason, digest)


def _root() -> Path:
    configured = os.environ.get("CRYODAQ_C2_SWEEP_ROOT")
    return Path(configured) if configured else Path(__file__).resolve().parents[1]


def _identity_name(name: str) -> bool:
    return name in _IDENTITY_WORDS or name.endswith(("_channel_id", "_instrument_id", "_source_key"))


def _literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _literal_collection(node: ast.AST) -> bool:
    return isinstance(node, (ast.Tuple, ast.List, ast.Set)) and all(_literal(item) for item in node.elts)


def _contains_string_literal(node: ast.AST) -> bool:
    return any(_literal(child) for child in ast.walk(node))


def _gui_identifier_roster(node: ast.AST) -> bool:
    targets: tuple[ast.AST, ...] = ()
    value: ast.AST | None = None
    if isinstance(node, ast.Assign):
        targets = tuple(node.targets)
        value = node.value
    elif isinstance(node, ast.AnnAssign):
        targets = (node.target,)
        value = node.value
    return (
        value is not None
        and _contains_string_literal(value)
        and any(
            isinstance(target, ast.Name)
            and target.id.upper() == target.id
            and any(token in target.id for token in ("CHANNEL", "INSTRUMENT", "SOURCE"))
            for target in targets
        )
    )


def _children_without_nested_scopes(scope: ast.AST) -> list[ast.AST]:
    nodes: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        nodes.append(node)
        for child in ast.iter_child_nodes(node):
            if child is not scope and isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef),
            ):
                continue
            visit(child)

    visit(scope)
    return nodes


def _identity_expression(node: ast.AST, aliases: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases or _identity_name(node.id)
    if isinstance(node, ast.Attribute):
        return _identity_name(node.attr)
    if isinstance(node, ast.Subscript):
        return _identity_expression(node.value, aliases)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return _identity_expression(node.func.value, aliases) or (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id == "str"
            and node.func.attr in {"split", "rsplit"}
            and any(_identity_expression(argument, aliases) for argument in node.args)
        )
    return False


def _split_identity_expression(node: ast.AST, aliases: set[str]) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"split", "rsplit"}:
        return _identity_expression(node.func.value, aliases) or any(
            _identity_expression(argument, aliases) for argument in node.args
        )
    if isinstance(node, ast.Subscript):
        return _split_identity_expression(node.value, aliases)
    return False


def _sliced_identity_expression(node: ast.AST, aliases: set[str]) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and _identity_expression(node.value, aliases)
        and not _split_identity_expression(node.value, aliases)
    )


def _assigned_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return set().union(*(_assigned_names(element) for element in node.elts))
    return set()


def _expression_key(node: ast.AST) -> str:
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def _identity_keyed_containers(tree: ast.Module) -> set[str]:
    containers: set[str] = set()
    for node in ast.walk(tree):
        targets: tuple[ast.AST, ...] = ()
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = (node.target,)
        for target in targets:
            if isinstance(target, ast.Subscript) and _identity_expression(target.slice, set()):
                containers.add(_expression_key(target.value))
    return containers


def _identity_iteration_names(
    node: ast.For | ast.AsyncFor | ast.comprehension,
    aliases: set[str],
    identity_keyed_containers: set[str],
    *,
    allow_short_name: bool = False,
) -> set[str]:
    iterator = node.iter
    if (
        isinstance(iterator, ast.Call)
        and isinstance(iterator.func, ast.Attribute)
        and iterator.func.attr == "items"
        and _expression_key(iterator.func.value) in identity_keyed_containers
        and isinstance(node.target, (ast.Tuple, ast.List))
        and node.target.elts
    ):
        return _assigned_names(node.target.elts[0])
    if (
        isinstance(iterator, ast.Call)
        and isinstance(iterator.func, ast.Attribute)
        and iterator.func.attr in _IDENTITY_ITERABLE_METHODS
    ):
        return _assigned_names(node.target)
    if _identity_expression(iterator, aliases):
        return _assigned_names(node.target)
    names = _assigned_names(node.target)
    if allow_short_name and names & _SHORT_ITERATION_IDENTITY_NAMES:
        return names
    return set()


def _returning_identity_functions(tree: ast.Module) -> set[str]:
    helpers: set[str] = set()
    for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
        aliases = {
            argument.arg
            for argument in (
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            )
            if _identity_name(argument.arg)
        }
        changed = True
        while changed:
            changed = False
            for node in _children_without_nested_scopes(function):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    value = node.value
                    if value is not None and _identity_expression(value, aliases):
                        names = (
                            _assigned_names(node.target)
                            if isinstance(node, ast.AnnAssign)
                            else set().union(*(_assigned_names(target) for target in node.targets))
                        )
                        if not names <= aliases:
                            aliases |= names
                            changed = True
        if any(
            return_.value is not None and _identity_expression(return_.value, aliases)
            for return_ in ast.walk(function)
            if isinstance(return_, ast.Return)
        ):
            helpers.add(function.name)
    return helpers


def _scope_aliases(
    scope: ast.AST,
    helpers: set[str],
    identity_keyed_containers: set[str],
    *,
    gui: bool = False,
) -> set[str]:
    aliases = (
        {
            argument.arg
            for argument in (
                *scope.args.posonlyargs,
                *scope.args.args,
                *scope.args.kwonlyargs,
            )
            if _identity_name(argument.arg)
        }
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef))
        else set()
    )
    if gui:
        aliases |= {
            node.id
            for node in _children_without_nested_scopes(scope)
            if isinstance(node, ast.Name) and node.id.lower() in _GUI_IDENTITY_WORDS
        }
    changed = True
    while changed:
        changed = False
        for node in _children_without_nested_scopes(scope):
            names: set[str] = set()
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                value = node.value
                returned_identity = (
                    isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in helpers
                )
                if _identity_expression(value, aliases) or returned_identity:
                    names = (
                        _assigned_names(node.target)
                        if isinstance(node, ast.AnnAssign)
                        else set().union(*(_assigned_names(target) for target in node.targets))
                    )
            if not names <= aliases:
                aliases |= names
                changed = True
    return aliases


def _reason(
    node: ast.AST,
    aliases: set[str],
    *,
    gui: bool = False,
    literal_bindings: set[str] = frozenset(),
) -> str | None:
    if gui and _gui_identifier_roster(node):
        return "GUI identifier literal roster"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in _STRING_OPERATIONS and _identity_expression(node.func.value, aliases):
            return f"identity spelling operation {node.func.attr}()"
        if node.func.attr in _REGEX_OPERATIONS and any(
            _identity_expression(argument, aliases) for argument in node.args
        ):
            return f"regular expression {node.func.attr}() over identity"
    if isinstance(node, ast.Compare):
        operands = (node.left, *node.comparators)
        if any(
            isinstance(operator, (ast.In, ast.NotIn)) and _identity_expression(haystack, aliases)
            for operator, haystack in zip(node.ops, node.comparators, strict=True)
        ):
            return "computed membership over identity"
        if any(_identity_expression(operand, aliases) for operand in operands) and any(
            _literal(operand) or _literal_collection(operand) for operand in operands
        ):
            if any(_sliced_identity_expression(operand, aliases) for operand in operands):
                return "identity slicing comparison"
            if any(_split_identity_expression(operand, aliases) for operand in operands):
                return "identity split-prefix comparison"
            if any(isinstance(operator, (ast.In, ast.NotIn)) for operator in node.ops):
                return "literal membership over identity"
            if any(isinstance(operator, (ast.Eq, ast.NotEq)) for operator in node.ops):
                return "bare literal equality over identity"
        if gui and any(_identity_expression(operand, aliases) for operand in operands):
            spelling_bearing = any(
                _contains_string_literal(operand) or (isinstance(operand, ast.Name) and operand.id in literal_bindings)
                for operand in operands
            )
            if spelling_bearing:
                if any(isinstance(operator, (ast.In, ast.NotIn)) for operator in node.ops):
                    return "computed membership over identity"
                return "GUI identifier-derived comparison"
    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Dict) and _identity_expression(node.slice, aliases):
            return "dict dispatch keyed on identity"
        if isinstance(node.value, (ast.Name, ast.Attribute)) and _identity_expression(node.value, aliases):
            return "identity indexing or slicing"
    if isinstance(node, ast.Match) and _identity_expression(node.subject, aliases):
        return "match dispatch keyed on identity"
    return None


def _semantic_scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    names: list[str] = []
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(current.name)
        elif isinstance(current, ast.Lambda):
            names.append("<lambda>")
    return ".".join(reversed(names)) or "<module>"


def _aliases_at_node(
    node: ast.AST,
    aliases: set[str],
    parents: dict[ast.AST, ast.AST],
    identity_keyed_containers: set[str],
) -> set[str]:
    active = set(aliases)
    allow_short_name = (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.attr in _STRING_OPERATIONS
    )
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.For, ast.AsyncFor)):
            active |= _identity_iteration_names(
                current,
                active,
                identity_keyed_containers,
                allow_short_name=allow_short_name,
            )
        elif isinstance(current, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for generator in current.generators:
                active |= _identity_iteration_names(
                    generator,
                    active,
                    identity_keyed_containers,
                    allow_short_name=allow_short_name,
                )
    return active


def _sites(root: Path) -> list[_Site]:
    source_root = root / "src" / "cryodaq"
    if not source_root.is_dir():
        raise RuntimeError(f"C2 scan root is missing: {source_root}")
    paths = sorted({*source_root.rglob("*.py"), *source_root.rglob("*.pyw")})
    if not paths:
        raise RuntimeError(f"C2 scan root contains no Python files: {source_root}")
    sites: list[_Site] = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        gui = relative.startswith("src/cryodaq/gui/")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        scopes = [
            tree,
            *(
                node
                for node in ast.walk(tree)
                if isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef),
                )
            ),
        ]
        helpers = _returning_identity_functions(tree)
        identity_keyed_containers = _identity_keyed_containers(tree)
        aliases = {
            scope: _scope_aliases(
                scope,
                helpers,
                identity_keyed_containers,
                gui=gui,
            )
            for scope in scopes
        }
        literal_bindings = {
            name
            for assignment in ast.walk(tree)
            if isinstance(assignment, (ast.Assign, ast.AnnAssign))
            and assignment.value is not None
            and _contains_string_literal(assignment.value)
            for target in ((assignment.target,) if isinstance(assignment, ast.AnnAssign) else tuple(assignment.targets))
            for name in _assigned_names(target)
        }
        for node in ast.walk(tree):
            scope = node
            while scope not in aliases:
                scope = parents[scope]
            reason = _reason(
                node,
                _aliases_at_node(
                    node,
                    aliases[scope],
                    parents,
                    identity_keyed_containers,
                ),
                gui=gui,
                literal_bindings=literal_bindings,
            )
            if reason:
                site = _Site(
                    relative,
                    node.lineno,
                    _semantic_scope(node, parents),
                    reason,
                    _expression_key(node),
                )
                sites.append(site)
    return sorted(sites, key=lambda site: (site.path, site.line, site.reason))


# Each registration has a stable review ID and an exact normalized-AST
# challenge. Source line numbers are diagnostics only and are never identity.
@dataclass(frozen=True)
class _Registration:
    registration_id: str
    challenge: _Challenge
    bucket: str
    authority: str


_REGISTRY_ROWS = (
    (
        "C2-145",
        _Challenge(
            "src/cryodaq/core/channel_manager.py",
            "ChannelManager.get_quantity",
            "computed membership over identity",
            "158f4568e2f6f782d7f8",
        ),
        "BLOCKED-ON-SCHEMA",
        "declared quantity is operator-owned in config/channels.yaml, not descriptor-derived",
    ),
    (
        # Same expression and therefore the same AST fingerprint as C2-145 above; only the scope
        # differs. The declaring authority is NAMED, which is what this registry requires before a
        # site may be called legitimate: the split produces a LOOKUP KEY into the active
        # channel-descriptor catalog that `MainWindowV2` installs via `set_descriptor_authority`,
        # and the catalog then declares the quantity and unit. Nothing here infers a ROLE from
        # spelling -- an unknown key returns None and the caller refuses to classify, which is the
        # opposite of the `startswith("Т")` behaviour OC-030 exists to remove.
        "C2-146",
        _Challenge(
            "src/cryodaq/core/channel_manager.py",
            "ChannelManager._descriptor_for",
            "computed membership over identity",
            "158f4568e2f6f782d7f8",
        ),
        "BLOCKED-ON-SCHEMA",
        "short-id lookup key into the descriptor catalog, which is itself the declaring authority",
    ),
    (
        "C2-001",
        _Challenge(
            "src/cryodaq/agents/assistant/live/context_builder.py",
            "_is_cryo_channel",
            "identity spelling operation startswith()",
            "7dc330017abd52dd056f",
        ),
        "OPEN-ROUTING-DEBT",
        "temperature role inferred from channel prefix",
    ),
    (
        "C2-002",
        _Challenge(
            "src/cryodaq/agents/assistant/live/context_builder.py",
            "_is_pressure_channel",
            "computed membership over identity",
            "b048a10e472814a0c02c",
        ),
        "OPEN-ROUTING-DEBT",
        "pressure role inferred from channel spelling",
    ),
    (
        "C2-003",
        _Challenge(
            "src/cryodaq/agents/assistant/live/context_builder.py",
            "_is_pressure_channel",
            "computed membership over identity",
            "993cf24f1730d650ad1a",
        ),
        "OPEN-ROUTING-DEBT",
        "pressure role inferred from channel spelling",
    ),
    (
        "C2-004",
        _Challenge(
            "src/cryodaq/agents/assistant/live/context_builder.py",
            "_is_pressure_channel",
            "identity spelling operation startswith()",
            "48c1f13c22ba081de038",
        ),
        "OPEN-ROUTING-DEBT",
        "pressure role inferred from channel prefix",
    ),
    (
        "C2-005",
        _Challenge(
            "src/cryodaq/agents/assistant/live/context_builder.py",
            "_is_pressure_channel",
            "identity spelling operation startswith()",
            "ffc54fb65ccf7a7965b0",
        ),
        "OPEN-ROUTING-DEBT",
        "pressure role inferred from channel prefix",
    ),
    (
        "C2-006",
        _Challenge(
            "src/cryodaq/agents/assistant/live/context_builder.py",
            "_is_pressure_channel",
            "identity spelling operation startswith()",
            "ae0fdb8fdc4f40ad8142",
        ),
        "OPEN-ROUTING-DEBT",
        "pressure role inferred from channel prefix",
    ),
    (
        "C2-007",
        _Challenge(
            "src/cryodaq/agents/assistant/live/context_builder.py",
            "_is_pressure_channel",
            "identity spelling operation startswith()",
            "b23c6acc4ab4bad98be3",
        ),
        "OPEN-ROUTING-DEBT",
        "pressure role inferred from channel prefix",
    ),
    (
        "C2-008",
        _Challenge(
            "src/cryodaq/agents/assistant/live/context_builder.py",
            "_is_pressure_channel",
            "identity spelling operation startswith()",
            "7b1e7bd9ecdb0491406f",
        ),
        "OPEN-ROUTING-DEBT",
        "pressure role inferred from channel prefix",
    ),
    (
        "C2-009",
        _Challenge(
            "src/cryodaq/agents/assistant/live/context_builder.py",
            "_is_pressure_channel",
            "identity spelling operation startswith()",
            "bf18ee80b722111a3be1",
        ),
        "OPEN-ROUTING-DEBT",
        "pressure role inferred from channel prefix",
    ),
    (
        "C2-010",
        _Challenge(
            "src/cryodaq/agents/assistant/query/adapters/broker_snapshot.py",
            "BrokerSnapshot.latest",
            "identity spelling operation startswith()",
            "fa14ad24352f3469c094",
        ),
        "OPEN-ROUTING-DEBT",
        "observational query routing infers semantics from identity spelling",
    ),
    (
        "C2-011",
        _Challenge(
            "src/cryodaq/channels/descriptors.py",
            "_validate_identifier",
            "identity indexing or slicing",
            "42dfe7d71ce4a598e00d",
        ),
        "LEGITIMATE",
        "ChannelDescriptorV1 identity grammar authority",
    ),
    (
        "C2-012",
        _Challenge(
            "src/cryodaq/channels/descriptors.py",
            "_validate_identifier",
            "identity indexing or slicing",
            "35f5461bd77a00b11fb6",
        ),
        "LEGITIMATE",
        "ChannelDescriptorV1 identity grammar authority",
    ),
    (
        "C2-013",
        _Challenge(
            "src/cryodaq/channels/descriptors.py",
            "_validate_source_key",
            "regular expression fullmatch() over identity",
            "daeb108827ceed358148",
        ),
        "LEGITIMATE",
        "ChannelDescriptorV1 source_key grammar authority",
    ),
    (
        "C2-014",
        _Challenge(
            "src/cryodaq/channels/descriptors.py",
            "_validate_source_key",
            "regular expression fullmatch() over identity",
            "6450f085a44cb4f42227",
        ),
        "LEGITIMATE",
        "ChannelDescriptorV1 source_key grammar authority",
    ),
    (
        "C2-015",
        _Challenge(
            "src/cryodaq/core/channel_manager.py",
            "ChannelManager.get_display_name",
            "computed membership over identity",
            "158f4568e2f6f782d7f8",
        ),
        "BLOCKED-ON-SCHEMA",
        "descriptor-backed display-label identity is absent",
    ),
    (
        "C2-016",
        _Challenge(
            "src/cryodaq/core/channel_manager.py",
            "ChannelManager.get_name",
            "computed membership over identity",
            "158f4568e2f6f782d7f8",
        ),
        "BLOCKED-ON-SCHEMA",
        "descriptor-backed display-label identity is absent",
    ),
    (
        "C2-017",
        _Challenge(
            "src/cryodaq/core/channel_manager.py",
            "ChannelManager.set_name",
            "computed membership over identity",
            "158f4568e2f6f782d7f8",
        ),
        "BLOCKED-ON-SCHEMA",
        "descriptor-backed display-label identity is absent",
    ),
    (
        "C2-018",
        _Challenge(
            "src/cryodaq/core/channel_manager.py",
            "ChannelManager.is_visible",
            "computed membership over identity",
            "158f4568e2f6f782d7f8",
        ),
        "BLOCKED-ON-SCHEMA",
        "descriptor-backed display-label identity is absent",
    ),
    (
        "C2-019",
        _Challenge(
            "src/cryodaq/core/channel_manager.py",
            "ChannelManager.set_visible",
            "computed membership over identity",
            "158f4568e2f6f782d7f8",
        ),
        "BLOCKED-ON-SCHEMA",
        "descriptor-backed display-label identity is absent",
    ),
    (
        "C2-020",
        _Challenge(
            "src/cryodaq/core/channel_manager.py",
            "ChannelManager.get_group",
            "computed membership over identity",
            "158f4568e2f6f782d7f8",
        ),
        "BLOCKED-ON-SCHEMA",
        "descriptor-backed display-label identity is absent",
    ),
    (
        "C2-021",
        _Challenge(
            "src/cryodaq/core/channel_manager.py",
            "ChannelManager.get_thermal_zone",
            "computed membership over identity",
            "158f4568e2f6f782d7f8",
        ),
        "BLOCKED-ON-SCHEMA",
        "descriptor-backed display-label identity is absent",
    ),
    (
        "C2-022",
        _Challenge(
            "src/cryodaq/core/channel_manager.py",
            "ChannelManager.get_alarm_band",
            "computed membership over identity",
            "158f4568e2f6f782d7f8",
        ),
        "BLOCKED-ON-SCHEMA",
        "descriptor-backed display-label identity is absent",
    ),
    (
        "C2-023",
        _Challenge(
            "src/cryodaq/core/channel_state.py",
            "ChannelStateTracker.update",
            "computed membership over identity",
            "2480667919e399cb464a",
        ),
        "BLOCKED-ON-SCHEMA",
        "descriptor-backed display-label identity is absent",
    ),
    (
        "C2-024",
        _Challenge(
            "src/cryodaq/core/housekeeping.py",
            "AdaptiveThrottle.observe_runtime_signal",
            "bare literal equality over identity",
            "dc682f7b48d1584cb7c1",
        ),
        "LEGITIMATE",
        "engine analytics protocol declares analytics/alarm_count",
    ),
    (
        "C2-025",
        _Challenge(
            "src/cryodaq/core/housekeeping.py",
            "AdaptiveThrottle.observe_runtime_signal",
            "identity spelling operation startswith()",
            "ffdf99aa4b1402a669d1",
        ),
        "OPEN-ROUTING-DEBT",
        "Keithley transition inferred from analytics channel prefix",
    ),
    (
        "C2-026",
        _Challenge(
            "src/cryodaq/core/housekeeping.py",
            "AdaptiveThrottle.observe_runtime_signal",
            "bare literal equality over identity",
            "411f3d38a3c641118391",
        ),
        "LEGITIMATE",
        "engine analytics protocol declares analytics/safety_state",
    ),
    (
        "C2-027",
        _Challenge(
            "src/cryodaq/core/housekeeping.py",
            "AdaptiveThrottle._matches_any",
            "regular expression search() over identity",
            "666cf2113275cc3bc224",
        ),
        "BLOCKED-ON-SCHEMA",
        "archive retention policy accepts channel regexes instead of descriptor selectors",
    ),
    (
        "C2-029",
        _Challenge(
            "src/cryodaq/core/rate_estimator.py",
            "RateEstimator.push",
            "computed membership over identity",
            "3428e9ddc76849cb2063",
        ),
        "BLOCKED-ON-SCHEMA",
        "rate grouping lacks verified descriptor selector",
    ),
    (
        "C2-031",
        _Challenge(
            "src/cryodaq/core/safety_manager.py",
            "SafetyManager._settle_latched_fault",
            "literal membership over identity",
            "8be126acdac11728b7d0",
        ),
        "BLOCKED-ON-SCHEMA",
        "safety configuration lacks verified descriptor selector",
    ),
    (
        "C2-035",
        _Challenge(
            "src/cryodaq/core/safety_manager.py",
            "SafetyManager._run_checks",
            "regular expression match() over identity",
            "c0c1b947225dcf4b8328",
        ),
        "LEGITIMATE",
        "mock-mode compatibility only; production rate selection requires descriptor bindings",
    ),
    (
        "C2-038",
        _Challenge(
            "src/cryodaq/core/safety_pattern_liveness.py",
            "_resolve_critical_input_bindings",
            "computed membership over identity",
            "c6da8c2a80c71fce6a67",
        ),
        "LEGITIMATE",
        "safety.yaml critical_channels declares exact canonical descriptor identities",
    ),
    (
        "C2-039",
        _Challenge(
            "src/cryodaq/core/safety_pattern_liveness.py",
            "_resolve_adaptive_patterns_to_raw",
            "regular expression fullmatch() over identity",
            "ae317c142cd85ba6d1e8",
        ),
        "BLOCKED-ON-SCHEMA",
        "safety liveness configuration lacks verified descriptor selector",
    ),
    (
        "C2-042",
        _Challenge(
            "src/cryodaq/core/sensor_diagnostics.py",
            "is_physical_sensor",
            "regular expression search() over identity",
            "a020d76260cf4c92bdbe",
        ),
        "BLOCKED-ON-SCHEMA",
        "legacy sensor fallback needs descriptor coverage",
    ),
    (
        "C2-043",
        _Challenge(
            "src/cryodaq/core/sensor_diagnostics.py",
            "is_physical_sensor",
            "regular expression search() over identity",
            "a020d76260cf4c92bdbe",
        ),
        "BLOCKED-ON-SCHEMA",
        "legacy sensor fallback needs descriptor coverage",
    ),
    (
        "C2-044",
        _Challenge(
            "src/cryodaq/core/sensor_diagnostics.py",
            "SensorDiagnosticsEngine._is_channel_cold",
            "computed membership over identity",
            "158f4568e2f6f782d7f8",
        ),
        "BLOCKED-ON-SCHEMA",
        "legacy sensor fallback needs descriptor coverage",
    ),
    (
        "C2-045",
        _Challenge(
            "src/cryodaq/core/sensor_diagnostics.py",
            "SensorDiagnosticsEngine._compute_correlation",
            "computed membership over identity",
            "158f4568e2f6f782d7f8",
        ),
        "BLOCKED-ON-SCHEMA",
        "legacy sensor fallback needs descriptor coverage",
    ),
    (
        "C2-046",
        _Challenge(
            "src/cryodaq/drivers/registry.py",
            "_validate_field",
            "regular expression fullmatch() over identity",
            "1fc134fdf293309b0d7b",
        ),
        "LEGITIMATE",
        "ASC driver configuration grammar authority",
    ),
    (
        "C2-048",
        _Challenge(
            "src/cryodaq/gui/dashboard/dashboard_view.py",
            "DashboardView.on_reading",
            "identity spelling operation endswith()",
            "61166f1c2c81a1e7f292",
        ),
        "OPEN-ROUTING-DEBT",
        "GUI routing infers presentation semantics from identity spelling",
    ),
    (
        "C2-049",
        _Challenge(
            "src/cryodaq/gui/dashboard/dashboard_view.py",
            "DashboardView.on_reading",
            "identity spelling operation startswith()",
            "8d2a427dc704c6606254",
        ),
        "OPEN-ROUTING-DEBT",
        "GUI routing infers presentation semantics from identity spelling",
    ),
    (
        "C2-051",
        _Challenge(
            "src/cryodaq/gui/dashboard/phase_aware_widget.py",
            "PhaseAwareWidget.on_reading",
            "identity spelling operation endswith()",
            "9fa40604c317626d30b4",
        ),
        "OPEN-ROUTING-DEBT",
        "GUI routing infers presentation semantics from identity spelling",
    ),
    (
        "C2-052",
        _Challenge(
            "src/cryodaq/gui/dashboard/phase_aware_widget.py",
            "PhaseAwareWidget.on_reading",
            "identity spelling operation endswith()",
            "9c1ea6596636cedd5ae7",
        ),
        "OPEN-ROUTING-DEBT",
        "GUI routing infers presentation semantics from identity spelling",
    ),
    (
        "C2-053",
        _Challenge(
            "src/cryodaq/gui/dashboard/phase_aware_widget.py",
            "PhaseAwareWidget.on_reading",
            "identity spelling operation endswith()",
            "61166f1c2c81a1e7f292",
        ),
        "OPEN-ROUTING-DEBT",
        "GUI routing infers presentation semantics from identity spelling",
    ),
    (
        "C2-054",
        _Challenge(
            "src/cryodaq/gui/dashboard/sensor_cell.py",
            "SensorCell.update_value",
            "identity spelling operation startswith()",
            "62dfc9872b2d6ae101c7",
        ),
        "OPEN-ROUTING-DEBT",
        "GUI routing infers presentation semantics from identity spelling",
    ),
    (
        "C2-056",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "_descriptor_is_emitted_by_instrument",
            "identity spelling operation startswith()",
            "e0e6ebd2fd167d99a3c5",
        ),
        "LEGITIMATE",
        "Etalon adapter declares length.<n> source_key grammar",
    ),
    (
        "C2-057",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "_emitted_channel_for_descriptor",
            "identity spelling operation startswith()",
            "fc51a501112d0d5afc89",
        ),
        "LEGITIMATE",
        "LakeShore adapter declares input.<n> source_key grammar",
    ),
    (
        "C2-058",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "_emitted_channel_for_descriptor",
            "identity indexing or slicing",
            "01a8f9863800d92a7895",
        ),
        "LEGITIMATE",
        "LakeShore adapter declares input.<n>.<kind> source_key grammar",
    ),
    (
        "C2-059",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "_emitted_channel_for_descriptor",
            "identity indexing or slicing",
            "60b7fcb2fe474e2e76cb",
        ),
        "LEGITIMATE",
        "LakeShore adapter declares input.<n>.<kind> source_key grammar",
    ),
    (
        "C2-060",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "_emitted_channel_for_descriptor",
            "identity slicing comparison",
            "687ad997c31285bd6ab6",
        ),
        "LEGITIMATE",
        "LakeShore adapter declares input.<n>.<kind> source_key grammar",
    ),
    (
        "C2-061",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "_emitted_channel_for_descriptor",
            "identity indexing or slicing",
            "60b7fcb2fe474e2e76cb",
        ),
        "LEGITIMATE",
        "LakeShore adapter declares input.<n>.<kind> source_key grammar",
    ),
    (
        "C2-062",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "_emitted_channel_for_descriptor",
            "identity indexing or slicing",
            "01a8f9863800d92a7895",
        ),
        "LEGITIMATE",
        "LakeShore adapter declares input.<n>.<kind> source_key grammar",
    ),
    (
        "C2-063",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "_emitted_channel_for_descriptor",
            "identity slicing comparison",
            "931b1d647f356f67b4cb",
        ),
        "LEGITIMATE",
        "LakeShore adapter declares raw_sensor source_key value",
    ),
    (
        "C2-064",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "_emitted_channel_for_descriptor",
            "identity spelling operation startswith()",
            "e0e6ebd2fd167d99a3c5",
        ),
        "LEGITIMATE",
        "Etalon adapter declares length.<n> source_key grammar",
    ),
    (
        "C2-065",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "_emitted_channel_for_descriptor",
            "literal membership over identity",
            "35e5527ecefaae0c8d0a",
        ),
        "LEGITIMATE",
        "Etalon adapter declares environment source_key values",
    ),
    (
        "C2-066",
        _Challenge(
            "src/cryodaq/gui/shell/experiment_overlay.py",
            "ExperimentOverlay.on_reading",
            "bare literal equality over identity",
            "c81502cc73a0af871976",
        ),
        "LEGITIMATE",
        "engine analytics protocol declares experiment event",
    ),
    (
        "C2-067",
        _Challenge(
            "src/cryodaq/gui/shell/main_window_v2.py",
            "MainWindowV2._dispatch_reading",
            "identity spelling operation startswith()",
            "827f14aa09678a913853",
        ),
        "OPEN-ROUTING-DEBT",
        "measurement flow inferred from namespace prefix",
    ),
    (
        "C2-068",
        _Challenge(
            "src/cryodaq/gui/shell/main_window_v2.py",
            "MainWindowV2._dispatch_reading",
            "bare literal equality over identity",
            "942e82439960963c317d",
        ),
        "LEGITIMATE",
        "engine versioned protocol declares this exact message",
    ),
    (
        "C2-069",
        _Challenge(
            "src/cryodaq/gui/shell/main_window_v2.py",
            "MainWindowV2._dispatch_reading",
            "bare literal equality over identity",
            "c81502cc73a0af871976",
        ),
        "LEGITIMATE",
        "engine versioned protocol declares this exact message",
    ),
    (
        "C2-070",
        _Challenge(
            "src/cryodaq/gui/shell/main_window_v2.py",
            "MainWindowV2._dispatch_reading",
            "literal membership over identity",
            "ea6aea2adce3c21bb353",
        ),
        "OPEN-ROUTING-DEBT",
        "generic shell assigns smua/smub semantics from spelling",
    ),
    (
        "C2-071",
        _Challenge(
            "src/cryodaq/gui/shell/main_window_v2.py",
            "MainWindowV2._dispatch_reading",
            "identity spelling operation startswith()",
            "8d2a427dc704c6606254",
        ),
        "OPEN-ROUTING-DEBT",
        "generic shell analytics routing uses namespace prefix",
    ),
    (
        "C2-072",
        _Challenge(
            "src/cryodaq/gui/shell/main_window_v2.py",
            "MainWindowV2._dispatch_reading",
            "bare literal equality over identity",
            "411f3d38a3c641118391",
        ),
        "LEGITIMATE",
        "engine versioned protocol declares this exact message",
    ),
    (
        "C2-073",
        _Challenge(
            "src/cryodaq/gui/shell/main_window_v2.py",
            "MainWindowV2._dispatch_disk_evidence",
            "bare literal equality over identity",
            "f2d503046d288f31e8a2",
        ),
        "LEGITIMATE",
        "engine versioned protocol declares this exact message",
    ),
    (
        "C2-074",
        _Challenge(
            "src/cryodaq/gui/shell/main_window_v2.py",
            "MainWindowV2._adapt_reading_to_analytics",
            "bare literal equality over identity",
            "2be993a0193e99c45e7b",
        ),
        "LEGITIMATE",
        "engine versioned protocol declares this exact message",
    ),
    (
        "C2-075",
        _Challenge(
            "src/cryodaq/gui/shell/main_window_v2.py",
            "MainWindowV2._adapt_reading_to_analytics",
            "identity spelling operation startswith()",
            "3b7c4f7105d00d1fab20",
        ),
        "OPEN-ROUTING-DEBT",
        "analytics adapter selection uses namespace prefix",
    ),
    (
        "C2-076",
        _Challenge(
            "src/cryodaq/gui/shell/main_window_v2.py",
            "MainWindowV2._adapt_reading_to_analytics",
            "bare literal equality over identity",
            "418ef26128e9a1128626",
        ),
        "LEGITIMATE",
        "engine versioned protocol declares this exact message",
    ),
    (
        "C2-077",
        _Challenge(
            "src/cryodaq/gui/shell/main_window_v2.py",
            "MainWindowV2._adapt_reading_to_analytics",
            "bare literal equality over identity",
            "0ff575fda407dc52ab33",
        ),
        "LEGITIMATE",
        "engine versioned protocol declares this exact message",
    ),
    (
        "C2-078",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/calibration_panel.py",
            "CalibrationPanel.on_reading",
            "identity spelling operation endswith()",
            "4b7b8cc4a5a1fb2ab805",
        ),
        "OPEN-ROUTING-DEBT",
        "calibration channel role inferred from suffix",
    ),
    (
        "C2-080",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/conductivity_panel.py",
            "ConductivityPanel._resolve_channel_id",
            "computed membership over identity",
            "3428e9ddc76849cb2063",
        ),
        "OPEN-ROUTING-DEBT",
        "conductivity routing inferred from channel spelling",
    ),
    (
        "C2-081",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/keithley_panel.py",
            "KeithleyPanel._command_description",
            "bare literal equality over identity",
            "9fc998c1b2d9f6290016",
        ),
        "OPEN-ROUTING-DEBT",
        "generic panel assigns SMU role from spelling",
    ),
    (
        "C2-082",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/keithley_panel.py",
            "KeithleyPanel.on_reading",
            "identity spelling operation startswith()",
            "ffdf99aa4b1402a669d1",
        ),
        "OPEN-ROUTING-DEBT",
        "Keithley analytics routing inferred from prefix",
    ),
    (
        "C2-083",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/keithley_panel.py",
            "KeithleyPanel.on_reading",
            "computed membership over identity",
            "39e2762f869937713a10",
        ),
        "OPEN-ROUTING-DEBT",
        "GUI routing infers presentation semantics from identity spelling",
    ),
    (
        "C2-084",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/keithley_panel.py",
            "KeithleyPanel.on_reading",
            "identity spelling operation endswith()",
            "452fa2e10799107eb5ec",
        ),
        "OPEN-ROUTING-DEBT",
        "Keithley channel role inferred from suffix",
    ),
    (
        "C2-085",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "is_manifest_multiline_descriptor",
            "bare literal equality over identity",
            "3fd0fcb38afd254634c1",
        ),
        "LEGITIMATE",
        "MultiLine manifest descriptor authority",
    ),
    (
        "C2-086",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "is_manifest_multiline_descriptor",
            "bare literal equality over identity",
            "d874313e0d804d89f224",
        ),
        "LEGITIMATE",
        "MultiLine manifest descriptor authority",
    ),
    (
        "C2-087",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "is_manifest_multiline_descriptor",
            "bare literal equality over identity",
            "f514818860321db90e81",
        ),
        "LEGITIMATE",
        "MultiLine manifest descriptor authority",
    ),
    (
        "C2-088",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "_is_length_channel",
            "computed membership over identity",
            "da928ef05c9f7da954f1",
        ),
        "OPEN-ROUTING-DEBT",
        "MultiLine role inferred from channel spelling",
    ),
    (
        "C2-089",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "_is_length_channel",
            "computed membership over identity",
            "975f2a4afe8767f9b674",
        ),
        "OPEN-ROUTING-DEBT",
        "MultiLine role inferred from channel spelling",
    ),
    (
        "C2-090",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "_is_env_channel",
            "computed membership over identity",
            "da928ef05c9f7da954f1",
        ),
        "OPEN-ROUTING-DEBT",
        "MultiLine role inferred from channel spelling",
    ),
    (
        "C2-091",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "_is_env_channel",
            "computed membership over identity",
            "7c8f203bd190a4c90c28",
        ),
        "OPEN-ROUTING-DEBT",
        "MultiLine role inferred from channel spelling",
    ),
    (
        "C2-092",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "_channel_number",
            "regular expression search() over identity",
            "c195828b548c3e9b241b",
        ),
        "OPEN-ROUTING-DEBT",
        "MultiLine role inferred from channel spelling",
    ),
    (
        "C2-093",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "_env_kind",
            "identity indexing or slicing",
            "4bd71a996d772104cf5c",
        ),
        "OPEN-ROUTING-DEBT",
        "MultiLine role inferred from channel spelling",
    ),
    (
        "C2-094",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "MultiLinePanel.on_descriptor_reading",
            "bare literal equality over identity",
            "b87916b5ed8ccf4b5a20",
        ),
        "LEGITIMATE",
        "MultiLine manifest descriptor authority",
    ),
    (
        "C2-095",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "MultiLinePanel.on_descriptor_reading",
            "bare literal equality over identity",
            "448815cd69e956ba8621",
        ),
        "LEGITIMATE",
        "MultiLine manifest descriptor authority",
    ),
    (
        "C2-096",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "MultiLinePanel.channel_belongs_to_panel",
            "identity spelling operation startswith()",
            "32ac1fa53b92c7a0bad2",
        ),
        "OPEN-ROUTING-DEBT",
        "MultiLine role inferred from channel spelling",
    ),
    (
        "C2-097",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "MultiLinePanel.channel_belongs_to_panel",
            "computed membership over identity",
            "da928ef05c9f7da954f1",
        ),
        "OPEN-ROUTING-DEBT",
        "MultiLine role inferred from channel spelling",
    ),
    (
        "C2-099",
        _Challenge(
            "src/cryodaq/gui/shell/top_watch_bar.py",
            "TopWatchBar.on_reading",
            "identity spelling operation endswith()",
            "10ecf5014e3df76867e2",
        ),
        "OPEN-ROUTING-DEBT",
        "watch-bar pressure routing inferred from suffix",
    ),
    (
        "C2-103",
        _Challenge(
            "src/cryodaq/notifications/periodic_report.py",
            "_natural_sort_key",
            "regular expression match() over identity",
            "ca5c413a63486e1b966f",
        ),
        "BLOCKED-ON-SCHEMA",
        "descriptor sort-rank capability is absent",
    ),
    (
        "C2-104",
        _Challenge(
            "src/cryodaq/notifications/periodic_report.py",
            "PeriodicReporter._plot_channels",
            "computed membership over identity",
            "d6737257a61843d2612e",
        ),
        "OPEN-ROUTING-DEBT",
        "periodic report grouping inferred from channel spelling",
    ),
    (
        "C2-105",
        _Challenge(
            "src/cryodaq/notifications/telegram_commands.py",
            "TelegramCommandBot._cmd_temps",
            "identity spelling operation startswith()",
            "3c6dbafb8e26ad2968c1",
        ),
        "OPEN-ROUTING-DEBT",
        "operator notification routing infers semantics from identity spelling",
    ),
    (
        "C2-106",
        _Challenge(
            "src/cryodaq/notifications/telegram_commands.py",
            "TelegramCommandBot._cmd_keithley",
            "computed membership over identity",
            "e43b01f2bf6fd0101d4f",
        ),
        "OPEN-ROUTING-DEBT",
        "operator notification routing infers semantics from identity spelling",
    ),
    # C2-107 RETIRED, deliberately. `_channel_key` and its Cyrillic-T regex were
    # removed from periodic_renderer.py by c9b02270, which made report ordering
    # follow the authority-supplied order rather than the spelling. The row is
    # retired because the defect is gone, not because the check was inconvenient.
    # The sweep detected the disappearance itself, by semantic anchor and AST
    # fingerprint rather than by line number, and named it -- which is precisely
    # the behaviour this registry exists to have.
    (
        "C2-108",
        _Challenge(
            "src/cryodaq/storage/channel_descriptors.py",
            "LiveChannelDescriptorCatalog.bind",
            "identity indexing or slicing",
            "060b2227021753d8d0cb",
        ),
        "LEGITIMATE",
        "descriptor persistence owns channel_id identity key",
    ),
    (
        "C2-109",
        _Challenge(
            "src/cryodaq/web/server.py",
            "_ServerState.on_reading",
            "computed membership over identity",
            "a3c6aa0200df91041974",
        ),
        "OPEN-ROUTING-DEBT",
        "web dashboard derives instrument from channel spelling",
    ),
    (
        "C2-110",
        _Challenge(
            "src/cryodaq/web/server.py",
            "_ServerState.on_reading",
            "identity spelling operation startswith()",
            "5e8520ba25821e4f74a4",
        ),
        "OPEN-ROUTING-DEBT",
        "web dashboard derives instrument from channel prefix",
    ),
    (
        "C2-111",
        _Challenge(
            "src/cryodaq/web/server.py",
            "_ServerState.on_reading",
            "identity indexing or slicing",
            "4093f04ed24456b4b8de",
        ),
        "OPEN-ROUTING-DEBT",
        "web dashboard derives instrument number from channel spelling",
    ),
    (
        "C2-112",
        _Challenge(
            "src/cryodaq/gui/dashboard/dynamic_sensor_grid.py",
            "DynamicSensorGrid.dispatch_reading",
            "computed membership over identity",
            "a56a567a833ac4318496",
        ),
        "LEGITIMATE",
        "resolved GUI cell map owns exact channel identity keys",
    ),
    (
        "C2-113",
        _Challenge(
            "src/cryodaq/gui/dashboard/experiment_card.py",
            "<module>",
            "GUI identifier literal roster",
            "3597afd2ef21b4318fa4",
        ),
        "LEGITIMATE",
        "ExperimentCardData contract declares the fixed reference-channel roster",
    ),
    (
        "C2-114",
        _Challenge(
            "src/cryodaq/gui/dashboard/experiment_card.py",
            "ExperimentCardData.__post_init__",
            "computed membership over identity",
            "85b3c6241fa05daf8185",
        ),
        "LEGITIMATE",
        "ExperimentCardData validates against its declared reference-channel roster",
    ),
    (
        "C2-115",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "<module>",
            "GUI identifier literal roster",
            "e92d3dc52d82109e020c",
        ),
        "LEGITIMATE",
        "first-run configuration declares the supported instrument-type roster",
    ),
    (
        "C2-116",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "<module>",
            "GUI identifier literal roster",
            "030329c4285b444f6439",
        ),
        "LEGITIMATE",
        "generated configuration header prose is not an identity selector",
    ),
    (
        "C2-117",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "<module>",
            "GUI identifier literal roster",
            "f31bbe0b9500b3d7401d",
        ),
        "LEGITIMATE",
        "generated descriptor header prose is not an identity selector",
    ),
    (
        "C2-118",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "build_channel_descriptors_local",
            "computed membership over identity",
            "a1f171ba497af421b88f",
        ),
        "LEGITIMATE",
        "descriptor generation rejects duplicate exact channel identities",
    ),
    (
        "C2-119",
        _Challenge(
            "src/cryodaq/gui/first_run_config.py",
            "build_channel_descriptors_local",
            "computed membership over identity",
            "1eca03c528ebd6c3ca2b",
        ),
        "LEGITIMATE",
        "binding generation rejects duplicate exact channel identities",
    ),
    (
        "C2-120",
        _Challenge(
            "src/cryodaq/gui/first_run_wizard.py",
            "<module>",
            "GUI identifier literal roster",
            "ab87d2183f84e5dc2285",
        ),
        "LEGITIMATE",
        "first-run source-setup schema declares the reviewed field roster",
    ),
    (
        "C2-121",
        _Challenge(
            "src/cryodaq/gui/shell/annunciation_controller.py",
            "<module>",
            "GUI identifier literal roster",
            "23bc917a4a26728cfcf5",
        ),
        "LEGITIMATE",
        "annunciation protocol declares its accepted source values",
    ),
    (
        "C2-122",
        _Challenge(
            "src/cryodaq/gui/shell/annunciation_controller.py",
            "decode_projection",
            "GUI identifier-derived comparison",
            "bd10d7cb4a6717d6fd80",
        ),
        "LEGITIMATE",
        "annunciation projection validation requires a source_key",
    ),
    (
        "C2-123",
        _Challenge(
            "src/cryodaq/gui/shell/annunciation_controller.py",
            "AnnunciationController.acknowledge",
            "GUI identifier-derived comparison",
            "36bf20dbc0c8fd9c707b",
        ),
        "LEGITIMATE",
        "annunciation acknowledgement correlates exact protocol identity values",
    ),
    (
        "C2-124",
        _Challenge(
            "src/cryodaq/gui/shell/annunciation_controller.py",
            "AnnunciationController._activations_with_pending_alarm_holds",
            "GUI identifier-derived comparison",
            "406ec91326093ef606de",
        ),
        "LEGITIMATE",
        "annunciation hold correlation compares exact protocol identity values",
    ),
    (
        "C2-125",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/calibration_panel.py",
            "<module>",
            "GUI identifier literal roster",
            "9523370ce05f520d980f",
        ),
        "LEGITIMATE",
        "configuration filename is not an instrument identity selector",
    ),
    (
        "C2-126",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/calibration_panel.py",
            "_load_lakeshore_channels",
            "computed membership over identity",
            "1acf40e8dbb7480cd2b2",
        ),
        "LEGITIMATE",
        "instrument configuration schema declares the channel label key",
    ),
    (
        "C2-127",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/calibration_panel.py",
            "_load_lakeshore_channels",
            "identity indexing or slicing",
            "1d9eb185b872e4ba78f0",
        ),
        "LEGITIMATE",
        "instrument configuration schema owns channel label lookup",
    ),
    (
        "C2-128",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/conductivity_panel.py",
            "<module>",
            "GUI identifier literal roster",
            "f5edd02f8c469da74217",
        ),
        "BLOCKED-ON-SCHEMA",
        "conductivity panel lacks a descriptor-backed power-channel selector",
    ),
    (
        "C2-129",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "is_manifest_multiline_descriptor",
            "GUI identifier-derived comparison",
            "279862590dd0d5fd4034",
        ),
        "LEGITIMATE",
        "MultiLine manifest descriptor authority declares the exact length-channel binding",
    ),
    (
        "C2-130",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "is_manifest_multiline_descriptor",
            "GUI identifier-derived comparison",
            "0beb0337d769150cf7ff",
        ),
        "LEGITIMATE",
        "MultiLine manifest descriptor authority declares exact environment bindings",
    ),
    (
        "C2-131",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/multiline_panel.py",
            "_env_kind",
            "GUI identifier-derived comparison",
            "6e2b8a021465d98b985f",
        ),
        "BLOCKED-ON-SCHEMA",
        "MultiLine environment role still depends on parsing the channel spelling",
    ),
    (
        "C2-132",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/operator_log_panel.py",
            "<module>",
            "GUI identifier literal roster",
            "6215c7b9d67cc478270a",
        ),
        "LEGITIMATE",
        "operator-log protocol declares its exact analytics channel",
    ),
    (
        "C2-133",
        _Challenge(
            "src/cryodaq/gui/shell/overlays/operator_log_panel.py",
            "OperatorLogPanel.on_reading",
            "GUI identifier-derived comparison",
            "2097ca6a3ad339ea5398",
        ),
        "LEGITIMATE",
        "operator-log consumer matches its declared protocol channel exactly",
    ),
    (
        "C2-134",
        _Challenge(
            "src/cryodaq/gui/shell/top_watch_bar.py",
            "<module>",
            "GUI identifier literal roster",
            "4a1112c7c5c75301d3e5",
        ),
        "LEGITIMATE",
        "watch-bar contract declares the fixed second-stage reference channel",
    ),
    (
        "C2-135",
        _Challenge(
            "src/cryodaq/gui/shell/top_watch_bar.py",
            "<module>",
            "GUI identifier literal roster",
            "c7304d70e94206cf8c7a",
        ),
        "LEGITIMATE",
        "watch-bar contract declares the fixed nitrogen-plate reference channel",
    ),
    (
        "C2-136",
        _Challenge(
            "src/cryodaq/gui/shell/top_watch_bar.py",
            "TopWatchBar.on_reading",
            "computed membership over identity",
            "d4683c56e2f188fd1b7a",
        ),
        "LEGITIMATE",
        "watch bar selects exact identities from its declared physical-reference roster",
    ),
    (
        "C2-137",
        _Challenge(
            "src/cryodaq/gui/shell/views/analytics_widgets.py",
            "CooldownPredictionWidget",
            "GUI identifier literal roster",
            "ed664f35fd9bf565582f",
        ),
        "LEGITIMATE",
        "predictor key is internal state and not a channel identity selector",
    ),
    (
        "C2-138",
        _Challenge(
            "src/cryodaq/gui/shell/views/analytics_widgets.py",
            "KeithleyPowerWidget.set_keithley_readings",
            "bare literal equality over identity",
            "0223438e06cad6d93601",
        ),
        "BLOCKED-ON-SCHEMA",
        "Keithley power widget lacks descriptor-backed SMU role selection",
    ),
    (
        "C2-139",
        _Challenge(
            "src/cryodaq/gui/shell/views/analytics_widgets.py",
            "KeithleyPowerWidget.set_keithley_readings",
            "bare literal equality over identity",
            "1f37d808dfc05a615650",
        ),
        "BLOCKED-ON-SCHEMA",
        "Keithley power widget lacks descriptor-backed SMU role selection",
    ),
    (
        "C2-140",
        _Challenge(
            "src/cryodaq/gui/shell/views/analytics_widgets.py",
            "KeithleyPowerWidget.set_keithley_readings",
            "GUI identifier-derived comparison",
            "bf04142ee62c2c3559a9",
        ),
        "BLOCKED-ON-SCHEMA",
        "Keithley power widget uses a spelling-derived SMU role",
    ),
    (
        "C2-141",
        _Challenge(
            "src/cryodaq/gui/shell/views/analytics_widgets.py",
            "KeithleyPowerWidget.set_keithley_readings",
            "dict dispatch keyed on identity",
            "bb31da67fdfb525cb4a6",
        ),
        "BLOCKED-ON-SCHEMA",
        "Keithley power widget derives quantity and unit from a path segment",
    ),
    (
        "C2-143",
        _Challenge(
            "src/cryodaq/gui/shell/views/analytics_widgets.py",
            "TemperatureSteadyStateWidget.set_temperature_readings",
            "computed membership over identity",
            "5ee1f2f2a052628afff5",
        ),
        "OPEN-ROUTING-DEBT",
        "landmark routing parses a display suffix from channel spelling",
    ),
    (
        "C2-144",
        _Challenge(
            "src/cryodaq/gui/shell/views/analytics_widgets.py",
            "TemperatureSteadyStateWidget._key_for_short_id",
            "GUI identifier-derived comparison",
            "b52e31519b8cfa6c083e",
        ),
        "LEGITIMATE",
        "steady-state widget matches exact identities from its declared landmark roster",
    ),
)

_REGISTRY = tuple(_Registration(*row) for row in _REGISTRY_ROWS)
_LIVE_PRODUCT_DEFECT_IDS = frozenset()


def _registry_errors(
    sites: list[_Site],
    registrations: tuple[_Registration, ...] = _REGISTRY,
) -> list[str]:
    expected = Counter(registration.challenge for registration in registrations)
    actual = Counter(site.challenge for site in sites)
    unexpected = actual - expected
    missing = expected - actual
    errors: list[str] = []

    for site in sites:
        if unexpected[site.challenge] <= 0:
            continue
        unexpected[site.challenge] -= 1
        errors.append(
            f"Identity spelling inference at {site.path}:{site.line} "
            f"({site.reason}; scope {site.scope}; AST {site.challenge.fingerprint}). "
            "Select through descriptor/resolved-binding authority; only compare "
            "opaque identity values for exact equality. Do not register this site "
            "as legitimate without naming the declaring authority."
        )

    for registration in registrations:
        if missing[registration.challenge] <= 0:
            continue
        missing[registration.challenge] -= 1
        challenge = registration.challenge
        errors.append(
            f"Registered challenge {registration.registration_id} disappeared or "
            f"changed policy shape: {challenge.path} scope {challenge.scope}, "
            f"{challenge.reason}, AST {challenge.fingerprint}."
        )
    return errors


def _assert_complete_registry(
    sites: list[_Site],
    registrations: tuple[_Registration, ...] = _REGISTRY,
) -> None:
    errors = _registry_errors(sites, registrations)
    assert not errors, "\n" + "\n".join(errors)


def test_c2_python_spelling_sweep_has_an_exact_shape_registry() -> None:
    sites = _sites(_root())
    _assert_complete_registry(sites)
    assert len({registration.registration_id for registration in _REGISTRY}) == len(_REGISTRY)
    assert {registration.bucket for registration in _REGISTRY} <= {
        "LEGITIMATE",
        "OPEN-ROUTING-DEBT",
        "BLOCKED-ON-SCHEMA",
        "LIVE-C2-PRODUCT-DEFECT",
    }
    assert {
        registration.registration_id for registration in _REGISTRY if registration.bucket == "LIVE-C2-PRODUCT-DEFECT"
    } == _LIVE_PRODUCT_DEFECT_IDS
    assert all(registration.authority for registration in _REGISTRY if registration.bucket == "LEGITIMATE")


@pytest.mark.parametrize("state", ("missing", "empty"))
def test_c2_python_spelling_sweep_fails_closed_for_missing_or_empty_roots(
    tmp_path: Path,
    state: str,
) -> None:
    root = tmp_path / state
    if state == "empty":
        (root / "src" / "cryodaq").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="C2 scan root"):
        _sites(root)


_PROOF_CASES = {
    "startswith": (
        "def probe(item):\n    identifier = item.channel\n    return identifier.startswith('cold')\n",
        "identity spelling operation startswith()",
    ),
    "endswith": (
        "def probe(item):\n    identifier = item.channel\n    return identifier.endswith('/pressure')\n",
        "identity spelling operation endswith()",
    ),
    "literal_tuple_membership": (
        "def probe(item):\n    identifier = item.channel\n    return identifier in ('cold', 'warm')\n",
        "literal membership over identity",
    ),
    "bare_literal_equality": (
        "def probe(item):\n    identifier = item.channel\n    return identifier == 'cold'\n",
        "bare literal equality over identity",
    ),
    "re_search": (
        "import re\ndef probe(item):\n    identifier = item.channel\n    return re.search('cold', identifier)\n",
        "regular expression search() over identity",
    ),
    "compiled_regex": (
        "import re\n"
        "PATTERN = re.compile('cold')\n"
        "def probe(item):\n"
        "    identifier = item.channel\n"
        "    return PATTERN.search(identifier)\n",
        "regular expression search() over identity",
    ),
    "slicing": (
        "def probe(item):\n    identifier = item.channel\n    return identifier[:1] == 'c'\n",
        "identity slicing comparison",
    ),
    "str_split_comparison": (
        "def probe(item):\n    identifier = item.channel\n    return str.split(identifier, '/')[0] == 'cold'\n",
        "identity split-prefix comparison",
    ),
    "local_alias": (
        "def probe(item):\n"
        "    identifier = item.channel\n"
        "    alias = identifier\n"
        "    return alias.startswith('cold')\n",
        "identity spelling operation startswith()",
    ),
    "helper_return": (
        "def identity_from(item):\n"
        "    return item.channel\n"
        "def probe(item):\n"
        "    identifier = identity_from(item)\n"
        "    return identifier.startswith('cold')\n",
        "identity spelling operation startswith()",
    ),
    "dict_dispatch": (
        "def probe(item):\n    identifier = item.channel\n    return {'cold': 1}[identifier]\n",
        "dict dispatch keyed on identity",
    ),
    "match_dispatch": (
        "def probe(item):\n"
        "    identifier = item.channel\n"
        "    match identifier:\n"
        "        case 'cold':\n"
        "            return 1\n",
        "match dispatch keyed on identity",
    ),
    "literal_list_membership": (
        "def probe(item):\n    identifier = item.channel\n    return identifier in ['cold', 'warm']\n",
        "literal membership over identity",
    ),
    "literal_set_membership": (
        "def probe(item):\n    identifier = item.channel\n    return identifier in {'cold', 'warm'}\n",
        "literal membership over identity",
    ),
    "literal_not_in": (
        "def probe(item):\n    identifier = item.channel\n    return identifier not in ('cold', 'warm')\n",
        "literal membership over identity",
    ),
    "literal_not_equal": (
        "def probe(item):\n    identifier = item.channel\n    return identifier != 'cold'\n",
        "bare literal equality over identity",
    ),
    "re_match": (
        "import re\ndef probe(item):\n    return re.match('cold', item.channel)\n",
        "regular expression match() over identity",
    ),
    "re_fullmatch": (
        "import re\ndef probe(item):\n    return re.fullmatch('cold', item.channel)\n",
        "regular expression fullmatch() over identity",
    ),
    "rsplit_comparison": (
        "def probe(item):\n    return item.channel.rsplit('/', 1)[0] == 'cold'\n",
        "identity split-prefix comparison",
    ),
    "direct_attribute": (
        "def probe(item):\n    return item.channel.startswith('cold')\n",
        "identity spelling operation startswith()",
    ),
    "annotated_alias": (
        "def probe(item):\n    identifier: str = item.channel\n    return identifier.startswith('cold')\n",
        "identity spelling operation startswith()",
    ),
    "chained_alias": (
        "def probe(item):\n    first = second = item.channel\n    return second.startswith('cold')\n",
        "identity spelling operation startswith()",
    ),
    "identity_indexing": (
        "def probe(item):\n    identifier = item.channel\n    return identifier[0]\n",
        "identity indexing or slicing",
    ),
}


def test_c2_repo_wide_spelling_sweep_proves_each_injection_and_removal(tmp_path: Path) -> None:
    assert len(_PROOF_CASES) == 23
    root = tmp_path / "probe_root"
    target = root / "src" / "cryodaq" / "c2_probe.py"
    target.parent.mkdir(parents=True)
    for name, (source, reason) in _PROOF_CASES.items():
        target.write_text(source, encoding="utf-8")
        assert any(site.reason == reason for site in _sites(root)), name
        target.unlink()
        with pytest.raises(RuntimeError, match="contains no Python files"):
            _sites(root)


@pytest.mark.parametrize(
    ("name", "source", "reason"),
    (
        (
            "for_target_from_identity_keyed_mapping",
            "import re\n"
            "PATTERN = re.compile('cold')\n"
            "class Probe:\n"
            "    def record(self, reading):\n"
            "        self.latest[reading.channel] = 1\n"
            "    def check(self):\n"
            "        for key, value in self.latest.items():\n"
            "            if PATTERN.match(key):\n"
            "                return value\n",
            "regular expression match() over identity",
        ),
        (
            "comprehension_target_from_identity_keyed_mapping",
            "import re\n"
            "PATTERN = re.compile('cold')\n"
            "class Probe:\n"
            "    def record(self, reading):\n"
            "        self.latest[reading.channel] = 1\n"
            "    def check(self):\n"
            "        return [value for key, value in self.latest.items() if PATTERN.match(key)]\n",
            "regular expression match() over identity",
        ),
        (
            "computed_fstring_needle",
            "def probe(channel, alias):\n    return f'/{alias}/' in channel\n",
            "computed membership over identity",
        ),
        (
            "named_needle",
            "def probe(channel, needle):\n    return needle in channel\n",
            "computed membership over identity",
        ),
        (
            "short_comprehension_target",
            "def probe(data):\n    return [ch for ch in data if ch.startswith('T')]\n",
            "identity spelling operation startswith()",
        ),
    ),
)
def test_c2_python_spelling_sweep_detects_red_team_bypasses(
    tmp_path: Path,
    name: str,
    source: str,
    reason: str,
) -> None:
    target = tmp_path / name / "src" / "cryodaq" / "probe.py"
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding="utf-8")
    assert any(site.reason == reason for site in _sites(target.parents[2])), name


def _registrations_for_sites(sites: list[_Site]) -> tuple[_Registration, ...]:
    return tuple(
        _Registration(f"MUTATION-{index}", site.challenge, "LEGITIMATE", "test authority")
        for index, site in enumerate(sites)
    )


@pytest.mark.parametrize(
    ("relative", "before", "after"),
    (
        (
            "src/cryodaq/core/safety_manager.py",
            "if self._mock and any(pattern.match(ch) for pattern in self._config.critical_channels)",
            'if self._mock and re.compile(r".*").match(ch)',
        ),
        (
            "src/cryodaq/gui/shell/overlays/keithley_panel.py",
            'if channel.startswith("analytics/keithley_channel_state/"):',
            'if channel.startswith("Т"):',
        ),
    ),
)
def test_c2_registry_rejects_exact_same_line_policy_substitutions(
    tmp_path: Path,
    relative: str,
    before: str,
    after: str,
) -> None:
    source = (_root() / relative).read_text(encoding="utf-8")
    assert source.count(before) == 1
    root = tmp_path / "mutation"
    target = root / relative
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding="utf-8")
    registrations = _registrations_for_sites(_sites(root))
    assert _registry_errors(_sites(root), registrations) == []

    target.write_text(source.replace(before, after), encoding="utf-8")
    errors = _registry_errors(_sites(root), registrations)
    assert any("Identity spelling inference at" in error for error in errors)
    assert any("changed policy shape" in error for error in errors)
    assert any("Do not register this site as legitimate" in error for error in errors)


def test_c2_registry_rejects_a_new_gui_site_and_names_a_genuine_fix(
    tmp_path: Path,
) -> None:
    root = tmp_path / "gui_registry"
    target = root / "src" / "cryodaq" / "gui" / "probe.py"
    target.parent.mkdir(parents=True)
    original = "def route(reading):\n    return reading.channel.startswith('cold')\n"
    target.write_text(original, encoding="utf-8")
    registrations = _registrations_for_sites(_sites(root))

    target.write_text(
        original + "\ndef new_route(reading):\n    return reading.channel.endswith('/pressure')\n",
        encoding="utf-8",
    )
    new_errors = _registry_errors(_sites(root), registrations)
    assert any("probe.py:5" in error for error in new_errors)
    assert any("Do not register this site as legitimate" in error for error in new_errors)

    target.write_text(
        "def route(reading, resolved_channel):\n    return reading.channel == resolved_channel\n",
        encoding="utf-8",
    )
    fixed_errors = _registry_errors(_sites(root), registrations)
    assert fixed_errors == [
        "Registered challenge MUTATION-0 disappeared or changed policy shape: "
        "src/cryodaq/gui/probe.py scope route, identity spelling operation "
        f"startswith(), AST {registrations[0].challenge.fingerprint}."
    ]


def test_c2_python_spelling_sweep_includes_pyw(tmp_path: Path) -> None:
    target = tmp_path / "pyw" / "src" / "cryodaq" / "operator.pyw"
    target.parent.mkdir(parents=True)
    target.write_text(
        "def probe(reading):\n    return reading.channel.startswith('T')\n",
        encoding="utf-8",
    )
    assert len(_sites(target.parents[2])) == 1


def test_c2_repo_wide_spelling_sweep_accepts_declared_identity_equalities(tmp_path: Path) -> None:
    root = tmp_path / "negative_controls"
    target = root / "src" / "cryodaq" / "c2_controls.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "def configured_binding(reading, resolved_bindings):\n"
        "    return reading.channel == resolved_bindings.cold_stage_channel\n\n"
        "def descriptor_identity(descriptor, reading):\n"
        "    return descriptor.instrument_id == reading.instrument_id\n",
        encoding="utf-8",
    )
    assert _sites(root) == []
