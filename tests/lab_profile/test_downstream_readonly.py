"""Proof that the lab_profile package stays downstream, read-only, and inert."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
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
    # The inert module is the ONLY cryodaq module the package may import:
    # reflection against these symbols lands in capability_metadata, where no
    # constructor or loader exists.  The authority-bearing registry is not
    # allowlisted at all — importing the package must never load it.
    "cryodaq.drivers.capability_metadata": frozenset(
        {"BUILTIN_DRIVER_METADATA", "DriverAuthority", "DriverCapability", "DriverTypeMetadata"}
    ),
}
REFLECTION_MODULES = ("inspect", "gc", "builtins")
REFLECTION_CALLS = frozenset({"getattr", "eval", "exec", "vars", "dir", "globals", "locals", "compile"})
# *** DENY BY DEFAULT. ***  Allowing "any stdlib module" was not a boundary:
# pkgutil.resolve_name("cryodaq.drivers.registry:construct_driver"),
# pydoc.locate and runpy.run_module each return the exact registry constructor
# while naming no dunder and no reflection module.  Enumerating those three
# would have been the fifth spelling list in five rounds, so instead only the
# modules the package actually imports are allowed, and every other module in
# the stdlib -- including every future module-loading helper -- is denied
# without needing to be named.  Measured from the package source; see
# test_every_allowlist_entry_is_load_bearing, which fails if an entry here is
# not required by the package as it actually stands.
ALLOWED_STDLIB_MODULES = frozenset(
    {"__future__", "dataclasses", "enum", "io", "os", "pathlib", "sys", "typing", "unicodedata"}
)
# Every route out of Python to a module object THROUGH THE INTERPRETER -- its
# builtins, function globals, the class hierarchy, import loaders -- must NAME a
# dunder, so denying the vocabulary closes that class in one rule where
# enumerating spellings did not terminate: four consecutive review rounds each
# produced a fresh bypass of the previous round's list.  This does NOT cover
# module-loading helpers reached by ordinary import -- ALLOWED_STDLIB_MODULES
# covers those, and claiming otherwise is precisely the overreach that round 9
# refuted.  ``__future__`` is deliberately absent here: it is an import, so it
# is load-bearing in ALLOWED_STDLIB_MODULES instead.  Every entry belongs to
# exactly one allowlist -- the one where deleting it turns the package scan red.
ALLOWED_DUNDERS = frozenset({"__all__", "__init__", "__main__", "__name__", "__post_init__", "__setattr__"})
# Deny-by-default capability policy.  A read-only artifact must not be able to
# write: open(..., "w"), Path.unlink, os.replace and shutil.rmtree are all
# invisible to a reflection-only filter, and an import-time write is invisible
# to the incumbent-snapshot test as well, because the package is imported
# before that snapshot is taken.  So calls are allowlisted rather than
# denylisted -- the loader's bounded READ is permitted and nothing else is.
# Only names that CROSS the boundary need an entry.  The package's own classes
# and helpers are in-boundary (see ``local_names``) and deliberately absent.
ALLOWED_CALL_NAMES = frozenset(
    {
        "Path",
        "SystemExit",
        "any",
        "dataclass",
        "enumerate",
        "field",
        "frozenset",
        "isinstance",
        "len",
        "list",
        "print",
        "set",
        "sorted",
        "str",
        "super",
        "tuple",
        "type",
    }
)
ALLOWED_METHOD_NAMES = frozenset(
    {
        "ConstructorError",
        "__init__",
        "__setattr__",
        "add",
        "append",
        "category",
        "check_event",
        "compose_node",
        "construct_object",
        "decode",
        "encode",
        "get",
        "isfile",
        "isspace",
        "join",
        "load",
        "lower",
        "normalize",
        "open",
        "peek_event",
        "read",
        "reconfigure",
        "startswith",
        "strip",
    }
)
_DUNDER = re.compile(r"^__[A-Za-z0-9_]+__$")


def _denied_dunder(name: str) -> bool:
    return bool(_DUNDER.match(name)) and name not in ALLOWED_DUNDERS


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


def _resolve_import(module: str, level: int, *, base: str) -> str:
    """Resolve one (possibly relative) import against the importing file's package."""

    if level == 0:
        return module
    parts = base.split(".")
    if level > len(parts):
        return ""  # escapes the top-level package: unresolvable, hence a violation
    prefix = ".".join(parts[: len(parts) - level + 1])
    return f"{prefix}.{module}" if module else prefix


def _import_violations(source: str, *, label: str, base: str = PACKAGE_MODULE) -> list[str]:
    """List every import in one source text that crosses the downstream boundary.

    Everything is DENIED BY DEFAULT and the allowlists are measured from the
    package's own source.  The package may import only the modules in
    ``ALLOWED_STDLIB_MODULES``, ``yaml``, its own modules, and the inert symbols
    of ``cryodaq.drivers.capability_metadata`` — a deliberately authority-free
    module, so reflection against them lands where no constructor exists.  The
    authority-bearing registry is not allowlisted at all: ``BUILTIN_DRIVER_SPECS``
    values carry public ``factory`` constructors, and even the inert projection
    is imported from its authoritative inert home.  Relative imports are
    resolved against the importing file's actual package (nested modules
    included).

    Three independent rules, because three independent classes defeated the
    earlier versions of this scan:

    1. **Modules.**  ``ALLOWED_STDLIB_MODULES``, not "any stdlib module".  The
       blanket allowance let ``pkgutil.resolve_name``, ``pydoc.locate`` and
       ``runpy.run_module`` return the registry constructor while naming no
       dunder and no reflection module.
    2. **Reflection.**  Any dunder outside ``ALLOWED_DUNDERS`` is a violation
       wherever it is named — attribute, bare name, string constant (covering
       ``x["__builtins__"]`` and ``getattr(x, "__globals__")``), or ``def``,
       since a module-level ``__getattr__`` is itself an interpreter hook.
    3. **Capability.**  Calls are allowlisted, not denylisted, so a read-only
       artifact cannot write.  ``open(..., "w")``, ``Path.unlink`` and
       ``os.replace`` are invisible to a reflection-only filter, and an
       import-time write is invisible to the incumbent-snapshot test too,
       because the package is imported before that snapshot is taken.

    Each rule is enumeration-free in the direction that matters: new module
    loaders, new dunder spellings and new write APIs are all denied without
    being named.  ``test_every_allowlist_entry_is_load_bearing`` proves no entry
    is padding, so the allowlists cannot quietly widen either.

    What this is NOT: a sandbox.  It is a scan of source text the package
    actually ships, so it constrains what this package can be written to do,
    not what arbitrary code loaded at runtime could do.  That is the honest
    claim, and it is the one the lab needs -- it keeps driver-construction
    authority from being wired into a downstream config reader by accident or
    by a later edit.
    """

    tree = ast.parse(source, filename=label)
    # Names the file itself defines, or imports from inside the boundary, are
    # in-boundary: the same scan is applied to their own source, so they need no
    # capability allowlist entry.  Only names crossing the boundary do.
    local_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local_names.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            origin = _resolve_import(node.module or "", node.level, base=base)
            if origin == PACKAGE_MODULE or origin.startswith(f"{PACKAGE_MODULE}.") or origin in ALLOWED_CRYODAQ_IMPORTS:
                local_names.update(alias.asname or alias.name for alias in node.names)

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if alias.name == "importlib" or alias.name.startswith("importlib."):
                    violations.append(f"{label}: importing {alias.name!r} enables dynamic module loading")
                    continue
                if root in REFLECTION_MODULES:
                    violations.append(f"{label}: importing {alias.name!r} enables reflection past the boundary")
                    continue
                if root in ALLOWED_STDLIB_MODULES or alias.name == "yaml":
                    continue
                if alias.name == PACKAGE_MODULE or alias.name.startswith(f"{PACKAGE_MODULE}."):
                    continue
                violations.append(f"{label}: bare import of {alias.name!r} crosses the downstream boundary")
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_import(node.module or "", node.level, base=base)
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
            if root in ALLOWED_STDLIB_MODULES or root == "yaml":
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
        elif isinstance(node, ast.Name) and node.id == "__builtins__":
            violations.append(f"{label}: __builtins__ access bypasses the static import boundary")
        elif isinstance(node, ast.Attribute) and _denied_dunder(node.attr):
            violations.append(f"{label}: {node.attr} attribute access exposes interpreter internals past the boundary")
        elif isinstance(node, ast.Name) and _denied_dunder(node.id):
            violations.append(f"{label}: {node.id} exposes interpreter internals past the boundary")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _denied_dunder(node.value):
            # Catches the subscript and getattr spellings -- ``x["__builtins__"]``
            # and ``getattr(x, "__globals__")`` name their dunder as a string.
            violations.append(f"{label}: the name {node.value!r} reaches interpreter internals past the boundary")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _denied_dunder(node.name):
            # Defining a dunder is a reflection hook too: a module-level
            # __getattr__ resolves arbitrary attribute names at import time.
            violations.append(f"{label}: defining {node.name} installs an interpreter hook past the boundary")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "__import__":
                violations.append(f"{label}: __import__ bypasses the static import boundary")
            elif isinstance(func, ast.Attribute) and func.attr == "import_module":
                violations.append(f"{label}: import_module bypasses the static import boundary")
            elif isinstance(func, ast.Name) and func.id in REFLECTION_CALLS:
                violations.append(f"{label}: {func.id}() bypasses the static import boundary")
            elif isinstance(func, ast.Name) and func.id not in ALLOWED_CALL_NAMES | local_names:
                violations.append(f"{label}: {func.id}() is not an allowlisted capability for a read-only artifact")
            elif isinstance(func, ast.Attribute) and func.attr not in ALLOWED_METHOD_NAMES:
                violations.append(f"{label}: .{func.attr}() is not an allowlisted capability for a read-only artifact")
    return violations


def _scan_package(base_dir: Path, *, package_module: str) -> list[str]:
    """Scan every Python module under a package directory, recursively."""

    violations: list[str] = []
    for path in sorted(base_dir.rglob("*.py")):
        relative_parent = path.parent.relative_to(base_dir)
        file_package = package_module
        if str(relative_parent) != ".":
            file_package = f"{package_module}.{'.'.join(relative_parent.parts)}"
        violations.extend(_import_violations(path.read_text(encoding="utf-8"), label=path.name, base=file_package))
    return violations


def test_import_closure_stays_downstream() -> None:
    assert _scan_package(PACKAGE_DIR, package_module=PACKAGE_MODULE) == []


@pytest.mark.parametrize(
    ("allowlist", "entry"),
    [
        (name, entry)
        for name, values in (
            ("ALLOWED_STDLIB_MODULES", ALLOWED_STDLIB_MODULES),
            ("ALLOWED_DUNDERS", ALLOWED_DUNDERS),
            ("ALLOWED_CALL_NAMES", ALLOWED_CALL_NAMES),
            ("ALLOWED_METHOD_NAMES", ALLOWED_METHOD_NAMES),
        )
        for entry in sorted(values)
    ],
)
def test_every_allowlist_entry_is_load_bearing(monkeypatch: pytest.MonkeyPatch, allowlist: str, entry: str) -> None:
    """Deleting any single allowlisted item must turn the real package scan red.

    An entry whose removal changes nothing is padding: it silently widens the
    boundary without being required by the package as it stands, so the
    deny-by-default claim would be weaker than it reads.  This is asserted
    mechanically rather than argued, because the previous round's "no entry is
    padding" claim was generalised from a hand-picked subset and two entries
    were in fact unused.
    """

    module = __import__(__name__.rsplit(".", 1)[0] + ".test_downstream_readonly", fromlist=["x"])
    monkeypatch.setattr(module, allowlist, getattr(module, allowlist) - {entry})
    assert _scan_package(PACKAGE_DIR, package_module=PACKAGE_MODULE) != [], (
        f"{allowlist} entry {entry!r} is not required by the package source"
    )


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
        "from cryodaq.drivers.registry import BUILTIN_DRIVER_METADATA",
        "import sys\ngetattr(sys, 'mod' + 'ules')['cryodaq.drivers.registry']",
        "getattr(sys, 'modules')",
        "eval('1 + 1')",
        "exec('pass')",
        "vars(sys)",
        "dir(sys)",
        "globals()",
        "locals()",
        "compile('1', 'x', 'eval')",
        "import builtins\nbuiltins.__import__('cryodaq.drivers.registry')",
        "import builtins\nbuiltins.getattr(sys, 'modules')",
        "from builtins import __import__ as load",
        "from builtins import getattr",
        "__builtins__['getattr']",
        "__builtins__.getattr",
        # Indirect reflection through an ALLOWED symbol's dunders.  The first is
        # the round-8 review finding; the rest are siblings found by hand once
        # the class was recognised, and every one of them defeated the previous
        # spelling-based scan.
        'DriverTypeMetadata.__init__.__globals__["__builtins__"]["__import__"]'
        '("cryodaq.drivers.registry", fromlist=("construct_driver",)).construct_driver',
        'DriverTypeMetadata.__init__.__globals__["construct_driver"]',
        "DriverTypeMetadata.__class__.__mro__[0].__subclasses__()",
        "DriverTypeMetadata.__module__",
        "__spec__.loader.load_module('cryodaq.drivers.registry')",
        "__loader__.load_module('cryodaq.drivers.registry')",
        "type(DriverTypeMetadata).__bases__",
        "getattr(DriverTypeMetadata, '__globals__')",
        "DriverTypeMetadata.__init__.__func__",
        "DriverTypeMetadata.__dict__",
        # Round 9: stdlib module-loading helpers.  None of these names a dunder
        # or a reflection module, and each returns the exact registry
        # constructor -- the blanket "any stdlib module" allowance was the hole.
        "import pkgutil\nactivate = pkgutil.resolve_name('cryodaq.drivers.registry:construct_driver')",
        "import pydoc\npydoc.locate('cryodaq.drivers.registry.construct_driver')",
        "import runpy\nrunpy.run_module('cryodaq.drivers.registry')",
        "from pkgutil import resolve_name",
        "import shutil",
        "import subprocess",
        # Round 9: write capability. A read-only artifact that can write can
        # corrupt the incumbent config, and an import-time write is invisible to
        # the incumbent-snapshot test because the package is imported first.
        "open('config/safety.yaml', 'w').write('disabled: true')",
        "from pathlib import Path\nPath('config/safety.yaml').unlink()",
        "import os\nos.replace('config/safety.yaml', 'config/safety.bak')",
        "from pathlib import Path\nPath('config/safety.yaml').write_text('disabled: true')",
        "import os\nos.remove('config/safety.yaml')",
        # Round 9: defining a module-level __getattr__ is an interpreter hook.
        "def __getattr__(name):\n    return None",
    ),
)
def test_import_guard_rejects_authority_bearing_symbols(hostile: str) -> None:
    assert _import_violations(hostile, label="hostile.py") != []


@pytest.mark.parametrize(
    "allowed",
    (
        "from cryodaq.drivers.capability_metadata import BUILTIN_DRIVER_METADATA",
        "from cryodaq.drivers.capability_metadata import DriverAuthority, DriverCapability",
        "from cryodaq.drivers.capability_metadata import DriverTypeMetadata",
        "import os\nimport sys",
        # ``raise SystemExit(0)`` is what __main__.py actually does.  Under a
        # deny-by-default capability policy a call the package never makes is
        # denied by design, so the accepted corpus tracks its real idioms.
        "import sys\nraise SystemExit(0)",
        "import yaml",
        "from .schema import LabProfileError",
        "from . import schema",
    ),
)
def test_import_guard_accepts_inert_imports(allowed: str) -> None:
    assert _import_violations(allowed, label="allowed.py") == []


def test_package_never_names_the_authority_bearing_registry_mapping() -> None:
    """BUILTIN_DRIVER_SPECS values carry public factories; the package must not touch them."""

    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        assert "BUILTIN_DRIVER_SPECS" not in path.read_text(encoding="utf-8"), path.name


def test_importing_the_package_never_loads_the_authority_bearing_registry() -> None:
    """import cryodaq.lab_profile must not put cryodaq.drivers.registry in sys.modules."""

    code = (
        "import sys\n"
        "import cryodaq.lab_profile\n"
        "assert 'cryodaq.drivers.registry' not in sys.modules, (\n"
        "    'lab_profile must not load the authority-bearing registry')\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_nested_modules_are_scanned_with_their_own_package(tmp_path: Path) -> None:
    """A hostile file in a nested subpackage must produce violations."""

    nested = tmp_path / "pkg" / "sub"
    nested.mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (nested / "__init__.py").write_text("", encoding="utf-8")
    (nested / "evil.py").write_text("from ..drivers.registry import construct_driver\n", encoding="utf-8")
    assert _scan_package(tmp_path / "pkg", package_module="pkg") != []


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
