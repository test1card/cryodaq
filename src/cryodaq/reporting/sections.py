from __future__ import annotations

import csv
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


def _existing_artifact(dataset: ReportDataset, role: str, *, category: str | None = None) -> Path | None:
    for item in dataset.artifact_index:
        if str(item.get("role", "")).strip() != role:
            continue
        if category is not None and str(item.get("category", "")).strip() != category:
            continue
        path = Path(str(item.get("path", "")).strip())
        if path.exists():
            return path
    return None


def _find_table_path(dataset: ReportDataset, table_id: str) -> Path | None:
    for item in dataset.result_tables:
        if str(item.get("table_id", "")).strip() != table_id:
            continue
        path = Path(str(item.get("path", "")).strip())
        if path.exists():
            return path
    return None


def _read_csv_preview(path: Path, *, limit: int = 6) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    if not rows:
        return [], []
    header = [str(item) for item in rows[0]]
    body = [[str(item) for item in row] for row in rows[1 : 1 + limit]]
    return header, body


def _add_table_preview(document: Document, path: Path, *, title: str, limit: int = 6) -> None:
    document.add_paragraph(f"{title}: {path}")
    header, rows = _read_csv_preview(path, limit=limit)
    if not header:
        document.add_paragraph("Таблица пуста.")
        return
    table = document.add_table(rows=1 + len(rows), cols=len(header))
    for index, value in enumerate(header):
        table.cell(0, index).text = value
    for row_index, row in enumerate(rows, start=1):
        for col_index, value in enumerate(row):
            table.cell(row_index, col_index).text = value


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
        document.add_paragraph(f"Заметки карточки: {experiment['notes']}")


def render_experiment_metadata_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    experiment = dataset.metadata["experiment"]
    summary = dataset.summary_metadata
    document.add_heading("Метаданные эксперимента", level=1)
    document.add_paragraph(f"Образец: {_display_value(experiment.get('sample'))}")
    document.add_paragraph(f"Криостат: {_display_value(experiment.get('cryostat'))}")
    if experiment.get("custom_fields"):
        document.add_paragraph(
            f"Поля карточки: {json.dumps(experiment.get('custom_fields', {}), ensure_ascii=False)}"
        )
    if summary:
        document.add_paragraph(f"Сводка архива: {json.dumps(summary, ensure_ascii=False)}")


def render_run_timeline_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    document.add_heading("Таймлайн прогонов", level=1)
    if not dataset.run_records:
        document.add_paragraph("Прогоны для этой карточки не зафиксированы.")
        return
    for item in dataset.run_records:
        document.add_paragraph(
            (
                f"{item.get('started_at', '')} → {item.get('finished_at', '') or '—'} | "
                f"{item.get('source_tab', '')}/{item.get('run_type', '')} | "
                f"{item.get('status', '')}"
            ),
            style="List Bullet",
        )


def render_run_parameters_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    document.add_heading("Параметры запусков", level=1)
    if not dataset.run_records:
        document.add_paragraph("Параметры запусков отсутствуют.")
        return
    for item in dataset.run_records:
        title = f"{item.get('source_tab', '')}/{item.get('run_type', '')}"
        document.add_paragraph(title, style="List Bullet")
        params = item.get("parameters") or {}
        if not params:
            document.add_paragraph("Параметры не сохранены.")
            continue
        document.add_paragraph(json.dumps(params, ensure_ascii=False, indent=2))


def render_result_tables_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    document.add_heading("Итоговые результаты и таблицы", level=1)
    table_map = {
        "measured_values": "Таблица измеренных величин",
        "setpoint_values": "Таблица заданных величин",
        "run_results": "Итоговые результаты прогонов",
        "conductivity_vs_temperature": "Теплопроводность vs температура",
    }
    rendered = False
    for table_id, title in table_map.items():
        path = _find_table_path(dataset, table_id)
        if path is None:
            continue
        _add_table_preview(document, path, title=title)
        rendered = True
    if not rendered:
        document.add_paragraph("Архивные таблицы результатов не найдены.")


def render_conductivity_section(document: Document, dataset: ReportDataset, assets_dir: Path) -> None:
    document.add_heading("Теплопроводность vs температура", level=1)
    archived_plot = _existing_artifact(dataset, "conductivity_vs_temperature", category="plot")
    if archived_plot is not None:
        document.add_picture(str(archived_plot), width=Inches(6.2))
        return
    path = _find_table_path(dataset, "conductivity_vs_temperature")
    if path is None:
        document.add_paragraph("График теплопроводности для этой карточки отсутствует.")
        return
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not rows:
        document.add_paragraph("График теплопроводности не удалось построить: таблица пуста.")
        return
    plot_path = assets_dir / "conductivity_vs_temperature.png"
    plt.figure(figsize=(6, 4))
    plt.plot(
        [float(item["temperature_k"]) for item in rows],
        [float(item["conductance_wk"]) for item in rows],
        marker="o",
    )
    plt.title("Conductivity vs temperature")
    plt.xlabel("Temperature (K)")
    plt.ylabel("Conductance (W/K)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close()
    document.add_picture(str(plot_path), width=Inches(6.2))


def render_artifact_manifest_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    document.add_heading("Ключевые артефакты", level=1)
    if not dataset.artifact_index:
        document.add_paragraph("Артефакты в архивной карточке отсутствуют.")
        return
    for item in dataset.artifact_index[:20]:
        document.add_paragraph(
            f"{item.get('category', '')} | {item.get('role', '')} | {item.get('path', '')}",
            style="List Bullet",
        )


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
    document.add_heading("Служебный лог", level=1)
    if not dataset.operator_log:
        document.add_paragraph("Записи служебного лога за интервал эксперимента отсутствуют.")
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


def render_operator_comments_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    document.add_heading("Комментарии оператора", level=1)
    document.add_paragraph("Заполнить после автоматической генерации отчёта.")
    document.add_paragraph("")
    document.add_paragraph("")


def render_operator_interpretation_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    document.add_heading("Интерпретация результатов", level=1)
    document.add_paragraph("Сюда оператор добавляет интерпретацию, выводы и замечания по качеству данных.")
    document.add_paragraph("")
    document.add_paragraph("")


def render_operator_photos_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    document.add_heading("Фотографии и внешние изображения", level=1)
    document.add_paragraph("В этот раздел можно вставить фотографии образца, оснастки и внешние иллюстрации.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Изображение 1"
    table.cell(0, 1).text = "Описание"
    table.cell(1, 0).text = ""
    table.cell(1, 1).text = ""


SECTION_REGISTRY: dict[str, SectionRenderer] = {
    "title_page": render_title_page,
    "experiment_metadata_section": render_experiment_metadata_section,
    "run_timeline_section": render_run_timeline_section,
    "run_parameters_section": render_run_parameters_section,
    "result_tables_section": render_result_tables_section,
    "conductivity_section": render_conductivity_section,
    "artifact_manifest_section": render_artifact_manifest_section,
    "cooldown_section": render_cooldown_section,
    "thermal_section": render_thermal_section,
    "pressure_section": render_pressure_section,
    "operator_log_section": render_operator_log_section,
    "alarms_section": render_alarms_section,
    "config_section": render_config_section,
    "operator_comments_section": render_operator_comments_section,
    "operator_interpretation_section": render_operator_interpretation_section,
    "operator_photos_section": render_operator_photos_section,
}
