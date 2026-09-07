"""A Telegram token must not survive into a logged traceback.

Found 2026-09-07 in the live engine log: fourteen occurrences of the running
bot's token, in plain text, inside `aiohttp.ConnectionTimeoutError` tracebacks
from `telegram_commands._fetch_updates`. Telegram offers no header auth, so the
token is in the URL PATH, and aiohttp puts the full URL into the exception.

`_TokenRedactFilter` was already installed on both handlers and could not help:
a filter rewrites `record.msg` and `record.args`, while `exc_text` is rendered
by the FORMATTER afterwards. Its own docstring claimed to cover "any aiohttp
URL-logging or traceback containing the request URL"; the traceback half was
precisely the half it could not reach.

The same text had by then been copied into a lane log and committed to a pushed
repository. This module pins the log-side hole; rotating the credential and
cleaning that history are separate operator actions.
"""

from __future__ import annotations

import io
import logging
import os

from cryodaq.logging_setup import _redact, _TokenRedactFilter, _TokenRedactFormatter

# Shaped like a real token, and deliberately not one: 10-digit id, 35-char tail.
_FAKE = "7701234567:AAEhBPqrstuvwxyz0123456789ABCDEFGHI"
_URL = f"https://api.telegram.org/bot{_FAKE}/getUpdates?timeout=5&offset=490907051"


def _capture(*, with_formatter: type[logging.Formatter]) -> str:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(with_formatter("%(levelname)s %(name)s %(message)s"))
    handler.addFilter(_TokenRedactFilter())
    logger = logging.getLogger(f"redaction-probe-{with_formatter.__name__}")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    try:
        try:
            raise ConnectionError(f"Connection timeout to host {_URL}")
        except ConnectionError:
            logger.exception("Telegram poll failed")
    finally:
        logger.handlers = []
    return stream.getvalue()


def test_the_token_does_not_reach_the_log_through_a_traceback() -> None:
    written = _capture(with_formatter=_TokenRedactFormatter)
    assert _FAKE not in written, (
        "the bot token survived into a logged traceback — this is the exact "
        f"defect found on 2026-09-07:\n{written}"
    )
    assert "bot***" in written, f"redaction must leave a visible marker:\n{written}"
    # The rest of the line must still be readable: a redactor that eats the
    # diagnosis is a different failure.
    assert "Connection timeout to host" in written
    assert "Telegram poll failed" in written


def test_a_plain_formatter_shows_why_the_filter_alone_was_not_enough() -> None:
    """The negative that names the mechanism, not just the symptom.

    With an ordinary formatter the filter is still installed and still runs —
    and the token appears anyway, because it lives in `exc_text`.
    """
    written = _capture(with_formatter=logging.Formatter)
    assert _FAKE in written, (
        "if this no longer reproduces, the mechanism has changed and the "
        "reason for the formatter needs re-checking"
    )


def test_the_filter_still_covers_message_and_args() -> None:
    """What the filter did do must keep working."""
    redacted = _redact(f"token={_FAKE}")
    assert _FAKE not in redacted
    assert _redact(_URL) == "https://api.telegram.org/bot***/getUpdates?timeout=5&offset=490907051"


def test_a_hardened_handler_writes_no_token_even_from_a_traceback() -> None:
    """Exercise the handler, do not read the source that builds it.

    The previous version of this test asserted that `logging_setup.py`
    contained certain words. Review pointed out on 2026-09-07 that a source
    check cannot see a handler built ANYWHERE ELSE, and one such handler was
    leaking at the time.
    """
    import logging
    import tempfile
    from pathlib import Path

    from cryodaq.logging_setup import install_token_redaction

    path = Path(tempfile.mkdtemp()) / "hardened.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    install_token_redaction(handler, fmt="%(message)s")
    logger = logging.getLogger("test.hardened")
    logger.propagate = False
    logger.setLevel(logging.ERROR)
    logger.addHandler(handler)
    try:
        try:
            raise RuntimeError(f"Cannot connect to host: {_URL}")
        except RuntimeError:
            logger.exception("polling failed")
        logger.error("as an arg: %s", _URL)
        handler.flush()
        written = path.read_text(encoding="utf-8")
    finally:
        handler.close()
        logger.removeHandler(handler)

    assert _FAKE not in written, "the token survived a hardened handler"
    assert "bot***" in written


def test_the_launcher_child_stderr_log_is_hardened(monkeypatch) -> None:
    """The production handler that was leaking, driven for real.

    Reviewer finding, 2026-09-07: `_create_engine_stderr_logger` builds its own
    logger with `propagate = False`, so it never reaches a root handler and
    never inherited the root's redaction — while a comment in the pump claimed
    it did. A child stderr line carrying a `getUpdates` URL wrote the token
    verbatim into `engine.stderr.log`.

    CRYODAQ_STATE_ROOT is redirected because this writes a real log file, and
    the live stand's is not a scratch directory.
    """
    import tempfile
    from pathlib import Path

    monkeypatch.setenv("CRYODAQ_STATE_ROOT", tempfile.mkdtemp())
    from cryodaq.launcher import _create_engine_stderr_logger

    stderr_logger, handler, log_path = _create_engine_stderr_logger()
    assert Path(log_path).parent.is_relative_to(Path(os.environ["CRYODAQ_STATE_ROOT"])), (
        "refusing to run: this test would have written to the real logs directory"
    )
    try:
        stderr_logger.error("engine child stderr; phase=runtime: %s", f"urllib.error: {_URL}")
        handler.flush()
        written = Path(log_path).read_text(encoding="utf-8")
    finally:
        handler.close()
        stderr_logger.removeHandler(handler)

    assert _FAKE not in written, "the launcher still persists the child's token"
    assert "bot***" in written


def test_redaction_stays_linear_on_a_long_near_miss() -> None:
    """A near-miss must not cost seconds. It used to.

    Reviewer measurement, 2026-09-07: with an unbounded digit run, "bot" plus
    40000 digits plus a colon took 3.18 s to NOT match, and the cost grew
    exactly fourfold per doubling. Redaction runs on every record on both
    handlers, so one such line stalls logging repeatedly.

    The threshold is deliberately loose — this catches a return to quadratic
    behaviour, not a small regression in constant factors.
    """
    import time

    hostile = "bot" + "9" * 40000 + ":" + "!" * 20
    started = time.perf_counter()
    result = _redact(hostile)
    elapsed = time.perf_counter() - started

    assert result == hostile, "a near-miss must not be redacted"
    assert elapsed < 0.5, f"redacting a 40k near-miss took {elapsed:.2f}s; the quantifier is unbounded again"


def test_the_cli_entry_point_is_hardened(capsys) -> None:
    """Stand-alone tools print to stderr, and stderr gets captured and kept.

    Reviewer sweep, 2026-09-07: two tools built their own unredacted handler
    with `logging.basicConfig`. They now share one entry point, and this drives
    that entry point rather than reading the tools' source.
    """
    import logging

    from cryodaq.logging_setup import configure_cli_logging

    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    for handler in list(root.handlers):
        root.removeHandler(handler)
    try:
        configure_cli_logging(level=logging.INFO)
        logging.getLogger("tool.under.test").error("polling failed: %s", _URL)
        try:
            raise RuntimeError(f"Cannot connect to host: {_URL}")
        except RuntimeError:
            logging.getLogger("tool.under.test").exception("and again in a traceback")
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)

    written = capsys.readouterr().err
    assert _FAKE not in written, "a stand-alone tool still prints the token"
    assert "bot***" in written
