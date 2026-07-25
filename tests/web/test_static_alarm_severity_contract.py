from __future__ import annotations

from pathlib import Path


def test_read_only_web_alarm_severity_uses_canonical_caution_and_conspicuous_unknown() -> None:
    html = Path("src/cryodaq/web/static/index.html").read_text(encoding="utf-8")

    assert "severity === 'warning' || severity === 'caution'" in html
    assert "cls = 'alarm-caution'; lvlText = 'ВНИМАНИЕ'" in html
    assert "let cls = 'alarm-critical'" in html
    assert "let lvlText = 'НЕИЗВЕСТНЫЙ УРОВЕНЬ'" in html
    assert "severity || 'unknown'" in html
    assert "ПРЕДУПРЕЖДЕНИЕ" not in html


def test_read_only_web_acknowledgement_retains_the_active_alarm_row() -> None:
    html = Path("src/cryodaq/web/static/index.html").read_text(encoding="utf-8")
    handler = html.split("function handleAlarm(msg) {", 1)[1].split("\n}\n\nfunction renderAlarms", 1)[0]

    assert "if (msg.state === 'OK')" in handler
    assert "msg.state === 'OK' || msg.state === 'ACKNOWLEDGED'" not in handler
    assert "else if (msg.state !== 'ACKNOWLEDGED')" in handler
