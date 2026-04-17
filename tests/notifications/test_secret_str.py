"""Verify SecretStr masks repr/str + telegram modules use it (Phase 2b K.1)."""

from __future__ import annotations

import inspect

import pytest

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


def test_telegram_notifier_no_plain_url_attribute():
    """TelegramNotifier must NOT store a plain-string _api_url containing the token."""
    from cryodaq.notifications import telegram

    src = inspect.getsource(telegram)
    if "self._api_url = f" in src:
        pytest.fail(
            "TelegramNotifier still stores _api_url as f-string with the token. "
            "Phase 2b K.1: must compute on demand via _build_api_url()."
        )


def test_telegram_command_bot_no_plain_api_attribute():
    """TelegramCommandBot must compute _api on demand from SecretStr."""
    from cryodaq.notifications import telegram_commands

    src = inspect.getsource(telegram_commands)
    # The old `self._api = f"https://..."` constant string is gone.
    assert 'self._api = f"https' not in src, (
        "TelegramCommandBot still stores plain f-string self._api"
    )
    # And the bot uses SecretStr.
    assert "SecretStr" in src


def test_periodic_report_no_plain_url_attribute():
    """PeriodicReporter must not store the URL with the token as an attr."""
    from cryodaq.notifications import periodic_report

    src = inspect.getsource(periodic_report)
    assert "self._api_url = f" not in src
    assert "SecretStr" in src


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
