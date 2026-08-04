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

# The exact tag vocabulary a lab profile may contain.  Module level so both
# the constructor table and the resolver table below can reference it: a
# class-body comprehension cannot see class scope.
_OWNED_TAGS: Final = frozenset(
    {
        "tag:yaml.org,2002:null",
        "tag:yaml.org,2002:bool",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:float",
        "tag:yaml.org,2002:str",
        "tag:yaml.org,2002:seq",
        "tag:yaml.org,2002:map",
    }
)


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

    # The exact tag vocabulary a lab profile can contain, bound to
    # SafeConstructor's own METHODS rather than copied from its (mutable,
    # shared) constructor mapping.  ``None`` keeps unknown tags failing closed.
    yaml_constructors = {
        None: yaml.constructor.SafeConstructor.construct_undefined,
        "tag:yaml.org,2002:null": yaml.constructor.SafeConstructor.construct_yaml_null,
        "tag:yaml.org,2002:bool": yaml.constructor.SafeConstructor.construct_yaml_bool,
        "tag:yaml.org,2002:int": yaml.constructor.SafeConstructor.construct_yaml_int,
        "tag:yaml.org,2002:float": yaml.constructor.SafeConstructor.construct_yaml_float,
        "tag:yaml.org,2002:str": yaml.constructor.SafeConstructor.construct_yaml_str,
        "tag:yaml.org,2002:seq": yaml.constructor.SafeConstructor.construct_yaml_seq,
        "tag:yaml.org,2002:map": yaml.constructor.SafeConstructor.construct_yaml_map,
    }
    yaml_multi_constructors: dict[str, object] = {}
    # ``yaml_implicit_resolvers`` is shared by reference too, and it is WORSE
    # than the constructor table: PyYAML calls each registered matcher's
    # ``match()`` while scanning every scalar, so a host that has called
    # ``yaml.SafeLoader.add_implicit_resolver(...)`` executes its code during
    # validation.  Measured before this fix: a resolver with a side-effecting
    # matcher deleted a file while an otherwise valid profile parsed
    # SUCCESSFULLY -- no error, no signal, arbitrary execution.
    #
    # Rebuilt here rather than copied: only tags in the owned vocabulary above
    # survive, and only when the matcher is a genuine compiled pattern, so an
    # object with a hand-written ``match`` cannot be inherited.  The type check
    # is EXACT: ``isinstance`` consults ``__class__`` and is spoofable, so a
    # matcher merely reporting ``re.Pattern`` would have passed.
    yaml_implicit_resolvers = {
        prefix: [(tag, matcher) for tag, matcher in entries if tag in _OWNED_TAGS and type(matcher) is re.Pattern]
        for prefix, entries in yaml.resolver.Resolver.yaml_implicit_resolvers.items()
    }

    # ``yaml_path_resolvers`` is a third shared mutable table.  An ordinary
    # ``yaml.SafeLoader.add_path_resolver(...)`` call would otherwise retag
    # nodes by position inside a lab profile -- e.g. forcing ``schema_version``
    # to a different type -- so it is owned empty.  This loader resolves by
    # implicit pattern only; it has no path-directed resolution to preserve.
    yaml_path_resolvers: dict[object, object] = {}

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
        payload = yaml.load(text, Loader=_StrictLabProfileLoader)
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
