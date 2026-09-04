"""A physically absent sensor must not be eligible for a formal report plot.

Т8 and Т16 are not connected — there were not enough contacts in the LEMO
connector — and they report -8.888e+88, the LakeShore no-sensor sentinel, on
every poll. `channels.yaml` has said `visible: false` for both all along.

`config/channel_descriptors.local.yaml` did not. It carried
`visible_by_default: true` for each, and the periodic report decides what to
plot from DESCRIPTOR visibility (`reporting/sections.py::_visible_quantity`),
not from `channels.yaml`. So two sensors that cannot produce a reading stayed
eligible for formal temperature plots, and the two files disagreed with nothing
to notice it.

This pins the agreement rather than the fix, because the fix is one flag and
the hazard is the divergence.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]

# Not connected on this stand. Named explicitly rather than derived, so that
# reconnecting a sensor is a deliberate edit here and not a silent drift.
_PHYSICALLY_ABSENT = ("Т8", "Т16")


def _descriptors() -> dict[str, dict]:
    document = yaml.safe_load(
        (_ROOT / "config" / "channel_descriptors.local.yaml").read_text(encoding="utf-8")
    )
    return {
        entry["channel_id"]: entry
        for entry in document["descriptors"]
        if isinstance(entry, dict)
    }


def _channels() -> dict[str, dict]:
    document = yaml.safe_load((_ROOT / "config" / "channels.yaml").read_text(encoding="utf-8"))
    return document["channels"]


@pytest.mark.parametrize("channel_id", _PHYSICALLY_ABSENT)
def test_an_absent_sensor_is_not_report_visible(channel_id: str) -> None:
    """The gate the periodic report actually consults."""

    descriptor = _descriptors()[channel_id]
    assert descriptor["visible_by_default"] is False, (
        f"{channel_id} is not physically connected, but its descriptor makes it "
        "eligible for a formal temperature plot — reports select on "
        "descriptor.visible_by_default, not on channels.yaml"
    )


@pytest.mark.parametrize("channel_id", _PHYSICALLY_ABSENT)
def test_the_raw_sibling_is_not_report_visible_either(channel_id: str) -> None:
    raw = _descriptors()[f"{channel_id}.raw"]
    assert raw["visible_by_default"] is False


@pytest.mark.parametrize("channel_id", _PHYSICALLY_ABSENT)
def test_the_two_configuration_files_agree(channel_id: str) -> None:
    """The divergence is the defect; either file alone looked reasonable."""

    channels_visible = _channels()[channel_id]["visible"]
    descriptor_visible = _descriptors()[channel_id]["visible_by_default"]
    assert channels_visible == descriptor_visible is False, (
        f"{channel_id}: channels.yaml visible={channels_visible} but descriptor "
        f"visible_by_default={descriptor_visible}. Two files describing one "
        "sensor's visibility must not disagree — the GUI reads one and the "
        "periodic report reads the other."
    )


def test_a_connected_sensor_is_still_plottable() -> None:
    """Guard against 'fixing' this by hiding everything.

    Т15 is the only live warm_flange sensor left once Т16 is excluded, so it
    must stay visible; if this ever fails alongside the tests above, the
    exclusion has been applied too broadly.
    """

    assert _descriptors()["Т15"]["visible_by_default"] is True
    assert _descriptors()["Т12"]["visible_by_default"] is True


def test_the_report_gate_reads_descriptor_visibility() -> None:
    """Pin the coupling this test exists to protect.

    If report eligibility stops consulting `visible_by_default`, the alignment
    above stops being the thing that keeps absent sensors out of plots, and
    this file would pass while the hazard returned.
    """

    import inspect

    from cryodaq.reporting.sections import _visible_quantity

    source = inspect.getsource(_visible_quantity)
    assert "visible_by_default" in source
    assert "quantity" in source
