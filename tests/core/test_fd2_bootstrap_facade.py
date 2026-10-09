"""Facade contract for the launcher fd-2 stderr isolation bootstrap.

These tests are pure and cross-platform: they exercise the text and binary
facade classes without touching real descriptors, so they run identically on
Ubuntu 22.04 and Windows. The descriptor-level external effects are covered
separately by tests/integration/test_launcher_fd2_shutdown_blocker.py.
"""

from __future__ import annotations

import io

import pytest

from cryodaq._fd2_bootstrap import _PrivateStderrBinary, _PrivateStderrText


def _facade(
    *,
    encoding: str = "utf-8",
    errors: str = "backslashreplace",
    isatty: bool = False,
) -> tuple[_PrivateStderrText, _PrivateStderrBinary, io.BytesIO]:
    sink = io.BytesIO()
    binary = _PrivateStderrBinary(sink)
    text = _PrivateStderrText(binary, encoding=encoding, errors=errors, isatty=isatty, name="<test-private>")
    return text, binary, sink


def test_text_facade_write_flushes_encoded_bytes_and_reports_char_count() -> None:
    text, _binary, sink = _facade()

    written = text.write("данные ✓\n")

    assert written == len("данные ✓\n")
    assert sink.getvalue() == "данные ✓\n".encode()
    assert text.flush() is None


def test_text_facade_preserves_encoding_errors_isatty_and_name() -> None:
    text, _binary, _sink = _facade(encoding="cp1251", errors="replace", isatty=True)

    assert text.encoding == "cp1251"
    assert text.errors == "replace"
    assert text.isatty() is True
    assert text.name == "<test-private>"
    assert text.writable() is True


def test_text_facade_writelines_delegates_through_write() -> None:
    text, _binary, sink = _facade()

    text.writelines(["a\n", "б\n"])

    assert sink.getvalue() == "a\nб\n".encode()


def test_text_facade_rejects_non_string_write() -> None:
    text, _binary, _sink = _facade()

    with pytest.raises(TypeError):
        text.write(b"bytes")  # type: ignore[arg-type]


def test_text_facade_fileno_raises_unsupported_operation() -> None:
    text, _binary, _sink = _facade()

    with pytest.raises(io.UnsupportedOperation):
        text.fileno()


def test_text_facade_detach_raises_unsupported_operation() -> None:
    text, _binary, _sink = _facade()

    with pytest.raises(io.UnsupportedOperation):
        text.detach()


def test_binary_facade_exposed_via_buffer_has_no_usable_descriptor_either() -> None:
    text, binary, sink = _facade()

    assert text.buffer is binary
    with pytest.raises(io.UnsupportedOperation):
        text.buffer.fileno()
    with pytest.raises(io.UnsupportedOperation):
        binary.fileno()
    with pytest.raises(io.UnsupportedOperation):
        binary.detach()
    assert binary.write(b"raw") == 3
    binary.flush()
    assert sink.getvalue() == b"raw"


def test_closed_text_facade_raises_value_error_and_second_close_is_noop() -> None:
    text, binary, _sink = _facade()

    text.close()
    assert text.closed is True
    assert text.writable() is False
    with pytest.raises(ValueError):
        text.write("x")
    with pytest.raises(ValueError):
        text.flush()
    text.close()


def test_closed_binary_facade_raises_value_error_on_write_and_flush() -> None:
    _text, binary, _sink = _facade()

    binary.close()
    assert binary.closed is True
    with pytest.raises(ValueError):
        binary.write(b"x")
    with pytest.raises(ValueError):
        binary.flush()
    binary.close()


def test_text_facade_close_with_binary_already_closed_is_silent_and_idempotent() -> None:
    text, binary, sink = _facade()

    text.write("перед закрытием\n")
    binary.close()
    text.close()

    assert text.closed is True
    assert binary.closed is True
    assert sink.getvalue() == "перед закрытием\n".encode()
    text.close()
    binary.close()
    with pytest.raises(ValueError):
        text.write("x")
