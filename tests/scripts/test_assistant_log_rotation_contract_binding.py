"""The soak publisher must accept exactly what the production handler can produce.

WHY THIS MODULE EXISTS (PR #102 cold review F1). The long-soak publisher restated the
assistant log's retention count and its rotation-name shape as private copies, and its
tests read those copies back -- so nothing compared them against the REAL handler that
produces the files. If ``setup_logging`` later retained more rotations, teardown would
refuse validly retained days and publish a false rotation-ceiling marker instead of the
diagnosis, losing the artifact this publisher exists to preserve.

WHAT BINDS NOW. One contract lives in ``cryodaq.logging_setup``; both sides consume it.
These tests construct the real production handler through ``setup_logging``'s own
default path, force a GENUINE rollover through the handler's own code, and prove the
publisher accepts exactly the names that machinery produces -- up to exactly the
handler's own retention, and no further. A change to real handler retention, rotation
trigger, or suffix shape without its consumer turns these red.
"""

from __future__ import annotations

import logging
import logging.handlers
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest

from cryodaq import logging_setup
from scripts import soak_mock_stack_runner as runner


class _Evidence:
    """The narrow part of the evidence writer these publishers use."""

    def __init__(self) -> None:
        self.logs: dict[str, str] = {}

    def write_log(self, name: str, text: str) -> None:
        self.logs[name] = text


@pytest.fixture
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect production logging into a throwaway root, and clean handlers up.

    The teardown closes every root handler the test installed BEFORE pytest's
    tmp_path cleanup runs, so no open handle keeps a deleted directory alive on
    Windows.
    """

    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))
    monkeypatch.delenv("CRYODAQ_STATE_ROOT", raising=False)
    (tmp_path / "logs").mkdir(parents=True)
    yield tmp_path
    root = logging.getLogger()
    for handler in list(root.handlers):
        try:
            handler.close()
        finally:
            root.removeHandler(handler)


def _production_assistant_file_handler() -> logging.handlers.TimedRotatingFileHandler:
    """The rotating file handler ``setup_logging`` actually installed, not a stand-in."""
    installed = [
        item for item in logging.getLogger().handlers if isinstance(item, logging.handlers.TimedRotatingFileHandler)
    ]
    assert len(installed) == 1, f"expected exactly one rotating file handler, found {len(installed)}"
    return installed[0]


def _dated_rotation_names(suffix_format: str, count: int) -> list[str]:
    """Names a daily-rotated log accumulates over ``count`` distinct past days.

    Calendar arithmetic rather than epoch subtraction, so consecutive names stay
    distinct across DST transitions and timezone shifts on either platform.
    """
    base = logging_setup.ASSISTANT_LOG_BASENAME
    today = date.today()
    return [
        f"{base}.{time.strftime(suffix_format, (today - timedelta(days=offset)).timetuple())}"
        for offset in range(1, count + 1)
    ]


def test_the_real_production_handler_carries_the_published_contract(state_root: Path) -> None:
    """Retention, trigger, suffix shape, and basename must BE the contract values.

    Each comparison reads an attribute of the object production really builds.
    A hardcoded alternative in ``setup_logging``, or a stdlib change to what
    ``midnight`` means, lands here instead of silently diverging from the
    publisher's expectations.
    """

    logging_setup.setup_logging("assistant", console=False)
    handler = _production_assistant_file_handler()

    # The component string the assistant bootstrap passes must produce the name
    # the contract publishes; otherwise teardown watches a file nobody writes.
    assert Path(handler.baseFilename).name == logging_setup.ASSISTANT_LOG_BASENAME
    assert handler.backupCount == logging_setup.ASSISTANT_LOG_BACKUP_COUNT
    assert handler.when == logging_setup.ASSISTANT_LOG_ROTATION_WHEN.upper()
    assert handler.suffix == logging_setup.ASSISTANT_LOG_SUFFIX_FORMAT


def test_a_real_rollover_produces_names_the_publisher_accepts(state_root: Path) -> None:
    """A genuine rollover through the handler's own code must yield accepted names."""

    logging_setup.setup_logging("assistant", console=False)
    handler = _production_assistant_file_handler()
    probe = logging.getLogger("contract.rollover.probe")

    # The first record arrives while rolloverAt is still in the future, so it
    # materialises the base file through the delayed-open path. Ageing rolloverAt
    # then makes the SECOND record roll that EXISTING file over via doRollover --
    # the exact code path a long soak exercises at midnight.
    probe.info("first record")
    handler.rolloverAt = int(time.time()) - 1
    probe.info("second record")
    handler.flush()

    logs_dir = state_root / "logs"
    produced = {item.name for item in logs_dir.iterdir()}
    rotated = produced - {logging_setup.ASSISTANT_LOG_BASENAME}
    assert rotated, "the forced rollover never wrote a dated rotation"
    for name in rotated:
        assert runner._ASSISTANT_LOG_ROTATION_RE.fullmatch(name) is not None, (
            f"the real handler produced {name!r}; the soak publisher would refuse or ignore it"
        )
    assert runner._rotated_assistant_log_names(logs_dir) == sorted(rotated)


def test_publisher_publishes_a_full_handler_retention_of_real_rotation_names(
    state_root: Path,
) -> None:
    """Exactly one full handler retention is accepted, oldest first, none refused.

    The boundary this pins: a directory holding EVERY day the real handler can
    validly retain must publish, so any future tightening of recognition loses
    evidence visibly here instead of silently at soak teardown.
    """

    logging_setup.setup_logging("assistant", console=False)
    handler = _production_assistant_file_handler()
    rotations = _dated_rotation_names(handler.suffix, logging_setup.ASSISTANT_LOG_BACKUP_COUNT)

    logs_dir = state_root / "logs"
    for offset, name in enumerate(rotations):
        (logs_dir / name).write_bytes(f"CAUSE-{offset:02d}\n".encode())
    (logs_dir / logging_setup.ASSISTANT_LOG_BASENAME).write_bytes(b"ACTIVE LAST DAY\n")

    assert runner._rotated_assistant_log_names(logs_dir) == sorted(rotations)

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "CAUSE-00" in published, "a validly retained day was dropped"
    assert f"CAUSE-{len(rotations) - 1:02d}" in published
    assert published.index("CAUSE-00") < published.index("ACTIVE LAST DAY")
    assert runner._ASSISTANT_LOG_ROTATION_CEILING_MARKER not in published


def test_process_death_after_real_handler_rename_keeps_the_causal_log(state_root: Path) -> None:
    """One extra rotation is a real interrupted-rollover state, not contract drift."""

    logs_dir = state_root / "logs"
    old_rotations = []
    for offset in range(30, 30 + logging_setup.ASSISTANT_LOG_BACKUP_COUNT):
        rotation_day = date.today() - timedelta(days=offset)
        suffix = time.strftime(logging_setup.ASSISTANT_LOG_SUFFIX_FORMAT, rotation_day.timetuple())
        old_rotations.append(f"{logging_setup.ASSISTANT_LOG_BASENAME}.{suffix}")
    for offset, name in enumerate(old_rotations):
        (logs_dir / name).write_bytes(f"OLDER CAUSE {offset:02d}\n".encode())

    child = "\n".join(
        (
            "import logging, logging.handlers, os, time",
            "from cryodaq import logging_setup",
            "logging_setup.setup_logging('assistant', console=False)",
            "handler = next(h for h in logging.getLogger().handlers "
            "if isinstance(h, logging.handlers.TimedRotatingFileHandler))",
            "logging.getLogger('rollover.death').error('PERIODIC SOURCE FAILED; api_key: leakme020Fj')",
            "handler.flush()",
            "handler.rolloverAt = int(time.time()) - 1",
            "handler.getFilesToDelete = lambda: os._exit(91)",
            "handler.doRollover()",
            "raise SystemExit(92)",
        )
    )
    completed = subprocess.run(
        (sys.executable, "-c", child),
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 91, completed.stderr

    selected = runner._rotated_assistant_log_names(logs_dir)
    assert not isinstance(selected, runner._AssistantLogDirectoryRefusal)
    assert len(selected) == logging_setup.ASSISTANT_LOG_BACKUP_COUNT + 1

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "PERIODIC SOURCE FAILED" in published
    assert "OLDER CAUSE" in published
    assert "leakme020Fj" not in published
    assert runner._ASSISTANT_LOG_ROTATION_CEILING_MARKER not in published


def test_two_rotations_beyond_handler_retention_refuse_fail_closed(state_root: Path) -> None:
    """Only one interrupted-rollover residue is accepted; further excess refuses."""

    logging_setup.setup_logging("assistant", console=False)
    handler = _production_assistant_file_handler()
    rotations = _dated_rotation_names(
        handler.suffix,
        logging_setup.ASSISTANT_LOG_BACKUP_COUNT + 2,
    )

    logs_dir = state_root / "logs"
    for name in rotations:
        (logs_dir / name).write_bytes(b"MUST NOT PUBLISH\n")
    (logs_dir / logging_setup.ASSISTANT_LOG_BASENAME).write_bytes(b"ACTIVE MUST NOT PUBLISH\n")

    evidence = _Evidence()
    runner._publish_assistant_log(evidence, state_root)

    published = evidence.logs[runner._ASSISTANT_LOG_EVIDENCE_NAME]
    assert "MUST NOT PUBLISH" not in published
    assert published == runner._ASSISTANT_LOG_ROTATION_CEILING_MARKER


def test_recognition_rejects_shapes_the_daily_handler_never_produces() -> None:
    """Recognition derived from the contract must discriminate, not accept broadly.

    If ``setup_logging`` ever rotated hourly, the handler would emit
    ``<basename>.YYYY-MM-DD_HH`` names; those must fail the publisher's pattern
    so the cross-binding guard turns red instead of the publisher pretending a
    changed suffix never happened.
    """

    pattern = runner._ASSISTANT_LOG_ROTATION_RE
    base = logging_setup.ASSISTANT_LOG_BASENAME
    daily = time.strftime(logging_setup.ASSISTANT_LOG_SUFFIX_FORMAT)
    hourly = time.strftime("%Y-%m-%d_%H")

    assert pattern.fullmatch(f"{base}.{daily}") is not None
    assert pattern.fullmatch(f"{base}.{hourly}") is None
    assert pattern.fullmatch(f"{base}.{daily}.gz") is None
    assert pattern.fullmatch(base) is None


def test_runner_constants_are_the_authoritative_contract_values() -> None:
    """The publisher consumes the one contract; no private copy remains."""

    assert runner._ASSISTANT_LOG_BACKUP_COUNT == logging_setup.ASSISTANT_LOG_BACKUP_COUNT
    base = logging_setup.ASSISTANT_LOG_BASENAME
    derived_here = logging_setup.rotated_log_name_pattern(base)
    assert runner._ASSISTANT_LOG_ROTATION_RE.pattern == derived_here.pattern
