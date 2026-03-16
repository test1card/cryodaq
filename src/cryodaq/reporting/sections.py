from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx.document import Document
from docx.shared import Inches

from cryodaq.reporting.data import HistoricalReading, ReportDataset

SectionRenderer = Callable[[Document, ReportDataset, Path], None]


def _status_label(raw: object) -> str:
    value = str(raw or "").strip().upper()
    return {
        "RUNNING": "Выполняется",
        "COMPLETED": "Завершён",
        "ABORTED": "Прерван",
    }.get(value, str(raw or ""))


def _display_value(raw: object, *, empty: str = "не указано") -> str:
    text = str(raw or "").strip()
    return text or empty


def _add_plot(document: Document, title: str, readings: list[HistoricalReading], output_path: Path) -> None:
    if not readings:
        document.add_paragraph(f"{title}: данные за интервал эксперимента отсутствуют.")
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    xs = [item.timestamp for item in readings]
    ys = [item.value for item in readings]
    plt.figure(figsize=(7, 3))
    plt.plot(xs, ys)
    plt.title(title)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    document.add_picture(str(output_path), width=Inches(6.5))


def render_title_page(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    experiment = dataset.metadata["experiment"]
    template = dataset.metadata["template"]
    document.add_heading(str(experiment.get("title") or experiment.get("name") or "Отчёт по эксперименту"), 0)
    document.add_paragraph(f"Идентификатор эксперимента: {experiment.get('experiment_id', '')}")
    document.add_paragraph(f"Шаблон: {_display_value(template.get('name', template.get('id', '')))}")
    document.add_paragraph(f"Оператор: {_display_value(experiment.get('operator'))}")
    document.add_paragraph(f"Образец: {_display_value(experiment.get('sample'))}")
    document.add_paragraph(f"Статус: {_status_label(experiment.get('status', ''))}")
    document.add_paragraph(f"Начало: {_display_value(experiment.get('start_time'))}")
    document.add_paragraph(f"Завершение: {experiment.get('end_time', '') or 'выполняется'}")
    if experiment.get("notes"):
        document.add_paragraph(f"Примечания: {experiment['notes']}")


def render_cooldown_section(document: Document, dataset: ReportDataset, assets_dir: Path) -> None:
    document.add_heading("Охлаждение", level=1)
    temp_readings = [item for item in dataset.readings if item.unit == "K"]
    _add_plot(document, "Температура", temp_readings, assets_dir / "cooldown_temperature.png")
    if temp_readings:
        document.add_paragraph(f"Число точек: {len(temp_readings)}")
        document.add_paragraph(f"Средняя температура: {mean(item.value for item in temp_readings):.3f} K")


def render_thermal_section(document: Document, dataset: ReportDataset, assets_dir: Path) -> None:
    document.add_heading("Тепловая нагрузка", level=1)
    power_readings = [item for item in dataset.readings if item.channel.endswith("/power")]
    _add_plot(document, "Мощность Keithley", power_readings, assets_dir / "thermal_power.png")
    if power_readings:
        by_channel: dict[str, list[float]] = defaultdict(list)
        for item in power_readings:
            by_channel[item.channel].append(item.value)
        for channel, values in sorted(by_channel.items()):
            document.add_paragraph(f"{channel}: среднее = {mean(values):.3f} {power_readings[0].unit}")


def render_pressure_section(document: Document, dataset: ReportDataset, assets_dir: Path) -> None:
    document.add_heading("Давление", level=1)
    pressure = [
        item for item in dataset.readings if "pressure" in item.channel.lower() or item.unit.lower() in {"mbar", "pa"}
    ]
    _add_plot(document, "Давление", pressure, assets_dir / "pressure.png")
    if pressure:
        document.add_paragraph(f"Число точек: {len(pressure)}")
        document.add_paragraph(f"Последнее значение: {pressure[-1].value:.3e} {pressure[-1].unit}")


def render_operator_log_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    document.add_heading("Журнал оператора", level=1)
    if not dataset.operator_log:
        document.add_paragraph("Записи журнала оператора за интервал эксперимента отсутствуют.")
        return
    for item in dataset.operator_log:
        who = item.author or item.source or "система"
        tag_suffix = f" [{', '.join(item.tags)}]" if item.tags else ""
        document.add_paragraph(
            f"{item.timestamp.isoformat()} | {who}: {item.message}{tag_suffix}",
            style="List Bullet",
        )


def render_alarms_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    document.add_heading("Алармы", level=1)
    if not dataset.alarm_readings:
        document.add_paragraph("События алармов за интервал эксперимента отсутствуют.")
        return
    for item in dataset.alarm_readings[-20:]:
        document.add_paragraph(
            f"{item.timestamp.isoformat()} | {item.channel} = {item.value:g} {item.unit} [{item.status}]",
            style="List Bullet",
        )


def render_config_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    document.add_heading("Снимок конфигурации", level=1)
    config_snapshot = dataset.metadata["experiment"].get("config_snapshot", {})
    if not config_snapshot:
        document.add_paragraph("Снимок конфигурации для этого эксперимента не сохранён.")
        return
    config_text = json.dumps(config_snapshot, ensure_ascii=False, indent=2)
    document.add_paragraph(config_text)


SECTION_REGISTRY: dict[str, SectionRenderer] = {
    "title_page": render_title_page,
    "cooldown_section": render_cooldown_section,
    "thermal_section": render_thermal_section,
    "pressure_section": render_pressure_section,
    "operator_log_section": render_operator_log_section,
    "alarms_section": render_alarms_section,
    "config_section": render_config_section,
}
