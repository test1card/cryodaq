"""The engine's own words must survive the pump, because the log has to say WHY it fell.

WHY THIS MODULE EXISTS. `_pump_engine_stderr` read each line and logged a FIXED string,
throwing the line away. Measured on the laboratory machine: one soak run produced 104
records in `log-engine-stderr.txt`, every one of them the identical placeholder, with
`log_capture.json` showing an empty allowlist. At the one moment the engine explains
itself, nothing it said was kept.

Owner, 2026-08-20, on whether to keep it and whether to redact:

    "конечно сохранять, ничего не чистить. секреты хранятся на том компе, их нужно
    чистить только если происходит вынос с компа, а не внутри работы программы"

So redaction belongs to EXPORT off the machine, not to running on it, and nothing here
scrubs anything. What these tests do enforce is that the bound and the failure tolerance
that were already there survive the change: an over-long line must not be decoded and
forwarded whole, and one undecodable byte must not kill the pump and lose every line
after it.
"""

from __future__ import annotations

import io

from cryodaq import launcher


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


def test_nothing_is_scrubbed_on_the_way_through(tmp_path, monkeypatch) -> None:
    """Redaction is for export off the machine, not for running on it.

    A line that merely LOOKS sensitive must arrive intact; the secrets live on this
    computer already and hiding them from its own log only hides the fault.
    """

    said = b"connect failed: token=abcdef123456 host=10.0.0.4\n"
    messages = _pump(said, tmp_path, monkeypatch)
    assert any("token=abcdef123456" in m for m in messages), (
        f"nothing may be scrubbed inside the program's own run; got {messages}"
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
