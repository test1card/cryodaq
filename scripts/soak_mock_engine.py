"""Bounded mock-engine soak driver (roadmap B-phase-exit: "72h mock soak
(nightly CI job) clean").

Launches the engine's real entry point (``cryodaq-engine --mock``) headless,
lets it run for a bounded window, ASKS it to stop, and asserts:

  - the process was still alive right before shutdown was requested
  - it exited within a grace period after that request (clean shutdown)

The shutdown request is SIGTERM on POSIX and CTRL_BREAK_EVENT on Windows.
They are not interchangeable: ``Popen.terminate()`` on Windows is
``Popen.kill()``, so it cannot be handled and the exit code is 1 whatever the
engine would have done. See ``_request_shutdown``.
  - its captured log has zero ERROR/CRITICAL lines except a small documented
    allowlist of known by-design mock-startup events (e.g. the
    ``detector_warmup`` interlock trip — the mock LS218 driver starts Т12
    warm, above the 10 K interlock threshold, which trips ``stop_source`` on
    essentially every run; that is expected mock behavior, not a defect)

GitHub-hosted runners cap a job at 6h, so CI runs a short bounded window
(see .github/workflows/nightly.yml, default ~25 min). The lab-side literal
72h soak is the SAME script with a larger --duration::

    python -m scripts.soak_mock_engine --duration 1500          # CI (~25 min)
    python -m scripts.soak_mock_engine --duration 259200         # lab (72h)
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

#: Known by-design CRITICAL/ERROR lines from a mock engine run. Kept as
#: regex patterns so a lab operator can extend this via --allow without
#: touching code (e.g. a site-specific known-benign shutdown warning).
DEFAULT_ALLOWLIST: tuple[str, ...] = (
    # Mock LS218 starts Т12 at a warm simulated value; detector_warmup
    # (Т12 > 10 K) trips stop_source on ~every mock run. By design, not a bug.
    r"detector_warmup",
)


def scan_log(text: str, allowlist: Sequence[str] = DEFAULT_ALLOWLIST) -> list[str]:
    """Return ERROR/CRITICAL log lines not matched by ``allowlist``.

    Matches on the structured log level field (see cryodaq.logging_setup:
    ``"%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s"``), not a bare
    substring search — a channel status string like "SENSOR_ERROR" logged at
    INFO must never false-positive as an ERROR line.

    A multi-line traceback's continuation lines (no level-field prefix) are
    not separately scanned; the header line that carries the level already
    flags the violation, so nothing is missed.
    """
    compiled = [re.compile(p) for p in allowlist]
    violations = []
    for line in text.splitlines():
        parts = line.split(" │ ")
        if len(parts) < 2:
            continue
        level = parts[1].strip()
        if level not in ("ERROR", "CRITICAL"):
            continue
        if any(p.search(line) for p in compiled):
            continue
        violations.append(line)
    return violations


@dataclass
class SoakResult:
    alive_before_shutdown: bool
    exit_code: int | None
    clean_shutdown: bool
    violations: list[str]
    log_path: Path
    duration_s: float

    @property
    def ok(self) -> bool:
        return self.alive_before_shutdown and self.clean_shutdown and self.exit_code == 0 and not self.violations


def _default_cmd() -> list[str]:
    """Resolve the engine's real entry point: prefer the installed console
    script (matches production/lab invocation); fall back to module
    invocation (same ``main()``) so the driver works in any dev checkout."""
    exe = shutil.which("cryodaq-engine")
    if exe:
        return [exe, "--mock"]
    return [sys.executable, "-m", "cryodaq.engine", "--mock"]


#: Windows needs the child in its own process group before CTRL_BREAK_EVENT can
#: be delivered to it. On POSIX this is 0 and changes nothing.
_SHUTDOWN_CREATION_FLAGS = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

# The engine emits this after installing its signal handlers.  A soak must not
# request shutdown until that receipt is present, otherwise a slow Windows
# startup can receive CTRL_BREAK_EVENT before the handler exists.
_ENGINE_READY_MARKER = "CryoDAQ Engine запущен"


def _request_shutdown(proc: subprocess.Popen[str]) -> None:
    """ASK the engine to stop, on a channel it can actually hear.

    ``Popen.terminate()`` is ``Popen.kill()`` on Windows: it calls
    ``TerminateProcess(handle, 1)``, so the child dies unconditionally and its
    exit code is 1 no matter how gracefully it would have exited. A
    ``clean_shutdown = exit_code == 0`` assertion built on it can therefore
    never pass on Windows, and reports the platform rather than the engine.
    Measured: a child that installs a SIGTERM handler and calls ``sys.exit(0)``
    still returns 1 after ``terminate()``, and returns 0 after
    ``CTRL_BREAK_EVENT``.

    On POSIX ``terminate()`` is a real SIGTERM and stays correct.
    """
    if sys.platform == "win32":
        proc.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        proc.terminate()


def run_soak(
    duration_s: float,
    *,
    log_path: Path,
    grace_s: float = 30.0,
    startup_timeout_s: float = 120.0,
    allowlist: Sequence[str] = DEFAULT_ALLOWLIST,
    cmd: Sequence[str] | None = None,
    poll_interval_s: float = 1.0,
) -> SoakResult:
    """Run the bounded soak after readiness within ``startup_timeout_s``.

    ``grace_s`` applies only after the shutdown request.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    argv = list(cmd) if cmd is not None else _default_cmd()

    with log_path.open("w", encoding="utf-8") as log_fh:
        child_env = dict(os.environ)
        # The child writes its stderr into the inherited log handle using its
        # OWN interpreter's stream encoding. On a Windows lab host whose active
        # code page is not UTF-8 (e.g. CP1251), the Cyrillic readiness marker
        # would be written in that code page and destroyed by the parent's
        # UTF-8 log reads below. Force UTF-8 in the child so the marker and the
        # whole log survive regardless of the host code page.
        child_env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            argv,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=_SHUTDOWN_CREATION_FLAGS,
            env=child_env,
        )
        try:
            ready_deadline = time.monotonic() + startup_timeout_s
            ready = False
            while time.monotonic() < ready_deadline:
                if _ENGINE_READY_MARKER in log_path.read_text(encoding="utf-8", errors="replace"):
                    ready = True
                    break
                if proc.poll() is not None:
                    break
                time.sleep(poll_interval_s)

            alive_before_shutdown = ready
            if ready:
                deadline = time.monotonic() + duration_s
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    if proc.poll() is not None:
                        alive_before_shutdown = False
                        break
                    time.sleep(min(poll_interval_s, remaining))

            if ready and proc.poll() is None:
                _request_shutdown(proc)
            elif not ready and proc.poll() is None:
                proc.kill()
                exit_code = proc.wait(timeout=10.0)
                clean_shutdown = False
            else:
                alive_before_shutdown = False
            if ready:
                try:
                    exit_code = proc.wait(timeout=grace_s)
                    clean_shutdown = exit_code == 0
                except subprocess.TimeoutExpired:
                    proc.kill()
                    exit_code = proc.wait(timeout=10.0)
                    clean_shutdown = False
            elif proc.poll() is not None:
                exit_code = proc.wait(timeout=10.0)
                clean_shutdown = False
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10.0)

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    violations = scan_log(log_text, allowlist)

    return SoakResult(
        alive_before_shutdown=alive_before_shutdown,
        exit_code=exit_code,
        clean_shutdown=clean_shutdown,
        violations=violations,
        log_path=log_path,
        duration_s=duration_s,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bounded mock-engine soak: run cryodaq-engine --mock for --duration "
            "seconds, SIGTERM it, and assert a clean shutdown with no unexpected "
            "ERROR/CRITICAL log lines."
        )
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=1500.0,
        help="Soak window in seconds (default: 1500 = 25 min). Lab 72h variant: --duration 259200.",
    )
    parser.add_argument(
        "--grace",
        type=float,
        default=30.0,
        help="Seconds to wait for a clean SIGTERM shutdown before SIGKILL (default: 30).",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=120.0,
        help="Seconds to wait for engine readiness before failing the soak (default: 120).",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=None,
        help="Where to write the captured engine log (default: a tempfile).",
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="REGEX",
        help="Extra allowlist regex pattern (repeatable).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    log_path = args.log_path or Path(tempfile.mkstemp(prefix="cryodaq_soak_", suffix=".log")[1])
    allowlist = tuple(DEFAULT_ALLOWLIST) + tuple(args.allow)

    print(
        f"[soak] duration={args.duration:.0f}s grace={args.grace:.0f}s "
        f"startup_timeout={args.startup_timeout:.0f}s log={log_path}"
    )
    result = run_soak(
        args.duration,
        log_path=log_path,
        grace_s=args.grace,
        startup_timeout_s=args.startup_timeout,
        allowlist=allowlist,
    )

    print(
        f"[soak] alive_before_shutdown={result.alive_before_shutdown} "
        f"clean_shutdown={result.clean_shutdown} exit_code={result.exit_code} "
        f"violations={len(result.violations)}"
    )
    if result.violations:
        print("[soak] VIOLATIONS (unexpected ERROR/CRITICAL log lines):")
        for line in result.violations[:50]:
            print(f"  {line}")

    if not result.ok:
        print(f"[soak] FAILED — full log at {log_path}", file=sys.stderr)
        return 1
    print("[soak] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
