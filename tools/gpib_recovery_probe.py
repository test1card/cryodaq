#!/usr/bin/env python3
"""Controlled hardware probe: does device-local recovery isolate one instrument?

Proves on the real GPIB0 bus that a desynchronized session is released by SDC
alone, and that its two healthy peers keep answering throughout.

Requires the engine to be STOPPED: it owns the bus, and a second session on a
live bus is exactly the fault this code exists to recover from.

Target is LS218_3 (GPIB0::13) on purpose -- it produces zero usable readings on
this stand (all overrange/sensor_error), so a deliberate fault there costs no
measurement. Its peers GPIB0::12 and GPIB0::11 carry the real temperatures.

Never sends IFC: that is interface-wide and would disturb the peers this probe
exists to protect. Any IFC attempt is recorded and fails the probe.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryodaq.drivers.transport.gpib import GPIBTransport  # noqa: E402

TARGET = "GPIB0::13::INSTR"
PEERS = ("GPIB0::12::INSTR", "GPIB0::11::INSTR")
TIMEOUT_MS = 3000
DESYNC_TIMEOUT_MS = 1  # far below any real response: forces a mid-transaction timeout

results: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


async def read_temps(transport: GPIBTransport, name: str) -> str | None:
    try:
        return (await transport.query("KRDG?", timeout_ms=TIMEOUT_MS)).strip()
    except Exception as exc:  # noqa: BLE001 - the probe reports, never raises
        print(f"       {name}: query failed: {type(exc).__name__}: {exc}")
        return None


async def main() -> int:
    ifc_attempts: list[str] = []
    target = GPIBTransport(mock=False)
    peers = {address: GPIBTransport(mock=False) for address in PEERS}

    # Any interface-wide operation fails the probe.
    for transport in (target, *peers.values()):
        transport._blocking_ifc = lambda: ifc_attempts.append("blocking_ifc") or False  # type: ignore[method-assign]

    print(f"\nopening {TARGET} and peers {', '.join(PEERS)}")
    await target.open(TARGET, timeout_ms=TIMEOUT_MS)
    for address, transport in peers.items():
        await transport.open(address, timeout_ms=TIMEOUT_MS)

    try:
        # 1. baseline
        base_target = await read_temps(target, "target")
        base_peers = {a: await read_temps(t, a) for a, t in peers.items()}
        check("baseline: target answers", base_target is not None, str(base_target)[:48])
        check("baseline: both peers answer", all(v is not None for v in base_peers.values()))

        # 2. force a genuine mid-transaction timeout on the target only
        print(f"\nforcing a desynchronized query on {TARGET} (timeout {DESYNC_TIMEOUT_MS} ms)")
        try:
            await target.query("KRDG?", timeout_ms=DESYNC_TIMEOUT_MS)
            check("target query timed out", False, "the 1 ms query unexpectedly succeeded")
        except Exception as exc:  # noqa: BLE001
            check("target query timed out", True, type(exc).__name__)

        check("target session is quarantined", target.query_desynchronized is True)

        # 3. peers must be unaffected while the target is broken
        during = {a: await read_temps(t, a) for a, t in peers.items()}
        check(
            "peers still answer while the target is quarantined",
            all(v is not None for v in during.values()),
        )
        check(
            "peers are NOT quarantined",
            all(not t.query_desynchronized for t in peers.values()),
        )

        # 4. a quarantined session refuses work rather than guessing
        try:
            await target.query("KRDG?", timeout_ms=TIMEOUT_MS)
            check("quarantined target refuses queries", False, "a query was served")
        except RuntimeError as exc:
            check("quarantined target refuses queries", "quarantined" in str(exc), str(exc)[:56])

        # 5. device-local recovery
        print(f"\nrecovering {TARGET} by device clear")
        recovered = True
        try:
            await target.recover_device()
        except Exception as exc:  # noqa: BLE001
            recovered = False
            check("recover_device() succeeded", False, f"{type(exc).__name__}: {exc}")
        if recovered:
            check("recover_device() succeeded", True)
            check("quarantine released", target.query_desynchronized is False)

        # 6. identity revalidated, then real readings resume
        if recovered:
            try:
                idn = (await target.query("*IDN?", timeout_ms=TIMEOUT_MS)).strip()
                check("target identity revalidated", "LSCI" in idn.upper(), idn[:52])
            except Exception as exc:  # noqa: BLE001
                check("target identity revalidated", False, f"{type(exc).__name__}: {exc}")
            after = await read_temps(target, "target")
            check("target produces readings again", after is not None, str(after)[:48])

        # 7. peers unharmed by the whole sequence
        final = {a: await read_temps(t, a) for a, t in peers.items()}
        check("peers answer after recovery", all(v is not None for v in final.values()))
        check("no IFC was ever issued", not ifc_attempts, str(ifc_attempts))

    finally:
        for transport in (target, *peers.values()):
            try:
                await transport.close()
            except Exception as exc:  # noqa: BLE001
                print(f"       close failed: {type(exc).__name__}: {exc}")

    failed = [label for label, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
