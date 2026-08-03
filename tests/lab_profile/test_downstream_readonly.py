"""Proof that the lab_profile package stays downstream, read-only, and inert."""

from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path

import pytest

import cryodaq.lab_profile as lab_profile_package
from cryodaq.drivers.registry import BUILTIN_DRIVER_SPECS
from cryodaq.lab_profile import LabProfileError, parse_lab_profile
from tests.lab_profile.test_boundary_rejection import HOSTILE_TEXTS

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "cryodaq" / "lab_profile"
PACKAGE_MODULE = "cryodaq.lab_profile"
ALLOWED_CRYODAQ_IMPORTS: dict[str, frozenset[str]] = {
    # The inert module: reflection against these symbols lands in
    # capability_metadata, where no constructor or loader exists.
    "cryodaq.drivers.capability_metadata": frozenset({"DriverAuthority", "DriverCapability", "DriverTypeMetadata"}),
    # The registry is authority-bearing; only the inert projection may be
    # imported from it, never the enums (whose inert home is above) and never
    # BUILTIN_DRIVER_SPECS (whose values carry public factories).
    "cryodaq.drivers.registry": frozenset({"BUILTIN_DRIVER_METADATA"}),
}
REFLECTION_MODULES = ("inspect", "gc")
INCUMBENT_CONFIG_FILES = (
    "config/safety.yaml",
    "config/interlocks.yaml",
    "config/alarms_v3.yaml",
    "config/instruments.yaml",
    "config/channel_descriptors.yaml",
)

_VALID_TEXT = """\
schema_version: 1
lab:
  lab_id: readonly-lab
  display_name: Readonly Lab
instruments:
  - type: lakeshore_218s
    name: LS1
questions: []
"""


def _resolve_import(module: str, level: int) -> str:
    """Resolve one (possibly relative) import to its absolute module name."""

    if level == 0:
        return module
    parts = PACKAGE_MODULE.split(".")
    if level > len(parts):
        return ""  # escapes the top-level package: unresolvable, hence a violation
    base = ".".join(parts[: len(parts) - level + 1])
    return f"{base}.{module}" if module else base


def _import_violations(source: str, *, label: str) -> list[str]:
    """List every import in one source text that crosses the downstream boundary.

    The package may import only stdlib modules, ``yaml``, its own modules, and
    a per-module allowlist of inert cryodaq symbols: the enums and metadata
    from ``cryodaq.drivers.capability_metadata`` (a deliberately authority-free
    module, so reflection against them lands where no constructor exists) and
    the factory-free ``BUILTIN_DRIVER_METADATA`` projection from
    ``cryodaq.drivers.registry``.  ``BUILTIN_DRIVER_SPECS`` is deliberately NOT
    allowlisted: its values carry public ``factory`` constructors.  Relative
    imports are resolved before the check so ``from ..drivers.registry import
    construct_driver`` cannot slip past as an unexamined relative import, and
    dynamic or reflective access (``importlib``/``import_module``,
    ``__import__``, ``.modules`` access, ``inspect``/``gc``) is a violation
    because it bypasses static examination entirely.
    """

    stdlib = set(sys.stdlib_module_names)
    violations: list[str] = []
    for node in ast.walk(ast.parse(source, filename=label)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if alias.name == "importlib" or alias.name.startswith("importlib."):
                    violations.append(f"{label}: importing {alias.name!r} enables dynamic module loading")
                    continue
                if root in REFLECTION_MODULES:
                    violations.append(f"{label}: importing {alias.name!r} enables reflection past the boundary")
                    continue
                if root in stdlib or alias.name == "yaml":
                    continue
                if alias.name == PACKAGE_MODULE or alias.name.startswith(f"{PACKAGE_MODULE}."):
                    continue
                violations.append(f"{label}: bare import of {alias.name!r} crosses the downstream boundary")
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_import(node.module or "", node.level)
            root = module.split(".", 1)[0] if module else ""
            if module == "importlib" or module.startswith("importlib."):
                violations.append(f"{label}: importing from {module!r} enables dynamic module loading")
                continue
            if root in REFLECTION_MODULES:
                violations.append(f"{label}: importing from {module!r} enables reflection past the boundary")
                continue
            if module == "sys" and any(alias.name == "modules" for alias in node.names):
                violations.append(f"{label}: importing sys.modules by name bypasses the static import boundary")
                continue
            if root in stdlib or root == "yaml":
                continue
            if module == PACKAGE_MODULE or module.startswith(f"{PACKAGE_MODULE}."):
                continue  # in-package imports are inside the boundary
            allowed_symbols = ALLOWED_CRYODAQ_IMPORTS.get(module)
            if allowed_symbols is None:
                violations.append(
                    f"{label}: import from {(node.module or '.')!r} (resolves to {module!r}) "
                    "crosses the downstream boundary"
                )
                continue
            for alias in node.names:
                if alias.name not in allowed_symbols:
                    violations.append(
                        f"{label}: symbol {alias.name!r} from {module!r} is not allowlisted "
                        f"(allowed: {sorted(allowed_symbols)}); the package may not hold "
                        "driver-construction authority"
                    )
        elif isinstance(node, ast.Attribute) and node.attr == "modules":
            violations.append(f"{label}: .modules access bypasses the static import boundary")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "__import__":
                violations.append(f"{label}: __import__ bypasses the static import boundary")
            elif isinstance(func, ast.Attribute) and func.attr == "import_module":
                violations.append(f"{label}: import_module bypasses the static import boundary")
    return violations


def test_import_closure_stays_downstream() -> None:
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        violations = _import_violations(path.read_text(encoding="utf-8"), label=path.name)
        assert violations == []


@pytest.mark.parametrize(
    "hostile",
    (
        "from cryodaq.drivers.registry import construct_driver as activate",
        "from cryodaq.drivers.registry import construct_driver",
        "from cryodaq.drivers.registry import BUILTIN_DRIVER_SPECS",
        "import cryodaq.drivers.registry",
        "from cryodaq.drivers import registry",
        "from cryodaq.drivers.registry import BUILTIN_DRIVER_METADATA, validate_instrument_entry",
        "from cryodaq.engine import main",
        "import cryodaq",
        "from ..drivers.registry import construct_driver",
        "from ..drivers.registry import BUILTIN_DRIVER_SPECS",
        "from ..drivers import registry",
        "from ...drivers.registry import construct_driver",
        "from .. import drivers",
        "import importlib\nimportlib.import_module('cryodaq.drivers.registry')",
        "from importlib import import_module",
        "__import__('cryodaq.drivers.registry')",
        "import sys\nsys.modules['cryodaq.drivers.registry']",
        "import sys as system\nsystem.modules['cryodaq.drivers.registry']",
        "from sys import modules\nmodules['cryodaq.drivers.registry']",
        "import sys\nmods = sys.modules\nmods['cryodaq.drivers.registry']",
        "import inspect\ninspect.getmodule(DriverAuthority)",
        "from inspect import getmodule",
        "import gc\ngc.get_objects()",
        "from cryodaq.drivers.registry import DriverAuthority",
        "from cryodaq.drivers.registry import DriverCapability",
    ),
)
def test_import_guard_rejects_authority_bearing_symbols(hostile: str) -> None:
    assert _import_violations(hostile, label="hostile.py") != []


@pytest.mark.parametrize(
    "allowed",
    (
        "from cryodaq.drivers.registry import BUILTIN_DRIVER_METADATA",
        "from cryodaq.drivers.capability_metadata import DriverAuthority, DriverCapability",
        "from cryodaq.drivers.capability_metadata import DriverTypeMetadata",
        "import os\nimport sys",
        "import sys\nsys.exit(0)",
        "import yaml",
        "from .schema import LabProfileError",
        "from . import schema",
    ),
)
def test_import_guard_accepts_inert_imports(allowed: str) -> None:
    assert _import_violations(allowed, label="allowed.py") == []


def test_package_never_names_the_authority_bearing_registry_mapping() -> None:
    """BUILTIN_DRIVER_SPECS values carry public factories; the package must not touch them."""

    for path in sorted(PACKAGE_DIR.glob("*.py")):
        assert "BUILTIN_DRIVER_SPECS" not in path.read_text(encoding="utf-8"), path.name


def test_driver_metadata_projection_is_inert_and_exact() -> None:
    from cryodaq.drivers.registry import BUILTIN_DRIVER_METADATA, BUILTIN_DRIVER_SPECS

    assert sorted(BUILTIN_DRIVER_METADATA) == sorted(BUILTIN_DRIVER_SPECS)
    for type_name, metadata in BUILTIN_DRIVER_METADATA.items():
        spec = BUILTIN_DRIVER_SPECS[type_name]
        assert metadata.type_name == spec.type_name
        assert metadata.authority is spec.authority
        assert metadata.capabilities == spec.capabilities
        for authority_bearing in ("factory", "normalizer", "module", "class_name", "config_fields"):
            assert not hasattr(metadata, authority_bearing), authority_bearing


def _incumbent_snapshot() -> tuple[object, dict[str, str]]:
    registry_state = (
        sorted(BUILTIN_DRIVER_SPECS),
        {key: (spec.authority, spec.capabilities) for key, spec in BUILTIN_DRIVER_SPECS.items()},
    )
    config_hashes = {
        name: hashlib.sha256((REPO_ROOT / name).read_bytes()).hexdigest() for name in INCUMBENT_CONFIG_FILES
    }
    return registry_state, config_hashes


def test_hostile_corpus_leaves_incumbent_state_untouched() -> None:
    before = _incumbent_snapshot()
    for text in HOSTILE_TEXTS:
        with pytest.raises(LabProfileError):
            parse_lab_profile(text)
    assert _incumbent_snapshot() == before


def test_package_grants_no_authority_objects() -> None:
    forbidden_prefixes = ("construct_", "connect", "open", "send", "write")
    for name in dir(lab_profile_package):
        assert not name.startswith(forbidden_prefixes), name
    profile = parse_lab_profile(_VALID_TEXT)
    assert profile.grants_control_authority is False
    assert profile.capabilities.actuation_supported is False
    assert profile.capabilities.grants_control_authority is False
