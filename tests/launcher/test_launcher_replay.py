"""Tests for Stage 4 replay launcher integration."""

from __future__ import annotations

import argparse
import io
import json
import os
import sqlite3
import stat
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_REPLAY_NONCE = "a" * 64
_REPLAY_SESSION = "b" * 32
_REPLAY_SOURCE = str(Path("C:/data/replay.db"))
_REPLAY_PID = 4242
_REPLAY_SPEED = 5.0
_ENGINE_NONCE = "c" * 64
_ENGINE_INSTANCE = "d" * 32
_ENGINE_PID = 4343
_ENGINE_PUB = "tcp://127.0.0.1:5555"
_ENGINE_CMD = "tcp://127.0.0.1:5556"
_ENGINE_SAFE_CMD = "tcp://127.0.0.1:5558"


def _replay_ready_frame(**changes: object) -> bytes:
    payload: dict[str, object] = {
        "schema": "cryodaq.replay_ready.v2",
        "nonce": _REPLAY_NONCE,
        "session_id": _REPLAY_SESSION,
        "mode": "replay",
        "source": _REPLAY_SOURCE,
        "speed": _REPLAY_SPEED,
        "pid": _REPLAY_PID,
        "pub_addr": "tcp://127.0.0.1:5555",
        "cmd_addr": "tcp://127.0.0.1:5556",
        "safe_cmd_addr": _ENGINE_SAFE_CMD,
    }
    payload.update(changes)
    return (
        b"CRYODAQ_REPLAY_READY_V2 "
        + json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
        + b"\n"
    )


def _engine_ready_frame(**changes: object) -> bytes:
    payload: dict[str, object] = {
        "schema": "cryodaq.engine_ready.v2",
        "nonce": _ENGINE_NONCE,
        "engine_instance_id": _ENGINE_INSTANCE,
        "mode": "live",
        "pid": _ENGINE_PID,
        "pub_addr": _ENGINE_PUB,
        "cmd_addr": _ENGINE_CMD,
        "safe_cmd_addr": _ENGINE_SAFE_CMD,
    }
    payload.update(changes)
    return (
        b"CRYODAQ_ENGINE_READY_V2 "
        + json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
        + b"\n"
    )


def _engine_ready_reply_frame(**changes: object) -> bytes:
    payload = {"ok": True, **json.loads(_engine_ready_frame().split(b" ", 1)[1]), "proto": 2}
    payload.update(changes)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def _replay_ready_reply_frame(**changes: object) -> bytes:
    payload = {"ok": True, **json.loads(_replay_ready_frame().split(b" ", 1)[1]), "proto": 2}
    payload.update(changes)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def _drop_ready_key(frame: bytes, key: str) -> bytes:
    prefix, raw_payload = frame.split(b" ", 1)
    payload = json.loads(raw_payload)
    del payload[key]
    return (
        prefix
        + b" "
        + json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
        + b"\n"
    )


def test_live_engine_ready_receipt_accepts_only_exact_child_authority() -> None:
    from cryodaq.launcher import _decode_engine_ready_receipt

    decoded = _decode_engine_ready_receipt(
        _engine_ready_frame(),
        expected_nonce=_ENGINE_NONCE,
        expected_engine_instance_id=_ENGINE_INSTANCE,
        expected_pid=_ENGINE_PID,
        expected_pub_addr=_ENGINE_PUB,
        expected_cmd_addr=_ENGINE_CMD,
        expected_safe_cmd_addr=_ENGINE_SAFE_CMD,
    )

    assert decoded == json.loads(_engine_ready_frame().split(b" ", 1)[1])


@pytest.mark.parametrize(
    "raw_frame",
    [
        _engine_ready_frame()[:-1],
        _engine_ready_frame()[:-1] + b"\r\n",
        _engine_ready_frame(nonce="e" * 64),
        _engine_ready_frame(engine_instance_id="f" * 32),
        _engine_ready_frame(pid=_ENGINE_PID + 1),
        _engine_ready_frame(mode="replay"),
        _engine_ready_frame(pub_addr="tcp://127.0.0.1:6555"),
        _engine_ready_frame(cmd_addr="tcp://127.0.0.1:6556"),
        _engine_ready_frame(safe_cmd_addr="tcp://127.0.0.1:6558"),
        _drop_ready_key(_engine_ready_frame(), "safe_cmd_addr"),
        _engine_ready_frame(schema="cryodaq.engine_ready.v1").replace(
            b"CRYODAQ_ENGINE_READY_V2 ", b"CRYODAQ_ENGINE_READY_V1 ", 1
        ),
        _engine_ready_frame(extra="not-allowed"),
        b'CRYODAQ_ENGINE_READY_V2 {"schema":"cryodaq.engine_ready.v2","schema":"cryodaq.engine_ready.v2"}\n',
        b'CRYODAQ_ENGINE_READY_V2 {"pid":NaN}\n',
        b'CRYODAQ_ENGINE_READY_V2 {"nonce":"\xff"}\n',
        b"CRYODAQ_ENGINE_READY_V2 " + (b"x" * 8192) + b"\n",
    ],
)
def test_live_engine_ready_receipt_rejects_malformed_or_mismatched_frames(raw_frame: bytes) -> None:
    from cryodaq.launcher import _decode_engine_ready_receipt

    with pytest.raises((UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError)):
        _decode_engine_ready_receipt(
            raw_frame,
            expected_nonce=_ENGINE_NONCE,
            expected_engine_instance_id=_ENGINE_INSTANCE,
            expected_pid=_ENGINE_PID,
            expected_pub_addr=_ENGINE_PUB,
            expected_cmd_addr=_ENGINE_CMD,
            expected_safe_cmd_addr=_ENGINE_SAFE_CMD,
        )


def test_live_engine_ready_pipe_rejects_duplicate_receipts() -> None:
    from cryodaq.launcher import _read_engine_ready_receipt

    ready = threading.Event()
    state: dict[str, object] = {"receipt": None, "error": None}
    lock = threading.Lock()
    pipe = io.BytesIO(_engine_ready_frame() + _engine_ready_frame())

    _read_engine_ready_receipt(
        pipe,
        ready,
        state,
        lock,
        expected_nonce=_ENGINE_NONCE,
        expected_engine_instance_id=_ENGINE_INSTANCE,
        expected_pid=_ENGINE_PID,
        expected_pub_addr=_ENGINE_PUB,
        expected_cmd_addr=_ENGINE_CMD,
        expected_safe_cmd_addr=_ENGINE_SAFE_CMD,
    )

    assert ready.is_set()
    assert state == {"receipt": None, "error": "invalid"}
    assert pipe.closed


def test_private_child_ready_pipe_cannot_be_retained_by_a_descendant() -> None:
    """A child-created descendant cannot delay readiness EOF."""

    import psutil

    from cryodaq.launcher import _open_child_ready_pipe

    ready_stream, ready_write_fd, ready_channel, popen_controls = _open_child_ready_pipe()
    environment = os.environ.copy()
    environment["CRYODAQ_CHILD_READY_CHANNEL"] = ready_channel
    child_code = "\n".join(
        (
            "import os, subprocess, sys",
            "from cryodaq.engine import _consume_child_ready_channel",
            "fd = _consume_child_ready_channel()",
            "assert fd is not None",
            "grandchild = subprocess.Popen(",
            "    [sys.executable, '-c', 'import time; time.sleep(30)'],",
            "    close_fds=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,",
            ")",
            "os.write(fd, str(grandchild.pid).encode('ascii') + b'\\n')",
            "os.close(fd)",
        )
    )
    child = None
    grandchild_pid: int | None = None
    if sys.platform == "win32":
        os.set_inheritable(ready_write_fd, True)
    try:
        child = subprocess.Popen(
            [sys.executable, "-c", child_code],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **popen_controls,
        )
    finally:
        if sys.platform == "win32":
            os.set_inheritable(ready_write_fd, False)
        os.close(ready_write_fd)
    eof_reader: threading.Thread | None = None
    prompt_eof = False
    try:
        first_lines: list[bytes] = []
        first_reader = threading.Thread(target=lambda: first_lines.append(ready_stream.readline()))
        first_reader.start()
        first_reader.join(timeout=10.0)
        if first_reader.is_alive():
            child.kill()
            child.wait(timeout=5.0)
            first_reader.join(timeout=5.0)
            pytest.fail("direct child never wrote its private readiness channel")
        assert len(first_lines) == 1 and first_lines[0].endswith(b"\n")
        grandchild_pid = int(first_lines[0])
        assert child.wait(timeout=10.0) == 0, child.stderr.read().decode("utf-8", errors="replace")

        eof_results: list[bytes] = []
        eof_reader = threading.Thread(target=lambda: eof_results.append(ready_stream.read()))
        eof_reader.start()
        eof_reader.join(timeout=2.0)
        prompt_eof = not eof_reader.is_alive() and eof_results == [b""]
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=5.0)
        if child is not None and child.stderr is not None:
            # stderr=PIPE hands back a BufferedReader this test owns. Leaving
            # it to the garbage collector raises ResourceWarning from the
            # finalizer, which pytest promotes to
            # PytestUnraisableExceptionWarning and charges to whichever test is
            # running when the collection fires. That is why it failed only
            # inside a long partition and never in isolation.
            child.stderr.close()
        if grandchild_pid is not None:
            try:
                grandchild = psutil.Process(grandchild_pid)
                grandchild.terminate()
                grandchild.wait(timeout=5.0)
            except psutil.NoSuchProcess:
                pass
        if eof_reader is not None:
            eof_reader.join(timeout=5.0)
        ready_stream.close()

    assert prompt_eof, "a direct-child descendant retained the one-shot readiness pipe"


def test_child_ready_pipe_is_one_noninheritable_fifo_with_exact_popen_controls() -> None:
    from cryodaq.launcher import _open_child_ready_pipe

    ready_stream, ready_write_fd, ready_channel, popen_controls = _open_child_ready_pipe()
    try:
        assert stat.S_ISFIFO(os.fstat(ready_stream.fileno()).st_mode)
        assert stat.S_ISFIFO(os.fstat(ready_write_fd).st_mode)
        assert os.get_inheritable(ready_stream.fileno()) is False
        assert os.get_inheritable(ready_write_fd) is False
        if sys.platform == "win32":
            import msvcrt

            handle = msvcrt.get_osfhandle(ready_write_fd)
            assert ready_channel == f"handle:{handle}"
            assert popen_controls["close_fds"] is True
            assert popen_controls["startupinfo"].lpAttributeList == {"handle_list": [handle]}
        else:
            assert ready_channel == f"fd:{ready_write_fd}"
            assert popen_controls == {"pass_fds": (ready_write_fd,)}
    finally:
        ready_stream.close()
        os.close(ready_write_fd)


@pytest.mark.parametrize("failure_point", ["setsockopt", "connect"])
def test_engine_ready_probe_settles_socket_and_context_on_setup_failure(monkeypatch, failure_point: str) -> None:
    import zmq

    from cryodaq.launcher import _request_engine_ready_reply

    socket = MagicMock()
    context = MagicMock()
    context.socket.return_value = socket
    getattr(socket, failure_point).side_effect = OSError(f"{failure_point} failed")
    monkeypatch.setattr(zmq, "Context", lambda: context)

    with pytest.raises(OSError, match=failure_point):
        _request_engine_ready_reply({"cmd": "engine_ready"})

    socket.close.assert_called_once_with(linger=0)
    context.term.assert_called_once_with()


def test_replay_ready_receipt_accepts_only_the_exact_child_authority() -> None:
    from cryodaq.launcher import _decode_replay_ready_receipt

    decoded = _decode_replay_ready_receipt(
        _replay_ready_frame(),
        expected_nonce=_REPLAY_NONCE,
        expected_session_id=_REPLAY_SESSION,
        expected_source=_REPLAY_SOURCE,
        expected_speed=_REPLAY_SPEED,
        expected_pid=_REPLAY_PID,
    )

    assert decoded == json.loads(_replay_ready_frame().split(b" ", 1)[1])


@pytest.mark.parametrize(
    "raw_frame",
    [
        b"Replay engine ready\n",
        _replay_ready_frame()[:-1],
        _replay_ready_frame()[:-1] + b"\r\n",
        _replay_ready_frame(nonce="c" * 64),
        _replay_ready_frame(session_id="d" * 32),
        _replay_ready_frame(source="C:/data/other.db"),
        _replay_ready_frame(speed=5),
        _replay_ready_frame(speed=True),
        _replay_ready_frame(speed=4.0),
        _replay_ready_frame(pid=_REPLAY_PID + 1),
        _replay_ready_frame(mode="acquisition"),
        _replay_ready_frame(pub_addr="tcp://127.0.0.1:6555"),
        _replay_ready_frame(cmd_addr="tcp://127.0.0.1:6556"),
        _replay_ready_frame(safe_cmd_addr="tcp://127.0.0.1:6558"),
        _drop_ready_key(_replay_ready_frame(), "safe_cmd_addr"),
        _replay_ready_frame(schema="cryodaq.replay_ready.v1").replace(
            b"CRYODAQ_REPLAY_READY_V2 ", b"CRYODAQ_REPLAY_READY_V1 ", 1
        ),
        _replay_ready_frame(extra="not-allowed"),
        b'CRYODAQ_REPLAY_READY_V2 {"schema":"cryodaq.replay_ready.v2","schema":"cryodaq.replay_ready.v2"}\n',
        b'CRYODAQ_REPLAY_READY_V2 {"pid":NaN}\n',
        b'CRYODAQ_REPLAY_READY_V2 {"source":"\xff"}\n',
        b"CRYODAQ_REPLAY_READY_V2 " + (b"x" * 8192) + b"\n",
    ],
    ids=[
        "human-log",
        "missing-lf",
        "crlf",
        "wrong-nonce",
        "wrong-session",
        "wrong-source",
        "integer-speed",
        "bool-speed",
        "wrong-speed",
        "wrong-pid",
        "wrong-mode",
        "wrong-address",
        "wrong-command-address",
        "wrong-safe-command-address",
        "missing-safe-command-address",
        "legacy-v1",
        "extra-key",
        "duplicate-key",
        "non-finite",
        "non-ascii",
        "oversize",
    ],
)
def test_replay_ready_receipt_rejects_malformed_or_mismatched_frames(raw_frame: bytes) -> None:
    from cryodaq.launcher import _decode_replay_ready_receipt

    with pytest.raises((UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError)):
        _decode_replay_ready_receipt(
            raw_frame,
            expected_nonce=_REPLAY_NONCE,
            expected_session_id=_REPLAY_SESSION,
            expected_source=_REPLAY_SOURCE,
            expected_speed=_REPLAY_SPEED,
            expected_pid=_REPLAY_PID,
        )


def test_replay_ready_pipe_rejects_duplicate_receipts() -> None:
    from cryodaq.launcher import _read_replay_ready_receipt

    ready = threading.Event()
    state: dict[str, object] = {"receipt": None, "error": None}
    lock = threading.Lock()
    pipe = io.BytesIO(_replay_ready_frame() + _replay_ready_frame())

    _read_replay_ready_receipt(
        pipe,
        ready,
        state,
        lock,
        expected_replay_nonce=_REPLAY_NONCE,
        expected_replay_session_id=_REPLAY_SESSION,
        expected_replay_source=_REPLAY_SOURCE,
        expected_replay_speed=_REPLAY_SPEED,
        expected_replay_pid=_REPLAY_PID,
    )

    assert ready.is_set()
    assert state == {"receipt": None, "error": "invalid"}
    assert pipe.closed


class _ObservedUnbufferedPipe:
    """Expose a real OS pipe while making the first short read observable."""

    def __init__(self, raw, first_read: threading.Event) -> None:  # noqa: ANN001
        self._raw = raw
        self._first_read = first_read

    def read(self, size: int) -> bytes:
        value = self._raw.read(size)
        self._first_read.set()
        return value

    def close(self) -> None:
        self._raw.close()

    @property
    def closed(self) -> bool:
        return self._raw.closed


def _read_fragmented_replay_pipe(chunks: list[bytes]) -> tuple[dict[str, object], list[OSError]]:
    from cryodaq.launcher import _read_replay_ready_receipt

    read_fd, write_fd = os.pipe()
    raw = os.fdopen(read_fd, "rb", buffering=0)
    first_read = threading.Event()
    pipe = _ObservedUnbufferedPipe(raw, first_read)
    ready = threading.Event()
    state: dict[str, object] = {"receipt": None, "error": None}
    lock = threading.Lock()
    writer_errors: list[OSError] = []

    def write_chunks() -> None:
        try:
            os.write(write_fd, chunks[0])
            assert first_read.wait(2.0)
            for chunk in chunks[1:]:
                os.write(write_fd, chunk)
        except OSError as exc:
            writer_errors.append(exc)
        finally:
            os.close(write_fd)

    writer = threading.Thread(target=write_chunks, name="fragmented-replay-ready-writer")
    writer.start()
    _read_replay_ready_receipt(
        pipe,
        ready,
        state,
        lock,
        expected_replay_nonce=_REPLAY_NONCE,
        expected_replay_session_id=_REPLAY_SESSION,
        expected_replay_source=_REPLAY_SOURCE,
        expected_replay_speed=_REPLAY_SPEED,
        expected_replay_pid=_REPLAY_PID,
    )
    writer.join(timeout=3.0)
    assert not writer.is_alive()
    assert ready.is_set()
    assert pipe.closed
    return state, writer_errors


def test_replay_ready_os_pipe_accepts_fragmented_frame_through_eof() -> None:
    frame = _replay_ready_frame()

    state, writer_errors = _read_fragmented_replay_pipe([frame[:17], frame[17:]])

    assert writer_errors == []
    assert state["error"] is None
    assert state["receipt"] == json.loads(frame.split(b" ", 1)[1])


def test_replay_ready_os_pipe_rejects_delayed_duplicate() -> None:
    frame = _replay_ready_frame()

    state, writer_errors = _read_fragmented_replay_pipe([frame, frame])

    assert writer_errors == []
    assert state == {"receipt": None, "error": "invalid"}


def test_replay_ready_os_pipe_cannot_authorize_before_eof() -> None:
    from cryodaq.launcher import _read_replay_ready_receipt

    read_fd, write_fd = os.pipe()
    pipe = os.fdopen(read_fd, "rb", buffering=0)
    ready = threading.Event()
    state: dict[str, object] = {"receipt": None, "error": None}
    lock = threading.Lock()
    reader = threading.Thread(
        target=_read_replay_ready_receipt,
        args=(pipe, ready, state, lock),
        kwargs={
            "expected_replay_nonce": _REPLAY_NONCE,
            "expected_replay_session_id": _REPLAY_SESSION,
            "expected_replay_source": _REPLAY_SOURCE,
            "expected_replay_speed": _REPLAY_SPEED,
            "expected_replay_pid": _REPLAY_PID,
        },
        name="replay-ready-eof-reader",
    )
    try:
        os.write(write_fd, _replay_ready_frame())
        reader.start()
        assert ready.wait(0.1) is False
    finally:
        os.close(write_fd)
    reader.join(timeout=3.0)
    assert not reader.is_alive()
    assert ready.is_set()
    assert state["error"] is None
    assert state["receipt"] is not None


def test_replay_child_consumes_complete_launcher_authority(monkeypatch) -> None:
    import cryodaq.replay_engine.__main__ as replay_main

    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, True)
    monkeypatch.setattr(replay_main.sys, "platform", "linux")
    monkeypatch.setenv("CRYODAQ_REPLAY_READY_NONCE", _REPLAY_NONCE)
    monkeypatch.setenv("CRYODAQ_REPLAY_SESSION_ID", _REPLAY_SESSION)
    monkeypatch.setenv("CRYODAQ_CHILD_READY_CHANNEL", f"fd:{write_fd}")

    try:
        assert replay_main._consume_launcher_replay_authority() == (_REPLAY_NONCE, _REPLAY_SESSION, write_fd)
        assert os.get_inheritable(write_fd) is False
        assert "CRYODAQ_REPLAY_READY_NONCE" not in os.environ
        assert "CRYODAQ_REPLAY_SESSION_ID" not in os.environ
        assert "CRYODAQ_CHILD_READY_CHANNEL" not in os.environ
    finally:
        os.close(write_fd)
        os.close(read_fd)


@pytest.mark.parametrize(
    ("nonce", "session_id", "channel"),
    [
        (None, _REPLAY_SESSION, "fd:17"),
        (_REPLAY_NONCE, None, "fd:17"),
        ("a" * 63, _REPLAY_SESSION, "fd:17"),
        (_REPLAY_NONCE, "B" * 32, "fd:17"),
        (_REPLAY_NONCE, _REPLAY_SESSION, None),
        (_REPLAY_NONCE, _REPLAY_SESSION, "fd:2"),
    ],
)
def test_replay_child_rejects_incomplete_or_malformed_launcher_authority(
    monkeypatch, nonce: str | None, session_id: str | None, channel: str | None
) -> None:
    import cryodaq.replay_engine.__main__ as replay_main

    monkeypatch.setattr(replay_main.sys, "platform", "linux")
    monkeypatch.delenv("CRYODAQ_REPLAY_READY_NONCE", raising=False)
    monkeypatch.delenv("CRYODAQ_REPLAY_SESSION_ID", raising=False)
    monkeypatch.delenv("CRYODAQ_CHILD_READY_CHANNEL", raising=False)
    if nonce is not None:
        monkeypatch.setenv("CRYODAQ_REPLAY_READY_NONCE", nonce)
    if session_id is not None:
        monkeypatch.setenv("CRYODAQ_REPLAY_SESSION_ID", session_id)
    if channel is not None:
        monkeypatch.setenv("CRYODAQ_CHILD_READY_CHANNEL", channel)

    with pytest.raises(RuntimeError, match=r"launcher replay readiness (?:authority|channel) is invalid"):
        replay_main._consume_launcher_replay_authority()

    assert "CRYODAQ_REPLAY_READY_NONCE" not in os.environ
    assert "CRYODAQ_REPLAY_SESSION_ID" not in os.environ
    assert "CRYODAQ_CHILD_READY_CHANNEL" not in os.environ


@pytest.mark.parametrize("descriptor", [0, 1, 2])
def test_replay_invalid_ready_channel_cannot_close_process_stdio(monkeypatch, descriptor: int) -> None:
    import cryodaq.replay_engine.__main__ as replay_main

    before = os.fstat(descriptor)
    monkeypatch.setattr(replay_main.sys, "platform", "linux")

    with pytest.raises(RuntimeError, match="launcher replay readiness channel is invalid"):
        replay_main._consume_replay_ready_channel(f"fd:{descriptor}")

    assert os.path.samestat(before, os.fstat(descriptor))


def test_replay_nonpipe_ready_channel_remains_open_after_rejection(tmp_path, monkeypatch) -> None:
    import cryodaq.replay_engine.__main__ as replay_main

    path = tmp_path / "not-a-pipe"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    before = os.fstat(descriptor)
    monkeypatch.setattr(replay_main.sys, "platform", "linux")
    try:
        with pytest.raises(RuntimeError, match="launcher replay readiness channel is invalid"):
            replay_main._consume_replay_ready_channel(f"fd:{descriptor}")

        assert os.path.samestat(before, os.fstat(descriptor))
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("descriptor", [0, 1, 2])
def test_replay_windows_ready_handle_rejects_standard_handles_before_conversion(
    monkeypatch,
    descriptor: int,
) -> None:
    import cryodaq.replay_engine.__main__ as replay_main

    standard_handles = {index: 20_000 + index for index in range(3)}
    open_osfhandle = MagicMock()
    fake_msvcrt = SimpleNamespace(
        get_osfhandle=lambda fd: standard_handles[fd],
        open_osfhandle=open_osfhandle,
    )
    monkeypatch.setattr(replay_main.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    with pytest.raises(RuntimeError, match="launcher replay readiness channel is invalid"):
        replay_main._consume_replay_ready_channel(f"handle:{standard_handles[descriptor]}")

    open_osfhandle.assert_not_called()


def test_replay_wait_never_accepts_port_occupancy_without_exact_session(monkeypatch) -> None:
    from cryodaq.launcher import LauncherWindow

    monkeypatch.setattr("cryodaq.launcher.time.sleep", lambda _delay: None)
    monkeypatch.setattr("cryodaq.launcher._is_port_busy", lambda _port: True)
    fake = SimpleNamespace(
        _replay_source=Path(_REPLAY_SOURCE),
        _engine_proc=SimpleNamespace(pid=_REPLAY_PID, poll=lambda: None),
        _replay_ready=threading.Event(),
        _replay_ready_lock=threading.Lock(),
        _replay_ready_state={"receipt": None, "error": None},
        _probe_exact_replay_session=lambda: False,
        _replay_engine_failed=False,
    )

    with pytest.raises(RuntimeError, match="exact session readiness"):
        LauncherWindow._wait_engine_ready(fake, max_attempts=1, interval_s=0)

    assert fake._replay_engine_failed is True


def test_live_wait_never_accepts_port_occupancy_without_exact_child_session(monkeypatch) -> None:
    from cryodaq.launcher import LauncherWindow

    monkeypatch.setattr("cryodaq.launcher.time.sleep", lambda _delay: None)
    monkeypatch.setattr("cryodaq.launcher._is_port_busy", lambda _port: True)
    fake = SimpleNamespace(
        _replay_source=None,
        _engine_proc=SimpleNamespace(pid=_ENGINE_PID, poll=lambda: None),
        _engine_ready=threading.Event(),
        _engine_ready_lock=threading.Lock(),
        _engine_ready_state={"receipt": None, "error": None},
        _probe_exact_live_engine_session=lambda: False,
    )

    with pytest.raises(RuntimeError, match="exact live engine readiness"):
        LauncherWindow._wait_engine_ready(fake, max_attempts=1, interval_s=0)


def test_live_probe_binds_private_receipt_to_exact_rep_incarnation(monkeypatch) -> None:
    from cryodaq.launcher import LauncherWindow

    receipt = json.loads(_engine_ready_frame().split(b" ", 1)[1])
    reply = json.loads(_engine_ready_reply_frame())
    encoded_reply = json.dumps(
        reply,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    sockets = [MagicMock(), MagicMock()]
    context = MagicMock()
    context.socket.side_effect = sockets
    for socket in sockets:
        socket.recv.return_value = encoded_reply
    monkeypatch.setattr("zmq.Context", lambda: context)
    ready = threading.Event()
    ready.set()
    fake = SimpleNamespace(
        _engine_proc=SimpleNamespace(pid=_ENGINE_PID, poll=lambda: None),
        _engine_instance_id=_ENGINE_INSTANCE,
        _engine_ready_nonce=_ENGINE_NONCE,
        _engine_ready=ready,
        _engine_ready_lock=threading.Lock(),
        _engine_ready_state={"receipt": receipt, "error": None},
    )

    assert LauncherWindow._probe_exact_live_engine_session(fake) is True
    challenge = {
        "cmd": "engine_ready",
        "nonce": _ENGINE_NONCE,
        "engine_instance_id": _ENGINE_INSTANCE,
        "pid": _ENGINE_PID,
        "pub_addr": _ENGINE_PUB,
        "cmd_addr": _ENGINE_CMD,
        "safe_cmd_addr": _ENGINE_SAFE_CMD,
    }
    for socket, address in zip(sockets, (_ENGINE_CMD, _ENGINE_SAFE_CMD), strict=True):
        socket.send_json.assert_called_once_with(challenge)
        socket.connect.assert_called_once_with(address)
        socket.close.assert_called_once_with(linger=0)


def test_live_probe_refuses_when_only_safe_endpoint_has_mismatched_incarnation(monkeypatch) -> None:
    from cryodaq.launcher import LauncherWindow

    receipt = json.loads(_engine_ready_frame().split(b" ", 1)[1])
    ordinary = MagicMock()
    ordinary.recv.return_value = _engine_ready_reply_frame()
    safe = MagicMock()
    safe.recv.return_value = _engine_ready_reply_frame(engine_instance_id="e" * 32)
    context = MagicMock()
    context.socket.side_effect = [ordinary, safe]
    monkeypatch.setattr("zmq.Context", lambda: context)
    ready = threading.Event()
    ready.set()
    fake = SimpleNamespace(
        _engine_proc=SimpleNamespace(pid=_ENGINE_PID, poll=lambda: None),
        _engine_instance_id=_ENGINE_INSTANCE,
        _engine_ready_nonce=_ENGINE_NONCE,
        _engine_ready=ready,
        _engine_ready_lock=threading.Lock(),
        _engine_ready_state={"receipt": receipt, "error": None},
    )

    assert LauncherWindow._probe_exact_live_engine_session(fake) is False
    ordinary.connect.assert_called_once_with(_ENGINE_CMD)
    safe.connect.assert_called_once_with(_ENGINE_SAFE_CMD)


@pytest.mark.parametrize(
    "raw_reply",
    [
        b'{"ok":true,"ok":true}',
        b'{"ok":true,"pid":NaN}',
        b'{"ok":true,"nonce":"\xff"}',
        b"{" + (b"x" * 8192) + b"}",
        json.dumps({"ok": True, **json.loads(_engine_ready_frame().split(b" ", 1)[1])}).encode("ascii"),
        _engine_ready_reply_frame(proto=True),
        _engine_ready_reply_frame(proto=3),
        _engine_ready_reply_frame(engine_instance_id="e" * 32),
        _engine_ready_reply_frame(extra="not-allowed"),
    ],
)
def test_live_probe_rejects_non_exact_rep_wire_encodings(monkeypatch, raw_reply: bytes) -> None:
    from cryodaq.launcher import LauncherWindow

    receipt = json.loads(_engine_ready_frame().split(b" ", 1)[1])
    socket = MagicMock()
    socket.recv.return_value = raw_reply
    context = MagicMock()
    context.socket.return_value = socket
    monkeypatch.setattr("zmq.Context", lambda: context)
    ready = threading.Event()
    ready.set()
    fake = SimpleNamespace(
        _engine_proc=SimpleNamespace(pid=_ENGINE_PID, poll=lambda: None),
        _engine_instance_id=_ENGINE_INSTANCE,
        _engine_ready_nonce=_ENGINE_NONCE,
        _engine_ready=ready,
        _engine_ready_lock=threading.Lock(),
        _engine_ready_state={"receipt": receipt, "error": None},
    )

    assert LauncherWindow._probe_exact_live_engine_session(fake) is False


def test_external_engine_adoption_is_refused_without_contacting_rep(monkeypatch) -> None:
    from cryodaq.launcher import LauncherWindow

    request = MagicMock()
    monkeypatch.setattr("cryodaq.launcher._request_engine_ready_reply", request)

    assert LauncherWindow._probe_external_engine_incarnation(SimpleNamespace(), _ENGINE_PID) is None
    assert LauncherWindow._probe_external_engine_incarnation(SimpleNamespace(), _ENGINE_PID + 1) is None
    request.assert_not_called()


def test_live_start_refuses_foreign_busy_ports_without_exact_lock_incarnation(tmp_path, monkeypatch) -> None:
    from cryodaq.launcher import LauncherWindow

    spawn = MagicMock()
    fake = SimpleNamespace(
        _engine_unsettled_incarnation=None,
        _engine_proc=None,
        _engine_instance_id=None,
        _engine_shutdown_capability=None,
        _engine_shutdown_request_id=None,
        _engine_shutdown_receipt=None,
        _engine_ready_nonce=None,
        _engine_external=False,
        _external_engine_ready_receipt=None,
        _replay_source=None,
        _check_predictor_bootstrap_hint=MagicMock(),
    )
    monkeypatch.setattr("cryodaq.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("cryodaq.launcher._is_port_busy", lambda _port: True)
    monkeypatch.setattr("cryodaq.launcher.subprocess.Popen", spawn)

    with pytest.raises(RuntimeError, match="ports are occupied without an adoptable exact lock-bound incarnation"):
        LauncherWindow._start_engine(fake)

    spawn.assert_not_called()
    assert fake._engine_proc is None
    assert fake._engine_external is False
    assert fake._external_engine_ready_receipt is None


def test_held_foreign_lock_refuses_self_attestation_before_rep_or_spawn(tmp_path, monkeypatch) -> None:
    import cryodaq.launcher as launcher

    lock_path = tmp_path / ".engine.lock"
    lock_path.write_text(f"{_ENGINE_PID}\n", encoding="ascii")
    spawn = MagicMock()
    request = MagicMock()
    fake = SimpleNamespace(
        _engine_unsettled_incarnation=None,
        _engine_proc=None,
        _engine_instance_id=None,
        _engine_shutdown_capability=None,
        _engine_shutdown_request_id=None,
        _engine_shutdown_receipt=None,
        _engine_ready_nonce=None,
        _engine_external=False,
        _external_engine_ready_receipt=None,
        _replay_source=None,
        _check_predictor_bootstrap_hint=MagicMock(),
    )
    monkeypatch.setattr("cryodaq.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher.os, "open", lambda *_args, **_kwargs: 17)
    monkeypatch.setattr(launcher.os, "close", lambda _fd: None)
    monkeypatch.setattr(launcher.os, "lseek", lambda *_args: 0)
    monkeypatch.setattr(launcher, "_opened_real_regular_file_matches", lambda *_args: True)
    fake_msvcrt = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=MagicMock(side_effect=OSError("held")))
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(launcher, "_request_engine_ready_reply", request)
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)

    with pytest.raises(RuntimeError, match="engine lock is held; unauthenticated external adoption is refused"):
        launcher.LauncherWindow._start_engine(fake)

    spawn.assert_not_called()
    request.assert_not_called()
    assert fake._engine_external is False
    assert fake._external_engine_ready_receipt is None


def test_replay_probe_binds_full_private_receipt_to_exact_raw_rep_incarnation(monkeypatch) -> None:
    import zmq

    from cryodaq.launcher import LauncherWindow

    receipt = json.loads(_replay_ready_frame().split(b" ", 1)[1])
    sockets = [MagicMock(), MagicMock()]
    context = MagicMock()
    context.socket.side_effect = sockets
    for socket in sockets:
        socket.recv.return_value = _replay_ready_reply_frame()
    monkeypatch.setattr("zmq.Context", lambda: context)
    process = SimpleNamespace(pid=_REPLAY_PID, poll=lambda: None)
    ready = threading.Event()
    ready.set()
    fake = SimpleNamespace(
        _engine_proc=process,
        _replay_source=Path(_REPLAY_SOURCE),
        _replay_speed=_REPLAY_SPEED,
        _replay_session_id=_REPLAY_SESSION,
        _replay_ready_nonce=_REPLAY_NONCE,
        _replay_ready=ready,
        _replay_ready_lock=threading.Lock(),
        _replay_ready_state={"receipt": receipt, "error": None},
    )

    assert LauncherWindow._probe_exact_replay_session(fake) is True
    expected_challenge = json.dumps(
        {"cmd": "replay_ready", **receipt},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    for socket, address in zip(sockets, (_ENGINE_CMD, _ENGINE_SAFE_CMD), strict=True):
        socket.send.assert_called_once_with(expected_challenge)
        socket.setsockopt.assert_any_call(zmq.MAXMSGSIZE, 8192)
        socket.connect.assert_called_once_with(address)
        socket.close.assert_called_once_with(linger=0)


def test_replay_probe_refuses_when_only_safe_endpoint_has_mismatched_session(monkeypatch) -> None:
    from cryodaq.launcher import LauncherWindow

    receipt = json.loads(_replay_ready_frame().split(b" ", 1)[1])
    ordinary = MagicMock()
    ordinary.recv.return_value = _replay_ready_reply_frame()
    safe = MagicMock()
    safe.recv.return_value = _replay_ready_reply_frame(session_id="e" * 32)
    context = MagicMock()
    context.socket.side_effect = [ordinary, safe]
    monkeypatch.setattr("zmq.Context", lambda: context)
    ready = threading.Event()
    ready.set()
    fake = SimpleNamespace(
        _engine_proc=SimpleNamespace(pid=_REPLAY_PID, poll=lambda: None),
        _replay_source=Path(_REPLAY_SOURCE),
        _replay_speed=_REPLAY_SPEED,
        _replay_session_id=_REPLAY_SESSION,
        _replay_ready_nonce=_REPLAY_NONCE,
        _replay_ready=ready,
        _replay_ready_lock=threading.Lock(),
        _replay_ready_state={"receipt": receipt, "error": None},
    )

    assert LauncherWindow._probe_exact_replay_session(fake) is False
    ordinary.connect.assert_called_once_with(_ENGINE_CMD)
    safe.connect.assert_called_once_with(_ENGINE_SAFE_CMD)


@pytest.mark.parametrize(
    "raw_reply",
    [
        json.dumps(
            {
                "ok": True,
                "mode": "replay",
                "launcher_session_id": _REPLAY_SESSION,
                "replay_source": _REPLAY_SOURCE,
                "replay_speed": _REPLAY_SPEED,
            },
            separators=(",", ":"),
        ).encode("ascii"),
        json.dumps({"ok": True, **json.loads(_replay_ready_frame().split(b" ", 1)[1])}).encode("ascii"),
        _replay_ready_reply_frame(proto=True),
        _replay_ready_reply_frame(proto=3),
        _replay_ready_reply_frame(extra="not-allowed"),
        b'{"ok":true,"ok":true}',
        b'{"ok":true,"speed":NaN}',
        b'{"ok":true,"source":"\xff"}',
        _replay_ready_reply_frame() + b"\r\n",
        b"{" + (b"x" * 8192) + b"}",
    ],
)
def test_replay_probe_rejects_status_subset_nonexact_proto_and_malformed_raw_reply(
    monkeypatch,
    raw_reply: bytes,
) -> None:
    from cryodaq.launcher import LauncherWindow

    receipt = json.loads(_replay_ready_frame().split(b" ", 1)[1])
    socket = MagicMock()
    socket.recv.return_value = raw_reply
    context = MagicMock()
    context.socket.return_value = socket
    monkeypatch.setattr("zmq.Context", lambda: context)
    process = MagicMock(pid=_REPLAY_PID)
    process.pid = _REPLAY_PID
    process.poll.return_value = None
    ready = threading.Event()
    ready.set()
    fake = SimpleNamespace(
        _engine_proc=process,
        _replay_source=Path(_REPLAY_SOURCE),
        _replay_speed=_REPLAY_SPEED,
        _replay_session_id=_REPLAY_SESSION,
        _replay_ready_nonce=_REPLAY_NONCE,
        _replay_ready=ready,
        _replay_ready_lock=threading.Lock(),
        _replay_ready_state={"receipt": receipt, "error": None},
    )

    assert LauncherWindow._probe_exact_replay_session(fake) is False
    socket.close.assert_called_once_with(linger=0)
    context.term.assert_called_once_with()


def test_replay_health_evaluates_process_and_bridge_without_live_status_workers(monkeypatch) -> None:
    import cryodaq.launcher as launcher
    from cryodaq.gui.tray_status import resolve_tray_status

    worker_commands: list[dict] = []

    def forbidden_worker(command, **_kwargs):  # noqa: ANN001
        worker_commands.append(dict(command))
        raise AssertionError("replay health attempted to construct a live status worker")

    monkeypatch.setattr(launcher, "ZmqCommandWorker", forbidden_worker)
    process_health = MagicMock(return_value=True)
    bridge_health = MagicMock(return_value=True)
    tray = SimpleNamespace(setIcon=MagicMock(), setToolTip=MagicMock())
    host = SimpleNamespace(
        _runtime_callbacks_open=True,
        _shutdown_requested=False,
        _assistant_enabled=False,
        _is_engine_alive=process_health,
        _restart_giving_up=False,
        _engine_unsettled_incarnation=None,
        _bridge_restart_fault=False,
        _bridge_restart_hold=False,
        _tray_only=True,
        _clear_engine_down_banner=MagicMock(),
        _restart_attempts=0,
        _engine_external=False,
        _replay_source=Path(_REPLAY_SOURCE),
        _bridge=SimpleNamespace(is_alive=bridge_health),
        _last_safety_state="ready",
        _last_alarm_count=0,
        _safety_worker=None,
        _annunciation_worker=None,
        _safety_status_generation=0,
        _annunciation_status_generation=0,
        _capture_launcher_status_authority=MagicMock(
            side_effect=AssertionError("replay must not capture live status authority")
        ),
        _invalidate_launcher_status_authority=MagicMock(
            side_effect=AssertionError("healthy replay must retain replay TopWatch authority")
        ),
        _last_reading_time=0.0,
        _periodic_reporting_fault=False,
        _tray_icon_green="green",
        _tray_icon_yellow="yellow",
        _tray_icon_red="red",
        _tray=tray,
    )

    launcher.LauncherWindow._check_engine_health(host)

    assert process_health.call_count == 1
    assert bridge_health.call_count == 1
    host._clear_engine_down_banner.assert_called_once_with()
    assert worker_commands == []
    assert host._safety_worker is None
    assert host._annunciation_worker is None
    assert host._last_safety_state is None
    assert host._last_alarm_count is None
    expected = resolve_tray_status(
        connected=True,
        safety_state=None,
        alarm_count=None,
        data_fresh=False,
        reporting_fault=False,
    )
    tray.setIcon.assert_called_once_with("yellow")
    tray.setToolTip.assert_called_once_with(expected.tooltip)

    launcher.LauncherWindow._on_safety_result(host, {"ok": True}, object())
    launcher.LauncherWindow._on_annunciation_result(host, {"ok": True}, object())
    assert host._last_safety_state is None
    assert host._last_alarm_count is None


def test_real_replay_launcher_health_and_root_shutdown_preserve_hold_without_live_alarm_owners(
    monkeypatch,
) -> None:
    from PySide6.QtCore import QThread
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QApplication

    import cryodaq.launcher as launcher

    app = QApplication.instance() or QApplication([])
    worker_commands: list[dict] = []
    beeps: list[str] = []
    quits: list[str] = []
    bridge_events: list[str] = []

    def forbidden_worker(command, **_kwargs):  # noqa: ANN001
        worker_commands.append(dict(command))
        raise AssertionError("replay lifecycle attempted to construct a live status worker")

    class Bridge:
        def start(self) -> None:
            return None

        def is_alive(self) -> bool:
            return True

        def restart_count(self) -> int:
            return 0

        def shutdown(self) -> None:
            bridge_events.append("shutdown")

        def close(self) -> None:
            bridge_events.append("close")

    class SnapshotIngress:
        active = True

        def invalidate_producer(self) -> None:
            return None

        def stop(self) -> None:
            self.active = False

    bridge = Bridge()
    tray = SimpleNamespace(
        setIcon=MagicMock(),
        setToolTip=MagicMock(),
        show=MagicMock(),
        showMessage=MagicMock(),
        hide=MagicMock(),
        isVisible=MagicMock(return_value=True),
    )

    def controlled_construction_step(self, phase: str, action):  # noqa: ANN001
        if phase == "bridge_bootstrap":
            self._bridge = bridge
            launcher.set_bridge(bridge)
            return None
        if phase == "engine":
            self._replay_session_id = _REPLAY_SESSION
            self._replay_session_verified = True
            return None
        if phase == "ui":
            return action()
        if phase == "tray":
            self._tray = tray
            self._tray_icon_green = "green"
            self._tray_icon_yellow = "yellow"
            self._tray_icon_red = "red"
            return None
        if phase == "health_timer":
            return action()
        return None

    def anchor_snapshot(_bridge, _window, *, expected_mode, anchor) -> None:  # noqa: ANN001
        from cryodaq.operator_snapshot import SnapshotMode

        assert expected_mode is SnapshotMode.REPLAY
        anchor(SnapshotIngress())

    monkeypatch.setattr(launcher, "_assistant_runtime_decision", lambda *, experiment_mode: (False, False))
    monkeypatch.setattr(launcher, "ZmqCommandWorker", forbidden_worker)
    monkeypatch.setattr(
        "cryodaq.gui.shell.overlays.alarm_panel.ZmqCommandWorker",
        forbidden_worker,
    )
    monkeypatch.setattr(launcher, "start_operator_snapshot_ingress", anchor_snapshot)
    monkeypatch.setattr(launcher.LauncherWindow, "_run_construction_step", controlled_construction_step)
    monkeypatch.setattr(launcher.LauncherWindow, "_merge_main_window_menus", lambda self: None)
    monkeypatch.setattr(launcher.LauncherWindow, "_build_settings_menu", lambda self: None)
    monkeypatch.setattr(launcher.LauncherWindow, "_is_engine_alive", lambda self: True)
    monkeypatch.setattr(launcher.LauncherWindow, "_stop_engine", lambda self: None)
    monkeypatch.setattr(launcher.LauncherWindow, "_stop_assistant", lambda self: None)
    monkeypatch.setattr(launcher.LauncherWindow, "_schedule_shutdown_retry", lambda self: None)
    monkeypatch.setattr(QApplication, "beep", lambda: beeps.append("hold"))
    monkeypatch.setattr(QApplication, "quit", lambda _self: quits.append("quit"))

    window = launcher.LauncherWindow(app, replay_source=Path(_REPLAY_SOURCE))
    main_window = window._main_window
    assert main_window is not None

    class UnsettledThread(QThread):
        def __init__(self) -> None:
            super().__init__(main_window)
            self.running = True

        def isRunning(self) -> bool:  # noqa: N802
            return self.running

        def requestInterruption(self) -> None:  # noqa: N802
            return None

        def quit(self) -> None:
            return None

        def wait(self, _timeout_ms: int) -> bool:
            return not self.running

    unsettled = UnsettledThread()
    try:
        assert main_window._annunciation_controller is None
        assert main_window._alarm_panel._live_capable is False
        assert main_window._alarm_panel._v2_poll_timer is None
        assert main_window._alarm_panel._cooldown_poll_timer is None
        assert window._health_timer is not None and window._health_timer.isActive()
        assert worker_commands == []
        assert beeps == []

        window._health_timer.timeout.emit()
        assert worker_commands == []
        assert window._safety_worker is None
        assert window._annunciation_worker is None
        assert window._last_safety_state is None
        assert window._last_alarm_count is None

        first_close = QCloseEvent()
        main_window.closeEvent(first_close)
        assert first_close.isAccepted() is False
        assert window._shutdown_phase is launcher._ShutdownPhase.RETRY_WAIT
        assert window._shutdown_hold_audible is True
        assert window._shutdown_hold_timer is not None
        assert window._shutdown_hold_timer.isActive()
        assert quits == []
        assert bridge_events == []

        unsettled.running = False
        second_close = QCloseEvent()
        main_window.closeEvent(second_close)
        assert second_close.isAccepted() is False
        assert window._shutdown_phase is launcher._ShutdownPhase.COMPLETE
        assert window._shutdown_hold_audible is False
        assert not window._shutdown_hold_timer.isActive()
        assert bridge_events == ["shutdown", "close"]
        assert quits == ["quit"]
        assert worker_commands == []
    finally:
        if window._health_timer is not None:
            window._health_timer.stop()
        if window._shutdown_hold_timer is not None:
            window._shutdown_hold_timer.stop()
            window._shutdown_hold_timer.deleteLater()
        window.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------------------
# Helpers to invoke argparse the same way main() does, without Qt
# ---------------------------------------------------------------------------


def _parse_launcher_args(argv: list[str]) -> argparse.Namespace:
    """Run the same argparse block as launcher.main() without spawning Qt."""
    from cryodaq.launcher import _REPLAY_LIST_SENTINEL

    parser = argparse.ArgumentParser(description="CryoDAQ Launcher")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--tray", action="store_true")
    parser.add_argument("--replay", nargs="?", const=_REPLAY_LIST_SENTINEL, default=None, metavar="PATH")
    parser.add_argument("--replay-speed", type=float, default=5.0)
    parser.add_argument("--replay-phase", type=str, default="cooldown")
    parser.add_argument("--replay-loop", action="store_true")
    parser.add_argument("--force-replay", action="store_true")
    args, _ = parser.parse_known_args(argv)
    return args


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def test_launcher_replay_flag_parsed():
    args = _parse_launcher_args(["--replay", "/fake/path.db", "--replay-speed", "50"])
    assert args.replay == "/fake/path.db"
    assert args.replay_speed == 50.0


def test_launcher_replay_speed_default_five():
    args = _parse_launcher_args(["--replay", "/some.db"])
    assert args.replay_speed == 5.0


def test_launcher_replay_phase_default_cooldown():
    args = _parse_launcher_args(["--replay", "/some.db"])
    assert args.replay_phase == "cooldown"


def test_launcher_replay_sentinel_when_no_path():
    from cryodaq.launcher import _REPLAY_LIST_SENTINEL

    args = _parse_launcher_args(["--replay"])
    assert args.replay == _REPLAY_LIST_SENTINEL


# ---------------------------------------------------------------------------
# Mutual exclusion
# ---------------------------------------------------------------------------


@patch("cryodaq.logging_setup.setup_logging")
def test_launcher_replay_and_mock_mutually_exclusive(_setup_logging: MagicMock, monkeypatch, capsys):
    """--mock + --replay must raise SystemExit before Qt starts."""
    monkeypatch.setattr(sys, "argv", ["cryodaq", "--mock", "--replay", "/some.db"])
    # Prevent Qt from starting
    with patch("cryodaq.launcher.QApplication"), pytest.raises(SystemExit) as exc_info:
        from cryodaq import launcher

        # Reload to pick up monkeypatched argv isn't needed —
        # we call main() which reads sys.argv via parse_known_args.
        launcher.main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "--mock" in captured.err and "--replay" in captured.err


# ---------------------------------------------------------------------------
# _start_engine cmd construction — uses SimpleNamespace to avoid Qt init
# ---------------------------------------------------------------------------


def _make_fake_self(src: Path, *, loop: bool = False) -> object:
    import types

    return types.SimpleNamespace(
        _mock=False,
        _replay_source=src,
        _replay_speed=5.0,
        _replay_phase="cooldown",
        _replay_loop=loop,
        _force_replay=False,
        _legacy_channel_era=None,
        _engine_proc=None,
        _engine_external=False,
        _engine_stderr_handler=None,
        _engine_stderr_logger=None,
        _engine_stderr_thread=None,
        _bridge=MagicMock(),
        _replay_session_verified=False,
        _wait_engine_ready=MagicMock(),
    )


def test_launcher_has_no_generic_ping_or_port_only_adoption() -> None:
    """Ports may reject startup, but only exact receipts may authorize it."""

    import ast
    import inspect
    import textwrap

    import cryodaq.launcher as launcher

    module_tree = ast.parse(Path(launcher.__file__).read_text(encoding="utf-8"))
    assert not any(
        (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_ping_engine")
        or (isinstance(node, ast.Name) and node.id == "_ping_engine")
        or (isinstance(node, ast.Attribute) and node.attr == "_ping_engine")
        for node in ast.walk(module_tree)
    )

    start_tree = ast.parse(textwrap.dedent(inspect.getsource(launcher.LauncherWindow._start_engine)))
    busy_guards = [
        node
        for node in ast.walk(start_tree)
        if isinstance(node, ast.If)
        and any(
            isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "_is_port_busy"
            for child in ast.walk(node.test)
        )
    ]
    assert len(busy_guards) == 1
    assert len(busy_guards[0].body) == 1 and isinstance(busy_guards[0].body[0], ast.Raise)


def test_launcher_port_collision_probe_includes_dedicated_safe_endpoint(monkeypatch) -> None:
    import cryodaq.launcher as launcher

    attempted_ports: list[int] = []

    class Socket:
        def settimeout(self, _timeout: float) -> None:
            return None

        def connect_ex(self, target: tuple[str, int]) -> int:
            attempted_ports.append(target[1])
            return 0 if target[1] == 5558 else 1

        def close(self) -> None:
            return None

    monkeypatch.setattr("socket.socket", lambda *_args, **_kwargs: Socket())

    assert launcher._is_port_busy(5555) is True
    assert attempted_ports == [5555, 5556, 5558]


def _stderr_logger_retval() -> tuple:
    return (MagicMock(), MagicMock(), Path("/tmp/x.log"))


def _pipe_backed_process(pid: int) -> MagicMock:
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    process = MagicMock()
    process.pid = pid
    process.stderr = os.fdopen(read_fd, "rb", buffering=0)
    return process


def test_launcher_start_engine_builds_replay_cmd():
    """_start_engine dispatches to cryodaq.replay_engine with correct args."""
    captured_cmd: list[str] = []
    src = Path("/data/run.db")

    def fake_popen(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return _pipe_backed_process(12345)

    from cryodaq.launcher import LauncherWindow

    fake = _make_fake_self(src)
    try:
        with (
            patch("cryodaq.launcher._is_port_busy", return_value=False),
            patch("cryodaq.launcher.subprocess.Popen", side_effect=fake_popen),
            patch(
                "cryodaq.launcher._create_engine_stderr_logger",
                return_value=_stderr_logger_retval(),
            ),
            patch("cryodaq.launcher.LauncherWindow._wait_engine_ready"),
            patch("cryodaq.paths.get_data_dir", return_value=Path("/data")),
        ):
            LauncherWindow._start_engine(fake)
    finally:
        LauncherWindow._close_engine_stderr_stream(fake)

    assert "-m" in captured_cmd
    replay_m_idx = captured_cmd.index("-m")
    assert captured_cmd[replay_m_idx + 1] == "cryodaq.replay_engine"
    assert "--source" in captured_cmd
    assert captured_cmd[captured_cmd.index("--source") + 1] == str(src)
    assert "--speed" in captured_cmd
    assert captured_cmd[captured_cmd.index("--speed") + 1] == "5.0"
    assert "--safe-cmd-addr" in captured_cmd
    assert captured_cmd[captured_cmd.index("--safe-cmd-addr") + 1] == _ENGINE_SAFE_CMD


def test_launcher_start_engine_appends_loop_flag():
    captured_cmd: list[str] = []
    src = Path("/data/run.db")

    def fake_popen(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return _pipe_backed_process(1)

    from cryodaq.launcher import LauncherWindow

    fake = _make_fake_self(src, loop=True)
    try:
        with (
            patch("cryodaq.launcher._is_port_busy", return_value=False),
            patch("cryodaq.launcher.subprocess.Popen", side_effect=fake_popen),
            patch(
                "cryodaq.launcher._create_engine_stderr_logger",
                return_value=_stderr_logger_retval(),
            ),
            patch("cryodaq.launcher.LauncherWindow._wait_engine_ready"),
            patch("cryodaq.paths.get_data_dir", return_value=Path("/data")),
        ):
            LauncherWindow._start_engine(fake)
    finally:
        LauncherWindow._close_engine_stderr_stream(fake)

    assert "--loop" in captured_cmd


# ---------------------------------------------------------------------------
# Source listing (_print_replay_sources)
# ---------------------------------------------------------------------------


def test_launcher_replay_no_source_lists_available(tmp_path, capsys):
    """--replay without path prints listing and exits 0."""
    cooldown_dir = tmp_path / "cooldown_v5"
    cooldown_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Write two minimal curve JSON files
    for i in range(2):
        (cooldown_dir / f"curve_{i}.json").write_text(
            json.dumps({"duration_hours": 8.0 + i, "T_cold_final": 3.1 + i * 0.5}),
            encoding="utf-8",
        )

    # Write one SQLite DB
    con = sqlite3.connect(str(data_dir / "data_2026-04-21.db"))
    con.execute("CREATE TABLE readings (timestamp REAL, channel TEXT, value REAL)")
    con.execute("INSERT INTO readings VALUES (1745000000.0, 'Т12', 3.1)")
    con.commit()
    con.close()

    with patch("cryodaq.paths.get_data_dir", return_value=data_dir):
        from cryodaq.launcher import _print_replay_sources

        _print_replay_sources()

    out = capsys.readouterr().out
    assert "curve_0.json" in out
    assert "curve_1.json" in out
    assert "data_2026-04-21.db" in out
    assert "cryodaq --replay" in out


def test_launcher_replay_listing_handles_missing_cooldown_v5(tmp_path, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    with patch("cryodaq.paths.get_data_dir", return_value=data_dir):
        from cryodaq.launcher import _print_replay_sources

        _print_replay_sources()

    out = capsys.readouterr().out
    assert "(нет файлов)" in out


def test_launcher_replay_listing_handles_missing_data_dir(tmp_path, capsys):
    data_dir = tmp_path / "data"  # does not exist
    cooldown_dir = tmp_path / "cooldown_v5"
    cooldown_dir.mkdir()

    with patch("cryodaq.paths.get_data_dir", return_value=data_dir):
        from cryodaq.launcher import _print_replay_sources

        _print_replay_sources()

    out = capsys.readouterr().out
    assert "(нет файлов)" in out


def test_launcher_replay_listing_handles_malformed_json(tmp_path, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    cooldown_dir = tmp_path / "cooldown_v5"
    cooldown_dir.mkdir()
    (cooldown_dir / "bad_curve.json").write_text("{not valid json", encoding="utf-8")

    with patch("cryodaq.paths.get_data_dir", return_value=data_dir):
        from cryodaq.launcher import _print_replay_sources

        _print_replay_sources()  # must not raise

    out = capsys.readouterr().out
    assert "bad_curve.json" in out
    assert "ошибка чтения" in out


def test_launcher_qtimer_module_import_present() -> None:
    """launcher.QTimer must be the PySide6 QTimer class (not None or shadowed)."""
    from PySide6.QtCore import QTimer as PySide6QTimer

    import cryodaq.launcher as launcher_mod

    assert launcher_mod.QTimer is PySide6QTimer, (
        "launcher.QTimer must be the real PySide6 QTimer imported at module top"
    )
