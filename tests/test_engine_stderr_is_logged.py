"""The engine child's stderr must reach the log, not just a note that it existed.

The engine died with SIGBUS six times on 2026-09-02. Its faulthandler traceback
is written to stderr -- exactly the stream this pump forwards -- and what
reached the log was:

    engine child stderr record received; phase=runtime

and nothing else. A record that proves a message existed while withholding it is
not evidence of anything, and it is why the crash could not be attributed. It
also led to a wrong attribution being acted on: a commit was reverted for
causing the crash, and the crash returned hours after that revert.

The content was withheld because engine stderr can carry a Telegram bot token
in a traceback URL. That belongs to the redaction filter already installed on
these handlers, not to withholding the whole line.
"""

from __future__ import annotations

import io
import logging

from cryodaq.launcher import _pump_engine_stderr


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _pump(payload: bytes) -> list[logging.LogRecord]:
    logger = logging.getLogger("test.engine.stderr")
    logger.handlers.clear()
    logger.propagate = False
    capture = _Capture()
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)
    _pump_engine_stderr(io.BytesIO(payload), logger)
    return capture.records


def test_the_child_s_message_is_in_the_log():
    records = _pump(b"Fatal Python error: Bus error\n")
    rendered = " ".join(record.getMessage() for record in records)
    assert "Fatal Python error: Bus error" in rendered


def test_a_faulthandler_traceback_survives_the_pump():
    """The exact shape that was lost when a native crash was being chased."""
    payload = (
        b"Current thread 0x00007f (most recent call first):\n"
        b'  File "/home/lab53/cryodaq/src/cryodaq/drivers/transport/gpib.py", line 750 in _blocking_query\n'
    )
    rendered = " ".join(record.getMessage() for record in _pump(payload))
    assert "_blocking_query" in rendered
    assert "gpib.py" in rendered


def test_undecodable_bytes_do_not_break_the_pump():
    records = _pump(b"\xff\xfe broken \xc3\x28 bytes\n")
    assert records, "a line that cannot be decoded must still be reported"


def test_an_empty_line_is_not_logged():
    assert _pump(b"\n   \n") == []


def test_the_text_is_passed_as_an_argument_so_redaction_can_reach_it():
    """_TokenRedactFilter rewrites record.args; inlining the text would evade it."""
    records = _pump(b"https://api.telegram.org/bot12345:SECRET/sendMessage failed\n")
    assert records
    assert records[0].args, "the child's text must be an arg, not baked into the message"
    assert "bot12345:SECRET" not in records[0].msg
