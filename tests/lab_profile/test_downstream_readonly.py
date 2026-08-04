"""The lab_profile downstream boundary: what is proved, and what is out of scope.

*** THE THREAT MODEL IS EXPLICIT. READ THIS BEFORE ADDING A GUARD HERE. ***

**In scope, and load-bearing.** A lab profile is data an operator may receive
from anyone.  Validating one must not load the driver registry, construct a
driver, acquire hardware authority, grant actuation, or alter any incumbent
state.  This must hold against hostile DATA and against ordinary behaviour of
the host process and its libraries -- including a host that has legitimately
called ``yaml.SafeLoader.add_constructor(...)``.  That last case was not
hypothetical: it is the defect fixed in ``loader.py``, where a shared mutable
constructor table let a third party decide what a lab profile executes.

The proof of this is the RUNTIME EFFECT PROBE at the bottom of this file.  It
runs the package and the documented CLI in a throwaway checkout and measures
what they DO -- every file hash, the environment, sys.path, the working
directory, umask, scheduling state, and process/filesystem/socket capabilities
observed through an audit hook.  Each dimension has a positive control that is
verified to report it.  Measuring effects is indifferent to how code is
spelled, which is why it is the load-bearing artifact.

**Out of scope: a hostile committer.** Guards here cannot bind someone who can
land arbitrary code in ``src/cryodaq/lab_profile/``.  Such a committer edits
this file in the same commit, or writes code that detects the probe harness.
The controls for that are review and branch protection, not a test.
``docs/OPEN_CELLS.md`` line 112 (OC-035) already ratifies this -- the checkpoint
"does not resist a malicious default-branch commit" -- and the rubric at lines
30-36 makes ordinary malicious-only residuals NONBLOCKING.

**What the static scan below is, therefore.** A decidable STRUCTURAL LINT, not
a proof.  It is exact about imports and the reflection/dunder vocabulary, and
merely indicative about call spellings, which aliasing defeats by construction.
Its job is to catch ACCIDENTAL coupling -- a later edit wiring driver authority
into a config reader without noticing -- which is the failure that actually
happens.  It is deliberately NOT an interprocedural dataflow analyser; an
earlier version grew toward one over nine review rounds without converging,
because the property it was claiming is undecidable over full Python.
``_OUT_OF_SCOPE_FOR_STATIC_LINT`` records what was considered and consciously
left to the effect probe and to review.

Do not restore the provenance/receiver/alias machinery here.  If a real escape
is found, close it in the EFFECT probe, where it can be measured.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import os
import re
import shutil
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
    # Measured, not assumed: DriverTypeMetadata was in this set and no
    # package source imports it, so its removal changed nothing -- padding
    # that silently widened the boundary.  test_every_symbol_allowance_is_load_bearing
    # now fails if any entry here stops being required.
    "cryodaq.drivers.capability_metadata": frozenset(
        {"BUILTIN_DRIVER_METADATA", "DriverAuthority", "DriverCapability"}
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

# Builtins that INVOKE a callable argument.  `isinstance` and `print` merely
# receive theirs, so passing a module attribute to them is an ordinary
# argument rather than a capability handover.


# The only foreign base classes the package needs.  A base can select an
# INHERITED metaclass that runs at class creation, so the set is measured
# rather than left open.


_DUNDER = re.compile(r"^__[A-Za-z0-9_]+__$")


def _denied_dunder(name: str) -> bool:
    return bool(_DUNDER.match(name)) and name not in ALLOWED_DUNDERS


def _root_name(node: ast.expr) -> str | None:
    """The base identifier of an assignment target, through attributes and subscripts."""

    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


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


def _import_violations(
    source: str,
    *,
    label: str,
    base: str = PACKAGE_MODULE,
    root: str = PACKAGE_MODULE,
) -> list[str]:
    """Structural lint over one source text.  SCOPED -- read the module docstring.

    This is a decidable, flat check: it inspects import statements, the dunder
    vocabulary, and call/method spellings.  It does NOT track provenance,
    aliases, receivers, return values or dataflow, and it does not try to.

    What it is complete for:

    1. **Modules.**  Only ``ALLOWED_STDLIB_MODULES``, ``yaml``, the package's own
       modules, and the inert symbols of ``cryodaq.drivers.capability_metadata``
       may be imported.  Every other module -- including every future
       module-loading helper -- is denied without being named.  An import
       statement is syntax, so this is exact.
    2. **Reflection vocabulary.**  Any dunder outside ``ALLOWED_DUNDERS`` is
       reported wherever it is named, and so are ``__import__``,
       ``import_module`` and the ``REFLECTION_CALLS`` builtins.

    What it is only INDICATIVE for: the call/method allowlists below.  A name
    check cannot survive aliasing, and it is not asked to.  It catches the
    accidental case -- someone writes ``open(path, "w")`` in a config reader --
    which is the case that actually happens.  The load-bearing proof that the
    package cannot touch anything is the runtime effect probe at the bottom of
    this file, which measures what running the package DOES.
    """

    tree = ast.parse(source, filename=label)
    # Names defined here, or imported from inside the boundary, are in-boundary:
    # the same scan runs over their own source.
    local_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local_names.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            origin = _resolve_import(node.module or "", node.level, base=base)
            if origin == root or origin.startswith(f"{root}.") or origin in ALLOWED_CRYODAQ_IMPORTS:
                local_names.update(alias.asname or alias.name for alias in node.names)

    violations: list[str] = []
    for node in ast.walk(tree):
        # A denied dunder carried by an IMPORT ALIAS never appears as a Name, an
        # Attribute or a string constant in the body.
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                for part in (*alias.name.split("."), alias.asname or ""):
                    if part and _denied_dunder(part):
                        violations.append(
                            f"{label}: importing the name {part!r} carries interpreter internals past the boundary"
                        )

        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".", 1)[0]
                if alias.name == "importlib" or alias.name.startswith("importlib."):
                    violations.append(f"{label}: importing {alias.name!r} enables dynamic module loading")
                    continue
                if top_level in REFLECTION_MODULES:
                    violations.append(f"{label}: importing {alias.name!r} enables reflection past the boundary")
                    continue
                if top_level in ALLOWED_STDLIB_MODULES or alias.name == "yaml":
                    continue
                if alias.name == root or alias.name.startswith(f"{root}."):
                    continue
                violations.append(f"{label}: bare import of {alias.name!r} crosses the downstream boundary")

        elif isinstance(node, ast.ImportFrom):
            module = _resolve_import(node.module or "", node.level, base=base)
            top_level = module.split(".", 1)[0] if module else ""
            if module == "importlib" or module.startswith("importlib."):
                violations.append(f"{label}: importing from {module!r} enables dynamic module loading")
                continue
            if top_level in REFLECTION_MODULES:
                violations.append(f"{label}: importing from {module!r} enables reflection past the boundary")
                continue
            if any(alias.name == "*" for alias in node.names) and not (module == root or module.startswith(f"{root}.")):
                # A wildcard's bound names cannot be determined from this AST.
                violations.append(f"{label}: wildcard import from {module!r} hides which names it binds")
                continue
            if module == "sys" and any(alias.name == "modules" for alias in node.names):
                violations.append(f"{label}: importing sys.modules by name bypasses the static import boundary")
                continue
            if top_level in ALLOWED_STDLIB_MODULES or top_level == "yaml":
                continue
            if module == root or module.startswith(f"{root}."):
                continue  # in-package
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
            violations.append(f"{label}: the name {node.value!r} reaches interpreter internals past the boundary")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _denied_dunder(node.name):
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
            elif isinstance(func, ast.Attribute) and func.attr == "open":
                # ``.open`` is allowlisted for the loader's bounded READ, so the
                # MODE has to be checked -- Path(...).open("w") truncates.
                modes = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                modes += [
                    k.value.value
                    for k in node.keywords
                    if k.arg == "mode" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)
                ]
                if any(set(m) & set("wax+") for m in modes) or not modes:
                    violations.append(f"{label}: .open() must name an explicit read-only mode, got {modes}")
    return violations


def _scan_package(base_dir: Path, *, package_module: str) -> list[str]:
    """Scan every Python module under a package directory, recursively."""

    violations: list[str] = []
    for path in sorted(base_dir.rglob("*.py")):
        relative_parent = path.parent.relative_to(base_dir)
        file_package = package_module
        if str(relative_parent) != ".":
            file_package = f"{package_module}.{'.'.join(relative_parent.parts)}"
        violations.extend(
            _import_violations(
                path.read_text(encoding="utf-8"), label=path.name, base=file_package, root=package_module
            )
        )
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
    ("module", "symbol"),
    [(module, symbol) for module, symbols in ALLOWED_CRYODAQ_IMPORTS.items() for symbol in sorted(symbols)],
)
def test_every_symbol_allowance_is_load_bearing(monkeypatch: pytest.MonkeyPatch, module: str, symbol: str) -> None:
    """The SYMBOL allowlist must be measured too, not only the four name sets.

    ``test_every_allowlist_entry_is_load_bearing`` covers the module, dunder,
    call and method sets, which made the no-padding claim read as universal
    while ``ALLOWED_CRYODAQ_IMPORTS`` went unmeasured.  It was in fact padded:
    ``DriverTypeMetadata`` sat in this set and no package source imported it,
    so removing it changed nothing.
    """

    scan_module = __import__(__name__.rsplit(".", 1)[0] + ".test_downstream_readonly", fromlist=["x"])
    reduced = dict(scan_module.ALLOWED_CRYODAQ_IMPORTS)
    reduced[module] = reduced[module] - {symbol}
    monkeypatch.setattr(scan_module, "ALLOWED_CRYODAQ_IMPORTS", reduced)
    assert _scan_package(PACKAGE_DIR, package_module=PACKAGE_MODULE) != [], (
        f"symbol {symbol!r} allowed from {module!r} is not required by the package source"
    )


# *** OUT OF SCOPE FOR THE STATIC LINT -- recorded, not silently dropped. ***
#
# Every entry below needs a HOSTILE EDIT TO PACKAGE SOURCE to land through
# review first.  A committer who can do that can also edit this file in the
# same commit, or write code that detects the probe harness, so no test here
# can bind them -- only review and branch protection can.  docs/OPEN_CELLS.md
# line 112 (OC-035) already ratifies exactly this: the checkpoint "does not
# resist a malicious default-branch commit", and the rubric at lines 30-36
# makes ordinary malicious-only residuals NONBLOCKING.
#
# They are listed rather than deleted so the scope decision is auditable and
# so a later reader can see what was considered.  Many of them ARE caught by
# the runtime effect probe below -- anything that mutates os.environ,
# sys.path, the working directory, the filesystem, or (via the in-process
# fingerprint) another module's state.  What is genuinely uncovered is a
# hostile committer, which is a code-review control, not a test control.
_OUT_OF_SCOPE_FOR_STATIC_LINT = (
    "from yaml import SafeLoader\nSafeLoader.yaml_constructors['tag:yaml.org,2002:str'] = None",
    "from yaml import SafeLoader as L\nL.yaml_constructors['tag:yaml.org,2002:str'] = None",
    "from os import environ\nenviron['CRYODAQ_ALLOW_BROKEN_SQLITE'] = '1'",
    "from sys import path\npath[:] = ['/tmp/attacker']",
    "from yaml import SafeLoader\ndel SafeLoader.yaml_constructors",
    "from yaml import SafeLoader\nLoader = SafeLoader\nLoader.yaml_constructors['t'] = None",
    "from yaml import SafeLoader\na = SafeLoader\nb = a\nb.yaml_constructors['t'] = None",
    "from yaml import SafeLoader\nLoader: type = SafeLoader\nLoader.yaml_constructors['t'] = None",
    "from yaml import SafeLoader\n(Loader,) = (SafeLoader,)\nLoader.yaml_constructors['t'] = None",
    "from yaml import SafeLoader\nfor Loader in (SafeLoader,):\n    Loader.yaml_constructors['t'] = None",
    "from yaml import SafeLoader\n(Loader := SafeLoader)\nLoader.yaml_constructors['t'] = None",
    "from os import environ\nE = environ\nE['CRYODAQ_ALLOW_BROKEN_SQLITE'] = '1'",
    "from yaml import SafeLoader\ndef poison(Loader=SafeLoader):\n    Loader.yaml_constructors['t'] = None",
    "from yaml import SafeLoader\ndef poison(*, Loader=SafeLoader):\n    Loader.yaml_constructors['t'] = None",
    "from yaml import SafeLoader\ndef p(Loader=(SafeLoader,)[0]):\n    Loader.yaml_constructors['t'] = None",
    "from yaml import SafeLoader\nL = (SafeLoader,)[0]\nL.yaml_constructors['t'] = None",
    "from yaml import SafeLoader\nL = SafeLoader if True else None\nL.yaml_constructors['t'] = None",
    "from yaml import SafeLoader\nL = [SafeLoader for _ in (1,)][0]\nL.yaml_constructors['t'] = None",
    "from yaml import SafeLoader\nL = SafeLoader or None\nL.yaml_constructors['t'] = None",
    "from yaml import SafeLoader\nL = {'k': SafeLoader}['k']\nL.yaml_constructors['t'] = None",
    "import yaml\nLoader = {'x': yaml.SafeLoader}.get('x')\nLoader.yaml_constructors['t'] = None",
    "from yaml import SafeLoader\nconstructors = SafeLoader.yaml_constructors\nconstructors |= {'t': None}",
    "from yaml import SafeLoader\nmatch SafeLoader:\n    case Loader:\n        Loader.yaml_constructors['t'] = 1",
    "from yaml import SafeLoader\n(SafeLoader,)[0].yaml_constructors['t'] = None",
    "from yaml import SafeLoader\ndef poison(loader):\n    loader.yaml_constructors['t'] = 1\npoison(SafeLoader)",
    "from yaml import SafeLoader\ndef p(*, ldr):\n    ldr.yaml_constructors['t'] = 1\np(ldr=SafeLoader)",
    "from yaml import add_constructor as m\ndef helper():\n    def m(x):\n        return x\nm('t', None)",
    (
        "from yaml import SafeLoader\ndef q(l):\n    l.yaml_constructors['t'] = 1\n"
        "def h():\n    def q(x, y):\n        return x\nq(SafeLoader)"
    ),
    (
        "from yaml import SafeLoader\nclass H:\n    def get(self, l):\n"
        "        l.yaml_constructors['t'] = 1\nH().get(SafeLoader)"
    ),
    "from yaml import SafeLoader\ndef g():\n    return SafeLoader\nL = g()\nL.yaml_constructors['t'] = 1",
    "import yaml\nyaml.__setattr__('safe_load', yaml.unsafe_load)",
    "import sys\nobject.__setattr__(sys, 'argv', [])",
    "from yaml import SafeLoader\ndef list():\n    return SafeLoader\ndef h():\n    x = list()\n    x.f = 1",
    "from yaml import SafeLoader\ndef h():\n    x = [SafeLoader]\n    x[0].yaml_constructors['t'] = 1",
    "import sys\nsys.meta_path.append(None)",
    "from os import get_inheritable as len, set_inheritable as print\nprint(1, not len(1))",
    "from sys import settrace\n@settrace\ndef f(frame, event, arg):\n    return None",
    "from yaml import SafeLoader\ndef h():\n    x = []\n    x.append(SafeLoader)\n    x[0].f = 1",
    "from yaml import SafeLoader\ndef h(list):\n    x = list()\n    x.yaml_constructors['t'] = 1",
    "from sys import settrace\n@(settrace,)[0]\ndef f(a, b, c):\n    return None",
    "from yaml import add_constructor\n(add_constructor,)[0]('tag:test', None)",
    "import sys\ndef poison(self):\n    object.__setattr__(self, 'argv', [])",
    "from yaml import add_implicit_resolver\nclass X(metaclass=add_implicit_resolver):\n    pass",
    "from yaml import add_implicit_resolver\nclass X(**{'metaclass': add_implicit_resolver}):\n    pass",
    "import sys\nclass X:\n    def get(self):\n        self.argv = []\nX.get(sys)",
    "import os\nos.open('/tmp/q', os.O_CREAT, 0o600)",
    "def h():\n    x = []\n    import sys as x\n    x.argv = []",
    "import sys\nsorted([lambda f, e, a: None], key=sys.settrace)",
    "from sys import settrace\nsorted([lambda f, e, a: None], key=settrace)",
    "import sys\nclass X:\n    def get(self):\n        self = sys\n        self.argv = []",
    "from sys import settrace\ndef invoke(print):\n    print(lambda f, e, a: None)",
    "import yaml\nclass X(yaml.YAMLObject):\n    yaml_tag = '!x'",
    "import yaml\nLoader = yaml.SafeLoader\nLoader.yaml_constructors['t'] = None",
    "import yaml\nL: type = yaml.SafeLoader\nL.yaml_constructors['t'] = None",
    "print = open\nprint('config/safety.yaml', 'w')",
    "import yaml\nyaml.load(text, Loader=yaml.UnsafeLoader)",
    "import yaml\nyaml.load(text)",
    "import os\nos.environ['CRYODAQ_ALLOW_BROKEN_SQLITE'] = '1'",
    "import os\nos.environ['CRYODAQ_ROOT'] = '/tmp/attacker'",
    "import sys\nsys.path[:] = ['/tmp/attacker']",
    "import os\ndel os.environ['PATH']",
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
        "from os import environ\nf = lambda E=environ: E.__setitem__('CRYODAQ_ALLOW_BROKEN_SQLITE', '1')",
        "from yaml import *\nSafeLoader.yaml_constructors['t'] = None",
        "from os import *\nenviron['CRYODAQ_ALLOW_BROKEN_SQLITE'] = '1'",
        "from yaml import SafeLoader\ndef h():\n    x = []\n    x.append(SafeLoader)\n    x[0].d.update({'t': 1})",
        "from yaml import __builtins__ as b\nb.get('x')",
        "from os import __dict__ as d\nd.get('x')",
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
        (
            'DriverTypeMetadata.__init__.__globals__["__builtins__"]["__import__"]'
            '("cryodaq.drivers.registry", fromlist=("construct_driver",)).construct_driver'
        ),
        'DriverTypeMetadata.__init__.__globals__["construct_driver"]',
        "DriverTypeMetadata.__class__.__mro__[0].__subclasses__()",
        "DriverTypeMetadata.__module__",
        "__spec__.loader.load_module('cryodaq.drivers.registry')",
        "__loader__.load_module('cryodaq.drivers.registry')",
        "type(DriverTypeMetadata).__bases__",
        "getattr(DriverTypeMetadata, '__globals__')",
        "DriverTypeMetadata.__init__.__func__",
        "DriverTypeMetadata.__dict__",
        "import pkgutil\nactivate = pkgutil.resolve_name('cryodaq.drivers.registry:construct_driver')",
        "import pydoc\npydoc.locate('cryodaq.drivers.registry.construct_driver')",
        "import runpy\nrunpy.run_module('cryodaq.drivers.registry')",
        "from pkgutil import resolve_name",
        "import shutil",
        "import subprocess",
        "open('config/safety.yaml', 'w').write('disabled: true')",
        "from pathlib import Path\nPath('config/safety.yaml').unlink()",
        "import os\nos.replace('config/safety.yaml', 'config/safety.bak')",
        "from pathlib import Path\nPath('config/safety.yaml').write_text('disabled: true')",
        "import os\nos.remove('config/safety.yaml')",
        "def __getattr__(name):\n    return None",
        "from pathlib import Path\nPath('config/safety.yaml').open('w')",
        "from pathlib import Path\nPath('config/safety.yaml').open(mode='a')",
    ),
)
def test_import_guard_rejects_authority_bearing_symbols(hostile: str) -> None:
    assert _import_violations(hostile, label="hostile.py") != []


@pytest.mark.parametrize(
    "allowed",
    (
        "from cryodaq.drivers.capability_metadata import BUILTIN_DRIVER_METADATA",
        "from cryodaq.drivers.capability_metadata import DriverAuthority, DriverCapability",
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
    """Relative imports resolve against the nested file's OWN package.

    The previous version of this test asserted that
    ``from ..drivers.registry import construct_driver`` in ``pkg/sub`` is a
    violation.  It was, but only because the scan compared against the hard-coded
    ``cryodaq.lab_profile`` root instead of the ``pkg`` root it was asked for, so
    the case would have stayed red however the relative-resolution logic broke.
    With the root threaded through, that import resolves to ``pkg.drivers.registry``
    and is correctly in-package -- so the control has to use an import that
    really does leave the package.
    """

    nested = tmp_path / "pkg" / "sub"
    nested.mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (nested / "__init__.py").write_text("", encoding="utf-8")
    # level=3 from pkg.sub climbs past the package root, so it cannot resolve.
    (nested / "evil.py").write_text("from ...drivers.registry import construct_driver\n", encoding="utf-8")
    violations = _scan_package(tmp_path / "pkg", package_module="pkg")
    assert violations != [] and any("evil.py" in entry for entry in violations), violations

    # Positive control on the other side: a relative import that stays inside the
    # requested package must NOT be reported, which is what proves the root is
    # honoured rather than everything simply being called foreign.
    (nested / "evil.py").write_text("from ..sub import helper\n", encoding="utf-8")
    assert _scan_package(tmp_path / "pkg", package_module="pkg") == []


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


_RUNTIME_PROBE = r"""
import hashlib, json, os, runpy, sys
from pathlib import Path

root = Path(sys.argv[1])
mode = sys.argv[2]
# The report goes to a FILE, never stdout: in cli mode the module entry point
# prints its own validation output there, and a report parsed out of a stream
# the measured code also writes to is not a measurement.
report_path = Path(sys.argv[3])
payload = json.loads(sys.stdin.read())

# Capabilities that leave NO trace in a before/after state comparison: a
# launched process, an outbound socket.  `from os import system as print;
# print('true')` mutates no file, no variable, no sys.path entry and no working
# directory, so a state diff alone reports green while a shell has run.  The
# audit hook observes the capability itself, is installed BEFORE the package is
# imported, and cannot be evaded by aliasing or by how the call is spelled.
# These are CPython's own audit-event names for the capability classes, taken as
# classes rather than as spellings: every documented way to create a process,
# every mutating filesystem primitive, every socket.  A write under $HOME and an
# os.fork both leave the copied checkout untouched, so neither is visible to a
# tree hash however complete that tree is.
_AUDITED = frozenset(
    {
        # create a process
        "os.system",
        "os.exec",
        "os.fork",
        "os.forkpty",
        "os.posix_spawn",
        "os.spawn",
        "os.startfile",
        "subprocess.Popen",
        "pty.spawn",
        # mutate the filesystem anywhere, not only under the checkout
        "os.remove",
        "os.rename",
        "os.link",
        "os.symlink",
        "os.mkdir",
        "os.rmdir",
        "os.truncate",
        "os.chmod",
        "os.chown",
        # Metadata, not content: a tree hash over file BYTES stays identical
        # while the mtime an incumbent freshness check relies on is rewritten.
        "os.utime",
        "os.setxattr",
        "os.removexattr",
        "shutil.copyfile",
        "shutil.copymode",
        "shutil.copystat",
        "shutil.copytree",
        "shutil.move",
        "shutil.rmtree",
        "shutil.unpack_archive",
        # reach the network
        "socket.connect",
        "socket.bind",
        "socket.getaddrinfo",
        "socket.sendto",
        "urllib.Request",
        # putenv/unsetenv change what future CHILDREN inherit without touching
        # os.environ, so the environ snapshot cannot see them.  Measured: the
        # interpreter does raise os.putenv, which is why this is an audit entry
        # while umask below is a snapshot -- os.umask raises no audit event.
        "os.putenv",
        "os.unsetenv",
    }
)
# os.open flags that request write access; the `open` audit event reports mode
# as a string for io.open and as flags for os.open.
_WRITE_FLAGS = getattr(os, "O_WRONLY", 0) | getattr(os, "O_RDWR", 0) | getattr(os, "O_APPEND", 0)
_WRITE_FLAGS |= getattr(os, "O_CREAT", 0) | getattr(os, "O_TRUNC", 0)
_observed = set()


def _audit(event, args):
    if event in _AUDITED:
        _observed.add(event)
        return
    if event != "open":
        return
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else None
    if isinstance(mode, str) and set(mode) & set("wax+"):
        _observed.add("file.write")
    elif mode is None and isinstance(flags, int) and flags & _WRITE_FLAGS:
        _observed.add("file.write")


sys.addaudithook(_audit)


def _read_umask():
    try:
        current = os.umask(0o022)
        os.umask(current)
        return current
    except (AttributeError, OSError):
        return None


def _read_priority():
    try:
        return os.getpriority(os.PRIO_PROCESS, 0)
    except (AttributeError, OSError):
        return None


def _read_affinity():
    try:
        return sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return None


def snapshot():
    # EVERY file under the checkout, not an enumerated list of interesting ones.
    # Naming five config paths would have left a write to any sixth path -- a
    # new file, the package's own source, a lock, a cache -- unobserved, which
    # is the same enumeration mistake that the static scan kept making.
    tree = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            tree[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "tree": tree,
        "environ": sorted(os.environ.items()),
        "sys_path": list(sys.path),
        # The working directory is process state the package can move: a single
        # os.chdir redirects every later relative path used by its long-lived
        # host, while touching no file, no variable and no sys.path entry.
        "cwd": os.getcwd(),
        "capabilities": sorted(_observed),
        # os.umask raises NO audit event (measured), so it is read directly.
        # Reading requires setting, hence set-then-restore.  It changes the
        # permissions applied to every later file this process creates while
        # leaving no other trace.
        "umask": _read_umask(),
        # Scheduling priority is likewise process state with no audit event:
        # os.nice(1) slows the long-lived host permanently and touches nothing
        # else.  POSIX-only; None elsewhere.
        "priority": _read_priority(),
        # Affinity is the same capability class as priority and equally
        # traceless: restricting the long-lived host to one CPU changes no
        # file, variable, path or audit event.
        "affinity": _read_affinity(),
    }


# Taken BEFORE the package is imported or executed: an effect that happens at
# import time is exactly what an in-process guard cannot see, because by then
# the package has already run.
before = snapshot()

if mode == "import":
    import cryodaq.lab_profile as lab_profile

    for text in payload["texts"]:
        try:
            lab_profile.parse_lab_profile(text)
        except Exception:
            pass
    measured = lab_profile.__file__
else:
    # The DOCUMENTED production path.  runpy executes __main__.py under the same
    # module machinery as `python -m cryodaq.lab_profile`, but inside THIS
    # process, so any effect it has on the incumbent config, the environment,
    # sys.path or the working directory lands in the after-snapshot instead of
    # vanishing when a grandchild process exits.
    # Every profile, not just the valid one: an operator points this CLI at an
    # UNTRUSTED file, so the rejection path is the one that matters most.
    for profile in payload["profiles"]:
        sys.argv = ["cryodaq.lab_profile", profile]
        try:
            runpy.run_module("cryodaq.lab_profile", run_name="__main__", alter_sys=True)
        except SystemExit:
            pass
        except BaseException:
            # A crashing entry point must not stop the after-snapshot.  The
            # effect it already had IS the measurement, and reporting "tree
            # changed" names the damage; dying here would only report that
            # something threw.
            pass
    measured = sys.modules["cryodaq.lab_profile"].__file__

after = snapshot()
differences = [key for key in before if before[key] != after[key]]
# Report the tree actually executed. Measuring the wrong checkout is this
# repository's single most expensive recurring mistake, and a guard that cannot
# say which source it exercised is not evidence.
report_path.write_text(json.dumps({"differences": differences, "tree": measured}), encoding="utf-8")
"""


def _isolated_checkout(tmp_path: Path) -> Path:
    """Build the throwaway checkout the probe is allowed to damage.

    The live repository is never the mutation target.  If the boundary ever
    regresses to an import-time write, the guard has to turn red *without*
    having first truncated the developer's real ``config/safety.yaml`` --
    a guard whose failure mode is destroying uncommitted work is not a guard
    anyone can afford to run.
    """

    checkout = tmp_path / "checkout"
    shutil.copytree(
        REPO_ROOT / "src" / "cryodaq",
        checkout / "src" / "cryodaq",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for name in INCUMBENT_CONFIG_FILES:
        destination = checkout / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / name, destination)
        # Byte-for-byte, so a hash difference means the package moved, not that
        # the fixture was already unlike the thing it stands in for.
        assert destination.read_bytes() == (REPO_ROOT / name).read_bytes(), name
    # Profiles live OUTSIDE the checkout on purpose: the checkout is the thing
    # being hashed, so writing fixtures into it would show up as a difference
    # the package did not cause.
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    shutil.copyfile(REPO_ROOT / "docs" / "examples" / "lab_profile.imaginary_lab.yaml", profiles / "valid.yaml")
    for index, text in enumerate(HOSTILE_TEXTS):
        (profiles / f"hostile-{index:03d}.yaml").write_text(text, encoding="utf-8")
    # The victim lives INSIDE the checkout on purpose: it is covered by the tree
    # hash, so a YAML constructor that actually executed would delete it and the
    # effect guard would report a ``tree`` difference.  This is what carries the
    # object-tag claim through the DOCUMENTED CLI rather than only through
    # parse_lab_profile.
    victim = checkout / "victim.txt"
    victim.write_text("intact", encoding="utf-8")
    target = json.dumps(str(victim))
    for index, text in enumerate(
        (
            f"!!python/object/apply:os.remove [{target}]",
            f"!!python/object/apply:os.unlink [{target}]",
            f"!!python/name:os.remove\nschema_version: !!python/object/apply:os.remove [{target}]",
            f"schema_version: !!python/object/apply:os.remove [{target}]",
            f"!!python/object/apply:pathlib.Path [{target}]",
        )
    ):
        (profiles / f"objecttag-{index:03d}.yaml").write_text(text, encoding="utf-8")
    return checkout


def _profile_paths(checkout: Path) -> list[str]:
    profiles = checkout.parent / "profiles"
    return [
        str(profiles / "valid.yaml"),
        *sorted(str(path) for path in profiles.glob("hostile-*.yaml")),
        *sorted(str(path) for path in profiles.glob("objecttag-*.yaml")),
    ]


def _probe(checkout: Path, mode: str) -> dict:
    profiles = _profile_paths(checkout)
    object_tags = [Path(path).read_text(encoding="utf-8") for path in profiles if "objecttag-" in path]
    payload = json.dumps({"texts": [_VALID_TEXT, *HOSTILE_TEXTS, *object_tags], "profiles": profiles})
    # *** SYNTHETIC, never dict(os.environ), and never near-empty either. ***
    #
    # Not inherited: this module imports cryodaq.lab_profile at its top, so by
    # the time these tests run the package has ALREADY executed inside the
    # pytest process. An inherited environment would carry any import-time
    # mutation it performed, the child's baseline would start out
    # already-mutated, and setting the same variable again changes nothing --
    # the guard reports green against the very defect it exists to catch.
    # Measured: with an inherited environment an injected os.environ write was
    # reported as no difference, while the identical run from an uncontaminated
    # parent reported it.
    #
    # But not near-empty either. A child holding only PATH is not a production
    # process, and an effect CONDITIONED on an ordinary variable is then
    # invisible: `if "HOME" in environ: environ[...] = ...` ran in a real POSIX
    # process while the probe reported no difference, because the probe had no
    # HOME. So the representative variables below are supplied with fixed
    # synthetic values -- present enough to satisfy such a condition, and
    # deterministic, so nothing from this process can mask a child mutation.
    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "SystemRoot", "COMSPEC") if name in os.environ}
    scratch = checkout.parent / "home"
    scratch.mkdir(exist_ok=True)
    env.update(
        {
            "HOME": str(scratch),
            "USERPROFILE": str(scratch),
            "TEMP": str(scratch),
            "TMP": str(scratch),
            "TMPDIR": str(scratch),
            "USER": "cryodaq-probe",
            "USERNAME": "cryodaq-probe",
            "LOGNAME": "cryodaq-probe",
            "HOSTNAME": "cryodaq-probe",
            "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8",
            "SHELL": "/bin/sh",
            "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        }
    )
    env["PYTHONPATH"] = str(checkout / "src")
    # A hand-built environment DROPS PYTHONDONTWRITEBYTECODE, and the child then
    # compiles __pycache__/*.pyc beside whatever it imports.  Against the
    # exported candidate tree that changed the evidence leaf set and failed the
    # run with `exported candidate leaf set changed (unexpected=[... .pyc])`,
    # listing exactly the import closure of cryodaq.lab_profile.  The copied
    # checkout already keeps that out of the candidate tree; -B and the variable
    # make it true of the child itself rather than a property of where it points.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    report_path = checkout.parent / f"report-{mode}.json"
    completed = subprocess.run(
        [sys.executable, "-B", "-c", _RUNTIME_PROBE, str(checkout), mode, str(report_path)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=checkout,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    # The measuring apparatus must not modify the tree it measures.  In CI that
    # tree is the exported candidate, whose leaf set is the evidence, so a
    # stray .pyc is a hard contract violation and not a tidiness point.
    stray = sorted(path.relative_to(checkout).as_posix() for path in checkout.rglob("*.pyc"))
    assert stray == [], f"the probe wrote bytecode into the tree it measures: {stray}"
    assert report_path.is_file(), f"probe wrote no report\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert Path(report["tree"]).is_relative_to(checkout), f"measured the wrong checkout: {report['tree']}"
    return report


# Each entry is a capability the read-only claim excludes, written the way a
# regression would actually arrive, mapped to the snapshot dimension that must
# report it.  These are CONTROLS, not a denylist: nothing in the guard matches
# on these strings -- it measures the resulting state -- and their only job is
# to prove the guard can go red.  Three separate ones land in ``tree`` because
# corrupting an incumbent config, planting a new file and editing the package's
# own source are different regressions that a five-path enumeration would have
# scored differently.
_REGRESSIONS = {
    "incumbent_config_write": (
        {"tree", "capabilities"},
        "open(os.path.join(os.getcwd(), 'config', 'safety.yaml'), 'w').write('disabled: true')",
    ),
    "new_file_anywhere": ({"tree", "capabilities"}, "open(os.path.join(os.getcwd(), 'planted.txt'), 'w').write('x')"),
    "package_self_edit": (
        {"tree", "capabilities"},
        "open(os.path.join(os.getcwd(), 'src', 'cryodaq', 'lab_profile', 'capabilities.py'), 'a').write('\\n')",
    ),
    # os.environ.__setitem__ calls putenv internally, so both the environ
    # snapshot and the audit hook fire.  Measured, not assumed.
    "environment_write": ({"environ", "capabilities"}, "os.environ['CRYODAQ_ALLOW_BROKEN_SQLITE'] = '1'"),
    # Leaves NO trace in a state diff -- no file, variable, path or cwd changes.
    # Only the audit hook sees it.  (Deliberately NOT spelled as an alias over
    # `print`: that shadows a builtin __main__.py itself calls, so the control
    # would fail for its own reason instead of measuring the guard.)
    "process_launch": ({"capabilities"}, "os.system('exit 0')"),
    # Changes what future CHILDREN inherit without touching os.environ, so the
    # environ snapshot is blind to it.
    "putenv_write": ({"capabilities"}, "os.putenv('CRYODAQ_ALLOW_BROKEN_SQLITE', '1')"),
    # Without this, removing or misspelling the socket audit entries left
    # every registered control green while the record claimed network
    # coverage.  Loopback with an ephemeral port: deterministic, reaches no
    # network.
    "network_socket": (
        {"capabilities"},
        "import socket\n_s = socket.socket()\n_s.bind(('127.0.0.1', 0))\n_s.close()",
    ),
    # Content unchanged, so the tree hash cannot see it; only the audit hook can.
    "metadata_mutation": (
        {"capabilities"},
        "os.utime(os.path.join(os.getcwd(), 'config', 'safety.yaml'), (0, 0))",
    ),
    # Outside the copied checkout entirely, so no tree hash can ever see it --
    # in a real invocation this is the operator's own home directory.
    "write_outside_checkout": (
        {"capabilities"},
        "import io\n"
        "class Sink(io.FileIO):\n"
        "    pass\n"
        "Sink(os.path.join(os.environ['HOME'], 'planted.txt'), 'w').close()",
    ),
    # Conditioned on an ordinary variable, which a near-empty environment hid.
    "conditional_on_home": (
        {"environ", "capabilities"},
        "os.environ['CRYODAQ_ALLOW_BROKEN_SQLITE'] = '1' if 'HOME' in os.environ else None",
    ),
    "import_path_insert": ({"sys_path"}, "sys.path.insert(0, os.path.join(os.getcwd(), 'attacker'))"),
    "working_directory_move": ({"cwd"}, "os.chdir(os.path.dirname(os.getcwd()))"),
}
if os.name == "posix":
    # Lowers the scheduling priority of the long-lived host permanently, with
    # no audit event and no other trace.  POSIX-only, like umask.
    if os.getpriority(os.PRIO_PROCESS, 0) < 19:
        # Gated on the priority actually being increasable: launched under
        # `nice -n 19`, os.nice(1) returns 19 and changes nothing, so the control
        # would fail for its own reason instead of proving the guard can go red.
        _REGRESSIONS["scheduling_change"] = ({"priority"}, "os.nice(1)")
    if hasattr(os, "sched_setaffinity") and len(os.sched_getaffinity(0)) > 1:
        # The next primitive in the same class as os.nice.  Gated on there being
        # at least TWO CPUs available: under `taskset -c 0` the process is
        # already pinned to a singleton, setting it again changes nothing, and
        # the control would fail for its own reason instead of proving the guard
        # can go red.
        _REGRESSIONS["affinity_change"] = (
            {"affinity"},
            "os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})",
        )
    # Changes the permissions applied to every later file this process creates.
    # os.umask raises no audit event, hence the umask snapshot.  Measured:
    # on Windows os.umask always returns 0o0 and tracks nothing, so the
    # control would be vacuous there and is gated rather than asserted.
    # The target mask is DERIVED from the inherited one: hard-coding 0o077 makes
    # no transition when the suite is launched under `umask 077`, and the
    # control then fails for its own reason.
    _inherited = os.umask(0o022)
    os.umask(_inherited)
    _REGRESSIONS["umask_change"] = ({"umask"}, f"os.umask({_inherited ^ 0o077:#o})")
if hasattr(os, "fork"):
    # POSIX only -- Windows has no fork, so this control cannot run there and is
    # registered conditionally rather than being asserted on every platform.
    # The child exits immediately so it cannot go on running the probe.
    _REGRESSIONS["fork_process"] = ({"capabilities"}, "if os.fork() == 0:\n    os._exit(0)")


@pytest.mark.parametrize("mode", ("import", "cli"))
def test_import_and_parse_leave_incumbent_process_state_untouched(tmp_path: Path, mode: str) -> None:
    """Measure the read-only claim by EFFECT, in a fresh process, not by spelling.

    The static scan constrains what the package's source may say; this
    constrains what running it may do.  It is indifferent to aliasing
    (``print = open``), to receiver (``Path(...).open("w")``), to argument
    values (``Loader=yaml.UnsafeLoader``) and to whether the mutation is a call
    at all (``os.environ[...] = ...``, ``sys.path[:] = [...]``) -- all of which
    defeated, or would defeat, a purely syntactic capability check.

    Both entry points are exercised.  ``import`` covers the library path;
    ``cli`` runs ``__main__`` the way the documented
    ``python -m cryodaq.lab_profile`` invocation does, which the earlier
    version of this guard never executed -- so a side effect added to
    ``__main__.py`` was unobserved by every test in this file.

    Crucially the baseline is taken BEFORE the package is imported or run.
    ``test_hostile_corpus_leaves_incumbent_state_untouched`` cannot do that: by
    the time it runs, this module's own import has already executed the
    package, so an import-time write would be inside its baseline.
    """

    assert _probe(_isolated_checkout(tmp_path), mode)["differences"] == []


@pytest.mark.parametrize(("mode", "entry_point"), (("import", "__init__.py"), ("cli", "__main__.py")))
@pytest.mark.parametrize("regression", sorted(_REGRESSIONS))
def test_effect_guard_reports_a_real_regression(tmp_path: Path, mode: str, entry_point: str, regression: str) -> None:
    """Positive control: a green guard is only evidence if it can go red.

    Each regression is injected into the throwaway checkout and must be
    reported, on the entry point that actually executes it.  The ``cli`` case
    is what binds the claim that the documented CLI is exercised: nothing in
    ``import`` mode runs ``__main__.py``, so if the probe were not really
    running the module entry point this control would observe no difference and
    fail.
    """

    dimension, code = _REGRESSIONS[regression]
    checkout = _isolated_checkout(tmp_path)
    module = checkout / "src" / "cryodaq" / "lab_profile" / entry_point
    source = module.read_text(encoding="utf-8")
    # Inserted AFTER the __future__ import, which must stay first in the file.
    anchor = "from __future__ import annotations\n"
    assert anchor in source, entry_point
    module.write_text(source.replace(anchor, f"{anchor}import os, sys\n{code}\n", 1), encoding="utf-8")
    assert set(_probe(checkout, mode)["differences"]) == dimension


def test_effect_guard_reports_a_function_local_unsafe_loader(tmp_path: Path) -> None:
    """A loader defined INSIDE a function, used only on the documented CLI path.

    ``vars(module)`` cannot see a class defined inside ``main()``, and the static
    scan trusts every locally defined class name, so neither of those guards
    covers this.  The effect probe does, because it drives Python object tags
    through ``python -m cryodaq.lab_profile`` against a victim file that lives
    inside the hashed tree -- a constructor that actually ran deletes it.

    This is registered as its own control so that coverage is asserted rather
    than argued: without it, the object-tag-through-the-CLI path was exercised
    but nothing proved it could go red.
    """

    checkout = _isolated_checkout(tmp_path)
    main_py = checkout / "src" / "cryodaq" / "lab_profile" / "__main__.py"
    source = main_py.read_text(encoding="utf-8")
    anchor = "    try:\n        profile = load_lab_profile(Path(args[0]))\n"
    assert anchor in source
    main_py.write_text(
        source.replace(
            anchor,
            "    import yaml as _y\n"
            "    class Loader(_y.UnsafeLoader):\n"
            "        pass\n"
            "    _y.load(Path(args[0]).read_text(encoding='utf-8'), Loader=Loader)\n" + anchor,
            1,
        ),
        encoding="utf-8",
    )
    victim = checkout / "victim.txt"
    assert victim.read_text(encoding="utf-8") == "intact"
    assert "tree" in _probe(checkout, "cli")["differences"]
    assert not victim.exists(), "the object tag did not execute, so this control proves nothing"


def test_documented_cli_spelling_validates_the_shipped_example(tmp_path: Path) -> None:
    """The documented invocation itself must work, not only an in-process stand-in.

    ``_probe`` runs ``__main__`` through ``runpy`` so that effects stay
    observable; this pins that stand-in to the real
    ``python -m cryodaq.lab_profile`` spelling the documentation promises.
    """

    checkout = _isolated_checkout(tmp_path)
    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "SystemRoot") if name in os.environ}
    env["PYTHONPATH"] = str(checkout / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # see _probe: a clean env drops this and the child writes .pyc
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "cryodaq.lab_profile", str(checkout.parent / "profiles" / "valid.yaml")],
        capture_output=True,
        text=True,
        env=env,
        cwd=checkout,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "actuation_supported: false" in completed.stdout, completed.stdout


def test_hostile_corpus_leaves_incumbent_state_untouched() -> None:
    before = _incumbent_snapshot()
    for text in HOSTILE_TEXTS:
        with pytest.raises(LabProfileError):
            parse_lab_profile(text)
    assert _incumbent_snapshot() == before


def test_no_loader_in_the_package_can_construct_python_objects() -> None:
    """Ask the loader what it can DO, not what it is called.

    The static scan accepts ``Loader=<any name defined in the package>``, so
    ``class Loader(yaml.UnsafeLoader): pass`` passes it while still executing
    tags such as ``!!python/object/apply:os.remove``.  Adding that spelling to
    a list would have been the next enumeration; the property that actually
    matters is whether the loader that runs is able to construct Python
    objects, which is asked here of every loader class the package defines --
    including ones that do not exist yet.
    """

    import yaml
    import yaml.constructor

    # PyYAML's loaders are SIBLINGS, not a hierarchy: issubclass(SafeLoader,
    # BaseLoader) is False, so testing against BaseLoader silently inspects
    # nothing.  Every loader does inherit a constructor, and FullConstructor is
    # exactly where the python/ tags are introduced -- FullLoader carries 13 and
    # UnsafeLoader 17, while SafeLoader carries none.
    inspected: list[type] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        relative = path.relative_to(PACKAGE_DIR).with_suffix("")
        parts = [part for part in relative.parts if part != "__init__"]
        # __main__ is INCLUDED.  Importing it as an ordinary submodule sets
        # __name__ to "cryodaq.lab_profile.__main__", so its
        # ``if __name__ == "__main__"`` guard is false and the entry point does
        # not run -- there is no reason to skip it, and skipping it left a
        # CLI-only loader outside every capability check.
        module = importlib.import_module(".".join([PACKAGE_MODULE, *parts]) if parts else PACKAGE_MODULE)
        for attribute in vars(module).values():
            if not isinstance(attribute, type) or not issubclass(attribute, yaml.constructor.BaseConstructor):
                continue
            inspected.append(attribute)
            assert not issubclass(attribute, yaml.constructor.FullConstructor), (
                f"{attribute!r} inherits object construction"
            )
            tags = set(attribute.yaml_constructors) | set(attribute.yaml_multi_constructors)
            executable = sorted(tag for tag in tags if tag and "python/" in tag)
            assert executable == [], f"{attribute!r} can construct {executable}"
    assert inspected, "no YAML loader found in the package; this guard would be vacuous"


def test_host_yaml_registrations_cannot_reach_the_profile_loader(tmp_path: Path) -> None:
    """A third party must not be able to decide what the profile parser runs.

    Subclassing ``yaml.SafeLoader`` shares its mutable ``yaml_constructors``
    mapping BY REFERENCE, so any host or library that has called
    ``yaml.SafeLoader.add_constructor(...)`` -- ordinary PyYAML use, not an
    attack -- changed what ``parse_lab_profile`` executed.  Measured before the
    fix: a constructor registered for the standard string tag deleted a file
    while an operator profile was being validated.

    The victim file is the measurement: a constructor that ran would remove it.
    """

    import yaml

    from cryodaq.lab_profile.loader import _StrictLabProfileLoader

    assert _StrictLabProfileLoader.yaml_constructors is not yaml.SafeLoader.yaml_constructors
    assert _StrictLabProfileLoader.yaml_multi_constructors is not yaml.SafeLoader.yaml_multi_constructors

    victim = tmp_path / "victim.txt"
    victim.write_text("intact", encoding="utf-8")

    def side_effecting(loader: object, node: object) -> str:
        victim.unlink(missing_ok=True)
        return "pwned"

    original = dict(yaml.SafeLoader.yaml_constructors)
    yaml.SafeLoader.add_constructor("tag:yaml.org,2002:str", side_effecting)
    try:
        profile = parse_lab_profile(_VALID_TEXT)
        assert profile.lab_id == "readonly-lab"
        assert victim.read_text(encoding="utf-8") == "intact", "a host registration reached the profile loader"
    finally:
        yaml.SafeLoader.yaml_constructors.clear()
        yaml.SafeLoader.yaml_constructors.update(original)


@pytest.mark.parametrize(
    ("label", "document"),
    (
        # Owning the constructor table narrowed the accepted tag vocabulary.
        # An unquoted date USED to construct a datetime.date and be rejected
        # later by the schema's exact type checks; it now dies at parse.  The
        # direction is unchanged -- fail closed -- but the boundary moved, so it
        # is pinned here rather than left as an undocumented side effect.
        ("implicit timestamp", "lab_id: 2026-01-01"),
        ("binary", "lab_id: !!binary aGk="),
        ("python object", "lab_id: !!python/object/apply:os.getcwd []"),
        ("arbitrary tag", "lab_id: !!foo bar"),
    ),
)
def test_owned_tag_vocabulary_rejects_everything_outside_it(label: str, document: str) -> None:
    """Only null/bool/int/float/str/seq/map construct; everything else fails closed."""

    text = _VALID_TEXT.replace("  lab_id: readonly-lab", f"  {document}")
    with pytest.raises(LabProfileError):
        parse_lab_profile(text)


def test_python_object_tags_never_execute(tmp_path: Path) -> None:
    """The same property proved by effect: an object tag must not run.

    This holds whatever the loader is named or wherever it is defined, so it
    survives an edit that the class-level check above would have to be taught
    about.  The file is the measurement: a constructor that ran would delete it.
    """

    victim = tmp_path / "victim.txt"
    victim.write_text("intact", encoding="utf-8")
    target = json.dumps(str(victim))
    for text in (
        f"!!python/object/apply:os.remove [{target}]",
        f"!!python/object/apply:os.unlink [{target}]",
        f"!!python/object/apply:pathlib.Path [{target}]",
        "!!python/name:os.system",
        "!!python/object/apply:subprocess.getoutput ['echo compromised']",
        f"schema_version: !!python/object/apply:os.remove [{target}]",
    ):
        with pytest.raises(LabProfileError):
            parse_lab_profile(text)
        assert victim.read_text(encoding="utf-8") == "intact", text


def test_package_grants_no_authority_objects() -> None:
    forbidden_prefixes = ("construct_", "connect", "open", "send", "write")
    for name in dir(lab_profile_package):
        assert not name.startswith(forbidden_prefixes), name
    profile = parse_lab_profile(_VALID_TEXT)
    assert profile.grants_control_authority is False
    assert profile.capabilities.actuation_supported is False
    assert profile.capabilities.grants_control_authority is False
