"""MultiLine channel selector dialog (smoke hotfix v0.55.16.0.1).

Operator-facing modal that lets a user pick which Etalon MultiLine
channels (1..32) the driver should poll. Pre-selects whatever the
driver is currently configured for; on accept, returns the new
list[int] for the panel to forward to the engine via the
`multiline.set_channels` ZMQ command.

Architectural decisions (architect smoke test 2026-05-07):
- Range fixed at 1..32 to mirror `MultiLineDriver._validate_channel_numbers`.
- At least one channel must be selected — empty submission is rejected
  with a Russian error label rather than raising.
- The dialog is purely a chooser; persistence + driver reconfigure live
  on the engine side. Returning a list keeps the GUI thread off the
  ZMQ path until the operator clicks OK.
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme

_MIN_CHANNELS = 1
_MAX_CHANNELS = 32
_GRID_COLUMNS = 8  # 8x4 = 32 checkboxes


class MultiLineChannelSelectorDialog(QDialog):
    """Modal dialog letting an operator pick channels 1..32 для polling."""

    def __init__(
        self,
        current_selection: Iterable[int] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Выбор каналов MultiLine")
        self.setModal(True)

        # Sanitize incoming selection — accept only canonical 1..32 ints.
        pre_checked = {
            int(c)
            for c in current_selection
            if isinstance(c, int) and _MIN_CHANNELS <= c <= _MAX_CHANNELS
        }

        self._checkboxes: dict[int, QCheckBox] = {}
        self._build_ui(pre_checked)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self, pre_checked: set[int]) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(theme.SPACE_3)

        header = QLabel(
            "Отметьте каналы, которые нужно опрашивать (1..32). "
            "Минимум один канал."
        )
        header.setWordWrap(True)
        header.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        root.addWidget(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE_3)
        grid.setVerticalSpacing(theme.SPACE_2)
        for ch in range(_MIN_CHANNELS, _MAX_CHANNELS + 1):
            box = QCheckBox(str(ch))
            box.setChecked(ch in pre_checked)
            row = (ch - 1) // _GRID_COLUMNS
            col = (ch - 1) % _GRID_COLUMNS
            grid.addWidget(box, row, col)
            self._checkboxes[ch] = box
        root.addLayout(grid)

        bulk = QHBoxLayout()
        select_all = QPushButton("Выбрать все")
        select_all.clicked.connect(self._select_all)
        clear_all = QPushButton("Снять все")
        clear_all.clicked.connect(self._clear_all)
        bulk.addWidget(select_all)
        bulk.addWidget(clear_all)
        bulk.addStretch(1)
        root.addLayout(bulk)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        root.addWidget(self._error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _select_all(self) -> None:
        for box in self._checkboxes.values():
            box.setChecked(True)
        self._error_label.setText("")

    def _clear_all(self) -> None:
        for box in self._checkboxes.values():
            box.setChecked(False)

    def _on_accept(self) -> None:
        selection = self.selected_channels()
        if not selection:
            self._error_label.setText(
                "Нужно выбрать хотя бы один канал."
            )
            return
        self.accept()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def selected_channels(self) -> list[int]:
        """Return the currently-checked channels, sorted ascending."""
        return sorted(ch for ch, box in self._checkboxes.items() if box.isChecked())
