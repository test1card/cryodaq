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
_EXPLICIT_LOADERS = {"load", "load_all"}


def _owned_loader_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    modules: set[str] = set()
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
                names.add(node.name)
            else:
                names.discard(node.name)
                modules.discard(node.name)
    return names, modules


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
                if alias.name in _CONVENIENCE_LOADERS | _EXPLICIT_LOADERS
            )

    owned_names, owned_modules = _owned_loader_names(tree)
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


def test_guard_accepts_relative_import_of_owned_loader(tmp_path: Path) -> None:
    path = tmp_path / "probe.py"
    path.write_text(
        "from .._owned_yaml import OwnedSafeLoader as Loader\nimport yaml as _yaml\n_yaml.load('x', Loader=Loader)\n",
        encoding="utf-8",
    )

    assert _unsafe_yaml_calls(path, tmp_path) == []
