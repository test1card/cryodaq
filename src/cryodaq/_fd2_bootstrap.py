"""Launcher-owned POSIX fd-2 stderr isolation for engine/replay children.

On Ubuntu 22.04 an abruptly dead launcher-owned engine could leave the
launcher stderr pipe open: the USBTMC ``multiprocessing`` spawn descendant
inherits OS descriptor 2, and the multiprocessing ResourceTracker separately
preserves ``sys.stderr.fileno()``. The launcher stderr pump then never
receives EOF and restart remains in HOLD.

This module installs one production bootstrap that must run exactly once,
before :func:`cryodaq.logging_setup.setup_logging` and before any
multiprocessing construction, in every launcher-owned POSIX engine or replay
child. It:

1. duplicates the current OS fd 2 to a high private descriptor;
2. marks and verifies that duplicate non-inheritable;
3. redirects OS fd 2 to ``/dev/null`` (so every descendant inherits only the
   null device, never the launcher pipe);
4. replaces ``sys.stderr`` with a text facade that writes and flushes to the
   private duplicate but whose ``fileno()`` raises
   :class:`io.UnsupportedOperation` (the binary facade exposed via
   ``.buffer`` likewise exposes no usable descriptor);
5. retains the original stderr object and every wrapper so the redirected
   descriptor is never garbage-collected closed;
6. on any failure raised after step 3's redirect, emits one bounded
   diagnostic line through the private duplicate before closing it and
   re-raising unchanged, because the interpreter's own traceback for such a
   failure would be written through OS fd 2 and lost inside ``/dev/null``.

Encoding, errors mode, ``isatty()``, ``write()``, ``flush()`` and normal
Python logging through :class:`logging.StreamHandler` are preserved. Direct
CLI runs and Windows children never call this module.
"""

from __future__ import annotations

import io
import os
import stat
import sys
import threading
from dataclasses import dataclass

try:
    import fcntl
except ImportError:
    fcntl = None

_PRIVATE_FD_FLOOR = 1000
_FAILURE_DIAGNOSTIC_MAX_BYTES = 512
_FAILURE_DIAGNOSTIC_MAX_WRITES = 8

_install_lock = threading.Lock()
_installed_receipt: Fd2IsolationReceipt | None = None
_retained: tuple[object, ...] = ()


@dataclass(frozen=True)
class Fd2IsolationReceipt:
    """Exact outcome of one successful fd-2 isolation."""

    private_fd: int
    encoding: str
    errors: str
    isatty: bool


class _PrivateStderrBinary(io.BufferedIOBase):
    """Binary sink over the private duplicate; exports no usable descriptor."""

    def __init__(self, sink: io.BufferedWriter) -> None:
        self._sink = sink
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def writable(self) -> bool:
        return not self._closed

    def fileno(self) -> int:
        raise io.UnsupportedOperation("private stderr descriptor is not exportable")

    def detach(self) -> io.RawIOBase:
        raise io.UnsupportedOperation("private stderr sink is not detachable")

    def write(self, data: bytes | bytearray | memoryview) -> int:
        self._require_open()
        written = self._sink.write(data)
        return int(written)

    def flush(self) -> None:
        self._require_open()
        self._sink.flush()

    def close(self) -> None:
        if self._closed:
            return
        try:
            if not getattr(self._sink, "closed", False):
                self.flush()
        finally:
            self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise ValueError("I/O operation on closed file")


class _PrivateStderrText(io.TextIOBase):
    """Text facade over the private duplicate preserving stderr semantics."""

    def __init__(
        self,
        binary: _PrivateStderrBinary,
        *,
        encoding: str,
        errors: str,
        isatty: bool,
        name: str,
    ) -> None:
        self._binary = binary
        self._encoding = encoding
        self._errors = errors
        self._isatty = isatty
        self._name = name
        self._closed = False

    @property
    def encoding(self) -> str:
        return self._encoding

    @property
    def errors(self) -> str | None:
        return self._errors

    @property
    def name(self) -> str:
        return self._name

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def buffer(self) -> _PrivateStderrBinary:
        return self._binary

    def isatty(self) -> bool:
        return self._isatty

    def writable(self) -> bool:
        return not self._closed

    def fileno(self) -> int:
        raise io.UnsupportedOperation("private stderr descriptor is not exportable")

    def detach(self) -> object:
        raise io.UnsupportedOperation("private stderr buffer is not detachable")

    def write(self, text: str) -> int:
        self._require_open()
        if not isinstance(text, str):
            raise TypeError(f"write() argument must be str, not {type(text).__name__}")
        payload = text.encode(self._encoding, self._errors)
        self._binary.write(payload)
        self._binary.flush()
        return len(text)

    def flush(self) -> None:
        self._require_open()
        self._binary.flush()

    def close(self) -> None:
        if self._closed:
            return
        try:
            if not self._binary.closed:
                self.flush()
        finally:
            self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise ValueError("I/O operation on closed file")


def isolate_launcher_stderr_fd2() -> Fd2IsolationReceipt:
    """Isolate launcher-owned fd 2 exactly once; fail closed on any defect."""
    global _installed_receipt, _retained
    if os.name != "posix" or fcntl is None:
        raise RuntimeError("launcher fd-2 isolation requires a POSIX runtime")
    with _install_lock:
        if _installed_receipt is not None:
            return _installed_receipt
        original = sys.stderr
        if original is None:
            raise RuntimeError("cannot isolate fd 2 without an existing stderr object")
        encoding = str(getattr(original, "encoding", None) or "utf-8")
        errors = str(getattr(original, "errors", None) or "backslashreplace")
        try:
            tty = bool(original.isatty())
        except Exception:
            tty = False
        try:
            private_fd = int(fcntl.fcntl(2, fcntl.F_DUPFD, _PRIVATE_FD_FLOOR))
        except OSError:
            private_fd = os.dup(2)
        try:
            os.set_inheritable(private_fd, False)
            if os.get_inheritable(private_fd) is not False:
                raise RuntimeError("private stderr duplicate did not settle non-inheritable")
            devnull_fd = os.open(os.devnull, os.O_WRONLY)
        except BaseException:
            _close_quietly(private_fd)
            raise
        try:
            try:
                original.flush()
            except Exception:
                pass
            os.dup2(devnull_fd, 2)
        finally:
            _close_quietly(devnull_fd)
        committed = False
        raw: io.FileIO | None = None
        buffered: io.BufferedWriter | None = None
        binary: _PrivateStderrBinary | None = None
        text: _PrivateStderrText | None = None
        try:
            devnull_stat = os.stat(os.devnull)
            redirected = os.fstat(2)
            if not (
                stat.S_ISCHR(redirected.st_mode)
                and redirected.st_dev == devnull_stat.st_dev
                and redirected.st_rdev == devnull_stat.st_rdev
            ):
                raise RuntimeError("OS fd 2 did not settle onto the null device")
            raw = io.FileIO(private_fd, "w", closefd=False)
            buffered = io.BufferedWriter(raw)
            binary = _PrivateStderrBinary(buffered)
            text = _PrivateStderrText(
                binary,
                encoding=encoding,
                errors=errors,
                isatty=tty,
                name="<cryodaq-private-stderr>",
            )
            sys.stderr = text
            committed = True
        except BaseException as failure:
            if not committed:
                _emit_post_dup2_failure_diagnostic(private_fd, failure)
                if raw is not None:
                    try:
                        raw.close()
                    except Exception:
                        pass
                _close_quietly(private_fd)
            raise
        assert raw is not None and buffered is not None and binary is not None and text is not None
        _retained = (original, raw, buffered, binary, text, private_fd)
        _installed_receipt = Fd2IsolationReceipt(
            private_fd=int(private_fd),
            encoding=encoding,
            errors=errors,
            isatty=tty,
        )
        return _installed_receipt


def current_receipt() -> Fd2IsolationReceipt | None:
    """Return the installed receipt without installing anything."""
    return _installed_receipt


def retained_stderr_state() -> tuple[object, ...]:
    """Return the retained objects keeping the private duplicate alive."""
    return _retained


def _close_quietly(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def _emit_post_dup2_failure_diagnostic(private_fd: int, failure: BaseException) -> None:
    """Best-effort bounded note over the private duplicate; never masks ``failure``.

    Reachable only once OS fd 2 already points at the null device, where an
    interpreter traceback for ``failure`` could never reach the launcher. At
    most one bounded line crosses the still-open non-inheritable duplicate;
    every write fault is swallowed so the original exception escapes intact.
    """
    summary = str(failure)[:200]
    message = (
        f"[cryodaq-fd2-bootstrap] installation failed after redirecting OS fd 2 "
        f"to {os.devnull}: {type(failure).__qualname__}: {summary}\n"
    )
    chunk = memoryview(message.encode("utf-8", "backslashreplace")[:_FAILURE_DIAGNOSTIC_MAX_BYTES])
    try:
        for _ in range(_FAILURE_DIAGNOSTIC_MAX_WRITES):
            written = os.write(private_fd, chunk)
            if written <= 0:
                return
            chunk = chunk[written:]
            if not chunk:
                return
    except OSError:
        return
