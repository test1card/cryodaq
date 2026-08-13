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


def test_a_channel_without_an_effective_quantity_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "channels.yaml"
    payload = {"channels": {"Т12": {"name": "2-я ступень"}}}
    target.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    from cryodaq.core.channel_manager import ChannelConfigError

    with pytest.raises(ChannelConfigError, match="effective quantity"):
        ChannelManager(target).load()


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


@pytest.mark.parametrize("field", ["default_quantity", "quantity"])
def test_an_unknown_quantity_is_refused_before_commit(tmp_path: Path, field: str) -> None:
    payload = {"channels": {"Т1": {"name": "one"}}}
    if field == "default_quantity":
        payload[field] = "temperatue"
    else:
        payload["default_quantity"] = "temperature"
        payload["channels"]["Т1"][field] = "temperatue"
    target = tmp_path / "channels.yaml"
    target.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    # Bind the three things the operator needs, not the sentence. A refusal that only says
    # "unsupported" leaves them guessing: the message must name the offending value, say what the
    # consequence would have been, and list what is accepted.
    with pytest.raises(ChannelConfigError) as raised:
        ChannelManager(target).load()
    message = str(raised.value)
    assert "temperatue" in message
    assert "not a known physical quantity" in message
    assert "temperature" in message and "resistance" in message, "the accepted values must be listed"


def test_successful_reload_notifies_subscribers(tmp_path: Path) -> None:
    target = tmp_path / "channels.yaml"
    target.write_text(
        yaml.safe_dump({"default_quantity": "temperature", "channels": {"Т1": {"name": "one"}}}, allow_unicode=True),
        encoding="utf-8",
    )
    manager = ChannelManager(target)
    calls: list[int] = []
    manager.on_change(lambda: calls.append(1))

    target.write_text(
        yaml.safe_dump({"default_quantity": "temperature", "channels": {"Т2": {"name": "two"}}}, allow_unicode=True),
        encoding="utf-8",
    )
    manager.load()

    assert calls == [1]
    assert list(manager.get_all()) == ["Т2"]


def test_descriptor_authority_controls_quantity_and_kelvin_surfaces() -> None:
    from types import SimpleNamespace

    manager = ChannelManager()
    manager.set_descriptor_authority(
        {
            "Т1": SimpleNamespace(quantity="temperature", unit="°C"),
            "Т2": SimpleNamespace(quantity="temperature", unit="K"),
        }
    )

    assert manager.get_quantity("Т1") == "temperature"
    assert manager.get_visible_temperature_channels() == ["Т2"]


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


def test_the_shipped_selection_is_byte_for_byte_what_spelling_selected(tmp_path: Path) -> None:
    """The PR's stated purpose, as an executable assertion.

    "Nothing an operator sees changes" was prose in the row and a claim in the
    commit message; here it is a measurement, run at the same commit as the
    change. The OLD selector and the NEW one are both applied to the real
    shipped configuration and required to agree EXACTLY.

    Any deliberate difference must be listed here explicitly. There are none:
    an empty list is the assertion, not an oversight.
    """

    manager = ChannelManager(SHIPPED_CHANNELS)
    manager.load()

    by_spelling = [ch for ch in manager.get_all_visible() if ch.startswith(CYRILLIC_TE)]
    by_declaration = manager.get_visible_temperature_channels()
    deliberate_differences: set[str] = set()

    assert set(by_declaration) ^ set(by_spelling) == deliberate_differences, (
        "the migration changes what an operator sees on the shipped configuration: "
        f"added={sorted(set(by_declaration) - set(by_spelling))}, "
        f"removed={sorted(set(by_spelling) - set(by_declaration))}. A migration that quietly changes a "
        "screen is the failure behind revert 0bea0449; if a difference is intended, name it above."
    )
    # ORDER IS PART OF THE CONTRACT, and the set comparison above cannot see it.
    # `get_visible_temperature_channels` documents that it preserves visible
    # ordering, and the grid, the plot and the watch bar all render in the order
    # they are handed. Reversing or sorting the result would leave every
    # membership assertion on this branch green while every operator screen
    # reordered itself, so "byte-for-byte" is asserted as a SEQUENCE here.
    assert by_declaration == by_spelling, (
        "the migration preserves membership but not ORDER: "
        f"declared={by_declaration}, spelling={by_spelling}. Operator surfaces render in the order they "
        "are given, so a reordering is a visible change even when the set is identical."
    )
    assert by_declaration, "the shipped configuration selects no temperature channels at all"

    control = _manager(
        tmp_path,
        {
            "default_quantity": "temperature",
            "channels": {
                "RENAMED": {"name": "temperature", "visible": True},
                "Т9": {"name": "pressure", "visible": True, "quantity": "pressure"},
            },
        },
    )
    assert control.get_visible_temperature_channels() == ["RENAMED"], (
        "the shipped-only baseline cannot detect a return to spelling; this mixed declaration must"
    )


def test_a_refused_reload_leaves_the_live_channel_set_untouched(tmp_path: Path) -> None:
    """A reload that raises must not half-apply.

    `load()` assigned `self._channels` before validating `default_quantity`, so
    reloading a file whose channels are fine and whose declaration is malformed
    swapped the live channel set and THEN raised. The manager was left serving
    the new channels under the old declaration — a configuration no file on disk
    describes, produced while an operator was running the instrument.
    """

    manager = _manager(
        tmp_path,
        {"default_quantity": "temperature", "channels": {"Т1": {"name": "one", "visible": True}}},
    )
    before_channels = list(manager.get_all())
    before_quantity = manager.get_quantity("Т1")

    target = tmp_path / "channels.yaml"
    target.write_text(
        yaml.safe_dump(
            {"default_quantity": ["not", "a", "string"], "channels": {"Т9": {"name": "nine", "visible": True}}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ChannelConfigError):
        manager.load()

    assert list(manager.get_all()) == before_channels, "a refused reload replaced the live channel set"
    assert manager.get_quantity("Т1") == before_quantity, "a refused reload changed what the live channels declare"


def test_a_refused_reload_does_not_adopt_the_rejected_path(tmp_path: Path) -> None:
    """The path is state, and a refused `load(new_path)` must not keep it.

    `self._config_path = path` ran before any validation, so a reload that
    REFUSED still left the manager pointing at the rejected file. The next
    argument-less `load()` — and every `save()` — would then target a
    configuration the instrument had already declined, which is how a rejected
    file becomes the live one by a route nobody wrote down.
    """

    good = tmp_path / "good"
    good.mkdir()
    manager = _manager(good, {"default_quantity": "temperature", "channels": {"Т1": {"name": "one"}}})
    original_path = manager._config_path

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        yaml.safe_dump({"default_quantity": 12345, "channels": {"Т9": {"name": "nine"}}}, allow_unicode=True),
        encoding="utf-8",
    )
    with pytest.raises(ChannelConfigError):
        manager.load(bad)

    assert manager._config_path == original_path, "a refused reload adopted the rejected path"
    # And the refusal must not have disturbed what the manager serves.
    assert list(manager.get_all()) == ["Т1"]


@pytest.mark.parametrize("bad", [["temperature"], {"kind": "temperature"}])
def test_a_non_string_quantity_is_refused_as_a_configuration_error(tmp_path: Path, bad: object) -> None:
    """An unhashable quantity must not escape as TypeError from the membership test.

    `quantity: [temperature]` is a YAML sequence, and asking whether it is in a frozenset raises
    TypeError, which bypasses the ChannelConfigError path the engine handles and reaches the
    operator as a bare startup traceback instead of an actionable refusal.
    """
    payload = {"default_quantity": "temperature", "channels": {"Т1": {"name": "one", "quantity": bad}}}
    target = tmp_path / "channels.yaml"
    target.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ChannelConfigError, match="must be a string"):
        ChannelManager(target).load()
