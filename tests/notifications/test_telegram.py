"""Tests for TelegramNotifier — alarm event formatting and callback behaviour."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from cryodaq.core.alarm import AlarmEvent, AlarmSeverity
from cryodaq.notifications.telegram import TelegramNotifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event(
    event_type: str = "activated",
    severity: AlarmSeverity = AlarmSeverity.WARNING,
    alarm_name: str = "test_alarm",
    channel: str = "ls218s/CH1",
    value: float = 150.0,
    threshold: float = 100.0,
    ts: datetime | None = None,
) -> AlarmEvent:
    return AlarmEvent(
        timestamp=ts or datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc),
        alarm_name=alarm_name,
        channel=channel,
        value=value,
        threshold=threshold,
        severity=severity,
        event_type=event_type,
    )


def _notifier(**kwargs) -> TelegramNotifier:
    return TelegramNotifier(
        bot_token=kwargs.get("bot_token", "123456:FAKE_TOKEN"),
        chat_id=kwargs.get("chat_id", -1001234567890),
        send_cleared=kwargs.get("send_cleared", True),
        timeout_s=kwargs.get("timeout_s", 5.0),
    )


# ---------------------------------------------------------------------------
# 1. _format_message for "activated" event contains emoji and ТРЕВОГА header
# ---------------------------------------------------------------------------

def test_format_message_activated() -> None:
    notifier = _notifier()
    event = _event(
        event_type="activated",
        severity=AlarmSeverity.CRITICAL,
        alarm_name="T_STAGE_HIGH",
        channel="ls218s/T_STAGE",
        value=350.0,
        threshold=300.0,
    )

    msg = notifier._format_message(event)

    assert "ТРЕВОГА" in msg, "Expected 'ТРЕВОГА' in activated message"
    assert "🔔" in msg, "Expected activated emoji 🔔"
    assert "🚨" in msg, "Expected critical severity emoji 🚨"
    assert "T_STAGE_HIGH" in msg, "alarm_name not in message"
    assert "ls218s/T_STAGE" in msg or "ls218s" in msg, "channel not in message"
    assert "350" in msg, "value not in message"
    assert "300" in msg, "threshold not in message"
    assert "CRITICAL" in msg, "severity label not in message"


# ---------------------------------------------------------------------------
# 2. _format_message for "cleared" event contains "Тревога снята"
# ---------------------------------------------------------------------------

def test_format_message_cleared() -> None:
    notifier = _notifier()
    event = _event(
        event_type="cleared",
        severity=AlarmSeverity.WARNING,
        alarm_name="T_SHIELD_HIGH",
        channel="ls218s/T_SHIELD",
        value=80.0,
        threshold=100.0,
    )

    msg = notifier._format_message(event)

    assert "Тревога снята" in msg, "Expected 'Тревога снята' in cleared message"
    assert "✅" in msg, "Expected cleared emoji ✅"
    assert "T_SHIELD_HIGH" in msg, "alarm_name not in cleared message"


# ---------------------------------------------------------------------------
# 3. __call__ with "acknowledged" event returns early — no HTTP call
# ---------------------------------------------------------------------------

async def test_acknowledged_skipped() -> None:
    notifier = _notifier()
    event = _event(event_type="acknowledged")

    # Patch _send so we can verify it is NOT called
    notifier._send = AsyncMock()

    await notifier(event)

    notifier._send.assert_not_called()


# ---------------------------------------------------------------------------
# 4. send_cleared=False skips cleared events — no HTTP call
# ---------------------------------------------------------------------------

async def test_send_cleared_disabled() -> None:
    notifier = _notifier(send_cleared=False)
    event = _event(event_type="cleared")

    notifier._send = AsyncMock()

    await notifier(event)

    notifier._send.assert_not_called()


# ---------------------------------------------------------------------------
# 5. from_config loads bot_token and chat_id from YAML
# ---------------------------------------------------------------------------

def test_from_config(tmp_path: Path) -> None:
    config_path = tmp_path / "notifications.yaml"
    config_data = {
        "telegram": {
            "bot_token": "987654:SECRET_TOKEN",
            "chat_id": -9998887776665,
            "send_cleared": False,
            "timeout_s": 15.0,
        }
    }
    with config_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(config_data, fh)

    notifier = TelegramNotifier.from_config(config_path)

    assert notifier._bot_token == "987654:SECRET_TOKEN"
    assert notifier._chat_id == -9998887776665
    assert notifier._send_cleared is False
    assert abs(notifier._timeout_s - 15.0) < 1e-9
    assert "987654:SECRET_TOKEN" in notifier._api_url


# ---------------------------------------------------------------------------
# Additional: activated event does invoke _send
# ---------------------------------------------------------------------------

async def test_activated_calls_send() -> None:
    notifier = _notifier()
    event = _event(event_type="activated")

    notifier._send = AsyncMock()

    await notifier(event)

    notifier._send.assert_called_once()
    # Verify the text passed contains the alarm name
    text_arg: str = notifier._send.call_args[0][0]
    assert "test_alarm" in text_arg


# ---------------------------------------------------------------------------
# Additional: from_config raises FileNotFoundError for missing file
# ---------------------------------------------------------------------------

def test_from_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        TelegramNotifier.from_config(tmp_path / "does_not_exist.yaml")


# ---------------------------------------------------------------------------
# Additional: _format_message includes time string in expected format
# ---------------------------------------------------------------------------

def test_format_message_time_format() -> None:
    notifier = _notifier()
    ts = datetime(2026, 3, 14, 9, 5, 3, tzinfo=timezone.utc)
    event = _event(event_type="activated", ts=ts)

    msg = notifier._format_message(event)

    # Time is formatted as HH:MM:SS DD.MM.YYYY
    assert "09:05:03" in msg, f"Expected time '09:05:03' in message: {msg!r}"
    assert "14.03.2026" in msg, f"Expected date '14.03.2026' in message: {msg!r}"
