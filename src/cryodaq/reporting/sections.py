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


def _add_plot(document: Document, title: str, readings: list[HistoricalReading], output_path: Path) -> None:
    if not readings:
        document.add_paragraph(f"{title}: no recorded data in experiment range.")
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
    document.add_heading(str(experiment.get("title") or experiment.get("name") or "Experiment Report"), 0)
    document.add_paragraph(f"Experiment ID: {experiment.get('experiment_id', '')}")
    document.add_paragraph(f"Template: {template.get('name', template.get('id', ''))}")
    document.add_paragraph(f"Operator: {experiment.get('operator', '')}")
    document.add_paragraph(f"Sample: {experiment.get('sample', '')}")
    document.add_paragraph(f"Status: {experiment.get('status', '')}")
    document.add_paragraph(f"Start: {experiment.get('start_time', '')}")
    document.add_paragraph(f"End: {experiment.get('end_time', '') or 'in progress'}")
    if experiment.get("notes"):
        document.add_paragraph(f"Notes: {experiment['notes']}")


def render_cooldown_section(document: Document, dataset: ReportDataset, assets_dir: Path) -> None:
    document.add_heading("Cooldown Section", level=1)
    temp_readings = [item for item in dataset.readings if item.unit == "K"]
    _add_plot(document, "Temperature channels", temp_readings, assets_dir / "cooldown_temperature.png")
    if temp_readings:
        document.add_paragraph(f"Samples captured: {len(temp_readings)}")
        document.add_paragraph(f"Average temperature: {mean(item.value for item in temp_readings):.3f} K")


def render_thermal_section(document: Document, dataset: ReportDataset, assets_dir: Path) -> None:
    document.add_heading("Thermal Section", level=1)
    power_readings = [item for item in dataset.readings if item.channel.endswith("/power")]
    _add_plot(document, "Keithley power", power_readings, assets_dir / "thermal_power.png")
    if power_readings:
        by_channel: dict[str, list[float]] = defaultdict(list)
        for item in power_readings:
            by_channel[item.channel].append(item.value)
        for channel, values in sorted(by_channel.items()):
            document.add_paragraph(f"{channel}: avg={mean(values):.3f} {power_readings[0].unit}")


def render_pressure_section(document: Document, dataset: ReportDataset, assets_dir: Path) -> None:
    document.add_heading("Pressure Section", level=1)
    pressure = [
        item for item in dataset.readings if "pressure" in item.channel.lower() or item.unit.lower() in {"mbar", "pa"}
    ]
    _add_plot(document, "Pressure channels", pressure, assets_dir / "pressure.png")
    if pressure:
        document.add_paragraph(f"Samples captured: {len(pressure)}")
        document.add_paragraph(f"Latest pressure: {pressure[-1].value:.3e} {pressure[-1].unit}")


def render_operator_log_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    document.add_heading("Operator Log", level=1)
    if not dataset.operator_log:
        document.add_paragraph("No operator log entries recorded for this experiment.")
        return
    for item in dataset.operator_log:
        who = item.author or item.source or "system"
        tag_suffix = f" [{', '.join(item.tags)}]" if item.tags else ""
        document.add_paragraph(
            f"{item.timestamp.isoformat()} | {who}: {item.message}{tag_suffix}",
            style="List Bullet",
        )


def render_alarms_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    document.add_heading("Alarms", level=1)
    if not dataset.alarm_readings:
        document.add_paragraph("No alarm readings recorded in experiment range.")
        return
    for item in dataset.alarm_readings[-20:]:
        document.add_paragraph(
            f"{item.timestamp.isoformat()} | {item.channel} = {item.value:g} {item.unit} [{item.status}]",
            style="List Bullet",
        )


def render_config_section(document: Document, dataset: ReportDataset, _assets_dir: Path) -> None:
    document.add_heading("Configuration Snapshot", level=1)
    config_text = json.dumps(dataset.metadata["experiment"].get("config_snapshot", {}), ensure_ascii=False, indent=2)
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
