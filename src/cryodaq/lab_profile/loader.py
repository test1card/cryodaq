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


class _StrictLabProfileLoader(yaml.SafeLoader):
    """Bounded YAML grammar with neither aliases nor duplicate mapping keys."""

    def __init__(self, stream: object) -> None:
        super().__init__(stream)
        self._lab_profile_depth = 0

    def compose_node(self, parent: yaml.Node | None, index: int | None) -> yaml.Node:
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise yaml.constructor.ConstructorError(
                "while composing a lab profile",
                getattr(event, "start_mark", None),
                "YAML aliases are not allowed",
                getattr(event, "start_mark", None),
            )
        self._lab_profile_depth += 1
        if self._lab_profile_depth > MAX_LAB_PROFILE_DEPTH:
            self._lab_profile_depth -= 1
            event = self.peek_event()
            raise yaml.constructor.ConstructorError(
                "while composing a lab profile",
                getattr(event, "start_mark", None),
                "lab profile nesting exceeds its limit",
                getattr(event, "start_mark", None),
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
    """Parse and validate one Lab Profile v1 document from text."""

    if type(text) is not str:
        raise LabProfileError("lab profile text must be an exact string")
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
        raw = selected.read_bytes()
    except OSError:
        raise LabProfileError(f"lab profile cannot be read: {selected}") from None
    if not raw or len(raw) > MAX_LAB_PROFILE_BYTES:
        raise LabProfileError("lab profile exceeds its bounded file grammar")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise LabProfileError("lab profile is not valid strict UTF-8") from None
    return parse_lab_profile(text)
