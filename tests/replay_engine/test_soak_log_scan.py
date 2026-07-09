"""Unit tests for scripts.soak_mock_engine.scan_log (B-phase-exit soak gate).

Pure function, no subprocess — the soak driver's actual process-lifecycle
behavior is exercised via the local bounded manual run described in the
task report, not here (spinning a real engine per test run would make the
default suite slow/flaky).
"""

from __future__ import annotations

from scripts import soak_mock_engine as soak


def _line(level: str, msg: str, name: str = "cryodaq.engine") -> str:
    return f"2026-07-09 16:00:00 │ {level:<8} │ {name} │ {msg}"


def test_scan_log_flags_error_line():
    text = _line("ERROR", "Something broke")
    assert soak.scan_log(text) == [text]


def test_scan_log_flags_critical_line():
    text = _line("CRITICAL", "Необработанное исключение в event loop: boom")
    assert soak.scan_log(text) == [text]


def test_scan_log_ignores_info_and_warning():
    text = "\n".join(
        [
            _line("INFO", "engine started"),
            _line("WARNING", "VSP63D_1: V1 probe checksum mismatch"),
        ]
    )
    assert soak.scan_log(text) == []


def test_scan_log_does_not_false_positive_on_error_substring_in_message():
    """A status string like SENSOR_ERROR appearing in an INFO message must
    never be mistaken for an ERROR-level line — only the structured level
    field counts."""
    text = _line("INFO", "channel status=SENSOR_ERROR recorded")
    assert soak.scan_log(text) == []


def test_scan_log_allowlists_detector_warmup_trip_by_default():
    """Real line captured from a local mock-engine probe run — the mock
    LS218 driver starts Т12 warm, above the detector_warmup interlock
    threshold (10 K), which trips stop_source on ~every mock run. Expected
    mock behavior, not a defect; must be filtered by the default allowlist."""
    text = (
        "2026-07-09 16:00:10 │ CRITICAL │ cryodaq.core.interlock │ "
        "!!! БЛОКИРОВКА СРАБОТАЛА !!! Имя: 'detector_warmup' | "
        "Описание: Нагрев 2-й ступени (Т12) выше рабочей температуры — "
        "остановка источника | Канал: 'Т12 Теплообменник 2' | Значение: 77.34 | "
        "Порог: > 10 | Действие: 'stop_source' | "
        "Время: 2026-07-09T13:00:10.079937+00:00 | Всего срабатываний: 1"
    )
    assert soak.scan_log(text) == []


def test_scan_log_allowlists_detector_warmup_action_confirmation_by_default():
    text = (
        "2026-07-09 16:00:10 │ CRITICAL │ cryodaq.core.interlock │ "
        "Действие 'stop_source' для блокировки 'detector_warmup' выполнено успешно."
    )
    assert soak.scan_log(text) == []


def test_scan_log_still_flags_unrelated_critical_despite_default_allowlist():
    text = _line("CRITICAL", "unrelated meltdown, nothing to do with interlocks")
    assert soak.scan_log(text) == [text]


def test_scan_log_custom_allowlist_extra_pattern():
    text = _line("ERROR", "known site-specific benign wart XYZ")
    assert soak.scan_log(text, allowlist=(*soak.DEFAULT_ALLOWLIST, "benign wart XYZ")) == []


def test_scan_log_traceback_continuation_lines_do_not_double_count():
    """A logged exception's traceback continuation lines carry no level-field
    prefix; only the header line (which does) should be counted."""
    header = _line("ERROR", "boom")
    text = "\n".join(
        [
            header,
            "Traceback (most recent call last):",
            '  File "engine.py", line 1, in <module>',
            "ValueError: boom",
        ]
    )
    assert soak.scan_log(text) == [header]


def test_scan_log_empty_text_returns_no_violations():
    assert soak.scan_log("") == []
