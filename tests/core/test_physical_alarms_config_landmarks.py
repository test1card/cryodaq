"""F-ChannelLandmarks: load_channel_landmarks parses the optional landmarks: section."""

from __future__ import annotations

from pathlib import Path

from cryodaq.core.physical_alarms_config import load_channel_landmarks


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_landmarks_section_parsed(tmp_path: Path) -> None:
    cfg = tmp_path / "physical_alarms.yaml"
    _write(
        cfg,
        """
landmarks:
  Т11:
    role: warm_stage
    physical: "1-я ступень GM-cooler, ~40K"
    aliases:
      - "азотная плита"
      - "плита"
  Т12:
    role: cold_stage
    physical: "2-я ступень GM-cooler"
    aliases:
      - "холодная точка"
""",
    )
    landmarks = load_channel_landmarks(cfg)
    assert set(landmarks) == {"Т11", "Т12"}
    assert landmarks["Т11"]["role"] == "warm_stage"
    assert landmarks["Т11"]["physical"] == "1-я ступень GM-cooler, ~40K"
    assert landmarks["Т11"]["aliases"] == ["азотная плита", "плита"]
    assert landmarks["Т12"]["aliases"] == ["холодная точка"]


def test_landmarks_missing_returns_empty_dict(tmp_path: Path) -> None:
    """A YAML without a `landmarks:` section yields {}, not an exception."""
    cfg = tmp_path / "physical_alarms.yaml"
    _write(
        cfg,
        """
cooldown:
  enabled: true
""",
    )
    assert load_channel_landmarks(cfg) == {}


def test_landmarks_missing_file_returns_empty_dict(tmp_path: Path) -> None:
    """Non-existent file is treated as 'no landmarks installed'."""
    assert load_channel_landmarks(tmp_path / "does-not-exist.yaml") == {}


def test_landmarks_aliases_lowercase_normalized(tmp_path: Path) -> None:
    """Aliases are lowercased and stripped so case-insensitive matching is
    free downstream."""
    cfg = tmp_path / "physical_alarms.yaml"
    _write(
        cfg,
        """
landmarks:
  Т11:
    role: warm_stage
    physical: "1-я ступень"
    aliases:
      - "  Азотная Плита  "
      - "T Warm"
      - "WARM CHANNEL"
""",
    )
    aliases = load_channel_landmarks(cfg)["Т11"]["aliases"]
    assert aliases == ["азотная плита", "t warm", "warm channel"]


def test_landmarks_malformed_entry_skipped(tmp_path: Path) -> None:
    """A non-mapping landmark entry is dropped; the rest still load."""
    cfg = tmp_path / "physical_alarms.yaml"
    _write(
        cfg,
        """
landmarks:
  Т11:
    role: warm_stage
    physical: "1-я ступень"
    aliases: ["азотная плита"]
  Т12: "broken_string_entry"
""",
    )
    landmarks = load_channel_landmarks(cfg)
    assert set(landmarks) == {"Т11"}


def test_landmarks_missing_aliases_yields_empty_list(tmp_path: Path) -> None:
    cfg = tmp_path / "physical_alarms.yaml"
    _write(
        cfg,
        """
landmarks:
  Т11:
    role: warm_stage
    physical: "1-я ступень"
""",
    )
    assert load_channel_landmarks(cfg)["Т11"]["aliases"] == []


def test_landmarks_yaml_error_returns_empty_dict(tmp_path: Path) -> None:
    cfg = tmp_path / "physical_alarms.yaml"
    _write(cfg, "landmarks:\n  Т11:\n    aliases:\n      - [unclosed")
    assert load_channel_landmarks(cfg) == {}
