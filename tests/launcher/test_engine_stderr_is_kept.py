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

import contextlib
import io
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

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


# A child that logs the way the engine logs: through the production setup_logging, whose
# handler is bound to ITS stderr, which is the stream the launcher's pump reads.
_ENGINE_LIKE_CHILD = """
import logging
from cryodaq.logging_setup import setup_logging
setup_logging("stderr-contract-probe", console=True, file=False)
logging.getLogger("cryodaq.probe").error("telegram call failed for %s", {url!r})
logging.getLogger("cryodaq.probe").error({said!r})
logging.shutdown()
"""


def _run_engine_like_child(program: str, env: dict[str, str]) -> bytes:
    child = subprocess.run([sys.executable, "-c", program], capture_output=True, env=env)
    assert child.returncode == 0, child.stderr.decode("utf-8", "replace")
    return child.stderr


def test_the_engine_end_replaces_a_token_through_its_real_logging_setup(tmp_path, monkeypatch) -> None:
    """Run production's setup_logging, in a child, and read what actually reached stderr.

    Constructing a _TokenRedactFilter by hand would prove only that the class works. What
    has to hold is that PRODUCTION attaches it to the stream the pump reads: if
    setup_logging ever stops adding it to the console handler, or adds it only to the file
    handler, a live credential reaches a file that leaves this machine, and a hand-built
    filter would go on passing.

    Telegram has no header authentication, so the token rides in the URL. That single
    replacement is the export boundary doing its job, not an operational scrub, which is
    why it stays while the pump itself keeps everything.
    """

    said = "Движок остановлен: датчик Т7 Детектор не отвечает"
    program = _ENGINE_LIKE_CHILD.format(
        url=f"https://api.telegram.org/{_REAL_TOKEN_SHAPE}/getMe",
        said=said,
    )
    env = launcher._engine_child_environment(os.environ)
    messages = _pump(_run_engine_like_child(program, env), tmp_path, monkeypatch)

    joined = "\n".join(messages)
    assert _REAL_TOKEN_SHAPE not in joined, "the engine's own logging setup must replace the token"
    assert "bot***" in joined, f"and it must replace it with the documented marker; got {messages}"
    assert said in joined, "everything that is not that one credential shape must survive intact"


def test_the_engine_end_replaces_a_token_in_formatted_exception_text(tmp_path, monkeypatch) -> None:
    """The formatter must redact credentials appended from ``exc_info``."""

    program = f"""\
import logging
from cryodaq.logging_setup import setup_logging
setup_logging("stderr-contract-exception-probe", console=True, file=False)
try:
    raise RuntimeError("https://api.telegram.org/{_REAL_TOKEN_SHAPE}/getMe")
except RuntimeError:
    logging.getLogger("cryodaq.probe").exception("telegram call failed")
logging.shutdown()
"""
    env = launcher._engine_child_environment(os.environ)
    messages = _pump(_run_engine_like_child(program, env), tmp_path, monkeypatch)

    joined = "\n".join(messages)
    assert _REAL_TOKEN_SHAPE not in joined, "formatted exception text must not retain the token"
    assert "bot***" in joined, f"the formatted exception must use the redaction marker; got {messages}"


def test_a_bounded_final_stderr_fragment_is_forwarded_at_eof(tmp_path, monkeypatch) -> None:
    """An abrupt child exit must not discard its final bounded diagnostic."""

    said = b"native dependency failed before it could flush a newline"
    messages = _pump(said, tmp_path, monkeypatch)

    assert any(said.decode() in message for message in messages), messages
    assert not any("exceeded the forwarding bound" in message for message in messages), messages


def test_record_framing_preserves_whitespace_repeated_cr_and_eof_cr() -> None:
    """Only the one wire delimiter may be removed from each captured payload."""

    captured: list[str] = []

    class _CapturePayload:
        def error(self, message: str, *args: object) -> None:
            if message == "engine child stderr; phase=runtime: %s":
                assert len(args) == 1
                assert isinstance(args[0], str)
                captured.append(args[0])

    wire = b" \t\n\n\r\r\n\r\r\r\nterminal\r"
    launcher._pump_engine_stderr(io.BytesIO(wire), _CapturePayload())  # type: ignore[arg-type]

    assert captured == [" \t", "", "\r", "\r\r", "terminal\r"]


def test_the_spawn_hands_the_operating_system_the_environment_under_test(monkeypatch) -> None:
    """Prove _start_engine PASSES that environment, not merely that it builds one.

    A helper that production calls and then overwrites, or hands to something other than
    the spawn, would leave the original failure able to recur while every test stayed
    green. So this intercepts the real Popen call inside the real _start_engine and reads
    the env that was actually on its way to the operating system.
    """

    captured: dict[str, dict[str, str]] = {}

    class _Stop(RuntimeError):
        pass

    def _capture(*_args, **kwargs):
        captured["env"] = dict(kwargs.get("env") or {})
        raise _Stop("spawn intercepted after the environment was fixed")

    monkeypatch.setattr(launcher.subprocess, "Popen", _capture)

    # The two extras are simply what _start_engine touches on the way to the spawn; they
    # were found by letting it say so, not chosen. Raising from inside Popen lets the
    # method's own descriptor cleanup run on the way out.
    window = SimpleNamespace(
        _engine_proc=None,
        _engine_external=False,
        _replay_source=None,
        _engine_unsettled_incarnation=None,
        _check_predictor_bootstrap_hint=MagicMock(),
        _mock=True,
    )
    with contextlib.suppress(BaseException):
        launcher.LauncherWindow._start_engine(window)

    assert "env" in captured, "the spawn was never reached; this test would prove nothing"
    assert captured["env"].get("PYTHONIOENCODING") == "utf-8", (
        f"the environment on its way to the operating system must fix the encoding; "
        f"got {captured['env'].get('PYTHONIOENCODING')!r}"
    )
    assert captured["env"].get("PYTHONUNBUFFERED") == "1"


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
