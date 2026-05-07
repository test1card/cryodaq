"""F-ConfigChannelDrift: ensure cooldown.yaml uses canonical Т11/Т12."""
import yaml
from pathlib import Path


def test_cooldown_yaml_uses_canonical_channels():
    cfg_path = Path(__file__).parents[2] / "config" / "cooldown.yaml"
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cooldown = raw.get("cooldown", {})
    cold = str(cooldown.get("channel_cold", ""))
    warm = str(cooldown.get("channel_warm", ""))
    # Must reference Т12 (cold) and Т11 (warm) — verified hardware mapping
    assert "Т12" in cold, f"channel_cold должен быть Т12, получено: {cold!r}"
    assert "Т11" in warm, f"channel_warm должен быть Т11, получено: {warm!r}"
