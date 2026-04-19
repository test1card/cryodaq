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


def test_bundled_theme_inventory(real_themes_dir):
    """The twelve shipped pack ids are frozen — renames or deletions must
    be paired with a CHANGELOG entry and an operator-facing note.

    Six new packs added 2026-04-19 per docs/design-system/HANDOFF_THEMES_V2.md
    (signal/instrument/amber dark + gost/xcode/braun light).
    """
    ids = sorted(p.stem for p in real_themes_dir.glob("*.yaml"))
    assert ids == [
        "amber",
        "anthropic_mono",
        "braun",
        "default_cool",
        "gost",
        "instrument",
        "ochre_bloom",
        "rose_dusk",
        "signal",
        "taupe_quiet",
        "warm_stone",
        "xcode",
    ]


# Pack mode classification by empirical BACKGROUND luminance (not by
# HANDOFF_THEMES_V2.md group labels). The handoff doc groups
# warm_stone / ochre_bloom / taupe_quiet / rose_dusk as "light" but
# their actual BG hexes are all dark (lum < 0.02) — only gost / xcode /
# braun have light substrates (lum > 0.8). Empirical check:
# `lum(BACKGROUND) > 0.5` → light pack.
_DARK_THEMES = frozenset(
    {
        "default_cool",
        "warm_stone",
        "anthropic_mono",
        "ochre_bloom",
        "taupe_quiet",
        "rose_dusk",
        "signal",
        "instrument",
        "amber",
    }
)
_LIGHT_THEMES = frozenset({"gost", "xcode", "braun"})

# ADR 001 STATUS-unlock applies only to the new three light packs.
# Hue-separation and AA-contrast regression tests run only on the six
# packs shipped WITH the ADR (signal/instrument/amber dark +
# gost/xcode/braun light) — the pre-ADR packs are out of scope for
# these checks (e.g. warm_stone has ACCENT hue == STATUS_OK hue,
# a known pre-existing compromise; retro-audit is an architect call).
_ADR_001_PACKS = frozenset(
    {"signal", "instrument", "amber", "gost", "xcode", "braun"}
)

_STATUS_TOKENS = (
    "STATUS_OK",
    "STATUS_WARNING",
    "STATUS_CAUTION",
    "STATUS_FAULT",
    "STATUS_INFO",
    "STATUS_STALE",
    "COLD_HIGHLIGHT",
)


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


def _rgb_to_hue(r: float, g: float, b: float) -> float:
    """Return hue in degrees (0-360). Achromatic (r==g==b) returns 0."""
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return 0.0
    d = mx - mn
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return (h * 60.0) % 360.0


def _hue(hex_color: str) -> float:
    return _rgb_to_hue(*_hex_to_rgb(hex_color))


def _relative_luminance(hex_color: str) -> float:
    """WCAG 2.1 relative luminance from sRGB hex."""

    def _channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb(hex_color)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def _contrast_ratio(fg: str, bg: str) -> float:
    lf = _relative_luminance(fg)
    lb = _relative_luminance(bg)
    lighter, darker = (lf, lb) if lf >= lb else (lb, lf)
    return (lighter + 0.05) / (darker + 0.05)


def test_status_palette_hue_locked_across_all_themes(real_themes_dir):
    """Safety invariant (ADR 001): every bundled theme must ship the same
    STATUS *hues*. Lightness is unlocked for light substrates to restore
    AA contrast; hue identity preserves operator pattern matching
    («amber = WARNING, red = FAULT») across dark/light switches.

    Tolerance: ±5° — covers sRGB quantization drift when the ADR's
    shifted-L hex set is rounded to 8-bit-per-channel integers (e.g.
    STATUS_OK dark #4a8a5e hue 138.8°, light #2e6b45 hue 142.6° —
    same hue family, quantization-bounded).
    """
    packs = {
        pack_file.stem: loader._load_theme_pack(pack_file.stem)
        for pack_file in real_themes_dir.glob("*.yaml")
    }
    assert packs
    for token in _STATUS_TOKENS:
        hues = {name: _hue(p[token]) for name, p in packs.items()}
        base = next(iter(hues.values()))
        for name, h in hues.items():
            delta = min(abs(h - base), 360.0 - abs(h - base))
            assert delta <= 5.0, (
                f"{token} hue {h:.1f}° in {name} differs >5° from base {base:.1f}°"
            )


def test_status_palette_hex_identical_across_dark_themes(real_themes_dir):
    """Dark packs share the original locked-hex STATUS set verbatim.
    ADR 001 only unlocks the LIGHT substrate variant — dark packs stay
    identically hex-locked."""
    dark_packs = {
        pack_file.stem: loader._load_theme_pack(pack_file.stem)
        for pack_file in real_themes_dir.glob("*.yaml")
        if pack_file.stem in _DARK_THEMES
    }
    assert dark_packs
    for token in _STATUS_TOKENS:
        values = {name: p[token] for name, p in dark_packs.items()}
        assert len(set(values.values())) == 1, f"{token} differs across dark themes: {values}"


def test_status_palette_aa_contrast_on_light_card(real_themes_dir):
    """ADR 001: STATUS tokens on light packs must achieve WCAG AA
    (≥4.5:1) contrast on SURFACE_CARD. If this regresses, the shifted-L
    set in the light pack was edited without re-checking contrast —
    revert or re-audit per ADR §Decision / §Metrics table."""
    light_packs = {
        pack_file.stem: loader._load_theme_pack(pack_file.stem)
        for pack_file in real_themes_dir.glob("*.yaml")
        if pack_file.stem in _LIGHT_THEMES
    }
    assert light_packs, "expected at least one bundled light theme"
    for name, pack in light_packs.items():
        card = pack["SURFACE_CARD"]
        for token in _STATUS_TOKENS:
            ratio = _contrast_ratio(pack[token], card)
            assert ratio >= 4.5, f"{name}.{token} vs SURFACE_CARD contrast {ratio:.2f}:1 < 4.5 AA"


def test_accent_hue_separation_from_status(real_themes_dir):
    """ADR 001 / hue-collision invariant: ACCENT hue must be ≥30° from
    every STATUS hue in the six ADR-scope packs. Pre-ADR packs
    (warm_stone / default_cool / ochre_bloom / taupe_quiet / rose_dusk /
    anthropic_mono) are out of scope — warm_stone in particular has a
    known pre-existing ACCENT==STATUS_OK hue collision at 138° that
    predates the ADR. Retro-fix is an architect call, not blocked by
    this invariant.
    """
    packs = {
        pack_file.stem: loader._load_theme_pack(pack_file.stem)
        for pack_file in real_themes_dir.glob("*.yaml")
        if pack_file.stem in _ADR_001_PACKS
    }
    assert packs, "expected the six ADR-scope packs to be bundled"
    for name, pack in packs.items():
        accent_hue = _hue(pack["ACCENT"])
        for token in _STATUS_TOKENS:
            status_hue = _hue(pack[token])
            delta = min(abs(accent_hue - status_hue), 360.0 - abs(accent_hue - status_hue))
            # COLD_HIGHLIGHT and STALE are often near-achromatic; 30°
            # still applies but should be trivially satisfied.
            assert delta >= 30.0, (
                f"{name}: ACCENT hue {accent_hue:.1f}° only {delta:.1f}° from "
                f"{token} {status_hue:.1f}° (need ≥30°)"
            )


@pytest.mark.parametrize(
    "theme_id",
    ["signal", "instrument", "amber", "gost", "xcode", "braun"],
)
def test_new_theme_loads_with_required_tokens(real_themes_dir, theme_id):
    """Smoke: each of the six 2026-04-19 packs loads cleanly and ships
    the full 25-token required set plus the two meta keys."""
    pack = loader._load_theme_pack(theme_id)
    assert set(loader.REQUIRED_TOKENS).issubset(pack.keys())
    # Meta keys are optional but present in the bundled packs.
    assert "__meta_name__" in pack
