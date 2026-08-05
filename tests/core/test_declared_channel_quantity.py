"""OC-030 — operator screens select channels by DECLARED quantity, not spelling.

Seven live GUI sites asked ``channel.startswith("Т")`` and treated the answer as
"this is a temperature".  Today every declared channel happens to start with
Cyrillic Т, so spelling and reality coincide exactly -- which is precisely why
the defect is invisible until a rename or a non-temperature channel arrives.

Three properties, and the first two matter most:

* a RENAMED temperature channel is still selected.  This is the defect: an
  operator readout could vanish from a screen because an identifier changed;
* a channel that DECLARES a different quantity is excluded however it is
  spelled, including a name beginning with Cyrillic Т;
* against today's configuration the declared selection is IDENTICAL to the
  spelling selection, so the migration changes no operator screen on landing.

The third is the no-regression baseline.  A migration that quietly changes what
an operator sees is the failure behind revert ``0bea0449``, and the guard has to
say it did not happen rather than assume it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cryodaq.core.channel_manager import ChannelManager

CYRILLIC_TE = "Т"
REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_CHANNELS = REPO_ROOT / "config" / "channels.yaml"


def _manager(tmp_path: Path, payload: dict) -> ChannelManager:
    target = tmp_path / "channels.yaml"
    target.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    manager = ChannelManager(target)
    manager.load()
    return manager


def test_the_shipped_configuration_selects_exactly_what_spelling_selected() -> None:
    """No operator screen changes on landing.  The baseline, measured not assumed."""

    manager = ChannelManager(SHIPPED_CHANNELS)
    manager.load()

    declared = set(manager.get_temperature_channels())
    by_spelling = {ch for ch in manager.get_all() if ch.startswith(CYRILLIC_TE)}

    assert declared == by_spelling, (
        "the declared selection differs from the spelling selection on the shipped "
        f"config: declared-only={sorted(declared - by_spelling)}, "
        f"spelling-only={sorted(by_spelling - declared)}"
    )
    assert declared, "the shipped config declares no temperature channels at all"


def test_a_renamed_temperature_channel_is_still_selected(tmp_path: Path) -> None:
    """The defect, stated as a behaviour.

    Under spelling inference this channel disappears from every temperature
    surface the moment it is renamed, with no diagnostic anywhere.
    """

    manager = _manager(
        tmp_path,
        {
            "default_quantity": "temperature",
            "channels": {"CRYO_STAGE_2": {"name": "Вторая ступень", "visible": True}},
        },
    )

    assert manager.is_temperature_channel("CRYO_STAGE_2") is True
    assert manager.get_temperature_channels() == ["CRYO_STAGE_2"]
    assert "CRYO_STAGE_2".startswith(CYRILLIC_TE) is False, "premise: spelling would have rejected it"


def test_a_declared_non_temperature_is_excluded_however_it_is_spelled(tmp_path: Path) -> None:
    """A pressure channel named like a temperature must not be routed as one."""

    manager = _manager(
        tmp_path,
        {
            "default_quantity": "temperature",
            "channels": {
                "Т90": {"name": "Давление камеры", "visible": True, "quantity": "pressure"},
                "Т12": {"name": "2-я ступень", "visible": True},
            },
        },
    )

    assert manager.is_temperature_channel("Т90") is False
    assert manager.is_temperature_channel("Т12") is True
    assert manager.get_temperature_channels() == ["Т12"]
    assert "Т90".startswith(CYRILLIC_TE) is True, "premise: spelling would have accepted it"


def test_an_undeclared_channel_reports_no_quantity_rather_than_guessing(tmp_path: Path) -> None:
    """Absent declaration is absent, not inferred.

    Callers must render such a channel MARKED rather than hidden -- see
    docs/design-system/patterns/state-visualization.md.  Returning a guess here
    would push the inference one layer down instead of removing it.
    """

    manager = _manager(tmp_path, {"channels": {"Т12": {"name": "2-я ступень", "visible": True}}})

    assert manager.get_quantity("Т12") is None
    assert manager.is_temperature_channel("Т12") is False
    assert manager.get_quantity("NOT_A_CHANNEL") is None


def test_a_full_channel_id_resolves_through_its_short_form(tmp_path: Path) -> None:
    """Runtime ids carry the display name; the declaration is keyed on the short id."""

    manager = _manager(
        tmp_path,
        {"default_quantity": "temperature", "channels": {"Т12": {"name": "2-я ступень", "visible": True}}},
    )

    assert manager.is_temperature_channel("Т12 Теплообменник 2") is True


def test_visible_temperature_channels_respect_visibility(tmp_path: Path) -> None:
    manager = _manager(
        tmp_path,
        {
            "default_quantity": "temperature",
            "channels": {
                "Т11": {"name": "1-я ступень", "visible": True},
                "Т12": {"name": "2-я ступень", "visible": False},
            },
        },
    )

    assert manager.get_temperature_channels() == ["Т11", "Т12"]
    assert manager.get_visible_temperature_channels() == ["Т11"]


@pytest.mark.parametrize("bad", [123, ["temperature"], {"q": 1}])
def test_a_malformed_default_quantity_is_refused(tmp_path: Path, bad: object) -> None:
    """Fail closed on a malformed declaration rather than silently ignoring it."""

    from cryodaq.core.channel_manager import ChannelConfigError

    target = tmp_path / "channels.yaml"
    target.write_text(
        yaml.safe_dump({"default_quantity": bad, "channels": {"Т12": {"name": "x"}}}, allow_unicode=True),
        encoding="utf-8",
    )
    with pytest.raises(ChannelConfigError, match="default_quantity"):
        ChannelManager(target).load()
