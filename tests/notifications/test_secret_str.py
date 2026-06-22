"""Verify SecretStr masks repr/str + telegram modules use it (Phase 2b K.1)."""

from __future__ import annotations

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


def _walk_attrs(obj, seen=None):
    """Recursively yield all string values reachable from obj.__dict__."""
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return
    seen.add(obj_id)
    try:
        d = object.__getattribute__(obj, "__dict__")
    except AttributeError:
        return
    for v in d.values():
        if isinstance(v, str):
            yield v
        elif isinstance(v, (list, tuple, set, frozenset)):
            for item in v:
                if isinstance(item, str):
                    yield item
                else:
                    yield from _walk_attrs(item, seen)
        elif isinstance(v, dict):
            for item in v.values():
                if isinstance(item, str):
                    yield item
                else:
                    yield from _walk_attrs(item, seen)
        elif hasattr(v, "__dict__"):
            yield from _walk_attrs(v, seen)


def test_telegram_notifier_no_plain_token_in_attrs():
    """TelegramNotifier must NOT store the raw token in any instance attribute.

    Runtime check: instantiate with a sentinel token, walk __dict__ recursively,
    assert the raw token string never appears as a plain string attribute.
    The token should only materialise inside _build_api_url() at call time.
    """
    from cryodaq.notifications.telegram import TelegramNotifier

    sentinel = "SENTINEL_TOKEN_12345"
    notifier = TelegramNotifier(bot_token=sentinel, chat_id=99999)

    # Walk all instance attributes: raw sentinel must not appear as plain str.
    # SecretStr wrapping is fine — its __str__/__repr__ mask it.
    plain_values = list(_walk_attrs(notifier))
    assert sentinel not in plain_values, (
        f"TelegramNotifier stores raw token in a plain attribute: {plain_values}"
    )

    # The token must materialise correctly when building the URL on demand.
    url = notifier._build_api_url("sendMessage")
    assert sentinel in url, "_build_api_url() must include the token in the URL"


def test_telegram_command_bot_no_plain_token_in_attrs():
    """TelegramCommandBot must NOT store the raw token in any instance attribute."""
    from cryodaq.notifications.telegram_commands import TelegramCommandBot

    sentinel = "SENTINEL_TOKEN_12345"
    bot = TelegramCommandBot(
        broker=None,
        alarm_engine=None,
        bot_token=sentinel,
        allowed_chat_ids=[123],
        commands_enabled=True,
    )

    plain_values = list(_walk_attrs(bot))
    assert sentinel not in plain_values, (
        f"TelegramCommandBot stores raw token in a plain attribute: {plain_values}"
    )

    # Token must appear in the URL built on demand.
    api_url = bot._api  # property calls get_secret_value()
    assert sentinel in api_url, "bot._api must materialise the token in the URL"


def test_periodic_reporter_no_plain_token_in_attrs():
    """PeriodicReporter must NOT store the raw token in any instance attribute."""
    from unittest.mock import MagicMock

    from cryodaq.notifications.periodic_report import PeriodicReporter

    sentinel = "SENTINEL_TOKEN_12345"
    reporter = PeriodicReporter(
        broker=MagicMock(),
        alarm_engine=MagicMock(),
        bot_token=sentinel,
        chat_id=99999,
    )

    plain_values = list(_walk_attrs(reporter))
    assert sentinel not in plain_values, (
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
