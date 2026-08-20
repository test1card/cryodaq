"""Shared logging configuration for CryoDAQ entry points.

Replaces scattered ``logging.basicConfig(...)`` calls in launcher, engine,
and gui with a single configurable entry point that writes to both stderr
(for dev / foreground runs) and a rotating file in ``get_logs_dir()``.

Also applies a filter that redacts Telegram bot tokens (Phase 2b K.1
defence-in-depth — combined with the SecretStr wrapper, prevents accidental
token leaks via aiohttp debug logs or exception traces).

IV.4 Finding 2: ``resolve_log_level()`` is the unified entry point for
picking the logging level across launcher / GUI / engine. Priority:

1. ``CRYODAQ_LOG_LEVEL`` environment variable (subprocess propagation
   + operator shell override).
2. GUI-persisted QSettings flag ``logging/debug_mode``.
3. ``logging.INFO`` default.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys

from cryodaq.paths import get_logs_dir

_QSETTINGS_ORG = "FIAN"
_QSETTINGS_APP = "CryoDAQ"
_QSETTINGS_DEBUG_KEY = "logging/debug_mode"
_ENV_VAR = "CRYODAQ_LOG_LEVEL"

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
                    record.args = tuple(_redact(a) if isinstance(a, str) else a for a in record.args)
                elif isinstance(record.args, dict):
                    record.args = {k: (_redact(v) if isinstance(v, str) else v) for k, v in record.args.items()}
            except Exception:
                # Filter must never raise — drop redaction silently if the
                # args object has an unexpected shape.
                pass
        return True


# RECORDS THAT HAPPEN BEFORE THERE IS ANYWHERE TO PUT THEM.
#
# Some facts are settled at import time. `cryodaq.gui.theme` resolves the colour pack at
# module level, and every entry point imports GUI modules before it calls setup_logging --
# `gui/app.py` imports the theme at line 27 and configures logging at line 431. A record
# emitted in that window reaches no file handler, and under the frozen pythonw launcher it
# reaches nothing at all, so "the reason is in the log" would simply be false.
#
# Anything in that position appends here instead, and setup_logging replays it the moment
# there is somewhere for it to go. Bounded, because an unbounded list filled before logging
# exists is a leak nothing would ever notice.
_MAX_DEFERRED_RECORDS = 64
_deferred_records: list[tuple[int, str, tuple[object, ...]]] = []


def defer_record(level: int, message: str, *args: object) -> None:
    """Hold one record until setup_logging has somewhere to put it."""

    if len(_deferred_records) < _MAX_DEFERRED_RECORDS:
        _deferred_records.append((level, message, args))


def _replay_deferred_records() -> None:
    """Emit everything held from before logging existed, oldest first, exactly once."""

    held, _deferred_records[:] = list(_deferred_records), []
    logger = logging.getLogger("cryodaq.startup")
    for level, message, args in held:
        logger.log(level, message, *args)


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
        # Without this, repeated setup_logging() calls leak FDs.
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

    # Now that handlers exist, say the things that could not be said before they did.
    _replay_deferred_records()


def read_debug_mode_from_qsettings() -> bool:
    """Read the debug-mode flag from QSettings, or False if unavailable.

    Returns False if PySide6 is not importable (CLI-only engine runs
    invoked without a GUI process ever having created the QSettings
    file). Caller is also expected to check the ``CRYODAQ_LOG_LEVEL``
    env var — this lets the launcher propagate the GUI choice to the
    engine subprocess without having the engine re-read QSettings from
    its own process.
    """
    try:
        from PySide6.QtCore import QSettings
    except ImportError:
        return False
    try:
        settings = QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
        value = settings.value(_QSETTINGS_DEBUG_KEY, False, type=bool)
    except Exception:
        return False
    return bool(value)


def resolve_log_level() -> int:
    """Unified log-level resolver.

    Priority:

    1. ``CRYODAQ_LOG_LEVEL`` env var (explicit override, also used by
       the launcher to propagate the GUI choice to the engine
       subprocess).
    2. QSettings ``logging/debug_mode`` flag.
    3. ``logging.INFO`` default.

    Values recognised on the env var (case-insensitive): ``DEBUG`` /
    ``INFO``. Unrecognised values fall through to QSettings.
    """
    env = os.environ.get(_ENV_VAR, "").upper()
    if env == "DEBUG":
        return logging.DEBUG
    if env == "INFO":
        return logging.INFO
    if read_debug_mode_from_qsettings():
        return logging.DEBUG
    return logging.INFO
