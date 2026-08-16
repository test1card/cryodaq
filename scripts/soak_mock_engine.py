"""Bounded mock-engine soak driver (roadmap B-phase-exit: "72h mock soak
(nightly CI job) clean").

Launches the engine's real entry point (``cryodaq-engine --mock``) headless,
lets it run for a bounded window, sends SIGTERM, and asserts:

  - the process was still alive right before shutdown was requested
  - it exited within a grace period after SIGTERM (clean shutdown)
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


class UnreadableLogError(RuntimeError):
    """Raised when a log cannot be scanned well enough to certify it clean.

    Three distinct causes, each carrying its own message: a non-empty log in
    which no line carries the structured level field at all, a log that does
    parse but contains a recognizably malformed ERROR/CRITICAL record, and a
    log whose raw bytes are not valid UTF-8. The malformed-record and
    undecodable cases are the dangerous ones — the readable lines can all be
    clean while the record that would have failed the scan is the one the
    parser could not read.
    """

    def __init__(self, message: str, violations: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.violations = list(violations)


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
    parsed_lines = 0
    malformed_error_record = False
    delimiter = chr(0x2502)
    escaped_delimiter = r"\u2502"
    for line in text.splitlines():
        parts = line.split(f" {delimiter} ")
        if len(parts) < 2:
            escaped_parts = line.split(f" {escaped_delimiter} ")
            if len(escaped_parts) >= 2 and escaped_parts[1].strip() in ("ERROR", "CRITICAL"):
                malformed_error_record = True
            continue
        parsed_lines += 1
        level = parts[1].strip()
        if level not in ("ERROR", "CRITICAL"):
            continue
        if any(p.search(line) for p in compiled):
            continue
        violations.append(line)
    # Order matters, and the more fundamental fact wins. A log in which nothing
    # parsed is reported as such even when it also holds a malformed record: the
    # mixed-log message would imply the rest of the log was read, and it was not.
    if text and parsed_lines == 0:
        raise UnreadableLogError("could not read log: no structured lines parsed from non-empty log")
    if malformed_error_record:
        raise UnreadableLogError(
            "could not read log: a malformed ERROR/CRITICAL record was found, "
            "so the readable lines do not establish a clean run",
            violations,
        )
    return violations


@dataclass
class SoakResult:
    alive_before_shutdown: bool
    exit_code: int | None
    clean_shutdown: bool
    violations: list[str]
    log_path: Path
    duration_s: float
    log_readable: bool
    # The exact reason the log could not be read, or None when it was readable.
    # scan_log distinguishes two causes and the command must report the right one.
    unreadable_reason: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.alive_before_shutdown
            and self.clean_shutdown
            and self.exit_code == 0
            and self.log_readable
            and not self.violations
        )


def _default_cmd() -> list[str]:
    """Resolve the engine's real entry point: prefer the installed console
    script (matches production/lab invocation); fall back to module
    invocation (same ``main()``) so the driver works in any dev checkout."""
    exe = shutil.which("cryodaq-engine")
    if exe:
        return [exe, "--mock"]
    return [sys.executable, "-m", "cryodaq.engine", "--mock"]


def _read_captured_log(path: Path) -> str:
    """Strictly decode the captured log, or fail the soak as unreadable.

    ``errors="replace"`` would turn invalid UTF-8 written directly to the
    captured fd (native code bypassing the child's Python stream encoding)
    into U+FFFD replacement characters, which scan as ordinary text -- a
    corrupted log would certify clean. A strict decode surfaces those bytes
    as an unreadable result instead.
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise UnreadableLogError(
            f"could not read log: {exc}. The captured log contains bytes that "
            "are not valid UTF-8, so the run cannot be certified clean"
        ) from exc


def run_soak(
    duration_s: float,
    *,
    log_path: Path,
    grace_s: float = 30.0,
    allowlist: Sequence[str] = DEFAULT_ALLOWLIST,
    cmd: Sequence[str] | None = None,
    poll_interval_s: float = 1.0,
) -> SoakResult:
    """Run the bounded soak. Blocks for ~``duration_s`` + shutdown time."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    argv = list(cmd) if cmd is not None else _default_cmd()

    with log_path.open("w", encoding="utf-8") as log_fh:
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONUTF8"] = "1"
        proc = subprocess.Popen(
            argv,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            text=True,
            env=child_env,
        )
        try:
            deadline = time.monotonic() + duration_s
            alive_before_shutdown = True
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if proc.poll() is not None:
                    alive_before_shutdown = False
                    break
                time.sleep(min(poll_interval_s, remaining))

            proc.terminate()  # SIGTERM — same signal a real deploy sends
            try:
                exit_code = proc.wait(timeout=grace_s)
                clean_shutdown = exit_code == 0
            except subprocess.TimeoutExpired:
                proc.kill()
                exit_code = proc.wait(timeout=10.0)
                clean_shutdown = False
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10.0)

    try:
        log_text = _read_captured_log(log_path)
        violations = scan_log(log_text, allowlist)
        log_readable = True
        unreadable_reason = None
    except UnreadableLogError as exc:
        # Keep the exact reason. `scan_log` distinguishes "nothing parsed at all" from
        # "a malformed ERROR record was found among readable lines", and discarding that
        # here made the command report the first cause for both -- sending an operator
        # investigating a failed long soak toward a log that had in fact parsed.
        violations = exc.violations
        log_readable = False
        unreadable_reason = str(exc)

    return SoakResult(
        alive_before_shutdown=alive_before_shutdown,
        exit_code=exit_code,
        clean_shutdown=clean_shutdown,
        violations=violations,
        log_path=log_path,
        duration_s=duration_s,
        log_readable=log_readable,
        unreadable_reason=unreadable_reason,
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

    print(f"[soak] duration={args.duration:.0f}s grace={args.grace:.0f}s log={log_path}")
    result = run_soak(args.duration, log_path=log_path, grace_s=args.grace, allowlist=allowlist)

    print(
        f"[soak] alive_before_shutdown={result.alive_before_shutdown} "
        f"clean_shutdown={result.clean_shutdown} exit_code={result.exit_code} "
        f"violations={len(result.violations)} log_readable={result.log_readable}"
    )
    if not result.log_readable:
        print(f"[soak] COULD NOT READ LOG — {result.unreadable_reason or 'reason unavailable'}")
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
