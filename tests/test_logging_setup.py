"""Verify logging_setup creates rotating files and redacts Telegram tokens."""

from __future__ import annotations

import importlib
import io
import logging
import sys

import pytest


@pytest.fixture(autouse=True)
def restore_root_logging():
    """Leave root logging exactly as each test found it.

    ``setup_logging()`` replaces every root handler, and several tests here
    also reload this module (resetting its globals). Without restoration a
    live handler -- and a claimed "configured" state -- leaked into every
    later file in the session: when the GUI suite ran after this one, the
    leaked handler answered "an emission reached a handler" for records that
    reached nowhere durable, and six theme-deferral guards failed that pass
    on their own.
    """

    from cryodaq import logging_setup

    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    configured = logging_setup._logging_configured
    deferred = list(logging_setup._deferred_records)
    replay_pending = getattr(logging_setup, "_replay_pending", None)
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            try:
                handler.close()
            except Exception:
                pass
            root.removeHandler(handler)
    for handler in handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
    root.setLevel(level)
    logging_setup._logging_configured = configured
    logging_setup._deferred_records[:] = deferred
    if replay_pending is not None:
        logging_setup._replay_pending = replay_pending


def test_setup_logging_creates_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))
    # `logs/` hangs off the *state* root, which CRYODAQ_STATE_ROOT relocates
    # independently of CRYODAQ_ROOT. The sealed-candidate runner sets it for
    # every execution, so without this the handler wrote under the candidate's
    # runtime root and this assertion failed on both operating systems in CI
    # while passing in every checkout run. Same idiom as test_paths_frozen.py.
    monkeypatch.delenv("CRYODAQ_STATE_ROOT", raising=False)

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

    logger.info("Posting to https://api.telegram.org/bot7701234567:AAEhBP0av8XyZabc-defGHIJ/sendMessage")
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


def test_setup_logging_keeps_deferred_records_until_a_handler_exists(tmp_path, monkeypatch):
    """A handlerless setup must not discard diagnostics that need a later log."""

    from cryodaq import logging_setup

    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    configured = logging_setup._logging_configured
    deferred = list(logging_setup._deferred_records)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    try:
        logging_setup._logging_configured = False
        logging_setup._deferred_records.clear()
        logging_setup.defer_record(logging.ERROR, "deferred startup failure")

        logging_setup.setup_logging("without-handlers", console=False, file=False)
        assert logging_setup._deferred_records

        def fail_to_create_log_dir():
            raise OSError("log directory unavailable")

        monkeypatch.setattr(logging_setup, "get_logs_dir", fail_to_create_log_dir)
        logging_setup.setup_logging("failed-file-handler", console=False, file=True)
        assert logging_setup._deferred_records

        monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: log_dir)
        logging_setup.setup_logging("durable-handler", console=False, file=True)
        logging.shutdown()

        written = (log_dir / "durable-handler.log").read_text(encoding="utf-8")
        assert "deferred startup failure" in written
        assert not logging_setup._deferred_records
    finally:
        for handler in list(root.handlers):
            if handler not in handlers:
                handler.close()
                root.removeHandler(handler)
        for handler in handlers:
            if handler not in root.handlers:
                root.addHandler(handler)
        root.setLevel(level)
        logging_setup._logging_configured = configured
        logging_setup._deferred_records[:] = deferred


def test_setup_logging_tolerates_file_failure_without_stderr(monkeypatch):
    """A windowed launcher must survive when neither logging sink can start."""

    from cryodaq import logging_setup

    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    configured = logging_setup._logging_configured
    deferred = list(logging_setup._deferred_records)

    def unavailable_log_dir():
        raise OSError("unavailable")

    try:
        logging_setup._logging_configured = False
        logging_setup._deferred_records.clear()
        logging_setup.defer_record(logging.ERROR, "startup diagnostic")
        monkeypatch.setattr(sys, "stderr", None)
        monkeypatch.setattr(logging_setup, "get_logs_dir", unavailable_log_dir)

        logging_setup.setup_logging("launcher", console=True, file=True)

        assert logging_setup._deferred_records == [(logging.ERROR, "startup diagnostic", ())]
        assert not logging_setup.logging_is_configured()
    finally:
        for handler in list(root.handlers):
            if handler not in handlers:
                handler.close()
                root.removeHandler(handler)
        for handler in handlers:
            if handler not in root.handlers:
                root.addHandler(handler)
        root.setLevel(level)
        logging_setup._logging_configured = configured
        logging_setup._deferred_records[:] = deferred


def test_setup_logging_retains_deferred_records_after_file_write_failure(tmp_path, monkeypatch):
    """A file handler that cannot write must not consume startup diagnostics."""

    from cryodaq import logging_setup

    class FailingStream:
        closed = False

        def write(self, _message):
            raise OSError("disk full")

        def flush(self):
            pass

        def close(self):
            self.closed = True

    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    configured = logging_setup._logging_configured
    deferred = list(logging_setup._deferred_records)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    try:
        logging_setup._logging_configured = False
        logging_setup._deferred_records.clear()
        logging_setup.defer_record(logging.ERROR, "startup diagnostic")
        monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: log_dir)
        monkeypatch.setattr(logging.FileHandler, "_open", lambda _handler: FailingStream())

        logging_setup.setup_logging("launcher", console=False, file=True)

        assert logging_setup._deferred_records == [(logging.ERROR, "startup diagnostic", ())]
        assert logging_setup.logging_is_configured()
    finally:
        for handler in list(root.handlers):
            if handler not in handlers:
                handler.close()
                root.removeHandler(handler)
        for handler in handlers:
            if handler not in root.handlers:
                root.addHandler(handler)
        root.setLevel(level)
        logging_setup._logging_configured = configured
        logging_setup._deferred_records[:] = deferred


def test_a_doubly_broken_console_does_not_stop_the_file_sink_or_startup(tmp_path, monkeypatch):
    """emit() fails AND the standard error report fails on the same broken stderr.

    StreamHandler re-raises RecursionError straight out of emit() (bpo-36272),
    and Handler.handleError re-raises it too when the report cannot be written
    to stderr. Neither may escape: the record must still reach the file sink
    behind the console, and the caller must carry on as if nothing happened.
    """

    from cryodaq import logging_setup

    class BrokenEverywhere:
        closed = False

        def write(self, _message):
            raise RecursionError("even the error report cannot be written")

        def flush(self):
            pass

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(sys, "stderr", BrokenEverywhere())
    monkeypatch.setattr(logging, "raiseExceptions", True)
    monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: log_dir)

    logging_setup.setup_logging("doubly-broken", console=True, file=True)
    logging.getLogger("probe.doubly_broken").error("must reach the file sink")

    for handler in list(logging.getLogger().handlers):
        handler.flush()

    written = (log_dir / "doubly-broken.log").read_text(encoding="utf-8")
    assert "must reach the file sink" in written


def test_a_retained_record_replays_when_the_broken_sink_recovers(tmp_path, monkeypatch):
    """Retention is not a parking lot: the first successful emission from a
    previously failing sink proves recovery and replays the backlog, without
    another setup_logging() call. While the sink stays broken, ordinary
    emissions must not re-attempt the backlog.
    """

    from cryodaq import logging_setup

    class FailingStream:
        closed = False

        def write(self, _message):
            raise OSError("disk full")

        def flush(self):
            pass

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: log_dir)

    logging_setup._logging_configured = False
    logging_setup._deferred_records.clear()
    logging_setup.defer_record(logging.ERROR, "held diagnostic")
    monkeypatch.setattr(logging.FileHandler, "_open", lambda _handler: FailingStream())
    logging_setup.setup_logging("recovering", console=False, file=True)

    assert logging_setup._deferred_records == [(logging.ERROR, "held diagnostic", ())]

    [file_handler] = logging.getLogger().handlers
    emissions: list[str] = []
    real_emit = file_handler.emit

    def counting_emit(record):
        emissions.append(record.getMessage())
        real_emit(record)

    monkeypatch.setattr(file_handler, "emit", counting_emit)

    for index in range(3):
        logging.getLogger("probe.recovery").error("while broken %d", index)

    assert emissions == ["while broken 0", "while broken 1", "while broken 2"], (
        "a permanently broken sink must not be handed the backlog back"
    )

    monkeypatch.setattr(file_handler, "stream", io.StringIO())
    logging.getLogger("probe.recovery").info("recovery proven")

    assert not logging_setup._deferred_records
    assert "held diagnostic" in emissions
    assert emissions.count("held diagnostic") == 1
    written = file_handler.stream.getvalue()
    assert "recovery proven" in written and "held diagnostic" in written


def test_a_partially_successful_replay_does_not_strand_the_retained_prefix(tmp_path, monkeypatch):
    """An early record can fail while a later one succeeds inside the SAME replay.

    The later success used to reset every handler's recovery transition before the earlier
    failure was restored, so the retained prefix had no trigger left and sat in the queue
    until the next setup_logging() call. Retention must arm an explicit pending condition
    instead, and the very next successful emission must deliver what was owed.
    """

    from cryodaq import logging_setup

    class FlakyOnceStream:
        closed = False

        def __init__(self) -> None:
            self.failures_left = 1
            self.written = io.StringIO()

        def write(self, message):
            if self.failures_left > 0:
                self.failures_left -= 1
                raise OSError("disk full")
            self.written.write(message)
            return len(message)

        def flush(self):
            pass

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: log_dir)

    stream = FlakyOnceStream()
    monkeypatch.setattr(logging.FileHandler, "_open", lambda _handler: stream)

    logging_setup._logging_configured = False
    logging_setup._deferred_records.clear()
    logging_setup.defer_record(logging.ERROR, "early diagnostic %d", 1)
    logging_setup.defer_record(logging.ERROR, "later diagnostic")

    # setup_logging replays immediately: "early" fails on the broken sink, "later"
    # succeeds once that failure has consumed the stream's only fault.
    logging_setup.setup_logging("partial-replay", console=False, file=True)

    assert logging_setup._deferred_records == [(logging.ERROR, "early diagnostic %d", (1,))]
    assert "later diagnostic" in stream.written.getvalue()
    assert "early diagnostic" not in stream.written.getvalue()

    logging.getLogger("probe.partial").error("post-recovery emission")

    assert not logging_setup._deferred_records, "a retained record must not be stranded"
    written = stream.written.getvalue()
    assert written.count("early diagnostic 1") == 1
    assert written.count("later diagnostic") == 1
    assert written.count("post-recovery emission") == 1


def test_arrivals_during_a_failing_replay_merge_under_the_hard_cap(tmp_path, monkeypatch):
    """Records deferred while a replay is running must not lift the bound.

    The replay hands the queue over, runs, then re-merges whatever every sink rejected.
    Defers landing inside that window used to be prepended back without any cap, so
    repeated recovery cycles ratcheted the list past _MAX_DEFERRED_RECORDS. The merge
    keeps retention first (oldest, proven undelivered so far), then arrival order, and
    drops the newest overflow -- asserted here as an exact expected survivor list.
    """

    from cryodaq import logging_setup

    class FailingThenWorkingStream:
        closed = False

        def __init__(self, failures_left: int) -> None:
            self.failures_left = failures_left
            self.written = io.StringIO()

        def write(self, message):
            if self.failures_left > 0:
                self.failures_left -= 1
                raise OSError("disk full")
            self.written.write(message)
            return len(message)

        def flush(self):
            pass

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: log_dir)

    logging_setup.setup_logging("cap-merge", console=False, file=True)
    [file_handler] = logging.getLogger().handlers

    # The first 60 replayed records fail; the last 4 succeed. While record "held 61" is
    # being emitted -- squarely inside the snapshot/merge window -- eight new records
    # are deferred, reproducing the concurrent-defer interleaving deterministically.
    monkeypatch.setattr(file_handler, "stream", FailingThenWorkingStream(failures_left=60))
    real_emit = file_handler.emit

    def injecting_emit(record):
        if record.getMessage() == "held 61":
            for index in range(8):
                logging_setup.defer_record(logging.ERROR, f"arrival {index}")
        real_emit(record)

    monkeypatch.setattr(file_handler, "emit", injecting_emit)

    for index in range(logging_setup._MAX_DEFERRED_RECORDS):
        logging_setup.defer_record(logging.ERROR, f"held {index}")
    logging_setup._replay_deferred_records()

    survivors = [(logging.ERROR, f"held {index}", ()) for index in range(60)] + [
        (logging.ERROR, f"arrival {index}", ()) for index in range(4)
    ]
    assert len(logging_setup._deferred_records) == logging_setup._MAX_DEFERRED_RECORDS
    assert logging_setup._deferred_records == survivors


def test_a_thread_deferring_inside_an_active_replay_cannot_lift_the_cap(tmp_path, monkeypatch):
    """The same hard bound, proven against a genuinely concurrent defer_record caller.

    The replay's window is pinned with Events: the first replayed emission holds the
    window open while another thread lands five records, so the merge always observes
    them -- no sleeps, no timing assumptions.
    """

    import threading

    from cryodaq import logging_setup

    class AlwaysFailingStream:
        closed = False

        def write(self, _message):
            raise OSError("disk full")

        def flush(self):
            pass

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: log_dir)

    logging_setup.setup_logging("thread-cap", console=False, file=True)
    [file_handler] = logging.getLogger().handlers
    monkeypatch.setattr(file_handler, "stream", AlwaysFailingStream())

    window_open = threading.Event()
    arrivals_done = threading.Event()
    real_emit = file_handler.emit

    def window_emit(record):
        if not window_open.is_set():
            window_open.set()
            assert arrivals_done.wait(timeout=30)
        real_emit(record)

    monkeypatch.setattr(file_handler, "emit", window_emit)

    def arrive():
        assert window_open.wait(timeout=30)
        for index in range(5):
            logging_setup.defer_record(logging.ERROR, f"thread arrival {index}")
        arrivals_done.set()

    for index in range(logging_setup._MAX_DEFERRED_RECORDS):
        logging_setup.defer_record(logging.ERROR, f"held {index}")

    worker = threading.Thread(target=arrive)
    worker.start()
    try:
        logging_setup._replay_deferred_records()
    finally:
        worker.join(timeout=30)

    assert len(logging_setup._deferred_records) == logging_setup._MAX_DEFERRED_RECORDS
    assert all(record[1].startswith("held ") for record in logging_setup._deferred_records)


def test_replay_delivery_uses_the_target_records_probe():
    """A foreign success must not erase a replay target rejected by every sink."""

    import threading

    from cryodaq import logging_setup

    target = "replay target"
    second_handler_entered = threading.Event()
    foreign_reached_first_handler = threading.Event()

    class FirstStream:
        closed = False

        def write(self, message):
            if target in message:
                raise OSError("first sink rejected target")
            foreign_reached_first_handler.set()
            return len(message)

        def flush(self):
            pass

    class SecondStream:
        closed = False

        def write(self, message):
            if target in message:
                second_handler_entered.set()
                assert foreign_reached_first_handler.wait(timeout=30)
            raise OSError("second sink rejected record")

        def flush(self):
            pass

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(logging.INFO)
    root.addHandler(logging_setup._EmissionTrackingStreamHandler(FirstStream()))
    root.addHandler(logging_setup._EmissionTrackingStreamHandler(SecondStream()))
    logging_setup._deferred_records.clear()
    logging_setup._replay_pending = False
    logging_setup.defer_record(logging.ERROR, target)

    def emit_foreign_record():
        assert second_handler_entered.wait(timeout=30)
        logging.getLogger("probe.foreign").error("foreign record")

    foreign = threading.Thread(target=emit_foreign_record)
    foreign.start()
    logging_setup._replay_deferred_records()
    foreign.join(timeout=30)

    assert not foreign.is_alive()
    assert logging_setup._deferred_records == [(logging.ERROR, target, ())]


def test_record_deferred_during_replay_keeps_the_replay_trigger_armed(tmp_path, monkeypatch):
    """A new arrival during replay must be delivered by the next proven success."""

    from cryodaq import logging_setup

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: log_dir)
    logging_setup.setup_logging("defer-during-replay", console=False, file=True)
    [file_handler] = logging.getLogger().handlers
    stream = io.StringIO()
    monkeypatch.setattr(file_handler, "stream", stream)
    real_emit = file_handler.emit

    def inject_arrival(record):
        if record.getMessage() == "first held record":
            logging_setup.defer_record(logging.ERROR, "arrived during replay")
        real_emit(record)

    monkeypatch.setattr(file_handler, "emit", inject_arrival)
    logging_setup._deferred_records.clear()
    logging_setup._replay_pending = False
    logging_setup.defer_record(logging.ERROR, "first held record")

    logging_setup._replay_deferred_records()

    assert logging_setup._deferred_records == [(logging.ERROR, "arrived during replay", ())]
    assert logging_setup._replay_pending

    logging.getLogger("probe.pending").info("proven success")

    assert not logging_setup._deferred_records
    assert stream.getvalue().count("arrived during replay") == 1


def test_replay_owner_lock_makes_contended_entry_nonblocking():
    """A second replay caller must return without consuming the shared queue."""

    import threading

    from cryodaq import logging_setup

    logging_setup._deferred_records.clear()
    logging_setup.defer_record(logging.ERROR, "held behind replay owner")
    assert logging_setup._replay_owner_lock.acquire(blocking=False)
    worker = threading.Thread(target=logging_setup._replay_deferred_records)
    try:
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert logging_setup._deferred_records == [(logging.ERROR, "held behind replay owner", ())]
    finally:
        logging_setup._replay_owner_lock.release()


def test_bare_token_without_bot_prefix_redacted():
    """P1: bare token (no 'bot' URL prefix) must also be redacted.

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


# ----------------------------------------------------------------------
# IV.4 F2 — resolve_log_level / debug mode toggle
# ----------------------------------------------------------------------


def test_resolve_log_level_env_var_debug(monkeypatch):
    """CRYODAQ_LOG_LEVEL=DEBUG overrides everything, even if QSettings
    says otherwise (QSettings unavailable in this test anyway)."""
    from cryodaq import logging_setup

    monkeypatch.setenv("CRYODAQ_LOG_LEVEL", "DEBUG")
    assert logging_setup.resolve_log_level() == logging.DEBUG


def test_resolve_log_level_env_var_info_overrides_qsettings(monkeypatch):
    """CRYODAQ_LOG_LEVEL=INFO forces INFO even if QSettings says debug."""
    from cryodaq import logging_setup

    monkeypatch.setenv("CRYODAQ_LOG_LEVEL", "INFO")
    monkeypatch.setattr(logging_setup, "read_debug_mode_from_qsettings", lambda: True)
    assert logging_setup.resolve_log_level() == logging.INFO


def test_resolve_log_level_qsettings_fallback_debug(monkeypatch):
    """No env var → QSettings True → DEBUG."""
    from cryodaq import logging_setup

    monkeypatch.delenv("CRYODAQ_LOG_LEVEL", raising=False)
    monkeypatch.setattr(logging_setup, "read_debug_mode_from_qsettings", lambda: True)
    assert logging_setup.resolve_log_level() == logging.DEBUG


def test_resolve_log_level_defaults_to_info(monkeypatch):
    """No env var, QSettings False → INFO."""
    from cryodaq import logging_setup

    monkeypatch.delenv("CRYODAQ_LOG_LEVEL", raising=False)
    monkeypatch.setattr(logging_setup, "read_debug_mode_from_qsettings", lambda: False)
    assert logging_setup.resolve_log_level() == logging.INFO


def test_resolve_log_level_unknown_env_var_falls_through(monkeypatch):
    """Garbage env value must not promote to DEBUG; falls to QSettings."""
    from cryodaq import logging_setup

    monkeypatch.setenv("CRYODAQ_LOG_LEVEL", "VERBOSE_BUT_WRONG")
    monkeypatch.setattr(logging_setup, "read_debug_mode_from_qsettings", lambda: False)
    assert logging_setup.resolve_log_level() == logging.INFO


def test_read_debug_mode_without_pyside_returns_false(monkeypatch):
    """CLI-only engine invocation without PySide6 returns False cleanly.

    We block the real PySide6.QtCore import so that the try/except ImportError
    branch inside read_debug_mode_from_qsettings() actually executes, rather
    than just patching the function under test (which proved nothing).
    """
    import importlib
    import sys

    # Force reload of logging_setup with PySide6.QtCore blocked so that
    # the ImportError branch inside read_debug_mode_from_qsettings is live.
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", None)  # None → ImportError on import
    # Also block the parent so nested imports don't bypass it.
    monkeypatch.setitem(sys.modules, "PySide6", None)

    # Reload logging_setup so it picks up the blocked module state.
    import cryodaq.logging_setup as ls_module

    importlib.reload(ls_module)

    result = ls_module.read_debug_mode_from_qsettings()
    assert result is False, "read_debug_mode_from_qsettings() must return False when PySide6 is not importable"
