"""Tests for the runtime theme loader.

Covers the fallback chain (missing settings, missing pack, malformed
pack, invalid hex), settings persistence, the bundled-pack inventory,
and the locked-status-palette invariant across all shipped themes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

from cryodaq.gui import _theme_loader as loader

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO_ROOT / "docs" / "design-system" / "MANIFEST.md"
_MACHINE_GATE_START = "<!-- MACHINE_GATES:BEGIN -->\n```json\n"
_MACHINE_GATE_END = "\n```\n<!-- MACHINE_GATES:END -->"

_REQUIRED_CONTRAST_CASES: dict[str, tuple[str, str, float]] = {
    "body_foreground_card": ("FOREGROUND", "SURFACE_CARD", 4.5),
    "body_secondary_card": ("TEXT_SECONDARY", "SURFACE_CARD", 4.5),
    "body_muted_card": ("MUTED_FOREGROUND", "SURFACE_CARD", 4.5),
    "focus_elevated": ("FOCUS_RING", "SURFACE_ELEVATED", 3.0),
    "status_ok_card": ("STATUS_OK", "SURFACE_CARD", 3.0),
    "status_caution_card": ("STATUS_CAUTION", "SURFACE_CARD", 3.0),
    "status_fault_card": ("STATUS_FAULT", "SURFACE_CARD", 3.0),
    "status_info_card": ("STATUS_INFO", "SURFACE_CARD", 3.0),
    "status_stale_card": ("STATUS_STALE", "SURFACE_CARD", 3.0),
    "filled_fault": ("ON_DESTRUCTIVE", "STATUS_FAULT", 4.5),
    "filled_accent": ("BACKGROUND", "ACCENT", 4.5),
    "legacy_caution_inverse": ("ON_PRIMARY", "STATUS_CAUTION", 4.5),
    "border_background": ("BORDER", "BACKGROUND", 3.0),
}

_REQUIRED_EXCEPTION_RATIO_FLOORS: dict[str, dict[str, float]] = {
    "A11Y-EX-001": {
        "amber": 3.7069,
        "anthropic_mono": 2.950593,
        "braun": 4.222376,
        "gost": 4.109723,
        "instrument": 3.725763,
        "ochre_bloom": 2.966639,
        "rose_dusk": 3.018188,
        "signal": 3.268795,
        "taupe_quiet": 3.210661,
        "warm_stone": 3.094435,
        "xcode": 3.851237,
    },
    "A11Y-EX-002": {
        "amber": 2.170522,
        "anthropic_mono": 2.401728,
        "default_cool": 2.570572,
        "instrument": 2.10437,
        "ochre_bloom": 1.962009,
        "rose_dusk": 1.919218,
        "taupe_quiet": 2.354748,
        "warm_stone": 2.086325,
    },
    "A11Y-EX-003": {
        "instrument": 2.702978,
        "ochre_bloom": 2.946179,
        "rose_dusk": 2.951782,
        "taupe_quiet": 2.956365,
    },
    "A11Y-EX-004": {
        "amber": 2.297509,
        "anthropic_mono": 2.360812,
        "default_cool": 2.6456,
        "instrument": 2.019105,
        "ochre_bloom": 2.200774,
        "rose_dusk": 2.20496,
        "signal": 2.961427,
        "taupe_quiet": 2.208383,
        "warm_stone": 2.25824,
    },
    "A11Y-EX-005": {"default_cool": 4.074971},
    "A11Y-EX-006": {"braun": 4.086638},
    "A11Y-EX-007": {"default_cool": 2.568701},
    "A11Y-EX-008": {
        "amber": 1.418847,
        "anthropic_mono": 1.557383,
        "braun": 2.134742,
        "default_cool": 1.461852,
        "gost": 2.407457,
        "instrument": 1.856912,
        "ochre_bloom": 1.635669,
        "rose_dusk": 1.576828,
        "signal": 1.118236,
        "taupe_quiet": 1.438573,
        "warm_stone": 1.527526,
        "xcode": 1.385558,
    },
}

_SUPPORTED_CANONICAL_SHAPES = {
    "ok": "circle",
    "caution": "triangle",
    "fault": "square",
    "stale": "hollow_circle",
    "disconnected": "diamond",
}


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
        "ACCENT": "#b89e7a",
        "ACCENT_300": "#9a8462",
        "ACCENT_500": "#c9b391",
        "ACCENT_600": "#dac7a8",
        "SELECTION_BG": "#2c2723",
        "FOCUS_RING": "#6b5d4d",
        "ON_PRIMARY": "#000000",
        "ON_DESTRUCTIVE": "#ffffff",
        "STATUS_OK": "#4a8a5e",
        "STATUS_WARNING": "#c4862e",
        "STATUS_CAUTION": "#c4862e",
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


@pytest.mark.parametrize("content", ["- one\n- two\n", "42\n", "plain scalar\n"])
def test_truthy_nonmapping_settings_fall_back_without_import_failure(monkeypatch, tmp_path, content):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    settings_file.write_text(content)

    assert loader._selected_theme_name() == "warm_stone"
    theme_id, pack = loader.resolve_theme()
    assert theme_id == "warm_stone"
    assert pack["BACKGROUND"] == "#111111"


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

    assert pack["ACCENT"] == "#b89e7a"
    assert any("ACCENT" in rec.message for rec in caplog.records)


def test_warning_must_alias_caution_or_pack_falls_back(monkeypatch, tmp_path, caplog):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    _write_pack(themes_dir / "split.yaml", overrides={"STATUS_WARNING": "#abcdef"})
    settings_file.write_text("theme: split\n")

    with caplog.at_level("ERROR"):
        pack = loader.load_theme()

    assert pack["STATUS_WARNING"] == pack["STATUS_CAUTION"]
    assert any("separates STATUS_WARNING" in rec.message for rec in caplog.records)


def test_short_hex_rejected(monkeypatch, tmp_path):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    _write_pack(themes_dir / "shorthex.yaml", overrides={"ACCENT": "#abc"})
    settings_file.write_text("theme: shorthex\n")

    pack = loader.load_theme()
    assert pack["ACCENT"] == "#b89e7a"  # fell back to stub


def test_missing_default_pack_raises(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)  # empty themes dir, no packs at all

    with pytest.raises(RuntimeError, match="Default theme pack invalid"):
        loader.load_theme()


def test_post_build_seeds_theme_pack_for_frozen_loader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The copied ONEDIR config must load through the frozen resource path."""

    repo_root = Path(__file__).resolve().parents[2]
    project_root = tmp_path / "project"
    bundle_root = project_root / "dist" / "CryoDAQ"
    script = project_root / "build_scripts" / "post_build.py"
    script.parent.mkdir(parents=True)
    bundle_root.mkdir(parents=True)
    shutil.copy2(repo_root / "build_scripts" / "post_build.py", script)
    # post_build now stamps the unqualified-artifact marker, so the synthetic
    # project needs the identity helper it imports and the pyproject it reads
    # the version from. Copy the real ones rather than inventing a version.
    shutil.copy2(repo_root / "build_scripts" / "artifact_identity.py", script.parent / "artifact_identity.py")
    shutil.copy2(repo_root / "pyproject.toml", project_root / "pyproject.toml")
    shutil.copytree(repo_root / "config", project_root / "config")

    subprocess.run([sys.executable, str(script)], check=True, capture_output=True, text=True)

    frozen_file = bundle_root / "_internal" / "cryodaq" / "gui" / "_theme_loader.py"
    module = types.ModuleType("frozen_theme_loader_probe")
    module.__file__ = str(frozen_file)
    monkeypatch.delenv("CRYODAQ_ROOT", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root / "_internal"), raising=False)
    monkeypatch.setattr(sys, "executable", str(bundle_root / "CryoDAQ.exe"), raising=False)
    exec(
        compile(
            (repo_root / "src" / "cryodaq" / "gui" / "_theme_loader.py").read_text(encoding="utf-8"),
            str(frozen_file),
            "exec",
        ),
        module.__dict__,
    )

    assert module.THEMES_DIR == bundle_root / "config" / "themes"
    theme_id, pack = module.resolve_theme()
    assert (module.THEMES_DIR / "warm_stone.yaml").is_file()
    assert theme_id == "warm_stone"
    assert pack["BACKGROUND"].startswith("#")


def test_write_theme_selection_creates_file(monkeypatch, tmp_path):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    assert not settings_file.exists()

    loader.write_theme_selection("warm_stone")

    data = yaml.safe_load(settings_file.read_text())
    assert data == {"theme": "warm_stone"}


def test_write_theme_selection_preserves_other_keys(monkeypatch, tmp_path):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    settings_file.write_text(yaml.safe_dump({"theme": "warm_stone", "other_key": "value"}))

    loader.write_theme_selection("warm_stone")  # same theme, preserve keys

    data = yaml.safe_load(settings_file.read_text())
    assert data["theme"] == "warm_stone"
    assert data["other_key"] == "value"


def test_write_theme_selection_refuses_corrupt_settings(monkeypatch, tmp_path):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    original = "theme: [unterminated"
    settings_file.write_text(original)

    with pytest.raises(loader.ThemePackError, match="selection was not changed"):
        loader.write_theme_selection("warm_stone")

    assert settings_file.read_text() == original


def test_write_theme_selection_rejects_unknown_or_unsafe_id(monkeypatch, tmp_path):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")

    with pytest.raises(loader.ThemePackError):
        loader.write_theme_selection("missing")
    with pytest.raises(loader.ThemePackError, match="invalid theme identifier"):
        loader.write_theme_selection("../warm_stone")

    assert not settings_file.exists()


def test_write_theme_selection_uses_atomic_replace(monkeypatch, tmp_path):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    calls: list[tuple[Path, str]] = []

    def _atomic_write(path: Path, content: str, *, encoding: str = "utf-8") -> None:
        calls.append((path, content))
        path.write_text(content, encoding=encoding)

    monkeypatch.setattr(loader, "atomic_write_text", _atomic_write)

    loader.write_theme_selection("warm_stone")

    assert [path for path, _content in calls] == [settings_file]
    assert yaml.safe_load(calls[0][1]) == {"theme": "warm_stone"}


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


def test_available_themes_excludes_invalid_packs(monkeypatch, tmp_path):
    themes_dir, _ = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    _write_pack(themes_dir / "broken.yaml", overrides={"BACKGROUND": None})

    assert [item["id"] for item in loader.available_themes()] == ["warm_stone"]


def test_resolve_theme_reports_actual_default_after_fallback(monkeypatch, tmp_path):
    themes_dir, settings_file = _isolate(monkeypatch, tmp_path)
    _write_pack(themes_dir / "warm_stone.yaml")
    _write_pack(themes_dir / "broken.yaml", overrides={"ACCENT": "invalid"})
    settings_file.write_text("theme: broken\n")

    theme_id, pack = loader.resolve_theme()

    assert theme_id == "warm_stone"
    assert pack["ACCENT"] == "#b89e7a"


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
_ADR_001_PACKS = frozenset({"signal", "instrument", "amber", "gost", "xcode", "braun"})

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


def _mechanical_accessibility_contract() -> dict:
    manifest = _MANIFEST.read_text(encoding="utf-8")
    assert "\ufffd" not in manifest
    assert manifest.count(_MACHINE_GATE_START) == 1
    assert manifest.count(_MACHINE_GATE_END) == 1
    payload = manifest.split(_MACHINE_GATE_START, 1)[1].split(_MACHINE_GATE_END, 1)[0]
    gate = json.loads(payload)
    assert gate["schema_version"] == 1
    return gate["mechanical_accessibility"]


def test_machine_accessibility_contrast_contract_matches_all_real_themes(real_themes_dir):
    contract = _mechanical_accessibility_contract()
    assert contract["target"] == "WCAG 2.2 AA"
    cases = contract["contrast_cases"]
    exceptions = contract["contrast_exceptions"]
    case_by_id = {case["id"]: case for case in cases}
    exception_by_id = {exception["id"]: exception for exception in exceptions}
    assert len(case_by_id) == len(cases)
    assert len(exception_by_id) == len(exceptions)

    for case_id, required in _REQUIRED_CONTRAST_CASES.items():
        assert case_id in case_by_id, f"missing required contrast case: {case_id}"
        case = case_by_id[case_id]
        actual = (case["foreground"], case["background"], case["minimum"])
        assert actual == required, (case_id, actual, required)

    for exception_id, required_floors in _REQUIRED_EXCEPTION_RATIO_FLOORS.items():
        assert exception_id in exception_by_id, f"missing required contrast exception: {exception_id}"
        manifest_floors = exception_by_id[exception_id]["ratio_floors"]
        for theme_id, required_floor in required_floors.items():
            assert theme_id in manifest_floors, (exception_id, theme_id)
            assert manifest_floors[theme_id] >= required_floor, (
                exception_id,
                theme_id,
                manifest_floors[theme_id],
                required_floor,
            )

    by_case = {exception["case_id"]: exception for exception in exceptions}
    assert len(by_case) == len(exceptions)
    minimum_by_criterion = {"1.4.3": 4.5, "1.4.11": 3.0}

    packs = {path.stem: loader.validate_theme_pack(path.stem) for path in sorted(real_themes_dir.glob("*.yaml"))}
    assert packs
    for case in cases:
        assert case["minimum"] == minimum_by_criterion[case["criterion"]], case
        ratios = {
            theme_id: _contrast_ratio(pack[case["foreground"]], pack[case["background"]])
            for theme_id, pack in packs.items()
        }
        failed_themes = sorted(theme_id for theme_id, ratio in ratios.items() if ratio < case["minimum"])
        exception = by_case.get(case["id"])
        expected_failures = [] if exception is None else exception["themes"]
        if exception is not None:
            assert expected_failures == sorted(set(expected_failures)), exception["id"]
            assert expected_failures, f"stale empty contrast exception: {exception['id']}"
        assert failed_themes == expected_failures, (
            case["id"],
            case["foreground"],
            case["background"],
            failed_themes,
            expected_failures,
        )
        if exception is not None:
            assert exception["scope"].strip()
            assert exception["rationale"].strip()
            assert exception["fallback_channels"]
            assert exception["human_verification"].strip()
            ratio_floors = exception["ratio_floors"]
            assert set(ratio_floors) == set(expected_failures), exception["id"]
            for theme_id, floor in ratio_floors.items():
                assert type(floor) in {int, float} and 0 < floor < case["minimum"], (exception["id"], theme_id)
                assert round(ratios[theme_id], 6) >= floor, (
                    exception["id"],
                    theme_id,
                    round(ratios[theme_id], 6),
                    floor,
                )

    assert set(by_case) <= set(case_by_id)


def test_machine_accessibility_non_color_states_match_real_runtime_contract():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from cryodaq.gui import theme
    from cryodaq.gui.presentation_severity import operator_state_for_display
    from cryodaq.gui.shell.operator_components import CanonicalStatusLabel
    from cryodaq.gui.shell.operator_components._visuals import paint_state_shape, state_visual
    from cryodaq.operator_snapshot import OperatorPresentationState

    app = QApplication.instance() or QApplication([])
    states = _mechanical_accessibility_contract()["states"]
    assert {item["source"] for item in states} == {state.value for state in OperatorPresentationState}
    canonical_shapes: dict[str, str] = {}
    rendered_masks: dict[str, tuple[bool, ...]] = {}
    status_label = CanonicalStatusLabel()
    try:
        for item in states:
            source_state = OperatorPresentationState(item["source"])
            display_state = operator_state_for_display(source_state)
            visual = state_visual(source_state)
            assert display_state.value == item["canonical"]
            assert visual.label == item["label"]
            assert visual.accessible_label == item["accessible_label"]
            assert visual.shape == item["shape"]
            assert visual.color == getattr(theme, item["token"])
            assert any("А" <= character <= "я" or character == "Ё" for character in visual.label)
            canonical_shapes.setdefault(item["canonical"], item["shape"])
            assert canonical_shapes[item["canonical"]] == item["shape"]

            status_label.set_state(source_state)
            assert status_label.accessibleName() == f"Состояние: {item['accessible_label']}"
            assert status_label.accessibleDescription() == (
                f"Каноническое состояние {item['canonical']}; обозначено формой и текстом {item['label']}."
            )

            if item["canonical"] not in rendered_masks:
                image = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                try:
                    paint_state_shape(painter, source_state, center_x=16, center_y=16, radius=6)
                finally:
                    painter.end()
                mask = tuple(
                    image.pixelColor(x, y).alpha() > 0 for y in range(image.height()) for x in range(image.width())
                )
                assert any(mask), item["canonical"]
                rendered_masks[item["canonical"]] = mask
    finally:
        status_label.deleteLater()
        app.processEvents()

    assert canonical_shapes == _SUPPORTED_CANONICAL_SHAPES
    assert set(rendered_masks) == set(_SUPPORTED_CANONICAL_SHAPES)
    assert len(set(rendered_masks.values())) == len(_SUPPORTED_CANONICAL_SHAPES)


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
    packs = {pack_file.stem: loader._load_theme_pack(pack_file.stem) for pack_file in real_themes_dir.glob("*.yaml")}
    assert packs
    for token in _STATUS_TOKENS:
        hues = {name: _hue(p[token]) for name, p in packs.items()}
        base = next(iter(hues.values()))
        for name, h in hues.items():
            delta = min(abs(h - base), 360.0 - abs(h - base))
            assert delta <= 5.0, f"{token} hue {h:.1f}° in {name} differs >5° from base {base:.1f}°"


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
                f"{name}: ACCENT hue {accent_hue:.1f}° only {delta:.1f}° from {token} {status_hue:.1f}° (need ≥30°)"
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


# =============================================================================
# Phase III.A — neutral interaction tokens
# =============================================================================

# default_cool is a historical exception — its ACCENT is pre-switcher
# indigo (hue ≈230°) and the invariant ≥60° vs STATUS_OK (140°) holds
# at 90° distance naturally; but the «warm-neutral recalibration» target
# does not apply. taupe_quiet used to have an identical ACCENT == STATUS_OK
# (documented as "by design"); III.A decoupled it to warm taupe.
_III_A_PACKS = frozenset(
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
        "gost",
        "xcode",
        "braun",
    }
)


def test_selection_bg_present_in_all_themes(real_themes_dir):
    """III.A neutral token invariant — SELECTION_BG is required."""
    for pack_file in real_themes_dir.glob("*.yaml"):
        pack = loader._load_theme_pack(pack_file.stem)
        assert "SELECTION_BG" in pack, f"{pack_file.stem} missing SELECTION_BG"
        assert isinstance(pack["SELECTION_BG"], str)
        assert pack["SELECTION_BG"].startswith("#")


def test_focus_ring_present_in_all_themes(real_themes_dir):
    """III.A neutral token invariant — FOCUS_RING is required."""
    for pack_file in real_themes_dir.glob("*.yaml"):
        pack = loader._load_theme_pack(pack_file.stem)
        assert "FOCUS_RING" in pack, f"{pack_file.stem} missing FOCUS_RING"
        assert isinstance(pack["FOCUS_RING"], str)
        assert pack["FOCUS_RING"].startswith("#")


def test_neutral_tokens_distinct_from_status_ok(real_themes_dir):
    """III.A: SELECTION_BG and FOCUS_RING must be chromatically
    distinct from STATUS_OK — either ≥30° hue distance OR ≥0.15
    luminance distance. Both are neutrals (near-achromatic), so the
    luminance path is the dominant one."""
    for pack_file in real_themes_dir.glob("*.yaml"):
        pack = loader._load_theme_pack(pack_file.stem)
        ok_hue = _hue(pack["STATUS_OK"])
        ok_lum = _relative_luminance(pack["STATUS_OK"])
        for token in ("SELECTION_BG", "FOCUS_RING"):
            tok_hue = _hue(pack[token])
            tok_lum = _relative_luminance(pack[token])
            hue_delta = min(abs(ok_hue - tok_hue), 360.0 - abs(ok_hue - tok_hue))
            lum_delta = abs(ok_lum - tok_lum)
            assert hue_delta >= 30.0 or lum_delta >= 0.15, (
                f"{pack_file.stem}.{token} too close to STATUS_OK: hue Δ{hue_delta:.1f}°, lum Δ{lum_delta:.3f}"
            )


def test_accent_hue_distance_from_status_ok_all_themes(real_themes_dir):
    """III.A global invariant — every bundled theme (except
    default_cool's historical baseline) keeps ACCENT hue ≥60° away
    from STATUS_OK. default_cool's indigo at ≈230° satisfies the check
    naturally; it is listed here for clarity and to guard against a
    future edit that breaks it."""
    for pack_file in real_themes_dir.glob("*.yaml"):
        name = pack_file.stem
        if name not in _III_A_PACKS:
            continue
        pack = loader._load_theme_pack(name)
        accent_hue = _hue(pack["ACCENT"])
        ok_hue = _hue(pack["STATUS_OK"])
        delta = min(abs(accent_hue - ok_hue), 360.0 - abs(accent_hue - ok_hue))
        assert delta >= 60.0, (
            f"{name}: ACCENT {pack['ACCENT']} hue {accent_hue:.1f}° only "
            f"{delta:.1f}° from STATUS_OK {pack['STATUS_OK']} hue "
            f"{ok_hue:.1f}° (III.A requires ≥60°)"
        )


def test_default_cool_accent_preserved_as_indigo():
    """III.A historical baseline — default_cool keeps pre-switcher
    indigo. Explicit guard against any rename back to the accidental
    STATUS_OK green that the other presets had."""
    pack = loader._load_theme_pack("default_cool")
    assert pack["ACCENT"] == "#7c8cff", (
        "default_cool ACCENT changed from historical indigo #7c8cff — if intentional, update this test + ADR 002"
    )


def test_warm_stone_accent_decoupled_from_status_ok():
    """III.A fix: warm_stone previously had ACCENT == STATUS_OK
    (#4a8a5e) which caused semantic collision across every primary
    button and mode badge. Guard against regression."""
    pack = loader._load_theme_pack("warm_stone")
    assert pack["ACCENT"] != pack["STATUS_OK"], "warm_stone ACCENT == STATUS_OK — III.A decoupling lost"


def test_taupe_quiet_accent_decoupled_from_status_ok():
    """III.A fix: taupe_quiet deliberately set ACCENT == STATUS_OK
    with a «by design» comment; III.A decoupled."""
    pack = loader._load_theme_pack("taupe_quiet")
    assert pack["ACCENT"] != pack["STATUS_OK"], "taupe_quiet ACCENT == STATUS_OK — III.A decoupling lost"
