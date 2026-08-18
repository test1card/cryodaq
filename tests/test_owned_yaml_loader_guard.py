"""OC-040: every PyYAML parse in ``cryodaq`` uses the package-owned loader."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# The module moved from `tests/governance/` to the tests root, so the depth changed.
# It lives here for the same reason `test_c2_repo_wide_spelling_sweep.py` does: it is a
# repo-wide AST sweep over production, not a governance-contract test -- and a new module
# under `tests/governance/` moves an inventory that OC-012 pins by COUNT and by hash.
_SOURCE_ROOT = Path(__file__).parents[1] / "src" / "cryodaq"
_CONVENIENCE_LOADERS = {
    "full_load",
    "full_load_all",
    "safe_load",
    "safe_load_all",
    "unsafe_load",
    "unsafe_load_all",
}
_EXPLICIT_LOADERS = {"load", "load_all", "scan", "scan_all", "parse", "compose", "compose_all"}
# PyYAML's C-backed loader classes are included because, on installations with
# LibYAML support, `yaml.CSafeLoader(text).get_single_data()` is a parse path that
# bypasses the owned loader exactly like the pure-Python classes, and `CSafeLoader`
# shares `SafeLoader`'s mutable constructor and resolver tables by reference.
_LOADER_CLASSES = {
    "Loader",
    "SafeLoader",
    "UnsafeLoader",
    "FullLoader",
    "BaseLoader",
    "CLoader",
    "CSafeLoader",
    "CFullLoader",
    "CUnsafeLoader",
}

# The mutable class attributes that subclassing `yaml.SafeLoader` shares BY
# REFERENCE.  A subclass of the owned loader that rebinds one of these to PyYAML
# state undoes the ownership snapshot and must not be trusted.
_OWNED_TABLE_NAMES = frozenset(
    {
        "yaml_constructors",
        "yaml_multi_constructors",
        "yaml_implicit_resolvers",
        "yaml_path_resolvers",
        "bool_values",
        "ESCAPE_REPLACEMENTS",
        "ESCAPE_CODES",
        "DEFAULT_TAGS",
        "inf_value",
        "nan_value",
        "timestamp_regexp",
        "NON_PRINTABLE",
        "DEFAULT_SCALAR_TAG",
        "DEFAULT_SEQUENCE_TAG",
        "DEFAULT_MAPPING_TAG",
    }
)

# The subset of owned tables that a locally-declared subclass of a raw PyYAML
# loader class must define in its own body for it to count as owning its parsing
# state rather than inheriting the host's.  `inf_value`, `nan_value`,
# `timestamp_regexp`, the DEFAULT_* tag strings, ESCAPE_* and NON_PRINTABLE are
# deliberately excluded: they are either immutable or read only by constructors
# that a bounded grammar can drop, and `cryodaq.lab_profile` -- the sanctioned
# in-package loader -- owns exactly this core set.
_CORE_OWNED_TABLES = frozenset(
    {
        "yaml_constructors",
        "yaml_multi_constructors",
        "yaml_implicit_resolvers",
        "yaml_path_resolvers",
        "bool_values",
    }
)


def _yaml_module_names(tree: ast.Module) -> set[str]:
    """Names bound to the ``yaml`` module in this tree (``import yaml as _yaml`` etc.)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name for alias in node.names if alias.name == "yaml")
    return names


def _references_yaml_module(value: ast.expr, yaml_modules: set[str]) -> bool:
    """True when ``value`` reads PyYAML state through a ``yaml``-bound name."""
    return any(
        isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in yaml_modules
        for node in ast.walk(value)
    )


def _subclass_reattaches_pyyaml_tables(class_node: ast.ClassDef, yaml_modules: set[str]) -> bool:
    """True when a class body rebinds an owned mutable parser table to PyYAML state."""
    for statement in class_node.body:
        if isinstance(statement, ast.Assign):
            targets = [(target, statement.value) for target in statement.targets]
        elif isinstance(statement, ast.AnnAssign):
            targets = [(statement.target, statement.value)]
        else:
            continue
        for target, value in targets:
            if (
                isinstance(target, ast.Name)
                and target.id in _OWNED_TABLE_NAMES
                and value is not None
                and _references_yaml_module(value, yaml_modules)
            ):
                return True
    return False


def _owned_loader_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    modules: set[str] = set()
    yaml_modules = _yaml_module_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"_owned_yaml", "cryodaq._owned_yaml"}:
            names.update(alias.asname or alias.name for alias in node.names if alias.name == "OwnedSafeLoader")
        elif isinstance(node, ast.Import):
            modules.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "cryodaq._owned_yaml" and alias.asname is not None
            )

    for node in sorted(ast.walk(tree), key=lambda item: (getattr(item, "lineno", -1), getattr(item, "col_offset", -1))):
        if isinstance(node, ast.Assign):
            targets = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if isinstance(node.value, ast.Name) and node.value.id in names:
                names.update(targets)
            else:
                names.difference_update(targets)
                modules.difference_update(targets)
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in names
                    and target.attr in _OWNED_TABLE_NAMES
                    and _references_yaml_module(node.value, yaml_modules)
                ):
                    names.discard(target.value.id)
                    modules.discard(target.value.id)
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id in names
                and target.attr in _OWNED_TABLE_NAMES
                and node.value is not None
                and _references_yaml_module(node.value, yaml_modules)
            ):
                names.discard(target.value.id)
                modules.discard(target.value.id)
        elif isinstance(node, ast.ClassDef):
            if any(
                (isinstance(base, ast.Name) and base.id in names)
                or (
                    isinstance(base, ast.Attribute)
                    and isinstance(base.value, ast.Name)
                    and base.value.id in modules
                    and base.attr == "OwnedSafeLoader"
                )
                for base in node.bases
            ):
                if _subclass_reattaches_pyyaml_tables(node, yaml_modules):
                    names.discard(node.name)
                    modules.discard(node.name)
                else:
                    names.add(node.name)
            else:
                names.discard(node.name)
                modules.discard(node.name)
    return names, modules


def _bare_yaml_table_reference(value: ast.expr, yaml_modules: set[str]) -> bool:
    """True when ``value`` is the host table itself, not a copy of it.

    ``dict(yaml.SafeLoader.yaml_constructors)`` snapshots the table at class
    definition and is ownership; ``yaml.SafeLoader.yaml_constructors`` reattaches
    the host's mutable dict and is a bypass.
    """

    if not isinstance(value, ast.Attribute):
        return False
    if not isinstance(value.value, ast.Attribute):
        return False
    return isinstance(value.value.value, ast.Name) and value.value.value.id in yaml_modules


def _class_owns_core_tables(class_node: ast.ClassDef, yaml_modules: set[str]) -> bool:
    """True when a class body itself defines every core mutable parser table.

    ``cryodaq.lab_profile`` owns its grammar in-package and is the sanctioned
    way to subclass a raw PyYAML loader; a body that just ``pass``es inherits
    the host's mutable state and must be rejected on construction.
    """

    assigned: set[str] = set()
    for statement in class_node.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id in _CORE_OWNED_TABLES:
                    if _bare_yaml_table_reference(statement.value, yaml_modules):
                        return False
                    assigned.add(target.id)
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id in _CORE_OWNED_TABLES
        ):
            if statement.value is not None and _bare_yaml_table_reference(statement.value, yaml_modules):
                return False
            assigned.add(statement.target.id)
    return _CORE_OWNED_TABLES.issubset(assigned)


def _local_loader_subclasses(
    tree: ast.Module, yaml_modules: set[str], yaml_functions: dict[str, str]
) -> dict[str, bool]:
    """Map local subclass name -> owns_core_tables, for every class that
    derives (directly or transitively) from a raw PyYAML loader class."""

    subclass_state: dict[str, bool] = {}
    for node in sorted(
        (c for c in ast.walk(tree) if isinstance(c, ast.ClassDef)),
        key=lambda item: (item.lineno, item.col_offset),
    ):
        derives_from_loader = False
        inherited_owned = False
        for base in node.bases:
            if (
                isinstance(base, ast.Attribute)
                and isinstance(base.value, ast.Name)
                and base.value.id in yaml_modules
                and base.attr in _LOADER_CLASSES
            ):
                derives_from_loader = True
            elif isinstance(base, ast.Name):
                if base.id in subclass_state:
                    derives_from_loader = True
                    if subclass_state[base.id]:
                        inherited_owned = True
                elif yaml_functions.get(base.id) in _LOADER_CLASSES:
                    derives_from_loader = True
        if derives_from_loader:
            subclass_state[node.name] = _class_owns_core_tables(node, yaml_modules) or inherited_owned
    return subclass_state


def _uses_owned_loader(call: ast.Call, names: set[str], modules: set[str]) -> bool:
    loader = next((keyword.value for keyword in call.keywords if keyword.arg == "Loader"), None)
    return (isinstance(loader, ast.Name) and loader.id in names) or (
        isinstance(loader, ast.Attribute)
        and isinstance(loader.value, ast.Name)
        and loader.value.id in modules
        and loader.attr == "OwnedSafeLoader"
    )


def _unsafe_yaml_calls(path: Path, root: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    yaml_modules: set[str] = set()
    yaml_functions: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yaml_modules.update(alias.asname or alias.name for alias in node.names if alias.name == "yaml")
        elif isinstance(node, ast.ImportFrom) and node.module == "yaml":
            yaml_functions.update(
                (alias.asname or alias.name, alias.name)
                for alias in node.names
                if alias.name in _CONVENIENCE_LOADERS | _EXPLICIT_LOADERS | _LOADER_CLASSES
            )

    owned_names, owned_modules = _owned_loader_names(tree)
    local_loader_subclasses = _local_loader_subclasses(tree, yaml_modules, yaml_functions)
    offenders: list[str] = []
    relative = path.relative_to(root).as_posix()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in yaml_modules
        ):
            api = node.func.attr
        elif isinstance(node.func, ast.Name):
            api = yaml_functions.get(node.func.id, "")
        else:
            continue

        if api in _CONVENIENCE_LOADERS or (
            api in _EXPLICIT_LOADERS and not _uses_owned_loader(node, owned_names, owned_modules)
        ):
            offenders.append(f"{relative}:{node.lineno}: PyYAML {api} bypasses cryodaq._owned_yaml.OwnedSafeLoader")
        elif api in _LOADER_CLASSES:
            offenders.append(
                f"{relative}:{node.lineno}: PyYAML {api} construction bypasses cryodaq._owned_yaml.OwnedSafeLoader"
            )
        elif (
            isinstance(node.func, ast.Name)
            and node.func.id in local_loader_subclasses
            and not local_loader_subclasses[node.func.id]
        ):
            offenders.append(
                f"{relative}:{node.lineno}: PyYAML {node.func.id} construction "
                "bypasses cryodaq._owned_yaml.OwnedSafeLoader"
            )
    return offenders


def test_cryodaq_modules_use_only_the_owned_yaml_loader() -> None:
    offenders = [
        offender for path in sorted(_SOURCE_ROOT.rglob("*.py")) for offender in _unsafe_yaml_calls(path, _SOURCE_ROOT)
    ]
    assert offenders == [], "\n" + "\n".join(offenders)


@pytest.mark.parametrize(
    "source",
    [
        "import yaml\nyaml.load('x')\n",
        "import yaml as _yaml\n_yaml.load('x')\n",
        "from yaml import load\nload('x')\n",
        "def parse():\n    import yaml\n    return yaml.load('x')\n",
        "import yaml\nyaml.load(\n    'x'\n)\n",
    ],
    ids=["module", "module-alias", "from-import", "function-local", "multiline-call"],
)
def test_guard_finds_every_required_import_and_call_shape(tmp_path: Path, source: str) -> None:
    path = tmp_path / "probe.py"
    path.write_text(source, encoding="utf-8")

    offenders = _unsafe_yaml_calls(path, tmp_path)

    assert offenders == [
        f"probe.py:{2 if not source.startswith('def ') else 3}: "
        "PyYAML load bypasses cryodaq._owned_yaml.OwnedSafeLoader"
    ]


def test_guard_accepts_explicit_owned_loader_and_its_subclass(tmp_path: Path) -> None:
    path = tmp_path / "probe.py"
    path.write_text(
        "from cryodaq._owned_yaml import OwnedSafeLoader\n"
        "import yaml\n"
        "LoaderAlias = OwnedSafeLoader\n"
        "class StrictLoader(LoaderAlias):\n"
        "    pass\n"
        "yaml.load('x', Loader=StrictLoader)\n",
        encoding="utf-8",
    )

    assert _unsafe_yaml_calls(path, tmp_path) == []


@pytest.mark.parametrize(
    "source",
    [
        """from cryodaq._owned_yaml import OwnedSafeLoader
import yaml
OwnedSafeLoader = yaml.UnsafeLoader
yaml.load("x", Loader=OwnedSafeLoader)
""",
        """from cryodaq._owned_yaml import OwnedSafeLoader
import yaml
LoaderAlias = OwnedSafeLoader
LoaderAlias = yaml.UnsafeLoader
yaml.load("x", Loader=LoaderAlias)
""",
        """import cryodaq._owned_yaml as owned
import yaml
owned = yaml
yaml.load("x", Loader=owned.OwnedSafeLoader)
""",
    ],
    ids=["imported-loader", "loader-alias", "module-alias"],
)
def test_guard_rejects_rebound_owned_loader_names(tmp_path: Path, source: str) -> None:
    path = tmp_path / "probe.py"
    path.write_text(source, encoding="utf-8")
    offenders = _unsafe_yaml_calls(path, tmp_path)
    assert len(offenders) == 1
    assert "PyYAML load bypasses cryodaq._owned_yaml.OwnedSafeLoader" in offenders[0]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import yaml\nyaml.SafeLoader('x')\n", "SafeLoader"),
        ("import yaml\nloader = yaml.UnsafeLoader('x')\n", "UnsafeLoader"),
        ("import yaml\nloader = yaml.FullLoader('x')\n", "FullLoader"),
        ("import yaml\nyaml.Loader('x').get_single_data()\n", "Loader"),
        ("from yaml import SafeLoader\nloader = SafeLoader('x')\n", "SafeLoader"),
        ("import yaml\nloader = yaml.BaseLoader('x')\n", "BaseLoader"),
        ("import yaml\nloader = yaml.CLoader('x')\n", "CLoader"),
        ("import yaml\nloader = yaml.CSafeLoader('x')\n", "CSafeLoader"),
        ("import yaml\nloader = yaml.CFullLoader('x')\n", "CFullLoader"),
        ("import yaml\nloader = yaml.CUnsafeLoader('x')\n", "CUnsafeLoader"),
        ("from yaml import CSafeLoader\nloader = CSafeLoader('x')\n", "CSafeLoader"),
    ],
    ids=[
        "module-attr",
        "module-attr-unsafe",
        "module-attr-full",
        "construct-and-parse",
        "from-import",
        "module-attr-base",
        "module-attr-cloader",
        "module-attr-csafe",
        "module-attr-cfull",
        "module-attr-cunsafe",
        "from-import-csafe",
    ],
)
def test_guard_finds_direct_loader_construction(tmp_path: Path, source: str, expected: str) -> None:
    path = tmp_path / "probe.py"
    path.write_text(source, encoding="utf-8")

    offenders = _unsafe_yaml_calls(path, tmp_path)

    assert offenders == [f"probe.py:2: PyYAML {expected} construction bypasses cryodaq._owned_yaml.OwnedSafeLoader"]


def test_guard_accepts_relative_import_of_owned_loader(tmp_path: Path) -> None:
    path = tmp_path / "probe.py"
    path.write_text(
        "from .._owned_yaml import OwnedSafeLoader as Loader\nimport yaml as _yaml\n_yaml.load('x', Loader=Loader)\n",
        encoding="utf-8",
    )

    assert _unsafe_yaml_calls(path, tmp_path) == []


@pytest.mark.parametrize(
    ("table", "source"),
    [
        (
            "yaml_constructors",
            """from cryodaq._owned_yaml import OwnedSafeLoader
import yaml
class Reattached(OwnedSafeLoader):
    yaml_constructors = yaml.SafeLoader.yaml_constructors
yaml.load('x', Loader=Reattached)
""",
        ),
        (
            "yaml_multi_constructors",
            """from cryodaq._owned_yaml import OwnedSafeLoader
import yaml
class Reattached(OwnedSafeLoader):
    yaml_multi_constructors = yaml.SafeLoader.yaml_multi_constructors
yaml.load('x', Loader=Reattached)
""",
        ),
        (
            "yaml_implicit_resolvers",
            """from cryodaq._owned_yaml import OwnedSafeLoader
import yaml
class Reattached(OwnedSafeLoader):
    yaml_implicit_resolvers = yaml.SafeLoader.yaml_implicit_resolvers
yaml.load('x', Loader=Reattached)
""",
        ),
        (
            "yaml_path_resolvers",
            """from cryodaq._owned_yaml import OwnedSafeLoader
import yaml
class Reattached(OwnedSafeLoader):
    yaml_path_resolvers = yaml.SafeLoader.yaml_path_resolvers
yaml.load('x', Loader=Reattached)
""",
        ),
        (
            "bool_values",
            """from cryodaq._owned_yaml import OwnedSafeLoader
import yaml
class Reattached(OwnedSafeLoader):
    bool_values = yaml.SafeLoader.bool_values
yaml.load('x', Loader=Reattached)
""",
        ),
        (
            "ESCAPE_REPLACEMENTS",
            """from cryodaq._owned_yaml import OwnedSafeLoader
import yaml
class Reattached(OwnedSafeLoader):
    ESCAPE_REPLACEMENTS = yaml.SafeLoader.ESCAPE_REPLACEMENTS
yaml.load('x', Loader=Reattached)
""",
        ),
        (
            "inf_value",
            """from cryodaq._owned_yaml import OwnedSafeLoader
import yaml
class Reattached(OwnedSafeLoader):
    inf_value = yaml.SafeLoader.inf_value
yaml.load('x', Loader=Reattached)
""",
        ),
    ],
    ids=[
        "constructors",
        "multi-constructors",
        "implicit-resolvers",
        "path-resolvers",
        "bool-values",
        "escape-replacements",
        "inf-value",
    ],
)
def test_guard_rejects_subclass_reattaching_owned_tables(tmp_path: Path, table: str, source: str) -> None:
    path = tmp_path / "probe.py"
    path.write_text(source, encoding="utf-8")

    offenders = _unsafe_yaml_calls(path, tmp_path)
    assert len(offenders) == 1
    assert "PyYAML load bypasses cryodaq._owned_yaml.OwnedSafeLoader" in offenders[0]


@pytest.mark.parametrize(
    "source",
    [
        """from cryodaq._owned_yaml import OwnedSafeLoader
import yaml
class Reattached(OwnedSafeLoader):
    pass
Reattached.yaml_constructors = yaml.SafeLoader.yaml_constructors
yaml.load('x', Loader=Reattached)
""",
        """from cryodaq._owned_yaml import OwnedSafeLoader
import yaml
class Reattached(OwnedSafeLoader):
    pass
Reattached.ESCAPE_REPLACEMENTS = yaml.SafeLoader.ESCAPE_REPLACEMENTS
yaml.load('x', Loader=Reattached)
""",
    ],
    ids=["constructors", "escape-replacements"],
)
def test_guard_rejects_post_definition_table_reattachment(tmp_path: Path, source: str) -> None:
    """A table rebound AFTER the class body reconnects the host's mutable state.

    The class-body scan cannot see it: `Reattached.yaml_constructors = ...` is
    an attribute assignment outside the class, and without tracking it the
    subclass name stays trusted while the host's table comes back.
    """

    path = tmp_path / "probe.py"
    path.write_text(source, encoding="utf-8")

    offenders = _unsafe_yaml_calls(path, tmp_path)
    assert len(offenders) == 1
    assert "PyYAML load bypasses cryodaq._owned_yaml.OwnedSafeLoader" in offenders[0]


@pytest.mark.parametrize(
    "source",
    [
        "import yaml\nclass LocalLoader(yaml.SafeLoader):\n    pass\nLocalLoader('x: 1').get_single_data()\n",
        "import yaml as _yaml\n"
        "class LocalLoader(_yaml.UnsafeLoader):\n"
        "    pass\n"
        "LocalLoader('x: 1').get_single_data()\n",
        "from yaml import SafeLoader\n"
        "class LocalLoader(SafeLoader):\n"
        "    pass\n"
        "LocalLoader('x: 1').get_single_data()\n",
    ],
    ids=["module-attr", "module-alias", "from-import"],
)
def test_guard_rejects_direct_construction_of_local_pyyaml_loader_subclass(tmp_path: Path, source: str) -> None:
    """A locally-declared subclass of a raw PyYAML loader inherits its mutable
    parser state and must not be constructed directly."""

    path = tmp_path / "probe.py"
    path.write_text(source, encoding="utf-8")

    offenders = _unsafe_yaml_calls(path, tmp_path)
    assert len(offenders) == 1
    assert "PyYAML LocalLoader construction bypasses cryodaq._owned_yaml.OwnedSafeLoader" in offenders[0]


def test_guard_accepts_local_subclass_that_owns_its_core_tables(tmp_path: Path) -> None:
    """The `cryodaq.lab_profile` pattern: an in-package subclass that defines its
    own grammar is the sanctioned alternative, not a bypass."""

    path = tmp_path / "probe.py"
    path.write_text(
        "import yaml\n"
        "class OwnedGrammarLoader(yaml.SafeLoader):\n"
        "    yaml_constructors = {'tag:yaml.org,2002:str': lambda l, n: l.construct_scalar(n)}\n"
        "    yaml_multi_constructors = {}\n"
        "    yaml_implicit_resolvers = {}\n"
        "    yaml_path_resolvers = {}\n"
        "    bool_values = {}\n"
        "OwnedGrammarLoader('x: 1').get_single_data()\n",
        encoding="utf-8",
    )

    assert _unsafe_yaml_calls(path, tmp_path) == []
