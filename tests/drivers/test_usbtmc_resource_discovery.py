"""Production-boundary guards for VISA USB resource discovery."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from cryodaq.drivers.transport import usbtmc

_CANONICAL = "USB0::0x05E6::0x2604::4083236::0::INSTR"
_DEVICE_RESOURCE = "USB0::0x05E6::0x2604::4083236\x00::0::INSTR"


class _Resource:
    pass


class _Manager:
    def __init__(self, resources: tuple[str, ...], *, expected_open: str | None) -> None:
        self.resources = resources
        self.expected_open = expected_open
        self.opened: list[str] = []
        self.closed = False
        self.resource = _Resource()

    def list_resources(self) -> tuple[str, ...]:
        return self.resources

    def open_resource(self, resource: str) -> _Resource:
        self.opened.append(resource)
        if resource != self.expected_open:
            raise OSError("resource is not openable")
        return self.resource

    def close(self) -> None:
        self.closed = True


def _install_manager(monkeypatch: pytest.MonkeyPatch, manager: _Manager) -> None:
    monkeypatch.setitem(
        sys.modules,
        "pyvisa",
        SimpleNamespace(ResourceManager=lambda: manager),
    )


def test_open_discovers_device_resource_with_one_trailing_serial_nul(monkeypatch) -> None:
    manager = _Manager((_DEVICE_RESOURCE,), expected_open=_DEVICE_RESOURCE)
    _install_manager(monkeypatch, manager)

    actual_manager, resource = usbtmc._blocking_open_handles(_CANONICAL)

    assert actual_manager is manager
    assert resource is manager.resource
    assert manager.opened == [_DEVICE_RESOURCE]
    assert manager.closed is False


@pytest.mark.parametrize("control", ["\n", "\r", "\t", "\x01", "\x7f"])
def test_discovery_rejects_other_controls_in_the_target_resource(monkeypatch, control: str) -> None:
    malformed = _CANONICAL.replace("4083236", f"4083236{control}")
    manager = _Manager((malformed,), expected_open=None)
    _install_manager(monkeypatch, manager)

    with pytest.raises(ValueError, match="control character"):
        usbtmc._blocking_open_handles(_CANONICAL)

    assert manager.opened == []
    assert manager.closed is True


def test_discovery_rejects_ambiguous_matching_resources(monkeypatch) -> None:
    manager = _Manager((_CANONICAL, _DEVICE_RESOURCE), expected_open=None)
    _install_manager(monkeypatch, manager)

    with pytest.raises(ValueError, match="ambiguous"):
        usbtmc._blocking_open_handles(_CANONICAL)

    assert manager.opened == []
    assert manager.closed is True


def test_configured_resource_cannot_embed_a_control_character(monkeypatch) -> None:
    manager = _Manager((_DEVICE_RESOURCE,), expected_open=None)
    _install_manager(monkeypatch, manager)

    with pytest.raises(ValueError, match="control character"):
        usbtmc._blocking_open_handles(_DEVICE_RESOURCE)

    assert manager.opened == []
    assert manager.closed is True
