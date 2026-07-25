"""Verify SecretStr masks repr/str + telegram modules use it (Phase 2b K.1)."""

from __future__ import annotations

import asyncio
import logging

from cryodaq.notifications._secrets import SecretStr


def test_secret_str_repr_hides_value():
    s = SecretStr("7701234567:AAEhBP0av8XyZabc-defGHIJ")
    assert "7701234567" not in repr(s)
    assert "AAEhBP0av8XyZabc" not in repr(s)
    assert "***" in repr(s)


def test_secret_str_str_hides_value():
    s = SecretStr("supersecret")
    assert str(s) == "***"
    assert "supersecret" not in str(s)


def test_secret_str_format_hides_value():
    s = SecretStr("leakmenot")
    formatted = f"token: {s}"
    assert "leakmenot" not in formatted
    assert "***" in formatted


def test_secret_str_get_secret_value():
    s = SecretStr("raw-token-123")
    assert s.get_secret_value() == "raw-token-123"


def test_secret_str_bool_and_eq():
    assert bool(SecretStr("x")) is True
    assert bool(SecretStr("")) is False
    assert SecretStr("a") == SecretStr("a")
    assert SecretStr("a") != SecretStr("b")


def _walk_plain_strings(obj, seen=None):
    """Recursively yield all plain string values stored in a cryodaq object.

    Security contract: a raw token must NOT appear as a plain ``str`` in any
    reachable location of the object graph.  A token wrapped in SecretStr is
    acceptable — SecretStr is explicitly excluded from recursion because its
    ``_value`` slot is the *intended* storage location (masked from repr/str).

    Coverage:
    - ``__dict__`` values (instance attributes)
    - ``__slots__`` attribute values on the class MRO
    - Nested ``list``/``tuple``/``set``/``frozenset`` elements
    - Nested ``dict`` values (not keys — keys are attribute names, not tokens)

    Recursion stops at:
    - Objects already visited (cycle guard via ``id``)
    - ``SecretStr`` instances (wrapping is correct by design)
    - Non-cryodaq objects (Mocks, stdlib, third-party) to avoid false
      positives from test infrastructure
    """
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return
    seen.add(obj_id)

    # Stop at SecretStr — that IS the correct wrapper; do not unwrap it.
    if isinstance(obj, SecretStr):
        return

    # Only recurse into cryodaq-owned objects; stop at Mocks / stdlib / etc.
    mod = getattr(type(obj), "__module__", "") or ""
    if not mod.startswith("cryodaq."):
        return

    # Gather all attribute values from __dict__ and __slots__
    attr_values: list = []

    try:
        d = object.__getattribute__(obj, "__dict__")
        attr_values.extend(d.values())
    except AttributeError:
        pass

    for cls in type(obj).__mro__:
        for slot in getattr(cls, "__slots__", ()):
            # Skip SecretStr's own _value slot — already guarded above
            try:
                attr_values.append(getattr(obj, slot))
            except AttributeError:
                pass

    for v in attr_values:
        if isinstance(v, str):
            yield v
        elif isinstance(v, SecretStr):
            pass  # correct storage — do not unwrap
        elif isinstance(v, (list, tuple, set, frozenset)):
            for item in v:
                if isinstance(item, str):
                    yield item
                else:
                    yield from _walk_plain_strings(item, seen)
        elif isinstance(v, dict):
            for item in v.values():
                if isinstance(item, str):
                    yield item
                else:
                    yield from _walk_plain_strings(item, seen)
        else:
            yield from _walk_plain_strings(v, seen)


_SENTINEL = "SENTINEL_TOK_9f3a"


def test_telegram_notifier_no_plain_token_in_attrs():
    """TelegramNotifier must NOT store the raw token in any plain attribute.

    Walks __dict__ values AND __slots__ attributes recursively (cryodaq objects
    only; stops at SecretStr so the correct wrapper is not unwrapped).
    Also asserts that _bot_token is a SecretStr instance (not a bare str).
    """
    from cryodaq.notifications.telegram import TelegramNotifier

    notifier = TelegramNotifier(bot_token=_SENTINEL, chat_id=99999)

    # _bot_token must be wrapped in SecretStr, never stored as a bare str
    assert isinstance(notifier._bot_token, SecretStr), (
        f"TelegramNotifier._bot_token must be SecretStr, got {type(notifier._bot_token)}"
    )

    plain_values = list(_walk_plain_strings(notifier))
    assert _SENTINEL not in plain_values, (
        f"TelegramNotifier stores raw token in a plain attribute: {plain_values}"
    )

    # The token must materialise correctly when building the URL on demand.
    url = notifier._build_api_url("sendMessage")
    assert _SENTINEL in url, "_build_api_url() must include the token in the URL"


def test_telegram_command_bot_no_plain_token_in_attrs():
    """TelegramCommandBot must NOT store the raw token in any plain attribute.

    Walks __dict__ values AND __slots__ attributes recursively (cryodaq objects
    only; stops at SecretStr so the correct wrapper is not unwrapped).
    Also asserts that _bot_token is a SecretStr instance (not a bare str).
    """
    from cryodaq.notifications.telegram_commands import TelegramCommandBot

    bot = TelegramCommandBot(
        broker=None,
        alarm_engine=None,
        bot_token=_SENTINEL,
        allowed_chat_ids=[123],
        commands_enabled=True,
    )

    assert isinstance(bot._bot_token, SecretStr), (
        f"TelegramCommandBot._bot_token must be SecretStr, got {type(bot._bot_token)}"
    )

    plain_values = list(_walk_plain_strings(bot))
    assert _SENTINEL not in plain_values, (
        f"TelegramCommandBot stores raw token in a plain attribute: {plain_values}"
    )

    # Token must appear in the URL built on demand.
    api_url = bot._api  # property calls get_secret_value()
    assert _SENTINEL in api_url, "bot._api must materialise the token in the URL"


def test_periodic_reporter_no_plain_token_in_attrs():
    """PeriodicReporter must NOT store the raw token in any plain attribute.

    Walks __dict__ values AND __slots__ attributes recursively (cryodaq objects
    only; stops at SecretStr so the correct wrapper is not unwrapped).
    Also asserts that _bot_token is a SecretStr instance (not a bare str).
    """
    from unittest.mock import MagicMock

    from cryodaq.notifications.periodic_report import PeriodicReporter

    reporter = PeriodicReporter(
        broker=MagicMock(),
        alarm_engine=MagicMock(),
        bot_token=_SENTINEL,
        chat_id=99999,
    )

    assert isinstance(reporter._bot_token, SecretStr), (
        f"PeriodicReporter._bot_token must be SecretStr, got {type(reporter._bot_token)}"
    )

    plain_values = list(_walk_plain_strings(reporter))
    assert _SENTINEL not in plain_values, (
        f"PeriodicReporter stores raw token in a plain attribute: {plain_values}"
    )


def test_telegram_notifier_constructed_with_secret_str():
    from cryodaq.notifications.telegram import TelegramNotifier

    n = TelegramNotifier(
        bot_token="7701234567:AAEhBP0av8XyZabc-defGHIJklmnopqrstuv",
        chat_id=12345,
    )
    assert isinstance(n._bot_token, SecretStr)
    # The URL helper assembles the real URL only on demand.
    url = n._build_api_url("sendMessage")
    assert "AAEhBP0av8XyZabc-defGHIJklmnopqrstuv" in url
    # repr of the notifier itself never leaks the token.
    assert "AAEhBP0av8XyZabc" not in repr(n._bot_token)


class _PeriodicTransportProbe:
    def __init__(self) -> None:
        self.called = asyncio.Event()
        self.release = asyncio.Event()
        self.saw_secret_wrapper = False
        self.close_calls = 0

    async def send_photo(self, **kwargs: object):
        from cryodaq.agents.assistant.periodic_telegram import (
            TelegramDeliveryResult,
            TelegramOutcome,
        )

        self.saw_secret_wrapper = isinstance(kwargs.get("token"), SecretStr)
        self.called.set()
        await self.release.wait()
        return TelegramDeliveryResult(
            TelegramOutcome.UNKNOWN,
            None,
            None,
            None,
            "telegram_transport_unknown",
            "Telegram delivery outcome is unknown",
        )

    async def close(self) -> None:
        self.close_calls += 1


class _RawLogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


async def test_periodic_telegram_client_no_plain_token_in_attrs_before_after_send_close() -> None:
    from cryodaq.agents.assistant.periodic_telegram import PeriodicTelegramClient
    from cryodaq.periodic_config import PeriodicPngConfig

    token = "7701234567:SENTINEL_TOK_9f3a_ABCDEFGHIJKLMNOP"
    config = PeriodicPngConfig(
        enabled=True,
        interval_s=1_800,
        chart_window_s=7_200,
        include_channels=None,
        max_points_per_channel=20_000,
        max_total_points=100_000,
        max_input_bytes=8 * 1024 * 1024,
        render_timeout_s=120.0,
        max_render_attempts=5,
        max_delivery_attempts=5,
        backoff_base_s=30.0,
        backoff_cap_s=3_600.0,
        telegram_token=SecretStr(token),
        telegram_chat_id=-100123,
        telegram_timeout_s=10.0,
        telegram_verify_ssl=False,
        config_fingerprint="sha256:" + "a" * 64,
    )
    transport = _PeriodicTransportProbe()
    capture = _RawLogCapture()
    client_logger = logging.getLogger("cryodaq.agents.assistant.periodic_telegram")
    client_logger.addHandler(capture)
    try:
        client = PeriodicTelegramClient(config, _transport=transport)

        def assert_secret_absent() -> None:
            assert isinstance(client._token, SecretStr)
            assert token not in list(_walk_plain_strings(client))
            assert token not in repr(client)

        assert_secret_absent()
        send = asyncio.create_task(client.send_photo(_minimal_png(), "periodic report"))
        await transport.called.wait()
        assert_secret_absent()
        assert transport.saw_secret_wrapper is True
        transport.release.set()
        result = await send
        assert_secret_absent()
        assert token not in repr(result)
        await client.close()
        assert_secret_absent()
        assert transport.close_calls == 1
    finally:
        client_logger.removeHandler(capture)

    assert capture.records
    for record in capture.records:
        assert token not in str(record.msg)
        assert token not in repr(record.args)
        assert token not in record.getMessage()


def _minimal_png() -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 640, 480, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", b"data") + chunk(b"IEND", b"")
