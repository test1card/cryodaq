"""A quarantined LakeShore must come back with validated data, or not at all.

The production path is what failed on 2026-09-01: `connect()` reopened the
resource, asked `*IDN?`, got "GPIB session is quarantined", issued clear_bus()
-- which sends the SDC but never clears the flag -- and failed again. Six point
eight hours of Т9 and Т11-Т16 were written as timeout rows.

These tests drive `connect()` itself, not the transport, because that is the
path the scheduler retries.
"""

import asyncio

import pytest

from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S

VALID_IDN = "LSCI,MODEL218S,1234567,1.2"
STALE_TEMPERATURES = "+294.56,+294.43,+294.46,+380.00,+283.56,+294.53,+294.53,+00.000"


class _FakeTransport:
    """Records what the driver asks of a quarantined session."""

    def __init__(self, *, quarantined: bool, idn: str = VALID_IDN, recovery_raises: bool = False):
        self._quarantined = quarantined
        self._idn = idn
        self._recovery_raises = recovery_raises
        self.recover_device_calls = 0
        self.ifc_calls = 0
        self.requantined: list[str] = []
        self.closed = False
        self.queries: list[str] = []
        self.opened = False

    @property
    def query_desynchronized(self) -> bool:
        return self._quarantined

    def mark_desynchronized(self, reason: str) -> None:
        self._quarantined = True
        self.requantined.append(reason)

    async def recover_device(self) -> None:
        self.recover_device_calls += 1
        if self._recovery_raises:
            raise RuntimeError("GPIB device recovery refused: drain did not go quiet")
        self._quarantined = False

    async def recover(self) -> bool:  # the IFC path; must never be used here
        self.ifc_calls += 1
        return True

    async def send_ifc(self) -> bool:
        self.ifc_calls += 1
        return True

    async def open(self, resource_str, timeout_ms=None):
        self.opened = True

    async def close(self):
        self.closed = True

    async def clear_bus(self) -> bool:
        return True

    async def query(self, cmd, timeout_ms=None) -> str:
        self.queries.append(cmd)
        if self._quarantined:
            raise RuntimeError("GPIB session is quarantined after a failed query")
        if cmd == "*IDN?":
            return self._idn
        if cmd == "KRDG?":
            return "+4.210,+4.215,+4.220,+4.225,+4.230,+4.235,+4.240,+4.245"
        if cmd.startswith("RDGST?"):
            return "000"
        return ""

    async def write(self, cmd) -> None:
        pass


def _driver(transport: _FakeTransport) -> LakeShore218S:
    driver = LakeShore218S("LS218_2", "GPIB0::11::INSTR", mock=False)
    driver._transport = transport
    return driver


@pytest.mark.asyncio
async def test_a_quarantined_session_recovers_and_validates_identity():
    transport = _FakeTransport(quarantined=True)
    driver = _driver(transport)

    await driver.connect()

    assert transport.recover_device_calls == 1, "the quarantine was never addressed"
    assert transport.ifc_calls == 0, "recovery must not reach the interface-wide path"
    assert transport.queries[0] == "*IDN?", "identity must be validated before any data query"
    assert driver._connected is True


@pytest.mark.asyncio
async def test_usable_readings_resume_after_a_validated_recovery():
    """Not timeout rows, not sentinels: real values."""
    transport = _FakeTransport(quarantined=True)
    driver = _driver(transport)
    await driver.connect()

    readings = await driver.read_channels()

    assert readings, "recovery produced no readings"
    usable = [
        r
        for r in readings
        if getattr(r.status, "value", r.status) == "ok" and r.value is not None and abs(r.value) < 1e30
    ]
    assert usable, f"only unusable readings after recovery: {[(r.channel, r.status) for r in readings]}"
    assert all(0.0 < r.value < 400.0 for r in usable), f"sentinel-looking values: {[r.value for r in usable]}"
    assert len(usable) == len(readings), "some channels came back unusable after a validated recovery"


@pytest.mark.asyncio
async def test_a_stale_reply_offered_as_the_identity_is_rejected():
    """The late answer to the failed query must never validate the session."""
    transport = _FakeTransport(quarantined=True, idn=STALE_TEMPERATURES)
    driver = _driver(transport)

    with pytest.raises(RuntimeError, match="IDN validation failed"):
        await driver.connect()

    assert transport.requantined, "the session was not re-quarantined after an invalid identity"
    assert transport.closed is True
    assert driver._connected is False


@pytest.mark.asyncio
async def test_a_refused_recovery_fails_the_connect_rather_than_reporting_success():
    """A recovery that cannot be trusted must not look like a working session."""
    transport = _FakeTransport(quarantined=True, recovery_raises=True)
    driver = _driver(transport)

    with pytest.raises(RuntimeError, match="recovery refused"):
        await driver.connect()

    assert driver._connected is False
    assert "KRDG?" not in transport.queries, "a data query was issued on an unrecovered bus"


@pytest.mark.asyncio
async def test_a_healthy_session_is_not_disturbed():
    transport = _FakeTransport(quarantined=False)
    driver = _driver(transport)
    await driver.connect()
    assert transport.recover_device_calls == 0, "a healthy session was cleared for no reason"
    assert transport.ifc_calls == 0


def test_no_instrument_driver_reaches_the_interface_wide_recovery():
    """IFC is an interface operation and belongs to a fenced coordinator.

    Three LakeShore sessions share one physical GPIB0. A per-device recovery
    that pulsed IFC would reset healthy peers mid-transaction, turning one
    instrument's desynchronization into three. Enforced against the source so
    it cannot be reintroduced by a later "fix".
    """
    import ast
    from pathlib import Path

    drivers = Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "drivers" / "instruments"
    offenders: list[str] = []
    for path in drivers.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr in {"send_ifc", "_blocking_ifc"}:
                offenders.append(f"{path.name}:{node.lineno} calls {node.func.attr}()")
            # `recover()` is the IFC-bearing transport method; `recover_device()` is not.
            if node.func.attr == "recover":
                offenders.append(f"{path.name}:{node.lineno} calls the IFC-bearing recover()")
    assert not offenders, "instrument drivers must not perform interface-wide recovery: " + "; ".join(offenders)
