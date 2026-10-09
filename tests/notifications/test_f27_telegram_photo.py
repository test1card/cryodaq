"""F27 Phase A tests — Telegram bot photo + callback handling.

Covers:
- _fetch_updates routes photo messages to photo handler
- _fetch_updates routes callback_query to _handle_callback
- New API methods: get_file_path, download_file, send_message_with_keyboard,
  edit_message, answer_callback
- _handle_callback routes photo: prefix to photo handler
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from cryodaq.notifications.telegram_commands import TelegramCommandBot


def _make_bot(*, photo_handler=None):
    bot = TelegramCommandBot(
        broker=None,
        alarm_engine=None,
        bot_token="token:TEST",
        allowed_chat_ids=[123],
        photo_handler=photo_handler,
    )
    return bot


def _make_fetch_session(updates: list) -> tuple:
    """Build a mock session that returns the given updates from getUpdates."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"ok": True, "result": updates})
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get.return_value = cm
    return session, mock_resp


# ---------------------------------------------------------------------------
# Photo routing in _fetch_updates
# ---------------------------------------------------------------------------


async def test_photo_routed_to_handler_when_allowed() -> None:
    handler = MagicMock()
    handler.handle_photo = AsyncMock()
    bot = _make_bot(photo_handler=handler)

    msg = {
        "chat": {"id": 123},
        "photo": [{"file_id": "abc", "file_size": 100}],
        "caption": "test",
    }
    update = {"update_id": 1, "message": msg}
    session, _ = _make_fetch_session([update])

    with patch.object(bot, "_get_session", new_callable=AsyncMock, return_value=session):
        await bot._fetch_updates()

    handler.handle_photo.assert_awaited_once_with(msg)


async def test_photo_dropped_when_chat_not_allowed() -> None:
    handler = MagicMock()
    handler.handle_photo = AsyncMock()
    bot = _make_bot(photo_handler=handler)

    msg = {"chat": {"id": 999}, "photo": [{"file_id": "abc", "file_size": 100}]}
    update = {"update_id": 1, "message": msg}
    session, _ = _make_fetch_session([update])

    with patch.object(bot, "_get_session", new_callable=AsyncMock, return_value=session):
        await bot._fetch_updates()

    handler.handle_photo.assert_not_awaited()


async def test_photo_dropped_when_no_handler() -> None:
    bot = _make_bot(photo_handler=None)
    msg = {"chat": {"id": 123}, "photo": [{"file_id": "abc", "file_size": 100}]}
    update = {"update_id": 1, "message": msg}
    session, _ = _make_fetch_session([update])

    with patch.object(bot, "_get_session", new_callable=AsyncMock, return_value=session):
        await bot._fetch_updates()  # should not raise


async def test_callback_query_routed_to_handle_callback() -> None:
    bot = _make_bot()
    cb = {
        "id": "cb1",
        "data": "photo:yes:abc123",
        "message": {"chat": {"id": 123}, "message_id": 5},
    }
    update = {"update_id": 1, "callback_query": cb}
    session, _ = _make_fetch_session([update])

    with patch.object(bot, "_handle_callback", new_callable=AsyncMock) as mock_cb, \
         patch.object(bot, "_get_session", new_callable=AsyncMock, return_value=session):
        await bot._fetch_updates()

    mock_cb.assert_awaited_once_with(cb)


# ---------------------------------------------------------------------------
# _handle_callback routing
# ---------------------------------------------------------------------------


async def test_handle_callback_routes_photo_to_handler() -> None:
    handler = MagicMock()
    handler.handle_callback = AsyncMock()
    bot = _make_bot(photo_handler=handler)

    cb = {"id": "cb1", "data": "photo:yes:abc", "message": {"chat": {"id": 123}}}

    with patch.object(bot, "answer_callback", new_callable=AsyncMock):
        await bot._handle_callback(cb)

    handler.handle_callback.assert_awaited_once_with(cb, "photo:yes:abc")


async def test_handle_callback_dropped_when_chat_not_allowed() -> None:
    handler = MagicMock()
    handler.handle_callback = AsyncMock()
    bot = _make_bot(photo_handler=handler)

    cb = {"id": "cb1", "data": "photo:yes:abc", "message": {"chat": {"id": 999}}}
    await bot._handle_callback(cb)

    handler.handle_callback.assert_not_awaited()


async def test_handle_callback_no_routing_for_non_photo_prefix() -> None:
    handler = MagicMock()
    handler.handle_callback = AsyncMock()
    bot = _make_bot(photo_handler=handler)

    cb = {"id": "cb1", "data": "other:data:xyz", "message": {"chat": {"id": 123}}}
    with patch.object(bot, "answer_callback", new_callable=AsyncMock):
        await bot._handle_callback(cb)

    handler.handle_callback.assert_not_awaited()


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


async def test_get_file_path_returns_path_on_success() -> None:
    bot = _make_bot()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "ok": True,
        "result": {"file_path": "photos/file.jpg"},
    })
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_resp)
    cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get.return_value = cm
    with patch.object(bot, "_get_session", return_value=session):
        result = await bot.get_file_path("file_id_abc")

    assert result == "photos/file.jpg"


async def test_get_file_path_returns_none_on_error() -> None:
    bot = _make_bot()
    mock_resp = MagicMock()
    mock_resp.status = 404
    mock_resp.json = AsyncMock(return_value={"ok": False})
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get.return_value = cm
    with patch.object(bot, "_get_session", return_value=session):
        result = await bot.get_file_path("bad_id")

    assert result is None


async def test_download_file_returns_bytes() -> None:
    bot = _make_bot()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read = AsyncMock(return_value=b"\xff\xd8\xff" + b"\x00" * 100)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get.return_value = cm
    with patch.object(bot, "_get_session", return_value=session):
        result = await bot.download_file("photos/file.jpg")

    assert result is not None
    assert isinstance(result, bytes)


async def test_download_file_returns_none_on_error() -> None:
    bot = _make_bot()
    mock_resp = MagicMock()
    mock_resp.status = 404
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get.return_value = cm
    with patch.object(bot, "_get_session", return_value=session):
        result = await bot.download_file("bad/path.jpg")

    assert result is None


async def test_send_message_with_keyboard_returns_message_id() -> None:
    bot = _make_bot()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"ok": True, "result": {"message_id": 42}})
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post.return_value = cm
    with patch.object(bot, "_get_session", return_value=session):
        result = await bot.send_message_with_keyboard(123, "pick one", [[]])

    assert result == 42


async def test_edit_message_calls_api() -> None:
    bot = _make_bot()
    mock_resp = MagicMock()
    mock_resp.status = 200
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post.return_value = cm
    with patch.object(bot, "_get_session", return_value=session):
        await bot.edit_message(123, 5, "updated text")

    session.post.assert_called_once()


async def test_answer_callback_calls_api() -> None:
    bot = _make_bot()
    mock_resp = MagicMock()
    mock_resp.status = 200
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post.return_value = cm
    with patch.object(bot, "_get_session", return_value=session):
        await bot.answer_callback("cb_id_123")

    session.post.assert_called_once()
