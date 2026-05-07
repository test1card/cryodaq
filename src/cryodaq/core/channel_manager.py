"""Централизованное управление именами и видимостью каналов.

ChannelManager — единый источник отображаемых имён каналов для всех
панелей GUI. Загружает конфигурацию из config/channels.yaml, позволяет
редактировать и сохранять.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from cryodaq.paths import get_config_dir as _get_config_dir

logger = logging.getLogger(__name__)


class ChannelConfigError(RuntimeError):
    """Raised when channels.yaml cannot be loaded in a fail-closed manner."""


_DEFAULT_CONFIG = _get_config_dir() / "channels.yaml"

# Стандартные имена (если channels.yaml не существует)
_DEFAULT_CHANNELS: dict[str, dict[str, Any]] = {
    "Т1": {"name": "Криостат верх", "visible": True, "group": "криостат"},
    "Т2": {"name": "Криостат низ", "visible": True, "group": "криостат"},
    "Т3": {"name": "Радиатор 1", "visible": True, "group": "криостат"},
    "Т4": {"name": "Радиатор 2", "visible": True, "group": "криостат"},
    "Т5": {"name": "Экран 77К", "visible": True, "group": "криостат"},
    "Т6": {"name": "Экран 4К", "visible": True, "group": "криостат"},
    "Т7": {"name": "Детектор", "visible": True, "group": "криостат"},
    "Т8": {"name": "Калибровка", "visible": False, "group": "криостат"},
    "Т9": {"name": "Компрессор вход", "visible": True, "group": "компрессор"},
    "Т10": {"name": "Компрессор выход", "visible": True, "group": "компрессор"},
    "Т11": {"name": "Плита 1-й ступени", "visible": True, "group": "компрессор"},
    "Т12": {"name": "2-я ступень", "visible": True, "group": "компрессор"},
    "Т13": {"name": "Труба подачи", "visible": True, "group": "компрессор"},
    "Т14": {"name": "Труба возврата", "visible": True, "group": "компрессор"},
    "Т15": {"name": "Вакуумный кожух", "visible": True, "group": "компрессор"},
    "Т16": {"name": "Фланец", "visible": False, "group": "компрессор"},
    "Т17": {"name": "Зеркало 1", "visible": False, "group": "оптика"},
    "Т18": {"name": "Зеркало 2", "visible": False, "group": "оптика"},
    "Т19": {"name": "Подвес", "visible": False, "group": "оптика"},
    "Т20": {"name": "Рама", "visible": False, "group": "оптика"},
    "Т21": {"name": "Резерв 1", "visible": False, "group": "резерв"},
    "Т22": {"name": "Резерв 2", "visible": False, "group": "резерв"},
    "Т23": {"name": "Резерв 3", "visible": False, "group": "резерв"},
    "Т24": {"name": "Резерв 4", "visible": False, "group": "резерв"},
}


class ChannelManager:
    """Централизованное управление именами и видимостью каналов.

    Пример использования::

        mgr = ChannelManager()
        mgr.load()
        name = mgr.get_display_name("Т7")  # "Т7 Детектор"
        mgr.set_name("Т7", "Болометр")
        mgr.save()
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._channels: dict[str, dict[str, Any]] = {}
        # Hardware-pinned landmark channels (Т11/Т12) populated by the
        # engine from physical_alarms.yaml. Default empty so direct
        # ChannelManager() construction (tests, GUI standalone) keeps
        # working without an alarms file.
        self._landmarks: dict[str, dict[str, Any]] = {}
        self._config_path: Path = config_path or _DEFAULT_CONFIG
        self._callbacks: list[Any] = []
        self.load()

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def load(self, path: Path | None = None) -> None:
        """Загрузить конфигурацию каналов из YAML.

        Raises ChannelConfigError on missing file, malformed YAML, or
        missing 'channels' key. Fail-closed: no silent fallback to defaults.
        """
        if path is not None:
            self._config_path = path

        if not self._config_path.exists():
            raise ChannelConfigError(
                f"channels.yaml not found at {self._config_path} — refusing "
                f"to start without channel configuration"
            )
        try:
            with self._config_path.open(encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ChannelConfigError(
                f"channels.yaml at {self._config_path}: YAML parse error — {exc}"
            ) from exc

        if not isinstance(raw, dict):
            raise ChannelConfigError(
                f"channels.yaml at {self._config_path}: expected mapping, got {type(raw).__name__}"
            )
        channels = raw.get("channels")
        if not isinstance(channels, dict):
            raise ChannelConfigError(
                f"channels.yaml at {self._config_path}: missing or invalid 'channels' key"
            )
        self._channels = channels
        logger.info("Загружена конфигурация каналов: %s", self._config_path)

    def save(self, path: Path | None = None) -> None:
        """Сохранить конфигурацию каналов в YAML."""
        save_path = path or self._config_path
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with save_path.open("w", encoding="utf-8") as fh:
            yaml.dump(
                {"channels": self._channels},
                fh,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
        logger.info("Конфигурация каналов сохранена: %s", save_path)
        self._notify()

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def get_display_name(self, channel_id: str) -> str:
        """Получить отображаемое имя канала (\"Т7 Детектор\")."""
        # channel_id может быть "Т7 Детектор" (полное) или "Т7" (короткое)
        short_id = channel_id.split(" ")[0] if " " in channel_id else channel_id
        info = self._channels.get(short_id, {})
        name = info.get("name", "")
        return f"{short_id} {name}" if name else short_id

    def get_name(self, channel_id: str) -> str:
        """Получить пользовательское имя канала (\"Детектор\")."""
        short_id = channel_id.split(" ")[0] if " " in channel_id else channel_id
        return self._channels.get(short_id, {}).get("name", "")

    def set_name(self, channel_id: str, name: str) -> None:
        """Установить пользовательское имя канала."""
        short_id = channel_id.split(" ")[0] if " " in channel_id else channel_id
        if short_id not in self._channels:
            self._channels[short_id] = {}
        self._channels[short_id]["name"] = name

    def is_visible(self, channel_id: str) -> bool:
        """Проверить, видим ли канал."""
        short_id = channel_id.split(" ")[0] if " " in channel_id else channel_id
        return self._channels.get(short_id, {}).get("visible", True)

    def set_visible(self, channel_id: str, visible: bool) -> None:
        """Установить видимость канала."""
        short_id = channel_id.split(" ")[0] if " " in channel_id else channel_id
        if short_id not in self._channels:
            self._channels[short_id] = {}
        self._channels[short_id]["visible"] = visible

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Получить все каналы."""
        return dict(self._channels)

    def get_all_visible(self) -> list[str]:
        """Получить список видимых channel_id."""
        return [ch_id for ch_id, info in self._channels.items() if info.get("visible", True)]

    # ------------------------------------------------------------------
    # Landmarks (system-level, hardware-pinned channels — F-ChannelLandmarks)
    # ------------------------------------------------------------------

    def set_landmarks(self, landmarks: dict[str, dict[str, Any]]) -> None:
        """Install the hardware-pinned landmark map (e.g. Т11/Т12 with aliases).

        Engine populates this from ``config/physical_alarms.yaml`` at startup
        via :func:`cryodaq.core.physical_alarms_config.load_channel_landmarks`.
        Stored by reference (no deep copy) — callers must not mutate the
        passed dict after handing it over.
        """
        self._landmarks = dict(landmarks) if landmarks else {}

    def get_landmarks(self) -> dict[str, dict[str, Any]]:
        """Return the landmark map (channel_id → {role, physical, aliases}).

        Empty dict when no landmarks have been installed (default state),
        so consumers can call this unconditionally.
        """
        return dict(self._landmarks)

    def find_by_landmark_alias(self, name: str) -> str | None:
        """Resolve a landmark alias phrase (case-insensitive) to its channel ID.

        Returns the landmark channel_id when ``name`` appears in any landmark's
        ``aliases`` list (also matches the channel_id itself for the no-op case).
        Returns ``None`` when no landmark matches — callers fall through to
        experiment-level name matching.

        This is the runtime counterpart of the priority text in the classifier
        prompt: even if Gemma echoes the operator phrase verbatim instead of
        the canonical ID, the resolver hits landmarks before experiment names
        and returns the right channel.
        """
        if not self._landmarks:
            return None
        needle = name.strip().lower()
        if not needle:
            return None
        for ch_id, entry in self._landmarks.items():
            if needle == ch_id.strip().lower():
                return ch_id
            for alias in entry.get("aliases", []):
                if needle == str(alias).strip().lower():
                    return ch_id
        return None

    # Latin↔Cyrillic visually-confusable map (e.g. Latin T → Cyrillic Т)
    _LATIN_TO_CYRILLIC: dict[int, str] = str.maketrans(
        "TtAaKkMmOoPpHhEeBbCcXxYy",
        "ТтАаКкМмООРрНнЕеВвСсХхУу",
    )  # type: ignore[assignment]

    def find_by_name(self, name: str) -> str | None:
        """Find channel ID by display name (case-insensitive, partial match).

        Four-pass: exact ID/name match, substring, then Latin→Cyrillic normalization.
        Returns first hit or None.
        """
        name_lower = name.lower().strip()
        if not name_lower:
            return None

        # First pass: direct channel ID match, including Latin→Cyrillic fallback.
        normalized_id = name.strip().translate(self._LATIN_TO_CYRILLIC)
        if normalized_id in self._channels:
            return normalized_id

        # Second pass: exact name match
        for ch_id, ch_data in self._channels.items():
            if ch_data.get("name", "").lower() == name_lower:
                return ch_id

        # Third pass: substring match (e.g. "плита" matches "Азотная плита")
        for ch_id, ch_data in self._channels.items():
            ch_name = ch_data.get("name", "").lower()
            if ch_name and (name_lower in ch_name or ch_name in name_lower):
                return ch_id

        # Fourth pass: Latin→Cyrillic normalized retry (e.g. "T12" name → "Т12" name)
        norm = name_lower.translate(self._LATIN_TO_CYRILLIC)
        if norm != name_lower:
            for ch_id, ch_data in self._channels.items():
                ch_name = ch_data.get("name", "").lower()
                if ch_name == norm:
                    return ch_id
            for ch_id, ch_data in self._channels.items():
                ch_name = ch_data.get("name", "").lower()
                if ch_name and (norm in ch_name or ch_name in norm):
                    return ch_id

        return None

    def normalize_channel_id(self, ch_ref: str) -> str:
        """Normalize a channel ID reference: Latin→Cyrillic confusables.

        Used by QueryRouter to handle operator keyboard layout mismatch.
        'T12' (Latin T) → 'Т12' (Cyrillic Т).
        """
        return ch_ref.strip().translate(self._LATIN_TO_CYRILLIC)

    def get_cold_channels(self) -> list[str]:
        """Return list of channel IDs marked as cold (cryogenic).

        Channels without an explicit ``is_cold`` field default to True
        (sensible default for a cryogenic system).
        """
        return [ch_id for ch_id, info in self._channels.items() if info.get("is_cold", True)]

    def get_visible_cold_channels(self) -> list[str]:
        """Convenience: intersection of visible AND cold channels."""
        cold = set(self.get_cold_channels())
        return [ch for ch in self.get_all_visible() if ch in cold]

    def get_group(self, channel_id: str) -> str:
        """Получить группу канала (из channels.yaml)."""
        short_id = channel_id.split(" ")[0] if " " in channel_id else channel_id
        return self._channels.get(short_id, {}).get("group", "")

    # ------------------------------------------------------------------
    # F-X (v0.55.9) — channel taxonomy + phase-aware alarm bands
    # ------------------------------------------------------------------

    def get_thermal_zone(self, channel_id: str) -> str | None:
        """Return the channel's ``thermal_zone`` classification or None.

        F-X (v0.55.9): operator-classified physical context for each
        channel. One of ``cold_4k``, ``cold_77k``, ``cold_landmark``,
        ``intermediate``, ``warm_flange``, ``warm_reference``,
        ``disconnected_reserve``. Channels without the field return
        ``None`` (legacy migration path — alarm engine then falls back
        to existing ``alarms_v3.yaml`` rules).
        """
        short_id = channel_id.split(" ")[0] if " " in channel_id else channel_id
        zone = self._channels.get(short_id, {}).get("thermal_zone")
        return str(zone) if zone else None

    def get_alarm_band(
        self,
        channel_id: str,
        phase: str | None = None,
    ) -> tuple[float, float] | None:
        """Return the phase-aware ``[min_K, max_K]`` band for the channel.

        F-X (v0.55.9): resolution order:
        1. If ``phase`` is supplied AND the channel's ``alarm_band``
           dict has a key matching it, return that band.
        2. Else return the ``all_phases`` fallback if defined.
        3. Else return ``None``.

        ``None`` means the AlarmEngine should fall back to the existing
        ``alarms_v3.yaml`` threshold rules — F-X bands are additive,
        not a replacement.
        """
        short_id = channel_id.split(" ")[0] if " " in channel_id else channel_id
        info = self._channels.get(short_id, {})
        band_cfg = info.get("alarm_band")
        if not isinstance(band_cfg, dict):
            return None

        candidate = None
        if phase:
            phase_band = band_cfg.get(str(phase).lower())
            if isinstance(phase_band, list) and len(phase_band) == 2:
                candidate = phase_band
        if candidate is None:
            fallback = band_cfg.get("all_phases")
            if isinstance(fallback, list) and len(fallback) == 2:
                candidate = fallback
        if candidate is None:
            return None

        try:
            low = float(candidate[0])
            high = float(candidate[1])
        except (TypeError, ValueError):
            logger.warning(
                "ChannelManager: alarm_band for %s contains non-numeric "
                "values (%r); ignoring", short_id, candidate,
            )
            return None
        if low > high:
            logger.warning(
                "ChannelManager: alarm_band for %s is reversed [%s..%s]; "
                "ignoring", short_id, low, high,
            )
            return None
        return (low, high)

    def get_channels_in_zone(self, zone: str) -> list[str]:
        """Return all channel IDs classified into ``zone``.

        F-X helper for callers that want to iterate by physical context
        (e.g. "all warm-by-design channels"). Order matches YAML
        declaration order.
        """
        return [
            ch_id
            for ch_id, info in self._channels.items()
            if info.get("thermal_zone") == zone
        ]

    def resolve_channel_reference(self, reference: str) -> str:
        """Resolve a channel reference to its canonical runtime label.

        Accepts short IDs (e.g. ``'Т1'``) or full labels
        (e.g. ``'Т1 Криостат верх'``).  Returns the canonical full label
        that matches ``Reading.channel`` values at runtime.

        Raises:
            ChannelConfigError: if *reference* is empty or doesn't match
                any known channel.
        """
        reference = reference.strip()
        if not reference:
            raise ChannelConfigError("empty channel reference")

        short_id = reference.split(" ")[0] if " " in reference else reference
        info = self._channels.get(short_id)
        if info is None:
            known = sorted(self._channels.keys())
            raise ChannelConfigError(
                f"unknown channel reference '{reference}' — known channels: {', '.join(known)}"
            )
        name = info.get("name", "")
        return f"{short_id} {name}" if name else short_id

    def get_channels_by_group(self) -> dict[str, list[str]]:
        """Получить каналы, сгруппированные по полю 'group'.

        Returns dict: group_name → [channel_id, ...] в порядке из YAML.
        Каналы без группы попадают в '' (пустая строка).
        """
        from collections import OrderedDict

        groups: dict[str, list[str]] = OrderedDict()
        for ch_id, info in self._channels.items():
            group = info.get("group", "")
            if group not in groups:
                groups[group] = []
            groups[group].append(ch_id)
        return dict(groups)

    def get_channel_configs(self) -> list[dict]:
        """Получить конфигурации для TemperaturePanel (совместимость)."""
        result = []
        for ch_id, info in self._channels.items():
            if info.get("visible", True):
                display = f"{ch_id} {info.get('name', '')}".strip()
                result.append({"name": display, "channel_id": display})
        return result

    # ------------------------------------------------------------------
    # Change notification
    # ------------------------------------------------------------------

    def on_change(self, callback: Any) -> None:
        """Зарегистрировать callback для оповещения об изменениях."""
        self._callbacks.append(callback)

    def off_change(self, callback: Any) -> None:
        """Unregister a previously-registered change callback.

        Symmetric to on_change. Idempotent: silently no-op if callback
        was not registered.
        """
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    def _notify(self) -> None:
        """Оповестить всех подписчиков об изменении."""
        for cb in self._callbacks:
            try:
                cb()
            except Exception as exc:
                logger.error("Ошибка в callback ChannelManager: %s", exc)


# Module-level default instance
_default_instance: ChannelManager | None = None


def get_channel_manager() -> ChannelManager:
    """Получить глобальный экземпляр ChannelManager (lazy init)."""
    global _default_instance
    if _default_instance is None:
        _default_instance = ChannelManager()
    return _default_instance
