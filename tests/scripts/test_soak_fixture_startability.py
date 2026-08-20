"""Can the soak fixture start the engine at all?

A SEPARATE module on purpose. These tests and the theme-pack tests were added to
`tests/scripts/test_soak_mock_fixture.py` on different branches, and the two branches then
conflicted there every time they met -- contention created by WHERE the tests were put, not
by what they assert. Splitting costs nothing and removes it.

What they cover is the chain of refusals the engine raises before it will run: an exact
canonical identity in `critical_channels`, a descriptor that classifies that identity
safety-critical, and a physical-alarms document the production loader accepts whole. Each
one was found only by running the engine alone, because the launcher discards its stderr.
"""

from __future__ import annotations

import yaml

from scripts import soak_mock_stack_runner as runner


def test_the_fixture_physical_alarms_document_is_complete_and_disarmed(tmp_path) -> None:
    """The production loader accepts nothing less than a complete document.

    It requires exactly cooldown, vacuum and landmarks, complete key sets in the first
    two, and the two canonical landmark channels with non-empty alias lists in the third.
    The fixture used to write a four-line static string, and the engine refused to start
    on it with ``physical alarms document must contain exactly cooldown, vacuum,
    landmarks``. Taking the tracked document and disarming it keeps the soak passive
    without inventing a document the loader has never reviewed.
    """
    from cryodaq.core.physical_alarms_config import load_production_physical_alarms_config

    runner._materialize_isolated_mock_config(tmp_path)
    path = tmp_path / "physical_alarms.yaml"

    cooldown, vacuum, landmarks = load_production_physical_alarms_config(path)

    assert cooldown["enabled"] is False, "the soak must not arm cooldown alarms"
    assert vacuum["enabled"] is False, "the soak must not arm vacuum alarms"
    assert set(landmarks) == {"\u0422\u0031\u0031", "\u0422\u0031\u0032"}


def test_the_fixture_declares_critical_channels_that_actually_exist(tmp_path) -> None:
    """`critical_channels` entries are EXACT canonical identities, never patterns.

    `_resolve_critical_bindings` does `if channel_id not in storage_catalog.by_channel_id`,
    so the literal string ".*" is simply a channel nobody has. The fixture declared exactly
    that, meaning "everything", and the engine therefore refused to start at its boot-time
    safety liveness check -- the F-1 silent-safety-kill guard doing its job. Measured on
    Ubuntu 22.04.5: the launcher started, the engine died before its readiness receipt, and
    the reason was `Dead safety/alarm channel pattern(s): 1 match NO channel ... pattern='.*'`.
    """
    runner._materialize_isolated_mock_config(tmp_path)

    safety = yaml.safe_load((tmp_path / "safety.yaml").read_text(encoding="utf-8"))
    descriptors = yaml.safe_load((tmp_path / "channel_descriptors.yaml").read_text(encoding="utf-8"))
    roster = {item["channel_id"] for item in descriptors["descriptors"]}

    declared = safety["critical_channels"]
    assert set(declared) <= roster, (
        f"every declared identity must exist on the roster; strays: {sorted(set(declared) - roster)}"
    )
    # A dot is legitimate INSIDE an identity -- the roster carries names like "T1.raw" --
    # so the check is for the wildcard that made the old declaration dead, not for every
    # character a regular expression happens to use.
    assert all("*" not in name for name in declared), (
        "these are identities, not patterns; a wildcard here matches no channel at all"
    )

    # And the declaration must match the DESCRIPTORS by the ENGINE's rule, not the
    # fixture's. `safety_pattern_liveness.py` builds `critical_manifest_ids` from
    # descriptors whose QUANTITY is temperature AND whose safety class is
    # safety_critical_input, and refuses when the declared set is not exactly that set. It
    # applies no role test at all.
    #
    # THE EARLIER VERSION OF THIS ASSERTION RESTATED THE FIXTURE'S OWN FILTER, so it could
    # not detect drift from the engine: both sides would have moved together and stayed
    # green while the engine refused to start. Here the expectation is written out from
    # the production rule instead.
    expected = sorted(
        item["channel_id"]
        for item in descriptors["descriptors"]
        if item.get("quantity") == "temperature"
        and item.get("safety_class") == "safety_critical_input"
    )
    assert sorted(declared) == expected
    assert declared, "an empty critical_channels list is refused by the engine outright"


def test_a_non_temperature_safety_critical_descriptor_is_not_declared() -> None:
    """The rule the engine applies, exercised on a descriptor the fixture does not carry.

    This is the case the previous assertion could never reach. LS218_2's two safety-critical
    descriptors are both `quantity=temperature`, so every filter that tests safety class
    alone agrees with the engine TODAY. A safety-critical descriptor of another quantity
    would be over-declared by such a filter, the engine's union check would fire, and the
    engine would refuse to start -- while the fixture's own test still passed.
    """

    from scripts.soak_mock_stack_runner import _engine_critical_channel_ids

    descriptors = [
        {"channel_id": "A", "quantity": "temperature", "safety_class": "safety_critical_input"},
        {"channel_id": "B", "quantity": "pressure", "safety_class": "safety_critical_input"},
        {"channel_id": "C", "quantity": "temperature", "safety_class": "observational"},
        {"channel_id": "D", "quantity": "raw_sensor", "safety_class": "safety_critical_input"},
    ]
    assert _engine_critical_channel_ids(descriptors) == ["A"], (
        "only a temperature descriptor classified safety-critical is what the engine counts"
    )
