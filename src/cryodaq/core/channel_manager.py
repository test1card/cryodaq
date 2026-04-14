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

logger = logging.getLogger(__name__)


class ChannelConfigError(RuntimeError):
    """Raised when channels.yaml cannot be loaded in a fail-closed manner."""

from cryodaq.paths import get_config_dir as _get_config_dir

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
    "Т11": {"name": "Теплообменник 1", "visible": True, "group": "компрессор"},
    "Т12": {"name": "Теплообменник 2", "visible": True, "group": "компрессор"},
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
                f"channels.yaml at {self._config_path}: expected mapping, "
                f"got {type(raw).__name__}"
            )
        channels = raw.get("channels")
        if not isinstance(channels, dict):
            raise ChannelConfigError(
                f"channels.yaml at {self._config_path}: missing or invalid "
                f"'channels' key"
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
        return [
            ch_id for ch_id, info in self._channels.items()
            if info.get("visible", True)
        ]

    def get_group(self, channel_id: str) -> str:
        """Получить группу канала (из channels.yaml)."""
        short_id = channel_id.split(" ")[0] if " " in channel_id else channel_id
        return self._channels.get(short_id, {}).get("group", "")

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
                f"unknown channel reference '{reference}' — "
                f"known channels: {', '.join(known)}"
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
