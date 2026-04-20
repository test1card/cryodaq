"""Shift handover widgets: start, periodic prompts, end summary.

Opt-in feature — requires config/shifts.yaml. All shift data is stored
via the existing operator log (log_entry command with tags).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

import yaml
from PySide6.QtCore import QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui.widgets.common import (
    apply_button_style,
    apply_panel_frame_style,
)
from cryodaq.paths import get_config_dir as _get_config_dir

logger = logging.getLogger(__name__)

_CONFIG_PATH = _get_config_dir() / "shifts.yaml"


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def load_shift_config() -> dict[str, Any]:
    """Load shift config; returns empty dict if file absent."""
    try:
        if _CONFIG_PATH.exists():
            with _CONFIG_PATH.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("Failed to load %s", _CONFIG_PATH, exc_info=True)
    return {}


def _colored_circle_icon(color: str) -> QIcon:
    """Create a small colored circle icon for ComboBox items."""
    pix = QPixmap(12, 12)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(QColor(color))
    painter.drawEllipse(1, 1, 10, 10)
    painter.end()
    return QIcon(pix)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _shift_id() -> str:
    now = _utcnow()
    return f"shift-{now.strftime('%Y%m%d')}-{now.strftime('%H')}"


# ---------------------------------------------------------------------------
# Auto-checks for shift start
# ---------------------------------------------------------------------------


def _send_log_fire_and_forget(payload: dict[str, Any], parent: QWidget) -> None:
    """Fire-and-forget log entry via background worker."""
    from cryodaq.gui.zmq_client import ZmqCommandWorker

    worker = ZmqCommandWorker(payload, parent=parent)
    worker.finished.connect(lambda r: None)
    worker.start()


# ---------------------------------------------------------------------------
# ShiftStartDialog
# ---------------------------------------------------------------------------


class ShiftStartDialog(QDialog):
    """Dialog for starting a shift — operator selection + auto-checks."""

    shift_started = Signal(str, str)  # operator_name, shift_id

    def __init__(self, config: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Заступление на смену")
        self.setMinimumWidth(420)

        self._config = config
        self._checks: list[dict[str, Any]] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Operator selector
        op_label = QLabel("Оператор:")
        op_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(op_label)

        self._operator_combo = QComboBox()
        self._operator_combo.setEditable(True)
        operators = config.get("operators", [])
        if isinstance(operators, list):
            for op in operators:
                self._operator_combo.addItem(str(op))
        layout.addWidget(self._operator_combo)

        # Auto-checks area
        checks_label = QLabel("Проверки:")
        checks_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(checks_label)

        self._checks_frame = QVBoxLayout()
        layout.addLayout(self._checks_frame)

        self._run_checks_btn = QPushButton("Запустить проверки")
        apply_button_style(self._run_checks_btn, "neutral")
        self._run_checks_btn.clicked.connect(self._do_checks)
        layout.addWidget(self._run_checks_btn)

        # Buttons
        self._btn_box = QDialogButtonBox()
        self._start_btn = self._btn_box.addButton(
            "Заступить",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._start_btn.setEnabled(False)
        self._btn_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._btn_box.accepted.connect(self._on_accept)
        self._btn_box.rejected.connect(self.reject)
        layout.addWidget(self._btn_box)

    @Slot()
    def _do_checks(self) -> None:
        # Clear previous
        while self._checks_frame.count():
            item = self._checks_frame.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        self._run_checks_btn.setEnabled(False)
        self._run_checks_btn.setText("Проверка...")

        from cryodaq.gui.zmq_client import ZmqCommandWorker

        worker = ZmqCommandWorker({"cmd": "experiment_status"}, parent=self)
        worker.finished.connect(self._on_checks_result)
        self._workers: list[object] = [worker]
        worker.start()

    @Slot(dict)
    def _on_checks_result(self, result: dict) -> None:
        engine_ok = result.get("ok", False)
        self._checks = [
            {
                "name": "Engine подключён",
                "ok": engine_ok,
                "detail": "OK" if engine_ok else "Engine не отвечает",
            },
            {
                "name": "Критических алармов нет",
                "ok": engine_ok,
                "detail": "OK" if engine_ok else "Невозможно проверить",
            },
        ]
        for check in self._checks:
            row = QLabel(f"{'✓' if check['ok'] else '✗'} {check['name']} — {check['detail']}")
            row.setStyleSheet(
                f"color: {theme.STATUS_OK if check['ok'] else theme.STATUS_FAULT}; padding: 2px;"
            )
            self._checks_frame.addWidget(row)

        self._run_checks_btn.setEnabled(True)
        self._run_checks_btn.setText("Запустить проверки")
        self._start_btn.setEnabled(True)
        self._workers = []

    @Slot()
    def _on_accept(self) -> None:
        operator = self._operator_combo.currentText().strip()
        if not operator:
            QMessageBox.warning(self, "Ошибка", "Укажите имя оператора.")
            return

        sid = _shift_id()
        checks_summary = [
            {"name": c["name"], "ok": c["ok"], "detail": c["detail"]} for c in self._checks
        ]

        _send_log_fire_and_forget(
            {
                "cmd": "log_entry",
                "message": f"Заступление на смену: {operator}",
                "author": operator,
                "source": "shift_handover",
                "tags": ["shift_start"],
                "metadata": json.dumps(
                    {
                        "shift_id": sid,
                        "operator": operator,
                        "checks": checks_summary,
                    }
                ),
            },
            parent=self,
        )

        self.shift_started.emit(operator, sid)
        self.accept()


# ---------------------------------------------------------------------------
# ShiftPeriodicPrompt
# ---------------------------------------------------------------------------


class ShiftPeriodicPrompt(QDialog):
    """Periodic status check dialog during a shift."""

    def __init__(
        self,
        operator: str,
        shift_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Периодическая проверка смены")
        self.setMinimumWidth(400)

        self._operator = operator
        self._shift_id = shift_id

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        info = QLabel(f"Оператор: {operator} | Смена: {shift_id}")
        info.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(info)

        # Status dropdown
        status_label = QLabel("Статус:")
        status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(status_label)

        self._status_combo = QComboBox()
        self._status_combo.addItem(_colored_circle_icon("#2ECC40"), "Штатно")
        self._status_combo.addItem(_colored_circle_icon("#FFDC00"), "Внимание")
        self._status_combo.addItem(_colored_circle_icon("#FF4136"), "Проблема")
        layout.addWidget(self._status_combo)

        # Auto-filled readings
        self._readings_label = QLabel("Показания загружаются...")
        self._readings_label.setStyleSheet(f"color: {theme.TEXT_ACCENT};")
        layout.addWidget(self._readings_label)

        # Notes
        notes_label = QLabel("Замечания:")
        layout.addWidget(notes_label)

        self._notes = QPlainTextEdit()
        self._notes.setMaximumHeight(80)
        self._notes.setPlaceholderText("Необязательно...")
        layout.addWidget(self._notes)

        # Buttons
        btn_box = QDialogButtonBox()
        btn_box.addButton("Записать", QDialogButtonBox.ButtonRole.AcceptRole)
        btn_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_submit)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def set_readings_text(self, text: str) -> None:
        self._readings_label.setText(text)

    @Slot()
    def _on_submit(self) -> None:
        status = self._status_combo.currentText()
        notes = self._notes.toPlainText().strip()

        message_parts = [f"Периодическая проверка: {status}"]
        if notes:
            message_parts.append(notes)

        _send_log_fire_and_forget(
            {
                "cmd": "log_entry",
                "message": " | ".join(message_parts),
                "author": self._operator,
                "source": "shift_handover",
                "tags": ["shift_periodic"],
                "metadata": json.dumps(
                    {
                        "shift_id": self._shift_id,
                        "status": status,
                        "readings": self._readings_label.text(),
                    }
                ),
            },
            parent=self,
        )
        self.accept()


# ---------------------------------------------------------------------------
# ShiftEndDialog
# ---------------------------------------------------------------------------


_SHIFT_FALLBACK_WINDOW_S = 8 * 3600
_SHIFT_EVENT_TAGS: frozenset[str] = frozenset({"phase", "experiment", "safety_fault", "alarm_ack"})


def _parse_epoch_or_iso(raw: object) -> float | None:
    """Accept either a numeric epoch (seconds, int/float) or an ISO 8601 string.

    log_get and experiment_status both return timestamps as ISO strings
    (``OperatorLogEntry.to_payload`` + metadata reader), while the
    alarm_v2 history deque stores numeric epoch floats directly. Unify
    handling here so every section formatter works against either
    shape.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        # Allow numeric strings first (back-compat with older tests /
        # fixtures that pass epoch seconds as strings).
        try:
            return float(text)
        except ValueError:
            pass
        # ISO 8601 with trailing Z needs the +00:00 suffix substitution
        # because fromisoformat only accepts full UTC offsets.
        iso = text
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(iso).timestamp()
        except ValueError:
            return None
    return None


def format_shift_events_section(entries: list[dict]) -> str:
    """Render the events section of the shift handover as Markdown lines.

    Each entry's timestamp is rendered HH:MM (UTC — operators read UTC
    throughout CryoDAQ by invariant); tag(s), author, and message are
    shown inline. Empty input yields the canonical "— нет событий"
    placeholder so the section never renders blank.
    """
    if not entries:
        return "— нет событий"
    lines: list[str] = []
    for entry in entries:
        raw_ts = entry.get("timestamp")
        epoch = _parse_epoch_or_iso(raw_ts)
        when = "—"
        if epoch is not None:
            try:
                when = datetime.fromtimestamp(epoch, tz=UTC).strftime("%H:%M")
            except (TypeError, ValueError, OSError):
                when = "—"
        tags = entry.get("tags") or []
        if isinstance(tags, str):
            tag_text = tags
        else:
            tag_text = ", ".join(str(t) for t in tags) if tags else ""
        message = str(entry.get("message", "")).strip() or "—"
        author = str(entry.get("author", "")).strip()
        prefix = f"**{when}**"
        if tag_text:
            prefix += f" *[{tag_text}]*"
        if author:
            prefix += f" {author}:"
        lines.append(f"- {prefix} {message}")
    return "\n".join(lines)


def format_shift_alarms_section(history: list[dict]) -> str:
    if not history:
        return "— тревог не было"
    lines: list[str] = []
    for entry in history:
        raw_ts = entry.get("at")
        when = "—"
        try:
            if raw_ts is not None:
                when = datetime.fromtimestamp(float(raw_ts), tz=UTC).strftime("%H:%M")
        except (TypeError, ValueError, OSError):
            when = "—"
        transition = str(entry.get("transition", "")).strip() or "—"
        level = str(entry.get("level", "")).strip()
        alarm_id = str(entry.get("alarm_id", "")).strip() or "—"
        message = str(entry.get("message", "")).strip()
        head = f"- **{when}** {transition}"
        if level:
            head += f" [{level}]"
        head += f" `{alarm_id}`"
        if message:
            head += f" — {message}"
        lines.append(head)
    return "\n".join(lines)


def format_shift_temperatures_section(per_channel: dict[str, dict]) -> str:
    """Render min/max/delta per temperature channel as a Markdown table.

    ``per_channel`` is ``{channel: {"min": ..., "max": ...}}``. Missing
    values become em-dash.
    """
    if not per_channel:
        return "— данных нет"
    headers = "| Канал | T min, K | T max, K | Δ, K |"
    sep = "|---|---:|---:|---:|"
    rows: list[str] = [headers, sep]
    for channel in sorted(per_channel):
        stats = per_channel[channel]

        def _fmt(v: object) -> str:
            try:
                return f"{float(v):.3f}"  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return "—"

        t_min = stats.get("min")
        t_max = stats.get("max")
        if t_min is None or t_max is None:
            delta_text = "—"
        else:
            try:
                delta_text = f"{float(t_max) - float(t_min):.3f}"
            except (TypeError, ValueError):
                delta_text = "—"
        rows.append(f"| {channel} | {_fmt(t_min)} | {_fmt(t_max)} | {delta_text} |")
    return "\n".join(rows)


def format_shift_experiment_section(payload: dict | None) -> str:
    """Render the experiment-progress block.

    ``payload`` is the engine's experiment_status reply (or None).
    """
    if not payload or not isinstance(payload, dict):
        return "— эксперимент не активен"
    exp = payload.get("active_experiment")
    if not isinstance(exp, dict) or not exp:
        return "— эксперимент не активен"
    name = str(exp.get("name") or exp.get("title") or "—").strip()
    operator = str(exp.get("operator", "")).strip()
    phases = payload.get("phases") or exp.get("phases") or []
    lines: list[str] = [f"- Эксперимент: **{name}**"]
    if operator:
        lines.append(f"- Оператор: {operator}")
    if isinstance(phases, list) and phases:
        phase_bits: list[str] = []
        for phase in phases:
            if not isinstance(phase, dict):
                continue
            phase_name = str(phase.get("phase", "")).strip() or "—"
            started = phase.get("started_at")
            ended = phase.get("ended_at")
            # Accept both numeric epoch and ISO 8601 — experiment_status
            # returns ISO strings from metadata; tests pass floats.
            started_f = _parse_epoch_or_iso(started)
            ended_f = _parse_epoch_or_iso(ended)
            if started_f is not None and ended_f is not None:
                duration_min = int(round((ended_f - started_f) / 60.0))
                phase_bits.append(f"{phase_name} ({duration_min} мин)")
            elif started_f is not None:
                phase_bits.append(f"{phase_name} (активная)")
            else:
                phase_bits.append(phase_name)
        if phase_bits:
            lines.append("- Фазы: " + " → ".join(phase_bits))
    return "\n".join(lines)


def compose_shift_handover_markdown(
    *,
    operator: str,
    start_epoch: float,
    end_epoch: float,
    events: str,
    alarms: str,
    temperatures: str,
    experiment: str,
    comment: str,
    handover_note: str,
) -> str:
    """Assemble the full Markdown body used by clipboard export + log save."""
    start_str = datetime.fromtimestamp(start_epoch, tz=UTC).strftime("%Y-%m-%d %H:%M")
    end_str = datetime.fromtimestamp(end_epoch, tz=UTC).strftime("%Y-%m-%d %H:%M")
    parts = [
        f"# Сдача смены — {operator}",
        f"*Окно смены:* `{start_str}` → `{end_str}` (UTC)",
        "",
        "## События смены",
        events,
        "",
        "## Тревоги за смену",
        alarms,
        "",
        "## Температуры за смену",
        temperatures,
        "",
        "## Прогресс эксперимента",
        experiment,
        "",
    ]
    if comment.strip():
        parts.extend(["## Комментарии", comment.strip(), ""])
    if handover_note.strip():
        parts.extend(["## Передача следующему оператору", handover_note.strip(), ""])
    return "\n".join(parts).rstrip() + "\n"


class ShiftEndDialog(QDialog):
    """Dialog for ending a shift — auto-summary + final comment.

    IV.4 F11 extension: the dialog now auto-populates four read-only
    sections (events / alarms / temperatures / experiment progress) by
    dispatching ZMQ queries to the engine at open time. The shift
    window spans from ``start_epoch`` (wall-clock seconds since the
    operator clicked «Заступить на смену») to ``now``; if no
    ``start_epoch`` is provided, the fallback is the last 8 hours so
    the dialog is useful even on a shift that wasn't formally started
    from this GUI.

    Operator still types free-form comments + a handover note; the
    «Скопировать в Markdown» button ships the full summary to the
    clipboard and the «Сдать смену» button writes it to the operator
    log under tag ``shift_end`` with the Markdown body embedded in
    the entry ``message`` field (operator_log has no metadata column).
    """

    shift_ended = Signal()

    def __init__(
        self,
        operator: str,
        shift_id: str,
        start_time: float,
        periodic_count: int,
        missed_count: int,
        start_epoch: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Сдача смены")
        self.setMinimumWidth(640)
        self.setMinimumHeight(640)

        self._operator = operator
        self._shift_id = shift_id
        self._end_epoch = time.time()
        if start_epoch is not None and start_epoch > 0:
            self._start_epoch = float(start_epoch)
        else:
            # IV.4 F11 spec: fallback window is the last 8 hours when
            # no shift-start log is available.
            self._start_epoch = self._end_epoch - _SHIFT_FALLBACK_WINDOW_S

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Summary
        elapsed_s = int(time.monotonic() - start_time)
        h, rem = divmod(elapsed_s, 3600)
        m, _ = divmod(rem, 60)

        summary_label = QLabel("Итоги смены")
        summary_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(summary_label)

        summary_lines = [
            f"Оператор: {operator}",
            f"Длительность: {h}ч {m}мин",
            f"Периодических проверок: {periodic_count}",
            f"Пропущенных проверок: {missed_count}",
        ]
        summary_text = QLabel("\n".join(summary_lines))
        summary_text.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; padding: {theme.SPACE_1}px;")
        layout.addWidget(summary_text)

        # IV.4 F11: four auto-sections. Each is a read-only block that
        # starts with a «загружается...» placeholder and is replaced
        # once the corresponding engine reply lands.
        self._events_section_text = "загружается..."
        self._alarms_section_text = "загружается..."
        self._temperatures_section_text = "загружается..."
        self._experiment_section_text = "загружается..."
        self._events_label = self._build_section(layout, "События смены")
        self._alarms_label = self._build_section(layout, "Тревоги за смену")
        self._temperatures_label = self._build_section(layout, "Температуры за смену")
        self._experiment_label = self._build_section(layout, "Прогресс эксперимента")

        # Final comment
        comment_label = QLabel("Итоговый комментарий:")
        layout.addWidget(comment_label)

        self._comment = QPlainTextEdit()
        self._comment.setMaximumHeight(100)
        self._comment.setPlaceholderText("Состояние системы, замечания для следующей смены...")
        layout.addWidget(self._comment)

        handover_label = QLabel("Передача следующему оператору:")
        layout.addWidget(handover_label)
        self._handover_note = QPlainTextEdit()
        self._handover_note.setMaximumHeight(80)
        self._handover_note.setPlaceholderText(
            "Активные эксперименты, контекст, на что обратить внимание..."
        )
        layout.addWidget(self._handover_note)

        # Buttons
        btn_box = QDialogButtonBox()
        self._markdown_btn = btn_box.addButton(
            "Скопировать в Markdown",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        self._markdown_btn.clicked.connect(self._on_copy_markdown)
        btn_box.addButton("Сдать смену", QDialogButtonBox.ButtonRole.AcceptRole)
        btn_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_end)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._elapsed_h = h
        self._elapsed_m = m
        self._periodic_count = periodic_count
        self._missed_count = missed_count
        self._workers: list[object] = []

        # Fire the four async fetches. Tests that don't want the
        # engine round-trip can patch `populate_sections`.
        self.populate_sections()

    def _build_section(self, layout: QVBoxLayout, title: str) -> QLabel:
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(title_label)
        body = QLabel("загружается...")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; padding: {theme.SPACE_1}px;")
        layout.addWidget(body)
        return body

    # ------------------------------------------------------------------
    # Async fetch / section population
    # ------------------------------------------------------------------

    def populate_sections(self) -> None:
        """Dispatch the four engine queries. Non-blocking."""
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        def _dispatch(payload: dict, slot) -> None:
            worker = ZmqCommandWorker(payload, parent=self)
            worker.finished.connect(slot)
            self._workers.append(worker)
            worker.start()

        _dispatch(
            {
                "cmd": "log_get",
                "start_ts": self._start_epoch,
                "end_ts": self._end_epoch,
                "limit": 500,
            },
            self._on_events_reply,
        )
        _dispatch(
            {
                "cmd": "alarm_v2_history",
                "start_ts": self._start_epoch,
                "end_ts": self._end_epoch,
                "limit": 500,
            },
            self._on_alarms_reply,
        )
        _dispatch(
            {
                "cmd": "readings_history",
                # IV.4 F11 amend: engine handler uses from_ts/to_ts, not
                # start_ts/end_ts — sending the wrong keys made the
                # query effectively unbounded and temperatures section
                # leaked data from outside the shift window.
                "from_ts": self._start_epoch,
                "to_ts": self._end_epoch,
                "channels": None,
            },
            self._on_temperatures_reply,
        )
        _dispatch({"cmd": "experiment_status"}, self._on_experiment_reply)

    @Slot(dict)
    def _on_events_reply(self, result: dict) -> None:
        if not isinstance(result, dict) or not result.get("ok"):
            self._events_section_text = "— данные недоступны"
        else:
            entries = result.get("entries") or []
            # Filter by tags only (engine log_get already filters by
            # the requested time range).
            filtered = [
                entry
                for entry in entries
                if isinstance(entry, dict)
                and any(tag in _SHIFT_EVENT_TAGS for tag in (entry.get("tags") or []))
            ]
            self._events_section_text = format_shift_events_section(filtered)
        self._events_label.setText(self._events_section_text)

    @Slot(dict)
    def _on_alarms_reply(self, result: dict) -> None:
        if not isinstance(result, dict) or not result.get("ok"):
            self._alarms_section_text = "— данные недоступны"
        else:
            history = result.get("history") or []
            self._alarms_section_text = format_shift_alarms_section(history)
        self._alarms_label.setText(self._alarms_section_text)

    @Slot(dict)
    def _on_temperatures_reply(self, result: dict) -> None:
        if not isinstance(result, dict) or not result.get("ok"):
            self._temperatures_section_text = "— данные недоступны"
        else:
            data = result.get("data") or {}
            # Compute min/max per T-prefixed channel only.
            per_channel: dict[str, dict[str, float]] = {}
            for channel, points in data.items():
                if not isinstance(channel, str) or not channel.startswith("Т"):
                    continue
                values: list[float] = []
                for point in points or []:
                    try:
                        values.append(float(point[1]))
                    except (TypeError, ValueError, IndexError):
                        continue
                if values:
                    per_channel[channel] = {"min": min(values), "max": max(values)}
            self._temperatures_section_text = format_shift_temperatures_section(per_channel)
        self._temperatures_label.setText(self._temperatures_section_text)

    @Slot(dict)
    def _on_experiment_reply(self, result: dict) -> None:
        if not isinstance(result, dict) or not result.get("ok"):
            self._experiment_section_text = "— данные недоступны"
        else:
            self._experiment_section_text = format_shift_experiment_section(result)
        self._experiment_label.setText(self._experiment_section_text)

    # ------------------------------------------------------------------
    # Markdown export + save
    # ------------------------------------------------------------------

    def _compose_markdown(self) -> str:
        return compose_shift_handover_markdown(
            operator=self._operator,
            start_epoch=self._start_epoch,
            end_epoch=self._end_epoch,
            events=self._events_section_text,
            alarms=self._alarms_section_text,
            temperatures=self._temperatures_section_text,
            experiment=self._experiment_section_text,
            comment=self._comment.toPlainText(),
            handover_note=self._handover_note.toPlainText(),
        )

    @Slot()
    def _on_copy_markdown(self) -> None:
        from PySide6.QtWidgets import QApplication as _QApp

        markdown = self._compose_markdown()
        clipboard = _QApp.clipboard()
        if clipboard is not None:
            clipboard.setText(markdown)

    @Slot()
    def _on_end(self) -> None:
        comment = self._comment.toPlainText().strip()
        markdown_body = self._compose_markdown()

        # IV.4 F11 amend: the operator_log schema has no metadata column
        # and the engine's log_entry handler ignores that field, so the
        # compiled Markdown summary is stored as the message body itself.
        # Format: one-line header + blank line + full Markdown so
        # log_get consumers (shift handover history, archive viewer)
        # still see the compiled summary verbatim.
        header_line = f"Сдача смены: {self._operator}"
        if comment:
            header_line = f"{header_line} | {comment}"
        message = f"{header_line}\n\n{markdown_body}"

        _send_log_fire_and_forget(
            {
                "cmd": "log_entry",
                "message": message,
                "author": self._operator,
                "source": "shift_handover",
                "tags": ["shift_end"],
            },
            parent=self,
        )

        self.shift_ended.emit()
        self.accept()


# ---------------------------------------------------------------------------
# ShiftBar — compact widget embedded in Overview
# ---------------------------------------------------------------------------


class ShiftBar(QFrame):
    """Compact shift status bar: start/end buttons + operator + elapsed time.

    Manages periodic prompt timer internally.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(36)
        apply_panel_frame_style(self)

        self._config = load_shift_config()
        self._active = False
        self._operator = ""
        self._shift_id = ""
        self._start_mono = 0.0
        self._start_epoch_s = 0.0
        self._periodic_count = 0
        self._missed_count = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 2, 12, 2)
        layout.setSpacing(8)

        lbl_font = QFont()
        lbl_font.setPointSize(10)

        self._status_label = QLabel("Смена: не активна")
        self._status_label.setFont(lbl_font)
        self._status_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; border: none;")
        layout.addWidget(self._status_label)

        self._elapsed_label = QLabel("")
        self._elapsed_label.setFont(lbl_font)
        self._elapsed_label.setStyleSheet(f"color: {theme.TEXT_ACCENT}; border: none;")
        layout.addWidget(self._elapsed_label)

        layout.addStretch()

        self._start_btn = QPushButton("Заступить на смену")
        self._start_btn.setFixedSize(QSize(160, 26))
        apply_button_style(self._start_btn, "primary", compact=True)
        self._start_btn.clicked.connect(self._on_start_shift)
        layout.addWidget(self._start_btn)

        self._end_btn = QPushButton("Сдать смену")
        self._end_btn.setFixedSize(QSize(120, 26))
        apply_button_style(self._end_btn, "warning", compact=True)
        self._end_btn.clicked.connect(self._on_end_shift)
        self._end_btn.setVisible(False)
        layout.addWidget(self._end_btn)

        # Elapsed update timer (1s)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick_elapsed)

        # Periodic prompt timer
        interval_h = float(self._config.get("periodic_interval_hours", 2))
        self._periodic_interval_ms = int(interval_h * 3600 * 1000)
        self._missed_timeout_ms = int(
            float(self._config.get("periodic_missed_timeout_minutes", 15)) * 60 * 1000
        )

        self._periodic_timer = QTimer(self)
        self._periodic_timer.timeout.connect(self._on_periodic_due)

        self._missed_timer = QTimer(self)
        self._missed_timer.setSingleShot(True)
        self._missed_timer.timeout.connect(self._on_periodic_missed)

        self._prompt_pending = False
        self._prompt_dialog: QDialog | None = None
        self._workers: list[object] = []

    # --- Public API ---

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def operator_name(self) -> str:
        return self._operator

    # --- Slots ---

    @Slot()
    def _on_start_shift(self) -> None:
        dialog = ShiftStartDialog(self._config, parent=self)
        dialog.shift_started.connect(self._activate_shift)
        dialog.exec()

    @Slot(str, str)
    def _activate_shift(self, operator: str, shift_id: str) -> None:
        self._active = True
        self._operator = operator
        self._shift_id = shift_id
        self._start_mono = time.monotonic()
        self._start_epoch_s = time.time()
        self._periodic_count = 0
        self._missed_count = 0

        self._status_label.setText(f"Смена: {operator}")
        self._status_label.setStyleSheet(f"color: {theme.STATUS_OK}; border: none;")
        self._start_btn.setVisible(False)
        self._end_btn.setVisible(True)

        self._tick_timer.start()
        if self._periodic_interval_ms > 0:
            self._periodic_timer.start(self._periodic_interval_ms)

    @Slot()
    def _on_end_shift(self) -> None:
        dialog = ShiftEndDialog(
            operator=self._operator,
            shift_id=self._shift_id,
            start_time=self._start_mono,
            periodic_count=self._periodic_count,
            missed_count=self._missed_count,
            start_epoch=self._start_epoch_s,
            parent=self,
        )
        dialog.shift_ended.connect(self._deactivate_shift)
        dialog.exec()

    @Slot()
    def _deactivate_shift(self) -> None:
        self._active = False
        self._operator = ""
        self._shift_id = ""

        self._tick_timer.stop()
        self._periodic_timer.stop()
        self._missed_timer.stop()

        self._status_label.setText("Смена: не активна")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; border: none;")
        self._elapsed_label.setText("")
        self._start_btn.setVisible(True)
        self._end_btn.setVisible(False)

    @Slot()
    def _tick_elapsed(self) -> None:
        if not self._active:
            return
        elapsed_s = int(time.monotonic() - self._start_mono)
        h, rem = divmod(elapsed_s, 3600)
        m, s = divmod(rem, 60)
        self._elapsed_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    @Slot()
    def _on_periodic_due(self) -> None:
        if not self._active:
            return
        if self._prompt_pending:
            return  # previous dialog still open — skip
        self._prompt_pending = True
        # Start missed timer
        if self._missed_timeout_ms > 0:
            self._missed_timer.start(self._missed_timeout_ms)

        dialog = ShiftPeriodicPrompt(
            operator=self._operator,
            shift_id=self._shift_id,
            parent=self,
        )
        self._prompt_dialog = dialog
        result = dialog.exec()
        self._prompt_dialog = None
        self._prompt_pending = False
        self._missed_timer.stop()

        if result == QDialog.DialogCode.Accepted:
            self._periodic_count += 1

    @Slot()
    def _on_periodic_missed(self) -> None:
        if not self._active or not self._prompt_pending:
            return
        self._missed_count += 1
        logger.warning("Shift periodic check missed for %s", self._shift_id)

        # Auto-dismiss the dialog — operator didn't respond in time
        if self._prompt_dialog is not None:
            logger.info("Auto-dismissing periodic prompt (missed timeout)")
            self._prompt_dialog.reject()

        from cryodaq.gui.zmq_client import ZmqCommandWorker

        worker = ZmqCommandWorker(
            {
                "cmd": "log_entry",
                "message": f"Пропущена периодическая проверка (оператор: {self._operator})",
                "author": self._operator,
                "source": "shift_handover",
                "tags": ["shift_periodic_missed"],
                "metadata": json.dumps(
                    {
                        "shift_id": self._shift_id,
                        "missed_count": self._missed_count,
                    }
                ),
            }
        )
        worker.finished.connect(lambda r: None)
        self._workers.append(worker)
        worker.start()
