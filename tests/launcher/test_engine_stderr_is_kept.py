"""The engine's own words must survive the pump, because the log has to say WHY it fell.

WHY THIS MODULE EXISTS. `_pump_engine_stderr` read each line and logged a FIXED string,
throwing the line away. Measured on the laboratory machine: one soak run produced 104
records in `log-engine-stderr.txt`, every one of them the identical placeholder, with
`log_capture.json` showing an empty allowlist. At the one moment the engine explains
itself, nothing it said was kept.

Owner, 2026-08-20, on whether to keep it and whether to redact:

    "конечно сохранять, ничего не чистить. секреты хранятся на том компе, их нужно
    чистить только если происходит вынос с компа, а не внутри работы программы"

So redaction belongs to EXPORT off the machine, not to running on it, and the PUMP scrubs
nothing.

BE EXACT ABOUT WHOSE CLAIM THAT IS. The pump is one end of the path. At the other end the
engine writes through `setup_logging()`, whose `_TokenRedactFilter` replaces a Telegram
bot token before the bytes ever leave the engine, because Telegram carries that token in
the URL and any logged URL would otherwise put a live credential into a file that leaves
this machine in a support bundle. That one narrow replacement is the export boundary
doing its job, not an operational scrub, and it stays. A test here that claimed "nothing
is scrubbed" of the whole path would be false; the tests below say which end they speak
for and prove each end separately.

What these tests also enforce is that the bound and the failure tolerance that were
already there survive the change: an over-long line must not be decoded and forwarded
whole, and one undecodable byte must not kill the pump and lose every line after it.
"""

from __future__ import annotations

import inspect
import io
import logging
import os
import subprocess
import sys

from cryodaq import launcher, logging_setup


def _pump(text: bytes, tmp_path, monkeypatch) -> list[str]:
    """Run the real pump over `text` and return the messages it logged."""

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr("cryodaq.paths.get_logs_dir", lambda: log_dir)
    stderr_logger, handler, _path = launcher._create_engine_stderr_logger()

    recorded: list[str] = []

    class _Capture:
        level = 0

        def handle(self, record):
            recorded.append(record.getMessage())

        def close(self):
            return None

    capture = _Capture()
    stderr_logger.addHandler(capture)  # type: ignore[arg-type]
    try:
        launcher._pump_engine_stderr(launcher._EngineStderrStreamOwner(io.BytesIO(text)), stderr_logger)
    finally:
        stderr_logger.removeHandler(capture)  # type: ignore[arg-type]
        stderr_logger.removeHandler(handler)
        handler.close()
    return recorded


def test_the_line_the_engine_wrote_is_what_is_logged(tmp_path, monkeypatch) -> None:
    """The defect itself: the content used to be replaced by a constant."""

    said = b"Traceback (most recent call last):\nValueError: the sensor roster is empty\n"
    messages = _pump(said, tmp_path, monkeypatch)

    assert any("ValueError: the sensor roster is empty" in m for m in messages), (
        f"the engine's own words must reach the log; got {messages}"
    )
    assert any("Traceback (most recent call last):" in m for m in messages)
    assert not any(m.endswith("engine child stderr record received; phase=runtime") for m in messages), (
        "the fixed placeholder must be gone, or the log still says nothing"
    )


# A token in the exact shape production recognises. Written from the pattern in
# logging_setup so the test cannot pass by using a shape nothing would have matched.
_REAL_TOKEN_SHAPE = "bot7701234567:AAEhBPqZzXyWvUtSrQpOnMlKjIhGfEdCbA9"


def test_the_pump_adds_and_removes_nothing_even_for_a_real_token_shape(tmp_path, monkeypatch) -> None:
    """The pump is a conduit. It must not become a second, hidden policy point.

    The payload is the shape the production filter DOES match, so this cannot pass by
    smuggling through something nothing would have touched. What it proves is only about
    the pump: a line handed to it arrives byte for byte.
    """

    assert logging_setup._redact(_REAL_TOKEN_SHAPE) != _REAL_TOKEN_SHAPE, (
        "the sample must be a shape production actually recognises, or this test is vacuous"
    )

    said = f"connect failed: url=https://api.telegram.org/{_REAL_TOKEN_SHAPE}/getMe\n".encode()
    messages = _pump(said, tmp_path, monkeypatch)
    assert any(_REAL_TOKEN_SHAPE in m for m in messages), f"the pump must forward the line unchanged; got {messages}"


def test_the_engine_end_still_replaces_a_telegram_token_before_it_is_written() -> None:
    """The other end, stated truthfully rather than overclaimed.

    Telegram has no header authentication, so the token rides in the URL and any logged
    URL would carry a live credential into a file that leaves this machine. That single
    replacement happens in the engine's own logging setup, before the pump ever sees the
    line, and it is the export boundary rather than an operational scrub.
    """

    record = logging.LogRecord(
        name="cryodaq.test.engine",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="telegram call failed for %s",
        args=(f"https://api.telegram.org/{_REAL_TOKEN_SHAPE}/getMe",),
        exc_info=None,
    )
    assert logging_setup._TokenRedactFilter().filter(record) is True
    assert _REAL_TOKEN_SHAPE not in record.getMessage()
    assert "bot***" in record.getMessage()


def test_a_russian_diagnostic_survives_the_real_subprocess_boundary(tmp_path, monkeypatch) -> None:
    """Cross the boundary for real, because that is where the encoding was decided.

    The pump decodes UTF-8. Nothing made the child ENCODE in UTF-8, so on a machine whose
    stream encoding is, say, CP1251 the engine's Russian explanation reached the log as
    replacement characters. `_start_engine` now fixes PYTHONIOENCODING for the child; this
    drives a real subprocess with a deliberately hostile inherited value to prove the fix
    is what decides the outcome, not the host's default.
    """

    said = "Движок остановлен: датчик Т7 Детектор не отвечает"
    program = f"import sys; sys.stderr.write({said!r} + chr(10)); sys.stderr.flush()"

    hostile = dict(os.environ)
    hostile["PYTHONIOENCODING"] = "cp1251"
    child = subprocess.run([sys.executable, "-c", program], capture_output=True, env=hostile)
    assert said not in child.stderr.decode("utf-8", "replace"), (
        "the hostile control must actually mangle the text, or this test proves nothing"
    )

    # The environment under test is PRODUCTION's, built by the same function the spawn
    # calls. Rebuilding a lookalike here would test the test.
    fixed = launcher._engine_child_environment(hostile)
    child = subprocess.run([sys.executable, "-c", program], capture_output=True, env=fixed)
    messages = _pump(child.stderr, tmp_path, monkeypatch)
    assert any(said in m for m in messages), f"the Russian diagnostic must arrive intact; got {messages}"


def test_the_spawn_uses_that_same_environment_builder() -> None:
    """A helper nothing calls would fix nothing."""

    source = inspect.getsource(launcher.LauncherWindow._start_engine)
    assert "_engine_child_environment(os.environ)" in source, (
        "the engine spawn must build its child environment through the helper under test"
    )


def test_an_undecodable_byte_does_not_kill_the_pump(tmp_path, monkeypatch) -> None:
    """One bad byte must not lose every line after it.

    The decode replaces rather than raises for this reason, and the line that follows is
    what proves the pump survived.
    """

    said = b"first \xff\xfe line\nsecond line survives\n"
    messages = _pump(said, tmp_path, monkeypatch)
    assert any("second line survives" in m for m in messages), (
        f"the pump must continue past an undecodable byte; got {messages}"
    )


def test_an_over_long_line_is_reported_and_not_forwarded_whole(tmp_path, monkeypatch) -> None:
    """The forwarding bound that was already there must survive the change.

    Keeping the content must not become keeping an unbounded amount of it.
    """

    marker = b"X" * (launcher._MAX_ENGINE_STDERR_LINE_BYTES + 64)
    said = marker + b"\nshort line after\n"
    messages = _pump(said, tmp_path, monkeypatch)

    assert any("exceeded the forwarding bound" in m for m in messages), (
        f"the over-long line must be reported as such; got {messages[:3]}"
    )
    assert not any(len(m) > launcher._MAX_ENGINE_STDERR_LINE_BYTES + 200 for m in messages), (
        "no single record may carry more than the bound plus its own prefix"
    )
    assert any("short line after" in m for m in messages), "and the pump must carry on to the next line"
