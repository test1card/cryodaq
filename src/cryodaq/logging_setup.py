"""Shared logging configuration for CryoDAQ entry points.

Replaces scattered ``logging.basicConfig(...)`` calls in launcher, engine,
and gui with a single configurable entry point that writes to both stderr
(for dev / foreground runs) and a rotating file in ``get_logs_dir()``.

Also applies a filter that redacts Telegram bot tokens (Phase 2b K.1
defence-in-depth — combined with the SecretStr wrapper, prevents accidental
token leaks via aiohttp debug logs or exception traces).
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys

from cryodaq.paths import get_logs_dir

# Telegram bot tokens follow ``botID:secret`` shape — 8+ digit bot ID +
# colon + ~35-char base64-ish secret. The token can leak in TWO forms:
#
#   1. URL form: ``https://api.telegram.org/bot7701234567:AAEhBP.../sendMessage``
#      → ``bot`` literal prefix is part of the URL, not the token.
#   2. Bare form: ``token: 7701234567:AAEhBP...`` (operator config dump,
#      pydantic-style repr, accidental ``logger.info("token=%s", token)``).
#
# We match BOTH. Bare form requires 8+ digit ID + 30+ char secret to keep
# false-positive rate near zero on unrelated colon-delimited strings.
# (Codex Phase 2b Block A P1.)
_TELEGRAM_TOKEN_RE = re.compile(r"(?:bot)?\d{6,}:[A-Za-z0-9_-]{20,}")
_BARE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])\d{8,}:[A-Za-z0-9_-]{30,}(?![A-Za-z0-9_-])")


def _redact(text: str) -> str:
    """Apply both URL-form and bare-form token redaction."""
    text = _TELEGRAM_TOKEN_RE.sub("bot***", text)
    text = _BARE_TOKEN_RE.sub("***", text)
    return text


class _TokenRedactFilter(logging.Filter):
    """Strip Telegram bot tokens from log messages.

    Telegram requires the token in the URL path (no header auth available),
    so any aiohttp URL-logging or traceback containing the request URL
    would leak it. This filter rewrites ``botNNNNN:xxxx`` → ``bot***`` in
    both the message template and any args tuple/dict.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact(record.msg)
        if record.args:
            try:
                if isinstance(record.args, tuple):
                    record.args = tuple(
                        _redact(a) if isinstance(a, str) else a for a in record.args
                    )
                elif isinstance(record.args, dict):
                    record.args = {
                        k: (_redact(v) if isinstance(v, str) else v) for k, v in record.args.items()
                    }
            except Exception:
                # Filter must never raise — drop redaction silently if the
                # args object has an unexpected shape.
                pass
        return True


def setup_logging(
    component: str,
    *,
    level: int = logging.INFO,
    console: bool = True,
    file: bool = True,
    when: str = "midnight",
    backup_count: int = 14,
) -> None:
    """Configure root logging for a CryoDAQ entry point.

    Parameters
    ----------
    component:
        Short name used in the log filename (e.g. ``'engine'``, ``'launcher'``,
        ``'gui'``). Becomes ``logs/<component>.log``.
    level:
        Minimum log level. Default ``logging.INFO``.
    console:
        Also log to stderr. Default ``True``.
    file:
        Also log to a rotating file in :func:`cryodaq.paths.get_logs_dir`.
        Default ``True``.
    when, backup_count:
        Passed to :class:`logging.handlers.TimedRotatingFileHandler`. Default:
        rotate at midnight, keep 14 old files.

    Idempotent — subsequent calls replace all handlers on the root logger.
    File logging failures are non-fatal; we fall back to console only and
    write a one-line warning to stderr.
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        # Close before removing to release file descriptors / streams.
        # Without this, repeated setup_logging() calls leak FDs (Codex P2).
        try:
            h.close()
        except Exception:
            pass
        root.removeHandler(h)

    root.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    redact = _TokenRedactFilter()

    if console:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(redact)
        root.addHandler(stream_handler)

    if file:
        try:
            log_dir = get_logs_dir()
            log_path = log_dir / f"{component}.log"
            file_handler = logging.handlers.TimedRotatingFileHandler(
                log_path,
                when=when,
                backupCount=backup_count,
                encoding="utf-8",
                delay=True,
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(redact)
            root.addHandler(file_handler)
        except Exception as exc:
            sys.stderr.write(f"WARNING: failed to set up file logging for {component}: {exc}\n")
