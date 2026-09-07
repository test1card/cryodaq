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
from typing import Final

from cryodaq.paths import get_logs_dir

_QSETTINGS_ORG = "FIAN"
_QSETTINGS_APP = "CryoDAQ"
_QSETTINGS_DEBUG_KEY = "logging/debug_mode"
_ENV_VAR = "CRYODAQ_LOG_LEVEL"

# --- Authoritative rotating-log retention/naming contract ----------------
#
# ``setup_logging`` below is the only producer of rotating component logs.
# Consumers that must recognise exactly what it can leave behind -- notably
# the long-soak evidence publisher in ``scripts/soak_mock_stack_runner.py``,
# which enumerates and reads the assistant log at teardown -- import THIS
# block instead of restating its values. A private copy of these numbers once
# drifted from the real handler: teardown then refused rotations the handler
# validly retained and replaced the diagnosis with a false rotation-ceiling
# marker (PR #102 cold review F1).
#
# ``tests/scripts/test_assistant_log_rotation_contract_binding.py``
# constructs the real production handler through ``setup_logging``'s own
# default path, forces a genuine rollover, and proves that binding holds;
# change anything here without its consumer and that guard turns red.
ASSISTANT_LOG_BASENAME: Final[str] = "assistant.log"
ASSISTANT_LOG_ROTATION_WHEN: Final[str] = "midnight"
ASSISTANT_LOG_SUFFIX_FORMAT: Final[str] = "%Y-%m-%d"
ASSISTANT_LOG_BACKUP_COUNT: Final[int] = 14

# The strftime directives a TimedRotatingFileHandler suffix carries for the
# rotation triggers this module configures ("midnight" -> "%Y-%m-%d").
_ROTATION_SUFFIX_DIRECTIVE_PATTERNS: Final[dict[str, str]] = {
    "%Y": r"\d{4}",
    "%m": r"\d{2}",
    "%d": r"\d{2}",
    "%H": r"\d{2}",
    "%M": r"\d{2}",
    "%S": r"\d{2}",
}


def _rotation_suffix_regex_source(format_string: str) -> str:
    """Translate a rotation suffix strftime format into a regex source.

    Unknown directives raise instead of degrading: a suffix carrying a token
    this translation does not know must fail loudly here rather than let
    downstream recognition silently disagree with what rotation writes.
    """
    pieces: list[str] = []
    index = 0
    while index < len(format_string):
        char = format_string[index]
        if char != "%":
            pieces.append(re.escape(char))
            index += 1
            continue
        directive = format_string[index : index + 2]
        pattern = _ROTATION_SUFFIX_DIRECTIVE_PATTERNS.get(directive)
        if pattern is None:
            raise ValueError(f"unsupported rotation suffix directive: {directive!r}")
        pieces.append(pattern)
        index += 2
    return "".join(pieces)


def rotated_log_name_pattern(basename: str) -> re.Pattern[str]:
    """Return the fullmatch pattern for names the production handler rotates to.

    :class:`~logging.handlers.TimedRotatingFileHandler` writes each rotation as
    ``<basename>.<suffix>``, where ``<suffix>`` is
    :data:`ASSISTANT_LOG_SUFFIX_FORMAT` rendered by ``time.strftime`` at
    rollover time. Recognition is derived from THE SAME format instead of
    restating a literal, so it cannot drift from what the handler produces.
    """
    return re.compile(re.escape(basename) + r"\." + _rotation_suffix_regex_source(ASSISTANT_LOG_SUFFIX_FORMAT))


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
# The digit run is BOUNDED. Reviewer measurement 2026-09-07: with an unbounded
# `\d{6,}` a near-miss like "bot" + 40000 digits + ":" + punctuation took 3.18 s
# to NOT match, growing exactly fourfold per doubling — quadratic, because every
# start position rescans the whole digit run before failing. Untrusted text does
# reach logging, and redaction runs on both handlers, so a single long line
# stalls the logging thread repeatedly. A Telegram bot ID is ten digits; 24 is
# already absurd headroom, and bounding it makes the scan linear.
#
# The SECRET stays unbounded on purpose: a bound there would match its first N
# characters and leave the tail of a longer secret in the log, which is the very
# leak this exists to stop. It costs nothing — nothing follows it to backtrack
# for, so the greedy match succeeds on the first attempt.
_TELEGRAM_TOKEN_RE = re.compile(r"(?:bot)?\d{6,24}:[A-Za-z0-9_-]{20,}")
_BARE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])\d{8,24}:[A-Za-z0-9_-]{30,}(?![A-Za-z0-9_-])")


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


class _TokenRedactFormatter(logging.Formatter):
    """Redact the FULLY FORMATTED record, tracebacks included.

    `_TokenRedactFilter` rewrites `record.msg` and `record.args`, which is
    where a token lands when someone logs it directly. It cannot reach a
    TRACEBACK: `exc_text` is rendered by the formatter, after every filter has
    already run, so an exception carrying the URL sails straight past it.

    That is not hypothetical. aiohttp puts the full request URL into
    `ConnectionTimeoutError`, and Telegram requires the token IN THE URL PATH
    because it offers no header auth — so every network hiccup while polling
    `getUpdates` wrote the live bot token into the log. Found 2026-09-07:
    fourteen occurrences in `logs/engine.log`, and the same text had already
    reached a pushed repository through a copied lane log.

    The filter's own docstring said it covered "any aiohttp URL-logging or
    traceback containing the request URL". The traceback half was the half it
    could not do. Redacting here, on the final string, covers message, args and
    traceback in one place and cannot be outflanked by a new logging path.
    """

    def format(self, record: logging.LogRecord) -> str:
        return _redact(super().format(record))


def install_token_redaction(
    handler: logging.Handler,
    *,
    fmt: str,
    datefmt: str | None = None,
) -> None:
    """Make one handler unable to write a Telegram token. Use for EVERY handler.

    `setup_logging` hardens the root handlers, and that covers everything which
    propagates. It does not cover a component that builds its own logger with
    `propagate = False` — such a handler never sees a root filter or formatter,
    so the protection has to be asked for by name.

    Reviewer finding, 2026-09-07: the launcher's engine-stderr logger is exactly
    that shape, and a comment in the pump asserted the redaction filter was
    "already installed on these handlers" when it was installed only on the root
    ones. Reproduced: a child stderr line carrying a `getUpdates` URL wrote the
    token verbatim into `engine.stderr.log`. The claim in that comment, and in
    the commit that added the formatter, was that a new logging path could not
    outflank it. A new logging path had already outflanked it.

    Both are applied because they cover different halves: the filter reaches
    `record.msg` and `record.args`, the formatter reaches the final string and
    with it the traceback, which is rendered after every filter has run.
    """
    handler.setFormatter(_TokenRedactFormatter(fmt=fmt, datefmt=datefmt))
    handler.addFilter(_TokenRedactFilter())


def configure_cli_logging(
    *,
    level: int = logging.INFO,
    fmt: str = "%(levelname)s %(message)s",
    datefmt: str | None = None,
) -> logging.Handler:
    """Stand-alone tools' one way to set up logging. Returns the handler.

    `logging.basicConfig` builds a plain StreamHandler, and a tool that calls it
    prints whatever it is given — a token included. stderr from a tool is
    routinely captured by a service manager, a shell redirect or a bundle
    collector, so "it only goes to the terminal" is not a place the token is
    safe to be.

    Reviewer finding, 2026-09-07: after the engine-stderr handler was hardened,
    a sweep found two more unredacted handlers built outside `setup_logging` —
    `tools/replay_alarm_history.py` and `agents/rag/cli.py`. Hardening one
    instance and missing its siblings is exactly the failure that produced the
    first one, so this exists to be the only thing a tool has to call.
    """
    handler = logging.StreamHandler()
    install_token_redaction(handler, fmt=fmt, datefmt=datefmt)
    logging.basicConfig(level=level, handlers=[handler])
    return handler


def setup_logging(
    component: str,
    *,
    level: int = logging.INFO,
    console: bool = True,
    file: bool = True,
    when: str = ASSISTANT_LOG_ROTATION_WHEN,
    backup_count: int = ASSISTANT_LOG_BACKUP_COUNT,
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
        Passed to :class:`logging.handlers.TimedRotatingFileHandler`. Defaults
        come from the authoritative rotating-log contract at the top of this
        module (:data:`ASSISTANT_LOG_ROTATION_WHEN`,
        :data:`ASSISTANT_LOG_BACKUP_COUNT`) — rotate at midnight, keep 14 old
        files. Do not hardcode alternatives here without moving them into that
        contract; its consumers bind against it and against the real handler
        this function builds.

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

    fmt = "%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    if console:
        stream_handler = logging.StreamHandler(sys.stderr)
        install_token_redaction(stream_handler, fmt=fmt, datefmt=datefmt)
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
            install_token_redaction(file_handler, fmt=fmt, datefmt=datefmt)
            root.addHandler(file_handler)
        except Exception as exc:
            sys.stderr.write(f"WARNING: failed to set up file logging for {component}: {exc}\n")


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
