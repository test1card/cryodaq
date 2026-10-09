from __future__ import annotations

import asyncio
import inspect
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.qualification import verify_qualification_receipt
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    SourceOffResult,
    _issue_registry_runtime_binding,
)
from cryodaq.engine import _run_engine, _run_keithley_command
from tests.qualification_support import (
    VALID_AT,
    qualification_context,
    qualification_receipt_bytes,
)


def _driver(*, simulated: bool) -> MagicMock:
    driver = MagicMock()
    driver.mock = simulated
    driver.connected = True
    driver.output_state_unverified = False
    driver.watchdog_trip_pending = False
    driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    driver.stop_source = AsyncMock()
    driver.update_source_limit = AsyncMock()
    runtime = SimpleNamespace(active=False, p_target=0.0, v_comp=40.0, i_comp=1.0)
    driver._channels = {"smua": runtime, "smub": SimpleNamespace(**vars(runtime))}

    async def start_source(channel: str, p_target: float, v_comp: float, i_comp: float) -> None:
        selected = driver._channels[channel]
        selected.active = True
        selected.p_target = p_target
        selected.v_comp = v_comp
        selected.i_comp = i_comp

    async def update_source_target(channel: str, p_target: float) -> None:
        driver._channels[channel].p_target = p_target

    driver.start_source = AsyncMock(side_effect=start_source)
    driver.update_source_target = AsyncMock(side_effect=update_source_target)
    return driver


async def _manager(
    *,
    driver_simulated: bool,
    manager_mock: bool,
    qualification_receipt: object | None = None,
) -> tuple[SafetyManager, MagicMock]:
    driver = _driver(simulated=driver_simulated)
    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(1.0, 1.0, 1.0),
        registry_provenance="test:qualification-interlock",
        trust_class=DriverTrustClass.REVIEWED_SOURCE,
        simulation=manager_mock and driver_simulated,
    )
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        qualification_receipt=qualification_receipt,  # type: ignore[arg-type]
        mock=manager_mock,
    )
    manager._config.critical_channels = []
    await manager.start()
    if not manager_mock:
        generation = await manager.begin_reviewed_source_connect(driver, binding, "qualification test")
        assert await manager.complete_reviewed_source_connect(driver, binding, generation, "qualification test")
    return manager, driver


async def test_no_receipt_refuses_every_energizing_mutation_but_admits_safe_surface() -> None:
    manager, driver = await _manager(driver_simulated=False, manager_mock=False)
    try:
        run = await manager.request_run(0.1, 10.0, 0.1, channel="smua")
        manager._state = SafetyState.RUNNING
        manager._active_sources.add("smua")
        driver._channels["smua"].active = True
        target = await manager.update_target(0.2, channel="smua")
        limits = await manager.update_limits(channel="smua", v_comp=9.0, i_comp=0.09)

        assert run["ok"] is target["ok"] is limits["ok"] is False
        assert all("UNQUALIFIED" in result["error"] for result in (run, target, limits))
        driver.start_source.assert_not_awaited()
        driver.update_source_limit.assert_not_awaited()
        assert driver._channels["smua"].p_target == 0.0

        status = manager.get_status()
        events = manager.get_events()
        emergency = await manager.emergency_off(channel=None)
        stopped = await manager.request_stop(channel=None)
        assert status["qualification_mode"] == "UNQUALIFIED"
        assert isinstance(events, list)
        assert emergency["ok"] is True
        assert stopped["ok"] is True
    finally:
        await manager.stop()


async def test_valid_receipt_preserves_the_complete_energizing_path(
    tmp_path,
) -> None:
    receipt = verify_qualification_receipt(
        qualification_receipt_bytes(),
        expected=qualification_context(),
        replay_directory=tmp_path,
        now_unix_s=VALID_AT,
    )
    manager, driver = await _manager(
        driver_simulated=False,
        manager_mock=False,
        qualification_receipt=receipt,
    )
    try:
        run = await manager.request_run(0.1, 10.0, 0.1, channel="smua")
        target = await manager.update_target(0.2, channel="smua")
        limits = await manager.update_limits(channel="smua", v_comp=9.0, i_comp=0.09)

        assert run["ok"] is target["ok"] is limits["ok"] is True
        driver.start_source.assert_awaited_once()
        assert driver._channels["smua"].p_target == 0.2
        assert driver.update_source_limit.await_count == 2
        assert manager.get_status()["qualification_mode"] == "QUALIFIED"
    finally:
        await manager.stop()


async def test_explicit_simulation_works_but_mock_flag_cannot_authorize_a_real_driver() -> None:
    simulation, simulated_driver = await _manager(driver_simulated=True, manager_mock=True)
    disguised_real, real_driver = await _manager(driver_simulated=False, manager_mock=True)
    try:
        simulated = await simulation.request_run(0.1, 10.0, 0.1, channel="smua")
        refused = await disguised_real.request_run(0.1, 10.0, 0.1, channel="smua")
        assert simulated["ok"] is True
        assert refused["ok"] is False
        assert "UNQUALIFIED" in refused["error"]
        simulated_driver.start_source.assert_awaited_once()
        real_driver.start_source.assert_not_awaited()
    finally:
        await asyncio.gather(simulation.stop(), disguised_real.stop())


async def test_environment_cli_and_shared_gui_remote_dispatch_cannot_grant_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRYODAQ_QUALIFIED", "1")
    monkeypatch.setenv("CRYODAQ_QUALIFICATION_RECEIPT", "forged.json")
    manager, driver = await _manager(driver_simulated=False, manager_mock=False)
    try:
        gui_or_remote = await _run_keithley_command(
            "keithley_start",
            {"channel": "smua", "p_target": 0.1, "v_comp": 10.0, "i_comp": 0.1},
            manager,
        )
        assert gui_or_remote["ok"] is False
        assert "UNQUALIFIED" in gui_or_remote["error"]
        assert "qualification" not in inspect.signature(_run_engine).parameters
        driver.start_source.assert_not_awaited()
    finally:
        await manager.stop()


@pytest.mark.parametrize("qualified", (False, True), ids=("without-receipt", "with-receipt"))
async def test_off_and_stop_remain_admitted_under_saturation_quarantine_and_shutdown(
    tmp_path,
    qualified: bool,
) -> None:
    receipt = None
    if qualified:
        receipt = verify_qualification_receipt(
            qualification_receipt_bytes(),
            expected=qualification_context(),
            replay_directory=tmp_path,
            now_unix_s=VALID_AT,
        )
    manager, driver = await _manager(
        driver_simulated=False,
        manager_mock=False,
        qualification_receipt=receipt,
    )

    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")
    await manager._cmd_lock.acquire()
    off_task = asyncio.create_task(manager.emergency_off(channel=None))
    stop_task = asyncio.create_task(manager.request_stop(channel=None))
    await asyncio.sleep(0)
    assert not off_task.done() and not stop_task.done()
    manager._cmd_lock.release()
    off_result, stop_result = await asyncio.gather(off_task, stop_task)
    assert off_result["ok"] is True
    assert stop_result["ok"] is True

    manager._state = SafetyState.FAULT_LATCHED
    manager._active_sources.add("smua")
    before_quarantined_stop = driver.emergency_off.await_count
    quarantined_stop = await manager.request_stop(channel=None)
    assert driver.emergency_off.await_count > before_quarantined_stop
    quarantined_off = await manager.emergency_off(channel=None)
    # The stop action remains admitted and performs OFF, while its existing
    # public result truthfully preserves the fault-latched quarantine.
    assert quarantined_stop["ok"] is False
    assert quarantined_off["ok"] is True
    assert manager._active_sources == set()

    manager._active_sources.add("smua")
    before_shutdown = driver.emergency_off.await_count
    await manager.stop()
    assert driver.emergency_off.await_count > before_shutdown


@pytest.mark.parametrize(
    ("relative_path", "needle", "replacement", "guard_node"),
    (
        (
            "core/safety_manager.py",
            (
                "    def _energizing_mutation_refusal(self) -> str | None:\n"
                '        """Return why this authority cannot energize; never used by OFF paths."""\n'
                "\n"
            ),
            (
                "    def _energizing_mutation_refusal(self) -> str | None:\n"
                '        """Return why this authority cannot energize; never used by OFF paths."""\n'
                "\n"
                "        return None\n\n"
            ),
            "test_no_receipt_refuses_every_energizing_mutation_but_admits_safe_surface",
        ),
        (
            "core/qualification.py",
            (
                '    if not _signature_valid(canonical, receipt["signature"]):\n'
                '        raise QualificationReceiptError("qualification receipt signature is invalid")\n'
            ),
            ('    if False:\n        raise QualificationReceiptError("qualification receipt signature is invalid")\n'),
            "test_malformed_receipt_is_refused_without_consuming_authority",
        ),
        (
            "core/qualification.py",
            (
                "    if actual != expected:\n"
                '        raise QualificationReceiptError("qualification receipt does not match '
                'the exact runtime context")\n'
            ),
            (
                "    if False:\n"
                '        raise QualificationReceiptError("qualification receipt does not match '
                'the exact runtime context")\n'
            ),
            "test_signed_receipt_for_wrong_runtime_context_is_refused",
        ),
        (
            "core/qualification.py",
            (
                "    if now < issued or now >= expires:\n"
                '        raise QualificationReceiptError("qualification receipt is stale or not yet valid")\n'
            ),
            (
                "    if False:\n"
                '        raise QualificationReceiptError("qualification receipt is stale or not yet valid")\n'
            ),
            "test_stale_or_not_yet_valid_receipt_is_refused",
        ),
        (
            "core/qualification.py",
            "    _consume_once(replay_directory, receipt_id, payload_digest)\n",
            "    pass  # mutation: replay acceptance\n",
            "test_consumed_receipt_cannot_be_replayed",
        ),
        (
            "core/safety_manager.py",
            "        if receipt is None:\n",
            "        if receipt is not None:  # mutation: reject valid authority\n",
            "test_valid_receipt_preserves_the_complete_energizing_path",
        ),
        (
            "core/safety_manager.py",
            "    async def _request_stop_owned(\n",
            (
                "    async def _request_stop_owned(\n"
                "        self,\n"
                "        *,\n"
                "        channel: str | None = None,\n"
                "        expected_abort_generation: int,\n"
                "    ) -> dict[str, Any]:\n"
                '        return {"ok": False}  # mutation: block stop\n'
                "\n"
                "    async def _blocked_request_stop_owned(\n"
            ),
            "test_off_and_stop_remain_admitted_under_saturation_quarantine_and_shutdown",
        ),
        (
            "core/safety_manager.py",
            (
                "    async def _emergency_off_with_lock(self, channel: str | None) -> dict[str, Any]:\n"
                '        """Own lock acquisition and the full OFF bookkeeping as one task."""\n'
            ),
            (
                "    async def _emergency_off_with_lock(self, channel: str | None) -> dict[str, Any]:\n"
                '        """Own lock acquisition and the full OFF bookkeeping as one task."""\n'
                '        return {"ok": False}  # mutation: block emergency OFF\n'
            ),
            "test_off_and_stop_remain_admitted_under_saturation_quarantine_and_shutdown",
        ),
        (
            "core/safety_manager.py",
            "        return self._mock and (\n",
            "        return self._mock or (  # mutation: mock flag grants authority\n",
            "test_explicit_simulation_works_but_mock_flag_cannot_authorize_a_real_driver",
        ),
        (
            "core/safety_manager.py",
            (
                "    def _energizing_mutation_refusal(self) -> str | None:\n"
                '        """Return why this authority cannot energize; never used by OFF paths."""\n'
                "\n"
            ),
            (
                "    def _energizing_mutation_refusal(self) -> str | None:\n"
                '        """Return why this authority cannot energize; never used by OFF paths."""\n'
                "\n"
                "        return None\n\n"
            ),
            "test_environment_cli_and_shared_gui_remote_dispatch_cannot_grant_authority",
        ),
    ),
    ids=(
        "a-no-receipt",
        "b-signature",
        "c-d-context-binding",
        "e-stale",
        "e-replay",
        "f-valid-control",
        "g-stop",
        "g-emergency-off",
        "h-mock",
        "h-env-cli-gui-remote",
    ),
)
def test_runtime_guard_suite_kills_interlock_mutation(
    tmp_path: Path,
    relative_path: str,
    needle: str,
    replacement: str,
    guard_node: str,
) -> None:
    """Required-CI behavioral guards go RED when authority checks are weakened."""

    root = Path(__file__).resolve().parents[2]
    mutated_src = tmp_path / "src"
    shutil.copytree(root / "src" / "cryodaq", mutated_src / "cryodaq")
    mutation_path = mutated_src / "cryodaq" / relative_path
    source = mutation_path.read_text(encoding="utf-8")
    assert source.count(needle) == 1
    mutation_path.write_text(source.replace(needle, replacement), encoding="utf-8", newline="\n")

    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(mutated_src), str(root)))
    guard_file = (
        "test_qualification_receipt.py"
        if relative_path == "core/qualification.py"
        else "test_qualification_interlock.py"
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            f"tests/core/{guard_file}::{guard_node}",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "FAILED" in completed.stdout
