"""Focused guards for named pytest dependency-closure digests."""

from __future__ import annotations

from tools.test_node_source import test_node_sha256 as _test_node_sha256


def test_node_digest_includes_support_closure_but_excludes_sibling_tests() -> None:
    node = "tests/example.py::TestGuards::test_guard"
    source = b"""\
import pytest

def _make_stack():
    return [1]

def _reading():
    return 1

def _write_yaml(value):
    return value

@pytest.fixture(autouse=True)
def _isolate_state():
    yield

def _class_mark(cls):
    return cls

@_class_mark
class TestGuards:
    def test_guard(self):
        assert _write_yaml(_make_stack()) == [_reading()]

    def test_sibling(self):
        assert "sibling-v1"

def test_top_level_sibling():
    assert "top-level-v1"
"""
    digest = _test_node_sha256(source, node)

    assert _test_node_sha256(source.replace(b"return [1]", b"return [2]"), node) != digest
    assert _test_node_sha256(source.replace(b"return 1", b"return 2", 1), node) != digest
    assert _test_node_sha256(source.replace(b"return value", b"return (value)"), node) != digest
    assert _test_node_sha256(source.replace(b"yield", b"yield None"), node) != digest
    assert _test_node_sha256(source.replace(b"@_class_mark", b"@_class_mark()"), node) != digest
    assert _test_node_sha256(source.replace(b"sibling-v1", b"sibling-v2"), node) == digest
    assert _test_node_sha256(source.replace(b"top-level-v1", b"top-level-v2"), node) == digest
