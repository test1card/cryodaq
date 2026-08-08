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

from cryodaq.channels.descriptors import ChannelQuantity
from cryodaq.core.channel_manager import ChannelConfigError, ChannelManager

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


def test_a_configuration_that_declares_nothing_is_refused_at_load(tmp_path: Path) -> None:
    """The rule this file previously got BACKWARDS, and review caught it.

    An earlier version of this node loaded a configuration with neither
    `default_quantity` nor any per-channel `quantity`, asserted the answer was
    None, and moved on -- which codified, in a guard, a file that starts
    cleanly and then omits every temperature reading from the grid, the plot,
    the watch bar, the conductivity panel and dashboard ingestion, silently.

    That is the opposite of this project's rule that an unclassified reading
    renders MARKED rather than hidden, and it is the `0bea0449` shape again.
    Refusing at load is the fail-closed half of that rule: the operator is told,
    in a file they own, rather than shown a blank screen.
    """

    with pytest.raises(ChannelConfigError) as raised:
        _manager(tmp_path, {"channels": {"Т12": {"name": "2-я ступень", "visible": True}}})
    message = str(raised.value)
    assert "Т12" in message, "the refusal must name the channel the operator has to fix"
    assert "vanish" in message or "resolve to a quantity" in message


def test_an_unknown_channel_reports_no_quantity_rather_than_guessing(tmp_path: Path) -> None:
    """Absent declaration is absent, not inferred -- asserted where it can hold.

    Every channel IN the file now resolves or load fails, so the no-guessing
    rule is about ids the manager has never heard of: a reading that arrives
    for a channel absent from the configuration must not be inferred into a
    quantity from its spelling.
    """

    manager = _manager(
        tmp_path,
        {"default_quantity": "temperature", "channels": {"Т12": {"name": "2-я ступень", "visible": True}}},
    )

    assert manager.get_quantity("NOT_A_CHANNEL") is None
    assert manager.is_temperature_channel("NOT_A_CHANNEL") is False
    # Spelled exactly like the declared ones, and still not inferred.
    assert manager.get_quantity("Т99") is None
    assert manager.is_temperature_channel("Т99") is False


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


def test_saving_channel_edits_preserves_the_declaration(tmp_path: Path) -> None:
    """The defect a review found in this migration, stated as a behaviour.

    `save()` serialised only `{"channels": ...}`, so the first time an operator
    renamed or hid a channel through the editor, `default_quantity` was dropped
    from the file.  Every shipped channel relies on that default rather than a
    per-channel `quantity`, so on the next restart NOTHING declared a
    temperature and the dashboard grid, the plot, the watch bar and the
    conductivity panel all came up empty -- with no diagnostic anywhere.

    That is `0bea0449` again, arriving through the save path rather than the
    read path, and it would have been reached by ordinary use rather than by
    any unusual configuration.
    """

    manager = ChannelManager(SHIPPED_CHANNELS)
    manager.load()
    before = set(manager.get_temperature_channels())
    assert before, "premise: the shipped configuration must declare temperatures"

    # Exactly what the editor does: rename one channel, hide another, save.
    first, second = sorted(before)[:2]
    manager.set_name(first, "Переименованный")
    manager.set_visible(second, False)
    saved = tmp_path / "channels.yaml"
    manager.save(saved)

    reloaded = ChannelManager(saved)
    reloaded.load()
    assert set(reloaded.get_temperature_channels()) == before, (
        "the declaration did not survive a save: every temperature surface would come up empty "
        f"after the next restart ({len(reloaded.get_temperature_channels())} of {len(before)} survived)"
    )
    assert "default_quantity" in yaml.safe_load(saved.read_text(encoding="utf-8"))


@pytest.mark.parametrize("bad", ["temperatue", "Temperature", "", "temp"])
def test_an_unsupported_default_quantity_is_refused_at_load(tmp_path: Path, bad: str) -> None:
    """A typo must be a startup error, not a silently blank rig.

    Any non-empty string was accepted, so `default_quantity: temperatue` loaded
    happily and then made `is_temperature_channel` false for every channel --
    the same empty screens as above, from a single wrong letter in a file the
    operator edits.  The vocabulary is `ChannelQuantity`, which the descriptor
    layer already owns; this must not invent a second one.
    """

    with pytest.raises(ChannelConfigError) as raised:
        _manager(tmp_path, {"default_quantity": bad, "channels": {"Т1": {"name": "к"}}})
    assert "not a supported quantity" in str(raised.value) or "must be a string" in str(raised.value)


def test_an_unsupported_per_channel_quantity_is_refused_at_load(tmp_path: Path) -> None:
    """The per-channel override needs the same closed vocabulary as the default."""

    with pytest.raises(ChannelConfigError) as raised:
        _manager(
            tmp_path,
            {
                "default_quantity": "temperature",
                "channels": {"Т1": {"name": "к"}, "Т2": {"name": "к", "quantity": "presure"}},
            },
        )
    assert "presure" in str(raised.value)


def test_every_supported_quantity_is_accepted(tmp_path: Path) -> None:
    """The refusal must not become a refusal of legitimate configurations.

    Without this, tightening the check to a single value would pass every node
    above while making the file unwritable for any rig that is not all
    temperatures.
    """

    for quantity in ChannelQuantity:
        manager = _manager(tmp_path, {"default_quantity": quantity.value, "channels": {"Т1": {"name": "к"}}})
        assert manager.get_quantity("Т1") == quantity.value


def test_a_rejected_reload_preserves_the_last_valid_configuration(tmp_path: Path) -> None:
    """`load()` published before it validated, so a REFUSED file half-applied.

    `self._channels` was assigned before the checks could raise, so a manager
    that rejected a reload was left holding the invalid configuration while the
    caller saw only an exception -- and the operator-reachable reset handler
    calls `load()` directly. The visible result is the same empty temperature
    surfaces, reached this time by an error path that looked handled.
    """

    good = {"default_quantity": "temperature", "channels": {"Т1": {"name": "верх"}, "Т2": {"name": "низ"}}}
    manager = _manager(tmp_path, good)
    before_channels = dict(manager.get_all())
    before_temperatures = set(manager.get_temperature_channels())
    assert before_temperatures, "premise: the good configuration must declare temperatures"

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        yaml.safe_dump(
            {"default_quantity": "temperature", "channels": {"Т2": {"name": "низ", "quantity": "presure"}}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ChannelConfigError):
        manager.load(bad)

    assert manager.get_all() == before_channels, "a refused reload replaced the live channel table"
    assert set(manager.get_temperature_channels()) == before_temperatures, (
        "a refused reload emptied the temperature surfaces it was supposed to leave untouched"
    )
