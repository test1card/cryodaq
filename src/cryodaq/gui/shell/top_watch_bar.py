"""TopWatchBar — persistent header with 4 zones (Phase UI-1 v2 Block A).

Always visible across dashboard and overlay panels. Shows engine status,
active experiment + phase + elapsed, channel summary, and alarm count.

Pixel sizes (height, padding, zone widths) are first-pass guesses from
docs/PHASE_UI1_V2_WIREFRAME.md section 3 — calibrate on lab PC later.
"""

from __future__ import annotations

import copy
import html
import logging
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.core.gas_inventory_format import ABSENT, format_inventory
from cryodaq.core.phase_labels import PHASE_LABELS_RU
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.operator_components._visuals import (
    bounded_visible_text,
    plain_text_tooltip,
    safe_plain_text,
)
from cryodaq.gui.utils.plural import ru_plural
from cryodaq.gui.zmq_client import CLIENT_PROTOCOL_VERSION, gui_worker_poll_in_flight

logger = logging.getLogger(__name__)

_STALE_TIMEOUT_S = 30.0  # [calibrate] seconds with no reading → "ожидают"
_PRESENTATION_INTERVAL_MS = 500  # DESIGN: RULE-DATA-002 — at most 2 Hz
_FUTURE_SOURCE_TOLERANCE_S = 1.0
_PRESSURE_VITAL = "pressure"
_STATUS_EVIDENCE_RANK = {
    ChannelStatus.OK: 0,
    ChannelStatus.TIMEOUT: 1,
    ChannelStatus.UNDERRANGE: 2,
    ChannelStatus.OVERRANGE: 3,
    ChannelStatus.SENSOR_ERROR: 3,
}
_STATUS_LABELS_RU = {
    ChannelStatus.OK: "норма",
    ChannelStatus.TIMEOUT: "тайм-аут",
    ChannelStatus.UNDERRANGE: "ниже диапазона",
    ChannelStatus.OVERRANGE: "выше диапазона",
    ChannelStatus.SENSOR_ERROR: "ошибка датчика",
}


_UNKNOWN_STATUS_LABEL_RU = "неизвестный статус"
_EXPERIMENT_STATUS_MAX_ROWS = 128
_EXPERIMENT_STATUS_MAX_PHASES = 64
_EXPERIMENT_STATUS_MAX_TEXT = 4096
_EXPERIMENT_STATUS_LIVE_KEYS = frozenset(
    {
        "ok",
        "app_mode",
        "active_experiment",
        "current_phase",
        "phase_started_at",
        "phases",
        "run_records",
        "templates",
        "proto",
    }
)
_EXPERIMENT_STATUS_REPLAY_KEYS = _EXPERIMENT_STATUS_LIVE_KEYS | {
    "error",
    "replay_source",
    "replay_speed",
    "replay_session_id",
}
_LIVE_APP_MODES = frozenset({"experiment", "debug"})
_LIVE_EXPERIMENT_KEYS = frozenset(
    {
        "experiment_id",
        "name",
        "title",
        "template_id",
        "operator",
        "cryostat",
        "sample",
        "description",
        "notes",
        "start_time",
        "end_time",
        "status",
        "config_snapshot",
        "custom_fields",
        "report_enabled",
        "sections",
        "artifact_dir",
        "metadata_path",
        "retroactive",
    }
)
_REPLAY_EXPERIMENT_KEYS = frozenset(
    {
        "experiment_id",
        "title",
        "sample",
        "operator",
        "status",
        "start_time",
        "end_time",
        "description",
        "notes",
        "is_replay",
        "phase",
        "phase_started_at",
        "custom_fields",
    }
)
_PHASE_ROW_KEYS = frozenset({"phase", "started_at", "ended_at", "operator"})
_RUN_RECORD_KEYS = frozenset(
    {
        "record_id",
        "source_run_id",
        "source_tab",
        "source_module",
        "run_type",
        "status",
        "started_at",
        "finished_at",
        "parameters",
        "result_summary",
        "artifact_paths",
        "experiment_context",
    }
)
_TEMPLATE_KEYS = frozenset({"id", "name", "sections", "report_enabled", "report_sections", "custom_fields"})
_TEMPLATE_FIELD_KEYS = frozenset({"id", "label", "default"})


def _status_text(value: object, *, allow_empty: bool = False, max_chars: int = 256) -> bool:
    return bool(
        type(value) is str
        and (allow_empty or bool(value))
        and len(value) <= max_chars
        and (not value or value.isprintable())
    )


def _status_experiment_id(value: object) -> bool:
    return bool(type(value) is str and len(value) == 12 and all(char in "0123456789abcdef" for char in value))


def _status_time(value: object, *, allow_none: bool = False) -> bool:
    if value is None:
        return allow_none
    if not _status_text(value, max_chars=64):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _bounded_status_json(value: object, *, depth: int = 0) -> bool:
    if depth > 6:
        return False
    if value is None or type(value) is bool:
        return True
    if type(value) is int:
        return -(2**63) <= value <= 2**63 - 1
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is str:
        return len(value) <= _EXPERIMENT_STATUS_MAX_TEXT
    if type(value) is list:
        return len(value) <= _EXPERIMENT_STATUS_MAX_ROWS and all(
            _bounded_status_json(item, depth=depth + 1) for item in value
        )
    if type(value) is dict:
        return len(value) <= _EXPERIMENT_STATUS_MAX_ROWS and all(
            _status_text(key) and _bounded_status_json(item, depth=depth + 1) for key, item in value.items()
        )
    return False


def _valid_phase_rows(value: object) -> bool:
    if type(value) is not list or len(value) > _EXPERIMENT_STATUS_MAX_PHASES:
        return False
    for row in value:
        if type(row) is not dict or set(row) != _PHASE_ROW_KEYS:
            return False
        phase = row.get("phase")
        if (
            type(phase) is not str
            or phase not in PHASE_LABELS_RU
            or not _status_time(row.get("started_at"))
            or not _status_time(row.get("ended_at"), allow_none=True)
            or not _status_text(row.get("operator"), allow_empty=True)
        ):
            return False
    return True


def _valid_live_experiment(value: object) -> bool:
    if value is None:
        return True
    if type(value) is not dict or set(value) != _LIVE_EXPERIMENT_KEYS:
        return False
    sections = value.get("sections")
    return bool(
        _status_experiment_id(value.get("experiment_id"))
        and _status_text(value.get("name"))
        and _status_text(value.get("title"))
        and _status_text(value.get("template_id"))
        and _status_text(value.get("operator"), allow_empty=True)
        and _status_text(value.get("cryostat"), allow_empty=True)
        and _status_text(value.get("sample"), allow_empty=True)
        and _status_text(value.get("description"), allow_empty=True, max_chars=_EXPERIMENT_STATUS_MAX_TEXT)
        and _status_text(value.get("notes"), allow_empty=True, max_chars=_EXPERIMENT_STATUS_MAX_TEXT)
        and _status_time(value.get("start_time"))
        and value.get("end_time") is None
        and type(value.get("status")) is str
        and value.get("status") == "RUNNING"
        and _bounded_status_json(value.get("config_snapshot"))
        and _bounded_status_json(value.get("custom_fields"))
        and type(value.get("report_enabled")) is bool
        and type(sections) is list
        and len(sections) <= _EXPERIMENT_STATUS_MAX_PHASES
        and all(_status_text(section) for section in sections)
        and _status_text(value.get("artifact_dir"), allow_empty=True, max_chars=_EXPERIMENT_STATUS_MAX_TEXT)
        and _status_text(value.get("metadata_path"), allow_empty=True, max_chars=_EXPERIMENT_STATUS_MAX_TEXT)
        and type(value.get("retroactive")) is bool
    )


def _valid_replay_experiment(value: object) -> bool:
    if value is None:
        return True
    phase = value.get("phase") if type(value) is dict else None
    return bool(
        type(value) is dict
        and set(value) == _REPLAY_EXPERIMENT_KEYS
        and _status_experiment_id(value.get("experiment_id"))
        and _status_text(value.get("title"))
        and _status_text(value.get("sample"), allow_empty=True)
        and _status_text(value.get("operator"), allow_empty=True)
        and type(value.get("status")) is str
        and value.get("status") == "active"
        and _status_time(value.get("start_time"))
        and value.get("end_time") is None
        and _status_text(value.get("description"), allow_empty=True, max_chars=_EXPERIMENT_STATUS_MAX_TEXT)
        and _status_text(value.get("notes"), allow_empty=True, max_chars=_EXPERIMENT_STATUS_MAX_TEXT)
        and value.get("is_replay") is True
        and type(phase) is str
        and phase in PHASE_LABELS_RU
        and _status_time(value.get("phase_started_at"))
        and _bounded_status_json(value.get("custom_fields"))
    )


def _valid_run_records(value: object) -> bool:
    if type(value) is not list or len(value) > _EXPERIMENT_STATUS_MAX_ROWS:
        return False
    for row in value:
        if type(row) is not dict or set(row) != _RUN_RECORD_KEYS:
            return False
        artifacts = row.get("artifact_paths")
        if (
            not _status_text(row.get("record_id"))
            or not _status_text(row.get("source_run_id"))
            or not all(
                _status_text(row.get(field), allow_empty=True) for field in ("source_tab", "source_module", "run_type")
            )
            or not _status_text(row.get("status"))
            or not _status_time(row.get("started_at"))
            or not _status_time(row.get("finished_at"), allow_none=True)
            or not _bounded_status_json(row.get("parameters"))
            or not _bounded_status_json(row.get("result_summary"))
            or not _bounded_status_json(row.get("experiment_context"))
            or type(artifacts) is not list
            or len(artifacts) > _EXPERIMENT_STATUS_MAX_ROWS
            or any(not _status_text(path, max_chars=_EXPERIMENT_STATUS_MAX_TEXT) for path in artifacts)
        ):
            return False
    return True


def _valid_templates(value: object) -> bool:
    if type(value) is not list or len(value) > _EXPERIMENT_STATUS_MAX_ROWS:
        return False
    for template in value:
        if type(template) is not dict or set(template) != _TEMPLATE_KEYS:
            return False
        sections = template.get("sections")
        report_sections = template.get("report_sections")
        custom_fields = template.get("custom_fields")
        if (
            not _status_text(template.get("id"))
            or not _status_text(template.get("name"))
            or type(template.get("report_enabled")) is not bool
            or type(sections) is not list
            or len(sections) > _EXPERIMENT_STATUS_MAX_PHASES
            or any(not _status_text(section) for section in sections)
            or type(report_sections) is not list
            or len(report_sections) > _EXPERIMENT_STATUS_MAX_PHASES
            or any(not _status_text(section) for section in report_sections)
            or type(custom_fields) is not list
            or len(custom_fields) > _EXPERIMENT_STATUS_MAX_PHASES
        ):
            return False
        if any(
            type(field) is not dict
            or set(field) != _TEMPLATE_FIELD_KEYS
            or not _status_text(field.get("id"))
            or not _status_text(field.get("label"))
            or not _status_text(field.get("default"), allow_empty=True)
            for field in custom_fields
        ):
            return False
    return True


def decode_experiment_status(payload: object) -> dict | None:
    """Return one detached, exact live/replay experiment authority cut."""

    if type(payload) is not dict or payload.get("ok") is not True:
        return None
    if type(payload.get("proto")) is not int or payload.get("proto") != CLIENT_PROTOCOL_VERSION:
        return None
    app_mode = payload.get("app_mode")
    current_phase = payload.get("current_phase")
    if type(app_mode) is not str:
        return None
    if current_phase is not None and (type(current_phase) is not str or current_phase not in PHASE_LABELS_RU):
        return None
    if app_mode == "replay":
        active = payload.get("active_experiment")
        phases = payload.get("phases")
        run_records = payload.get("run_records")
        templates = payload.get("templates")
        speed = payload.get("replay_speed")
        if (
            set(payload) != _EXPERIMENT_STATUS_REPLAY_KEYS
            or payload.get("error") is not None
            or not _valid_replay_experiment(active)
            or not _valid_phase_rows(phases)
            or type(run_records) is not list
            or len(run_records) != 0
            or type(templates) is not list
            or len(templates) != 0
            or not _status_text(payload.get("replay_source"), max_chars=_EXPERIMENT_STATUS_MAX_TEXT)
            or type(speed) is not float
            or not math.isfinite(speed)
            or speed < 0.0
            or (
                payload.get("replay_session_id") is not None
                and (
                    type(payload["replay_session_id"]) is not str
                    or len(payload["replay_session_id"]) != 32
                    or any(character not in "0123456789abcdef" for character in payload["replay_session_id"])
                )
            )
            or not _status_time(payload.get("phase_started_at"), allow_none=True)
            or (
                active is not None
                and (current_phase != active["phase"] or payload.get("phase_started_at") != active["phase_started_at"])
            )
        ):
            return None
    elif app_mode in _LIVE_APP_MODES:
        active = payload.get("active_experiment")
        phase_started_at = payload.get("phase_started_at")
        phases = payload.get("phases")
        run_records = payload.get("run_records")
        if (
            set(payload) != _EXPERIMENT_STATUS_LIVE_KEYS
            or not _valid_live_experiment(active)
            or (app_mode == "debug" and active is not None)
            or (active is None and current_phase is not None)
            or not _valid_phase_rows(phases)
            or not _valid_run_records(run_records)
            or not _valid_templates(payload.get("templates"))
            or (active is None and (phase_started_at is not None or len(phases) != 0 or len(run_records) != 0))
            or (active is not None and current_phase is None and (phase_started_at is not None or len(phases) != 0))
            or (
                current_phase is not None
                and (
                    len(phases) == 0
                    or phases[-1]["phase"] != current_phase
                    or phases[-1]["ended_at"] is not None
                    or phase_started_at is None
                )
            )
            or (
                phase_started_at is not None
                and (
                    type(phase_started_at) not in (int, float)
                    or not math.isfinite(float(phase_started_at))
                    or float(phase_started_at) < 0.0
                )
            )
        ):
            return None
    else:
        return None
    return copy.deepcopy(payload)


def _presentation_status(status: object) -> ChannelStatus:
    """Project malformed transport status to the pessimistic UI state."""
    if isinstance(status, ChannelStatus):
        return status
    return ChannelStatus.SENSOR_ERROR


def _status_evidence_rank(status: object) -> int:
    return _STATUS_EVIDENCE_RANK[_presentation_status(status)]


def _status_label_ru(status: object) -> str:
    if isinstance(status, ChannelStatus):
        return _STATUS_LABELS_RU[status]
    return _UNKNOWN_STATUS_LABEL_RU


def _invalid_value_reason(key: str, reading: Reading) -> str | None:
    """Return a Russian reason when an OK-status vital is physically unusable."""
    if reading.status is not ChannelStatus.OK:
        return None
    try:
        value = float(reading.value)
    except (TypeError, ValueError):
        return "значение не является числом"
    if not math.isfinite(value):
        return "значение не является конечным"
    if key == _PRESSURE_VITAL and value <= 0:
        return "давление должно быть больше нуля"
    return None


def _usable_value(key: str, reading: Reading) -> float | None:
    if reading.is_usable() and _invalid_value_reason(key, reading) is None:
        return float(reading.value)
    return None


def _future_timestamp_at_receipt(reading: Reading, *, now: float | None = None) -> bool:
    """Flag source time that is implausibly ahead of this GUI host."""
    receipt_time = time.time() if now is None else now
    return reading.timestamp.timestamp() - receipt_time > _FUTURE_SOURCE_TOLERANCE_S


def _incoming_supersedes(
    current: Reading,
    current_future: bool,
    incoming: Reading,
    incoming_future: bool,
) -> bool:
    """Use source time normally and arrival order while either clock is untrusted."""
    return current_future or incoming_future or incoming.timestamp >= current.timestamp


@dataclass(frozen=True, slots=True)
class ReplayStatusAuthority:
    """Exact launcher/bridge cut allowed to publish replay status."""

    source: str
    speed: float
    session_id: str
    launcher_generation: int
    bridge_generation: int


@dataclass(slots=True)
class _PendingVitalCut:
    """O(1) human-presentation cut; persistence remains authoritative."""

    latest: Reading
    latest_future: bool
    latest_usable: Reading | None
    latest_usable_future: bool
    minimum: Reading | None
    maximum: Reading | None
    status_evidence: Reading
    invalid_value_evidence: Reading | None
    invalid_value_future: bool
    clock_skew_evidence: Reading | None
    count: int = 1

    @classmethod
    def from_reading(cls, key: str, reading: Reading, *, future_timestamp: bool) -> _PendingVitalCut:
        usable = reading if _usable_value(key, reading) is not None else None
        invalid = reading if _invalid_value_reason(key, reading) is not None else None
        return cls(
            latest=reading,
            latest_future=future_timestamp,
            latest_usable=usable,
            latest_usable_future=future_timestamp if usable is not None else False,
            minimum=usable,
            maximum=usable,
            status_evidence=reading,
            invalid_value_evidence=invalid,
            invalid_value_future=future_timestamp if invalid is not None else False,
            clock_skew_evidence=reading if future_timestamp else None,
        )

    def add(self, key: str, reading: Reading, *, future_timestamp: bool) -> None:
        self.count += 1
        if _incoming_supersedes(self.latest, self.latest_future, reading, future_timestamp):
            self.latest = reading
            self.latest_future = future_timestamp

        value = _usable_value(key, reading)
        if value is not None:
            if self.latest_usable is None or _incoming_supersedes(
                self.latest_usable,
                self.latest_usable_future,
                reading,
                future_timestamp,
            ):
                self.latest_usable = reading
                self.latest_usable_future = future_timestamp
            minimum = _usable_value(key, self.minimum) if self.minimum is not None else None
            maximum = _usable_value(key, self.maximum) if self.maximum is not None else None
            if minimum is None or value < minimum:
                self.minimum = reading
            if maximum is None or value > maximum:
                self.maximum = reading

        incoming_rank = _status_evidence_rank(reading.status)
        current_rank = _status_evidence_rank(self.status_evidence.status)
        if incoming_rank > current_rank or (
            incoming_rank == current_rank and reading.timestamp >= self.status_evidence.timestamp
        ):
            self.status_evidence = reading

        invalid_reason = _invalid_value_reason(key, reading)
        if invalid_reason is not None and (
            self.invalid_value_evidence is None
            or _incoming_supersedes(
                self.invalid_value_evidence,
                self.invalid_value_future,
                reading,
                future_timestamp,
            )
        ):
            self.invalid_value_evidence = reading
            self.invalid_value_future = future_timestamp
        if future_timestamp:
            self.clock_skew_evidence = reading


def _format_pressure(p: float) -> str:
    """Format pressure as compact scientific notation (X.Xe±Y).

    Cryo vacuum spans many orders of magnitude; the prior `f"{p:.2e}"`
    output `1.45e-06` wasted width on leading zeros in the exponent.
    This helper emits `1.5e-6` — same precision bucket, tighter glyph
    count. Non-positive values render as em-dash because pressure is
    log-quantity-only.
    """
    if not math.isfinite(p) or p <= 0:
        return "\u2014"
    mantissa, exp = f"{p:.1e}".split("e")
    return f"{mantissa}e{int(exp)}"


# Positionally fixed reference channels (design system invariant #21,
# MANIFEST.md decision #21). Т11 / Т12 are physically immovable on the
# second stage (nitrogen plate); cannot be relocated without dismantling
# the rheostat. All temperature channels are metrologically calibrated,
# but only these two qualify as fixed quantitative references for
# TopWatchBar physical-reference display.
SECOND_STAGE_CHANNEL = "Т12"  # U+0422 Cyrillic Т — 2-я ступень GM-cooler (~2.9 K floor)
N2_PLATE_CHANNEL = "Т11"  # U+0422 Cyrillic Т — азотная плита (~40 K floor)

# Derived, published by the molecular_counter analytics plugin.
_GAS_INVENTORY_CHANNEL = "analytics/molecular_counter/gas_inventory"


def _fmt_elapsed(start_iso: str) -> str:
    try:
        start = datetime.fromisoformat(start_iso).astimezone(UTC)
    except (TypeError, ValueError):
        return ""
    delta = datetime.now(UTC) - start
    total = max(0, int(delta.total_seconds()))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days:
        return f"{days}д {hours}ч {mins}мин"
    if hours:
        return f"{hours}ч {mins}мин"
    return f"{mins}мин"


class _ClickableLabel(QLabel):
    """QLabel that emits clicked() on left-mouse press."""

    clicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TopWatchBar(QWidget):
    """Persistent header bar — 4 zones, always visible."""

    experiment_clicked = Signal()
    alarms_clicked = Signal()
    experiment_status_received = Signal(dict)  # B.5: forward /status to dashboard

    def __init__(self, channel_manager: ChannelManager | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # DESIGN: invariant #1 — height = HEADER_HEIGHT (56), coupled to
        # TOOL_RAIL_WIDTH per RULE-SPACE-006 (corner square).
        self.setFixedHeight(theme.HEADER_HEIGHT)
        self.setObjectName("TopWatchBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            f"#TopWatchBar {{ background-color: {theme.SURFACE_PANEL}; "
            f"border-bottom: 1px solid {theme.BORDER_SUBTLE}; }}"
        )

        self._channel_mgr = channel_manager
        # Per-channel last-seen tracking: channel_id -> (monotonic_ts, status)
        self._channel_last_seen: dict[str, tuple[float, ChannelStatus]] = {}
        self._alarm_count: int | None = None
        # The composition root pins one transport domain before the first
        # asynchronous poll.  ``live`` accepts only experiment/debug cuts;
        # ``replay`` additionally requires the exact launcher/bridge authority.
        self._expected_app_mode_domain = "live"
        self._replay_authority: ReplayStatusAuthority | None = None
        self._engine_alive: bool | None = None
        self._last_experiment_full_text = "\u25cb Нет активного эксперимента"

        self._build_ui()
        self._build_persistent_context()
        # Cold start is deliberately empty.  Only an actual reading may add a
        # current channel state; otherwise the header must remain visibly
        # unavailable instead of manufacturing a brief green/OK interval.
        self._refresh_channels()

        # 1 Hz polling for zones 1, 2, 3
        self._fast_timer = QTimer(self)
        self._fast_timer.setInterval(1000)
        self._fast_timer.timeout.connect(self._poll_fast)
        self._fast_timer.start()

        # Kept solely as a stopped test-isolation handle for legacy shell
        # fixtures.  It has no callback, no poll command, and no sound role;
        # audible annunciation belongs only to AnnunciationController.
        self._slow_timer = QTimer(self)

        # 1 Hz channel summary refresh (cheap, just re-renders cache)
        self._channel_refresh_timer = QTimer(self)
        self._channel_refresh_timer.setInterval(1000)
        self._channel_refresh_timer.timeout.connect(self._refresh_channels)
        self._channel_refresh_timer.start()

        # B.4: one bounded presentation/stale tick for persistent vitals.
        # Ingestion remains full-rate; only human-readable repaint is capped.
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(_PRESENTATION_INTERVAL_MS)
        self._stale_timer.timeout.connect(self._flush_persistent_context)
        self._stale_timer.start()

        # One in-flight worker per poll stream — skip tick if previous
        # request still running (Finding 2, Block A.9).
        self._experiment_worker = None

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        layout.setSpacing(0)  # B.5.7.1: all gaps via _make_zone_sep wrapper

        # Zone 1: engine
        self._engine_label = QLabel("● Engine: —")
        self._engine_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(self._engine_label)

        layout.addWidget(self._make_zone_sep())

        # Zone 2: experiment + phase + elapsed (clickable) + time window echo
        self._exp_label = _ClickableLabel(self._last_experiment_full_text)
        self._exp_label.setTextFormat(Qt.TextFormat.PlainText)
        self._exp_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._exp_label.setMaximumWidth(220)
        self._exp_label.clicked.connect(self.experiment_clicked.emit)
        layout.addWidget(self._exp_label, stretch=1)

        # B.6: Mode badge (ЭКСПЕРИМЕНТ / ОТЛАДКА) — clickable (B.6.2)
        self._mode_badge = _ClickableLabel()
        self._mode_badge.setObjectName("modeBadge")
        self._mode_badge.setTextFormat(Qt.TextFormat.PlainText)
        self._update_mode_badge(None)
        self._mode_badge.clicked.connect(self._on_mode_badge_clicked)
        self._app_mode: str | None = None
        self._mode_switch_worker = None
        layout.addWidget(self._mode_badge)

        layout.addWidget(self._make_zone_sep())

        # Zone 3: channel summary
        self._channel_label = QLabel("● —/— норма")
        self._channel_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(self._channel_label)

        layout.addWidget(self._make_zone_sep())

        # Zone 4: alarms (clickable). No emoji per RULE-COPY-005 — text label only.
        self._alarms_label = _ClickableLabel(
            "\u0422\u0440\u0435\u0432\u043e\u0433\u0438: \u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445"
        )
        self._alarms_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._alarms_label.clicked.connect(self.alarms_clicked.emit)
        layout.addWidget(self._alarms_label)

    # ------------------------------------------------------------------
    # B.4: Persistent context strip
    # ------------------------------------------------------------------

    @staticmethod
    def _make_zone_sep() -> QWidget:
        """Zone separator: VLine in wrapper for consistent spacing."""
        container = QWidget()
        # Without explicit transparent background, Fusion palette paints
        # the wrapper + VLine frame with Window fill, producing visible
        # rectangles around the 1px divider.
        container.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(container)
        lay.setContentsMargins(theme.SPACE_2, 0, theme.SPACE_2, 0)
        lay.setSpacing(0)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedHeight(20)
        sep.setStyleSheet(f"color: {theme.BORDER}; max-width: 1px; background: transparent;")
        lay.addWidget(sep)
        return container

    def _set_experiment_text(self, full_text: str) -> None:
        """Set experiment label with elide + tooltip for long names."""
        full_text = safe_plain_text(full_text)
        self._last_experiment_full_text = full_text
        metrics = self._exp_label.fontMetrics()
        max_w = self._exp_label.maximumWidth()
        elided = metrics.elidedText(full_text, Qt.TextElideMode.ElideRight, max_w)
        self._exp_label.setTextFormat(Qt.TextFormat.PlainText)
        self._exp_label.setText(elided)
        self._exp_label.setToolTip(plain_text_tooltip(full_text))

    def _mark_experiment_status_unavailable(self) -> None:
        """Retain last evidence while visibly revoking current authority."""

        self._exp_label.setStyleSheet(f"color: {theme.STATUS_CAUTION};")
        self._exp_label.setToolTip(
            plain_text_tooltip(
                "Статус эксперимента недоступен",
                f"Последние принятые данные: {self._last_experiment_full_text}",
            )
        )
        self._update_mode_badge(None)

    def _build_persistent_context(self) -> None:
        """Add 4-value persistent context strip to the watch bar."""
        # v0.55.2 ds-007: route inline font sizes/weights through tokens.
        label_style = f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_XS}px;"
        value_style = (
            f"color: {theme.TEXT_PRIMARY}; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"font-family: '{theme.FONT_MONO}', monospace;"
        )

        self._context_frame = QFrame(self)
        self._context_frame.setObjectName("topWatchBarContext")
        # v0.55.2 ds-006: padding 2px 8px expressed via SPACE_1 // 2 + SPACE_2
        # (2 is the same micro-step we pin in sensor_cell.py; folding both
        # callsites onto SPACE_HALF is a v0.56 follow-up).
        self._context_frame.setStyleSheet(
            "#topWatchBarContext { "
            "background-color: transparent; "
            f"padding: {theme.SPACE_1 // 2}px {theme.SPACE_2}px; "
            "}"
        )
        ctx = QHBoxLayout(self._context_frame)
        ctx.setContentsMargins(theme.SPACE_2, theme.SPACE_1 // 2, theme.SPACE_2, theme.SPACE_1 // 2)
        ctx.setSpacing(theme.SPACE_3)

        # Pressure
        self._ctx_pressure_label = QLabel("\u0414\u0430\u0432\u043b\u0435\u043d\u0438\u0435")  # Давление
        self._ctx_pressure_label.setStyleSheet(label_style)
        self._ctx_pressure_value = QLabel("\u2014")
        self._ctx_pressure_value.setStyleSheet(value_style)
        ctx.addWidget(self._ctx_pressure_label)
        ctx.addWidget(self._ctx_pressure_value)

        ctx.addWidget(self._make_ctx_dot())

        # Gas inventory — a DERIVED cell, not a fourth physical reading. The
        # three physical readings remain exactly three and keep their fixed
        # relative order (pressure → Т12 → Т11); this sits between the first two
        # because it answers the question the gauge beside it cannot: whether
        # the pump is winning. On 2026-09-03 the pressure fell 31% over ten
        # hours while the chamber was gaining molecules the whole time.
        #
        # Marked as derived by the "~" prefix on its label, so it is never read
        # as a measured channel: it is computed from an operator-chosen sensor
        # set and is meaningless if that set is wrong.
        self._ctx_gas_label = QLabel("~ Газ")
        self._ctx_gas_label.setStyleSheet(label_style)
        self._ctx_gas_value = QLabel("\u2014")
        self._ctx_gas_value.setStyleSheet(value_style)
        # DESIGN: RULE-A11Y-003. STATUS_FAULT is 3.94:1 and fails AA body
        # contrast, so it never colours the value. The arrow carries the colour;
        # the digits stay TEXT_PRIMARY whatever the direction.
        self._ctx_gas_arrow = QLabel("")
        self._ctx_gas_arrow.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; font-size: {theme.FONT_SIZE_SM}px;")
        ctx.addWidget(self._ctx_gas_label)
        ctx.addWidget(self._ctx_gas_arrow)
        ctx.addWidget(self._ctx_gas_value)

        ctx.addWidget(self._make_ctx_dot())

        # Т12 is physically fixed on the second cryocooler stage.
        # The operator label names that location instead of implying a
        # computed minimum across the channel fleet.
        self._ctx_second_stage_label = QLabel("Т 2-й ступени")
        self._ctx_second_stage_label.setStyleSheet(label_style)
        self._ctx_second_stage_value = QLabel("\u2014")
        self._ctx_second_stage_value.setStyleSheet(value_style)
        ctx.addWidget(self._ctx_second_stage_label)
        ctx.addWidget(self._ctx_second_stage_value)

        ctx.addWidget(self._make_ctx_dot())

        # Т11 is physically fixed on the nitrogen plate. Subscript 2 via
        # U+2082 (₂) preserves the chemical formula in operator copy.
        self._ctx_n2_plate_label = QLabel("Т плиты N₂")
        self._ctx_n2_plate_label.setStyleSheet(label_style)
        self._ctx_n2_plate_value = QLabel("\u2014")
        self._ctx_n2_plate_value.setStyleSheet(value_style)
        ctx.addWidget(self._ctx_n2_plate_label)
        ctx.addWidget(self._ctx_n2_plate_value)

        # Insert after exp_label, before mode_badge
        # exp_label is at index 2, mode_badge at index 3
        main = self.layout()
        main.insertWidget(3, self._make_zone_sep())  # sep before context
        main.insertWidget(4, self._context_frame)
        main.insertWidget(5, self._make_zone_sep())  # sep after context

        # Physical-reference lock: track only Т11 and Т12 readings
        # (positionally fixed reference channels, design system invariant #21).
        # Other cold channels are metrologically valid but not positionally
        # fixed, so using them would allow T-min / T-max to shift between
        # experiments depending on the visible-channel set.
        self._latest_physical_temps: dict[str, tuple[Reading, bool]] = {}
        self._latest_pressure: tuple[Reading, bool] | None = None
        self._latest_vital_sources: dict[str, Reading] = {}
        self._latest_vital_source_future: dict[str, bool] = {}
        self._pending_vital_cuts: dict[str, _PendingVitalCut] = {}
        self._last_interval_cuts: dict[str, _PendingVitalCut] = {}
        for key in (_PRESSURE_VITAL, SECOND_STAGE_CHANNEL, N2_PLATE_CHANNEL):
            self._render_vital(key)

    def _render_gas_inventory(self, reading) -> None:
        """Show N/N₀ and its direction. Refuses rather than guessing."""

        value = getattr(reading, "value", None)
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            self._ctx_gas_value.setText(ABSENT)
            self._ctx_gas_arrow.setText("")
            return

        meta = getattr(reading, "metadata", None) or {}
        rate = meta.get("rate_pct_per_h")
        rate = float(rate) if isinstance(rate, (int, float)) and math.isfinite(float(rate)) else None

        # Shared formatter: the chrome rendered a deep pump-down as "0%" while
        # the analytics card said "-5.0 дек" for the same instant. Two places
        # showing one quantity must not be able to disagree.
        self._ctx_gas_value.setText(format_inventory(float(value)))
        if rate is None or abs(rate) < 0.2:
            self._ctx_gas_arrow.setText("")
            self._ctx_gas_arrow.setStyleSheet(
                f"color: {theme.MUTED_FOREGROUND}; font-size: {theme.FONT_SIZE_SM}px;"
            )
            return
        falling = rate < 0
        self._ctx_gas_arrow.setText("\u2193" if falling else "\u2191")
        colour = theme.STATUS_OK if falling else theme.STATUS_FAULT
        self._ctx_gas_arrow.setStyleSheet(f"color: {colour}; font-size: {theme.FONT_SIZE_SM}px;")

    @staticmethod
    def _make_ctx_dot() -> QLabel:
        """Middle dot separator for items within persistent context strip."""
        dot = QLabel(" \u00b7 ")  # · middle dot
        dot.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; font-size: {theme.FONT_SIZE_XS}px;")
        return dot

    # ------------------------------------------------------------------
    # Persistent context display updates
    # ------------------------------------------------------------------

    @staticmethod
    def _vital_name(key: str) -> str:
        return {
            _PRESSURE_VITAL: "Давление",
            SECOND_STAGE_CHANNEL: "Т 2-й ступени (Т12)",
            N2_PLATE_CHANNEL: "Т плиты N₂ (Т11)",
        }[key]

    def _vital_widget(self, key: str) -> QLabel:
        return {
            _PRESSURE_VITAL: self._ctx_pressure_value,
            SECOND_STAGE_CHANNEL: self._ctx_second_stage_value,
            N2_PLATE_CHANNEL: self._ctx_n2_plate_value,
        }[key]

    @staticmethod
    def _format_vital_value(key: str, value: float) -> str:
        if key == _PRESSURE_VITAL:
            formatted = _format_pressure(value)
            return formatted if formatted == "\u2014" else f"{formatted} мбар"
        return f"{value:.2f} K"

    def _last_usable_entry(self, key: str) -> tuple[Reading, bool] | None:
        if key == _PRESSURE_VITAL:
            return self._latest_pressure
        return self._latest_physical_temps.get(key)

    def _set_last_usable(self, key: str, reading: Reading, *, future_timestamp: bool) -> None:
        previous = self._last_usable_entry(key)
        if previous is not None and not _incoming_supersedes(previous[0], previous[1], reading, future_timestamp):
            return
        entry = (reading, future_timestamp)
        if key == _PRESSURE_VITAL:
            self._latest_pressure = entry
        else:
            self._latest_physical_temps[key] = entry

    @staticmethod
    def _source_time_text(reading: Reading) -> str:
        return reading.timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f UTC")

    @classmethod
    def _provenance_text(cls, reading: Reading) -> str:
        def plain(value: object) -> str:
            text = str(value).strip() or "не указан"
            # Qt tooltips auto-detect rich text.  Escape markup and replace
            # controls so an untrusted Reading identity stays literal text.
            return html.escape("".join(char if ord(char) >= 32 else "�" for char in text))

        instrument = plain(reading.instrument_id)
        channel = plain(reading.channel)
        return f"прибор: {instrument}; канал: {channel}; время: {cls._source_time_text(reading)}"

    def _render_vital(self, key: str, cut: _PendingVitalCut | None = None) -> None:
        """Render one bounded cut without hiding last-known numeric truth."""
        widget = self._vital_widget(key)
        source = self._latest_vital_sources.get(key)
        source_future = self._latest_vital_source_future.get(key, False)
        usable_entry = self._last_usable_entry(key)
        usable = usable_entry[0] if usable_entry is not None else None
        evidence = cut if cut is not None else self._last_interval_cuts.get(key)

        value_text = "\u2014" if usable is None else self._format_vital_value(key, float(usable.value))
        source_age = None if source is None else time.time() - source.timestamp.timestamp()
        stale = source_age is not None and not source_future and source_age > _STALE_TIMEOUT_S
        source_invalid = source is not None and _usable_value(key, source) is None
        interval_invalid = evidence is not None and (
            evidence.status_evidence.status is not ChannelStatus.OK or evidence.invalid_value_evidence is not None
        )
        interval_clock_skew = evidence is not None and evidence.clock_skew_evidence is not None
        clock_skew = source_future or interval_clock_skew
        disconnected = self._engine_alive is False

        range_visible = False
        if evidence is not None and evidence.minimum is not None and evidence.maximum is not None:
            minimum = self._format_vital_value(key, float(evidence.minimum.value))
            maximum = self._format_vital_value(key, float(evidence.maximum.value))
            range_visible = minimum != maximum

        text = value_text
        if range_visible:
            text += " ↕"
        if source_invalid:
            text += " · НЕТ ДАННЫХ"
        elif interval_invalid:
            text += " · СБОЙ ЗА ИНТ."
        if stale:
            text += " (устар.)"
        if disconnected:
            text += " · НЕТ СВЯЗИ"
        if clock_skew:
            text += " · РАССИНХР. ЧАСОВ"

        value_color = theme.TEXT_PRIMARY
        border = ""
        if source_invalid or interval_invalid:
            border = f" border-bottom: 2px solid {theme.STATUS_FAULT};"
        elif clock_skew:
            value_color = theme.STATUS_CAUTION
            border = f" border-bottom: 2px solid {theme.STATUS_CAUTION};"
        elif stale or disconnected or source is None:
            value_color = theme.TEXT_MUTED
        style = (
            f"color: {value_color}; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"font-family: '{theme.FONT_MONO}', monospace;"
            f"{border}"
        )

        details = [f"{self._vital_name(key)}. Отображаемое значение: {value_text}."]
        if usable is None:
            details.append("Пригодного измеренного значения ещё нет.")
        else:
            details.append(f"Происхождение отображаемого значения: {self._provenance_text(usable)}.")
        if source is None:
            details.append("Текущих данных нет.")
        else:
            details.append(f"Последний принятый источник: {self._provenance_text(source)}.")
            details.append(f"Статус источника: {_status_label_ru(source.status)}.")
            invalid_reason = _invalid_value_reason(key, source)
            if invalid_reason is not None:
                details.append(f"Причина непригодности: {invalid_reason}.")
        if stale and source_age is not None:
            details.append(f"Данные устарели: возраст {max(0.0, source_age):.1f} с; порог {_STALE_TIMEOUT_S:.0f} с.")
        if disconnected:
            details.append("Связь с Engine отсутствует; последнее пригодное значение сохранено.")
        if source_future:
            details.append(
                "Метка времени источника была более чем на "
                f"{_FUTURE_SOURCE_TOLERANCE_S:.0f} с впереди часов GUI при получении."
            )
        if evidence is not None:
            interval_parts = [f"отсчётов: {evidence.count}"]
            if evidence.minimum is not None and evidence.maximum is not None:
                interval_parts.extend(
                    (
                        f"минимум: {self._format_vital_value(key, float(evidence.minimum.value))}; "
                        f"время минимума: {self._source_time_text(evidence.minimum)}",
                        f"максимум: {self._format_vital_value(key, float(evidence.maximum.value))}; "
                        f"время максимума: {self._source_time_text(evidence.maximum)}",
                    )
                )
            interval_parts.append(
                f"худший статус: {_status_label_ru(evidence.status_evidence.status)}; "
                f"время статуса: {self._source_time_text(evidence.status_evidence)}"
            )
            if evidence.invalid_value_evidence is not None:
                invalid_reason = _invalid_value_reason(key, evidence.invalid_value_evidence)
                interval_parts.append(
                    f"непригодное значение: {invalid_reason}; "
                    f"время: {self._source_time_text(evidence.invalid_value_evidence)}"
                )
            if evidence.clock_skew_evidence is not None:
                interval_parts.append(
                    f"рассинхронизация часов; время источника: {self._source_time_text(evidence.clock_skew_evidence)}"
                )
            details.append(f"За интервал {_PRESENTATION_INTERVAL_MS} мс: {'; '.join(interval_parts)}.")
        if range_visible:
            details.append("Маркер ↕ означает видимый разброс за интервал.")
        description = " ".join(details)

        if widget.text() != text:
            widget.setText(text)
        if widget.styleSheet() != style:
            widget.setStyleSheet(style)
        accessible_name = f"{self._vital_name(key)}: {text}"
        if widget.accessibleName() != accessible_name:
            widget.setAccessibleName(accessible_name)
        if widget.accessibleDescription() != description:
            widget.setAccessibleDescription(description)
        if widget.toolTip() != description:
            widget.setToolTip(description)

    def _flush_persistent_context(self) -> None:
        """Render one latest-value cut at no more than two ticks per second."""
        pending, self._pending_vital_cuts = self._pending_vital_cuts, {}
        for key, cut in pending.items():
            previous = self._last_interval_cuts.get(key)
            if previous is None or _incoming_supersedes(
                previous.latest,
                previous.latest_future,
                cut.latest,
                cut.latest_future,
            ):
                self._last_interval_cuts[key] = cut

        for key in (_PRESSURE_VITAL, SECOND_STAGE_CHANNEL, N2_PLATE_CHANNEL):
            self._render_vital(key)

    def _update_pressure_display(self) -> None:
        self._render_vital(_PRESSURE_VITAL)

    def _update_physical_temp_display(self) -> None:
        """Render only the fixed T12/T11 references; never substitute channels."""
        self._render_vital(SECOND_STAGE_CHANNEL)
        self._render_vital(N2_PLATE_CHANNEL)

    def _stale_check_tick(self) -> None:
        """Compatibility hook: refresh stale state without draining a cut."""
        self._update_pressure_display()
        self._update_physical_temp_display()

    # ------------------------------------------------------------------
    # Reading ingestion (called from MainWindowV2._dispatch_reading)
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Ingest full-rate evidence; human-readable values repaint at <=2 Hz."""
        ch = reading.channel
        vital_key: str | None = None

        if ch.startswith("\u0422") and reading.unit == "K":
            # v0.55.4 A5 fix: get_all_visible() returns short IDs like
            # "\u04221"; the driver emits readings as "\u04221 <display suffix>".
            # _refresh_channels looks up the short id, so stamp under
            # the short id only \u2014 otherwise the seeded "\u04221" entry goes
            # stale after _STALE_TIMEOUT_S and the counter freezes at
            # "0/16 \u043d\u043e\u0440\u043c\u0430".
            short_id = ch.split(" ", 1)[0]
            self._channel_last_seen[short_id] = (
                time.monotonic(),
                _presentation_status(reading.status),
            )
            if short_id in (SECOND_STAGE_CHANNEL, N2_PLATE_CHANNEL):
                vital_key = short_id
        elif ch.endswith("/pressure"):
            vital_key = _PRESSURE_VITAL
        elif ch == _GAS_INVENTORY_CHANNEL:
            # Deliberately outside the _PendingVitalCut path. That machinery
            # exists to reconcile full-rate instrument samples with source-time
            # ordering and a 500 ms repaint; this arrives once a minute already
            # reconciled, and pushing it through would buy nothing and couple a
            # derived analytic to the physical-vital contract.
            self._render_gas_inventory(reading)
            return

        if vital_key is None:
            return
        future_timestamp = _future_timestamp_at_receipt(reading)
        pending = self._pending_vital_cuts.get(vital_key)
        if pending is None:
            pending = _PendingVitalCut.from_reading(vital_key, reading, future_timestamp=future_timestamp)
            self._pending_vital_cuts[vital_key] = pending
        else:
            pending.add(vital_key, reading, future_timestamp=future_timestamp)

        if _usable_value(vital_key, reading) is not None:
            self._set_last_usable(vital_key, reading, future_timestamp=future_timestamp)

        previous = self._latest_vital_sources.get(vital_key)
        previous_future = self._latest_vital_source_future.get(vital_key, False)
        is_newest = previous is None or _incoming_supersedes(previous, previous_future, reading, future_timestamp)
        if is_newest:
            self._latest_vital_sources[vital_key] = reading
            self._latest_vital_source_future[vital_key] = future_timestamp
            # RULE-INTER-006: invalid/fault truth is immediate and textual;
            # normal numeric motion still waits for the bounded tick.
            if _usable_value(vital_key, reading) is None:
                self._render_vital(vital_key, pending)

    # ------------------------------------------------------------------
    # Zone refresh
    # ------------------------------------------------------------------

    def _poll_fast(self) -> None:
        """Poll experiment status (zone 2). Skips if previous still in flight."""
        if gui_worker_poll_in_flight(self._experiment_worker):
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        expected_replay_authority = self._replay_authority if self._expected_app_mode_domain == "replay" else None
        worker = ZmqCommandWorker({"cmd": "experiment_status"}, parent=self, release_on_settle=True)
        # The completing worker is captured so the handler can prove it is
        # still the current one. Without that, a queued completion from a
        # superseded poll could render stale status over a newer result, and
        # nothing ever cleared the attribute.
        worker.finished.connect(
            lambda result, expected=expected_replay_authority, completed=worker: self._on_experiment_result(
                result, expected, completed
            )
        )
        # Started BEFORE the slot is claimed. `start()` raises when worker
        # admission is closed, and a QThread that never ran reports
        # isFinished() False forever -- so claiming the slot first would leave
        # it occupied permanently and every later tick would skip. Nothing is
        # lost by failing with the slot still free.
        worker.start()
        self._experiment_worker = worker

    def _on_experiment_result(
        self,
        result: dict,
        expected_replay_authority: ReplayStatusAuthority | None = None,
        completed: object | None = None,
    ) -> None:
        if completed is not None:
            if completed is not self._experiment_worker:
                # Superseded: a newer poll owns the display. Render nothing and
                # clear nothing -- clearing here would free the CURRENT worker's
                # slot and let the next tick start a second concurrent poll.
                return
            # Ours: release the slot by identity, so the next tick may poll and
            # so no destroyed wrapper is ever consulted again.
            self._experiment_worker = None
        accepted = decode_experiment_status(result)
        if accepted is None:
            self._mark_experiment_status_unavailable()
            return
        accepted_mode = accepted["app_mode"]
        accepted_domain = "replay" if accepted_mode == "replay" else "live"
        if accepted_domain != self._expected_app_mode_domain:
            self._mark_experiment_status_unavailable()
            return
        if self._expected_app_mode_domain == "replay":
            current_authority = self._replay_authority
            if (
                current_authority is None
                or expected_replay_authority != current_authority
                or accepted_mode != "replay"
                or accepted.get("replay_source") != current_authority.source
                or type(accepted.get("replay_speed")) is not float
                or accepted["replay_speed"] != current_authority.speed
                or accepted.get("replay_session_id") != current_authority.session_id
            ):
                self._mark_experiment_status_unavailable()
                return
        # B.5: only one detached, fully decoded authority cut may reach the
        # dashboard and MainWindow identity cache.
        self.experiment_status_received.emit(accepted)
        # B.6: update mode badge from the same accepted cut.
        self._update_mode_badge(accepted["app_mode"], accepted)
        # Zone 2 — experiment (zone 1 engine state is driven externally
        # via set_engine_state() so it stays consistent with the launcher
        # and the reading data flow).
        exp = accepted["active_experiment"]
        if exp is None:
            self._set_experiment_text("\u25cb Нет активного эксперимента")
            self._exp_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            return
        name = safe_plain_text(exp.get("name") or exp.get("title") or "\u2014")
        phase = accepted["current_phase"] or ""
        phase_label = safe_plain_text(PHASE_LABELS_RU.get(phase, phase))
        elapsed = _fmt_elapsed(exp["start_time"])
        parts = [f"\u25cf {name}"]
        if phase_label:
            parts.append(phase_label)
        if elapsed:
            parts.append(elapsed)
        self._set_experiment_text(" \u00b7 ".join(parts))
        self._exp_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY};")

    def _refresh_channels(self) -> None:
        """Re-render zone 3 using ChannelManager visible channels as denominator."""
        if self._channel_mgr is None:
            self._channel_label.setText("◇ Данные каналов недоступны")
            self._channel_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            return

        visible_ids = [ch for ch in self._channel_mgr.get_all_visible() if ch.startswith("Т")]
        total = len(visible_ids)
        if total == 0:
            self._channel_label.setText("◇ Нет настроенных каналов")
            self._channel_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            return

        now = time.monotonic()
        ok_count = 0
        non_ok = 0
        waiting = 0
        worst = ChannelStatus.OK
        for ch in visible_ids:
            entry = self._channel_last_seen.get(ch)
            if entry is None or (now - entry[0]) > _STALE_TIMEOUT_S:
                waiting += 1
                continue
            status = entry[1]
            if status == ChannelStatus.OK:
                ok_count += 1
            else:
                non_ok += 1
                if status in (ChannelStatus.SENSOR_ERROR, ChannelStatus.TIMEOUT):
                    worst = ChannelStatus.SENSOR_ERROR
                elif worst != ChannelStatus.SENSOR_ERROR and status in (
                    ChannelStatus.OVERRANGE,
                    ChannelStatus.UNDERRANGE,
                ):
                    worst = ChannelStatus.OVERRANGE

        if non_ok:
            color = {
                ChannelStatus.OVERRANGE: theme.STATUS_CAUTION,
                ChannelStatus.SENSOR_ERROR: theme.STATUS_FAULT,
            }.get(worst, theme.TEXT_MUTED)
            cue = "▲" if worst is ChannelStatus.OVERRANGE else "■"
        elif waiting:
            color = theme.STATUS_STALE
            cue = "◇"
        else:
            color = theme.STATUS_OK
            cue = "●"

        if waiting == total:
            text = f"{cue} Нет текущих данных · {waiting} ожидают"
        elif waiting:
            text = f"{cue} {ok_count}/{total} текущих"
        else:
            text = f"{cue} {ok_count}/{total} норма"
        if non_ok > 0:
            text += f" · {non_ok} вне нормы"
        if waiting > 0 and waiting != total:
            waits = ru_plural(waiting, "ожидает", "ожидают", "ожидают")
            text += f" · {waiting} {waits}"
        # Item 13: tooltip explains the count breakdown.
        tooltip_parts = [f"{total} каналов температуры"]
        tooltip_parts.append(f"{ok_count} в норме")
        if waiting:
            tooltip_parts.append(f"{waiting} {ru_plural(waiting, 'ожидает', 'ожидают', 'ожидают')} первого показания")
        if non_ok:
            tooltip_parts.append(f"{non_ok} вне нормы")
        self._channel_label.setText(text)
        self._channel_label.setToolTip(", ".join(tooltip_parts))
        self._channel_label.setStyleSheet(f"color: {color};")

    # ------------------------------------------------------------------
    # External setters (for direct injection from MainWindowV2 dispatchers)
    # ------------------------------------------------------------------

    def set_engine_state(self, alive: bool) -> None:
        """Update zone 1 from authoritative external source.

        Called by MainWindowV2 (which knows whether readings are flowing)
        and by the launcher (which owns the engine subprocess lifecycle).
        Single source of truth — no internal polling for engine state.
        """
        self._engine_alive = bool(alive)
        if self._engine_alive:
            self._engine_label.setText("● Engine: работает")
            self._engine_label.setStyleSheet(f"color: {theme.STATUS_OK};")
        else:
            self._engine_label.setText("● Engine: нет связи")
            self._engine_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")
        for key in (_PRESSURE_VITAL, SECOND_STAGE_CHANNEL, N2_PLATE_CHANNEL):
            self._render_vital(key)

    def set_replay_mode(self, replay: bool) -> None:
        """Pin archive/replay truth before the first asynchronous status poll."""

        if type(replay) is not bool:
            raise TypeError("replay mode must be an exact bool")
        self._expected_app_mode_domain = "replay" if replay else "live"
        self._replay_authority = None
        self._mark_experiment_status_unavailable()

    def bind_replay_authority(
        self,
        *,
        source: str,
        speed: float,
        session_id: str,
        launcher_generation: int,
        bridge_generation: int,
    ) -> None:
        """Bind replay rendering to one immutable launcher/bridge authority cut."""

        if (
            type(source) is not str
            or not source
            or len(source) > _EXPERIMENT_STATUS_MAX_TEXT
            or not source.isprintable()
            or type(speed) is not float
            or not math.isfinite(speed)
            or speed < 0.0
            or type(session_id) is not str
            or len(session_id) != 32
            or any(character not in "0123456789abcdef" for character in session_id)
            or type(launcher_generation) is not int
            or launcher_generation < 0
            or type(bridge_generation) is not int
            or bridge_generation < 0
        ):
            raise ValueError("replay status authority is invalid")
        self._expected_app_mode_domain = "replay"
        self._replay_authority = ReplayStatusAuthority(
            source,
            speed,
            session_id,
            launcher_generation,
            bridge_generation,
        )
        self._mark_experiment_status_unavailable()

    def invalidate_replay_authority(self) -> None:
        """Synchronously revoke a replay cut before producer/bridge turnover."""

        self._replay_authority = None
        if self._expected_app_mode_domain == "replay":
            self._mark_experiment_status_unavailable()

    def _update_mode_badge(self, app_mode: str | None, result: dict | None = None) -> None:
        """Update mode badge from app_mode field in /status response."""
        self._mode_badge.setTextFormat(Qt.TextFormat.PlainText)
        if app_mode is not None and type(app_mode) is not str:
            app_mode = None
            result = None
        if self._expected_app_mode_domain == "replay" and app_mode != "replay":
            app_mode = "replay"
            result = None
        self._app_mode = app_mode
        if app_mode is None:
            self._mode_badge.setText(
                "\u0420\u0435\u0436\u0438\u043c: \u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445"
            )
            self._mode_badge.setStyleSheet(
                f"#modeBadge {{ background-color: {theme.SURFACE_MUTED}; "
                f"color: {theme.MUTED_FOREGROUND}; "
                f"border: 1px solid {theme.BORDER_SUBTLE}; "
                f"border-radius: {theme.RADIUS_SM}px; "
                f"padding: {theme.SPACE_1}px {theme.SPACE_3}px; }}"
            )
            self._mode_badge.setVisible(True)
            return
        # Authoritative mode is absent, not inferred: unavailable remains visible.
        # DESIGN: cryodaq-primitives/top-watch-bar.md ModeBadge reference +
        # invariant #5 "Mode badge always visible".
        # Phase III.A: "Эксперимент" renders as low-emphasis identifier
        # (SURFACE_ELEVATED chip with BORDER_SUBTLE) — mode badge is a
        # state identifier, not a safety indicator. "Отладка" keeps
        # STATUS_CAUTION foreground because it IS an operator-attention
        # signal (data are not archived). "REPLAY" uses STATUS_WARNING
        # (amber) — non-production data, operator must notice immediately.
        base_style = (
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: {theme.SPACE_1}px {theme.SPACE_3}px; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_LABEL_SIZE}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
        )
        if app_mode == "experiment":
            self._mode_badge.setText("Эксперимент")
            self._mode_badge.setStyleSheet(
                f"#modeBadge {{ "
                f"background-color: {theme.SURFACE_ELEVATED}; "
                f"color: {theme.FOREGROUND}; "
                f"border: 1px solid {theme.BORDER_SUBTLE}; "
                f"{base_style}"
                f"}}"
            )
            self._mode_badge.setVisible(True)
        elif app_mode == "debug":
            self._mode_badge.setText("Отладка")
            self._mode_badge.setStyleSheet(
                f"#modeBadge {{ "
                f"background-color: {theme.SURFACE_ELEVATED}; "
                f"color: {theme.STATUS_CAUTION}; "
                f"border: 1px solid {theme.STATUS_CAUTION}; "
                f"{base_style}"
                f"}}"
            )
            self._mode_badge.setVisible(True)
        elif app_mode == "replay":
            from pathlib import Path

            src_name = ""
            speed_suffix = ""
            tooltip_lines = ["REPLAY"]
            if type(result) is dict:
                src = result.get("replay_source", "")
                if type(src) is str and src:
                    raw_name = Path(src).name
                    src_name, full_name = bounded_visible_text(raw_name, limit=80)
                    tooltip_lines.append(f"Источник: {full_name}")
                spd = result.get("replay_speed")
                if type(spd) is float and math.isfinite(spd) and spd >= 0.0:
                    if spd == 0.0:
                        speed_suffix = " @ MAX"
                        tooltip_lines.append("Скорость: максимум")
                    else:
                        speed_suffix = f" @ {spd:g}x"
                        tooltip_lines.append(f"Скорость: {spd:g}x")
            badge_text = f"REPLAY{f': {src_name}' if src_name else ''}{speed_suffix}"
            self._mode_badge.setText(badge_text)
            self._mode_badge.setToolTip(plain_text_tooltip(*tooltip_lines))
            self._mode_badge.setStyleSheet(
                f"#modeBadge {{ "
                f"background-color: {theme.SURFACE_ELEVATED}; "
                f"color: {theme.STATUS_CAUTION}; "
                f"border: 1px solid {theme.STATUS_CAUTION}; "
                f"{base_style}"
                f"}}"
            )
            self._mode_badge.setVisible(True)
        else:
            logger.warning("Unknown app_mode value: %s", app_mode)
            self._mode_badge.setText(
                "\u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u044b\u0439 \u0440\u0435\u0436\u0438\u043c"
            )
            self._mode_badge.setStyleSheet(
                f"#modeBadge {{ background-color: {theme.SURFACE_ELEVATED}; "
                f"color: {theme.STATUS_CAUTION}; "
                f"border: 1px solid {theme.STATUS_CAUTION}; "
                f"border-radius: {theme.RADIUS_SM}px; "
                f"padding: {theme.SPACE_1}px {theme.SPACE_3}px; }}"
            )
            self._mode_badge.setVisible(True)

    # ------------------------------------------------------------------
    # Mode badge click → confirmation → ZMQ command (B.6.2)
    # ------------------------------------------------------------------

    def _on_mode_badge_clicked(self) -> None:
        if self._app_mode not in ("experiment", "debug"):
            logger.warning("Mode badge clicked but app_mode unknown: %s", self._app_mode)
            return
        if gui_worker_poll_in_flight(self._mode_switch_worker):
            return  # command in flight

        from PySide6.QtWidgets import QMessageBox

        if self._app_mode == "experiment":
            target = "debug"
            title = "\u041f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0438\u0442\u044c \u0432 \u0440\u0435\u0436\u0438\u043c \u041e\u0442\u043b\u0430\u0434\u043a\u0430?"  # noqa: E501
            body = (
                "\u0412 \u0440\u0435\u0436\u0438\u043c\u0435 \u041e\u0442\u043b\u0430\u0434\u043a\u0430 "  # noqa: E501
                "\u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0430 \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442\u0430 "  # noqa: E501
                "\u043d\u0435 \u0441\u043e\u0437\u0434\u0430\u0451\u0442\u0441\u044f, "
                "\u0430\u0440\u0445\u0438\u0432\u043d\u044b\u0435 \u0437\u0430\u043f\u0438\u0441\u0438 "  # noqa: E501
                "\u0438 \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0435 "  # noqa: E501
                "\u043e\u0442\u0447\u0451\u0442\u044b \u043d\u0435 \u0444\u043e\u0440\u043c\u0438\u0440\u0443\u044e\u0442\u0441\u044f."  # noqa: E501
            )
        else:
            target = "experiment"
            title = "\u041f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0438\u0442\u044c \u0432 \u0440\u0435\u0436\u0438\u043c \u042d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442?"  # noqa: E501
            body = (
                "\u0412 \u0440\u0435\u0436\u0438\u043c\u0435 \u042d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442 "  # noqa: E501
                "\u0441\u043e\u0437\u0434\u0430\u044e\u0442\u0441\u044f \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0438, "  # noqa: E501
                "\u0430\u0440\u0445\u0438\u0432\u043d\u044b\u0435 \u0437\u0430\u043f\u0438\u0441\u0438 "  # noqa: E501
                "\u0438 \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0435 "  # noqa: E501
                "\u043e\u0442\u0447\u0451\u0442\u044b."
            )

        dlg = QMessageBox(self)
        dlg.setWindowTitle(title)
        dlg.setText(body)
        btn_cancel = dlg.addButton(
            "\u041e\u0442\u043c\u0435\u043d\u0430",  # Отмена
            QMessageBox.ButtonRole.RejectRole,
        )
        dlg.addButton(
            "\u041f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0438\u0442\u044c",  # Переключить
            QMessageBox.ButtonRole.AcceptRole,
        )
        dlg.setDefaultButton(btn_cancel)
        dlg.exec()
        if dlg.clickedButton() == btn_cancel:
            return

        self._mode_badge.setCursor(Qt.CursorShape.WaitCursor)
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._mode_switch_worker = ZmqCommandWorker({"cmd": "set_app_mode", "app_mode": target}, parent=self)
        self._mode_switch_worker.finished.connect(self._on_mode_switch_result)
        self._mode_switch_worker.start()

    def _on_mode_switch_result(self, result: dict) -> None:
        self._mode_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        if not result.get("ok"):
            from PySide6.QtWidgets import QMessageBox

            error = result.get(
                "error",
                "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0441\u043c\u0435\u043d\u0438\u0442\u044c \u0440\u0435\u0436\u0438\u043c.",  # noqa: E501
            )
            QMessageBox.warning(self, "\u041e\u0448\u0438\u0431\u043a\u0430", str(error))

    def closeEvent(self, event):  # noqa: ANN001
        super().closeEvent(event)

    def set_alarm_summary(self, n: int, worst_level: str) -> None:
        self._alarm_count = max(0, int(n))
        if self._alarm_count == 0:
            self._alarms_label.setText("Тревоги: 0")
            self._alarms_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        else:
            verb = ru_plural(self._alarm_count, "активна", "активны", "активны")
            self._alarms_label.setText(f"Тревоги: {self._alarm_count} {verb}")
            color = {
                "INFO": theme.STATUS_INFO,
                "CAUTION": theme.STATUS_CAUTION,
                "CRITICAL": theme.STATUS_FAULT,
                "UNKNOWN": theme.STATUS_FAULT,
            }.get(str(worst_level).upper(), theme.STATUS_FAULT)
            self._alarms_label.setStyleSheet(f"color: {color};")

    def set_alarm_available(self, available: bool) -> None:
        if available:
            return
        self._alarm_count = None
        self._alarms_label.setText(
            "\u0422\u0440\u0435\u0432\u043e\u0433\u0438: \u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445"
        )
        self._alarms_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
