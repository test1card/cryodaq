"""F27 — Composition photo handler for Telegram bot.

Operator sends photo of experimental composition (sample mounting, sensor
placement, cryostat layout). Bot confirms target experiment via inline
keyboard. Confirmed photo persisted to experiment artifact_dir with sidecar
metadata. ZMQ EventBus event published for GUI re-render.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryodaq.core.channel_manager import ChannelManager
    from cryodaq.core.event_bus import EventBus
    from cryodaq.core.experiment import ExperimentManager
    from cryodaq.notifications.telegram_commands import TelegramCommandBot

logger = logging.getLogger(__name__)

_PENDING_TTL_S = 1800  # 30 min
_CALLBACK_PREFIX = "photo:"
_MAX_CAPTION_LEN = 500


@dataclass
class PendingPhoto:
    """State held between photo arrival and operator confirmation."""

    file_id: str
    photo_bytes: bytes
    caption: str
    chat_id: int
    operator_username: str
    arrived_at: datetime
    confirm_message_id: int = 0
    target_experiment_id: str | None = None


class CompositionPhotoHandler:
    """Handle incoming composition photos from Telegram operators."""

    def __init__(
        self,
        bot: TelegramCommandBot,
        experiment_manager: ExperimentManager,
        *,
        channel_manager: ChannelManager | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._bot = bot
        self._em = experiment_manager
        self._channel_manager = channel_manager
        self._event_bus = event_bus
        self._pending: dict[str, PendingPhoto] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._cleanup_task = asyncio.create_task(
            self._cleanup_loop(), name="composition_photo_cleanup"
        )

    async def stop(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def handle_photo(self, msg: dict) -> None:
        """Photo arrived from operator. Download and present confirmation prompt."""
        photos = msg.get("photo") or []
        if not photos:
            return

        # Telegram sends multiple sizes — take largest
        largest = max(photos, key=lambda p: p.get("file_size", 0))
        file_id = largest["file_id"]
        chat_id = msg["chat"]["id"]
        from_info = msg.get("from", {})
        username = from_info.get("username") or from_info.get("first_name", "telegram")
        caption = (msg.get("caption") or "").strip()[:_MAX_CAPTION_LEN]

        # Download
        file_path = await self._bot.get_file_path(file_id)
        if file_path is None:
            await self._bot._send(chat_id, "❌ Не удалось получить файл от Telegram")
            return
        photo_bytes = await self._bot.download_file(file_path)
        if photo_bytes is None:
            await self._bot._send(chat_id, "❌ Не удалось скачать фото")
            return

        # Determine target experiment
        active = self._em.get_active_experiment()
        if active is None:
            await self._bot._send(
                chat_id,
                "ℹ️ Нет активного эксперимента. Фото не прикреплено.\n"
                "Создай эксперимент в GUI и отправь фото снова.",
            )
            return

        # Build confirmation inline keyboard
        import html as _html

        cb_key = hashlib.sha1(
            f"{file_id}:{chat_id}:{datetime.now(UTC).isoformat()}".encode()
        ).hexdigest()[:16]
        keyboard = [
            [
                {"text": "✅ Да", "callback_data": f"{_CALLBACK_PREFIX}yes:{cb_key}"},
                {"text": "❌ Нет", "callback_data": f"{_CALLBACK_PREFIX}no:{cb_key}"},
            ],
            [
                {
                    "text": "Другой эксперимент",
                    "callback_data": f"{_CALLBACK_PREFIX}other:{cb_key}",
                }
            ],
        ]
        title = _html.escape(active.title or active.name or active.experiment_id[:8])
        safe_user = _html.escape(username)
        confirm_text = (
            f"📸 Получено фото от @{safe_user}\n"
            f"Прикрепить к эксперименту <b>«{title}»</b>?"
        )
        if caption:
            confirm_text += f"\n<i>Подпись: {_html.escape(caption[:80])}</i>"

        message_id = await self._bot.send_message_with_keyboard(
            chat_id, confirm_text, keyboard
        )
        if message_id is None:
            return

        async with self._lock:
            self._pending[cb_key] = PendingPhoto(
                file_id=file_id,
                photo_bytes=photo_bytes,
                caption=caption,
                chat_id=chat_id,
                operator_username=username,
                arrived_at=datetime.now(UTC),
                confirm_message_id=message_id,
                target_experiment_id=active.experiment_id,
            )

    async def handle_callback(self, cb: dict, data: str) -> None:
        """Process inline keyboard tap from confirmation prompt.

        data format:
          photo:yes:<cb_key>
          photo:no:<cb_key>
          photo:other:<cb_key>
          photo:pick:<cb_key>:<exp_id_short>
        """
        parts = data.split(":")
        if len(parts) < 3:
            return
        action = parts[1]
        cb_key = parts[2]
        msg_chat_id = cb.get("message", {}).get("chat", {}).get("id")

        async with self._lock:
            pending = self._pending.get(cb_key)

        if pending is None:
            if msg_chat_id:
                await self._bot.edit_message(
                    msg_chat_id,
                    cb.get("message", {}).get("message_id", 0),
                    "⚠️ Запрос истёк. Отправь фото заново.",
                )
            return

        if action == "no":
            await self._bot.edit_message(
                pending.chat_id,
                pending.confirm_message_id,
                "❌ Отменено.",
            )
            async with self._lock:
                self._pending.pop(cb_key, None)
            return

        if action == "other":
            await self._show_experiment_picker(pending, cb_key)
            return

        if action == "pick" and len(parts) >= 4:
            exp_id_short = parts[3]
            # Resolve full experiment_id from short prefix via archive
            entries = self._em.list_archive_entries()
            matched = next(
                (e for e in entries if e.experiment_id.startswith(exp_id_short)), None
            )
            # Also check active experiment
            active = self._em.get_active_experiment()
            if active and active.experiment_id.startswith(exp_id_short):
                matched_id = active.experiment_id
            elif matched:
                matched_id = matched.experiment_id
            else:
                await self._bot.edit_message(
                    pending.chat_id,
                    pending.confirm_message_id,
                    "❌ Эксперимент не найден.",
                )
                async with self._lock:
                    self._pending.pop(cb_key, None)
                return
            async with self._lock:
                if cb_key in self._pending:
                    self._pending[cb_key].target_experiment_id = matched_id
            action = "yes"

        if action == "yes" and pending.target_experiment_id:
            await self._attach(pending, cb_key)

    async def _show_experiment_picker(
        self, pending: PendingPhoto, cb_key: str
    ) -> None:
        """Show recent experiment list for operator to pick alternative."""
        entries = self._em.list_archive_entries()
        recent = sorted(entries, key=lambda e: e.start_time, reverse=True)[:5]

        active = self._em.get_active_experiment()
        options: list[tuple[str, str]] = []
        if active:
            disp = active.title or active.name or active.experiment_id[:8]
            options.append((active.experiment_id, disp))
        for e in recent:
            if not any(opt[0] == e.experiment_id for opt in options):
                options.append(
                    (e.experiment_id, e.title or e.experiment_id[:8])
                )
        options = options[:5]

        if not options:
            await self._bot.edit_message(
                pending.chat_id,
                pending.confirm_message_id,
                "Нет доступных экспериментов.",
            )
            async with self._lock:
                self._pending.pop(cb_key, None)
            return

        keyboard = []
        for exp_id, title in options:
            # callback_data limit 64 bytes — use short prefix
            keyboard.append(
                [
                    {
                        "text": title[:40],
                        "callback_data": f"{_CALLBACK_PREFIX}pick:{cb_key}:{exp_id[:12]}",
                    }
                ]
            )
        await self._bot.edit_message(
            pending.chat_id,
            pending.confirm_message_id,
            "Выбери эксперимент для прикрепления:",
        )
        # Send new message with picker keyboard (edit doesn't update keyboard layout)
        await self._bot.send_message_with_keyboard(
            pending.chat_id, "Выбери эксперимент:", keyboard
        )

    async def _attach(self, pending: PendingPhoto, cb_key: str) -> None:
        """Persist photo and notify operator of result."""
        # Remove pending BEFORE any I/O — prevents duplicate attachment if Telegram
        # retransmits the callback (Telegram may retry unacknowledged callbacks).
        async with self._lock:
            self._pending.pop(cb_key, None)

        channels_mentioned = self._extract_channels(pending.caption)
        try:
            result = self._em.attach_composition_photo(
                experiment_id=pending.target_experiment_id,
                photo_bytes=pending.photo_bytes,
                caption=pending.caption,
                operator_username=pending.operator_username,
                file_id=pending.file_id,
                channels_mentioned=channels_mentioned,
            )
            # Determine display title
            active = self._em.get_active_experiment()
            if active and active.experiment_id == pending.target_experiment_id:
                disp = active.title or active.name or active.experiment_id[:8]
            else:
                entries = self._em.list_archive_entries()
                found = next(
                    (e for e in entries if e.experiment_id == pending.target_experiment_id),
                    None,
                )
                disp = (found.title if found else None) or pending.target_experiment_id[:8]

            await self._bot.edit_message(
                pending.chat_id,
                pending.confirm_message_id,
                f"✅ Прикреплено к «{disp}»\nФайл: {result['filename']}",
            )

            # Publish ZMQ event for GUI re-render
            if self._event_bus is not None:
                from datetime import UTC, datetime

                from cryodaq.core.event_bus import EngineEvent

                await self._event_bus.publish(
                    EngineEvent(
                        event_type="experiment.photo_attached",
                        timestamp=datetime.now(UTC),
                        payload={
                            "experiment_id": pending.target_experiment_id,
                            "filename": result["filename"],
                            "path": result["path"],
                        },
                        experiment_id=pending.target_experiment_id,
                    )
                )
        except Exception as exc:
            logger.error("attach_composition_photo failed: %s", exc, exc_info=True)
            await self._bot.edit_message(
                pending.chat_id,
                pending.confirm_message_id,
                f"❌ Не удалось прикрепить: {exc}",
            )

    def _extract_channels(self, caption: str) -> list[str]:
        """Find channel IDs mentioned in caption. LATE BINDING — reads ChannelManager fresh."""
        if not caption or self._channel_manager is None:
            return []
        import re

        mentioned: list[str] = []
        all_ids = set(self._channel_manager.get_all())

        # Match Cyrillic Т<digits> tokens directly
        for token in re.findall(r"Т\d+", caption):
            if token in all_ids and token not in mentioned:
                mentioned.append(token)

        # Substring match against display names (e.g. caption "cold finger" → Т12)
        for ch_id in all_ids:
            if ch_id in mentioned:
                continue
            display = self._channel_manager.get_display_name(ch_id)
            # Strip "Т<digits> " prefix to get the name part only
            name_part = display.split(" ", 1)[1] if " " in display else display
            if len(name_part) >= 4 and name_part.lower() in caption.lower():
                mentioned.append(ch_id)

        return mentioned

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup of expired pending photo confirmations."""
        try:
            while True:
                await asyncio.sleep(300)  # check every 5 min
                async with self._lock:
                    now = datetime.now(UTC)
                    expired = [
                        k
                        for k, p in self._pending.items()
                        if (now - p.arrived_at).total_seconds() > _PENDING_TTL_S
                    ]
                    for k in expired:
                        self._pending.pop(k, None)
                if expired:
                    logger.info("Состарилось %d ожидающих фото", len(expired))
        except asyncio.CancelledError:
            return
