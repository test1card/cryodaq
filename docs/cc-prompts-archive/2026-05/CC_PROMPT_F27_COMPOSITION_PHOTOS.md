# F27 — Experiment composition photos via Telegram bot

> Operator photographs the experimental composition (sample mounting,
> sensor placement, cryostat layout) on phone, sends к Гемма bot,
> bot validates + attaches photo к active experiment, GUI ExperimentOverlay
> shows photos с метаданными, ArchivePanel shows photos в archived
> experiments.
>
> ARCHITECT REQUEST source: Vladimir 2026-05-01 post-v0.47.4.
> "встроить фото чтобы оператор мог прислать в бота и подтвердить
> фото композиции эксперимента конкретного и оно отображалось на
> странице эксперимента и в архиве."
>
> Severity: HIGH UX — currently photos live в operator's phone, не
> attached к scientific record. Composition photos critical для
> reproducibility и diagnostics ("how was sample mounted in
> experiment-042?").
>
> Effort: M (~600 LOC across 4 layers + 50 tests). Estimated 4-5
> hours including investigation.
>
> Target release: v0.48.0 (если ship before F-X) или v0.50.0 (если
> F-X/F-Y promoted ahead).

---

## 0. Scope

### 0.1 In-scope

1. Telegram bot accepts photo messages (existing handler ignores)
2. Confirmation flow: photo arrives → bot replies "Прикрепить к
   эксперименту «<title>»? [да/нет/другой]"
3. Photo persisted к experiment artifact_dir as JPEG/PNG
4. Artifact_index updated с category=composition_photo entries
5. GUI ExperimentOverlay shows photo thumbnails в new "Композиция"
   section
6. GUI ArchivePanel details view shows photo gallery для archived
   experiments
7. Photo metadata: timestamp, operator (Telegram username), caption
   (optional first 200 chars), file size, dimensions

### 0.2 Out of scope (defer)

- Photo annotations / drawing на фото (out of scope, separate
  F-task если нужно)
- Photo cropping / rotation в bot UI (operator handles на phone)
- Auto-classification by content (sample / sensor / cryostat) —
  operator manually tags via caption
- Web export gallery (operator opens folder в Finder/Explorer)
- OCR of labels на фото (future F-task)
- Video / animated GIF support (photo only — JPEG/PNG)

### 0.3 Constraints

- Vladimir directive 2026-05-01: architect не делает manually,
  spec → CC trigger → wait → ratify
- LATE BINDING preserved: photo metadata reads ChannelManager fresh
  если caption mentions channels
- NO file deletion (only stub or rename if photo replaced)
- Telegram file size limit: 10 MB photo, 20 MB document — clamp
  к 10 MB photo route
- macOS dev workflow с Amnezia VPN — verify_ssl config knob must
  survive (см. §1.1)

---

## 1. CRITICAL — DO NOT REGRESS BASELINE (mandatory pre-flight)

### 1.1 SSL invariant

```bash
grep -c "verify_ssl" \
  src/cryodaq/notifications/telegram.py \
  src/cryodaq/notifications/telegram_commands.py \
  src/cryodaq/engine.py
# MUST report ≥14 occurrences
```

If <14 — STOP, manual restore required, surface к architect.

### 1.2 No merge conflict markers

```bash
grep -rn "<<<<<<< Updated\|>>>>>>> Stashed\|======= " \
  src/cryodaq/ config/ tests/ 2>/dev/null | wc -l
# MUST be 0
```

### 1.3 Engine import

```bash
python -c "import cryodaq.engine"
# MUST exit 0
```

### 1.4 Test baseline

```bash
pytest tests/ --collect-only -q 2>&1 | tail -3
# Records collected count для drift tracking

pytest tests/ --tb=line -q 2>&1 | tail -5
# MUST end "≥2300 passed" (current baseline after v0.47.4)
```

### 1.5 ChannelManager LATE BINDING preserved

```bash
grep -n "channel_manager" src/cryodaq/agents/assistant/query/intent_classifier.py
# MUST show channel_manager parameter and per-call rebuild
```

If ANY pre-flight fails — STOP, surface к architect.

---

## 2. Architecture overview

### 2.1 Data flow

```
Phone camera → Telegram chat → bot.getUpdates (polling)
                                ↓
                         _fetch_updates picks up "photo" field
                                ↓
                         bot.getFile(file_id) → file_path
                                ↓
                         bot downloads bytes via /file/<token>/<path>
                                ↓
                         CompositionPhotoHandler.confirm_attach(...)
                                ↓
                         bot replies inline keyboard:
                         "Прикрепить к «expA»? [Да] [Нет] [Другой]"
                                ↓
                         operator taps callback button
                                ↓
                         ExperimentManager.attach_composition_photo(
                             experiment_id, bytes, caption, operator
                         )
                                ↓
                         photo saved к artifact_dir/composition/
                         artifact_index entry appended
                         experiment metadata.json updated
                                ↓
                         ZMQ event "experiment.photo_attached" published
                                ↓
                         GUI ExperimentOverlay re-renders (subscribed)
```

### 2.2 Storage layout

```
~/data/experiments/{experiment_id}/
├── metadata.json              # existing — gets composition_photos[] field
├── composition/               # NEW
│   ├── 20260501T140523_001.jpg
│   ├── 20260501T140523_001.json    # metadata sidecar
│   ├── 20260501T141812_002.jpg
│   └── 20260501T141812_002.json
├── plots/                     # existing
└── ... existing artifacts
```

Naming: `<ISO timestamp без separators>_<seq>.<ext>`. Sidecar JSON
contains:

```json
{
  "filename": "20260501T140523_001.jpg",
  "telegram_file_id": "AgACAgIAAxkBAAI...",
  "telegram_message_id": 12345,
  "telegram_chat_id": 123456789,
  "telegram_username": "vladimir",
  "caption": "Образец А, термопаста Apiezon N",
  "uploaded_at": "2026-05-01T14:05:23+00:00",
  "file_size_bytes": 1842341,
  "dimensions": {"width": 4032, "height": 3024},
  "mime_type": "image/jpeg",
  "experiment_id": "cc35331d8c89",
  "experiment_title": "Измерение образца #42",
  "phase_at_upload": "preparation",
  "channels_mentioned": ["Т7", "Т12"]
}
```

`channels_mentioned` extracted from caption via ChannelManager fresh
read (LATE BINDING pattern — pick up renames). Best-effort, не
required field.

### 2.3 artifact_index entry

Existing `_artifact_entry` schema:

```python
{
    "artifact_id": "composition_photo:operator:20260501T140523_001.jpg",
    "category": "composition_photo",
    "role": "operator_upload",
    "path": "/abs/path/to/composition/20260501T140523_001.jpg",
    "summary": {
        "uploaded_at": "2026-05-01T14:05:23+00:00",
        "telegram_username": "vladimir",
        "caption": "Образец А, термопаста Apiezon N",
        "file_size_bytes": 1842341,
        "dimensions": {"width": 4032, "height": 3024},
    }
}
```

ArchivePanel iterates `artifact_index` filtering `category="composition_photo"`
для gallery rendering.

---

## 3. Implementation phases

### 3.1 Phase A — Telegram bot photo handling (~150 LOC + 12 tests)

#### 3.1.1 Update _fetch_updates к recognize photos

`telegram_commands.py` — extend updates loop:

```python
for update in updates:
    self._last_update_id = max(self._last_update_id, update["update_id"])
    msg = update.get("message", {})
    
    # NEW: callback queries (button taps from inline keyboards)
    cb = update.get("callback_query")
    if cb is not None:
        await self._handle_callback(cb)
        continue
    
    text = msg.get("text", "")
    photo = msg.get("photo")  # NEW: list of PhotoSize objects
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id:
        continue
    
    if photo and self._photo_handler is not None:
        if self._is_chat_allowed(chat_id):
            await self._photo_handler.handle_photo(msg)
        continue
    
    if not text:
        continue
    # ... existing text/command logic ...
```

#### 3.1.2 Add Telegram getFile + download

`telegram_commands.py` — new methods:

```python
async def get_file_path(self, file_id: str) -> str | None:
    """Resolve Telegram file_id к downloadable path via getFile API."""
    session = await self._get_session()
    try:
        async with session.get(f"{self._api}/getFile", params={"file_id": file_id}) as resp:
            if resp.status != 200:
                logger.error("Telegram getFile %d", resp.status)
                return None
            data = await resp.json()
            if not data.get("ok"):
                return None
            return data["result"].get("file_path")
    except Exception as exc:
        logger.error("getFile error: %s", exc)
        return None

async def download_file(self, file_path: str) -> bytes | None:
    """Download file content от Telegram CDN."""
    token = self._bot_token.get_secret_value()
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    session = await self._get_session()
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                logger.error("Telegram download %d", resp.status)
                return None
            return await resp.read()
    except Exception as exc:
        logger.error("download error: %s", exc)
        return None

async def send_message_with_keyboard(
    self,
    chat_id: int,
    text: str,
    keyboard: list[list[dict]],
) -> int | None:
    """Send message с inline keyboard. Returns message_id или None."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": keyboard},
    }
    session = await self._get_session()
    try:
        async with session.post(f"{self._api}/sendMessage", json=payload) as resp:
            if resp.status != 200:
                logger.error("Telegram sendMessage with keyboard %d", resp.status)
                return None
            data = await resp.json()
            return data.get("result", {}).get("message_id")
    except Exception as exc:
        logger.error("sendMessage keyboard error: %s", exc)
        return None

async def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
    """Edit existing message (after callback button tap)."""
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    session = await self._get_session()
    try:
        async with session.post(f"{self._api}/editMessageText", json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error("Telegram editMessage %d: %s", resp.status, body[:200])
    except Exception as exc:
        logger.error("editMessage error: %s", exc)

async def answer_callback(self, callback_id: str, text: str = "") -> None:
    """Answer callback query (removes loading spinner на button)."""
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    session = await self._get_session()
    try:
        async with session.post(f"{self._api}/answerCallbackQuery", json=payload) as resp:
            if resp.status != 200:
                logger.warning("Telegram answerCallback %d", resp.status)
    except Exception as exc:
        logger.error("answerCallback error: %s", exc)
```

#### 3.1.3 Constructor accepts photo handler

```python
class TelegramCommandBot:
    def __init__(
        self,
        broker: DataBroker | None = None,
        alarm_engine: AlarmEngine | None = None,
        *,
        bot_token: str | SecretStr,
        allowed_chat_ids: list[int] | None = None,
        poll_interval_s: float = 2.0,
        command_handler: Callable[[dict], Awaitable[dict]] | None = None,
        commands_enabled: bool = True,
        query_agent: Any | None = None,
        photo_handler: Any | None = None,  # NEW
        verify_ssl: bool = True,
    ) -> None:
        ...
        self._photo_handler = photo_handler
```

#### 3.1.4 Callback query routing

```python
async def _handle_callback(self, cb: dict) -> None:
    """Route inline keyboard button taps."""
    callback_id = cb.get("id")
    data = cb.get("data", "")
    chat_id = cb.get("message", {}).get("chat", {}).get("id")
    
    if not callback_id or not chat_id:
        return
    if not self._is_chat_allowed(chat_id):
        return
    
    # Always acknowledge к remove loading spinner
    await self.answer_callback(callback_id)
    
    if self._photo_handler is not None and data.startswith("photo:"):
        await self._photo_handler.handle_callback(cb, data)
```

#### 3.1.5 Tests

```python
def test_fetch_updates_picks_up_photo_field():
def test_photo_routes_к_handler_when_chat_allowed():
def test_photo_dropped_when_chat_not_allowed():
def test_photo_dropped_when_no_handler_configured():
def test_callback_query_routed_к_photo_handler():
def test_callback_query_dropped_when_chat_not_allowed():
def test_get_file_path_handles_telegram_error():
def test_download_file_returns_bytes():
def test_download_file_handles_404():
def test_send_message_with_keyboard_returns_message_id():
def test_edit_message_after_callback():
def test_answer_callback_acknowledges():
```

### 3.2 Phase B — CompositionPhotoHandler (~200 LOC + 18 tests)

`src/cryodaq/notifications/composition_photo_handler.py` — new module.

#### 3.2.1 Pending-confirmation state machine

Operator workflow:
1. Operator sends photo + optional caption "Образец А термопаста"
2. Bot replies: "Получено фото. Прикрепить к эксперименту «expA»?
   [✅ Да] [❌ Нет] [Другой]"
3. Operator taps button:
   - **Да** → bot calls `attach_composition_photo(experiment_id=current, ...)`,
     replies "✅ Прикреплено к «expA»"
   - **Нет** → bot replies "❌ Отменено", deletes pending state
   - **Другой** → bot replies inline list of recent active+recent
     completed experiments, operator picks one

State между photo arrival и button tap:

```python
@dataclass
class PendingPhoto:
    file_id: str           # Telegram file_id для re-download если needed
    photo_bytes: bytes     # already downloaded на arrival
    caption: str
    chat_id: int
    operator_username: str
    arrived_at: datetime
    confirm_message_id: int  # для editMessageText after tap
    target_experiment_id: str | None  # populated when operator picks
```

`PendingPhoto` stored в `dict[str, PendingPhoto]` keyed by short
hash of file_id (used as callback_data key для button taps).

State expires after 30 minutes — cleanup loop drops stale entries.

#### 3.2.2 Module skeleton

```python
"""F27 — Composition photo handler для Telegram bot.

Operator sends photo of experimental composition. Bot confirms target
experiment via inline keyboard. Confirmed photo persisted к experiment
artifact_dir с metadata sidecar.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_PENDING_TTL_S = 1800  # 30 min
_CALLBACK_PREFIX = "photo:"


@dataclass
class PendingPhoto:
    file_id: str
    photo_bytes: bytes
    caption: str
    chat_id: int
    operator_username: str
    arrived_at: datetime
    confirm_message_id: int = 0
    target_experiment_id: str | None = None


class CompositionPhotoHandler:
    def __init__(
        self,
        bot,  # TelegramCommandBot
        experiment_manager,  # provides active + recent experiments + attach
        channel_manager=None,  # для caption channel mention extraction
    ) -> None:
        self._bot = bot
        self._em = experiment_manager
        self._channel_manager = channel_manager
        self._pending: dict[str, PendingPhoto] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None
    
    async def start(self) -> None:
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
    
    async def handle_photo(self, msg: dict) -> None:
        """Photo arrived. Download + confirm target experiment."""
        photos = msg.get("photo") or []
        if not photos:
            return
        # Telegram sends multiple sizes. Take largest.
        largest = max(photos, key=lambda p: p.get("file_size", 0))
        file_id = largest["file_id"]
        chat_id = msg["chat"]["id"]
        from_info = msg.get("from", {})
        username = from_info.get("username") or from_info.get("first_name", "telegram")
        caption = (msg.get("caption") or "").strip()
        
        # Download
        file_path = await self._bot.get_file_path(file_id)
        if file_path is None:
            await self._bot._send(chat_id, "❌ Не удалось получить файл")
            return
        photo_bytes = await self._bot.download_file(file_path)
        if photo_bytes is None:
            await self._bot._send(chat_id, "❌ Не удалось скачать фото")
            return
        
        # Determine target experiment
        active = await self._em.get_active_experiment()
        if active is None:
            await self._bot._send(
                chat_id,
                "ℹ️ Нет активного эксперимента. Фото не прикреплено.\n"
                "Создай эксперимент в GUI и отправь фото снова.",
            )
            return
        
        # Build confirmation prompt с inline keyboard
        cb_key = hashlib.sha1(f"{file_id}:{chat_id}".encode()).hexdigest()[:16]
        keyboard = [
            [
                {"text": "✅ Да", "callback_data": f"{_CALLBACK_PREFIX}yes:{cb_key}"},
                {"text": "❌ Нет", "callback_data": f"{_CALLBACK_PREFIX}no:{cb_key}"},
            ],
            [
                {"text": "Другой эксперимент", "callback_data": f"{_CALLBACK_PREFIX}other:{cb_key}"},
            ],
        ]
        title = active.title or active.name or active.experiment_id[:8]
        confirm_text = (
            f"📸 Получено фото от @{username}\n"
            f"Прикрепить к эксперименту <b>«{title}»</b>?"
        )
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
        """Process button tap from confirmation prompt."""
        # data format: "photo:yes:abc123" / "photo:no:abc123" / "photo:other:abc123" / "photo:pick:abc123:exp_id"
        parts = data.split(":")
        if len(parts) < 3:
            return
        action = parts[1]
        cb_key = parts[2]
        
        async with self._lock:
            pending = self._pending.get(cb_key)
        if pending is None:
            await self._bot.edit_message(
                cb["message"]["chat"]["id"],
                cb["message"]["message_id"],
                "⚠️ Запрос истёк. Отправь фото заново.",
            )
            return
        
        if action == "no":
            await self._bot.edit_message(
                pending.chat_id, pending.confirm_message_id,
                "❌ Отменено."
            )
            async with self._lock:
                self._pending.pop(cb_key, None)
            return
        
        if action == "other":
            recent = await self._em.recent_experiments(limit=5)
            if not recent:
                await self._bot.edit_message(
                    pending.chat_id, pending.confirm_message_id,
                    "Нет доступных экспериментов."
                )
                async with self._lock:
                    self._pending.pop(cb_key, None)
                return
            keyboard = []
            for exp in recent:
                title = exp.title or exp.name or exp.experiment_id[:8]
                # callback_data limit 64 bytes — keep cb_key + exp_id short
                keyboard.append([{
                    "text": title,
                    "callback_data": f"{_CALLBACK_PREFIX}pick:{cb_key}:{exp.experiment_id[:12]}",
                }])
            await self._bot.edit_message(
                pending.chat_id, pending.confirm_message_id,
                "Выбери эксперимент:"
            )
            # Send new keyboard message (editMessageText doesn't update keyboard)
            # OR use editMessageReplyMarkup (cleaner)
            # Implementation detail — surface to architect if blocked
            return
        
        if action == "pick" and len(parts) >= 4:
            exp_id_short = parts[3]
            # resolve full experiment_id from short prefix
            recent = await self._em.recent_experiments(limit=20)
            matched = next((e for e in recent if e.experiment_id.startswith(exp_id_short)), None)
            if matched is None:
                await self._bot.edit_message(
                    pending.chat_id, pending.confirm_message_id,
                    "❌ Эксперимент не найден."
                )
                async with self._lock:
                    self._pending.pop(cb_key, None)
                return
            pending.target_experiment_id = matched.experiment_id
            action = "yes"  # fall through к attach
        
        if action == "yes" and pending.target_experiment_id:
            channels_mentioned = self._extract_channels(pending.caption)
            try:
                result = await self._em.attach_composition_photo(
                    experiment_id=pending.target_experiment_id,
                    photo_bytes=pending.photo_bytes,
                    caption=pending.caption,
                    operator_username=pending.operator_username,
                    file_id=pending.file_id,
                    channels_mentioned=channels_mentioned,
                )
                exp = await self._em.get_experiment(pending.target_experiment_id)
                title = exp.title or exp.name or exp.experiment_id[:8]
                await self._bot.edit_message(
                    pending.chat_id, pending.confirm_message_id,
                    f"✅ Прикреплено к «{title}»\n"
                    f"Файл: {result.get('filename', '?')}"
                )
            except Exception as exc:
                logger.error("attach photo failed: %s", exc, exc_info=True)
                await self._bot.edit_message(
                    pending.chat_id, pending.confirm_message_id,
                    f"❌ Не удалось прикрепить: {exc}"
                )
            async with self._lock:
                self._pending.pop(cb_key, None)
    
    def _extract_channels(self, caption: str) -> list[str]:
        """Find channel IDs mentioned в caption.
        
        LATE BINDING: reads ChannelManager fresh per call. Picks up
        renames done via GUI mid-campaign.
        """
        if not caption or self._channel_manager is None:
            return []
        all_ids = self._channel_manager.get_all()
        mentioned = []
        # Match Cyrillic Т<digits> tokens
        import re
        for token in re.findall(r"Т\d+", caption):
            if token in all_ids:
                mentioned.append(token)
        # Also try display name substring match
        for ch_id in all_ids:
            display = self._channel_manager.get_display_name(ch_id)
            # Skip Cyrillic Т<digit> prefix in display name
            name_part = display.split(" ", 1)[1] if " " in display else display
            if len(name_part) >= 4 and name_part.lower() in caption.lower():
                if ch_id not in mentioned:
                    mentioned.append(ch_id)
        return mentioned
    
    async def _cleanup_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(300)  # check every 5 min
                async with self._lock:
                    now = datetime.now(UTC)
                    expired = [
                        k for k, p in self._pending.items()
                        if (now - p.arrived_at).total_seconds() > _PENDING_TTL_S
                    ]
                    for k in expired:
                        self._pending.pop(k, None)
                if expired:
                    logger.info("Expired %d pending photos", len(expired))
        except asyncio.CancelledError:
            return
```

#### 3.2.2 Tests (~18)

```python
def test_handle_photo_picks_largest_size():
def test_handle_photo_downloads_bytes():
def test_handle_photo_no_active_experiment_replies_error():
def test_handle_photo_creates_pending_entry():
def test_callback_yes_attaches_к_active_experiment():
def test_callback_no_cancels_and_drops_pending():
def test_callback_other_lists_recent_experiments():
def test_callback_pick_resolves_short_id_to_full():
def test_callback_expired_pending_replies_error():
def test_extract_channels_finds_cyrillic_t_tokens():
def test_extract_channels_finds_display_name_substring():
def test_extract_channels_late_binding_reflects_renames():
def test_extract_channels_empty_caption():
def test_extract_channels_no_channel_manager():
def test_pending_cleanup_after_30min():
def test_concurrent_photos_independent_pending_keys():
def test_callback_unknown_action_handled_gracefully():
def test_attach_failure_replies_к_operator():
```

### 3.3 Phase C — ExperimentManager attach API (~120 LOC + 12 tests)

`src/cryodaq/core/experiment.py` (или dedicated photo manager):

```python
async def attach_composition_photo(
    self,
    experiment_id: str,
    photo_bytes: bytes,
    *,
    caption: str = "",
    operator_username: str = "",
    file_id: str = "",
    channels_mentioned: list[str] | None = None,
    mime_type: str = "image/jpeg",
) -> dict:
    """Persist photo к experiment artifact_dir + update artifact_index.
    
    Returns metadata dict с filename + path для confirmation message.
    """
    info = self._registry.get(experiment_id)
    if info is None:
        raise ValueError(f"Experiment not found: {experiment_id}")
    if info.artifact_dir is None:
        raise ValueError(f"Experiment {experiment_id} has no artifact_dir")
    
    composition_dir = info.artifact_dir / "composition"
    composition_dir.mkdir(parents=True, exist_ok=True)
    
    # Filename: ISO timestamp без separators + sequence
    now = datetime.now(UTC)
    ts_str = now.strftime("%Y%m%dT%H%M%S")
    existing_count = len(list(composition_dir.glob("*.jpg"))) + len(list(composition_dir.glob("*.png")))
    seq = existing_count + 1
    ext = "jpg" if "jpeg" in mime_type else "png"
    filename = f"{ts_str}_{seq:03d}.{ext}"
    photo_path = composition_dir / filename
    sidecar_path = composition_dir / f"{photo_path.stem}.json"
    
    # Validate image dimensions (reject oversized или corrupt)
    dimensions = self._validate_photo(photo_bytes, mime_type)
    if dimensions is None:
        raise ValueError("Invalid or corrupt photo data")
    
    # Atomic write photo
    from cryodaq.core.atomic_write import atomic_write_bytes
    atomic_write_bytes(photo_path, photo_bytes)
    
    # Determine current phase
    state = self.get_state()
    phase_at_upload = state.current_phase if state else None
    
    # Sidecar metadata
    metadata = {
        "filename": filename,
        "telegram_file_id": file_id,
        "telegram_username": operator_username,
        "caption": caption[:500] if caption else "",
        "uploaded_at": now.isoformat(),
        "file_size_bytes": len(photo_bytes),
        "dimensions": dimensions,
        "mime_type": mime_type,
        "experiment_id": experiment_id,
        "experiment_title": info.title or info.name,
        "phase_at_upload": str(phase_at_upload) if phase_at_upload else None,
        "channels_mentioned": list(channels_mentioned or []),
    }
    from cryodaq.core.atomic_write import atomic_write_text
    import json
    atomic_write_text(sidecar_path, json.dumps(metadata, ensure_ascii=False, indent=2))
    
    # Persist artifact_index entry to registry
    artifact_entry = {
        "artifact_id": f"composition_photo:operator:{filename}",
        "category": "composition_photo",
        "role": "operator_upload",
        "path": str(photo_path),
        "summary": {
            "uploaded_at": metadata["uploaded_at"],
            "telegram_username": operator_username,
            "caption": metadata["caption"],
            "file_size_bytes": len(photo_bytes),
            "dimensions": dimensions,
            "phase_at_upload": metadata["phase_at_upload"],
            "channels_mentioned": metadata["channels_mentioned"],
        },
    }
    
    # Append к existing artifact_index inside metadata.json
    self._append_artifact_to_metadata(experiment_id, artifact_entry)
    
    # Publish event for GUI subscribers
    if self._event_bus is not None:
        await self._event_bus.publish("experiment.photo_attached", {
            "experiment_id": experiment_id,
            "filename": filename,
            "path": str(photo_path),
        })
    
    return {
        "filename": filename,
        "path": str(photo_path),
        "metadata": metadata,
    }


def _validate_photo(self, data: bytes, mime_type: str) -> dict | None:
    """Verify photo bytes parseable + extract dimensions. Returns None on invalid."""
    try:
        from PIL import Image
        from io import BytesIO
        img = Image.open(BytesIO(data))
        return {"width": img.width, "height": img.height}
    except Exception as exc:
        logger.error("Photo validation failed: %s", exc)
        return None


def _append_artifact_to_metadata(self, experiment_id: str, entry: dict) -> None:
    """Update metadata.json artifact_index field atomically."""
    info = self._registry.get(experiment_id)
    if info is None or info.metadata_path is None:
        return
    import json
    from cryodaq.core.atomic_write import atomic_write_text
    
    if info.metadata_path.exists():
        with info.metadata_path.open(encoding="utf-8") as f:
            metadata = json.load(f)
    else:
        metadata = info.to_payload()
    
    composition_photos = metadata.setdefault("composition_photos", [])
    composition_photos.append(entry)
    
    atomic_write_text(
        info.metadata_path,
        json.dumps(metadata, ensure_ascii=False, indent=2),
    )


async def recent_experiments(self, *, limit: int = 5) -> list[ExperimentInfo]:
    """Return recent experiments (active + recently completed)."""
    all_exps = self._registry.list_all()
    sorted_exps = sorted(all_exps, key=lambda e: e.start_time, reverse=True)
    return sorted_exps[:limit]


async def get_active_experiment(self) -> ExperimentInfo | None:
    """Return current active experiment или None."""
    state = self.get_state()
    if state is None or state.active_experiment_id is None:
        return None
    return self._registry.get(state.active_experiment_id)


async def get_experiment(self, experiment_id: str) -> ExperimentInfo | None:
    return self._registry.get(experiment_id)
```

#### 3.3.1 Tests (~12)

```python
def test_attach_creates_composition_dir():
def test_attach_writes_photo_atomically():
def test_attach_writes_sidecar_metadata():
def test_attach_sequence_number_increments():
def test_attach_rejects_corrupt_image():
def test_attach_appends_artifact_index_к_metadata():
def test_attach_publishes_zmq_event():
def test_attach_uses_jpg_extension_for_jpeg():
def test_attach_uses_png_extension_for_png():
def test_attach_clamps_caption_to_500_chars():
def test_attach_records_phase_at_upload():
def test_attach_records_channels_mentioned():
```

### 3.4 Phase D — GUI ExperimentOverlay rendering (~150 LOC + tests)

`src/cryodaq/gui/shell/experiment_overlay.py` — add "Композиция"
section.

UI layout:
- Below existing experiment fields, before phase timeline
- Section header: "Композиция эксперимента"
- Grid of photo thumbnails (max 4 columns, 120px height)
- Click thumbnail → opens modal с full-size + caption + metadata
- Empty state: "Фото пока не прикреплены. Отправь в Telegram бота."

Subscribe к ZMQ events `experiment.photo_attached` для re-render.

```python
class CompositionPhotosWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._photos: list[dict] = []
        self._build_ui()
    
    def set_photos(self, artifact_index: list[dict]) -> None:
        composition = [a for a in artifact_index if a.get("category") == "composition_photo"]
        self._photos = composition
        self._refresh()
    
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        
        header = QLabel("Композиция эксперимента")
        header.setObjectName("section-header")
        layout.addWidget(header)
        
        self._grid_container = QWidget()
        self._grid = QGridLayout(self._grid_container)
        self._grid.setSpacing(8)
        layout.addWidget(self._grid_container)
        
        self._empty_label = QLabel("Фото пока не прикреплены. Отправь в Telegram бота.")
        self._empty_label.setObjectName("empty-state")
        layout.addWidget(self._empty_label)
    
    def _refresh(self) -> None:
        # Clear grid
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not self._photos:
            self._grid_container.setVisible(False)
            self._empty_label.setVisible(True)
            return
        
        self._grid_container.setVisible(True)
        self._empty_label.setVisible(False)
        
        for i, photo in enumerate(self._photos):
            thumb = self._build_thumbnail(photo)
            self._grid.addWidget(thumb, i // 4, i % 4)
    
    def _build_thumbnail(self, photo: dict) -> QWidget:
        widget = QFrame()
        widget.setFrameShape(QFrame.Shape.Box)
        layout = QVBoxLayout(widget)
        
        # Lazy-load thumbnail (Qt scales к fit)
        from PySide6.QtGui import QPixmap
        pixmap = QPixmap(photo["path"])
        scaled = pixmap.scaled(
            120, 120,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        thumb_label = QLabel()
        thumb_label.setPixmap(scaled)
        thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
        thumb_label.mousePressEvent = lambda e: self._open_full(photo)
        layout.addWidget(thumb_label)
        
        # Caption preview (first 40 chars)
        caption = photo.get("summary", {}).get("caption", "")
        if caption:
            cap_label = QLabel(caption[:40] + ("..." if len(caption) > 40 else ""))
            cap_label.setObjectName("caption-preview")
            cap_label.setWordWrap(True)
            layout.addWidget(cap_label)
        
        return widget
    
    def _open_full(self, photo: dict) -> None:
        dialog = PhotoDetailsDialog(photo, self)
        dialog.exec()


class PhotoDetailsDialog(QDialog):
    """Full-size view с metadata."""
    def __init__(self, photo: dict, parent=None):
        super().__init__(parent)
        self._photo = photo
        self.setWindowTitle("Композиция эксперимента")
        self._build_ui()
    
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        
        # Image
        from PySide6.QtGui import QPixmap
        pixmap = QPixmap(self._photo["path"])
        scaled = pixmap.scaledToHeight(600, Qt.TransformationMode.SmoothTransformation)
        image_label = QLabel()
        image_label.setPixmap(scaled)
        layout.addWidget(image_label)
        
        # Metadata
        summary = self._photo.get("summary", {})
        meta_text = (
            f"Загружено: {summary.get('uploaded_at', '?')}\n"
            f"Оператор: @{summary.get('telegram_username', '?')}\n"
            f"Фаза: {summary.get('phase_at_upload', '?')}\n"
            f"Каналы: {', '.join(summary.get('channels_mentioned', []))}\n"
            f"Caption: {summary.get('caption', '')}"
        )
        meta_label = QLabel(meta_text)
        meta_label.setWordWrap(True)
        layout.addWidget(meta_label)
        
        # Open in finder button
        open_btn = QPushButton("Открыть в Finder")
        open_btn.clicked.connect(lambda: self._open_in_finder())
        layout.addWidget(open_btn)
    
    def _open_in_finder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        path = Path(self._photo["path"]).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
```

Tests focus на rendering logic (Qt Test framework):
- Empty state shown when no photos
- Grid populated when photos present
- Thumbnail click opens dialog
- ZMQ event triggers refresh

### 3.5 Phase E — ArchivePanel gallery (~80 LOC + tests)

ArchivePanel details view existing — extend к show composition gallery
when archived experiment selected.

Reuse `CompositionPhotosWidget` от Phase D. Read photos from
`archive_entry.artifact_index` filtered к `category="composition_photo"`.

### 3.6 Phase F — Engine wiring (~30 LOC)

`engine.py` — create CompositionPhotoHandler, wire к bot:

```python
# After experiment_manager constructed
from cryodaq.notifications.composition_photo_handler import CompositionPhotoHandler
from cryodaq.core.channel_manager import get_channel_manager

photo_handler = CompositionPhotoHandler(
    bot=telegram_bot,
    experiment_manager=experiment_manager,
    channel_manager=get_channel_manager(),
)
await photo_handler.start()
telegram_bot._photo_handler = photo_handler  # OR pass via constructor
```

Cleanup на engine shutdown:
```python
await photo_handler.stop()
```

---

## 4. Smoke testing (manual, Vladimir с phone)

After engine restart с v0.48.x:

1. **Active experiment + photo:**
   - Create experiment в GUI ("Тест композиции")
   - Send photo + caption "Образец А, Apiezon N на Т7"
   - Bot replies с inline keyboard
   - Tap "✅ Да"
   - Bot: "✅ Прикреплено к «Тест композиции»"
   - GUI ExperimentOverlay shows thumbnail under "Композиция эксперимента"

2. **Click thumbnail:**
   - Full-size dialog opens
   - Caption visible
   - "Channels mentioned" shows ["Т7"]
   - "Open in Finder" reveals file

3. **No active experiment:**
   - Finalize current experiment
   - Send photo
   - Bot: "ℹ️ Нет активного эксперимента..."
   - No pending state created

4. **Decline:**
   - Active experiment present
   - Send photo, tap "❌ Нет"
   - Bot: "❌ Отменено"
   - No file persisted

5. **Other experiment:**
   - Active experiment is "Тест1"
   - Send photo, tap "Другой"
   - List of recent experiments shown
   - Tap "Тест-Предыдущий"
   - Bot: "✅ Прикреплено к «Тест-Предыдущий»"
   - GUI ArchivePanel showing that experiment displays photo

6. **Mid-session rename test (LATE BINDING):**
   - Active experiment present
   - Rename Т12 "Азотная плита" → "Cold finger" via GUI ChannelEditor
   - Send photo + caption "На cold finger"
   - Tap "✅ Да"
   - Sidecar JSON shows `channels_mentioned: ["Т12"]`
   - Confirms LATE BINDING channel resolution в caption parsing

7. **Stale pending:**
   - Send photo
   - Wait 35 min
   - Tap "Да"
   - Bot: "⚠️ Запрос истёк. Отправь фото заново."

8. **Concurrent photos:**
   - Send photo from chat A
   - Send photo from chat B (если allowed)
   - Both confirmation prompts independent
   - Tap "Да" on each — both attached correctly

9. **Archive view:**
   - Open ArchivePanel
   - Select archived experiment с composition photos
   - Gallery section shows thumbnails
   - Click thumbnail → full-size dialog

If ANY scenario fails — surface specific failure mode.

---

## 5. Acceptance criteria

1. ✅ All §1 pre-flight checks pass
2. ✅ Telegram bot accepts photo messages (existing handler unchanged for text)
3. ✅ Confirmation flow с inline keyboard works
4. ✅ Photo persisted к `<artifact_dir>/composition/<ts>_<seq>.<ext>`
5. ✅ Sidecar JSON metadata next к photo
6. ✅ artifact_index entry с category=composition_photo appended
7. ✅ ExperimentOverlay shows photos в "Композиция эксперимента" section
8. ✅ ArchivePanel shows photos в archived experiments
9. ✅ ZMQ event published — GUI auto-refreshes
10. ✅ Pending state expires after 30 min
11. ✅ Channel mentions extracted via LATE BINDING (renames respected)
12. ✅ Caption clamped к 500 chars (sanity)
13. ✅ Corrupt photos rejected gracefully
14. ✅ "Other experiment" picker works для 5 recent
15. ✅ NO regression: 2300+ baseline tests pass
16. ✅ ≥50 new tests across phases A-F
17. ✅ SSL invariant preserved (≥14 verify_ssl)
18. ✅ Multi-verifier audit (Codex + Gemini) clean

---

## 6. Hard stops

- §1 pre-flight fails → STOP, surface regression
- Telegram API behavior unexpected (photo field structure changes)
  → STOP, surface
- Image validation library (PIL/Pillow) not installed → add к
  pyproject.toml dependencies, surface к architect для approval
  before adding new dep
- artifact_dir non-writable → STOP, surface storage issue
- ZMQ event publish fails silently → add visible error в GUI
- Existing experiment.metadata.json schema migration risk → STOP,
  architect ratifies migration approach (likely additive only,
  safe)

---

## 7. Implementation order

1. Phase 1 — pre-flight (§1) STOP if fails
2. Phase A — Telegram bot photo + callback handling
3. Phase B — CompositionPhotoHandler с pending state
4. Phase C — ExperimentManager attach API
5. Phase D — GUI ExperimentOverlay rendering
6. Phase E — ArchivePanel gallery
7. Phase F — engine wiring
8. Final §1 regression check
9. Vladimir manual smoke (9 scenarios §4)
10. Multi-verifier audit (Codex + Gemini per ORCHESTRATION v1.5)
11. Tag v0.48.0 (или next available)

---

## 8. Open questions для architect ratify

1. **Image dependency:** PIL/Pillow добавляется к pyproject.toml.
   Currently не в deps. OK to add? Alt: skip dimension validation,
   trust Telegram bytes (риск corrupt sidecar).

2. **Photo storage location:** `<artifact_dir>/composition/` vs
   global `~/data/photos/<exp_id>/`. Architect picks. Spec defaults
   к artifact_dir (locality + cleanup-on-archive).

3. **Multiple photos per message:** Telegram allows photo album
   (multiple photos в one message). Spec assumes 1 photo per
   message. OK to defer multi-photo? Operator can send several
   sequentially — UX-wise acceptable.

4. **Annotation in caption:** caption "Образец А, термопаста Apiezon
   N" — keep verbatim, don't try к parse structurally. Future F-task
   if structured tagging needed.

5. **Captions с PII:** operator sends caption containing colleague
   name / personal info. Spec stores verbatim. Architect — should
   we sanitize? Defer (operator's own data, lab-internal, low risk).

6. **Photo overwrite policy:** sequence number prevents overwrite,
   but operator might re-upload corrected version. Spec keeps both
   (sequence increments). Future F-task если "replace this photo"
   button needed.

7. **Order in priority queue:** F27 already в roadmap as independent
   track. Where in v0.48+ sequence? Architect decides relative к
   F-X (channel taxonomy) и F-Y (diagnostic mode).

---

## 9. Begin

1. Phase 1 pre-flight
2. Surface §8 open questions к architect, await ratify
3. Phases A-F per §7 order
4. §4 smoke testing (Vladimir manual)
5. Multi-verifier audit
6. Tag

GO.
