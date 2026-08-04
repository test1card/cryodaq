"""Strict YAML loader for Lab Profile v1 documents.

This is an offline validation artifact, not the engine startup path: the full
symlink/TOCTOU/hard-link defense of ``cryodaq.storage.channel_descriptors`` is
deliberately not replicated here.  The path must still name a regular file and
the document stays under a hard byte ceiling with a bounded strict grammar.
All failures raise ``LabProfileError`` (or a subclass) with no exception
chaining noise.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

import yaml

from .schema import (
    LabProfileError,
    LabProfileV1,
    ProfileInstrument,
    QuestionKind,
    UnansweredQuestion,
)

MAX_LAB_PROFILE_BYTES: Final = 65_536
MAX_LAB_PROFILE_DEPTH: Final = 8

_ROOT_KEYS: Final = frozenset({"schema_version", "lab", "instruments", "questions"})
_LAB_KEYS: Final = frozenset({"lab_id", "display_name"})
_INSTRUMENT_ALLOWED_KEYS: Final = frozenset({"type", "name", "note"})
_INSTRUMENT_REQUIRED_KEYS: Final = frozenset({"type", "name"})
_QUESTION_KEYS: Final = frozenset({"kind", "subject", "summary"})

_INCUMBENT_SURFACES: Final = "safety, thresholds, interlocks, alarms, overrides, channels, actuation"

# The exact tag vocabulary a lab profile may contain.  FLOAT IS ABSENT: no field
# in the schema accepts one -- schema_version is an exact int and every other
# field an exact str -- and construct_yaml_float reads the inherited, mutable
# ``inf_value``/``nan_value`` class attributes.  Measured: a host setting
# ``yaml.SafeLoader.inf_value = 1`` made ``schema_version: .inf`` validate as
# the integer 1.  Dropping the constructor removes that dependency outright,
# which is better than owning yet more host state.  Module level so both
# the constructor table and the resolver table below can reference it: a
# class-body comprehension cannot see class scope.
_OWNED_TAGS: Final = frozenset(
    {
        "tag:yaml.org,2002:null",
        "tag:yaml.org,2002:bool",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:str",
        "tag:yaml.org,2002:seq",
        "tag:yaml.org,2002:map",
    }
)


_NULL_PATTERN: Final = re.compile(r"^(?:~|null|Null|NULL|)$")
_BOOL_PATTERN: Final = re.compile(r"^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$")
_INT_PATTERN: Final = re.compile(r"^[-+]?[0-9]+$")


def _build_implicit_resolvers() -> dict[str | None, list[tuple[str, re.Pattern[str]]]]:
    """The implicit-resolution table, owned outright and keyed as PyYAML expects.

    PyYAML looks up candidate resolvers by the scalar's FIRST CHARACTER, with
    ``""`` for the empty scalar, so the first characters each pattern can match
    are listed alongside it.
    """

    table: dict[str | None, list[tuple[str, re.Pattern[str]]]] = {}
    for tag, pattern, first_characters in (
        ("tag:yaml.org,2002:null", _NULL_PATTERN, "~nN"),
        ("tag:yaml.org,2002:bool", _BOOL_PATTERN, "yYnNtTfFoO"),
        ("tag:yaml.org,2002:int", _INT_PATTERN, "-+0123456789"),
    ):
        for character in first_characters:
            table.setdefault(character, []).append((tag, pattern))
    # The empty scalar resolves to null, exactly as upstream does.
    table.setdefault("", []).append(("tag:yaml.org,2002:null", _NULL_PATTERN))
    return table


def _scalar_text(node: yaml.Node) -> str:
    """The scalar's own text, read off the node rather than via an inherited method."""

    if not isinstance(node, yaml.ScalarNode):
        raise yaml.constructor.ConstructorError(None, None, f"expected a scalar node, found {node.id}", node.start_mark)
    return node.value


def _construct_undefined(loader: yaml.Loader, node: yaml.Node) -> object:
    raise yaml.constructor.ConstructorError(
        None, None, f"tag {node.tag!r} is not part of the lab profile grammar", node.start_mark
    )


def _construct_null(loader: yaml.Loader, node: yaml.Node) -> None:
    _scalar_text(node)
    return None


def _construct_str(loader: yaml.Loader, node: yaml.Node) -> str:
    return _scalar_text(node)


def _construct_bool(loader: yaml.Loader, node: yaml.Node) -> bool:
    return loader.bool_values[_scalar_text(node).lower()]


def _construct_int(loader: yaml.Loader, node: yaml.Node) -> int:
    # The pattern is applied HERE, not assumed.  _INT_PATTERN gates only
    # IMPLICIT resolution: an explicitly tagged `!!int 0_1` never passes through
    # a resolver, and plain int() accepts underscores -- measured, it validated
    # as 1.  The previous comment here asserted that such forms "fail closed",
    # which was written without being executed and was false.
    text = _scalar_text(node)
    if _INT_PATTERN.match(text) is None:
        raise yaml.constructor.ConstructorError(
            None, None, f"integer {text!r} is outside the lab profile decimal grammar", node.start_mark
        )
    return int(text)


def _construct_seq(loader: yaml.Loader, node: yaml.Node) -> object:
    if not isinstance(node, yaml.SequenceNode):
        raise yaml.constructor.ConstructorError(
            None, None, f"expected a sequence node, found {node.id}", node.start_mark
        )
    data: list[object] = []
    yield data
    # append() rather than extend(): "update"/"extend" are mutation spellings
    # the package's own structural lint uses to catch writes to foreign state,
    # and allowlisting them here made a hostile case go green.  The lint was
    # right; this code changed instead.
    for child in node.value:
        data.append(loader.construct_object(child))


def _construct_map(loader: yaml.Loader, node: yaml.Node) -> object:
    data: dict[object, object] = {}
    yield data
    for key, value in loader.construct_mapping(node).items():
        data[key] = value


class _StrictLabProfileLoader(yaml.SafeLoader):
    """Bounded YAML grammar with neither aliases nor duplicate mapping keys.

    The constructor tables are OWNED, not inherited.  Subclassing
    ``yaml.SafeLoader`` shares its mutable ``yaml_constructors`` mapping by
    reference, so any host or library that has ever called
    ``yaml.SafeLoader.add_constructor(...)`` -- ordinary PyYAML use -- changes
    what a lab profile executes.  Measured: registering a side-effecting
    constructor for the standard string tag deleted a file while an operator
    profile was being validated, and
    ``_StrictLabProfileLoader.yaml_constructors is yaml.SafeLoader.yaml_constructors``
    was true.  A downstream artifact cannot be a read-only boundary if a third
    party can decide what its parser runs.
    """

    # The exact tag vocabulary a lab profile can contain, bound to THIS
    # MODULE'S OWN functions.  Binding SafeConstructor's methods was not
    # ownership: a host that rebinds
    # ``yaml.constructor.SafeConstructor.construct_yaml_str`` BEFORE the first
    # import of this package is captured here verbatim.  Measured -- a valid
    # operator profile validated normally while the replacement deleted a file,
    # and every table guard stayed green, because the poisoned function was
    # what "the expected constructor" resolved to on both sides.
    #
    # Defining the value in the package is the only defence in this module that
    # has survived: copying was defeated by pre-import ordering, filtering by a
    # genuine backtracking regex, type-checking by __class__ spoofing, and
    # name/identity comparison by writable __qualname__ and by this very case.
    # ``None`` keeps unknown tags failing closed.
    yaml_constructors = {
        None: _construct_undefined,
        "tag:yaml.org,2002:null": _construct_null,
        "tag:yaml.org,2002:bool": _construct_bool,
        "tag:yaml.org,2002:int": _construct_int,
        "tag:yaml.org,2002:str": _construct_str,
        "tag:yaml.org,2002:seq": _construct_seq,
        "tag:yaml.org,2002:map": _construct_map,
    }
    yaml_multi_constructors: dict[str, object] = {}
    # ``yaml_implicit_resolvers`` is shared by reference too, and it is WORSE
    # than the constructor table: PyYAML calls each registered matcher's
    # ``match()`` while scanning every scalar, so a host that has called
    # ``yaml.SafeLoader.add_implicit_resolver(...)`` executes its code during
    # validation.  Measured before this was owned: a resolver with a
    # side-effecting matcher deleted a file while an otherwise valid profile
    # parsed SUCCESSFULLY -- no error, no signal, arbitrary execution.
    #
    # The table is now BUILT FROM PATTERNS DEFINED HERE, not filtered from the
    # inherited one.  Filtering was not enough: a host that registered a genuine
    # but catastrophically backtracking regex BEFORE this module was imported
    # had it copied in, and a 31-character scalar could then stall validation
    # for seconds.  That breaks the bounded-parse contract this loader exists to
    # provide, so nothing from the host is carried across at all.
    #
    # The patterns are deliberately narrower than PyYAML's and are linear-time:
    # no nested quantifiers, each fully anchored.  Anything they do not match
    # stays a plain string and is then rejected by the schema's exact type
    # checks, which is the fail-closed direction.  Only these three tags have
    # implicit resolvers; str, seq and map are decided structurally.
    yaml_implicit_resolvers = _build_implicit_resolvers()
    # The DEFAULT_* tags are inherited class attributes too, and they decide
    # what an untagged node becomes.  Measured: a host setting
    # DEFAULT_SCALAR_TAG to the int tag before the first import made every
    # scalar in a lab profile parse as an integer, breaking validation of
    # ordinary documents.  Owned so the loader's behaviour is decided here.
    DEFAULT_SCALAR_TAG = "tag:yaml.org,2002:str"
    DEFAULT_SEQUENCE_TAG = "tag:yaml.org,2002:seq"
    DEFAULT_MAPPING_TAG = "tag:yaml.org,2002:map"
    # And the PARSER's tag-handle map, which expands `!foo` and `!!foo` shorthands.
    # Measured: with yaml.parser.Parser.DEFAULT_TAGS['!'] set to the yaml.org
    # prefix before the first import, `schema_version: !int "1"` -- normally
    # rejected as an unknown tag -- constructed as the integer 1 and validated.
    # Written out with PyYAML's own defaults so no host value is inherited.
    DEFAULT_TAGS = {"!": "!", "!!": "tag:yaml.org,2002:"}
    # The SCANNER's escape tables decide what a backslash escape means inside
    # a quoted scalar.  Measured: with
    # ``yaml.SafeLoader.ESCAPE_REPLACEMENTS["q"] = "imaginary"`` set before the
    # first import, the normally invalid ``lab_id: "\\q"`` validated with
    # ``lab_id == "imaginary"`` -- the accepted grammar itself was rewritten by
    # the host.  Written out with PyYAML's own defaults.
    ESCAPE_REPLACEMENTS = {
        "0": "\0",
        "a": "\x07",
        "b": "\x08",
        "t": "\t",
        "\t": "\t",
        "n": "\n",
        "v": "\x0b",
        "f": "\x0c",
        "r": "\r",
        "e": "\x1b",
        " ": " ",
        '"': '"',
        "\\": "\\",
        "/": "/",
        "N": "\x85",
        "_": "\xa0",
        "L": "\u2028",
        "P": "\u2029",
    }
    ESCAPE_CODES = {"x": 2, "u": 4, "U": 8}
    # The reader's non-printable guard is a Pattern, so it cannot be mutated in
    # place -- but it can be REBOUND on the shared class, which would weaken the
    # check that rejects control characters in the raw stream.  Owned for the
    # same reason as the tables above.
    NON_PRINTABLE = re.compile("[^\x09\x0a\x0d\x20-\x7e\x85\xa0-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")

    # ``yaml_path_resolvers`` is a third shared mutable table.  An ordinary
    # ``yaml.SafeLoader.add_path_resolver(...)`` call would otherwise retag
    # nodes by position inside a lab profile -- e.g. forcing ``schema_version``
    # to a different type -- so it is owned empty.  This loader resolves by
    # implicit pattern only; it has no path-directed resolution to preserve.
    yaml_path_resolvers: dict[object, object] = {}
    # ``bool_values`` is a FOURTH shared mutable table.  construct_yaml_bool
    # calls through to ``self.bool_values``, so a host that wrote
    # ``yaml.SafeLoader.bool_values["true"] = 1`` would make ``schema_version:
    # true`` validate as the integer 1.  Owned as a copy of the standard
    # mapping, which is plain data rather than callables.
    # Written OUT, not copied.  Copying reads the process-global mapping at
    # import time, so a host that poisoned it BEFORE the first
    # ``cryodaq.lab_profile`` import would have its value copied in --
    # identity separation only blocks mutation that happens afterwards.
    # These are the YAML 1.1 booleans; plain data, so owning them literally
    # costs nothing and depends on no import ordering.
    bool_values = {
        "yes": True,
        "no": False,
        "true": True,
        "false": False,
        "on": True,
        "off": False,
    }

    def __init__(self, stream: object) -> None:
        super().__init__(stream)
        self._lab_profile_depth = 0

    def compose_node(self, parent: yaml.Node | None, index: int | None) -> yaml.Node:
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise yaml.constructor.ConstructorError(
                "while composing a lab profile",
                event.start_mark,
                "YAML aliases are not allowed",
                event.start_mark,
            )
        self._lab_profile_depth += 1
        if self._lab_profile_depth > MAX_LAB_PROFILE_DEPTH:
            self._lab_profile_depth -= 1
            event = self.peek_event()
            raise yaml.constructor.ConstructorError(
                "while composing a lab profile",
                event.start_mark,
                "lab profile nesting exceeds its limit",
                event.start_mark,
            )
        try:
            return super().compose_node(parent, index)
        finally:
            self._lab_profile_depth -= 1

    def get_single_data(self) -> object:
        """The parse entry point, DEFINED HERE rather than inherited.

        ``BaseConstructor.get_single_data`` is an ordinary class attribute on a
        shared PyYAML base.  Rebound before this package's first import, it
        replaced the whole parse: measured, a wrapper returned a forged profile
        and deleted a file while the strict grammar never ran.
        """

        node = self.get_single_node()
        if node is None:
            return None
        return self.construct_document(node)

    def construct_mapping(self, node: yaml.Node, deep: bool = False) -> dict[object, object]:
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(None, None, "expected a mapping", node.start_mark)
        result: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                ) from None
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found a duplicate key",
                    key_node.start_mark,
                )
            result[key] = self.construct_object(value_node, deep=deep)
        return result


# ``yaml.load`` is an ordinary MODULE ATTRIBUTE, looked up at call time.  A host
# or an earlier library that rebinds it -- plain monkey-patching, not a hostile
# edit to this package -- replaces the entire parse entry point, and every table
# owned above becomes irrelevant because the strict loader is never constructed.
# Measured before this fix: with ``yaml.load`` set to a wrapper that deleted a
# file and returned a dict, ``parse_lab_profile("not yaml at all")`` returned a
# valid-looking profile and the file was gone.
#
# So the machinery is bound HERE, once, to this package's own class, and the
# parse below calls it directly.  ``get_single_data`` and ``dispose`` are
# resolved through _StrictLabProfileLoader's MRO at import time rather than
# through ``yaml`` at call time.
_LOADER_DISPOSE: Final = _StrictLabProfileLoader.dispose


def _parse_strict_yaml(text: str) -> object:
    """Run the owned loader directly, with no module-attribute indirection.

    Binding ``get_single_data`` at import time was NOT enough and the reason is
    worth stating: it is inherited from ``yaml.constructor.BaseConstructor``, so
    a host that rebinds it before the first import is captured by the binding
    exactly as ``yaml.load`` was.  Measured: a replacement returned a forged
    profile and deleted a file, and the strict grammar never ran.  Fixing the
    ``yaml.load`` instance without looking at what it called was the same
    mistake, one rung lower.

    ``_StrictLabProfileLoader`` now defines ``get_single_data`` itself, so the
    entry point belongs to this package.

    WHAT THIS DOES NOT DO, stated plainly because an earlier version of this
    docstring claimed otherwise and the claim was false.  Everything below
    ``get_single_data`` -- the composer, parser and scanner methods -- is
    inherited and NOT owned, and nothing here constrains it at runtime.
    Measured against this very tree: rebinding
    ``yaml.constructor.BaseConstructor.construct_document`` AFTER a completed
    import made ``parse_lab_profile("hello: world")`` return a forged profile
    and delete a file.  No import ordering was required, which makes it easier
    than the cases this module already fixed.

    The provenance guard in the tests does NOT prevent that.  It detects a
    foreign replacement present when the SUITE runs; it cannot police the
    operator's process.  It is a drift fence, not a runtime defence.

    That residual is accepted deliberately.  Every remaining attack of this
    shape requires the attacker to already be executing arbitrary Python inside
    the operator's process -- and such an attacker does not need YAML at all.
    What the boundary actually rests on is ``schema.py``, which re-derives
    instrument authority from ``BUILTIN_DRIVER_METADATA`` rather than trusting
    the parsed document: with the parser fully replaced as above, forging a
    ``keithley_2604b`` still raises ``ActuationBoundaryError``.  That property
    has its own guard and is the one worth defending.
    """

    loader = _StrictLabProfileLoader(text)
    try:
        return loader.get_single_data()
    finally:
        _LOADER_DISPOSE(loader)


def _check_exact_keys(row: object, context: str, allowed: frozenset[str], required: frozenset[str]) -> dict:
    if type(row) is not dict or any(type(key) is not str for key in row):
        raise LabProfileError(f"lab profile {context} must be a string-keyed mapping")
    unknown = sorted(set(row) - allowed)
    if unknown:
        raise LabProfileError(
            f"lab profile {context} has unknown keys {unknown}: incumbent config surfaces "
            f"({_INCUMBENT_SURFACES}) are deliberately not representable in a lab profile"
        )
    missing = sorted(required - set(row))
    if missing:
        raise LabProfileError(f"lab profile {context} is missing required keys {missing}")
    return row


def _question_kind(value: object) -> QuestionKind:
    valid = ", ".join(sorted(member.value for member in QuestionKind))
    if type(value) is QuestionKind:
        return value
    if type(value) is str:
        try:
            return QuestionKind(value)
        except ValueError:
            raise LabProfileError(f"unknown question kind {value!r} (valid kinds: {valid})") from None
    raise LabProfileError(f"question kind must be one of the typed kinds: {valid}")


def _build_profile(payload: object) -> LabProfileV1:
    root = _check_exact_keys(payload, "root", _ROOT_KEYS, _ROOT_KEYS)
    version = root["schema_version"]
    if type(version) is not int or version != 1:
        raise LabProfileError("lab profile schema_version must be the integer 1")
    lab = _check_exact_keys(root["lab"], "lab", _LAB_KEYS, _LAB_KEYS)

    instrument_rows = root["instruments"]
    if type(instrument_rows) is not list or not instrument_rows:
        raise LabProfileError("lab profile instruments must be a non-empty list of mappings")
    instruments: list[ProfileInstrument] = []
    for index, row in enumerate(instrument_rows):
        entry = _check_exact_keys(row, f"instruments[{index}]", _INSTRUMENT_ALLOWED_KEYS, _INSTRUMENT_REQUIRED_KEYS)
        note = entry.get("note", "")
        if type(note) is not str:
            raise LabProfileError(f"lab profile instruments[{index}] note must be an exact string")
        instruments.append(ProfileInstrument(type_name=entry["type"], name=entry["name"], note=note))

    question_rows = root["questions"]
    if type(question_rows) is not list:
        raise LabProfileError("lab profile questions must be a list of mappings (possibly empty)")
    questions: list[UnansweredQuestion] = []
    for index, row in enumerate(question_rows):
        entry = _check_exact_keys(row, f"questions[{index}]", _QUESTION_KEYS, _QUESTION_KEYS)
        questions.append(
            UnansweredQuestion(
                kind=_question_kind(entry["kind"]),
                subject=entry["subject"],
                summary=entry["summary"],
            )
        )

    return LabProfileV1(
        lab_id=lab["lab_id"],
        display_name=lab["display_name"],
        instruments=tuple(instruments),
        questions=tuple(questions),
    )


def parse_lab_profile(text: str) -> LabProfileV1:
    """Parse and validate one Lab Profile v1 document from text.

    The same hard byte ceiling as ``load_lab_profile`` applies to the text
    form: an arbitrarily large string must not reach the YAML parser.
    """

    if type(text) is not str:
        raise LabProfileError("lab profile text must be an exact string")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        raise LabProfileError("lab profile text is not valid Unicode (unpaired surrogate)") from None
    if len(encoded) > MAX_LAB_PROFILE_BYTES:
        raise LabProfileError("lab profile exceeds its bounded text grammar")
    try:
        payload = _parse_strict_yaml(text)
    except LabProfileError:
        raise
    except Exception as exc:
        raise LabProfileError(f"lab profile is not valid strict YAML: {exc}") from None
    return _build_profile(payload)


def load_lab_profile(path: Path) -> LabProfileV1:
    """Load and validate one Lab Profile v1 document from a regular file."""

    selected = Path(path)
    if not os.path.isfile(selected):
        raise LabProfileError(f"lab profile path must be a regular file: {selected}")
    try:
        with selected.open("rb") as handle:
            raw = handle.read(MAX_LAB_PROFILE_BYTES + 1)
    except OSError:
        raise LabProfileError(f"lab profile cannot be read: {selected}") from None
    if not raw or len(raw) > MAX_LAB_PROFILE_BYTES:
        raise LabProfileError("lab profile exceeds its bounded file grammar")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise LabProfileError("lab profile is not valid strict UTF-8") from None
    return parse_lab_profile(text)
