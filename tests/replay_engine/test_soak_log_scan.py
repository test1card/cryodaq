"""Unit tests for scripts.soak_mock_engine.scan_log (B-phase-exit soak gate).

Pure function, no subprocess — the soak driver's actual process-lifecycle
behavior is exercised via the local bounded manual run described in the
task report, not here (spinning a real engine per test run would make the
default suite slow/flaky).
"""

from __future__ import annotations

from scripts import soak_mock_engine as soak


def _line(level: str, msg: str, name: str = "cryodaq.engine") -> str:
    delimiter = chr(0x2502)
    return f"2026-07-09 16:00:00 {delimiter} {level:<8} {delimiter} {name} {delimiter} {msg}"


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


def test_scan_log_rejects_non_empty_unreadable_log():
    text = "literal escape " + chr(92) + "u2502 ERROR " + chr(92) + "u2502 message"
    try:
        soak.scan_log(text)
    except soak.UnreadableLogError as exc:
        assert str(exc) == "could not read log: no structured lines parsed from non-empty log"
    else:
        raise AssertionError("unreadable non-empty log was accepted")


def test_scan_log_rejects_mixed_log_with_literal_escaped_error_record():
    text = "\n".join(
        [
            _line("INFO", "engine started"),
            "literal escape " + chr(92) + "u2502 ERROR " + chr(92) + "u2502 message",
        ]
    )
    try:
        soak.scan_log(text)
    except soak.UnreadableLogError as exc:
        # The message must describe THIS cause. The mixed log did parse structured
        # lines, so the all-unreadable message would state a property that was not
        # measured, and a reader debugging a red soak would look for the wrong thing.
        assert "malformed ERROR/CRITICAL record" in str(exc), str(exc)
        assert "no structured lines parsed" not in str(exc), str(exc)
    else:
        raise AssertionError("mixed log with malformed ERROR record was accepted")


def test_scan_log_clean_structured_log_is_readable():
    assert soak.scan_log(_line("INFO", "engine started")) == []


def test_run_soak_reports_the_specific_unreadable_reason(tmp_path):
    """The retained reason must name the cause that actually occurred.

    A mixed log DID parse structured lines, so reporting "no structured lines parsed"
    is false and points an operator at the wrong thing. `scan_log` already
    distinguishes the two causes; this pins that the distinction survives to
    `SoakResult` instead of being discarded by `run_soak`.
    """
    bar = chr(0x2502)
    # The child must emit a LITERAL backslash then u2502, not the character that
    # escape produces. Writing chr(92) in THIS file evaluates here and hands the
    # child a real escape, which Python turns back into the delimiter -- giving a
    # readable line and a test that quietly measures the empty-log case instead.
    # So the text "chr(92)" is passed through unevaluated and the CHILD evaluates it.
    backslash = "chr(92)"
    script = (
        "print('2026 ' + chr(0x2502) + ' INFO     ' + chr(0x2502) + ' child ' "
        "+ chr(0x2502) + ' started', flush=True);"
        "print('2026 ' + " + backslash + " + 'u2502 ERROR ' + " + backslash + " + 'u2502 broke', flush=True)"
    )
    log_path = tmp_path / "mixed.log"
    result = soak.run_soak(
        1.0,
        log_path=log_path,
        grace_s=5,
        cmd=(soak.sys.executable, "-c", script),
        poll_interval_s=0.001,
    )

    # The INFO line really did parse, so this is the mixed case, not the empty one.
    assert f" {bar} INFO" in log_path.read_text(encoding="utf-8")
    assert result.log_readable is False
    assert result.ok is False
    # getattr, not attribute access: reverting production removes the field, and an
    # AttributeError proves only that a symbol is missing. This must fail as an
    # ASSERTION about what the driver reports.
    reason = getattr(result, "unreadable_reason", None)
    assert reason is not None, "run_soak discarded the reason scan_log raised"
    assert "malformed ERROR/CRITICAL record" in reason, reason
    assert "no structured lines parsed" not in reason, reason


def test_run_soak_keeps_no_reason_when_the_log_is_readable(tmp_path):
    """A readable log carries no reason, so the field cannot go stale."""
    script = "print('2026 ' + chr(0x2502) + ' INFO     ' + chr(0x2502) + ' child " + chr(0x2502) + " ok', flush=True)"
    result = soak.run_soak(
        1.0,
        log_path=tmp_path / "clean.log",
        grace_s=5,
        cmd=(soak.sys.executable, "-c", script),
        poll_interval_s=0.001,
    )

    assert result.log_readable is True
    assert getattr(result, "unreadable_reason", None) is None


def test_run_soak_forces_child_utf8_output(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "cp1251")
    script = (
        "print('2026 ' + chr(0x2502) + ' INFO     ' + chr(0x2502) + ' child ' + chr(0x2502) + ' Привет', flush=True)"
    )
    log_path = tmp_path / "child.log"
    result = soak.run_soak(
        1.0,
        log_path=log_path,
        grace_s=5,
        cmd=(soak.sys.executable, "-c", script),
        poll_interval_s=0.001,
    )
    assert result.log_readable is True
    assert "Привет" in log_path.read_text(encoding="utf-8")
