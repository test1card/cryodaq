"""«История охлаждений» card + live verdict badge (Task 8b, GUI half).

GUI surface for the cooldown-baseline feature (backend Task 8a). Reads
per-cooldown fingerprints from ``data/cooldown_history/`` via
``analytics.cooldown_fingerprint`` and compares against the pinned golden
baseline via ``analytics.cooldown_compare``. No engine round-trip — the
history dir is a plain local directory of JSON files, so the card reads and
the pin action writes ``baseline.json`` directly through the backend module.

Two widgets:

- :class:`CooldownBaselineCard` — table of stored fingerprints (date,
  duration, T_cold_final, time-to-base, verdict vs golden), a pin-as-baseline
  action, and a delta-vs-baseline readout for the selected entry. Lives in
  the Архив overlay.
- :class:`CooldownVerdictBadge` — compact ok/degraded/unknown chip for the
  Аналитика view; hidden when the feature is disabled or no baseline is set.

Graceful degradation: ``cooldown_baseline`` disabled or empty history → the
card shows an informative empty state and the badge stays hidden.

All colors/sizes/fonts come from ``theme`` tokens (RULE-COLOR-010 /
RULE-TYPO-007 / RULE-SPACE-001). Named ``*_baseline_card`` to avoid a Python
collision with the unrelated F3 ``CooldownHistoryWidget`` (duration plot).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.analytics.cooldown_compare import DEFAULT_THRESHOLDS, compare
from cryodaq.analytics.cooldown_fingerprint import (
    CooldownFingerprint,
    get_baseline,
    list_fingerprints,
    set_baseline,
)
from cryodaq.gui import theme

logger = logging.getLogger(__name__)

_ID_ROLE = int(Qt.ItemDataRole.UserRole)

_TABLE_COLUMNS: tuple[str, ...] = (
    "Дата",
    "Длит., ч",
    "T_хол, К",
    "До базы, ч",
    "Вердикт",
)

# ok / degraded / unknown → (Russian label, status color token)
_VERDICT_LABEL: dict[str, str] = {
    "ok": "НОРМА",
    "degraded": "ДЕГРАДАЦИЯ",
    "unknown": "НЕТ ДАННЫХ",
}
_VERDICT_COLOR: dict[str, str] = {
    "ok": theme.STATUS_OK,
    "degraded": theme.STATUS_WARNING,
    "unknown": theme.STATUS_STALE,
}


# --------------------------------------------------------------------------
# Config / formatting helpers
# --------------------------------------------------------------------------


def _load_baseline_cfg(config_path: Path | None = None) -> dict:
    """``cooldown_baseline`` block from plugins.yaml; {} on any failure."""
    try:
        import yaml

        from cryodaq.paths import get_config_dir

        path = config_path or (get_config_dir() / "plugins.yaml")
        if not path.exists():
            return {}
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return raw.get("cooldown_baseline", {}) or {}
    except Exception as exc:  # noqa: BLE001 — config read must never raise
        logger.error("Ошибка чтения cooldown_baseline из plugins.yaml: %s", exc)
        return {}


def _default_history_dir() -> Path:
    from cryodaq.paths import get_data_dir

    return get_data_dir() / "cooldown_history"


def _fmt_h(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}"


def _fmt_k(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f}"


def _fmt_ts(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return "—"


def _fmt_signed(v: float | None, unit: str) -> str:
    return "—" if v is None else f"{v:+.1f} {unit}"


def _badge_verdict(
    latest: CooldownFingerprint,
    baseline: CooldownFingerprint,
    thresholds: dict[str, float],
) -> str:
    """ok / degraded / unknown for the latest cooldown vs baseline."""
    cmp = compare(latest, baseline, thresholds=thresholds)
    if (
        cmp.time_to_base_verdict == "unknown"
        and cmp.ultimate_vacuum_verdict == "unknown"
    ):
        return "unknown"
    return cmp.overall


def _label_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
    return font


def _title_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_SIZE_XL)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


def _mono_font() -> QFont:
    font = QFont(theme.FONT_MONO)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return font


def _style_pin_button(btn: QPushButton) -> None:
    # DESIGN: RULE-COLOR-004 — pin is a UI activation, uses ACCENT not STATUS_OK.
    btn.setStyleSheet(
        f"QPushButton {{"
        f" background-color: {theme.ACCENT};"
        f" color: {theme.ON_ACCENT};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f" border-radius: {theme.RADIUS_MD}px;"
        f" padding: {theme.SPACE_1}px {theme.SPACE_3}px;"
        f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        f"}}"
        f" QPushButton:disabled {{"
        f" background-color: {theme.SURFACE_MUTED};"
        f" color: {theme.MUTED_FOREGROUND};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f"}}"
    )


# --------------------------------------------------------------------------
# Card
# --------------------------------------------------------------------------


class CooldownBaselineCard(QWidget):
    """«История охлаждений» card for the Архив overlay (Task 8b)."""

    baseline_pinned = Signal(str)  # fingerprint_id

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        history_dir: Path | None = None,
        enabled: bool | None = None,
        config_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._history_dir = Path(history_dir) if history_dir else _default_history_dir()
        cfg = _load_baseline_cfg(config_path)
        # Strict-bool: a quoted YAML `enabled: "false"` must NOT enable the
        # card (mirrors the engine-side watchdog fix, commit b132fab).
        self._enabled = (
            cfg.get("enabled", False) is True if enabled is None else bool(enabled)
        )
        self._thresholds = {**DEFAULT_THRESHOLDS, **dict(cfg.get("thresholds") or {})}
        self._entries: list[CooldownFingerprint] = []
        self._baseline_id: str | None = None
        self._populated = False

        self.setObjectName("cooldownBaselineCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#cooldownBaselineCard {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )
        self._build_ui()
        # Populate is deferred to the first showEvent: the Архив overlay is
        # built on demand, so this keeps the fingerprint glob+parse off the
        # shell-construction path and off users who never open the card.
        # ponytail: sync FS read on the GUI thread, bounded by first-show +
        # local disk; move list+compare to a QThread worker if the history
        # dir ever lives on network storage.

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 — Qt override
        super().showEvent(event)
        if not self._populated:
            self._populated = True
            self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        root.setSpacing(theme.SPACE_2)

        title = QLabel("ИСТОРИЯ ОХЛАЖДЕНИЙ")
        title.setFont(_title_font())
        title.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
            f" letter-spacing: 1px;"
        )
        root.addWidget(title)

        self._empty_label = QLabel("")
        self._empty_label.setFont(_label_font())
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
            f" border: none; padding: {theme.SPACE_4}px;"
        )
        root.addWidget(self._empty_label)

        self._table = QTableWidget(0, len(_TABLE_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_TABLE_COLUMNS))
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setFont(_label_font())
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" color: {theme.FOREGROUND};"
            f" gridline-color: {theme.BORDER_SUBTLE};"
            f" border: none;"
            f"}} "
            f"QHeaderView::section {{"
            f" background-color: {theme.SURFACE_MUTED};"
            f" color: {theme.MUTED_FOREGROUND};"
            f" border: 0px;"
            f" border-bottom: 1px solid {theme.BORDER_SUBTLE};"
            f" padding: {theme.SPACE_1}px {theme.SPACE_2}px;"
            f"}}"
        )
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self._table, stretch=1)

        self._delta_label = QLabel("—")
        self._delta_label.setFont(_label_font())
        self._delta_label.setWordWrap(True)
        self._delta_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        root.addWidget(self._delta_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(theme.SPACE_2)
        actions.addStretch()
        self._pin_btn = QPushButton("Сделать эталонным")
        _style_pin_button(self._pin_btn)
        self._pin_btn.clicked.connect(self._on_pin_clicked)
        actions.addWidget(self._pin_btn)
        root.addLayout(actions)

    # ------------------------------------------------------------------
    # Data / refresh
    # ------------------------------------------------------------------

    def entries(self) -> list[CooldownFingerprint]:
        return list(self._entries)

    def refresh(self) -> None:
        """Reload fingerprints + baseline pointer from disk and repopulate."""
        if not self._enabled:
            self._entries = []
            self._baseline_id = None
            self._show_empty("Функция базового охлаждения отключена.")
            return
        self._entries = sorted(
            list_fingerprints(self._history_dir),
            key=lambda fp: fp.cooldown_start_ts,
            reverse=True,
        )
        base = get_baseline(self._history_dir)
        self._baseline_id = base.fingerprint_id if base else None
        if not self._entries:
            self._show_empty("История охлаждений пуста.")
            return
        self._empty_label.setVisible(False)
        self._table.setVisible(True)
        self._populate_table()

    def _show_empty(self, message: str) -> None:
        self._empty_label.setText(message)
        self._empty_label.setVisible(True)
        self._table.setVisible(False)
        self._table.setRowCount(0)
        self._delta_label.setText("—")
        self._pin_btn.setEnabled(False)

    def _populate_table(self) -> None:
        baseline = get_baseline(self._history_dir)
        self._table.setRowCount(len(self._entries))
        for row, fp in enumerate(self._entries):
            self._set_cell(row, 0, _fmt_ts(fp.cooldown_start_ts), fid=fp.fingerprint_id)
            self._set_cell(row, 1, _fmt_h(fp.duration_h), mono=True)
            self._set_cell(row, 2, _fmt_k(fp.T_cold_final), mono=True)
            self._set_cell(row, 3, _fmt_h(fp.time_to_base_h), mono=True)
            self._set_verdict_cell(row, 4, fp, baseline)
        if self._table.rowCount() > 0:
            self._table.selectRow(0)

    def _set_cell(
        self, row: int, col: int, text: str, *, mono: bool = False, fid: str | None = None
    ) -> None:
        item = QTableWidgetItem(text)
        if mono:
            item.setFont(_mono_font())
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if fid is not None:
            item.setData(_ID_ROLE, fid)
        self._table.setItem(row, col, item)

    def _set_verdict_cell(
        self,
        row: int,
        col: int,
        fp: CooldownFingerprint,
        baseline: CooldownFingerprint | None,
    ) -> None:
        if baseline is None:
            text, color = "нет эталона", theme.MUTED_FOREGROUND
        elif fp.fingerprint_id == baseline.fingerprint_id:
            text, color = "ЭТАЛОН", theme.ACCENT
        else:
            verdict = _badge_verdict(fp, baseline, self._thresholds)
            text = _VERDICT_LABEL[verdict]
            color = _VERDICT_COLOR[verdict]
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setForeground(_qcolor(color))
        self._table.setItem(row, col, item)

    # ------------------------------------------------------------------
    # Selection / delta
    # ------------------------------------------------------------------

    def select_fingerprint(self, fingerprint_id: str) -> bool:
        for row, fp in enumerate(self._entries):
            if fp.fingerprint_id == fingerprint_id:
                self._table.selectRow(row)
                return True
        return False

    def _selected_entry(self) -> CooldownFingerprint | None:
        model = self._table.selectionModel()
        rows = model.selectedRows() if model else []
        if not rows:
            return None
        idx = rows[0].row()
        if idx < 0 or idx >= len(self._entries):
            return None
        return self._entries[idx]

    def _on_selection_changed(self) -> None:
        entry = self._selected_entry()
        self._pin_btn.setEnabled(entry is not None)
        self._update_delta(entry)

    def _update_delta(self, entry: CooldownFingerprint | None) -> None:
        if entry is None:
            self._delta_label.setText("—")
            return
        baseline = get_baseline(self._history_dir)
        if baseline is None:
            self._delta_label.setText("Эталонное охлаждение не задано.")
            return
        if entry.fingerprint_id == baseline.fingerprint_id:
            self._delta_label.setText("Выбранное охлаждение — эталон.")
            return
        cmp = compare(entry, baseline, thresholds=self._thresholds)
        parts = [
            f"Δ до базы: {_fmt_signed(cmp.time_to_base_delta_h, 'ч')}",
            f"Δ длит.: {_fmt_signed(cmp.duration_delta_h, 'ч')}",
            f"Δ T_хол: {_fmt_signed(cmp.T_cold_final_delta_K, 'К')}",
        ]
        if cmp.ultimate_vacuum_delta_decades is not None:
            parts.append(f"Δ вакуум: {cmp.ultimate_vacuum_delta_decades:+.1f} дек.")
        self._delta_label.setText("   ".join(parts))

    def _on_pin_clicked(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        set_baseline(entry.fingerprint_id, self._history_dir)
        self.baseline_pinned.emit(entry.fingerprint_id)
        self.refresh()
        self.select_fingerprint(entry.fingerprint_id)


# --------------------------------------------------------------------------
# Badge
# --------------------------------------------------------------------------


class CooldownVerdictBadge(QLabel):
    """Compact ok/degraded/unknown chip for the Аналитика view (Task 8b).

    Compares the latest stored fingerprint against the golden baseline.
    Hidden when the feature is disabled, no baseline is pinned, or the
    history is empty — :meth:`verdict` returns ``None`` in that state.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        history_dir: Path | None = None,
        enabled: bool | None = None,
        config_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._history_dir = Path(history_dir) if history_dir else _default_history_dir()
        cfg = _load_baseline_cfg(config_path)
        # Strict-bool: quoted YAML `enabled: "false"` must NOT enable the badge.
        self._enabled = (
            cfg.get("enabled", False) is True if enabled is None else bool(enabled)
        )
        self._thresholds = {**DEFAULT_THRESHOLDS, **dict(cfg.get("thresholds") or {})}
        self._verdict: str | None = None
        self._last_read_ts: float | None = None

        self.setObjectName("cooldownVerdictBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont(theme.FONT_BODY)
        font.setPixelSize(theme.FONT_LABEL_SIZE)
        font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
        # DESIGN: RULE-TYPO-005 — uppercase Cyrillic status gets tracking.
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.05 * theme.FONT_LABEL_SIZE)
        self.setFont(font)
        self.refresh()

    # Throttle disk re-reads: the badge refreshes on every phase change, so
    # skip the fingerprint glob+parse if the last read was very recent.
    # ponytail: fixed 5 s window on the GUI thread; move list+compare to a
    # QThread worker if the history dir ever lives on network storage.
    _READ_THROTTLE_S = 5.0

    def verdict(self) -> str | None:
        return self._verdict

    def refresh(self) -> None:
        now = time.monotonic()
        if (
            self._last_read_ts is not None
            and now - self._last_read_ts < self._READ_THROTTLE_S
        ):
            return
        self._last_read_ts = now
        self._verdict = self._compute_verdict()
        if self._verdict is None:
            self.setVisible(False)
            self.setText("")
            return
        # DESIGN: RULE-COLOR-002, RULE-COLOR-008 — filled status chip.
        color = _VERDICT_COLOR[self._verdict]
        self.setText(f"Эталон: {_VERDICT_LABEL[self._verdict]}")
        self.setStyleSheet(
            f"#cooldownVerdictBadge {{"
            f" background: {color};"
            f" color: {theme.ON_DESTRUCTIVE};"
            f" border: none;"
            f" border-radius: {theme.RADIUS_SM}px;"
            f" padding: {theme.SPACE_1}px {theme.SPACE_2}px;"
            f"}}"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setVisible(True)

    def _compute_verdict(self) -> str | None:
        if not self._enabled:
            return None
        baseline = get_baseline(self._history_dir)
        if baseline is None:
            return None
        entries = list_fingerprints(self._history_dir)
        if not entries:
            return None
        latest = max(entries, key=lambda fp: fp.cooldown_start_ts)
        return _badge_verdict(latest, baseline, self._thresholds)


def _qcolor(token: str):
    from PySide6.QtGui import QColor

    return QColor(token)
