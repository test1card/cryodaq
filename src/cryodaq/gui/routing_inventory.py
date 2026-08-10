"""Descriptor-backed inventory for live GUI routing and selection policy.

This module is declarative and observational.  It grants no driver, command, or
safety authority.  The keys describe semantic code sites, so source movement
cannot silently change their identity.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
    ChannelStreamClass,
)

DescriptorAnchor = tuple[str, str, str]
_SEMANTIC_SITE_KEY: Final = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)+")
_RAW_LINE_SEGMENT: Final = re.compile(r"(?:source-)?line(?:no)?-[0-9]+")


@dataclass(frozen=True, slots=True)
class DescriptorSelector:
    """A data-only selector over immutable channel descriptor semantics."""

    channel_ids: frozenset[str] = field(default_factory=frozenset)
    instrument_ids: frozenset[str] = field(default_factory=frozenset)
    source_keys: frozenset[str] = field(default_factory=frozenset)
    quantities: frozenset[ChannelQuantity] = field(default_factory=frozenset)
    excluded_quantities: frozenset[ChannelQuantity] = field(default_factory=frozenset)
    units: frozenset[str] = field(default_factory=frozenset)
    roles: frozenset[ChannelRole] = field(default_factory=frozenset)
    safety_classes: frozenset[ChannelSafetyClass] = field(default_factory=frozenset)
    stream_classes: frozenset[ChannelStreamClass] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        values = (
            self.channel_ids,
            self.instrument_ids,
            self.source_keys,
            self.quantities,
            self.excluded_quantities,
            self.units,
            self.roles,
            self.safety_classes,
            self.stream_classes,
        )
        if any(type(value) is not frozenset for value in values):
            raise TypeError("descriptor selector fields must be frozensets")
        if not any(values):
            raise ValueError("descriptor selector must constrain at least one descriptor field")
        if self.quantities & self.excluded_quantities:
            raise ValueError("included and excluded quantities overlap")

    def matches(self, descriptor: ChannelDescriptorV1) -> bool:
        """Return whether one real descriptor satisfies every declared field."""

        if type(descriptor) is not ChannelDescriptorV1:
            return False
        return (
            (not self.channel_ids or descriptor.channel_id in self.channel_ids)
            and (not self.instrument_ids or descriptor.instrument_id in self.instrument_ids)
            and (not self.source_keys or descriptor.source_key in self.source_keys)
            and (not self.quantities or descriptor.quantity in self.quantities)
            and descriptor.quantity not in self.excluded_quantities
            and (not self.units or descriptor.unit in self.units)
            and (not self.roles or descriptor.role in self.roles)
            and (not self.safety_classes or descriptor.safety_class in self.safety_classes)
            and (not self.stream_classes or descriptor.stream_class in self.stream_classes)
        )

    def resolve(self, descriptors: Iterable[ChannelDescriptorV1]) -> frozenset[DescriptorAnchor]:
        """Resolve to immutable descriptor anchors, never display spellings."""

        return frozenset(descriptor.anchor for descriptor in descriptors if self.matches(descriptor))


class GuiRoutingFinding(StrEnum):
    """Why a live spelling-dependent site has no complete descriptor binding."""

    ANALYTICS_DESCRIPTOR_ABSENT = "analytics_channel_not_described"
    ANNUNCIATION_PROTOCOL_IDENTITY = "annunciation_protocol_identity"
    COMMAND_TARGET_REQUIRES_SAFETY_AUTHORITY = "command_target_requires_safety_authority"
    HISTORY_REQUIRES_DESCRIPTOR_JOIN = "history_requires_descriptor_join"
    LANDMARK_ROLE_NOT_IN_DESCRIPTOR = "landmark_role_not_in_descriptor"
    SYSTEM_DESCRIPTOR_ABSENT = "system_channel_not_described"


@dataclass(frozen=True, slots=True)
class GuiRoutingInventoryEntry:
    """One live semantic GUI site and its descriptor binding or explicit gap."""

    sweep_registration_id: str
    site_key: str
    selector: DescriptorSelector | None = None
    findings: frozenset[GuiRoutingFinding] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if re.fullmatch(r"C2-[0-9]{3}", self.sweep_registration_id) is None:
            raise ValueError("sweep registration ID must use the C2-NNN grammar")
        if _SEMANTIC_SITE_KEY.fullmatch(self.site_key) is None:
            raise ValueError("site key must be normalized lowercase semantic segments")
        segments = self.site_key.split(".")
        if segments[0] != "gui":
            raise ValueError("site key must be rooted in the semantic gui namespace")
        if any(segment in {"src", "cryodaq"} for segment in segments):
            raise ValueError("site key must not encode a raw source path")
        if any(segment.isdecimal() or _RAW_LINE_SEGMENT.fullmatch(segment) for segment in segments):
            raise ValueError("site key must not encode a raw source line location")
        if self.selector is None and not self.findings:
            raise ValueError("inventory entry needs a descriptor selector or an explicit finding")
        if type(self.findings) is not frozenset:
            raise TypeError("inventory findings must be a frozenset")


_CRYOGENIC_TEMPERATURE = DescriptorSelector(
    quantities=frozenset({ChannelQuantity.TEMPERATURE}),
    units=frozenset({"K"}),
)
_VACUUM_PRESSURE = DescriptorSelector(
    instrument_ids=frozenset({"VSP63D_1"}),
    quantities=frozenset({ChannelQuantity.PRESSURE}),
    units=frozenset({"mbar"}),
    roles=frozenset({ChannelRole.PRIMARY_MEASUREMENT}),
    safety_classes=frozenset({ChannelSafetyClass.SAFETY_CRITICAL_INPUT}),
)
_ALL_TEMPERATURE = DescriptorSelector(
    quantities=frozenset({ChannelQuantity.TEMPERATURE}),
)
_NON_TEMPERATURE = DescriptorSelector(
    excluded_quantities=frozenset({ChannelQuantity.TEMPERATURE}),
)
_RAW_SENSOR = DescriptorSelector(
    quantities=frozenset({ChannelQuantity.RAW_SENSOR}),
    units=frozenset({"sensor_unit"}),
)
_MEASUREMENT_STREAM = DescriptorSelector(
    stream_classes=frozenset(
        {
            ChannelStreamClass.PASSIVE_MEASUREMENT,
            ChannelStreamClass.CALIBRATION_RAW,
            ChannelStreamClass.SOURCE_READBACK,
        }
    ),
)
_SOURCE_READBACK = DescriptorSelector(
    roles=frozenset({ChannelRole.SOURCE_READBACK}),
    safety_classes=frozenset({ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK}),
)
_SOURCE_POWER = DescriptorSelector(
    quantities=frozenset({ChannelQuantity.POWER}),
    roles=frozenset({ChannelRole.SOURCE_READBACK}),
    safety_classes=frozenset({ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK}),
)
_SOURCE_DISPLAY = DescriptorSelector(
    quantities=frozenset(
        {
            ChannelQuantity.VOLTAGE,
            ChannelQuantity.CURRENT,
            ChannelQuantity.POWER,
        }
    ),
    roles=frozenset({ChannelRole.SOURCE_READBACK}),
    safety_classes=frozenset({ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK}),
)
_SMUA_ANALYTICS = DescriptorSelector(
    source_keys=frozenset({"smua.voltage", "smua.current", "smua.power"}),
    roles=frozenset({ChannelRole.SOURCE_READBACK}),
    safety_classes=frozenset({ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK}),
)
_SMUB_ANALYTICS = DescriptorSelector(
    source_keys=frozenset({"smub.voltage", "smub.current", "smub.power"}),
    roles=frozenset({ChannelRole.SOURCE_READBACK}),
    safety_classes=frozenset({ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK}),
)
_MULTILINE_ALL = DescriptorSelector(
    instrument_ids=frozenset({"MultiLine_1"}),
    safety_classes=frozenset({ChannelSafetyClass.OBSERVATIONAL}),
)
_MULTILINE_LENGTH = DescriptorSelector(
    instrument_ids=frozenset({"MultiLine_1"}),
    source_keys=frozenset({"length.1", "length.2", "length.3", "length.4"}),
    quantities=frozenset({ChannelQuantity.LENGTH}),
    units=frozenset({"mm"}),
    roles=frozenset({ChannelRole.PRIMARY_MEASUREMENT}),
    safety_classes=frozenset({ChannelSafetyClass.OBSERVATIONAL}),
)
_MULTILINE_ENVIRONMENT = DescriptorSelector(
    instrument_ids=frozenset({"MultiLine_1"}),
    source_keys=frozenset({"env.temperature", "env.pressure", "env.humidity"}),
    roles=frozenset({ChannelRole.ENVIRONMENT}),
    safety_classes=frozenset({ChannelSafetyClass.OBSERVATIONAL}),
)
_T11 = DescriptorSelector(
    instrument_ids=frozenset({"LS218_2"}),
    source_keys=frozenset({"input.3.temperature"}),
    quantities=frozenset({ChannelQuantity.TEMPERATURE}),
)
_T12 = DescriptorSelector(
    instrument_ids=frozenset({"LS218_2"}),
    source_keys=frozenset({"input.4.temperature"}),
    quantities=frozenset({ChannelQuantity.TEMPERATURE}),
)
_T11_T12 = DescriptorSelector(
    instrument_ids=frozenset({"LS218_2"}),
    source_keys=frozenset({"input.3.temperature", "input.4.temperature"}),
    quantities=frozenset({ChannelQuantity.TEMPERATURE}),
)

_ANALYTICS = frozenset({GuiRoutingFinding.ANALYTICS_DESCRIPTOR_ABSENT})
_ANNUNCIATION = frozenset({GuiRoutingFinding.ANNUNCIATION_PROTOCOL_IDENTITY})
_COMMAND = frozenset({GuiRoutingFinding.COMMAND_TARGET_REQUIRES_SAFETY_AUTHORITY})
_HISTORY = frozenset({GuiRoutingFinding.HISTORY_REQUIRES_DESCRIPTOR_JOIN})
_LANDMARK = frozenset({GuiRoutingFinding.LANDMARK_ROLE_NOT_IN_DESCRIPTOR})
_SYSTEM = frozenset({GuiRoutingFinding.SYSTEM_DESCRIPTOR_ABSENT})


def _entry(
    sweep_registration_id: str,
    site_key: str,
    selector: DescriptorSelector | None = None,
    findings: frozenset[GuiRoutingFinding] = frozenset(),
) -> GuiRoutingInventoryEntry:
    return GuiRoutingInventoryEntry(sweep_registration_id, site_key, selector, findings)


_ENTRIES: Final = (
    _entry("C2-047", "gui.dashboard.dashboard-view.on-reading.temperature", _CRYOGENIC_TEMPERATURE),
    _entry("C2-048", "gui.dashboard.dashboard-view.on-reading.pressure", _VACUUM_PRESSURE),
    _entry("C2-049", "gui.dashboard.dashboard-view.on-reading.analytics", findings=_ANALYTICS),
    _entry(
        "C2-050",
        "gui.dashboard.dynamic-sensor-grid.rebuild.temperature",
        _CRYOGENIC_TEMPERATURE,
    ),
    _entry("C2-051", "gui.dashboard.phase-aware-widget.on-reading.cooldown-eta", findings=_ANALYTICS),
    _entry(
        "C2-052",
        "gui.dashboard.phase-aware-widget.on-reading.thermal-resistance",
        findings=_ANALYTICS,
    ),
    _entry("C2-053", "gui.dashboard.phase-aware-widget.on-reading.pressure", findings=_ANALYTICS),
    _entry("C2-054", "gui.dashboard.sensor-cell.update.temperature", _CRYOGENIC_TEMPERATURE),
    _entry("C2-055", "gui.dashboard.temp-plot.rebuild.temperature", _CRYOGENIC_TEMPERATURE),
    _entry(
        "C2-112",
        "gui.dashboard.dynamic-sensor-grid.dispatch.configured-cell",
        _CRYOGENIC_TEMPERATURE,
    ),
    _entry(
        "C2-121",
        "gui.shell.annunciation-controller.protocol-identifiers",
        findings=_ANNUNCIATION,
    ),
    _entry(
        "C2-123",
        "gui.shell.annunciation-controller.acknowledge.activation",
        findings=_ANNUNCIATION,
    ),
    _entry(
        "C2-124",
        "gui.shell.annunciation-controller.pending-alarm-holds.activation",
        findings=_ANNUNCIATION,
    ),
    _entry("C2-066", "gui.shell.experiment-overlay.on-reading.operator-log", findings=_ANALYTICS),
    _entry("C2-067", "gui.shell.main-window.dispatch.measurement-flow", _MEASUREMENT_STREAM),
    _entry("C2-068", "gui.shell.main-window.dispatch.disk-evidence", findings=_SYSTEM),
    _entry("C2-069", "gui.shell.main-window.dispatch.operator-log", findings=_ANALYTICS),
    _entry("C2-070", "gui.shell.main-window.dispatch.keithley-state", findings=_ANALYTICS),
    _entry("C2-071", "gui.shell.main-window.dispatch.analytics-family", findings=_ANALYTICS),
    _entry("C2-072", "gui.shell.main-window.dispatch.safety-state", findings=_ANALYTICS),
    _entry("C2-073", "gui.shell.main-window.dispatch-disk-evidence.instrument-identity", findings=_SYSTEM),
    _entry("C2-074", "gui.shell.main-window.analytics-adapter.cooldown", findings=_ANALYTICS),
    _entry(
        "C2-075",
        "gui.shell.main-window.analytics-adapter.thermal-resistance",
        findings=_ANALYTICS,
    ),
    _entry(
        "C2-076",
        "gui.shell.main-window.analytics-adapter.instrument-health",
        findings=_ANALYTICS,
    ),
    _entry(
        "C2-077",
        "gui.shell.main-window.analytics-adapter.vacuum-prediction",
        findings=_ANALYTICS,
    ),
    _entry("C2-078", "gui.shell.calibration-panel.on-reading.raw-sensor", _RAW_SENSOR),
    _entry("C2-128", "gui.shell.conductivity-panel.power-channel", _SOURCE_POWER),
    _entry(
        "C2-079",
        "gui.shell.conductivity-panel.temperature-channel-roster",
        _CRYOGENIC_TEMPERATURE,
    ),
    _entry(
        "C2-080",
        "gui.shell.conductivity-panel.resolve-configured-temperature",
        _CRYOGENIC_TEMPERATURE,
    ),
    _entry(
        "C2-081",
        "gui.shell.keithley-panel.command-description.target",
        findings=_COMMAND,
    ),
    _entry("C2-082", "gui.shell.keithley-panel.on-reading.state", findings=_ANALYTICS),
    _entry("C2-083", "gui.shell.keithley-panel.on-reading.source-channel", _SOURCE_READBACK),
    _entry("C2-084", "gui.shell.keithley-panel.on-reading.measurement", _SOURCE_READBACK),
    _entry("C2-085", "gui.shell.multiline-panel.manifest.instrument", _MULTILINE_ALL),
    _entry("C2-086", "gui.shell.multiline-panel.manifest.length-source", _MULTILINE_LENGTH),
    _entry(
        "C2-087",
        "gui.shell.multiline-panel.manifest.length-source-separator",
        _MULTILINE_LENGTH,
    ),
    _entry("C2-092", "gui.shell.multiline-panel.curve.length-index", _MULTILINE_LENGTH),
    _entry(
        "C2-094",
        "gui.shell.multiline-panel.descriptor-reading.length-source",
        _MULTILINE_LENGTH,
    ),
    _entry(
        "C2-095",
        "gui.shell.multiline-panel.descriptor-reading.length-separator",
        _MULTILINE_LENGTH,
    ),
    _entry("C2-129", "gui.shell.multiline-panel.manifest.length-channel", _MULTILINE_LENGTH),
    _entry(
        "C2-130",
        "gui.shell.multiline-panel.manifest.environment-channel",
        _MULTILINE_ENVIRONMENT,
    ),
    _entry("C2-132", "gui.shell.operator-log-panel.channel-roster", findings=_ANALYTICS),
    _entry("C2-133", "gui.shell.operator-log-panel.on-reading.channel", findings=_ANALYTICS),
    _entry("C2-134", "gui.shell.top-watch-bar.second-stage-channel", _T12, _LANDMARK),
    _entry("C2-135", "gui.shell.top-watch-bar.first-stage-channel", _T11, _LANDMARK),
    _entry("C2-098", "gui.shell.top-watch-bar.on-reading.temperature", _CRYOGENIC_TEMPERATURE),
    _entry("C2-136", "gui.shell.top-watch-bar.on-reading.landmark", _T11_T12, _LANDMARK),
    _entry("C2-099", "gui.shell.top-watch-bar.on-reading.pressure", _VACUUM_PRESSURE),
    _entry("C2-100", "gui.shell.top-watch-bar.refresh.temperature", _CRYOGENIC_TEMPERATURE),
    _entry("C2-138", "gui.shell.analytics.keithley-power.source-a", _SMUA_ANALYTICS),
    _entry("C2-139", "gui.shell.analytics.keithley-power.source-b", _SMUB_ANALYTICS),
    _entry("C2-140", "gui.shell.analytics.keithley-power.drop-unknown-source", _SOURCE_DISPLAY),
    _entry("C2-141", "gui.shell.analytics.keithley-power.measurement-dispatch", _SOURCE_DISPLAY),
    _entry(
        "C2-101",
        "gui.shell.analytics.experiment-summary.history.temperature-order.cyrillic-prefix",
        _ALL_TEMPERATURE,
        _HISTORY,
    ),
    _entry(
        "C2-102",
        "gui.shell.analytics.experiment-summary.history.temperature-order.latin-prefix",
        _ALL_TEMPERATURE,
        _HISTORY,
    ),
    _entry(
        "C2-142",
        "gui.shell.analytics.experiment-summary.history.other-measurements",
        _NON_TEMPERATURE,
        _HISTORY,
    ),
    _entry(
        "C2-143",
        "gui.shell.analytics.temperature-steady-state.landmark-selection",
        _T11_T12,
        _LANDMARK,
    ),
    _entry(
        "C2-144",
        "gui.shell.analytics.temperature-steady-state.landmark-key",
        _T11_T12,
        _LANDMARK,
    ),
)


def _build_inventory(
    entries: tuple[GuiRoutingInventoryEntry, ...],
) -> Mapping[str, GuiRoutingInventoryEntry]:
    by_key: dict[str, GuiRoutingInventoryEntry] = {}
    registration_ids: set[str] = set()
    for entry in entries:
        if entry.site_key in by_key:
            raise ValueError(f"duplicate GUI routing site key: {entry.site_key}")
        if entry.sweep_registration_id in registration_ids:
            raise ValueError(f"duplicate GUI sweep registration: {entry.sweep_registration_id}")
        by_key[entry.site_key] = entry
        registration_ids.add(entry.sweep_registration_id)
    return MappingProxyType(by_key)


GUI_ROUTING_INVENTORY: Final[Mapping[str, GuiRoutingInventoryEntry]] = _build_inventory(_ENTRIES)
