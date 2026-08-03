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
ALLOWED_CRYODAQ_MODULE = "cryodaq.drivers.registry"
ALLOWED_REGISTRY_SYMBOLS = frozenset({"BUILTIN_DRIVER_SPECS", "DriverAuthority", "DriverCapability"})
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


def _import_violations(source: str, *, label: str) -> list[str]:
    """List every import in one source text that crosses the downstream boundary.

    The package may import only stdlib modules, ``yaml``, and — by name — the
    three inert public symbols of ``cryodaq.drivers.registry``.  A bare
    ``import cryodaq.drivers.registry`` or a from-import of any other registry
    symbol (for example ``construct_driver``) is a boundary violation even
    though the module name matches.
    """

    stdlib = set(sys.stdlib_module_names)
    violations: list[str] = []
    for node in ast.walk(ast.parse(source, filename=label)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in stdlib or alias.name == "yaml":
                    continue
                violations.append(f"{label}: bare import of {alias.name!r} crosses the downstream boundary")
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0:
                continue  # in-package relative imports are inside the boundary
            module = node.module or ""
            root = module.split(".", 1)[0]
            if root in stdlib or root == "yaml":
                continue
            if module != ALLOWED_CRYODAQ_MODULE:
                violations.append(f"{label}: import from {module!r} crosses the downstream boundary")
                continue
            for alias in node.names:
                if alias.name not in ALLOWED_REGISTRY_SYMBOLS:
                    violations.append(
                        f"{label}: registry symbol {alias.name!r} is not one of "
                        f"{sorted(ALLOWED_REGISTRY_SYMBOLS)}; the package may not hold driver-construction authority"
                    )
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
        "import cryodaq.drivers.registry",
        "from cryodaq.drivers import registry",
        "from cryodaq.drivers.registry import BUILTIN_DRIVER_SPECS, validate_instrument_entry",
        "from cryodaq.engine import main",
        "import cryodaq",
    ),
)
def test_import_guard_rejects_authority_bearing_symbols(hostile: str) -> None:
    assert _import_violations(hostile, label="hostile.py") != []


@pytest.mark.parametrize(
    "allowed",
    (
        "from cryodaq.drivers.registry import BUILTIN_DRIVER_SPECS",
        "from cryodaq.drivers.registry import BUILTIN_DRIVER_SPECS, DriverAuthority, DriverCapability",
        "import os\nimport sys",
        "import yaml",
        "from .schema import LabProfileError",
    ),
)
def test_import_guard_accepts_inert_imports(allowed: str) -> None:
    assert _import_violations(allowed, label="allowed.py") == []


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
