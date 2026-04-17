"""Tests for the runtime theme loader.

Covers the fallback chain (missing settings, missing pack, malformed
pack, invalid hex), settings persistence, the bundled-pack inventory,
and the locked-status-palette invariant across all shipped themes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cryodaq.gui import _theme_loader as loader


@pytest.fixture
def real_themes_dir() -> Path:
    return loader.THEMES_DIR


def _write_pack(path: Path, overrides: dict[str, str] | None = None) -> None:
    """Write a minimal-valid pack; overrides replace specific token values
    (use {} to drop a key for missing-token tests)."""
    base = {
        "__meta_name__": "Test",
        "__meta_description__": "Test pack",
        "BACKGROUND": "#111111",
        "SURFACE_PANEL": "#222222",
        "SURFACE_CARD": "#232323",
        "SURFACE_ELEVATED": "#242424",
        "SURFACE_SUNKEN": "#101010",
        "SURFACE_MUTED": "#252525",
        "BORDER": "#333333",
        "BORDER_SUBTLE": "#282828",
        "FOREGROUND": "#eeeeee",
        "TEXT_SECONDARY": "#cccccc",
        "MUTED_FOREGROUND": "#999999",
        "TEXT_DISABLED": "#666666",
        "ACCENT": "#4a8a5e",
        "ACCENT_300": "#3a6e48",
        "ACCENT_500": "#68a77c",
        "ACCENT_600": "#8bc49b",
        "ON_PRIMARY": "#000000",
        "ON_DESTRUCTIVE": "#ffffff",
        "STATUS_OK": "#4a8a5e",
        "STATUS_WARNING": "#c4862e",
        "STATUS_CAUTION": "#b35a38",
        "STATUS_FAULT": "#c44545",
        "STATUS_INFO": "#6490c4",
        "STATUS_STALE": "#5a5d68",
        "COLD_HIGHLIGHT": "#7ab8c4",
    }
    if overrides:
        for k, v in overrides.items():
            if v is None:
                base.pop(k, None)
            else:
                base[k] = v
    path.write_text(yaml.safe_dump(base, allow_unicode=True, sort_keys=False))


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    """Point loader at a scratch themes dir + settings file. Returns
    (themes_dir, settings_file)."""
    themes_dir = tmp_path / "themes"
    themes_dir.mkdir()
    settings_file = tmp_path / "settings.local.yaml"
    monkeypatch.setattr(loader, "THEMES_DIR", themes_dir)
    monkeypatch.setattr(loader, "SETTINGS_FILE", settings_file)
    return themes_dir, settings_file


def test_loads_default_when_no_settings(monkeypatch, tmp_path):
    themes_dir, _ = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")

    pack = loader.load_theme()

    assert pack["BACKGROUND"].startswith("#")
    assert pack["STATUS_OK"] == "#4a8a5e"


def test_loads_default_when_settings_is_garbage(monkeypatch, tmp_path):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    settings_file.write_text("::: not valid YAML :::")

    assert loader._selected_theme_name() == "warm_stone"
    pack = loader.load_theme()
    assert pack["STATUS_OK"] == "#4a8a5e"


def test_loads_default_when_theme_key_wrong_type(monkeypatch, tmp_path):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    settings_file.write_text("theme: 42\n")

    assert loader._selected_theme_name() == "warm_stone"


def test_unknown_pack_falls_back_to_default(monkeypatch, tmp_path, caplog):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    settings_file.write_text("theme: nonexistent\n")

    with caplog.at_level("WARNING"):
        pack = loader.load_theme()

    assert pack["STATUS_OK"] == "#4a8a5e"
    assert any("nonexistent" in rec.message for rec in caplog.records)


def test_missing_token_falls_back(monkeypatch, tmp_path, caplog):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    _write_pack(themes_dir / "broken.yaml", overrides={"BACKGROUND": None})
    settings_file.write_text("theme: broken\n")

    with caplog.at_level("ERROR"):
        pack = loader.load_theme()

    assert pack["BACKGROUND"] == "#111111"  # the default stub
    assert any("broken" in rec.message and "BACKGROUND" in rec.message for rec in caplog.records)


def test_invalid_hex_falls_back(monkeypatch, tmp_path, caplog):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    _write_pack(themes_dir / "broken.yaml", overrides={"ACCENT": "not-a-hex"})
    settings_file.write_text("theme: broken\n")

    with caplog.at_level("ERROR"):
        pack = loader.load_theme()

    assert pack["ACCENT"] == "#4a8a5e"
    assert any("ACCENT" in rec.message for rec in caplog.records)


def test_short_hex_rejected(monkeypatch, tmp_path):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    _write_pack(themes_dir / "shorthex.yaml", overrides={"ACCENT": "#abc"})
    settings_file.write_text("theme: shorthex\n")

    pack = loader.load_theme()
    assert pack["ACCENT"] == "#4a8a5e"  # fell back


def test_missing_default_pack_raises(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)  # empty themes dir, no packs at all

    with pytest.raises(RuntimeError, match="Default theme pack missing"):
        loader.load_theme()


def test_write_theme_selection_creates_file(monkeypatch, tmp_path):
    _, settings_file = _isolate(monkeypatch, tmp_path)
    assert not settings_file.exists()

    loader.write_theme_selection("warm_stone")

    data = yaml.safe_load(settings_file.read_text())
    assert data == {"theme": "warm_stone"}


def test_write_theme_selection_preserves_other_keys(monkeypatch, tmp_path):
    _, settings_file = _isolate(monkeypatch, tmp_path)
    settings_file.write_text(yaml.safe_dump({"theme": "warm_stone", "other_key": "value"}))

    loader.write_theme_selection("warm_stone")  # same theme, preserve keys

    data = yaml.safe_load(settings_file.read_text())
    assert data["theme"] == "warm_stone"
    assert data["other_key"] == "value"


def test_write_theme_selection_overwrites_corrupt_settings(monkeypatch, tmp_path, caplog):
    _, settings_file = _isolate(monkeypatch, tmp_path)
    settings_file.write_text("::: garbage :::")

    with caplog.at_level("WARNING"):
        loader.write_theme_selection("warm_stone")

    data = yaml.safe_load(settings_file.read_text())
    assert data == {"theme": "warm_stone"}


def test_available_themes_returns_metadata(monkeypatch, tmp_path):
    themes_dir, _ = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    _write_pack(themes_dir / "zz_other.yaml")

    themes = loader.available_themes()

    assert [t["id"] for t in themes] == ["warm_stone", "zz_other"]
    for t in themes:
        assert "name" in t and "description" in t


def test_available_themes_empty_when_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(loader, "THEMES_DIR", tmp_path / "does-not-exist")
    assert loader.available_themes() == []


# ---------------------------------------------------------------------------
# Bundled-pack invariants (run against the real config/themes/ contents)
# ---------------------------------------------------------------------------


def test_default_theme_is_warm_stone():
    assert loader.DEFAULT_THEME == "warm_stone"


def test_bundled_default_pack_exists(real_themes_dir):
    assert (real_themes_dir / "warm_stone.yaml").exists()


def test_all_bundled_packs_load_cleanly(real_themes_dir):
    """Every shipped *.yaml in config/themes/ must pass validation
    without triggering the fallback path."""
    for pack_file in real_themes_dir.glob("*.yaml"):
        pack = loader._load_theme_pack(pack_file.stem)
        assert set(loader.REQUIRED_TOKENS).issubset(pack.keys()), pack_file


def test_status_palette_identical_across_all_themes(real_themes_dir):
    """Safety invariant: every bundled theme must ship the same status
    tier colors. Style varies; safety semantics don't."""
    status_tokens = [
        "STATUS_OK",
        "STATUS_WARNING",
        "STATUS_CAUTION",
        "STATUS_FAULT",
        "STATUS_INFO",
        "STATUS_STALE",
        "COLD_HIGHLIGHT",
    ]
    packs = {
        pack_file.stem: loader._load_theme_pack(pack_file.stem)
        for pack_file in real_themes_dir.glob("*.yaml")
    }
    assert packs, "no bundled theme packs found"
    for token in status_tokens:
        values = {name: p[token] for name, p in packs.items()}
        assert len(set(values.values())) == 1, (
            f"Status token {token} differs across themes: {values}"
        )
