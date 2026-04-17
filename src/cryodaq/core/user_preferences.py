"""Persistent user preferences для форм создания экспериментов.

Хранит последние значения полей и историю для autocomplete.
Файл: data/user_preferences.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class UserPreferences:
    """Persistent user preferences (last experiment, history).

    Параметры
    ----------
    path:
        Путь к JSON-файлу. Родительские директории создаются при сохранении.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Не удалось загрузить user_preferences: %s", exc)
        return {}

    def save(self) -> None:
        """Сохранить в файл."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Не удалось сохранить user_preferences: %s", exc)

    def save_last_experiment(
        self,
        template_id: str,
        operator: str,
        sample: str,
        cryostat: str,
        description: str,
        custom_fields: dict | None = None,
    ) -> None:
        """Сохранить данные последнего эксперимента и обновить историю."""
        self._data["last_experiment"] = {
            "template_id": template_id,
            "operator": operator,
            "sample": sample,
            "cryostat": cryostat,
            "description": description,
            "custom_fields": custom_fields or {},
        }
        self._add_to_history("operator_history", operator)
        self._add_to_history("sample_history", sample)
        self._add_to_history("cryostat_history", cryostat)
        self.save()

    def get_last_experiment(self) -> dict:
        """Вернуть данные последнего эксперимента или пустой dict."""
        return self._data.get("last_experiment", {})

    def get_history(self, field: str) -> list[str]:
        """Вернуть историю для поля (operator, sample, cryostat).

        Параметры
        ----------
        field:
            Имя поля без суффикса ``_history`` (например, ``"operator"``).
        """
        return list(self._data.get(f"{field}_history", []))

    def _add_to_history(self, key: str, value: str, max_items: int = 20) -> None:
        """Добавить значение в историю, поддерживая dedup и лимит."""
        if not value or not value.strip():
            return
        history: list[str] = list(self._data.get(key, []))
        if value in history:
            history.remove(value)
        history.insert(0, value)
        self._data[key] = history[:max_items]


def suggest_experiment_name(
    template_id: str, existing_names: list[str], template_name_map: dict[str, str] | None = None
) -> str:
    """Предложить имя для нового эксперимента с авто-инкрементом.

    Параметры
    ----------
    template_id:
        ID шаблона (например, ``"thermal_conductivity"``).
    existing_names:
        Список существующих имён экспериментов.
    template_name_map:
        Словарь template_id → prefix. Если None — используется template_id.

    Пример
    ------
    >>> suggest_experiment_name("cooldown", ["Cooldown-001", "Cooldown-005"])
    'Cooldown-006'
    """
    if template_name_map and template_id in template_name_map:
        prefix = template_name_map[template_id]
    else:
        # Capitalize first letter of template_id for display
        prefix = template_id.replace("_", " ").title() if template_id else "Experiment"

    max_num = 0
    for name in existing_names:
        if name.startswith(prefix + "-"):
            suffix = name[len(prefix) + 1 :]
            try:
                num = int(suffix)
                max_num = max(max_num, num)
            except ValueError:
                pass

    return f"{prefix}-{max_num + 1:03d}"
