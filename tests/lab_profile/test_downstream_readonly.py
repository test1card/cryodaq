"""Proof that the lab_profile package stays downstream, read-only, and inert."""

from __future__ import annotations

import ast
import builtins
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
        # A bare decorator is an invocation, so @property needs an entry here
        # now that decorators are checked.  Its removal turns the scan red.
        "property",
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
        # __setattr__ is deliberately ABSENT: allowing it by name let
        # ``yaml.__setattr__('safe_load', yaml.unsafe_load)`` rebind a module
        # attribute process-wide.  It has its own branch that pins the receiver
        # to ``object``, so an entry here would now be padding -- which
        # test_every_allowlist_entry_is_load_bearing proves.
        # "add" and "append" are deliberately ABSENT: they mutate their
        # receiver, so they are checked by _MUTATING_METHODS against the same
        # provably-local rule as assignment, and an entry here would be padding.
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
# Methods that MUTATE their receiver.  These are assignments in disguise, so
# they are held to the same provably-local-receiver rule.
_MUTATING_METHODS = frozenset(
    {"add", "append", "clear", "extend", "insert", "pop", "popitem", "remove", "setdefault", "update"}
)
_BUILTIN_NAMES = frozenset(dir(builtins))
_DUNDER = re.compile(r"^__[A-Za-z0-9_]+__$")


def _denied_dunder(name: str) -> bool:
    return bool(_DUNDER.match(name)) and name not in ALLOWED_DUNDERS


def _bound_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.arg):
        return [target.arg]
    return [sub.id for sub in ast.walk(target) if isinstance(sub, ast.Name)]


def _bindings(node: ast.AST):
    """Every (bound names, bound value) pair, over Python's binding grammar.

    This enumerates the LANGUAGE's binding forms, which are a closed and
    documented set, rather than the spellings an attacker might choose --
    handling only ``ast.Assign`` lost provenance the moment an alias was written
    as ``Loader: type = SafeLoader`` or ``(Loader,) = (SafeLoader,)``, and
    omitting parameter defaults lost it again for
    ``def poison(Loader=SafeLoader)``.
    """

    if isinstance(node, ast.Assign):
        yield [name for target in node.targets for name in _bound_names(target)], node.value
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
        if node.value is not None:
            yield _bound_names(node.target), node.value
    elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        yield _bound_names(node.target), node.iter
    elif isinstance(node, ast.withitem):
        if node.optional_vars is not None:
            yield _bound_names(node.optional_vars), node.context_expr
    elif isinstance(node, ast.Match):
        # `match SafeLoader: case Loader:` binds Loader to the SAME object.
        for case in node.cases:
            for captured in ast.walk(case.pattern):
                name = getattr(captured, "name", None)
                if isinstance(name, str):
                    yield [name], node.subject
                rest = getattr(captured, "rest", None)
                if isinstance(rest, str):
                    yield [rest], node.subject
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        # A default binds the SAME object to the parameter name on every call.
        signature = node.args
        positional = [*signature.posonlyargs, *signature.args]
        offset = len(positional) - len(signature.defaults)
        for parameter, default in zip(positional[offset:], signature.defaults):
            yield [parameter.arg], default
        for parameter, default in zip(signature.kwonlyargs, signature.kw_defaults):
            if default is not None:
                yield [parameter.arg], default


def _aliases_foreign(value: ast.expr, foreign: set[str]) -> bool:
    """True when ``value`` hands over a foreign object itself, not a new one.

    A bare name, or a tuple/list of them, is an ALIAS: the same object gets a
    second name.  A call such as ``Path(path)`` merely mentions a foreign name
    and produces a fresh object, so it is deliberately not treated as one --
    otherwise every ordinary local in the package would be marked foreign.
    """

    # FAIL CLOSED.  Enumerating identity-preserving expression forms did not
    # terminate: bare names, then attributes, then containers, then
    # ``(SafeLoader,)[0]`` -- and subscripts, conditionals, comprehensions,
    # walrus and boolean operators were all still waiting.  So the rule is
    # inverted.  A binding value that MENTIONS a foreign name is treated as an
    # alias unless it is a call, because a call is the one construct that
    # reliably produces a NEW object: ``Path(path)`` yields a fresh Path, while
    # every non-call expression can hand back the foreign object itself.
    # Over-approximating is safe here -- it can only mark more names foreign,
    # and a violation still requires an actual assignment INTO one of them.
    # Calls are NOT exempt either.  ``{'x': yaml.SafeLoader}.get('x')`` is a
    # call that returns the foreign object itself, so "a call produces a fresh
    # object" was simply false.  There is no expression form that can be trusted
    # to launder provenance, so none is exempt: mentioning a foreign name
    # anywhere in a bound value makes the bound name foreign.  This
    # over-approximates -- ``Path(path)`` marks ``selected`` foreign too -- which
    # is harmless, because a violation additionally requires a mutation THROUGH
    # the name, and the package never does that to its own locals.
    return any(isinstance(node, ast.Name) and node.id in foreign for node in ast.walk(value))


_FRESH = (
    ast.Dict,
    ast.List,
    ast.Set,
    ast.Tuple,
    ast.DictComp,
    ast.ListComp,
    ast.SetComp,
    ast.GeneratorExp,
    ast.Constant,
)


_FRESH_CALLS = frozenset({"bytearray", "dict", "frozenset", "list", "set", "sorted", "tuple"})


def _provably_local(tree: ast.AST, foreign: set[str], shadowed: set[str]) -> set[str]:
    """Names EVERY binding of which is a fresh literal in this file.

    This is the inverse of chasing provenance.  Tracking where a foreign object
    came from did not terminate -- aliases, attributes, containers, calls,
    parameters, returns, pattern captures and cross-module exports were each a
    separate route, and resolving call targets properly would mean writing a
    scope-aware interprocedural analyser inside a test.

    So the burden is flipped.  A mutation is allowed only when its receiver is
    provably fresh: a container literal bound here, or ``self``.  Nothing needs
    to be known about foreign objects at all, and a laundering route cannot
    help, because whatever it produces is still not a literal bound in this
    file.
    """

    def fresh(value: ast.expr) -> bool:
        # A literal that CONTAINS a foreign object does not make its elements
        # fresh: ``x = [SafeLoader]`` then ``x[0].yaml_constructors[...] = ...``
        # mutates the foreign loader, not the list.
        if any(isinstance(sub, ast.Name) and sub.id in foreign for sub in ast.walk(value)):
            return False
        if isinstance(value, _FRESH):
            return True
        # ``set()``, ``dict()``, ``{}``-equivalents: builtin container
        # constructors always return a NEW object.  Guarded against shadowing --
        # ``from yaml import SafeLoader as set`` would make ``set()`` foreign.
        return (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in _FRESH_CALLS
            and value.func.id not in foreign
            and value.func.id not in shadowed
        )

    bound: dict[str, list[ast.expr]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                # BARE names only.  ``result[key] = ...`` is a mutation OF
                # ``result``, not a binding of it, and counting it as one made
                # ``result`` look re-bound to a call and therefore not local.
                if isinstance(target, ast.Name) and node.value is not None:
                    bound.setdefault(target.id, []).append(node.value)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            # A parameter is never a provably fresh local: its value comes from
            # the caller.
            for parameter in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                bound.setdefault(parameter.arg, []).append(node)
    return {name for name, values in bound.items() if values and all(fresh(v) for v in values)}


def _forbidden_mutation(node: ast.AST, target: ast.expr, local_receivers: set[str]) -> bool:
    """True unless this mutation's receiver is provably a fresh local object."""

    if not isinstance(target, (ast.Attribute, ast.Subscript)):
        # A bare rebinding only moves a label; augmented assignment mutates in
        # place first (``constructors |= {...}`` changes the foreign dict).
        if not isinstance(node, ast.AugAssign) or not isinstance(target, ast.Name):
            return False
        return target.id != "self" and target.id not in local_receivers
    receiver = target
    while isinstance(receiver, (ast.Attribute, ast.Subscript)):
        receiver = receiver.value
    if isinstance(receiver, ast.Name) and (receiver.id == "self" or receiver.id in local_receivers):
        return False
    return True


def _mutates_foreign(node: ast.AST, target: ast.expr, foreign: set[str]) -> bool:
    """True when this binding reaches a foreign object rather than a local label.

    Provenance is read from the COMPLETE target expression, not from a bare-name
    root: ``(SafeLoader,)[0].yaml_constructors['t'] = None`` needs no
    intermediate binding at all, and peeling attributes and subscripts until a
    ``Name`` appears never reaches the tuple.
    """

    # Follow the RECEIVER spine -- the ``.value`` chain of attributes and
    # subscripts -- to the object actually being mutated.  Walking the whole
    # target instead would count a subscript INDEX: ``result[key] = ...`` mutates
    # ``result``, and ``key`` merely selects a slot, so a foreign ``key`` would
    # be a false positive.  Peeling to a bare Name is not enough either, because
    # ``(SafeLoader,)[0].yaml_constructors['t'] = None`` never reaches one.
    receiver = target
    while isinstance(receiver, (ast.Attribute, ast.Subscript)):
        receiver = receiver.value
    if not any(isinstance(sub, ast.Name) and sub.id in foreign for sub in ast.walk(receiver)):
        return False
    if isinstance(target, ast.Name):
        # A bare rebinding only moves a local label -- EXCEPT augmented
        # assignment, which mutates in place through __ior__/__iadd__ before
        # rebinding, so ``constructors |= {...}`` changes the foreign dict.
        return isinstance(node, ast.AugAssign)
    return True


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


def _import_violations(source: str, *, label: str, base: str = PACKAGE_MODULE, root: str = PACKAGE_MODULE) -> list[str]:
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
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update((alias.asname or alias.name).split(".", 1)[0] for alias in node.names)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local_names.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            origin = _resolve_import(node.module or "", node.level, base=base)
            if origin == root or origin.startswith(f"{root}.") or origin in ALLOWED_CRYODAQ_IMPORTS:
                local_names.update(alias.asname or alias.name for alias in node.names)
            else:
                # A ``from``-imported symbol is a FOREIGN object that lives in
                # another module, so assigning into it mutates process-wide
                # state outside the boundary exactly as ``os.environ[...] = ...``
                # does.  Tracking only ``import x`` missed it, and
                # ``from yaml import SafeLoader;
                # SafeLoader.yaml_constructors['tag:yaml.org,2002:str'] = None``
                # poisons the safe-YAML constructor table for the whole host
                # while leaving no file, variable, path or process trace.
                imported_modules.update(alias.asname or alias.name for alias in node.names)

    # An imported name is NEVER local, even if some nested scope also defines
    # it.  ``local_names`` is collected file-wide, so ``from yaml import
    # add_constructor as mutate`` plus a nested ``def mutate`` made a
    # module-level ``mutate(...)`` call look like an in-boundary helper while it
    # actually rewrote PyYAML's global constructor table.
    local_names -= imported_modules

    # An alias of a foreign binding is still foreign.  ``from yaml import
    # SafeLoader; Loader = SafeLoader`` loses provenance unless the rebind is
    # followed, and the mutation then lands on a name the scan does not
    # recognise.  Iterated to a fixpoint so chains (``a = SafeLoader; b = a``)
    # are covered too, not merely one hop.
    # A call to an in-package helper binds its arguments to that helper's
    # parameters, so passing a foreign object into an ordinary function
    # laundered it: ``def poison(loader): ...; poison(SafeLoader)`` named nothing
    # foreign inside the body.  Rejecting such calls is not an option -- the
    # loader legitimately passes parsed foreign values into its own helpers --
    # so provenance is propagated into the parameter instead.
    definitions = {
        node.name: node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            for names, value in _bindings(node):
                if not _aliases_foreign(value, imported_modules):
                    continue
                for name in names:
                    if name not in imported_modules:
                        imported_modules.add(name)
                        changed = True
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            target = definitions.get(node.func.id)
            if target is None:
                continue
            parameters = [*target.args.posonlyargs, *target.args.args]
            pairs = list(zip(parameters, node.args))
            pairs += [
                (parameter, keyword.value)
                for keyword in node.keywords
                for parameter in [*parameters, *target.args.kwonlyargs]
                if keyword.arg == parameter.arg
            ]
            for parameter, argument in pairs:
                if _aliases_foreign(argument, imported_modules) and parameter.arg not in imported_modules:
                    imported_modules.add(parameter.arg)
                    changed = True

    # Names the file itself defines, so a helper called ``list`` cannot pass for
    # the builtin container constructor.
    shadowing = {
        node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    local_receivers = _provably_local(tree, imported_modules, shadowing)
    violations: list[str] = []

    # Shadowing a BUILTIN hides what a call does: `from os import
    # get_inheritable as len` and `def list(): ...` both put a foreign or local
    # callable behind a name the capability allowlist trusts.  The package
    # shadows none, so this costs nothing and closes the class.
    for node in ast.walk(tree):
        bound: list[str] = []
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound = [(alias.asname or alias.name).split(".", 1)[0] for alias in node.names]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound = [node.name]
        for name in bound:
            if name in _BUILTIN_NAMES:
                violations.append(f"{label}: binding {name!r} shadows a builtin and hides what a call does")

    # A bare decorator INVOKES its object without producing an ast.Call, so
    # `@settrace` installed process-wide tracing past a call-only capability
    # filter.  Decorators are classified as invocations under the same rules.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                continue  # already handled as a call below
            if isinstance(decorator, ast.Name) and decorator.id not in ALLOWED_CALL_NAMES | local_names:
                violations.append(f"{label}: decorator {decorator.id} invokes a capability that is not allowlisted")
            elif isinstance(decorator, ast.Attribute) and decorator.attr not in ALLOWED_METHOD_NAMES:
                violations.append(f"{label}: decorator .{decorator.attr} invokes a capability that is not allowlisted")

    # A MODULE-LEVEL alias of a foreign object is exportable: another file in the
    # package can `from .source import Loader`, which this scan classifies as an
    # in-package import, and mutate it there with no foreign name in sight.
    # Rejecting the export is simpler and tighter than propagating provenance
    # across files, and the package has no legitimate need for one.
    for statement in tree.body:
        for names, value in _bindings(statement):
            if not _aliases_foreign(value, imported_modules):
                continue
            for name in names:
                violations.append(
                    f"{label}: module-level name {name!r} aliases a foreign object and can be re-imported "
                    "elsewhere in the package, laundering its provenance"
                )
    for node in ast.walk(tree):
        # A denied dunder carried by an IMPORT ALIAS never appears as a Name,
        # an Attribute or a string constant in the body, so every dunder rule
        # below missed it: ``from yaml import __builtins__ as b`` hands over the
        # interpreter builtins through an otherwise allowlisted module.  The
        # imported symbol name is checked here, before the module allowance.
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
                # `from yaml import *` binds names this AST cannot enumerate, so
                # provenance recorded only the literal '*' and every later
                # mutation of a wildcard-bound name looked local.
                violations.append(f"{label}: wildcard import from {module!r} hides which names it binds")
                continue
            if module == "sys" and any(alias.name == "modules" for alias in node.names):
                violations.append(f"{label}: importing sys.modules by name bypasses the static import boundary")
                continue
            if top_level in ALLOWED_STDLIB_MODULES or top_level == "yaml":
                continue
            if module == root or module.startswith(f"{root}."):
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
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and any(
            isinstance(t, ast.Name) and t.id in ALLOWED_CALL_NAMES | ALLOWED_METHOD_NAMES
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
        ):
            # ``print = open`` rebinds an allowlisted spelling to a denied
            # capability, so the name in the allowlist stops meaning what it says.
            violations.append(f"{label}: rebinding an allowlisted capability name hides what the call does")
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)) and any(
            # THROUGH the name, not the name itself.  ``X.y = ...``, ``X[...] = ...``
            # and ``del X.y`` reach the foreign object; a bare ``X = ...`` only
            # rebinds a local label and changes nothing outside this module.  The
            # distinction matters because provenance now propagates fail-closed,
            # so ``args = sys.argv[1:]`` marks ``args`` foreign even though the
            # slice is a fresh list -- without this, that ordinary line in
            # __main__.py would be reported as a boundary violation.
            _forbidden_mutation(node, target, local_receivers)
            for target in (
                node.targets
                if isinstance(node, ast.Assign)
                else node.targets
                if isinstance(node, ast.Delete)
                else [node.target]
            )
        ):
            # Mutation WITHOUT a call: os.environ[...] = ..., sys.path[:] = ...,
            # del os.environ[...].  A call-only capability filter never sees these,
            # and os.environ writes can flip documented runtime bypasses.
            violations.append(
                f"{label}: mutating through a receiver that is not a provably local literal reaches "
                "state outside the boundary"
            )
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
            elif isinstance(func, ast.Attribute) and func.attr == "__setattr__":
                # Allowing this by NAME let `yaml.__setattr__('safe_load',
                # yaml.unsafe_load)` rebind a module attribute process-wide.  The
                # package's only legitimate use is the frozen-dataclass idiom, so
                # the receiver is pinned rather than the method name allowlisted.
                receiver_ok = isinstance(func.value, ast.Name) and func.value.id == "object"
                # The mutated object is the FIRST ARGUMENT, not the receiver:
                # `object.__setattr__(sys, 'argv', [])` satisfies an
                # object-receiver check while rewriting sys.argv.
                target_ok = bool(node.args) and isinstance(node.args[0], ast.Name) and node.args[0].id == "self"
                if not (receiver_ok and target_ok):
                    violations.append(
                        f"{label}: __setattr__ is permitted only as object.__setattr__(self, ...) "
                        "on the instance being built"
                    )
            elif isinstance(func, ast.Attribute) and func.attr in _MUTATING_METHODS:
                # `sys.meta_path.append(None)` rewrites the host's import
                # machinery.  A mutating method is an assignment in disguise, so
                # its receiver is held to the same provably-local standard.
                receiver = func.value
                while isinstance(receiver, (ast.Attribute, ast.Subscript)):
                    receiver = receiver.value
                if not (isinstance(receiver, ast.Name) and (receiver.id == "self" or receiver.id in local_receivers)):
                    violations.append(
                        f"{label}: .{func.attr}() mutates a receiver that is not a provably local literal"
                    )
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
            elif isinstance(func, ast.Attribute) and func.attr == "load":
                # yaml.load is safe only with the bounded in-package Loader;
                # Loader=yaml.UnsafeLoader reintroduces arbitrary construction.
                loaders = [k.value for k in node.keywords if k.arg == "Loader"]
                if not loaders or not all(isinstance(v, ast.Name) and v.id in local_names for v in loaders):
                    violations.append(f"{label}: .load() must pass an in-package Loader, not an external one")
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
        # A ``from``-imported symbol is a foreign object; assigning into it
        # poisons process-wide state with no file, variable, path or process
        # trace.  Tracking only ``import x`` bindings missed every one of these.
        "from yaml import SafeLoader\nSafeLoader.yaml_constructors['tag:yaml.org,2002:str'] = None",
        "from yaml import SafeLoader as L\nL.yaml_constructors['tag:yaml.org,2002:str'] = None",
        "from os import environ\nenviron['CRYODAQ_ALLOW_BROKEN_SQLITE'] = '1'",
        "from sys import path\npath[:] = ['/tmp/attacker']",
        "from yaml import SafeLoader\ndel SafeLoader.yaml_constructors",
        # Aliases of a foreign binding, across the binding grammar.  Without
        # fixpoint propagation each of these loses provenance and the mutation
        # lands on a name the scan does not recognise as foreign.
        "from yaml import SafeLoader\nLoader = SafeLoader\nLoader.yaml_constructors['t'] = None",
        "from yaml import SafeLoader\na = SafeLoader\nb = a\nb.yaml_constructors['t'] = None",
        "from yaml import SafeLoader\nLoader: type = SafeLoader\nLoader.yaml_constructors['t'] = None",
        "from yaml import SafeLoader\n(Loader,) = (SafeLoader,)\nLoader.yaml_constructors['t'] = None",
        "from yaml import SafeLoader\nfor Loader in (SafeLoader,):\n    Loader.yaml_constructors['t'] = None",
        "from yaml import SafeLoader\n(Loader := SafeLoader)\nLoader.yaml_constructors['t'] = None",
        "from os import environ\nE = environ\nE['CRYODAQ_ALLOW_BROKEN_SQLITE'] = '1'",
        # A parameter DEFAULT binds the same object on every call.
        "from yaml import SafeLoader\ndef poison(Loader=SafeLoader):\n    Loader.yaml_constructors['t'] = None",
        "from yaml import SafeLoader\ndef poison(*, Loader=SafeLoader):\n    Loader.yaml_constructors['t'] = None",
        "from os import environ\nf = lambda E=environ: E.__setitem__('CRYODAQ_ALLOW_BROKEN_SQLITE', '1')",
        # Indirect, identity-preserving expressions.  Enumerating these forms is
        # exactly what stopped terminating, so provenance now fails closed on
        # any non-call expression mentioning a foreign name; these are the
        # registered evidence that it does.
        "from yaml import SafeLoader\ndef p(Loader=(SafeLoader,)[0]):\n    Loader.yaml_constructors['t'] = None",
        "from yaml import SafeLoader\nL = (SafeLoader,)[0]\nL.yaml_constructors['t'] = None",
        "from yaml import SafeLoader\nL = SafeLoader if True else None\nL.yaml_constructors['t'] = None",
        "from yaml import SafeLoader\nL = [SafeLoader for _ in (1,)][0]\nL.yaml_constructors['t'] = None",
        "from yaml import SafeLoader\nL = SafeLoader or None\nL.yaml_constructors['t'] = None",
        "from yaml import SafeLoader\nL = {'k': SafeLoader}['k']\nL.yaml_constructors['t'] = None",
        # A CALL can preserve identity too, so no expression form is exempt.
        "import yaml\nLoader = {'x': yaml.SafeLoader}.get('x')\nLoader.yaml_constructors['t'] = None",
        # In-place mutation through the augmented-assignment protocol, on a bare
        # name -- ``dict.__ior__`` changes the foreign dict before rebinding.
        "from yaml import SafeLoader\nconstructors = SafeLoader.yaml_constructors\nconstructors |= {'t': None}",
        # Pattern-matching capture: ``Loader is SafeLoader``.
        "from yaml import SafeLoader\nmatch SafeLoader:\n    case Loader:\n        Loader.yaml_constructors['t'] = 1",
        # Wildcard: the bound names cannot be enumerated from this AST at all.
        "from yaml import *\nSafeLoader.yaml_constructors['t'] = None",
        "from os import *\nenviron['CRYODAQ_ALLOW_BROKEN_SQLITE'] = '1'",
        # No intermediate binding: the receiver is reached through a tuple, so
        # peeling the target to a bare Name never finds it.
        "from yaml import SafeLoader\n(SafeLoader,)[0].yaml_constructors['t'] = None",
        # Laundered through an ordinary argument: nothing foreign is named in
        # the body at all.
        "from yaml import SafeLoader\ndef poison(loader):\n    loader.yaml_constructors['t'] = 1\npoison(SafeLoader)",
        "from yaml import SafeLoader\ndef p(*, ldr):\n    ldr.yaml_constructors['t'] = 1\np(ldr=SafeLoader)",
        # A nested definition must not legitimize a module-level foreign call.
        "from yaml import add_constructor as m\ndef helper():\n    def m(x):\n        return x\nm('t', None)",
        # Laundering routes that a name-only call map cannot resolve: a
        # duplicate helper name, a method rather than a function, and a return
        # value.  None of these is chased -- the receiver simply is not a
        # provably local literal.
        (
            "from yaml import SafeLoader\ndef q(l):\n    l.yaml_constructors['t'] = 1\n"
            "def h():\n    def q(x, y):\n        return x\nq(SafeLoader)"
        ),
        (
            "from yaml import SafeLoader\nclass H:\n    def get(self, l):\n"
            "        l.yaml_constructors['t'] = 1\nH().get(SafeLoader)"
        ),
        "from yaml import SafeLoader\ndef g():\n    return SafeLoader\nL = g()\nL.yaml_constructors['t'] = 1",
        # Rebinding a module attribute process-wide through __setattr__.
        "import yaml\nyaml.__setattr__('safe_load', yaml.unsafe_load)",
        # The mutated object is __setattr__'s FIRST ARGUMENT, not its receiver.
        "import sys\nobject.__setattr__(sys, 'argv', [])",
        # A shadowed container constructor is not the builtin.
        ("from yaml import SafeLoader\ndef list():\n    return SafeLoader\ndef h():\n    x = list()\n    x.f = 1"),
        # A fresh container holding a foreign object does not make it fresh.
        "from yaml import SafeLoader\ndef h():\n    x = [SafeLoader]\n    x[0].yaml_constructors['t'] = 1",
        # A mutating method is an assignment in disguise.
        "import sys\nsys.meta_path.append(None)",
        # Foreign callables hidden behind allowlisted builtin spellings.
        "from os import get_inheritable as len, set_inheritable as print\nprint(1, not len(1))",
        # A bare decorator invokes without producing an ast.Call.
        "from sys import settrace\n@settrace\ndef f(frame, event, arg):\n    return None",
        # The alias is an ATTRIBUTE of a foreign module, which is still the same
        # object rather than a fresh one.
        "import yaml\nLoader = yaml.SafeLoader\nLoader.yaml_constructors['t'] = None",
        "import yaml\nL: type = yaml.SafeLoader\nL.yaml_constructors['t'] = None",
        # The dunder is carried by an import alias, so no dunder ever appears as
        # a Name, Attribute or string constant in the body.
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
        # Round 10: the allowlisted SPELLING is not the capability.  Rebinding,
        # receiver and argument values each let an allowed name do a denied thing.
        "print = open\nprint('config/safety.yaml', 'w')",
        "from pathlib import Path\nPath('config/safety.yaml').open('w')",
        "from pathlib import Path\nPath('config/safety.yaml').open(mode='a')",
        "import yaml\nyaml.load(text, Loader=yaml.UnsafeLoader)",
        "import yaml\nyaml.load(text)",
        # Round 10: mutation performed without any call at all.
        "import os\nos.environ['CRYODAQ_ALLOW_BROKEN_SQLITE'] = '1'",
        "import os\nos.environ['CRYODAQ_ROOT'] = '/tmp/attacker'",
        "import sys\nsys.path[:] = ['/tmp/attacker']",
        "import os\ndel os.environ['PATH']",
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


def test_module_level_alias_cannot_launder_provenance_across_files(tmp_path: Path) -> None:
    """One module exports a foreign alias; another imports and mutates it.

    The importer's ``from .source import Loader`` is an in-package import, so
    nothing foreign is named there at all, and the exporter merely rebinds a
    name.  Neither file looks hostile on its own, which is why the export itself
    has to be the violation.
    """

    package = tmp_path / "pkg"
    package.mkdir()
    (package / "source.py").write_text("from yaml import SafeLoader\nLoader = SafeLoader\n", encoding="utf-8")
    (package / "__init__.py").write_text(
        "from .source import Loader\nLoader.yaml_constructors['t'] = None\n", encoding="utf-8"
    )
    violations = _scan_package(package, package_module="pkg")
    assert any("laundering" in entry for entry in violations), violations


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
