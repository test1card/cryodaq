"""Integration checks for the external thermal mock instrument."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

import cryodaq.engine as engine_module
from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B
from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S
from cryodaq.drivers.registry import (
    DriverConstructionContext,
    DriverRegistryError,
    construct_driver,
    validate_instrument_entry,
)
from cryodaq.drivers.transport.mock_instrument import (
    ExternalMockInstrumentClient,
    MockInstrumentEndpoint,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def external_simulator(tmp_path: Path) -> Iterator[ExternalMockInstrumentClient]:
    ready_path = tmp_path / "ready.json"
    truth_path = tmp_path / "truth.json"
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools/thermal_conductivity_simulator.py"),
            "--ready-file",
            str(ready_path),
            "--truth-output",
            str(truth_path),
            "--time-constant-s",
            "0.02",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5.0
    while not ready_path.is_file() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if not ready_path.is_file():
        stdout, stderr = process.communicate(timeout=2.0)
        pytest.fail(f"external simulator did not become ready; stdout={stdout!r}; stderr={stderr!r}")

    ready = json.loads(ready_path.read_text(encoding="utf-8"))
    endpoint = MockInstrumentEndpoint(host=ready["host"], port=ready["port"])
    client = ExternalMockInstrumentClient(endpoint, timeout_s=1.0)
    yield client

    if process.poll() is None:
        with socket.create_connection((endpoint.host, endpoint.port), timeout=1.0) as connection:
            connection.sendall(b"MOCK:SHUTDOWN\n")
            assert connection.makefile("rb").readline() == b"OK\n"
    process.wait(timeout=5.0)
    stdout, stderr = process.communicate()
    assert process.returncode == 0, f"stdout={stdout!r}; stderr={stderr!r}"
    assert truth_path.is_file()
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    assert truth["model"] == "nonlinear_thermal_link_v1"


def _lakeshore_config():
    return validate_instrument_entry(
        {
            "type": "lakeshore_218s",
            "name": "LS",
            "resource": "GPIB0::12::INSTR",
            "channels": {1: "sample.hot", 2: "sample.cold"},
        }
    )


def _keithley_config():
    return validate_instrument_entry(
        {
            "type": "keithley_2604b",
            "name": "K",
            "resource": "USB0::0x05E6::0x2604::MOCK00001::INSTR",
        }
    )


async def _wait_for_equilibrium(
    lakeshore: LakeShore218S,
    *,
    expected_delta_t_k: float,
) -> dict[str, float]:
    deadline = time.monotonic() + 2.0
    latest: dict[str, float] = {}
    while time.monotonic() < deadline:
        latest = {reading.channel: reading.value for reading in await lakeshore.read_channels()}
        delta_t = latest["sample.hot"] - latest["sample.cold"]
        if delta_t == pytest.approx(expected_delta_t_k, rel=0.02, abs=1e-5):
            return latest
        await asyncio.sleep(0.01)
    pytest.fail(f"external simulator did not settle; latest={latest!r}")


async def test_external_process_drives_normal_lakeshore_parser_and_keithley_mock(
    external_simulator: ExternalMockInstrumentClient,
) -> None:
    context = DriverConstructionContext(mock=True, mock_instrument_client=external_simulator)
    lakeshore = construct_driver(_lakeshore_config(), context)
    keithley = construct_driver(_keithley_config(), context)
    assert isinstance(lakeshore, LakeShore218S)
    assert isinstance(keithley, Keithley2604B)

    await lakeshore.connect()
    await keithley.connect()
    baseline_readings = await lakeshore.read_channels()
    baseline = {reading.channel: reading.value for reading in baseline_readings}
    assert baseline["sample.hot"] == pytest.approx(4.2)
    assert baseline["sample.cold"] == pytest.approx(4.2)
    assert baseline_readings[0].raw == pytest.approx(4.2)

    await keithley.start_source("smua", 0.2, 10.0, 0.5)
    truth = json.loads(await external_simulator.query("MOCK:TRUTH?"))
    expected = truth["commanded_points"][-1]
    heated = await _wait_for_equilibrium(
        lakeshore,
        expected_delta_t_k=expected["equilibrium_delta_t_k"],
    )
    measured_delta_t = heated["sample.hot"] - heated["sample.cold"]
    measured_g = 0.2 / measured_delta_t
    assert measured_g == pytest.approx(expected["expected_g_w_per_k"], rel=0.02)

    await keithley.update_source_target("smua", 0.35)
    truth = json.loads(await external_simulator.query("MOCK:TRUTH?"))
    expected = truth["commanded_points"][-1]
    hotter = await _wait_for_equilibrium(
        lakeshore,
        expected_delta_t_k=expected["equilibrium_delta_t_k"],
    )
    assert hotter["sample.hot"] > heated["sample.hot"]

    await keithley.stop_source("smua")
    truth = json.loads(await external_simulator.query("MOCK:TRUTH?"))
    assert truth["commanded_points"][-1]["power_w"] == 0.0

    await keithley.disconnect()
    await lakeshore.disconnect()


def test_engine_cli_rejects_external_simulator_without_mock(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CRYODAQ_MOCK", raising=False)
    monkeypatch.setattr(
        engine_module,
        "_consume_engine_launch_authority",
        lambda: ("", "", "", None),
    )
    monkeypatch.setattr(
        engine_module.sys,
        "argv",
        ["cryodaq-engine", "--mock-thermal-simulator", "127.0.0.1:1234"],
    )
    with pytest.raises(SystemExit) as raised:
        engine_module.main()
    assert raised.value.code == 2
    assert "requires mock mode" in capsys.readouterr().err


def test_external_simulator_is_loopback_only_and_mock_only(
    external_simulator: ExternalMockInstrumentClient,
) -> None:
    assert MockInstrumentEndpoint.parse("localhost:1234") == MockInstrumentEndpoint("localhost", 1234)
    with pytest.raises(ValueError, match="localhost"):
        MockInstrumentEndpoint.parse("192.0.2.1:1234")
    with pytest.raises(DriverRegistryError, match="only in mock mode"):
        DriverConstructionContext(mock=False, mock_instrument_client=external_simulator)
