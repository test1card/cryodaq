"""Verify logging_setup creates rotating files and redacts Telegram tokens."""

from __future__ import annotations

import importlib
import io
import logging


def test_setup_logging_creates_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))

    from cryodaq import logging_setup, paths

    importlib.reload(paths)
    importlib.reload(logging_setup)

    logging_setup.setup_logging("test_component", file=True, console=False)

    logger = logging.getLogger("test.file")
    logger.info("hello world")

    for h in logging.getLogger().handlers:
        h.flush()

    log_file = tmp_path / "logs" / "test_component.log"
    assert log_file.exists(), f"Log file not created at {log_file}"
    content = log_file.read_text(encoding="utf-8")
    assert "hello world" in content


def test_telegram_token_redacted_in_msg():
    from cryodaq import logging_setup

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(logging_setup._TokenRedactFilter())

    logger = logging.getLogger("test.redact_msg")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info(
        "Posting to https://api.telegram.org/bot7701234567:AAEhBP0av8XyZabc-defGHIJ/sendMessage"
    )
    output = stream.getvalue()
    assert "AAEhBP0av8XyZabc-defGHIJ" not in output
    assert "bot***" in output


def test_telegram_token_redacted_in_args():
    from cryodaq import logging_setup

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(logging_setup._TokenRedactFilter())

    logger = logging.getLogger("test.redact_args")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info(
        "URL: %s",
        "https://api.telegram.org/bot7701234567:AAEhBP0av8XyZabc-defGHIJ/sendMessage",
    )
    output = stream.getvalue()
    assert "AAEhBP0av8XyZabc-defGHIJ" not in output, f"Token leaked: {output}"
    assert "bot***" in output


def test_setup_logging_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))
    from cryodaq import logging_setup, paths

    importlib.reload(paths)
    importlib.reload(logging_setup)

    logging_setup.setup_logging("idem_test", file=False)
    n1 = len(logging.getLogger().handlers)
    logging_setup.setup_logging("idem_test", file=False)
    n2 = len(logging.getLogger().handlers)
    assert n1 == n2


def test_bare_token_without_bot_prefix_redacted():
    """Codex P1: bare token (no 'bot' URL prefix) must also be redacted.

    Operators sometimes accidentally log the raw token via
    ``logger.info("token: %s", token_str)`` or via a config dump.
    """
    from cryodaq import logging_setup

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(logging_setup._TokenRedactFilter())

    logger = logging.getLogger("test.bare_token")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    # Bare token form: 10-digit ID + 35-char secret
    logger.info("Loaded token: 7701234567:AAEhBP0av8XyZabc-defGHIJklmnopqrstuv")
    output = stream.getvalue()
    assert "AAEhBP0av8XyZabc-defGHIJklmnopqrstuv" not in output, f"Bare token leaked: {output}"
    assert "***" in output


def test_bare_token_redact_minimum_length():
    """The bare-token regex requires 30+ char secret to avoid false positives
    on unrelated short colon-delimited strings like '123456:abc'."""
    from cryodaq.logging_setup import _redact

    # Real bot token shape — must be redacted
    real = "7701234567:AAEhBP0av8XyZabc-defGHIJklmnopqrstuv"
    assert real not in _redact(f"token={real}")

    # Short colon-delimited (e.g. timestamp, port:host) — must NOT be matched
    short = "12345:abcdef"
    assert short in _redact(f"port {short}")
    short2 = "12:34"
    assert short2 in _redact(f"time {short2}")


def test_redact_filter_handles_non_string_args():
    """Filter must not raise on int / None / dict args."""
    from cryodaq import logging_setup

    f = logging_setup._TokenRedactFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="x=%d y=%s",
        args=(42, "bot1234567:AAA-bbb_CCC-ddd-eee-fff_ggg"),
        exc_info=None,
    )
    assert f.filter(record) is True
    assert "bot***" in (record.msg % record.args)
