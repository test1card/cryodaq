"""Structurally extract the source owned by one pytest test node."""

from __future__ import annotations

import ast
import hashlib
import io
import tokenize
from pathlib import Path


class TestNodeSourceError(ValueError):
    """A pytest node cannot be resolved to one structural source owner."""


def _safe_node_parts(node_id: str) -> tuple[str, list[str]]:
    path, separator, qualified_name = node_id.partition("::")
    candidate = Path(path)
    if (
        separator != "::"
        or not qualified_name
        or candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.suffix != ".py"
    ):
        raise TestNodeSourceError(f"test node is not a safe Python node id: {node_id!r}")
    names = qualified_name.split("::")
    names[-1] = names[-1].split("[", 1)[0]
    if any(not name.isidentifier() for name in names):
        raise TestNodeSourceError(f"test node has an unsupported qualified name: {node_id!r}")
    return candidate.as_posix(), names


def _one_named(nodes: list[ast.stmt], name: str, kinds: tuple[type[ast.stmt], ...], node_id: str) -> ast.stmt:
    matches = [node for node in nodes if isinstance(node, kinds) and getattr(node, "name", None) == name]
    if len(matches) != 1:
        raise TestNodeSourceError(f"test node does not resolve to one structural owner: {node_id!r}")
    return matches[0]


def test_node_source_bytes(source: bytes, node_id: str) -> bytes:
    """Return exact bytes from the node's first decorator through its AST end.

    The AST selects the owning function or method. Its span includes nested
    helpers automatically; moving the start to the earliest decorator keeps
    decorator behavior inside the same binding. No neighbouring top-level test
    is part of the selected byte range.
    """

    _path, names = _safe_node_parts(node_id)
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise TestNodeSourceError(f"test source encoding is invalid for {node_id!r}") from exc
    if encoding.lower().replace("_", "-") not in {"utf-8", "utf-8-sig"}:
        raise TestNodeSourceError(f"test source must be UTF-8 for exact structural binding: {node_id!r}")
    try:
        tree = ast.parse(source, filename=node_id.split("::", 1)[0], type_comments=True)
    except (SyntaxError, ValueError) as exc:
        raise TestNodeSourceError(f"test source cannot be parsed for {node_id!r}") from exc

    body = tree.body
    owner: ast.stmt
    for name in names[:-1]:
        owner = _one_named(body, name, (ast.ClassDef,), node_id)
        body = owner.body  # type: ignore[union-attr]
    owner = _one_named(body, names[-1], (ast.FunctionDef, ast.AsyncFunctionDef), node_id)
    assert isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef))
    if owner.end_lineno is None or owner.end_col_offset is None:
        raise TestNodeSourceError(f"test node has no complete source span: {node_id!r}")

    start_line = min([owner.lineno, *(decorator.lineno for decorator in owner.decorator_list)])
    start_column = owner.col_offset
    lines = source.splitlines(keepends=True)
    if start_line < 1 or owner.end_lineno > len(lines):
        raise TestNodeSourceError(f"test node source span is outside its file: {node_id!r}")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    start = offsets[start_line - 1] + start_column
    end = offsets[owner.end_lineno - 1] + owner.end_col_offset
    segment = source[start:end]
    if not segment:
        raise TestNodeSourceError(f"test node source span is empty: {node_id!r}")
    return segment


def test_node_sha256(source: bytes, node_id: str) -> str:
    """Derive a SHA-256 digest from one structurally selected test node."""

    return f"sha256:{hashlib.sha256(test_node_source_bytes(source, node_id)).hexdigest()}"


def test_node_sha256_from_root(root: Path, node_id: str) -> str:
    """Read and digest one node from an explicit materialized tree root."""

    path, _names = _safe_node_parts(node_id)
    try:
        source = (root / path).read_bytes()
    except OSError as exc:
        raise TestNodeSourceError(f"test node source is unavailable: {node_id!r}") from exc
    return test_node_sha256(source, node_id)


def test_node_sha256_bindings(root: Path, node_ids: list[str]) -> dict[str, str]:
    """Derive sorted node bindings without accepting any claimed digest."""

    if not node_ids or node_ids != sorted(set(node_ids)):
        raise TestNodeSourceError("test nodes must be a sorted, unique, nonempty list")
    return {node_id: test_node_sha256_from_root(root, node_id) for node_id in node_ids}
