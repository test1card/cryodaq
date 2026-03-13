"""Управление жизненным циклом эксперимента.

ExperimentManager отслеживает текущий эксперимент: старт, стоп, запись
метаданных в SQLite.  Снимок конфигурации приборов сохраняется как JSON
в таблице experiments, что позволяет воспроизвести условия эксперимента.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Схема таблицы экспериментов (создаётся в том же daily-файле SQLite)
# ---------------------------------------------------------------------------
SCHEMA_EXPERIMENTS = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id   TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    operator        TEXT NOT NULL,
    cryostat        TEXT NOT NULL DEFAULT '',
    sample          TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    start_time      TEXT NOT NULL,
    end_time        TEXT,
    status          TEXT NOT NULL DEFAULT 'RUNNING',
    config_snapshot TEXT NOT NULL DEFAULT '{}'
);
"""


class ExperimentStatus(Enum):
    """Статус эксперимента."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


@dataclass(frozen=True, slots=True)
class ExperimentInfo:
    """Метаданные текущего эксперимента (только для чтения)."""

    experiment_id: str
    name: str
    operator: str
    cryostat: str
    sample: str
    description: str
    start_time: datetime
    status: ExperimentStatus
    config_snapshot: dict[str, Any] = field(default_factory=dict)


class ExperimentManager:
    """Управление жизненным циклом эксперимента.

    Хранит запись об эксперименте в той же daily-базе SQLite, что и
    SQLiteWriter.  Один эксперимент может быть активен одновременно.

    Параметры
    ----------
    data_dir:
        Директория с файлами БД (совпадает с SQLiteWriter.data_dir).
    instruments_config:
        Путь к config/instruments.yaml — снимок записывается при старте.
    """

    def __init__(self, data_dir: Path, instruments_config: Path) -> None:
        self._data_dir = data_dir
        self._instruments_config = instruments_config
        self._active: ExperimentInfo | None = None

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @property
    def active_experiment(self) -> ExperimentInfo | None:
        """Текущий активный эксперимент (или None)."""
        return self._active

    def start_experiment(
        self,
        name: str,
        operator: str,
        *,
        cryostat: str = "",
        sample: str = "",
        description: str = "",
    ) -> str:
        """Начать новый эксперимент.

        Параметры
        ----------
        name:        Краткое название эксперимента.
        operator:    Имя оператора.
        cryostat:    Идентификатор криостата.
        sample:      Описание образца.
        description: Произвольные заметки.

        Возвращает
        ----------
        str:  Уникальный experiment_id (UUID4).

        Исключения
        ----------
        RuntimeError:  Если эксперимент уже запущен.
        """
        if self._active is not None:
            raise RuntimeError(
                f"Эксперимент '{self._active.name}' ({self._active.experiment_id}) "
                f"уже запущен.  Остановите его перед началом нового."
            )

        experiment_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)

        # Снимок конфигурации приборов
        config_snapshot = self._read_config_snapshot()

        info = ExperimentInfo(
            experiment_id=experiment_id,
            name=name,
            operator=operator,
            cryostat=cryostat,
            sample=sample,
            description=description,
            start_time=now,
            status=ExperimentStatus.RUNNING,
            config_snapshot=config_snapshot,
        )

        # Записать в БД
        self._write_start(info)
        self._active = info

        logger.info(
            "Эксперимент начат: id=%s, название='%s', оператор='%s', "
            "криостат='%s', образец='%s'",
            experiment_id, name, operator, cryostat, sample,
        )
        return experiment_id

    def stop_experiment(
        self,
        experiment_id: str | None = None,
        *,
        status: ExperimentStatus = ExperimentStatus.COMPLETED,
    ) -> None:
        """Завершить эксперимент.

        Параметры
        ----------
        experiment_id:
            ID эксперимента.  Если None — останавливает текущий активный.
        status:
            Финальный статус (COMPLETED или ABORTED).

        Исключения
        ----------
        RuntimeError:  Если нет активного эксперимента.
        ValueError:    Если experiment_id не совпадает с активным.
        """
        if self._active is None:
            raise RuntimeError("Нет активного эксперимента для остановки.")

        if experiment_id is not None and self._active.experiment_id != experiment_id:
            raise ValueError(
                f"experiment_id '{experiment_id}' не совпадает с активным "
                f"'{self._active.experiment_id}'."
            )

        now = datetime.now(timezone.utc)
        self._write_end(self._active.experiment_id, now, status)

        logger.info(
            "Эксперимент завершён: id=%s, статус=%s, "
            "длительность=%.1f мин",
            self._active.experiment_id,
            status.value,
            (now - self._active.start_time).total_seconds() / 60,
        )
        self._active = None

    # ------------------------------------------------------------------
    # Работа с SQLite
    # ------------------------------------------------------------------

    def _db_path_for_today(self) -> Path:
        """Путь к БД текущего дня."""
        today = datetime.now(timezone.utc).date()
        return self._data_dir / f"data_{today.isoformat()}.db"

    def _get_connection(self) -> sqlite3.Connection:
        """Открыть соединение и убедиться, что таблица experiments существует."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        db_path = self._db_path_for_today()
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(SCHEMA_EXPERIMENTS)
        conn.commit()
        return conn

    def _write_start(self, info: ExperimentInfo) -> None:
        """Записать строку начала эксперимента."""
        conn = self._get_connection()
        try:
            conn.execute(
                "INSERT INTO experiments "
                "(experiment_id, name, operator, cryostat, sample, description, "
                " start_time, status, config_snapshot) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    info.experiment_id,
                    info.name,
                    info.operator,
                    info.cryostat,
                    info.sample,
                    info.description,
                    info.start_time.isoformat(),
                    info.status.value,
                    json.dumps(info.config_snapshot, ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _write_end(
        self, experiment_id: str, end_time: datetime, status: ExperimentStatus,
    ) -> None:
        """Обновить строку эксперимента: записать end_time и статус."""
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE experiments SET end_time = ?, status = ? "
                "WHERE experiment_id = ?;",
                (end_time.isoformat(), status.value, experiment_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _read_config_snapshot(self) -> dict[str, Any]:
        """Прочитать instruments.yaml и вернуть как словарь."""
        if not self._instruments_config.exists():
            logger.warning(
                "Файл конфигурации приборов не найден: %s", self._instruments_config,
            )
            return {}
        try:
            with self._instruments_config.open(encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
        except Exception as exc:
            logger.error("Ошибка чтения конфигурации приборов: %s", exc)
            return {}
