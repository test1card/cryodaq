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

    # And the declaration must match the DESCRIPTORS, not the roster: the liveness check
    # also requires safety_class SAFETY_CRITICAL_INPUT and a role that is not
    # SOURCE_READBACK, so declaring the whole roster only moves the refusal to the next
    # plane. For this fixture that leaves the two channels LS218_2 carries as
    # safety-critical inputs. The assertion below derives the expectation from the
    # descriptors rather than naming those two, so the test follows a descriptor added or
    # removed later instead of blocking it.
    expected = sorted(
        item["channel_id"]
        for item in descriptors["descriptors"]
        if item.get("safety_class") == "safety_critical_input" and item.get("role") != "source_readback"
    )
    assert sorted(declared) == expected
