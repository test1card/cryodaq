"""F27 — Composition photos section for ExperimentOverlay.

Shows thumbnails of composition photos attached to an experiment via
Telegram bot. Auto-refreshes on experiment.photo_attached ZMQ event.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_THUMB_SIZE = 120
_COLS = 4


class CompositionPhotosWidget(QWidget):
    """Grid of composition photo thumbnails for an experiment."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._photos: list[dict] = []
        self._artifact_dir: Path | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_from_artifact_dir(self, artifact_dir: str | None) -> None:
        """Load composition photos from experiment artifact dir."""
        if not artifact_dir:
            self._artifact_dir = None
            self._photos = []
            self._refresh()
            return

        path = Path(artifact_dir)
        self._artifact_dir = path
        self._photos = self._read_photos(path)
        self._refresh()

    def set_photos(self, artifact_index: list[dict]) -> None:
        """Set photos directly from a pre-loaded artifact_index list.

        Used by ArchivePanel where data is already available without disk read.
        """
        self._photos = [
            e for e in artifact_index if e.get("category") == "composition_photo"
        ]
        self._refresh()

    def on_photo_attached(self, payload: dict) -> None:
        """Handle experiment.photo_attached EventBus event — reload from disk."""
        if self._artifact_dir is not None:
            self._photos = self._read_photos(self._artifact_dir)
            self._refresh()

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    @staticmethod
    def _read_photos(artifact_dir: Path) -> list[dict]:
        """Read composition_photo entries from metadata.json."""
        metadata_path = artifact_dir / "metadata.json"
        if not metadata_path.exists():
            return []
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            return [
                entry
                for entry in payload.get("artifact_index", [])
                if entry.get("category") == "composition_photo"
            ]
        except Exception as exc:
            logger.warning("CompositionPhotosWidget: failed to read metadata: %s", exc)
            return []

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, theme.SPACE_3, 0, 0)
        layout.setSpacing(theme.SPACE_2)

        header = QLabel("Композиция эксперимента")
        header.setObjectName("compPhotosHeader")
        header.setStyleSheet(
            f"#compPhotosHeader {{"
            f"color: {theme.FOREGROUND};"
            f"font-family: '{theme.FONT_BODY}';"
            f"font-size: {theme.FONT_SIZE_SM}px;"
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
            f"text-transform: uppercase;"
            f"letter-spacing: 0.05em;"
            f"}}"
        )
        layout.addWidget(header)

        # Scroll area for thumbnails
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._grid_widget = QWidget()
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(theme.SPACE_2)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._grid_widget)
        layout.addWidget(scroll)

        self._empty_label = QLabel(
            "Фото пока не прикреплены. Отправь в Telegram бота."
        )
        self._empty_label.setObjectName("compPhotosEmpty")
        self._empty_label.setStyleSheet(
            f"#compPhotosEmpty {{"
            f"color: {theme.MUTED_FOREGROUND};"
            f"font-family: '{theme.FONT_BODY}';"
            f"font-size: {theme.FONT_SIZE_SM}px;"
            f"font-style: italic;"
            f"}}"
        )
        self._empty_label.setWordWrap(True)
        layout.addWidget(self._empty_label)

    def _refresh(self) -> None:
        # Clear existing thumbnails
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._photos:
            self._grid_widget.setVisible(False)
            self._empty_label.setVisible(True)
            self.setMinimumHeight(60)
            self.setMaximumHeight(80)
            return

        self._grid_widget.setVisible(True)
        self._empty_label.setVisible(False)

        for idx, photo in enumerate(self._photos):
            thumb = self._build_thumbnail(photo)
            self._grid.addWidget(thumb, idx // _COLS, idx % _COLS)

        rows = (len(self._photos) + _COLS - 1) // _COLS
        min_h = rows * (_THUMB_SIZE + theme.SPACE_2 + 28) + 60
        self.setMinimumHeight(min_h)
        self.setMaximumHeight(16777215)  # Qt QWIDGETSIZE_MAX — reset from empty state

    def _build_thumbnail(self, photo: dict) -> QWidget:
        cell = QFrame()
        cell.setFrameShape(QFrame.Shape.StyledPanel)
        cell.setObjectName("compPhotoCell")
        cell.setStyleSheet(
            f"#compPhotoCell {{"
            f"background: {theme.CARD};"
            f"border: 1px solid {theme.BORDER};"
            f"border-radius: {theme.RADIUS_SM}px;"
            f"}}"
        )
        cell.setFixedWidth(_THUMB_SIZE + 8)

        v = QVBoxLayout(cell)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(2)

        path_str = photo.get("path", "")
        pixmap = QPixmap(path_str)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                _THUMB_SIZE,
                _THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            scaled = QPixmap(_THUMB_SIZE, _THUMB_SIZE)
            scaled.fill(Qt.GlobalColor.gray)

        thumb_label = QLabel()
        thumb_label.setPixmap(scaled)
        thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
        thumb_label.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        photo_ref = dict(photo)
        thumb_label.mousePressEvent = lambda _e, p=photo_ref: self._open_detail(p)
        v.addWidget(thumb_label)

        summary = photo.get("summary", {})
        cap = summary.get("caption", "")
        if cap:
            cap_label = QLabel(cap[:35] + ("…" if len(cap) > 35 else ""))
            cap_label.setObjectName("compThumbCaption")
            cap_label.setStyleSheet(
                f"#compThumbCaption {{"
                f"color: {theme.MUTED_FOREGROUND};"
                f"font-size: {theme.FONT_SIZE_XS}px;"
                f"}}"
            )
            cap_label.setWordWrap(True)
            v.addWidget(cap_label)

        return cell

    def _open_detail(self, photo: dict) -> None:
        dlg = PhotoDetailsDialog(photo, self)
        dlg.exec()


class PhotoDetailsDialog(QDialog):
    """Full-size photo with metadata sidebar."""

    def __init__(self, photo: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._photo = photo
        self.setWindowTitle("Композиция эксперимента")
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_3)

        # Image
        path_str = self._photo.get("path", "")
        pixmap = QPixmap(path_str)
        if not pixmap.isNull():
            scaled = pixmap.scaledToHeight(
                480, Qt.TransformationMode.SmoothTransformation
            )
        else:
            scaled = QPixmap(480, 360)
            scaled.fill(Qt.GlobalColor.darkGray)

        image_label = QLabel()
        image_label.setPixmap(scaled)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(image_label)

        # Metadata
        summary = self._photo.get("summary", {})
        lines = []
        if summary.get("uploaded_at"):
            lines.append(f"Загружено: {summary['uploaded_at']}")
        if summary.get("telegram_username"):
            lines.append(f"Оператор: @{summary['telegram_username']}")
        if summary.get("phase_at_upload"):
            lines.append(f"Фаза: {summary['phase_at_upload']}")
        channels = summary.get("channels_mentioned", [])
        if channels:
            lines.append(f"Каналы: {', '.join(channels)}")
        if summary.get("caption"):
            lines.append(f"Подпись: {summary['caption']}")
        if summary.get("dimensions"):
            d = summary["dimensions"]
            lines.append(f"Размер: {d.get('width')}×{d.get('height')} пикс.")

        meta_label = QLabel("\n".join(lines))
        meta_label.setObjectName("photoMeta")
        meta_label.setStyleSheet(
            f"#photoMeta {{"
            f"color: {theme.MUTED_FOREGROUND};"
            f"font-family: '{theme.FONT_BODY}';"
            f"font-size: {theme.FONT_SIZE_SM}px;"
            f"}}"
        )
        meta_label.setWordWrap(True)
        layout.addWidget(meta_label)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        open_btn = QPushButton("Открыть в Finder")
        open_btn.setObjectName("photoOpenBtn")
        open_btn.clicked.connect(self._open_in_finder)
        btn_row.addWidget(open_btn)

        close_btn = QPushButton("Закрыть")
        close_btn.setObjectName("photoCloseBtn")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _open_in_finder(self) -> None:
        from PySide6.QtCore import QUrl

        path = Path(self._photo.get("path", "")).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
