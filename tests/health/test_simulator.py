from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from cryodaq.health.contract import HealthFreshness, HealthTelemetryError
from cryodaq.health.simulator import DeterministicFleetHealthSimulator


def test_default_fleet_is_stable_100_devices_2000_metrics_at_two_hz() -> None:
    simulator = DeterministicFleetHealthSimulator(seed=36)
    frame = simulator.frame()

    assert simulator.device_count == frame.summary.device_count == 100
    assert simulator.metric_count == frame.summary.metric_count == 2_000
    assert simulator.cadence_hz == frame.cadence_hz == 2.0
    assert len({device.descriptor.device_id for device in frame.devices}) == 100
    assert frame.summary.fresh_count == 90
    assert frame.summary.stale_count == 10
    assert frame.summary.disconnected_count == 0
    assert frame.summary.faulted_count == frame.summary.active_alarm_count == 2


def test_seed_and_manual_clock_are_deterministic_without_retained_history() -> None:
    left = DeterministicFleetHealthSimulator(seed=73)
    right = DeterministicFleetHealthSimulator(seed=73)

    assert left.frame() == right.frame()
    assert left.frame() == right.frame()
    assert left.retained_frame_count == right.retained_frame_count == 0


def test_different_seed_changes_values_but_not_stable_shape() -> None:
    left = DeterministicFleetHealthSimulator(seed=1).frame()
    right = DeterministicFleetHealthSimulator(seed=2).frame()

    assert left.summary == right.summary
    assert left.devices[0].descriptor.device_id == right.devices[0].descriptor.device_id
    assert left.devices[0].metrics[0].value != right.devices[0].metrics[0].value


@pytest.mark.parametrize("cadence", [0.0, -1.0, 2.0001, float("inf"), float("nan")])
def test_simulator_rejects_non_human_readable_cadence(cadence: float) -> None:
    with pytest.raises(HealthTelemetryError, match="cadence_hz"):
        DeterministicFleetHealthSimulator(cadence_hz=cadence)


@pytest.mark.parametrize("start", [-1.0, float("inf"), float("nan")])
def test_simulator_rejects_invalid_manual_clock_origin(start: float) -> None:
    with pytest.raises(HealthTelemetryError, match="start_time_s"):
        DeterministicFleetHealthSimulator(start_time_s=start)


def test_frames_are_aggregation_ready_and_faults_are_not_diluted() -> None:
    frame = DeterministicFleetHealthSimulator().frame()
    faulted = [device for device in frame.devices if device.alarms]
    stale = [device for device in frame.devices if device.freshness is HealthFreshness.STALE]

    assert len(faulted) == frame.summary.faulted_count
    assert all(any(alarm.active for alarm in device.alarms) for device in faulted)
    assert len(stale) == frame.summary.stale_count
    assert frame.grants_control_authority is False


def test_simulator_has_no_task_queue_widget_or_action_surface() -> None:
    simulator = DeterministicFleetHealthSimulator()
    public = {name for name in dir(simulator) if not name.startswith("_")}

    assert public <= {
        "cadence_hz",
        "device_count",
        "frame",
        "grants_control_authority",
        "metric_count",
        "retained_frame_count",
    }
    assert not any(
        token in name for name in public for token in ("queue", "task", "widget", "start", "stop", "reset", "remediate")
    )


def test_each_instance_isolated_even_under_concurrent_consumption() -> None:
    simulators = [DeterministicFleetHealthSimulator(seed=91) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        frames = tuple(executor.map(lambda simulator: simulator.frame(), simulators))

    assert frames[0] == frames[1] == frames[2] == frames[3]
