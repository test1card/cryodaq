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
    {"__future__", "dataclasses", "enum", "io", "os", "pathlib", "re", "sys", "typing", "unicodedata"}
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
        # int(): the owned integer constructor converts a scalar whose text
        # _INT_PATTERN has already restricted to ^[-+]?[0-9]+$.  Strictly
        # narrower than PyYAML's own, which also accepts 0x/0b/sexagesimal.
        "int",
        "isinstance",
        # This package's own import-time-bound disposer.  It exists
        # precisely so validation does not look up `yaml.load` at call time,
        # which a host can rebind -- measured: a wrapper that deleted a file and
        # returned a forged dict was accepted as a valid profile.
        "_LOADER_DISPOSE",
        "len",
        "list",
        "print",
        "repr",
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
        "compile",
        "check_event",
        "compose_node",
        "construct_object",
        "decode",
        "encode",
        "get",
        "isfile",
        "isprintable",
        "isspace",
        "join",
        "lower",
        # construct_mapping is the loader's OWN duplicate-key-rejecting method;
        # items() is a pure read.  Neither is a mutation spelling, so neither
        # weakens what this vocabulary is for.
        "construct_mapping",
        # The owned parse entry point calls these two on ITSELF.  They are the
        # rungs below get_single_data that remain inherited -- named here rather
        # than hidden, and covered by the MRO provenance guard.
        "get_single_node",
        "construct_document",
        "get_single_data",
        "items",
        # _INT_PATTERN.match(): explicit !!int text is now checked against the
        # loader's decimal grammar instead of trusting int().
        "match",
        "normalize",
        "open",
        "peek_event",
        "read",
        "reconfigure",
        "setdefault",
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


def _encode(value, depth, home, seen):
    # Structural encoding of one object, depth-capped and cycle-safe.
    if depth <= 0:
        return "..."
    if value is None or isinstance(value, (bool, int, float, complex, str, bytes)):
        return repr(value)[:200]
    marker = id(value)
    if marker in seen:
        return "<cycle>"
    seen.add(marker)
    try:
        if isinstance(value, dict):
            return "{" + ",".join(
                f"{_encode(k, depth - 1, home, seen)}:{_encode(v, depth - 1, home, seen)}"
                for k, v in sorted(value.items(), key=lambda kv: repr(kv[0]))
            ) + "}"
        if isinstance(value, (list, tuple)):
            return "[" + ",".join(_encode(x, depth - 1, home, seen) for x in value) + "]"
        if isinstance(value, (set, frozenset)):
            return "[" + ",".join(_encode(x, depth - 1, home, seen) for x in sorted(value, key=repr)) + "]"
        if isinstance(value, type):
            # Recurse into classes DEFINED HERE -- that is where a mutable
            # class-level registry such as SafeLoader.yaml_constructors lives.
            # Foreign classes are named, not walked, so the encoding stays local.
            if getattr(value, "__module__", None) == home:
                body = {k: v for k, v in vars(value).items() if not k.startswith("__")}
                return f"<class {value.__qualname__} {_encode(body, depth - 1, home, seen)}>"
            return f"<class {getattr(value, '__module__', '?')}.{getattr(value, '__qualname__', '?')}>"
        module_name = getattr(value, "__module__", None)
        qualname = getattr(value, "__qualname__", None)
        if qualname is not None:
            # Functions and bound methods.  __module__ and __qualname__ are
            # WRITABLE, so naming alone is not identity: a replacement callable
            # that copies both -- built from dynamically assembled strings, so
            # the static scan sees nothing -- produced an IDENTICAL fingerprint
            # and `_probe(..., "import")` reported `differences: []` while the
            # host `yaml` module had in fact been modified.
            #
            # The code object is the part a replacement cannot fake while still
            # being a different function: it names the file and line where the
            # body was compiled and carries the compiled bytecode itself.
            code = getattr(value, "__code__", None) or getattr(
                getattr(value, "__func__", None), "__code__", None
            )
            if code is not None:
                # The code object alone is NOT identity either.  A replacement
                # built as types.FunctionType(original.__code__, {...}) reuses
                # the bytecode verbatim while resolving its global lookups
                # through a different namespace -- measured, the probe reported
                # `differences: []` while the swapped function called a
                # different `load`.  So the namespace, defaults and closure are
                # part of the encoding.
                function_globals = getattr(value, "__globals__", None)
                globals_identity = id(function_globals) if function_globals is not None else 0
                return (
                    f"<fn {module_name}.{qualname}"
                    f" @{getattr(code, 'co_filename', '?')}:{getattr(code, 'co_firstlineno', '?')}"
                    f" #{hash(getattr(code, 'co_code', b''))}"
                    f" g={function_globals.get('__name__', '?') if function_globals is not None else '?'}"
                    f"/{globals_identity}"
                    f" d={_encode(getattr(value, '__defaults__', None), depth - 1, home, seen)}"
                    f" c={len(getattr(value, '__closure__', ()) or ())}>"
                )
            # C functions and builtins have no code object.  Fall back to the
            # exact type plus the object's own repr, which for builtins encodes
            # the underlying implementation rather than a writable label.
            return f"<builtin {type(value).__module__}.{type(value).__name__} {value!r}>"
        return f"<{type(value).__module__}.{type(value).__name__}>"
    except Exception:
        return "<unencodable>"
    finally:
        seen.discard(marker)


def _fingerprint():
    # Hash the reachable state of every module already imported.
    #
    # This is what a before/after file+env comparison cannot see: a package
    # that mutates ANOTHER module's state leaves no file, variable, path or
    # audit trace.  Not hypothetical -- it is the class the shipped
    # yaml_constructors defect belonged to, where a shared mutable table let
    # a third party decide what a lab profile executes.
    #
    # Depth-capped at 5, which reaches module -> class -> registry -> entry.
    # A floor, not totality, and stated as such rather than claimed to be
    # exhaustive.
    prints = {}
    for name, module in sorted(sys.modules.items()):
        if module is None:
            continue
        try:
            members = {k: v for k, v in vars(module).items() if not k.startswith("__")}
            if name == "sys":
                # Two members are pure IMPORT BOOKKEEPING and are excluded, both
                # for the same reason: each is a function of what has been
                # imported, so hashing it makes `sys` move on every import and
                # drowns the signal.  Measured -- path_importer_cache was the
                # last mover after the closure was warmed.
                #   modules             -- set growth is reported separately
                #   path_importer_cache -- which finder handles which path
                # Everything a package could actually abuse stays hashed:
                # meta_path, path_hooks, argv, and the trace/profile hooks.
                # sys.path itself is snapshotted as its own dimension, so path
                # injection is caught regardless.
                members.pop("modules", None)
                members.pop("path_importer_cache", None)
        except Exception:
            continue
        prints[name] = hashlib.sha256(_encode(members, 5, name, set()).encode("utf-8", "replace")).hexdigest()
    return prints


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
        # Trace/profile hooks are INTERPRETER state, not module attributes:
        # sys.settrace(...) leaves nothing in vars(sys), so neither the module
        # fingerprint nor the audit hook sees it.  Measured -- the tracing
        # control reported nothing at all until this dimension existed.
        "hooks": [repr(sys.gettrace()), repr(sys.getprofile())],
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


# The volatility mask is MEASURED, not authored.
#
# First WARM the exact import closure the package is allowed to use, taken from
# ALLOWED_STDLIB_MODULES rather than hand-listed here.  After warming, the
# package's own imports add nothing new, so anything that moves afterwards is a
# MUTATION rather than an import side effect.  Without this, copyreg dispatch
# tables, collections.abc registries and sys internals move on any import and
# drown the signal.
#
# Then fingerprint repeatedly with only benign work in between: whatever moves
# on its own is inherently volatile and is masked.  Only self-moving state is
# excused, so the mask cannot quietly cover a real mutation -- the same
# second-pass-fixed-point idea this repository already uses for derived
# artifacts.
import importlib as _calibration_importlib

for _warm in payload["warm"]:
    try:
        _calibration_importlib.import_module(_warm)
    except ImportError:
        pass

_first = _fingerprint()
_second = _fingerprint()
sys.modules["yaml"].safe_load("calibration: 1")
_third = _fingerprint()
# One more FRESH import, after warming: the first import following a baseline
# perturbs import bookkeeping (path_importer_cache and friends) nested inside
# sys.  Measuring that here masks it; hand-excluding sys members would not be
# measurement.
_calibration_importlib.import_module("fractions")
_fourth = _fingerprint()
_volatile = {name for name in _first if _first.get(name) != _second.get(name)}
_volatile |= {name for name in _second if _second.get(name) != _third.get(name)}
_volatile |= {name for name in _third if _third.get(name) != _fourth.get(name)}
_baseline = _fingerprint()

# Taken BEFORE the package is imported or executed: an effect that happens at
# import time is exactly what an in-process guard cannot see, because by then
# the package has already run.
before = snapshot()

_argv_rewrites = []
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
    # The HARNESS sets argv, so the harness restores it.  Otherwise the
    # fingerprint reports the probe's own mutation of sys as a finding.
    #
    # CORRECTED: this used to claim "a package that rewrote argv would still be
    # caught: its change persists past this restore".  That was FALSE and was
    # disproved by injecting `sys.argv = []` into __main__.py, which produced
    # `differences: []`.  The restore below overwrites exactly the evidence the
    # after-snapshot was supposed to find.  So argv is now compared BEFORE it is
    # restored, once per profile, and any divergence is its own finding.
    _harness_argv = list(sys.argv)
    _argv_rewrites = []
    for profile in payload["profiles"]:
        _expected_argv = ["cryodaq.lab_profile", profile]
        sys.argv = list(_expected_argv)
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
        # Measured HERE, before any restore: runpy with alter_sys=True sets and
        # then restores argv[0] itself, so anything still different at this
        # point was written by the package under test.
        if list(sys.argv) != _expected_argv:
            _argv_rewrites.append({"expected": _expected_argv, "observed": list(sys.argv)[:8]})
    sys.argv = _harness_argv
    measured = sys.modules["cryodaq.lab_profile"].__file__

after = snapshot()
differences = [key for key in before if before[key] != after[key]]
_final = _fingerprint()
# Modules the boundary is ALLOWED to pull in.  Anything else appearing is a
# finding: the whole claim is that validating a profile does not load the
# driver registry or any authority-bearing module.
_ALLOWED_NEW_MODULE_ROOTS = ("cryodaq.lab_profile", "cryodaq.drivers.capability_metadata")
# Measured, not guessed: a clean import adds exactly `__future__` and `cryodaq`
# beyond the roots above.  Both are inert -- `src/cryodaq/__init__.py` and
# `src/cryodaq/drivers/__init__.py` are EMPTY files, and `__future__` carries
# compiler flags and no authority.  Each name is listed individually so that
# adding one is a visible decision rather than a widened prefix.
_ALLOWED_NEW_MODULES = frozenset({"__future__", "cryodaq", "cryodaq.drivers"})
_expected_new = sorted(
    name
    for name in set(_final) - set(_baseline)
    if not name.startswith(_ALLOWED_NEW_MODULE_ROOTS) and name not in _ALLOWED_NEW_MODULES
)
_moved = sorted(
    name
    for name in _baseline
    if name not in _volatile and _baseline[name] != _final.get(name)
)
if _moved:
    differences.append("module_state")
if _expected_new:
    # This was computed and then NEVER USED, so module-set growth was never
    # reported at all: injecting a plain `import decimal` into the checkout left
    # the probe reporting `differences: []`.  A dimension the report does not
    # carry is not measured, however carefully it is computed.
    differences.append("new_modules")
if _argv_rewrites:
    differences.append("argv")
# Report the tree actually executed. Measuring the wrong checkout is this
# repository's single most expensive recurring mistake, and a guard that cannot
# say which source it exercised is not evidence.
report_path.write_text(
    json.dumps(
        {
            "differences": differences,
            "tree": measured,
            "moved_modules": _moved[:12],
            "new_modules": _expected_new[:12],
            "argv_rewrites": _argv_rewrites[:4],
        }
    ),
    encoding="utf-8",
)
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
    payload = json.dumps(
        {
            "texts": [_VALID_TEXT, *HOSTILE_TEXTS, *object_tags],
            "profiles": profiles,
            # The package's own declared import closure, warmed before the
            # baseline so its imports add nothing new.  Taken from the
            # allowlist, so it cannot drift from what the scan permits.
            "warm": [*sorted(ALLOWED_STDLIB_MODULES - {"__future__"}), "yaml"],
        }
    )
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
# On POSIX, assigning to os.environ also mutates posix.environ, so the module
# fingerprint legitimately reports it alongside the environ dimension.  That is
# platform state, not a defect, and it is measured here rather than hard-coded:
# Windows has no posix module and reports only the two.
_ENVIRON_DIMENSIONS = {"environ", "capabilities"} | ({"module_state"} if os.name == "posix" else set())

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
    "environment_write": (_ENVIRON_DIMENSIONS, "os.environ['CRYODAQ_ALLOW_BROKEN_SQLITE'] = '1'"),
    # Leaves NO trace in a state diff -- no file, variable, path or cwd changes.
    # Only the audit hook sees it.  (Deliberately NOT spelled as an alias over
    # `print`: that shadows a builtin __main__.py itself calls, so the control
    # would fail for its own reason instead of measuring the guard.)
    "process_launch": ({"capabilities"}, "os.system('exit 0')"),
    # Changes what future CHILDREN inherit without touching os.environ, so the
    # environ snapshot is blind to it.
    "putenv_write": ({"capabilities"}, "os.putenv('CRYODAQ_ALLOW_BROKEN_SQLITE', '1')"),
    # ---- in-process Python state.  None of these touches a file, a
    # variable, a path, the working directory, or any audit event, so only
    # the module-state fingerprint can see them.  The first is the class the
    # shipped yaml_constructors defect belonged to.
    "yaml_constructor_registration": (
        {"module_state"},
        "import yaml\nyaml.SafeLoader.add_constructor('tag:yaml.org,2002:str', lambda l, n: 'x')",
    ),
    "import_hook_installed": ({"module_state"}, "import sys\nsys.meta_path.insert(0, object())"),
    "tracing_installed": ({"hooks"}, "import sys\nsys.settrace(lambda f, e, a: None)"),
    "foreign_attribute_rebound": ({"module_state"}, "import yaml\nyaml.safe_load = yaml.unsafe_load"),
    # Without this, removing or misspelling the socket audit entries left
    # every registered control green while the record claimed network
    # coverage.  Loopback with an ephemeral port: deterministic, reaches no
    # network.
    "network_socket": (
        # Two dimensions, because `import socket` really does both: it acquires
        # a capability AND grows the module set.  Recorded as measured.
        {"capabilities", "new_modules"},
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
        _ENVIRON_DIMENSIONS,
        "os.environ['CRYODAQ_ALLOW_BROKEN_SQLITE'] = '1' if 'HOME' in os.environ else None",
    ),
    # sys.path is also reachable inside the `sys` fingerprint, so a path
    # insert legitimately reports both dimensions.  Measured, not assumed.
    "import_path_insert": (
        {"sys_path", "module_state"},
        "sys.path.insert(0, os.path.join(os.getcwd(), 'attacker'))",
    ),
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


def test_effect_probe_reports_a_newly_imported_module(tmp_path: Path) -> None:
    """`_expected_new` was computed and never reported, so this never fired.

    Measured before the fix: injecting a plain ``import decimal`` into the
    throwaway checkout left the probe reporting ``differences: []``, even though
    the boundary's central claim is that validating a profile does not pull in
    authority-bearing modules. A dimension the report does not carry is not
    measured, however carefully it is computed -- so it now has a control.
    """

    checkout = _isolated_checkout(tmp_path)
    entry_point = checkout / "src" / "cryodaq" / "lab_profile" / "__init__.py"
    entry_point.write_text(
        entry_point.read_text(encoding="utf-8") + "\nimport decimal  # REGRESSION\n",
        encoding="utf-8",
    )
    report = _probe(checkout, "import")
    assert "new_modules" in report["differences"], report
    assert "decimal" in report["new_modules"], report


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
        ("binary", "lab_id: !!binary aGk="),
        ("python object", "lab_id: !!python/object/apply:os.getcwd []"),
        ("arbitrary tag", "lab_id: !!foo bar"),
        ("timestamp tag", "lab_id: !!timestamp 2026-01-01"),
    ),
)
def test_owned_tag_vocabulary_rejects_everything_outside_it(label: str, document: str) -> None:
    """Only null/bool/int/float/str/seq/map construct; every other tag fails closed."""

    text = _VALID_TEXT.replace("  lab_id: readonly-lab", f"  {document}")
    with pytest.raises(LabProfileError):
        parse_lab_profile(text)


def test_owned_resolvers_read_date_like_scalars_as_plain_strings() -> None:
    """A consequence of owning the resolver table, pinned rather than left implicit.

    Only resolvers for the owned tag vocabulary survive, so an unquoted
    ``2026-01-01`` no longer resolves to the timestamp tag.  It is read as the
    string it looks like, which is what an operator writing a lab identity
    means.  Previously it constructed a ``datetime.date`` and was rejected
    downstream by the schema's exact type checks.
    """

    profile = parse_lab_profile(_VALID_TEXT.replace("  lab_id: readonly-lab", "  lab_id: 2026-01-01"))
    assert profile.lab_id == "2026-01-01"
    assert type(profile.lab_id) is str


def test_host_implicit_resolvers_cannot_reach_the_profile_loader(tmp_path: Path) -> None:
    """A host resolver must not run while a lab profile is validated.

    ``yaml_implicit_resolvers`` is shared by reference from SafeLoader, and
    PyYAML calls each registered matcher's ``match()`` while scanning EVERY
    scalar.  Measured before the fix: a resolver registered through the ordinary
    ``yaml.SafeLoader.add_implicit_resolver(...)`` API deleted a file while an
    otherwise valid profile parsed SUCCESSFULLY -- no error, no signal.

    That is worse than the constructor-table defect, which at least failed the
    parse.  The victim file is the measurement.
    """

    import yaml

    from cryodaq.lab_profile.loader import _StrictLabProfileLoader

    assert _StrictLabProfileLoader.yaml_implicit_resolvers is not yaml.SafeLoader.yaml_implicit_resolvers

    victim = tmp_path / "victim.txt"
    victim.write_text("intact", encoding="utf-8")

    class SideEffectingMatcher:
        def match(self, value: str) -> None:
            victim.unlink(missing_ok=True)
            return None

    original = {key: list(value) for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()}
    yaml.SafeLoader.add_implicit_resolver("tag:yaml.org,2002:str", SideEffectingMatcher(), None)
    try:
        assert parse_lab_profile(_VALID_TEXT).lab_id == "readonly-lab"
        assert victim.read_text(encoding="utf-8") == "intact", "a host resolver ran during validation"
    finally:
        yaml.SafeLoader.yaml_implicit_resolvers.clear()
        yaml.SafeLoader.yaml_implicit_resolvers.update(original)


def test_spoofed_pattern_matchers_cannot_be_inherited(tmp_path: Path) -> None:
    """`isinstance` consults `__class__` and is spoofable; the check must be exact.

    Measured: a matcher declaring ``__class__ = re.Pattern`` passed an
    ``isinstance`` filter and its ``match()`` ran during a successful parse.
    """

    import re as _re

    import yaml

    victim = tmp_path / "victim.txt"
    victim.write_text("intact", encoding="utf-8")

    class SpoofedPattern:
        __class__ = _re.Pattern  # type: ignore[assignment]

        def match(self, value: str) -> None:
            victim.unlink(missing_ok=True)
            return None

    original = {key: list(value) for key, value in yaml.resolver.Resolver.yaml_implicit_resolvers.items()}
    yaml.resolver.Resolver.add_implicit_resolver("tag:yaml.org,2002:str", SpoofedPattern(), None)
    try:
        assert parse_lab_profile(_VALID_TEXT).lab_id == "readonly-lab"
        assert victim.read_text(encoding="utf-8") == "intact", "a spoofed matcher ran during validation"
    finally:
        yaml.resolver.Resolver.yaml_implicit_resolvers.clear()
        yaml.resolver.Resolver.yaml_implicit_resolvers.update(original)


def test_host_path_resolvers_cannot_reach_the_profile_loader() -> None:
    """`yaml_path_resolvers` is a third shared mutable table; it must be owned too.

    ``yaml.SafeLoader.add_path_resolver(...)`` retags nodes BY POSITION, so a
    host could force ``schema_version`` to a different type inside a lab profile.
    """

    import yaml

    from cryodaq.lab_profile.loader import _StrictLabProfileLoader

    assert _StrictLabProfileLoader.yaml_path_resolvers is not yaml.SafeLoader.yaml_path_resolvers

    original = dict(yaml.SafeLoader.yaml_path_resolvers)
    yaml.SafeLoader.add_path_resolver("tag:yaml.org,2002:int", ["schema_version"], str)
    try:
        assert _StrictLabProfileLoader.yaml_path_resolvers == {}
        assert parse_lab_profile(_VALID_TEXT).lab_id == "readonly-lab"
    finally:
        yaml.SafeLoader.yaml_path_resolvers.clear()
        yaml.SafeLoader.yaml_path_resolvers.update(original)


def test_cli_restores_an_aliased_stream_exactly_once() -> None:
    """A host may assign ONE wrapper to both stdout and stderr.

    Measured: a naive loop recorded that wrapper twice -- the second time in its
    already-retuned UTF-8 state -- then restored CP1252 and immediately
    overwrote it with UTF-8.
    """

    import io as _io

    from cryodaq.lab_profile.__main__ import main

    shared = _io.TextIOWrapper(_io.BytesIO(), encoding="cp1252", errors="strict")
    original_out, original_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = shared
    try:
        main([])
        encoding, errors = shared.encoding, shared.errors
    finally:
        sys.stdout, sys.stderr = original_out, original_err
    assert (encoding, errors) == ("cp1252", "strict"), (encoding, errors)


# Inherited attributes proved NOT to affect what a lab profile parses to.  Each
# needs a reason, because the whole point of the guard below is that "we looked
# at it and it is fine" must be written down rather than assumed.
_IRRELEVANT_INHERITED_STATE = {
    # The float constructor is not in the owned tag vocabulary at all, so these
    # two are unreachable.  See loader.py -- dropping the constructor was the
    # fix for a host poisoning them.
    "inf_value",
    "nan_value",
    # Likewise the timestamp tag: not owned, so its pattern is never consulted.
    "timestamp_regexp",
}


def test_no_inherited_pyyaml_state_is_left_unowned() -> None:
    """The systematic form of eight separate defects found one at a time.

    Subclassing ``yaml.SafeLoader`` inherits its mutable class state wholesale,
    and a host that uses ordinary public PyYAML APIs can then decide what a lab
    profile does.  Eight pieces were found individually in review --
    constructors, implicit resolvers, path resolvers, bool values, float support
    values, the DEFAULT_*_TAG defaults, the parser's tag handles, and the
    scanner's escape tables.  Finding a ninth the same way is not a plan.

    So the rule is enforced instead of the instances.  Every non-callable
    attribute reachable through the MRO must be either OWNED by the loader or
    listed above with a reason, AND an owned mutable value must not be the same
    object as the inherited one -- a name-only check passes for
    ``ESCAPE_CODES = yaml.SafeLoader.ESCAPE_CODES``, which owns nothing.
    """

    from cryodaq.lab_profile.loader import _StrictLabProfileLoader

    owned = vars(_StrictLabProfileLoader)
    unowned: dict[str, str] = {}
    aliased: dict[str, str] = {}
    for klass in _StrictLabProfileLoader.__mro__[1:]:
        if klass is object:
            continue
        for name, value in vars(klass).items():
            if name.startswith("__") or name in _IRRELEVANT_INHERITED_STATE:
                continue
            if callable(value) or isinstance(value, (staticmethod, classmethod, property)):
                continue
            if name not in owned:
                unowned.setdefault(name, f"{klass.__name__}.{name} = {type(value).__name__}")
                continue
            # Shadowed by NAME.  For anything mutable that is not enough: the
            # override must not simply alias the inherited object.
            if isinstance(value, (dict, list, set, bytearray)) and owned[name] is value:
                aliased.setdefault(name, f"{klass.__name__}.{name}")

    assert unowned == {}, (
        "inherited PyYAML state is neither owned nor justified: "
        f"{sorted(unowned.values())}. Own it in _StrictLabProfileLoader, or add it to "
        "_IRRELEVANT_INHERITED_STATE with the reason it cannot affect parsing."
    )
    assert aliased == {}, (
        f"these overrides ALIAS the inherited object rather than owning it: {sorted(aliased.values())}. "
        "Define the value in the package; assigning the inherited one owns nothing."
    )


def test_no_inherited_pyyaml_callable_comes_from_outside_pyyaml() -> None:
    """The METHOD chain, not just the data tables.

    ``yaml.load`` was replaceable; the fix bound ``get_single_data`` at import
    time; that was inherited from ``BaseConstructor`` and equally replaceable --
    the SAME defect one rung lower, found the round after. Fixing instances of a
    class one at a time is exactly what the data-table guard exists to stop, and
    the method chain had no equivalent.

    So this asserts provenance rather than enumerating rungs: every callable
    reachable through the loader's MRO must have been COMPILED INSIDE the
    installed PyYAML package or inside this repository. A host that rebinds any
    method -- at any depth, before or after import -- installs a function whose
    code object was compiled somewhere else, and that fails here.

    Provenance, deliberately, not bytecode pinning: hashing PyYAML's compiled
    code would break on every upstream release and teach the next author to
    re-baseline the guard instead of reading it.

    KNOWN LIMIT, stated because the alternative is overclaiming: this checks
    where a callable was compiled, not what it does. A replacement that reuses
    PyYAML's own code object is covered by ``__globals__`` below, but a patched
    PyYAML *installation* would pass. That is a supply-chain question this guard
    does not answer and does not pretend to.
    """

    import yaml

    from cryodaq.lab_profile.loader import _StrictLabProfileLoader

    yaml_root = str(Path(yaml.__file__).resolve().parent).lower()
    repo_root = str(REPO_ROOT.resolve()).lower()
    foreign: dict[str, str] = {}

    for klass in _StrictLabProfileLoader.__mro__:
        if klass is object:
            continue
        for name, value in vars(klass).items():
            function = getattr(value, "__func__", value)
            code = getattr(function, "__code__", None)
            if code is None:
                continue
            origin = str(Path(code.co_filename).resolve()).lower()
            if not (origin.startswith(yaml_root) or origin.startswith(repo_root)):
                foreign.setdefault(f"{klass.__name__}.{name}", origin)
                continue
            # Same code object, different globals is the other half: a
            # replacement built with types.FunctionType(original.__code__, {...})
            # is compiled in PyYAML's file yet resolves its global lookups
            # through the attacker's namespace.
            globals_name = getattr(function, "__globals__", {}).get("__name__", "?")
            if globals_name.split(".")[0] not in {"yaml", "cryodaq"}:
                foreign.setdefault(f"{klass.__name__}.{name}", f"globals={globals_name}")

    assert foreign == {}, (
        f"these callables on the loader's MRO did not come from PyYAML or this repository: {sorted(foreign.items())}. "
        "A host that rebinds a parse method at any depth lands here."
    )


# The exact values the loader must hold, restated HERE so the assertion does not
# read them back out of the thing it is checking.  A table copied from a
# pre-poisoned host would be a distinct object -- passing the identity check
# above -- but would not equal these.
#
# The first version pinned KEY SETS, and review found five ways through it in a
# single round: a replaced constructor under the same tag, an added resolver
# under a new first character, ESCAPE_REPLACEMENTS["n"] rebound to a forged
# string, bool_values["true"] set to the integer 1 (Python mapping equality
# treats 1 == True), and NON_PRINTABLE omitted entirely.  Every one kept the
# guard green while changing what a profile parses to.  So the whole surface is
# pinned now, by exact value AND exact type.
#
# Non-ASCII codepoints are spelled chr(0x....) on purpose.  Transcribing U+2028
# or U+D7FF as literal characters through an editor, a shell and a file encoding
# is exactly the "measured through a layer that normalises it" mistake this
# guard exists to catch; a numeric codepoint cannot be silently rewritten.
# Every constructor must be one of THIS PACKAGE'S functions.  Binding
# SafeConstructor's methods was not ownership: a host that rebound
# construct_yaml_str before the first import was captured verbatim, and the
# guard compared the poisoned function against itself.
_EXPECTED_CONSTRUCTOR_NAMES = {
    None: "_construct_undefined",
    "tag:yaml.org,2002:null": "_construct_null",
    "tag:yaml.org,2002:bool": "_construct_bool",
    "tag:yaml.org,2002:int": "_construct_int",
    "tag:yaml.org,2002:str": "_construct_str",
    "tag:yaml.org,2002:seq": "_construct_seq",
    "tag:yaml.org,2002:map": "_construct_map",
}
_EXPECTED_OWNED_TAGS = set(_EXPECTED_CONSTRUCTOR_NAMES) - {None}

_EXPECTED_NULL_SOURCE = "^(?:~|null|Null|NULL|)$"
_EXPECTED_BOOL_SOURCE = "^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$"
_EXPECTED_INT_SOURCE = "^[-+]?[0-9]+$"
_EXPECTED_PATTERN_FLAGS = re.UNICODE


def _expected_resolver_table() -> dict[str, list[tuple[str, str]]]:
    """The COMPLETE table: which first characters exist, and in what order.

    Pinning only the entries reachable from a first character this test already
    knew about let an added ``a``-prefixed catastrophic resolver through.  The
    key set is part of the property, not a detail of it.
    """

    table: dict[str, list[tuple[str, str]]] = {}
    for tag, source, first_characters in (
        ("tag:yaml.org,2002:null", _EXPECTED_NULL_SOURCE, "~nN"),
        ("tag:yaml.org,2002:bool", _EXPECTED_BOOL_SOURCE, "yYnNtTfFoO"),
        ("tag:yaml.org,2002:int", _EXPECTED_INT_SOURCE, "-+0123456789"),
    ):
        for character in first_characters:
            table.setdefault(character, []).append((tag, source))
    table.setdefault("", []).append(("tag:yaml.org,2002:null", _EXPECTED_NULL_SOURCE))
    return table


_EXPECTED_ESCAPE_CODES = {"x": 2, "u": 4, "U": 8}
_EXPECTED_DEFAULT_TAGS = {"!": "!", "!!": "tag:yaml.org,2002:"}
_EXPECTED_BOOL_VALUES = {
    "yes": True,
    "no": False,
    "true": True,
    "false": False,
    "on": True,
    "off": False,
}
# The full mapping, not just its keys.  Rebinding "n" from newline to "FORGED"
# made a quoted backslash-n escape parse as "readFORGEDonly" while a key-set
# check stayed green.
_EXPECTED_ESCAPE_REPLACEMENTS = {
    "0": chr(0x00),
    "a": chr(0x07),
    "b": chr(0x08),
    "t": chr(0x09),
    chr(0x09): chr(0x09),
    "n": chr(0x0A),
    "v": chr(0x0B),
    "f": chr(0x0C),
    "r": chr(0x0D),
    "e": chr(0x1B),
    " ": chr(0x20),
    '"': chr(0x22),
    "\\": chr(0x5C),
    "/": chr(0x2F),
    "N": chr(0x85),
    "_": chr(0xA0),
    "L": chr(0x2028),
    "P": chr(0x2029),
}
# The YAML 1.1 printable set, assembled from codepoints for the reason above.
_EXPECTED_NON_PRINTABLE_SOURCE = (
    "[^"
    + chr(0x09)
    + chr(0x0A)
    + chr(0x0D)
    + chr(0x20)
    + "-"
    + chr(0x7E)
    + chr(0x85)
    + chr(0xA0)
    + "-"
    + chr(0xD7FF)
    + chr(0xE000)
    + "-"
    + chr(0xFFFD)
    + chr(0x10000)
    + "-"
    + chr(0x10FFFF)
    + "]"
)


def _typed(value: object) -> object:
    """Canonical representation that distinguishes ``1`` from ``True``.

    Ordinary ``==`` does not.  ``{"true": 1} == {"true": True}`` is True, so the
    original boolean escape -- setting ``bool_values["true"]`` to the integer 1,
    which made ``schema_version: true`` validate as version 1 -- survived a plain
    dictionary comparison.
    """

    # EXACT types, never isinstance.  A dict SUBCLASS whose __getitem__ and
    # items() delegate to yaml.SafeLoader.ESCAPE_CODES canonicalises as an
    # ordinary dict under isinstance, so the pin stayed green while the loader
    # was still backed by host state -- and setting ESCAPE_CODES["q"] on the
    # host then made a quoted backslash-q escape parse as "A".  The container's
    # type is part of the property: a view over inherited tables is not
    # ownership.
    if type(value) is dict:
        return ("dict", sorted(((_typed(key), _typed(item)) for key, item in value.items()), key=repr))
    if type(value) is list:
        return ("list", [_typed(item) for item in value])
    if type(value) is tuple:
        return ("tuple", [_typed(item) for item in value])
    if type(value) is set:
        return ("set", sorted((_typed(item) for item in value), key=repr))
    if type(value) is frozenset:
        return ("frozenset", sorted((_typed(item) for item in value), key=repr))
    return (type(value).__name__, value)


def test_owned_pyyaml_values_are_the_expected_ones() -> None:
    """Identity is not enough either: a COPY of poisoned state is a distinct object.

    Pre-import poisoning was already shown to survive copying, so the values
    themselves are pinned against literals held in this test rather than read
    back from the loader -- by exact value and exact TYPE, across the whole
    surface rather than its key sets.
    """

    from cryodaq.lab_profile.loader import _StrictLabProfileLoader as loader

    assert _typed(loader.ESCAPE_CODES) == _typed(_EXPECTED_ESCAPE_CODES)
    assert _typed(loader.DEFAULT_TAGS) == _typed(_EXPECTED_DEFAULT_TAGS)
    assert _typed(loader.bool_values) == _typed(_EXPECTED_BOOL_VALUES)
    assert _typed(loader.ESCAPE_REPLACEMENTS) == _typed(_EXPECTED_ESCAPE_REPLACEMENTS)
    assert _typed(loader.yaml_multi_constructors) == _typed({})
    assert _typed(loader.yaml_path_resolvers) == _typed({})
    assert _typed(loader.DEFAULT_SCALAR_TAG) == _typed("tag:yaml.org,2002:str")
    assert _typed(loader.DEFAULT_SEQUENCE_TAG) == _typed("tag:yaml.org,2002:seq")
    assert _typed(loader.DEFAULT_MAPPING_TAG) == _typed("tag:yaml.org,2002:map")

    # WHICH CALLABLE runs for a tag, not merely which tags exist.  A host that
    # replaces the string constructor leaves the key set identical.
    #
    # Compared by IDENTITY against SafeConstructor's own functions, because
    # __module__ and __qualname__ are WRITABLE: a replacement that sets them to
    # "yaml.constructor.SafeConstructor.construct_yaml_str" satisfied the
    # previous introspection-text comparison while executing during a valid
    # parse.
    #
    # This used to resolve the expected callables from SafeConstructor -- the
    # same object the loader borrowed them from -- so a pre-import rebinding
    # poisoned BOTH SIDES and the comparison passed vacuously while the
    # replacement ran during a valid parse.  The constructors are now defined in
    # the package, so this compares against functions a host cannot reach
    # without editing this repository.  The behavioural and subprocess guards
    # below still exist because structure alone has been defeated four times.
    from cryodaq.lab_profile import loader as loader_module

    expected_functions = {tag: getattr(loader_module, name) for tag, name in _EXPECTED_CONSTRUCTOR_NAMES.items()}
    assert set(loader.yaml_constructors) == set(expected_functions)
    mismatched = sorted(
        str(tag) for tag, function in loader.yaml_constructors.items() if function is not expected_functions[tag]
    )
    assert mismatched == [], (
        f"these tags are served by a callable that is not PyYAML's own: {mismatched}. "
        "__module__/__qualname__ are writable, so only identity distinguishes them."
    )

    # The COMPLETE resolver table: keys, order, tags, pattern sources, flags.
    actual_resolvers = {
        key: [(tag, matcher.pattern) for tag, matcher in entries]
        for key, entries in loader.yaml_implicit_resolvers.items()
    }
    assert _typed(actual_resolvers) == _typed(_expected_resolver_table())
    for entries in loader.yaml_implicit_resolvers.values():
        for tag, matcher in entries:
            assert type(matcher) is re.Pattern, (tag, type(matcher))
            assert matcher.flags == _EXPECTED_PATTERN_FLAGS, (tag, matcher.flags)

    # NON_PRINTABLE gates the RAW stream.  With a never-matching pattern, a NUL
    # truncated the document, so a valid profile followed by forbidden trailing
    # content was accepted.  It is a compiled pattern: it cannot be mutated in
    # place, and the aliasing check above deliberately ignores it -- identity
    # would be a FALSE POSITIVE here anyway, because ``re.compile`` caches by
    # source and hands back upstream's own object for an identical local
    # literal.  Only the value carries information.
    assert loader.NON_PRINTABLE.pattern == _EXPECTED_NON_PRINTABLE_SOURCE
    assert loader.NON_PRINTABLE.flags == _EXPECTED_PATTERN_FLAGS


def test_owned_tables_produce_the_intended_parse() -> None:
    """A structural pin is worth nothing if it describes a parse nobody checks.

    Two behaviours the pinned tables exist to produce, asserted through the real
    public entry point rather than against the loader's attributes.
    """

    from cryodaq.lab_profile import LabProfileError, parse_lab_profile

    # A backslash-n escape must be a NEWLINE, not whatever a host says it is.
    # The observable consequence is rejection: the schema forbids Unicode
    # control characters in `lab_id`, so the correct escape FAILS validation.
    # That is the discriminator -- with ESCAPE_REPLACEMENTS["n"] rebound to a
    # printable string such as "FORGED", this same document is ACCEPTED and the
    # lab_id silently becomes "readFORGEDonly".
    with pytest.raises(LabProfileError, match="control character"):
        parse_lab_profile(_VALID_TEXT.replace("lab_id: readonly-lab", 'lab_id: "read\\nonly"'))

    # A boolean is not an integer version.
    with pytest.raises(LabProfileError):
        parse_lab_profile(_VALID_TEXT.replace("schema_version: 1", "schema_version: true"))


def _run_probe(script: str, tmp_path: Path) -> str:
    """Run one host-poisoning probe in a clean child and return its verdict line.

    A child process is not a stylistic choice: by pytest collection time this
    package is already imported, so no in-process test can exercise poisoning
    that happens BEFORE the first import.
    """

    environment = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "SystemRoot") if name in os.environ}
    environment["PYTHONPATH"] = str(REPO_ROOT / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True,
        text=True,
        env=environment,
        cwd=tmp_path,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    return completed.stdout.strip()


_ENTRY_POINT_BYPASS = r"""
import pathlib
import tempfile

import yaml

victim = pathlib.Path(tempfile.mkdtemp()) / "victim.txt"
victim.write_text("operator data", encoding="utf-8")

def _wrapper(stream, *args, **kwargs):
    victim.unlink()
    return {
        "schema_version": 1,
        "lab": {"lab_id": "forged", "display_name": "Forged"},
        "instruments": [{"type": "lakeshore_218s", "name": "LS1"}],
        "questions": [],
    }

yaml.load = _wrapper

from cryodaq.lab_profile import LabProfileError, parse_lab_profile

try:
    parse_lab_profile("not yaml at all")
except LabProfileError:
    print("rejected" if victim.exists() else "rejected-but-side-effect-ran")
else:
    print("ACCEPTED")
"""


_TOTAL_PARSER_COMPROMISE = r"""
from cryodaq.lab_profile import parse_lab_profile
import yaml.constructor


def _evil(self, node):
    # A parse result invented wholesale: the document is never read.
    return {
        "schema_version": 1,
        "lab": {"lab_id": "forged", "display_name": "Forged"},
        "instruments": [{"type": "keithley_2604b", "name": "SRC1"}],
        "questions": [],
    }


yaml.constructor.BaseConstructor.construct_document = _evil

try:
    profile = parse_lab_profile("hello: world\n")
except Exception as exc:
    print(type(exc).__name__)
else:
    print("ACCEPTED:" + ",".join(instrument.type for instrument in profile.instruments))
"""


def test_actuation_boundary_survives_a_fully_compromised_parser(tmp_path: Path) -> None:
    """The property this package actually protects, isolated from the parser.

    Rounds of work went into owning the loader's tables and entry point, and a
    residual remains that cannot be closed by descending further: rebinding an
    inherited composer/constructor method AFTER import replaces the parse
    entirely.  Measured -- a forged profile was returned and a file deleted, with
    no import ordering required.

    That residual is accepted, because an attacker who can execute arbitrary
    Python in the operator's process does not need YAML to do harm.  What must
    NOT depend on the parser is the actuation boundary, and it does not:
    ``schema.py`` re-derives instrument authority from BUILTIN_DRIVER_METADATA
    rather than trusting the parsed document.

    So this asserts the boundary under TOTAL parser compromise -- the strongest
    attacker the module admits -- rather than asserting the parser is
    uncompromisable, which it is not.
    """

    assert _run_probe(_TOTAL_PARSER_COMPROMISE, tmp_path) == "ActuationBoundaryError"


def test_host_cannot_replace_the_parse_entry_point(tmp_path: Path) -> None:
    """``yaml.load`` is a module attribute, looked up at CALL time.

    Measured before the fix: with ``yaml.load`` rebound to a wrapper that
    deleted a file and returned a valid-looking dict, ``parse_lab_profile("not
    yaml at all")`` returned a profile with ``lab_id == "forged"`` and the file
    was gone.  Every owned table was irrelevant because the strict loader was
    never constructed.  Ordinary monkey-patching, not a hostile edit here.
    """

    assert _run_probe(_ENTRY_POINT_BYPASS, tmp_path) == "rejected"


_PRE_IMPORT_CONSTRUCTOR_POISON = r"""
import builtins
import pathlib
import tempfile

import yaml.constructor

victim = pathlib.Path(tempfile.mkdtemp()) / "victim.txt"
victim.write_text("operator data", encoding="utf-8")
builtins._VICTIM = victim

_real = yaml.constructor.SafeConstructor.construct_yaml_str


def _evil(self, node):
    import builtins

    try:
        builtins._VICTIM.unlink()
    except OSError:
        pass
    return _real(self, node)


yaml.constructor.SafeConstructor.construct_yaml_str = _evil

from cryodaq.lab_profile import LabProfileError, parse_lab_profile

text = (
    "schema_version: 1\n"
    "lab:\n  lab_id: readonly-lab\n  display_name: Readonly Lab\n"
    "instruments:\n  - type: lakeshore_218s\n    name: LS1\n"
    "questions: []\n"
)
try:
    profile = parse_lab_profile(text)
except LabProfileError as exc:
    print("rejected:" + str(exc)[:40])
else:
    print("clean" if victim.exists() and profile.lab_id == "readonly-lab" else "POISON REACHED THE PARSE")
"""


def test_pre_import_constructor_rebinding_cannot_reach_the_profile_loader(tmp_path: Path) -> None:
    """Borrowing SafeConstructor's METHODS was never ownership.

    Measured before the fix: rebinding
    ``yaml.constructor.SafeConstructor.construct_yaml_str`` before the first
    import made the loader capture the replacement, a valid operator profile
    validated normally, and the replacement deleted a file while it did.  Both
    table guards stayed green, because the poisoned function was what "the
    expected constructor" resolved to on BOTH sides of the comparison.
    """

    assert _run_probe(_PRE_IMPORT_CONSTRUCTOR_POISON, tmp_path) == "clean"


def test_host_bool_values_cannot_reach_the_profile_loader() -> None:
    """`bool_values` is a fourth shared mutable table feeding construct_yaml_bool.

    Measured: with ``yaml.SafeLoader.bool_values["true"] = 1`` a profile
    containing ``schema_version: true`` validated successfully, because the
    boolean constructor calls through to ``self.bool_values``.
    """

    import yaml

    from cryodaq.lab_profile.loader import _StrictLabProfileLoader

    assert _StrictLabProfileLoader.bool_values is not yaml.SafeLoader.bool_values

    original = dict(yaml.SafeLoader.bool_values)
    yaml.SafeLoader.bool_values["true"] = 1
    try:
        with pytest.raises(LabProfileError):
            parse_lab_profile(_VALID_TEXT.replace("schema_version: 1", "schema_version: true"))
    finally:
        yaml.SafeLoader.bool_values.clear()
        yaml.SafeLoader.bool_values.update(original)


_PRE_IMPORT_REDOS = r"""
import re
import time

import yaml

# A GENUINE compiled pattern -- so a type check cannot reject it -- but one that
# backtracks catastrophically.  Registered BEFORE the first import, which is the
# ordering a filter-based defence could not survive.
yaml.resolver.Resolver.add_implicit_resolver("tag:yaml.org,2002:str", re.compile(r"^(a+)+$"), list("a"))

from cryodaq.lab_profile import LabProfileError, parse_lab_profile

document = (
    "schema_version: 1\n"
    "lab:\n  lab_id: " + "a" * 30 + "b\n  display_name: y\n"
    "instruments:\n  - type: lakeshore_218s\n    name: LS1\n"
    "questions: []\n"
)
started = time.monotonic()
try:
    parse_lab_profile(document)
except LabProfileError:
    pass
print("%.2f" % (time.monotonic() - started))
"""


# Generous enough that ordinary interpreter start-up on a loaded CI runner never
# trips it, small enough that a catastrophic pattern fails the job in seconds
# rather than at the outer job timeout.
_LINEAR_TIME_BUDGET_S = 60.0

_LINEAR_TIME_PROBE = r"""
from cryodaq.lab_profile import LabProfileError, parse_lab_profile

document = (
    "schema_version: 1\n"
    "lab:\n  lab_id: @@SCALAR@@\n  display_name: Readonly Lab\n"
    "instruments:\n  - type: lakeshore_218s\n    name: LS1\n"
    "questions: []\n"
)
profile = parse_lab_profile(document)
assert profile.lab_id == "@@SCALAR@@", repr(profile.lab_id)
print("ok")
"""


def _adversarial_scalars() -> list[tuple[str, str]]:
    """One probe per production resolver key, DERIVED from the table.

    A hand-written list covered only ``1``, ``-``, and lower-case ``t/y/o/n/~``
    while the loader also installs resolvers for ``+`` and upper-case
    ``Y/N/T/F/O``.  A catastrophic pattern reachable only from an omitted key
    would have stayed green here until an operator profile happened to contain
    that scalar.  Deriving the probes means adding a resolver key
    automatically adds its probe.
    """

    probes = []
    for key in sorted(_expected_resolver_table()):
        if not key:  # the empty-scalar key cannot start a 40-character run
            continue
        # Repeat the key, then break the match at the very end: the shape that
        # makes a backtracking pattern explode.
        probes.append((f"resolver key {key!r}", key * 40 + "x"))
    return probes


@pytest.mark.parametrize(("label", "scalar"), _adversarial_scalars())
def test_owned_resolver_patterns_are_linear_time(label: str, scalar: str) -> None:
    """The package's OWN resolvers must not backtrack, and must be proved so here.

    Every pattern this loader installs is fully anchored with no nested
    quantifier, which makes it linear.  This asserts that mechanically against
    adversarial NON-matches rather than trusting the reading, so a future edit
    that introduces a catastrophic pattern is caught by its own guard.

    Run in a SUBPROCESS with an enforced timeout, not in-process.  Measured
    against a deliberately catastrophic ``_INT_PATTERN`` of ``^([0-9]+)+$``, the
    in-process version never returned: the elapsed-time assertion below it was
    unreachable and the ``remaining`` CI partition would have hung until the
    outer job timeout instead of failing.  A guard whose failure mode is "the
    job hangs" reports nothing.
    """

    # PLAIN, not quoted.  A quoted scalar is never implicitly resolved, so the
    # first version of this test never reached the patterns at all and passed
    # against a deliberately catastrophic _INT_PATTERN.
    script = _LINEAR_TIME_PROBE.replace("@@SCALAR@@", scalar)
    environment = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "SystemRoot") if name in os.environ}
    environment["PYTHONPATH"] = str(REPO_ROOT / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script],
            capture_output=True,
            text=True,
            env=environment,
            timeout=_LINEAR_TIME_BUDGET_S,
            check=False,
        )
    except subprocess.TimeoutExpired:  # pragma: no cover - the regression path
        raise AssertionError(
            f"{label}: parsing {scalar[:12]}... did not finish within "
            f"{_LINEAR_TIME_BUDGET_S}s. An owned resolver backtracks."
        ) from None
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert completed.stdout.strip() == "ok", completed.stdout + completed.stderr


def test_host_regexes_cannot_stall_validation(tmp_path: Path) -> None:
    """A hostile-but-genuine regex must not reach the loader at all.

    An exact ``type(matcher) is re.Pattern`` filter accepts a real compiled
    pattern, so a catastrophically backtracking one registered BEFORE the first
    import was copied in.  Measured then: a 31-character scalar pushed
    validation past four seconds, breaking the bounded-parse contract this
    loader exists to provide.

    The resolver table is now built from patterns defined in the package, so
    nothing from the host is carried across.  Budget is generous on purpose --
    the failure it guards against was seconds, not milliseconds.
    """

    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "SystemRoot") if name in os.environ}
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", "-c", _PRE_IMPORT_REDOS],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert float(completed.stdout.strip()) < 1.0, completed.stdout


_PRE_IMPORT_FLOAT_POISON = r"""
import yaml

# Poison the float constructor's support values BEFORE the first import.
yaml.SafeLoader.inf_value = 1
yaml.SafeLoader.nan_value = 1

from cryodaq.lab_profile import LabProfileError, parse_lab_profile

body = (
    "lab:\n  lab_id: x\n  display_name: y\n"
    "instruments:\n  - type: lakeshore_218s\n    name: LS1\n"
    "questions: []\n"
)
outcomes = []
for scalar in (".inf", ".nan", "1.5"):
    try:
        parse_lab_profile("schema_version: " + scalar + "\n" + body)
    except LabProfileError:
        outcomes.append("rejected")
    else:
        outcomes.append("accepted")
print(",".join(outcomes))
"""


_PRE_IMPORT_TAG_POISON = r"""
import yaml

# The parser's tag-handle map and the resolver defaults are BOTH ordinary
# mutable class attributes.  Poison them before the first import -- the ordering
# a copy-based defence cannot survive.
yaml.parser.Parser.DEFAULT_TAGS["!"] = "tag:yaml.org,2002:"
yaml.SafeLoader.DEFAULT_SCALAR_TAG = "tag:yaml.org,2002:int"

from cryodaq.lab_profile import LabProfileError, parse_lab_profile

body = (
    "lab:\n  lab_id: x\n  display_name: y\n"
    "instruments:\n  - type: lakeshore_218s\n    name: LS1\n"
    "questions: []\n"
)

outcomes = []
try:
    parse_lab_profile('schema_version: !int "1"\n' + body)
except LabProfileError:
    outcomes.append("rejected")
else:
    outcomes.append("accepted")

# The ordinary document must still validate: owning this state must not break
# the normal path.
try:
    parse_lab_profile("schema_version: 1\n" + body)
except LabProfileError:
    outcomes.append("broken")
else:
    outcomes.append("valid")

print(",".join(outcomes))
"""


_PRE_IMPORT_ESCAPE_POISON = r"""
import yaml

# The SCANNER's escape tables decide what a backslash escape means inside a
# quoted scalar -- i.e. the accepted grammar itself.
yaml.SafeLoader.ESCAPE_REPLACEMENTS["q"] = "imaginary"

from cryodaq.lab_profile import LabProfileError, parse_lab_profile

body = (
    "lab:\n  lab_id: \"\\q\"\n  display_name: y\n"
    "instruments:\n  - type: lakeshore_218s\n    name: LS1\n"
    "questions: []\n"
)
try:
    profile = parse_lab_profile("schema_version: 1\n" + body)
except LabProfileError:
    print("rejected")
else:
    print("accepted:" + profile.lab_id)
"""


def test_pre_import_escape_poisoning_cannot_reach_the_profile_loader(tmp_path: Path) -> None:
    """A host must not be able to rewrite the accepted escape grammar.

    Measured before the scanner tables were owned: with
    ``ESCAPE_REPLACEMENTS["q"] = "imaginary"`` set before the first import, the
    normally invalid ``lab_id: "\\q"`` validated with ``lab_id == "imaginary"``.
    """

    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "SystemRoot") if name in os.environ}
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", "-c", _PRE_IMPORT_ESCAPE_POISON],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "rejected", completed.stdout + completed.stderr


def test_pre_import_tag_poisoning_cannot_reach_the_profile_loader(tmp_path: Path) -> None:
    """The parser's tag handles and the resolver defaults are inherited too.

    Measured before they were owned: with
    ``yaml.parser.Parser.DEFAULT_TAGS["!"]`` pointed at the yaml.org prefix,
    ``schema_version: !int "1"`` -- normally rejected as an unknown tag --
    constructed as the integer 1 and validated.

    Subprocess, because the ordering that matters is host-first, import-second.
    """

    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "SystemRoot") if name in os.environ}
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", "-c", _PRE_IMPORT_TAG_POISON],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "rejected,valid", completed.stdout + completed.stderr


def test_float_scalars_cannot_reach_the_schema(tmp_path: Path) -> None:
    """No field accepts a float, so the float constructor is not owned at all.

    ``construct_yaml_float`` reads the inherited, mutable ``inf_value`` and
    ``nan_value`` class attributes.  Measured before the fix, in a fresh process:
    ``yaml.SafeLoader.inf_value = 1`` made ``schema_version: .inf`` validate as
    the integer 1.  Removing the constructor removes the dependency outright,
    rather than owning yet more host state -- schema_version is an exact int and
    every other field an exact str, so nothing legitimate is lost.

    Runs in a subprocess: the ordering that matters is host-first, import-second.
    """

    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "SystemRoot") if name in os.environ}
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", "-c", _PRE_IMPORT_FLOAT_POISON],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "rejected,rejected,rejected", completed.stdout + completed.stderr


_PRE_IMPORT_POISON = r"""
import sys
import yaml

# Poison BEFORE the first cryodaq.lab_profile import.  Identity separation alone
# does not help here: a table COPIED at import time copies whatever is already
# there, so this ordering is the one that matters.
yaml.SafeLoader.bool_values["true"] = 1

from cryodaq.lab_profile import LabProfileError, parse_lab_profile

document = (
    "schema_version: true\n"
    "lab:\n  lab_id: x\n  display_name: y\n"
    "instruments:\n  - type: lakeshore_218s\n    name: LS1\n"
    "questions: []\n"
)
try:
    parse_lab_profile(document)
except LabProfileError:
    print("REJECTED")
else:
    print("ACCEPTED")
"""


def test_pre_import_bool_poisoning_cannot_reach_the_profile_loader(tmp_path: Path) -> None:
    """The host customises PyYAML, THEN the package is imported for the first time.

    This must run in a fresh process: by the time this module is collected,
    ``cryodaq.lab_profile`` is long since imported, so an in-process test can
    only ever exercise the easy ordering.  Measured with a copied table: the
    poisoned value was copied in and ``schema_version: true`` validated as 1.
    """

    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "SystemRoot") if name in os.environ}
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", "-c", _PRE_IMPORT_POISON],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "REJECTED", completed.stdout + completed.stderr


def test_cli_diagnostics_cannot_forge_a_status_line() -> None:
    """An error message must not be able to print this tool's own status lines.

    A validation error carries attacker-influenced text -- the supplied path and
    PyYAML's source snippets.  Measured: a filename containing a newline
    followed by ``actuation_supported: false`` emitted that as a standalone
    line, indistinguishable from the real boundary status.  That is the
    misreporting failure this artifact exists to avoid.
    """

    import io as _io

    from cryodaq.lab_profile.__main__ import main

    captured = _io.StringIO()
    original_err = sys.stderr
    sys.stderr = captured
    try:
        assert main(["missing\nactuation_supported: false\nunanswered questions: none"]) == 2
    finally:
        sys.stderr = original_err
    emitted = captured.getvalue()
    assert emitted.strip().count("\n") == 0, emitted
    for forged in ("actuation_supported: false", "unanswered questions: none"):
        assert not any(line.strip() == forged for line in emitted.splitlines()), emitted


def test_cli_restores_host_stream_configuration() -> None:
    """The CLI retunes stdout/stderr to UTF-8, and must put them back.

    Run in-process -- by an embedding host, or by the boundary probe's runpy
    path -- leaving the reconfiguration in place permanently changes the host's
    own streams.  Measured before the fix: two CP1252 wrappers were still UTF-8
    after ``main([])`` returned.
    """

    import io as _io

    from cryodaq.lab_profile.__main__ import main

    replacement_out = _io.TextIOWrapper(_io.BytesIO(), encoding="cp1252", errors="strict")
    replacement_err = _io.TextIOWrapper(_io.BytesIO(), encoding="cp1252", errors="strict")
    original_out, original_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = replacement_out, replacement_err
    try:
        main([])  # usage error path: still reconfigures the streams
        encodings = (replacement_out.encoding, replacement_err.encoding)
        errors = (replacement_out.errors, replacement_err.errors)
    finally:
        sys.stdout, sys.stderr = original_out, original_err
    assert encodings == ("cp1252", "cp1252"), encodings
    assert errors == ("strict", "strict"), errors


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
