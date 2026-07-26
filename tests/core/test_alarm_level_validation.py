"""Fail-closed load-time validation for canonical alarm levels."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cryodaq.core.alarm_config import AlarmConfigError, load_alarm_config


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "alarms_v3.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


@pytest.mark.parametrize(
    ("level_line", "offending_value"),
    [
        ("level: CRITCAL", "'CRITCAL'"),
        ("level: FATAL", "'FATAL'"),
        ("# level deliberately absent", "None"),
        ("level: [CRITICAL]", "['CRITICAL']"),
        # HIGH is only a legacy raw-config safety/throttle classification.  It
        # is not representable by the canonical AlarmEvent snapshot schema.
        ("level: HIGH", "'HIGH'"),
    ],
    ids=["misspelling", "unknown", "missing", "wrong-type", "legacy-high"],
)
def test_alarm_level_must_be_an_exact_canonical_enum(tmp_path: Path, level_line: str, offending_value: str) -> None:
    """No malformed level may silently receive a non-safety classification."""
    p = _write_yaml(
        tmp_path,
        f"""
        global_alarms:
          bad_level:
            alarm_type: threshold
            channel: T12
            check: above
            threshold: 5.0
            {level_line}
        """,
    )

    with pytest.raises(AlarmConfigError) as exc_info:
        load_alarm_config(p)

    message = str(exc_info.value)
    assert "bad_level" in message
    assert offending_value in message
    assert "level" in message


@pytest.mark.parametrize("level", ["INFO", "WARNING", "CRITICAL"])
def test_canonical_alarm_levels_still_load(tmp_path: Path, level: str) -> None:
    p = _write_yaml(
        tmp_path,
        f"""
        global_alarms:
          canonical_level:
            alarm_type: threshold
            channel: T12
            check: above
            threshold: 5.0
            level: {level}
        """,
    )

    _, alarms = load_alarm_config(p)
    assert alarms[0].config["level"] == level
