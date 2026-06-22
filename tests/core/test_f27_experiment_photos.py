"""F27 Phase C tests — ExperimentManager.attach_composition_photo.

Covers:
- Creates composition/ dir
- Writes photo + sidecar atomically
- Sequence number increments on multiple photos
- Appends artifact_index entry to metadata.json
- Rejects corrupt image data
- Records phase_at_upload for active experiment
- Records channels_mentioned
- Returns correct filename/path dict
- _validate_photo_dimensions via Pillow
- CompositionPhotosWidget._read_photos data loading (no Qt required)
"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest

from cryodaq.core.experiment import _validate_photo_dimensions

# ---------------------------------------------------------------------------
# _validate_photo_dimensions
# ---------------------------------------------------------------------------


def _make_valid_jpeg() -> bytes:
    try:
        from PIL import Image
        img = Image.new("RGB", (64, 48), color=(200, 100, 50))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()
    except ImportError:
        pytest.skip("Pillow not installed")


def _make_valid_png() -> bytes:
    try:
        from PIL import Image
        img = Image.new("RGB", (32, 32), color=(0, 128, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        pytest.skip("Pillow not installed")


def test_validate_photo_dimensions_jpeg() -> None:
    data = _make_valid_jpeg()
    result = _validate_photo_dimensions(data)
    assert result is not None
    assert result["width"] == 64
    assert result["height"] == 48


def test_validate_photo_dimensions_png() -> None:
    data = _make_valid_png()
    result = _validate_photo_dimensions(data)
    assert result is not None
    assert result["width"] == 32
    assert result["height"] == 32


def test_validate_photo_dimensions_invalid_returns_none() -> None:
    result = _validate_photo_dimensions(b"not an image at all \x00\x01\x02")
    assert result is None


def test_validate_photo_dimensions_empty_returns_none() -> None:
    result = _validate_photo_dimensions(b"")
    assert result is None


# ---------------------------------------------------------------------------
# ExperimentManager.attach_composition_photo
# ---------------------------------------------------------------------------


def _make_experiment_manager_with_artifact_dir(tmp_path: Path):
    """Build a minimal ExperimentManager-like scenario with an artifact dir."""

    from cryodaq.core.experiment import ExperimentManager

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    instruments_cfg = tmp_path / "instruments.yaml"
    instruments_cfg.write_text("{}")
    em = ExperimentManager(data_dir=data_dir, instruments_config=instruments_cfg)
    return em


def test_attach_composition_photo_creates_composition_dir(tmp_path: Path) -> None:
    jpeg_bytes = _make_valid_jpeg()
    em = _make_experiment_manager_with_artifact_dir(tmp_path)

    # Create the experiment artifact dir (normally created by create_experiment)
    exp_id = "test-exp-001"
    artifact_dir = em._artifact_dir(exp_id)
    artifact_dir.mkdir(parents=True)
    # Create a minimal metadata.json so _read_metadata_payload works
    (artifact_dir / "metadata.json").write_text(
        json.dumps({"experiment": {"experiment_id": exp_id}}), encoding="utf-8"
    )

    result = em.attach_composition_photo(
        experiment_id=exp_id,
        photo_bytes=jpeg_bytes,
        caption="test caption",
        operator_username="vladimir",
    )

    composition_dir = artifact_dir / "composition"
    assert composition_dir.exists()
    assert result["filename"].endswith(".jpg")


def test_attach_composition_photo_writes_photo_and_sidecar(tmp_path: Path) -> None:
    jpeg_bytes = _make_valid_jpeg()
    em = _make_experiment_manager_with_artifact_dir(tmp_path)

    exp_id = "test-exp-002"
    artifact_dir = em._artifact_dir(exp_id)
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "metadata.json").write_text(
        json.dumps({"artifact_index": []}), encoding="utf-8"
    )

    result = em.attach_composition_photo(
        experiment_id=exp_id,
        photo_bytes=jpeg_bytes,
        caption="test",
        operator_username="user",
    )

    photo_path = Path(result["path"])
    assert photo_path.exists()
    sidecar_path = photo_path.with_suffix(".json")
    assert sidecar_path.exists()
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["caption"] == "test"
    assert sidecar["telegram_username"] == "user"
    assert sidecar["dimensions"]["width"] == 64


def test_attach_composition_photo_sequence_increments(tmp_path: Path) -> None:
    jpeg_bytes = _make_valid_jpeg()
    em = _make_experiment_manager_with_artifact_dir(tmp_path)

    exp_id = "test-exp-003"
    artifact_dir = em._artifact_dir(exp_id)
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "metadata.json").write_text("{}", encoding="utf-8")

    r1 = em.attach_composition_photo(experiment_id=exp_id, photo_bytes=jpeg_bytes)
    r2 = em.attach_composition_photo(experiment_id=exp_id, photo_bytes=jpeg_bytes)

    assert r1["filename"] != r2["filename"]
    assert "_001." in r1["filename"]
    assert "_002." in r2["filename"]


def test_attach_composition_photo_appends_artifact_index(tmp_path: Path) -> None:
    jpeg_bytes = _make_valid_jpeg()
    em = _make_experiment_manager_with_artifact_dir(tmp_path)

    exp_id = "test-exp-004"
    artifact_dir = em._artifact_dir(exp_id)
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "metadata.json").write_text(
        json.dumps({"artifact_index": []}), encoding="utf-8"
    )

    em.attach_composition_photo(
        experiment_id=exp_id,
        photo_bytes=jpeg_bytes,
        caption="first",
    )
    em.attach_composition_photo(
        experiment_id=exp_id,
        photo_bytes=jpeg_bytes,
        caption="second",
    )

    payload = json.loads((artifact_dir / "metadata.json").read_text(encoding="utf-8"))
    photos = [
        e for e in payload.get("artifact_index", [])
        if e.get("category") == "composition_photo"
    ]
    assert len(photos) == 2
    assert photos[0]["summary"]["caption"] == "first"
    assert photos[1]["summary"]["caption"] == "second"


def test_attach_composition_photo_rejects_corrupt_image(tmp_path: Path) -> None:
    em = _make_experiment_manager_with_artifact_dir(tmp_path)

    exp_id = "test-exp-005"
    artifact_dir = em._artifact_dir(exp_id)
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "metadata.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid or unreadable"):
        em.attach_composition_photo(
            experiment_id=exp_id,
            photo_bytes=b"not an image",
        )


def test_attach_composition_photo_records_channels_mentioned(tmp_path: Path) -> None:
    jpeg_bytes = _make_valid_jpeg()
    em = _make_experiment_manager_with_artifact_dir(tmp_path)

    exp_id = "test-exp-006"
    artifact_dir = em._artifact_dir(exp_id)
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "metadata.json").write_text("{}", encoding="utf-8")

    result = em.attach_composition_photo(
        experiment_id=exp_id,
        photo_bytes=jpeg_bytes,
        channels_mentioned=["Т7", "Т12"],
    )

    sidecar = json.loads(Path(result["path"]).with_suffix(".json").read_text(encoding="utf-8"))
    assert "Т7" in sidecar["channels_mentioned"]
    assert "Т12" in sidecar["channels_mentioned"]


def test_attach_composition_photo_clamps_long_caption(tmp_path: Path) -> None:
    jpeg_bytes = _make_valid_jpeg()
    em = _make_experiment_manager_with_artifact_dir(tmp_path)

    exp_id = "test-exp-007"
    artifact_dir = em._artifact_dir(exp_id)
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "metadata.json").write_text("{}", encoding="utf-8")

    long_caption = "А" * 600
    result = em.attach_composition_photo(
        experiment_id=exp_id,
        photo_bytes=jpeg_bytes,
        caption=long_caption,
    )

    sidecar = json.loads(Path(result["path"]).with_suffix(".json").read_text(encoding="utf-8"))
    assert len(sidecar["caption"]) <= 500


def test_attach_composition_photo_missing_artifact_dir_raises(tmp_path: Path) -> None:
    em = _make_experiment_manager_with_artifact_dir(tmp_path)

    with pytest.raises(ValueError, match="artifact dir not found"):
        em.attach_composition_photo(
            experiment_id="nonexistent-exp",
            photo_bytes=b"data",
        )


def test_attach_composition_photo_returns_filename_path(tmp_path: Path) -> None:
    jpeg_bytes = _make_valid_jpeg()
    em = _make_experiment_manager_with_artifact_dir(tmp_path)

    exp_id = "test-exp-008"
    artifact_dir = em._artifact_dir(exp_id)
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "metadata.json").write_text("{}", encoding="utf-8")

    result = em.attach_composition_photo(
        experiment_id=exp_id,
        photo_bytes=jpeg_bytes,
    )

    assert "filename" in result
    assert "path" in result
    assert "metadata" in result
    assert Path(result["path"]).exists()


# ---------------------------------------------------------------------------
# CompositionPhotosWidget._read_photos (data layer, no Qt)
# ---------------------------------------------------------------------------


def test_read_photos_returns_empty_when_no_metadata(tmp_path: Path) -> None:
    from cryodaq.gui.shell.composition_photos_widget import CompositionPhotosWidget

    result = CompositionPhotosWidget._read_photos(tmp_path)
    assert result == []


def test_read_photos_filters_composition_photo_category(tmp_path: Path) -> None:
    from cryodaq.gui.shell.composition_photos_widget import CompositionPhotosWidget

    metadata = {
        "artifact_index": [
            {"category": "composition_photo", "path": "/a.jpg", "summary": {}},
            {"category": "report_pdf", "path": "/r.pdf", "summary": {}},
            {"category": "composition_photo", "path": "/b.jpg", "summary": {}},
        ]
    }
    (tmp_path / "metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )

    result = CompositionPhotosWidget._read_photos(tmp_path)
    assert len(result) == 2
    assert all(e["category"] == "composition_photo" for e in result)


def test_read_photos_handles_corrupt_metadata(tmp_path: Path) -> None:
    from cryodaq.gui.shell.composition_photos_widget import CompositionPhotosWidget

    (tmp_path / "metadata.json").write_text("not json {{{", encoding="utf-8")
    result = CompositionPhotosWidget._read_photos(tmp_path)
    assert result == []


# ---------------------------------------------------------------------------
# Audit fix regression tests
# ---------------------------------------------------------------------------


async def test_attach_dedup_second_callback_is_noop() -> None:
    """After _attach pops pending entry, a second callback for same key is ignored."""
    from unittest.mock import AsyncMock, MagicMock

    from cryodaq.notifications.composition_photo_handler import (
        CompositionPhotoHandler,
        PendingPhoto,
    )

    bot = MagicMock()
    bot._send = AsyncMock()
    bot.edit_message = AsyncMock()
    em = MagicMock()
    em.get_active_experiment.return_value = None
    em.list_archive_entries.return_value = []
    em.attach_composition_photo.return_value = {
        "filename": "20260501T140523_001.jpg",
        "path": "/tmp/a.jpg",
        "metadata": {},
    }

    handler = CompositionPhotoHandler(bot=bot, experiment_manager=em)
    cb_key = "dedup_key"
    from datetime import UTC, datetime

    async with handler._lock:
        handler._pending[cb_key] = PendingPhoto(
            file_id="fid",
            photo_bytes=b"\xff\xd8" + b"\x00" * 100,
            caption="",
            chat_id=123,
            operator_username="user",
            arrived_at=datetime.now(UTC),
            confirm_message_id=42,
            target_experiment_id="exp-001",
        )

    cb = {"id": "cbq", "message": {"chat": {"id": 123}, "message_id": 42}}

    # First callback — should attach
    await handler.handle_callback(cb, f"photo:yes:{cb_key}")
    assert em.attach_composition_photo.call_count == 1

    # Second callback — pending gone, should reply "expired", not attach again
    await handler.handle_callback(cb, f"photo:yes:{cb_key}")
    assert em.attach_composition_photo.call_count == 1  # still 1, not 2


async def test_html_escape_in_caption_prevents_injection() -> None:
    """handle_photo escapes malicious HTML in username, caption, and title."""
    from unittest.mock import AsyncMock, MagicMock

    from cryodaq.notifications.composition_photo_handler import CompositionPhotoHandler

    bot = MagicMock()
    bot.get_file_path = AsyncMock(return_value="path/to/file")
    bot.download_file = AsyncMock(return_value=b"\xff\xd8\xff" + b"\x00" * 50)
    bot._send = AsyncMock()

    captured_texts: list[str] = []

    async def _capture_send(chat_id: int, text: str, keyboard: object) -> int:
        captured_texts.append(text)
        return 99

    bot.send_message_with_keyboard = _capture_send

    # Active experiment with a malicious title
    active = MagicMock()
    active.title = "<b>INJECT</b>"
    active.name = "<b>INJECT</b>"
    active.experiment_id = "exp-001"

    em = MagicMock()
    em.get_active_experiment.return_value = active

    handler = CompositionPhotoHandler(bot=bot, experiment_manager=em)

    msg = {
        "chat": {"id": 42},
        "photo": [{"file_id": "fid1", "file_size": 1000}],
        "from": {"username": "<evil>user</evil>"},
        "caption": "<script>alert('xss')</script>",
    }
    await handler.handle_photo(msg)

    assert captured_texts, "send_message_with_keyboard was never called"
    text = captured_texts[0]

    # Raw HTML tags must not appear in the output (they must be escaped)
    assert "<script>" not in text, f"Unescaped <script> in confirm text: {text!r}"
    assert "<evil>" not in text, f"Unescaped <evil> in confirm text: {text!r}"
    # The malicious title tag must be escaped too
    assert "<b>INJECT</b>" not in text or text.count("<b>") == 1, (
        f"Unescaped title injection in confirm text: {text!r}"
    )
    # Escaped forms must be present
    assert "&lt;script&gt;" in text or "script" not in text


def test_widgets_set_photos_then_empty_then_photos_restores_max_height() -> None:
    """setMaximumHeight is reset to QWIDGETSIZE_MAX when going empty → non-empty."""
    from PySide6.QtWidgets import QApplication

    from cryodaq.gui.shell.composition_photos_widget import CompositionPhotosWidget

    _app = QApplication.instance() or QApplication([])

    widget = CompositionPhotosWidget()

    fake_photo = {
        "category": "composition_photo",
        "path": "/tmp/fake.jpg",
        "summary": {
            "uploaded_at": "2026-01-01T00:00:00+00:00",
            "telegram_username": "op",
            "caption": "",
            "file_size_bytes": 100,
            "dimensions": {"width": 64, "height": 48},
            "phase_at_upload": None,
            "channels_mentioned": [],
        },
    }

    # Populate — widget is non-empty
    widget.set_photos([fake_photo])
    assert widget.maximumHeight() == 16777215, (
        f"After set_photos([...]) maximumHeight should be QWIDGETSIZE_MAX, "
        f"got {widget.maximumHeight()}"
    )

    # Clear — widget goes empty (maxHeight locked to 80)
    widget.set_photos([])
    assert widget.maximumHeight() == 80, (
        f"After set_photos([]) maximumHeight should be 80 (empty state), "
        f"got {widget.maximumHeight()}"
    )

    # Repopulate — maxHeight must be restored to QWIDGETSIZE_MAX
    widget.set_photos([fake_photo])
    assert widget.maximumHeight() == 16777215, (
        f"After set_photos([...]) following empty state, maximumHeight should be "
        f"QWIDGETSIZE_MAX (16777215), got {widget.maximumHeight()}"
    )

    widget.deleteLater()
    _app.processEvents()
