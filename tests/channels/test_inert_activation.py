from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

_CHANNEL_PACKAGE = "cryodaq.channels"
_SOURCE_SUFFIXES = frozenset({".py", ".pyi"})


def _is_channel_module(module: str) -> bool:
    return module == _CHANNEL_PACKAGE or module.startswith(f"{_CHANNEL_PACKAGE}.")


def _constant_string(node: ast.expr) -> str | None:
    """Return a string literal or a statically concatenated string literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_string(node.left)
        right = _constant_string(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr) and all(
        isinstance(value, ast.Constant) and isinstance(value.value, str) for value in node.values
    ):
        return "".join(value.value for value in node.values)
    return None


def _module_name(source_root: Path, path: Path) -> str:
    relative = path.relative_to(source_root).with_suffix("")
    parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
    return ".".join(("cryodaq", *parts))


def _resolve_from_module(source_root: Path, path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = _module_name(source_root, path).split(".")
    if path.stem != "__init__":
        package.pop()
    parent = package[: len(package) - node.level + 1]
    return ".".join((*parent, *((node.module or "").split("."))))


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return None if parent is None else f"{parent}.{node.attr}"
    return None


def _source_paths(source_root: Path) -> list[Path]:
    if not source_root.is_dir():
        raise AssertionError(f"channel import guard source tree is missing: {source_root}")
    paths = sorted(path for path in source_root.rglob("*") if path.suffix in _SOURCE_SUFFIXES)
    if not paths:
        raise AssertionError(f"channel import guard scanned no Python sources: {source_root}")
    return paths


def _channel_contract_dependencies(source_root: Path) -> dict[str, frozenset[str]]:
    """Enumerate statically resolvable channel dependencies, not runtime-built imports.

    This catches direct, relative, static-string ``importlib``/``__import__``,
    and second-hand re-export imports in ``.py`` and ``.pyi`` sources.  A name
    assembled from runtime data (or code executed outside these source files)
    cannot be resolved by this AST sweep and remains a review-time concern.
    """
    channel_root = source_root / "channels"
    paths = [path for path in _source_paths(source_root) if not path.is_relative_to(channel_root)]
    trees = {path: ast.parse(path.read_text(encoding="utf-8"), filename=str(path)) for path in paths}
    dependencies: dict[str, set[str]] = {}
    exports: dict[str, set[str]] = {}

    for path, tree in trees.items():
        relative = path.relative_to(source_root).as_posix()
        imports: set[str] = set()
        exported_names: set[str] = set()
        importlib_modules: set[str] = set()
        import_module_functions: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "importlib":
                        importlib_modules.add(alias.asname or alias.name)
                    if _is_channel_module(alias.name):
                        imports.add(f"import {alias.name} as {alias.asname or alias.name.split('.')[0]}")
                        exported_names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                module = _resolve_from_module(source_root, path, node)
                if module == "importlib":
                    import_module_functions.update(
                        alias.asname or alias.name for alias in node.names if alias.name == "import_module"
                    )
                if _is_channel_module(module):
                    for alias in node.names:
                        imports.add(f"from {module} import {alias.name} as {alias.asname or alias.name}")
                        exported_names.add(alias.asname or alias.name)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            is_import_module = (isinstance(node.func, ast.Name) and node.func.id in import_module_functions) or (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in importlib_modules
                and node.func.attr == "import_module"
            )
            is_builtin_import = isinstance(node.func, ast.Name) and node.func.id == "__import__"
            if not (is_import_module or is_builtin_import):
                continue
            module = _constant_string(node.args[0])
            if module is not None and _is_channel_module(module):
                loader = "__import__" if is_builtin_import else "importlib.import_module"
                imports.add(f"{loader}({module!r})")

        if imports:
            dependencies[relative] = imports
            exports[_module_name(source_root, path)] = exported_names

    for path, tree in trees.items():
        relative = path.relative_to(source_root).as_posix()
        reexports: set[str] = set()
        imported_adapters: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in exports:
                        imported_adapters[alias.asname or alias.name] = alias.name
            if not isinstance(node, ast.ImportFrom):
                continue
            module = _resolve_from_module(source_root, path, node)
            if module not in exports:
                continue
            for alias in node.names:
                if alias.name == "*" or alias.name in exports[module]:
                    reexports.add(f"re-export {module} import {alias.name}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            access = _dotted_name(node)
            if access is None:
                continue
            for bound_name, module in imported_adapters.items():
                if access.startswith(f"{bound_name}."):
                    name = access.removeprefix(f"{bound_name}.").split(".", 1)[0]
                    if name in exports[module]:
                        reexports.add(f"re-export {module} attribute {name}")
        if reexports:
            dependencies.setdefault(relative, set()).update(reexports)

    return {path: frozenset(values) for path, values in dependencies.items()}


def _write_source(root: Path, relative: str, source: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _scratch_dependencies(tmp_path: Path, sources: Iterable[tuple[str, str]]) -> dict[str, frozenset[str]]:
    source_root = tmp_path / "src" / "cryodaq"
    _write_source(source_root, "channels/__init__.py", "")
    for relative, source in sources:
        _write_source(source_root, relative, source)
    return _channel_contract_dependencies(source_root)


def _direct_imports(module: str, *names: str) -> frozenset[str]:
    return frozenset(f"from {module} import {name} as {name}" for name in names)


def test_only_approved_passive_adapters_import_channel_contract() -> None:
    source_root = Path(__file__).parents[2] / "src" / "cryodaq"
    assert _channel_contract_dependencies(source_root) == {
        "core/broker.py": _direct_imports("cryodaq.channels.persistence", "MAX_PERSISTED_ENVELOPE_BYTES"),
        "core/descriptor_transport.py": _direct_imports(
            "cryodaq.channels.descriptors",
            "ChannelDescriptorV1",
        )
        | _direct_imports(
            "cryodaq.channels.persistence",
            "PersistedChannelEnvelopeError",
            "PersistedChannelEnvelopeV1",
            "decode_persisted_channel_envelope",
        ),
        "core/safety_pattern_liveness.py": _direct_imports(
            "cryodaq.channels.descriptors",
            "ChannelRole",
            "ChannelSafetyClass",
        ),
        "core/sensor_diagnostics.py": _direct_imports(
            "cryodaq.channels.descriptors", "ChannelCatalog", "ChannelQuantity", "ChannelRole"
        ),
        "core/zmq_bridge.py": _direct_imports("cryodaq.channels.persistence", "MAX_PERSISTED_ENVELOPE_BYTES"),
        "core/zmq_subprocess.py": _direct_imports("cryodaq.channels.persistence", "MAX_PERSISTED_ENVELOPE_BYTES"),
        "gui/shell/main_window_v2.py": _direct_imports(
            "cryodaq.channels.descriptors",
            "ChannelDescriptorV1",
            "ChannelQuantity",
            "ChannelRole",
            "ChannelSafetyClass",
        ),
        "gui/shell/overlays/instruments_panel.py": _direct_imports(
            "cryodaq.channels.descriptors", "MAX_CATALOG_DESCRIPTORS", "ChannelDescriptorV1"
        ),
        "gui/shell/overlays/multiline_panel.py": _direct_imports(
            "cryodaq.channels.descriptors",
            "ChannelDescriptorV1",
            "ChannelQuantity",
            "ChannelRole",
            "ChannelSafetyClass",
        ),
        "gui/state/descriptor_store.py": _direct_imports(
            "cryodaq.channels.descriptors",
            "MAX_CATALOG_DESCRIPTORS",
            "ChannelDescriptorV1",
            "legacy_unknown_descriptor",
        ),
        "storage/channel_descriptors.py": _direct_imports(
            "cryodaq.channels.descriptors",
            "MAX_CATALOG_DESCRIPTORS",
            "ChannelCatalog",
            "ChannelDescriptorError",
            "ChannelDescriptorV1",
            "ChannelQuantity",
            "ChannelRole",
            "ChannelSafetyClass",
            "validate_catalog_update",
        )
        | _direct_imports(
            "cryodaq.channels.persistence",
            "MAX_PERSISTED_ENVELOPE_BYTES",
            "PersistedChannelEnvelopeError",
            "PersistedChannelEnvelopeV1",
            "decode_persisted_channel_envelope",
            "resolve_persisted_channel",
        ),
        "storage/descriptor_archive.py": _direct_imports(
            "cryodaq.channels.descriptors",
            "MAX_CATALOG_DESCRIPTORS",
            "ChannelDescriptorError",
            "legacy_unknown_descriptor",
            "validate_catalog_update",
        )
        | frozenset(
            {
                "from cryodaq.channels.persistence import MAX_PERSISTED_ENVELOPE_BYTES"
                " as _MAX_PERSISTED_ENVELOPE_BYTES",
                "from cryodaq.channels.persistence import PersistedChannelEnvelopeError"
                " as _PersistedChannelEnvelopeError",
                "from cryodaq.channels.persistence import decode_persisted_channel_envelope"
                " as _decode_persisted_channel_envelope",
            }
        ),
        # THE TELEGRAM SURFACE IS AN APPROVED PASSIVE READER, and it is on this list because
        # of what it is allowed to do rather than because it appeared. It reads ONE declared
        # property, `ChannelQuantity`, so `/temps` can select temperature channels by their
        # DECLARED quantity instead of by a Cyrillic-Te name prefix. It writes nothing to the
        # contract and commands nothing; the catalog reaches it from its only production
        # constructor. If this entry ever grows a second name, ask what the surface started
        # doing with the contract before widening it.
        "notifications/telegram_commands.py": _direct_imports("cryodaq.channels.descriptors", "ChannelQuantity"),
        "reporting/descriptor_projection.py": _direct_imports(
            "cryodaq.channels.persistence",
            "PersistedChannelEnvelopeError",
            "decode_persisted_channel_envelope",
        ),
        "storage/sqlite_writer.py": _direct_imports("cryodaq.channels.descriptors", "ChannelCatalog")
        | _direct_imports("cryodaq.channels.persistence", "PersistedChannelEnvelopeV1"),
    }


def test_channel_contract_guard_catches_static_import(tmp_path: Path) -> None:
    assert "probe.py" in _scratch_dependencies(tmp_path, [("probe.py", "import cryodaq.channels\n")])


def test_channel_contract_guard_catches_literal_importlib_import(tmp_path: Path) -> None:
    dependencies = _scratch_dependencies(
        tmp_path,
        [("probe.py", "import importlib\nimportlib.import_module('cryodaq.channels')\n")],
    )
    assert dependencies["probe.py"] == frozenset({"importlib.import_module('cryodaq.channels')"})


def test_channel_contract_guard_catches_computed_importlib_import(tmp_path: Path) -> None:
    dependencies = _scratch_dependencies(
        tmp_path,
        [("probe.py", "import importlib\nimportlib.import_module('cryodaq.' + 'channels')\n")],
    )
    assert dependencies["probe.py"] == frozenset({"importlib.import_module('cryodaq.channels')"})


def test_channel_contract_guard_catches_builtin_import(tmp_path: Path) -> None:
    dependencies = _scratch_dependencies(
        tmp_path,
        [("probe.py", "__import__('cryodaq.' + 'channels')\n")],
    )
    assert dependencies["probe.py"] == frozenset({"__import__('cryodaq.channels')"})


def test_channel_contract_guard_catches_literal_builtin_import(tmp_path: Path) -> None:
    dependencies = _scratch_dependencies(
        tmp_path,
        [("probe.py", "__import__('cryodaq.channels')\n")],
    )
    assert dependencies["probe.py"] == frozenset({"__import__('cryodaq.channels')"})


def test_channel_contract_guard_catches_relative_import(tmp_path: Path) -> None:
    assert "core/probe.py" in _scratch_dependencies(
        tmp_path, [("core/probe.py", "from ..channels import descriptors\n")]
    )


def test_channel_contract_guard_catches_stub_import(tmp_path: Path) -> None:
    assert "probe.pyi" in _scratch_dependencies(tmp_path, [("probe.pyi", "from cryodaq.channels import descriptors\n")])


def test_channel_contract_guard_catches_reexport(tmp_path: Path) -> None:
    dependencies = _scratch_dependencies(
        tmp_path,
        [
            ("approved.py", "from cryodaq.channels.descriptors import ChannelDescriptorV1\n"),
            ("unapproved.py", "from cryodaq.approved import ChannelDescriptorV1\n"),
        ],
    )
    assert dependencies["unapproved.py"] == frozenset({"re-export cryodaq.approved import ChannelDescriptorV1"})


def test_channel_contract_guard_catches_reexported_attribute(tmp_path: Path) -> None:
    dependencies = _scratch_dependencies(
        tmp_path,
        [
            ("approved.py", "from cryodaq.channels.descriptors import ChannelDescriptorV1\n"),
            (
                "unapproved.py",
                "import cryodaq.approved as approved\napproved.ChannelDescriptorV1\n",
            ),
        ],
    )
    assert dependencies["unapproved.py"] == frozenset({"re-export cryodaq.approved attribute ChannelDescriptorV1"})


def test_channel_contract_guard_fails_closed_for_missing_or_empty_tree(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    empty = tmp_path / "empty"
    empty.mkdir()
    for root in (missing, empty):
        try:
            _channel_contract_dependencies(root)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"guard accepted {root}")


def test_channel_contract_has_no_product_subsystem_imports() -> None:
    source_root = Path(__file__).parents[2] / "src" / "cryodaq"
    forbidden = ("cryodaq.core", "cryodaq.drivers", "cryodaq.engine", "cryodaq.storage")
    offenders: list[tuple[str, str]] = []
    for path in (source_root / "channels").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(forbidden):
                offenders.append((path.name, node.module or ""))
            elif isinstance(node, ast.Import):
                offenders.extend((path.name, alias.name) for alias in node.names if alias.name.startswith(forbidden))
    assert offenders == []
