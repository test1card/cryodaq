"""Fail closed when tests introduce a fixed network bind.

The sweep is intentionally syntactic.  It catches literal or locally constant
ports passed to direct bind APIs and to started CryoDAQ ZMQ owners.  Dynamic
values and port zero remain allowed.  Binder-shaped tests that deliberately
stop before a real bind or use a fake socket are registered explicitly below.
"""

from __future__ import annotations

import ast
import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

_TESTS_ROOT = Path(__file__).resolve().parents[1]
_SCOPE_NODES = (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)
_UNKNOWN = object()


@dataclass(frozen=True, order=True)
class FixedPortBind:
    path: str
    scope: str
    api: str
    endpoint: str
    control_fingerprint: str


@dataclass(frozen=True)
class FixedPortException:
    site: FixedPortBind
    reason: str


_FIXED_PORT_EXCEPTIONS = (
    FixedPortException(
        FixedPortBind(
            "tests/test_zmq_bind_recovery.py",
            "test_bind_with_retry_retries_on_eaddrinuse_then_succeeds",
            "_bind_with_retry",
            "tcp://127.0.0.1:5555",
            "2ed298c1a1ee68142aae",
        ),
        "The production retry helper receives a MagicMock socket; no network bind occurs.",
    ),
    FixedPortException(
        FixedPortBind(
            "tests/test_zmq_bind_recovery.py",
            "test_bind_with_retry_raises_after_max_attempts",
            "_bind_with_retry",
            "tcp://127.0.0.1:5555",
            "e8da5726d9c3ce723c7e",
        ),
        "The exhaustion control injects EADDRINUSE through a MagicMock socket.",
    ),
    FixedPortException(
        FixedPortBind(
            "tests/test_zmq_safety.py",
            "test_publisher_rejects_wildcard_bind",
            "ZMQPublisher.start",
            "tcp://0.0.0.0:5561",
            "b95f3c76632581c5f0fa",
        ),
        "Production rejects the wildcard address before it reaches socket.bind().",
    ),
    FixedPortException(
        FixedPortBind(
            "tests/core/test_zmq_command_server_supervision.py",
            "test_command_server_partial_start_rolls_back_and_allows_clean_retry",
            "ZMQCommandServer.start",
            "tcp://127.0.0.1:5556",
            "2aeefc4ef68290982d8e",
        ),
        "The test replaces _open_bound_socket with a deterministic fake owner.",
    ),
    FixedPortException(
        FixedPortBind(
            "tests/test_zmq_safety.py",
            "test_command_server_rejects_wildcard_bind",
            "ZMQCommandServer.start",
            "tcp://0.0.0.0:5560",
            "00b7d6e627cc3cac3528",
        ),
        "Production rejects this parameterized wildcard before socket.bind().",
    ),
    FixedPortException(
        FixedPortBind(
            "tests/test_zmq_safety.py",
            "test_command_server_rejects_wildcard_bind",
            "ZMQCommandServer.start",
            "tcp://*:5560",
            "00b7d6e627cc3cac3528",
        ),
        "Production rejects this parameterized wildcard before socket.bind().",
    ),
    FixedPortException(
        FixedPortBind(
            "tests/test_zmq_safety.py",
            "test_command_server_rejects_wildcard_bind",
            "ZMQCommandServer.start",
            "tcp://[::]:5560",
            "00b7d6e627cc3cac3528",
        ),
        "Production rejects this parameterized wildcard before socket.bind().",
    ),
)


def _scope_nodes(root: ast.AST):
    for child in ast.iter_child_nodes(root):
        if isinstance(child, _SCOPE_NODES):
            continue
        yield child
        yield from _scope_nodes(child)


def _child_scopes(root: ast.AST):
    for child in ast.iter_child_nodes(root):
        if isinstance(child, _SCOPE_NODES):
            yield child
        else:
            yield from _child_scopes(child)


def _owner_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _owner_key(node.value)
        return f"{owner}.{node.attr}" if owner else None
    return None


def _literal(node: ast.AST | None, bindings: dict[str, Any]) -> Any:
    if node is None:
        return _UNKNOWN
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return bindings.get(node.id, _UNKNOWN)
    if isinstance(node, ast.Attribute):
        owner = _owner_key(node)
        return bindings.get(owner, _UNKNOWN) if owner else _UNKNOWN
    if isinstance(node, ast.NamedExpr):
        return _literal(node.value, bindings)
    if isinstance(node, (ast.List, ast.Tuple)):
        values = tuple(_literal(item, bindings) for item in node.elts)
        return _UNKNOWN if _UNKNOWN in values else values
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal(node.left, bindings)
        right = _literal(node.right, bindings)
        if left is not _UNKNOWN and right is not _UNKNOWN:
            try:
                return left + right
            except TypeError:
                return _UNKNOWN
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
                continue
            if isinstance(value, ast.FormattedValue):
                rendered = _literal(value.value, bindings)
                if rendered is not _UNKNOWN and value.format_spec is None:
                    parts.append(str(rendered))
                    continue
            return _UNKNOWN
        return "".join(parts)
    return _UNKNOWN


def _bindings(nodes: tuple[ast.AST, ...], inherited: dict[str, Any]) -> dict[str, Any]:
    assignments: dict[str, list[ast.AST | None]] = {}

    def record(target: ast.AST, value: ast.AST | None) -> None:
        if (
            isinstance(target, (ast.List, ast.Tuple))
            and isinstance(value, (ast.List, ast.Tuple))
            and len(target.elts) == len(value.elts)
        ):
            for child_target, child_value in zip(target.elts, value.elts, strict=True):
                record(child_target, child_value)
            return
        key = _owner_key(target)
        if key:
            assignments.setdefault(key, []).append(value)

    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                record(target, node.value)
        elif isinstance(node, ast.AnnAssign):
            record(node.target, node.value)
        elif isinstance(node, ast.NamedExpr):
            record(node.target, node.value)

    base = {key: value for key, value in inherited.items() if key not in assignments}
    result = dict(base)
    for _pass in range(len(nodes) + 1):
        candidate = dict(base)
        for key, value_nodes in assignments.items():
            values = tuple(_literal(value_node, result) for value_node in value_nodes)
            if not values or any(value is _UNKNOWN for value in values):
                continue
            first = values[0]
            if all(value == first for value in values[1:]):
                candidate[key] = first
        if candidate == result:
            break
        result = candidate
    return result


def _scope_fingerprint(root: ast.AST) -> str:
    normalized = ast.dump(root, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def _call_name(call: ast.Call) -> str:
    function = call.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return ""


def _argument(
    call: ast.Call,
    position: int | None,
    keyword: str,
    bindings: dict[str, Any],
    *,
    default: Any = _UNKNOWN,
) -> Any:
    for item in call.keywords:
        if item.arg == keyword:
            return _literal(item.value, bindings)
    if position is not None and len(call.args) > position:
        return _literal(call.args[position], bindings)
    return default


def _parameter_variants(root: ast.AST, inherited: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    variants = [dict(inherited)]
    if not isinstance(root, (ast.AsyncFunctionDef, ast.FunctionDef)):
        return tuple(variants)

    positional = (*root.args.posonlyargs, *root.args.args)
    if root.args.defaults:
        defaulted = zip(positional[-len(root.args.defaults) :], root.args.defaults, strict=True)
        for argument, default_node in defaulted:
            value = _literal(default_node, inherited)
            if value is not _UNKNOWN:
                for variant in variants:
                    variant[argument.arg] = value
    for argument, default_node in zip(root.args.kwonlyargs, root.args.kw_defaults, strict=True):
        value = _literal(default_node, inherited)
        if value is not _UNKNOWN:
            for variant in variants:
                variant[argument.arg] = value

    for decorator in root.decorator_list:
        if not isinstance(decorator, ast.Call) or _call_name(decorator) != "parametrize":
            continue
        if len(decorator.args) < 2:
            continue
        expanded: list[dict[str, Any]] = []
        for variant in variants:
            raw_names = _literal(decorator.args[0], variant)
            rows = _literal(decorator.args[1], variant)
            if isinstance(raw_names, str):
                names = tuple(name.strip() for name in raw_names.split(",") if name.strip())
            elif isinstance(raw_names, tuple) and all(isinstance(name, str) for name in raw_names):
                names = raw_names
            else:
                continue
            if not names or not isinstance(rows, tuple):
                continue
            for row in rows:
                values = (row,) if len(names) == 1 else row
                if not isinstance(values, tuple) or len(values) != len(names):
                    continue
                expanded.append({**variant, **dict(zip(names, values, strict=True))})
        if expanded:
            variants = expanded
    return tuple(variants)


def _class_attribute_bindings(root: ast.ClassDef, inherited: dict[str, Any]) -> dict[str, Any]:
    method_nodes = tuple(
        node
        for child in root.body
        if isinstance(child, (ast.AsyncFunctionDef, ast.FunctionDef))
        for node in _scope_nodes(child)
    )
    resolved = _bindings(method_nodes, inherited)
    return {
        **inherited,
        **{key: value for key, value in resolved.items() if key.startswith("self.")},
    }


def _fixed_endpoint(value: Any) -> str | None:
    if isinstance(value, tuple) and len(value) >= 2:
        host, port = value[:2]
        if isinstance(host, str) and type(port) is int and 0 < port <= 65535:
            return f"{host}:{port}"
        return None
    if not isinstance(value, str) or ":" not in value:
        return None
    try:
        port = int(value.rsplit(":", 1)[1])
    except ValueError:
        return None
    if not 0 < port <= 65535:
        return None
    scheme = value.split("://", 1)[0].lower() if "://" in value else ""
    return value if scheme in {"http", "https", "tcp", "udp"} else None


def _host_port_endpoint(host: Any, port: Any) -> str | None:
    if isinstance(host, str) and type(port) is int and 0 < port <= 65535:
        return f"{host}:{port}"
    return None


def _binder_endpoints(call: ast.Call, bindings: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    name = _call_name(call)
    if name == "ZMQPublisher":
        address = _argument(
            call,
            0,
            "address",
            bindings,
            default="tcp://127.0.0.1:5555",
        )
        endpoint = _fixed_endpoint(address)
        return (("ZMQPublisher.start", endpoint),) if endpoint else ()
    if name == "ZMQCommandServer":
        address = _argument(
            call,
            0,
            "address",
            bindings,
            default="tcp://127.0.0.1:5556",
        )
        endpoint = _fixed_endpoint(address)
        return (("ZMQCommandServer.start", endpoint),) if endpoint else ()
    if name == "ReplayEngine":
        endpoints = []
        for keyword, default in (
            ("pub_addr", "tcp://127.0.0.1:5555"),
            ("cmd_addr", "tcp://127.0.0.1:5556"),
            ("safe_cmd_addr", "tcp://127.0.0.1:5558"),
        ):
            endpoint = _fixed_endpoint(_argument(call, None, keyword, bindings, default=default))
            if endpoint:
                endpoints.append((f"ReplayEngine.start[{keyword}]", endpoint))
        return tuple(endpoints)
    return ()


def _assigned_call(node: ast.AST) -> tuple[str, ast.Call] | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        value = node.value
    elif isinstance(node, ast.AnnAssign):
        target = node.target
        value = node.value
    else:
        return None
    owner = _owner_key(target)
    if owner and isinstance(value, ast.Call):
        return owner, value
    return None


def _direct_bind_site(call: ast.Call, bindings: dict[str, Any]) -> tuple[str, str] | None:
    name = _call_name(call)
    if name in {"bind", "_bind_with_retry"}:
        position = 1 if name == "_bind_with_retry" else 0
        if len(call.args) > position:
            endpoint = _fixed_endpoint(_literal(call.args[position], bindings))
            if endpoint:
                return name, endpoint
    if name in {"TCPServer", "ThreadingTCPServer", "UDPServer", "HTTPServer", "ThreadingHTTPServer"}:
        if call.args:
            endpoint = _fixed_endpoint(_literal(call.args[0], bindings))
            if endpoint:
                return name, endpoint
    positions = {
        "TCPSite": (1, 2),
        "create_server": (1, 2),
        "make_server": (0, 1),
        "run_app": (1, 2),
        "start_server": (1, 2),
    }
    if name in positions:
        host_position, port_position = positions[name]
        host = _argument(call, host_position, "host", bindings)
        port = _argument(call, port_position, "port", bindings)
        endpoint = _host_port_endpoint(host, port)
        if endpoint:
            return name, endpoint
    return None


def _scan_scope_variant(
    root: ast.AST,
    *,
    relative_path: str,
    scope: str,
    inherited: dict[str, Any],
) -> list[FixedPortBind]:
    nodes = tuple(_scope_nodes(root))
    bindings = _bindings(nodes, inherited)
    control_fingerprint = _scope_fingerprint(root)
    sites: list[FixedPortBind] = []
    binders: dict[str, ast.Call] = {}
    pairs: dict[str, tuple[str, ...]] = {}

    for node in nodes:
        assigned = _assigned_call(node)
        if assigned is None:
            continue
        owner, call = assigned
        if _call_name(call) in {"ReplayEngine", "ZMQCommandServer", "ZMQPublisher"}:
            binders[owner] = call
        elif _call_name(call) == "ZMQCommandIngressPair":
            children: list[str] = []
            for position, keyword in ((0, "ordinary"), (1, "safe")):
                value = None
                for item in call.keywords:
                    if item.arg == keyword:
                        value = item.value
                if value is None and len(call.args) > position:
                    value = call.args[position]
                child_owner = _owner_key(value) if value is not None else None
                if child_owner:
                    children.append(child_owner)
            pairs[owner] = tuple(children)

    started: set[str] = set()
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        direct = _direct_bind_site(node, bindings)
        if direct is not None:
            api, endpoint = direct
            sites.append(FixedPortBind(relative_path, scope, api, endpoint, control_fingerprint))
        function = node.func
        if not isinstance(function, ast.Attribute) or function.attr != "start":
            continue
        owner = function.value
        owner_key = _owner_key(owner)
        if owner_key:
            started.add(owner_key)
        elif isinstance(owner, ast.Call):
            for api, endpoint in _binder_endpoints(owner, bindings):
                sites.append(FixedPortBind(relative_path, scope, api, endpoint, control_fingerprint))

    for owner in tuple(started):
        started.update(pairs.get(owner, ()))
    for owner in sorted(started):
        call = binders.get(owner)
        if call is None:
            continue
        for api, endpoint in _binder_endpoints(call, bindings):
            sites.append(FixedPortBind(relative_path, scope, api, endpoint, control_fingerprint))

    for child in _child_scopes(root):
        child_scope = child.name if scope == "<module>" else f"{scope}.{child.name}"
        sites.extend(
            _scan_scope(
                child,
                relative_path=relative_path,
                scope=child_scope,
                inherited=bindings,
            )
        )
    return sites


def _class_cross_method_sites(
    root: ast.ClassDef,
    *,
    relative_path: str,
    scope: str,
    inherited: dict[str, Any],
) -> list[FixedPortBind]:
    constructors: dict[str, list[tuple[str, ast.Call, dict[str, Any]]]] = {}
    starts: dict[str, set[str]] = {}
    for child in root.body:
        if not isinstance(child, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        nodes = tuple(_scope_nodes(child))
        bindings = _bindings(nodes, inherited)
        for node in nodes:
            assigned = _assigned_call(node)
            if assigned is not None:
                owner, call = assigned
                if "." in owner and _call_name(call) in {
                    "ReplayEngine",
                    "ZMQCommandServer",
                    "ZMQPublisher",
                }:
                    constructors.setdefault(owner, []).append((child.name, call, bindings))
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not isinstance(function, ast.Attribute) or function.attr != "start":
                continue
            owner = _owner_key(function.value)
            if owner and "." in owner:
                starts.setdefault(owner, set()).add(child.name)

    fingerprint = _scope_fingerprint(root)
    sites: set[FixedPortBind] = set()
    for owner, owned_constructors in constructors.items():
        start_methods = starts.get(owner, set())
        constructor_methods = {method for method, _call, _bindings_ in owned_constructors}
        if not start_methods or start_methods & constructor_methods:
            continue
        for _method, call, bindings in owned_constructors:
            for api, endpoint in _binder_endpoints(call, bindings):
                sites.add(FixedPortBind(relative_path, scope, api, endpoint, fingerprint))
    return sorted(sites)


def _scan_scope(
    root: ast.AST,
    *,
    relative_path: str,
    scope: str,
    inherited: dict[str, Any],
) -> list[FixedPortBind]:
    if isinstance(root, ast.ClassDef):
        inherited = _class_attribute_bindings(root, inherited)
        sites = _class_cross_method_sites(
            root,
            relative_path=relative_path,
            scope=scope,
            inherited=inherited,
        )
    else:
        sites = []
    for variant in _parameter_variants(root, inherited):
        sites.extend(
            _scan_scope_variant(
                root,
                relative_path=relative_path,
                scope=scope,
                inherited=variant,
            )
        )
    return sites


def _scan_source(source: str, relative_path: str) -> Counter[FixedPortBind]:
    tree = ast.parse(source, filename=relative_path)
    return Counter(
        _scan_scope(
            tree,
            relative_path=relative_path,
            scope="<module>",
            inherited={},
        )
    )


def _scan_tree(root: Path) -> Counter[FixedPortBind]:
    if not root.is_dir():
        raise AssertionError(f"fixed-port sweep root is missing: {root}")
    paths = sorted(root.rglob("*.py"))
    if not paths:
        raise AssertionError(f"fixed-port sweep root contains no Python files: {root}")
    findings: Counter[FixedPortBind] = Counter()
    for path in paths:
        relative = path.relative_to(root.parent).as_posix()
        findings.update(_scan_source(path.read_text(encoding="utf-8"), relative))
    return findings


def _registry_delta(
    actual: Counter[FixedPortBind],
    registered: Counter[FixedPortBind],
) -> tuple[Counter[FixedPortBind], Counter[FixedPortBind]]:
    return actual - registered, registered - actual


def _render(findings: Counter[FixedPortBind]) -> str:
    return "\n".join(
        f"{count} x {site.path}::{site.scope} {site.api}({site.endpoint}) control={site.control_fingerprint}"
        for site, count in sorted(findings.items())
    )


def test_no_unregistered_fixed_port_binds_under_tests() -> None:
    assert all(item.reason.strip() for item in _FIXED_PORT_EXCEPTIONS)
    registered = Counter(item.site for item in _FIXED_PORT_EXCEPTIONS)
    assert len(registered) == len(_FIXED_PORT_EXCEPTIONS), "fixed-port exception registry has duplicates"

    unexpected, missing = _registry_delta(_scan_tree(_TESTS_ROOT), registered)
    assert not unexpected and not missing, (
        "Fixed-port registry and tests/ differ in one or both directions.\n"
        f"UNREGISTERED:\n{_render(unexpected) or '<none>'}\n"
        f"STALE REGISTRY:\n{_render(missing) or '<none>'}"
    )


def test_fixed_port_sweep_fails_closed_for_missing_or_empty_root(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="missing"):
        _scan_tree(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(AssertionError, match="no Python files"):
        _scan_tree(empty)


def test_fixed_port_sweep_detects_new_direct_bind() -> None:
    source = """
import socket

PORT = 45123

def test_new_server():
    listener = socket.socket()
    listener.bind(("127.0.0.1", PORT))
"""
    path = "tests/test_new_server.py"
    findings = _scan_source(source, path)
    assert len(findings) == 1
    site = next(iter(findings))
    assert (site.path, site.scope, site.api, site.endpoint) == (
        path,
        "test_new_server",
        "bind",
        "127.0.0.1:45123",
    )
    assert _scan_source(source.replace("PORT = 45123", "PORT = 0"), path) == Counter()


def test_fixed_port_sweep_detects_started_replay_engine() -> None:
    source = """
async def test_new_replay(source):
    engine = ReplayEngine(source)
    await engine.start()
"""
    findings = _scan_source(source, "tests/test_new_replay.py")
    assert {site.api for site in findings} == {
        "ReplayEngine.start[cmd_addr]",
        "ReplayEngine.start[pub_addr]",
        "ReplayEngine.start[safe_cmd_addr]",
    }
    assert {site.endpoint for site in findings} == {
        "tcp://127.0.0.1:5555",
        "tcp://127.0.0.1:5556",
        "tcp://127.0.0.1:5558",
    }


def test_fixed_port_sweep_detects_attribute_owner_ipv6_and_start_server() -> None:
    source = """
class Harness:
    def __init__(self):
        self.address = "tcp://127.0.0.1:45123"
        self.server = ZMQCommandServer(self.address)

    async def run(self):
        await self.server.start()

def test_ipv6(listener):
    listener.bind(("::1", 45124, 0, 0))

async def test_asyncio(handler):
    await asyncio.start_server(handler, "::1", 45125)

def test_destructuring(listener):
    host, port = ("127.0.0.1", 45126)
    listener.bind((host, port))

def test_walrus(listener):
    listener.bind(("127.0.0.1", (port := 45127)))
"""
    findings = _scan_source(source, "tests/test_network_owners.py")
    assert {(site.api, site.endpoint) for site in findings} == {
        ("ZMQCommandServer.start", "tcp://127.0.0.1:45123"),
        ("bind", "::1:45124"),
        ("start_server", "::1:45125"),
        ("bind", "127.0.0.1:45126"),
        ("bind", "127.0.0.1:45127"),
    }


def test_fixed_port_sweep_allows_port_zero_and_unstarted_constructor() -> None:
    source = """
def test_unstarted(listener):
    server = ZMQCommandServer("tcp://127.0.0.1:45123")
    listener.bind(("127.0.0.1", 0))

async def test_asyncio(handler):
    await asyncio.start_server(handler, host="127.0.0.1", port=0)
"""
    assert _scan_source(source, "tests/test_safe_ports.py") == Counter()


def test_fixed_port_registry_delta_is_scanner_integrated_and_bidirectional() -> None:
    source = """
def test_probe(listener):
    fake_socket = True
    listener.bind(("127.0.0.1", 45123))
"""
    registered = _scan_source(source, "tests/test_probe.py")
    changed = _scan_source(source.replace("fake_socket = True", "fake_socket = False"), "tests/test_probe.py")
    assert {(site.path, site.scope, site.api, site.endpoint) for site in registered} == {
        (site.path, site.scope, site.api, site.endpoint) for site in changed
    }
    unexpected, missing = _registry_delta(changed, registered)
    assert sum(unexpected.values()) == 1
    assert sum(missing.values()) == 1
    assert next(iter(unexpected)).control_fingerprint != next(iter(missing)).control_fingerprint
