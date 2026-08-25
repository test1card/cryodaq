"""Child-importable fake pyvisa backend for the fd-2 shutdown-blocker harness.

This stands in for the vendor VISA library ONLY. It never fakes
multiprocessing, ResourceTracker, descriptors, pipes, or the launcher pump:
the real ``multiprocessing`` spawn path, the real resource tracker, and the
real OS descriptor table are exercised by every consumer of this stub.
"""

from __future__ import annotations

_RESOURCE_ID = "FAKE0::FD2TEST::SIMULATED::INSTR"


class VisaIOError(Exception):
    """Shape-compatible error type for the fake backend."""


class _FakeResource:
    def __init__(self) -> None:
        self.timeout = 0

    def query(self, command: str) -> str:
        return f"FAKE:{command}"

    def write(self, command: str) -> None:
        del command

    def write_raw(self, data: bytes) -> None:
        del data

    def close(self) -> None:
        return None


class ResourceManager:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def open_resource(self, resource_str: str) -> _FakeResource:
        if resource_str != _RESOURCE_ID:
            raise VisaIOError(f"unknown fake resource: {resource_str!r}")
        return _FakeResource()

    def close(self) -> None:
        return None
