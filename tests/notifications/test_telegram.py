"""Tests for TelegramNotifier, TelegramCommandBot, EscalationService."""

from __future__ import annotations

import asyncio
import html
import json
import re
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.notifications.telegram import TelegramNotifier
from cryodaq.notifications.telegram_commands import _HELP_TEXT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _notifier(**kwargs) -> TelegramNotifier:
    return TelegramNotifier(
        bot_token=kwargs.get("bot_token", "123456:FAKE_TOKEN"),
        chat_id=kwargs.get("chat_id", -1001234567890),
        send_cleared=kwargs.get("send_cleared", True),
        timeout_s=kwargs.get("timeout_s", 5.0),
    )


# ---------------------------------------------------------------------------
# 1. The retired alarm-v1 notifier surface stays retired.
#
# TelegramNotifier.__call__/_format_message/_send formatted a
# cryodaq.core.alarm AlarmEvent — a type deleted in the v1->v2 migration.
# Nothing constructed such an event and nothing registered the notifier as
# an alarm callback (engine.py builds it only for EscalationService, which
# calls send_message). The formatter carried the unknown-as-determined
# defect (`f"{event.value:.4g}"` prints "nan" for an unavailable reading),
# so the unreachable chain was removed rather than patched. This guard
# fails if it is reintroduced without a live caller.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attr", ["__call__", "_format_message", "_send"])
def test_retired_alarm_notifier_surface_absent(attr: str) -> None:
    # vars(), not hasattr(): every class inherits type.__call__.
    assert attr not in vars(TelegramNotifier), (
        f"TelegramNotifier.{attr} is the retired alarm-v1 formatting chain "
        "(unreachable, and it rendered non-finite values as 'nan'). "
        "Reintroduce it only together with a production caller and a "
        "finite-value guard."
    )


# ---------------------------------------------------------------------------
# 2. from_config loads bot_token and chat_id from YAML
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

    # Phase 2b K.1: token is wrapped in SecretStr; compare via get_secret_value.
    assert notifier._bot_token.get_secret_value() == "987654:SECRET_TOKEN"
    assert notifier._chat_id == -9998887776665
    assert notifier._send_cleared is False
    assert abs(notifier._timeout_s - 15.0) < 1e-9
    # _api_url is no longer a stored attribute; the URL is built on demand.
    assert "987654:SECRET_TOKEN" in notifier._build_api_url("sendMessage")


# ---------------------------------------------------------------------------
# Additional: from_config raises FileNotFoundError for missing file
# ---------------------------------------------------------------------------


def test_from_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        TelegramNotifier.from_config(tmp_path / "does_not_exist.yaml")


# ===========================================================================
# TelegramCommandBot v2 tests
# ===========================================================================


def _make_bot(**kwargs):
    """Создать TelegramCommandBot с заглушками."""
    from unittest.mock import MagicMock

    from cryodaq.notifications.telegram_commands import TelegramCommandBot

    broker = MagicMock()
    broker.subscribe = AsyncMock(return_value=asyncio.Queue())
    alarm_engine = MagicMock()
    alarm_engine.get_active.return_value = {}
    # Phase 2b K.1: TelegramCommandBot now refuses empty allowlist
    # when commands are enabled. Pass a default test chat id unless the
    # caller overrides it.
    kwargs.setdefault("allowed_chat_ids", [1234])
    bot = TelegramCommandBot(
        broker,
        alarm_engine,
        bot_token="fake:TOKEN",
        **kwargs,
    )
    bot._send = AsyncMock()
    return bot


def _tg_msg(
    text: str,
    chat_id: int = 1234,
    username: str = "testuser",
    message_id: int = 77,
) -> dict:
    return {
        "text": text,
        "message_id": message_id,
        "chat": {"id": chat_id},
        "from": {"id": 9, "username": username, "first_name": "Test"},
    }



def _extract_required_form_from_handler_error(text: str, command: str) -> str:
    normalized = html.unescape(text)
    pattern = rf"{re.escape(command)}\s+<[^\n>]+(?:\s+<[^\n>]+)?"
    match = re.search(pattern, normalized)
    assert match is not None, f"handler rejection for {command} did not include a full required form"
    return match.group(0).strip()


def _help_line_from_text(help_text: str, command: str) -> str:
    for line in html.unescape(help_text).splitlines():
        normalized = line.strip()
        if normalized.startswith(f"{command} "):
            return normalized.split("—", 1)[0].strip()
    raise AssertionError(f"help text is missing {command}")

def _capability_response(token: str = "token-1") -> dict:
    return {
        "ok": True,
        "compatibility_receipt": {
            "schema": "mutation_compatibility_v1",
            "accepted": True,
            "server_protocol_major": 1,
            "required_capability": "cryodaq_mutation_v1",
            "capability_token": token,
        },
    }


def _published_log_result(command: dict, *, entry_id: int = 1) -> dict:
    entry = {
        "id": entry_id,
        "timestamp": "2026-07-23T00:00:00+00:00",
        "experiment_id": command["experiment_id"],
        "author": command["author"],
        "source": command["source"],
        "message": command["message"],
        "tags": list(command.get("tags", [])),
    }
    return {
        "ok": True,
        "committed": True,
        "retry_safe": False,
        "publication_state": "published",
        "entry": entry,
        "commit_receipt": {
            "schema": "operator_log_commit_v1",
            "request_id": command["request_id"],
            "entry_id": entry_id,
            "experiment_id": command["experiment_id"],
            "committed": True,
        },
    }


async def test_cmd_status_formats_message() -> None:
    bot = _make_bot()
    await bot._handle_message(_tg_msg("/status"))
    bot._send.assert_called_once()
    text: str = bot._send.call_args[0][1]
    assert "CryoDAQ" in text or "Статус" in text or "Аптайм" in text


def test_cached_readings_render_stale_or_unavailable_truthfully() -> None:
    bot = _make_bot()
    bot._latest = {
        "Т1": Reading(
            timestamp=datetime.now(UTC) - timedelta(minutes=5),
            instrument_id="LS218",
            channel="Т1",
            value=4.2,
            unit="K",
        ),
        "Т2": Reading(
            timestamp=datetime.now(UTC),
            instrument_id="LS218",
            channel="Т2",
            value=float("nan"),
            unit="K",
            status=ChannelStatus.SENSOR_ERROR,
        ),
        "vacuum": Reading(
            timestamp=datetime.now(UTC) - timedelta(minutes=5),
            instrument_id="VSP",
            channel="vacuum",
            value=1e-4,
            unit="mbar",
        ),
        "Keithley/smu/voltage": Reading(
            timestamp=datetime.now(UTC),
            instrument_id="Keithley",
            channel="Keithley/smu/voltage",
            value=float("nan"),
            unit="V",
            status=ChannelStatus.SENSOR_ERROR,
        ),
    }

    temps = bot._cmd_temps()
    pressure = bot._cmd_pressure()
    keithley = bot._cmd_keithley()
    status = bot._cmd_status()

    assert "4.20" in temps and "устар" in temps
    assert "nan" not in temps and "недоступ" in temps
    assert "1.00e-04" in pressure and "устар" in pressure
    assert "nan" not in keithley and "недоступ" in keithley
    assert "LS218: активен" not in status
    assert "устар" in status or "недоступ" in status


def test_fresh_cached_temperature_remains_a_normal_readout() -> None:
    bot = _make_bot()
    bot._latest = {
        "Т1": Reading.now("Т1", 4.2, "K", instrument_id="LS218"),
    }

    rendered = bot._cmd_temps()

    assert "4.20 K" in rendered
    assert "устар" not in rendered and "недоступ" not in rendered


async def test_cmd_log_writes_entry() -> None:
    async def dispatch(command: dict) -> dict:
        if command == {"cmd": "mutation_capabilities"}:
            return _capability_response()
        return _published_log_result(command)

    handler = AsyncMock(side_effect=dispatch)
    bot = _make_bot(command_handler=handler)
    await bot._handle_message(_tg_msg("/log exp-1 Всё штатно"))
    assert handler.await_count == 2
    cmd = handler.await_args_list[1].args[0]
    assert cmd["cmd"] == "log_entry"
    assert "Всё штатно" in cmd["message"]
    assert cmd["author"] == "testuser"
    assert cmd["experiment_id"] == "exp-1"
    assert len(cmd["request_id"]) == 32
    assert set(cmd["request_id"]) <= set("0123456789abcdef")
    assert set(cmd) == {
        "cmd",
        "request_id",
        "experiment_id",
        "message",
        "author",
        "source",
        "protocol_major",
        "mutation_capability",
        "capability_token",
    }
    assert cmd["protocol_major"] == 1
    assert cmd["mutation_capability"] == "cryodaq_mutation_v1"
    assert cmd["capability_token"] == "token-1"
    bot._send.assert_called_once()
    assert "✅" in bot._send.call_args[0][1]


@pytest.mark.parametrize("corruption", ["missing_publication", "wrong_request", "wrong_author", "extra_key"])
async def test_cmd_log_never_accepts_incomplete_or_misbound_success(corruption: str) -> None:
    async def dispatch(command: dict) -> dict:
        if command == {"cmd": "mutation_capabilities"}:
            return _capability_response()
        result = _published_log_result(command)
        if corruption == "missing_publication":
            result.pop("publication_state")
        elif corruption == "wrong_request":
            result["commit_receipt"]["request_id"] = "f" * 32
        elif corruption == "wrong_author":
            result["entry"]["author"] = "forged"
        else:
            result["unexpected"] = True
        return result

    bot = _make_bot(command_handler=AsyncMock(side_effect=dispatch))
    await bot._handle_message(_tg_msg("/log exp-1 exact"))

    reply = bot._send.await_args.args[1]
    assert "✅" not in reply
    assert "Подробности" in reply


async def test_query_agent_missing_reply_has_no_english_terms() -> None:
    bot = _make_bot(query_agent=None)

    await bot._handle_text(_tg_msg("что сейчас?"))

    text: str = bot._send.call_args[0][1]
    assert "slash" not in text.lower()
    assert "команды" in text


async def test_unavailable_command_handler_reply_has_no_english_terms() -> None:
    bot = _make_bot(command_handler=None)

    await bot._handle_message(_tg_msg("/log exp-1 запись"))

    text: str = bot._send.call_args[0][1]
    assert "command_handler" not in text
    assert "обработчик" in text


async def test_command_handler_failure_does_not_expose_raw_english_error() -> None:
    handler = AsyncMock(return_value={"ok": False, "error": "backend failure"})
    bot = _make_bot(command_handler=handler)

    await bot._handle_message(_tg_msg("/log exp-1 запись"))

    text: str = bot._send.call_args[0][1]
    assert "backend failure" not in text
    assert "Подробности" in text


async def test_cmd_log_empty_text_returns_error() -> None:
    bot = _make_bot()
    await bot._handle_message(_tg_msg("/log"))
    bot._send.assert_called_once()
    reply = bot._send.call_args[0][1]
    assert reply == "❌ Укажите experiment_id и текст: /log &lt;experiment_id&gt; &lt;текст&gt;"
    assert reply.encode("utf-8").decode("utf-8") == reply
    assert "\ufffd" not in reply




@pytest.mark.parametrize(
    ("message", "command"),
    [
        ("/log text", "/log"),
        ("/phase cooling", "/phase"),
    ],
)
async def test_help_text_reflects_current_command_requirements(message: str, command: str) -> None:
    bot = _make_bot()
    await bot._handle_message(_tg_msg(message))
    rejection = bot._send.call_args[0][1]

    required = _extract_required_form_from_handler_error(rejection, command)
    help_line = _help_line_from_text(_HELP_TEXT, command)

    assert required == help_line

async def test_cmd_phase_advances() -> None:
    """Phase 2c I.2: legacy 'cooling' alias canonicalises to the
    ExperimentPhase enum value 'cooldown' before being dispatched."""

    async def dispatch(command: dict) -> dict:
        if command == {"cmd": "experiment_status"}:
            return {
                "ok": True,
                "active_experiment": {"experiment_id": "exp-current"},
            }
        if command == {"cmd": "mutation_capabilities"}:
            return _capability_response()
        return {"ok": True}

    handler = AsyncMock(side_effect=dispatch)
    bot = _make_bot(command_handler=handler)
    await bot._handle_message(_tg_msg("/phase cooling exp-current"))
    assert handler.await_count == 3
    cmd = handler.await_args_list[2].args[0]
    assert cmd["cmd"] == "experiment_advance_phase"
    assert cmd["experiment_id"] == "exp-current"
    assert cmd["phase"] == "cooldown", "legacy 'cooling' must canonicalise to enum value 'cooldown'"
    assert cmd["protocol_major"] == 1
    assert cmd["mutation_capability"] == "cryodaq_mutation_v1"
    assert cmd["capability_token"] == "token-1"
    assert "expected_experiment_id" not in cmd
    assert "✅" in bot._send.call_args[0][1]


async def test_cmd_phase_invalid_returns_error() -> None:
    bot = _make_bot()
    await bot._handle_message(_tg_msg("/phase nonexistent_phase"))
    bot._send.assert_called_once()
    assert "❌" in bot._send.call_args[0][1]


@pytest.mark.parametrize(
    "discovery_response",
    [
        {"ok": True},
        {"ok": True, "compatibility_receipt": None},
        {
            "ok": True,
            "compatibility_receipt": {
                **_capability_response()["compatibility_receipt"],
                "unexpected": True,
            },
        },
        {
            "ok": True,
            "compatibility_receipt": {
                **_capability_response()["compatibility_receipt"],
                "server_protocol_major": 2,
            },
        },
        {
            "ok": True,
            "compatibility_receipt": {
                **_capability_response()["compatibility_receipt"],
                "capability_token": "",
            },
        },
    ],
)
async def test_mutation_discovery_refuses_missing_or_malformed_receipts(
    discovery_response: dict,
) -> None:
    handler = AsyncMock(return_value=discovery_response)
    bot = _make_bot(command_handler=handler)

    await bot._handle_message(_tg_msg("/log exp-1 запись"))

    handler.assert_awaited_once_with({"cmd": "mutation_capabilities"})
    assert bot._mutation_envelope is None
    assert "Подробности" in bot._send.await_args.args[1]


async def test_rotated_token_is_invalidated_without_automatic_mutation_replay() -> None:
    discoveries = iter(("token-old", "token-new"))
    commands: list[dict] = []

    async def dispatch(command: dict) -> dict:
        commands.append(command)
        if command == {"cmd": "mutation_capabilities"}:
            return _capability_response(next(discoveries))
        if command.get("capability_token") == "token-old":
            return {
                "ok": False,
                "error_code": "mutation_protocol_incompatible",
                "retry_safe": True,
            }
        return {"ok": True}

    bot = _make_bot(command_handler=dispatch)

    await bot._handle_message(_tg_msg("/log exp-1 first", message_id=91))

    assert len(commands) == 2
    assert [command["cmd"] for command in commands] == [
        "mutation_capabilities",
        "log_entry",
    ]
    assert bot._mutation_envelope is None

    await bot._handle_message(_tg_msg("/log exp-1 second", message_id=92))

    assert [command["cmd"] for command in commands] == [
        "mutation_capabilities",
        "log_entry",
        "mutation_capabilities",
        "log_entry",
    ]
    assert commands[-1]["capability_token"] == "token-new"
    assert commands[1]["request_id"] != commands[-1]["request_id"]


async def test_concurrent_mutations_share_one_capability_discovery() -> None:
    discovery_entered = asyncio.Event()
    release_discovery = asyncio.Event()
    commands: list[dict] = []

    async def dispatch(command: dict) -> dict:
        commands.append(command)
        if command == {"cmd": "mutation_capabilities"}:
            discovery_entered.set()
            await release_discovery.wait()
            return _capability_response("shared-token")
        return {"ok": True}

    bot = _make_bot(command_handler=dispatch)
    first = asyncio.create_task(bot._handle_message(_tg_msg("/log exp-1 first", message_id=101)))
    second = asyncio.create_task(bot._handle_message(_tg_msg("/log exp-2 second", message_id=102)))
    await asyncio.wait_for(discovery_entered.wait(), timeout=1)
    assert [command["cmd"] for command in commands] == ["mutation_capabilities"]
    release_discovery.set()
    await asyncio.gather(first, second)

    assert sum(command["cmd"] == "mutation_capabilities" for command in commands) == 1
    mutations = [command for command in commands if command["cmd"] == "log_entry"]
    assert len(mutations) == 2
    assert {command["capability_token"] for command in mutations} == {"shared-token"}
    assert len({command["request_id"] for command in mutations}) == 2


async def test_phase_refuses_to_discover_or_mutate_without_stable_experiment_id() -> None:
    handler = AsyncMock(return_value={"ok": True, "active_experiment": None})
    bot = _make_bot(command_handler=handler)

    await bot._handle_message(_tg_msg("/phase cooldown exp-claimed"))

    handler.assert_awaited_once_with({"cmd": "experiment_status"})
    assert bot._mutation_envelope is None
    assert "Подробности" in bot._send.await_args.args[1]


async def test_phase_refuses_mismatched_operator_identity_before_capability_discovery() -> None:
    handler = AsyncMock(
        return_value={
            "ok": True,
            "active_experiment": {"experiment_id": "exp-new"},
        }
    )
    bot = _make_bot(command_handler=handler)

    await bot._handle_message(_tg_msg("/phase cooldown exp-stale"))

    handler.assert_awaited_once_with({"cmd": "experiment_status"})
    assert bot._mutation_envelope is None
    assert "Подробности" in bot._send.await_args.args[1]


async def test_invalid_phase_with_exact_identity_never_dispatches() -> None:
    handler = AsyncMock(return_value={"ok": True})
    bot = _make_bot(command_handler=handler)

    await bot._handle_message(_tg_msg("/phase definitely-not-a-phase exp-A"))

    handler.assert_not_awaited()
    bot._send.assert_awaited_once()
    assert "\u274c" in bot._send.await_args.args[1]


async def test_cmd_phase_without_identity_is_rejected() -> None:
    handler = AsyncMock(return_value={"ok": True})
    bot = _make_bot(command_handler=handler)
    await bot._handle_message(_tg_msg("/phase cooling"))
    handler.assert_not_called()
    assert "experiment_id" in bot._send.call_args[0][1]


# ===========================================================================
async def test_cmd_log_without_identity_is_rejected() -> None:
    handler = AsyncMock(return_value={"ok": True})
    bot = _make_bot(command_handler=handler)
    await bot._handle_message(_tg_msg("/log запись"))
    handler.assert_not_called()
    assert "experiment_id" in bot._send.call_args[0][1]


# EscalationService tests
# ===========================================================================


class _TelegramResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def json(self) -> object:
        return json.loads(self._body)


class _TelegramResponseContext:
    def __init__(self, response: _TelegramResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _TelegramResponse:
        return self._response

    async def __aexit__(self, exc_type, exc_value, traceback) -> bool:
        return False


class _TelegramSession:
    def __init__(self, response: _TelegramResponse) -> None:
        self._response = response

    def post(self, url: str, *, json: dict) -> _TelegramResponseContext:
        return _TelegramResponseContext(self._response)


@pytest.mark.parametrize(
    ("body", "recorded_outcome"),
    [
        ("", "transport_accepted"),
        ('{"ok": true, "result": {"message_id": 42}}', "service_reported_delivered"),
    ],
)
async def test_delayed_send_records_telegram_confirmation_tier(
    caplog: pytest.LogCaptureFixture,
    body: str,
    recorded_outcome: str,
) -> None:
    """Escalation records a service confirmation separately from HTTP acceptance."""
    from cryodaq.notifications.escalation import EscalationService

    notifier = _notifier()

    async def get_200_session() -> _TelegramSession:
        return _TelegramSession(_TelegramResponse(200, body))

    notifier._get_session = get_200_session  # type: ignore[method-assign]
    service = EscalationService(notifier, {})

    with caplog.at_level(logging.INFO, logger="cryodaq.notifications.escalation"):
        await service._delayed_send(111, "Тест эскалации", 0)

    assert f"outcome={recorded_outcome}" in caplog.text


@pytest.mark.parametrize(
    ("body", "expected_outcome"),
    [
        ("", "transport_accepted"),
        ('{"ok": true, "result": {}}', "transport_accepted"),
        ('{"ok": true, "result": {"message_id": 42}}', "service_reported_delivered"),
    ],
)
async def test_send_message_distinguishes_transport_and_service_confirmation(body: str, expected_outcome: str) -> None:
    notifier = _notifier()

    async def get_200_session() -> _TelegramSession:
        return _TelegramSession(_TelegramResponse(200, body))

    notifier._get_session = get_200_session  # type: ignore[method-assign]

    assert await notifier.send_message(111, "Тест") == expected_outcome


async def test_transport_errors_record_failed_and_unknown_outcomes(caplog: pytest.LogCaptureFixture) -> None:
    """A rejected request and a transport exception remain distinct non-success records."""
    from cryodaq.notifications.escalation import EscalationService

    notifier = _notifier()
    service = EscalationService(notifier, {})

    async def get_non_200_session() -> _TelegramSession:
        return _TelegramSession(_TelegramResponse(500, "internal error"))

    async def raise_connection_error() -> _TelegramSession:
        raise ConnectionError("connection lost")

    notifier._get_session = get_non_200_session  # type: ignore[method-assign]
    with caplog.at_level(logging.INFO, logger="cryodaq.notifications.escalation"):
        await service._delayed_send(111, "Тест", 0)

    notifier._get_session = raise_connection_error  # type: ignore[method-assign]
    with caplog.at_level(logging.INFO, logger="cryodaq.notifications.escalation"):
        await service._delayed_send(111, "Тест", 0)

    assert "outcome=failed" in caplog.text
    assert "outcome=outcome_unknown" in caplog.text


async def test_escalation_chain_sends() -> None:
    """Both zero-delay escalation levels send their messages.

    Waits by gathering all pending tasks directly instead of a fixed sleep,
    so the test is deterministic and not flaky under slow CI.
    """
    from cryodaq.notifications.escalation import EscalationService

    notifier = MagicMock()
    notifier.send_message = AsyncMock(return_value="service_reported_delivered")

    config = {
        "escalation": [
            {"chat_id": 111, "delay_minutes": 0},
            {"chat_id": 222, "delay_minutes": 0},
        ]
    }
    svc = EscalationService(notifier, config)
    await svc.escalate("test_event", "Тест эскалации")

    # Await all pending tasks directly — no fixed sleep, deterministic completion.
    pending_tasks = list(svc._pending.values())
    assert len(pending_tasks) == 2, f"Expected 2 pending tasks, got {len(pending_tasks)}"
    await asyncio.gather(*pending_tasks, return_exceptions=True)

    assert notifier.send_message.call_count == 2
    called_ids = {call.args[0] for call in notifier.send_message.call_args_list}
    assert called_ids == {111, 222}


async def test_escalation_cancel_stops() -> None:
    """cancel() must cancel the pending task and remove it from _pending.

    The 60-minute delay means send_message would never fire within the test,
    so we cannot rely on absence of calls as proof. Instead we assert:
    1. After escalate(), _pending contains the task for the event.
    2. After cancel(), _pending no longer contains the key.
    3. The task itself reports cancelled (task.cancelled() is True).
    send_message is also expected not to be called (belt-and-suspenders).
    """
    from cryodaq.notifications.escalation import EscalationService

    notifier = MagicMock()
    notifier.send_message = AsyncMock()

    config = {
        "escalation": [
            {"chat_id": 111, "delay_minutes": 60},  # large delay — must be cancelled
        ]
    }
    svc = EscalationService(notifier, config)
    await svc.escalate("shift_missed", "Оператор не ответил")

    # Task must be registered immediately after escalate()
    pending_key = "shift_missed_111"
    assert pending_key in svc._pending, (
        f"Expected task key '{pending_key}' in _pending after escalate(), got keys: {list(svc._pending)}"
    )
    task_ref = svc._pending[pending_key]
    assert not task_ref.done(), "Task should be waiting (not done) before cancel()"

    await svc.cancel("shift_missed")

    # cancel() awaits the task cancellation — task must be done and cancelled
    assert task_ref.cancelled(), "Task must be in cancelled state after cancel()"
    # Key must be removed from _pending
    assert pending_key not in svc._pending, f"Key '{pending_key}' must be removed from _pending after cancel()"
    # Belt-and-suspenders: send_message must not have been called
    notifier.send_message.assert_not_called()
