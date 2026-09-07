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


def test_setup_logging_installs_the_redacting_formatter() -> None:
    """Read the wiring: both handlers must get it, not just one."""
    from pathlib import Path

    source = (Path(__file__).parents[1] / "src" / "cryodaq" / "logging_setup.py").read_text(encoding="utf-8")
    assert "formatter = _TokenRedactFormatter(" in source, (
        "setup_logging must build the redacting formatter, not a plain one"
    )
    assert source.count("setFormatter(formatter)") == 2, (
        "both the stream and file handlers must use it"
    )
