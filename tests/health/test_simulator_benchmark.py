"""Pure fleet-scale proxy gate.

This test intentionally measures neither Qt frame work nor process RSS.  Those
remain lab-PC GUI evidence.  It bounds only deterministic contract materialization
time and a semantic payload-size proxy, so regression here cannot be mistaken for
the F36.4 design-system performance gate.
"""

from __future__ import annotations

import time

from cryodaq.health.simulator import DeterministicFleetHealthSimulator, estimate_fleet_frame_payload_bytes


def test_100_device_2000_metric_pure_frame_proxy_budget() -> None:
    simulator = DeterministicFleetHealthSimulator(seed=36)

    started = time.perf_counter()
    frames = tuple(simulator.frame() for _ in range(5))
    elapsed_s = time.perf_counter() - started

    assert elapsed_s < 5.0, f"pure simulator regression: five frames took {elapsed_s:.3f}s"
    assert max(estimate_fleet_frame_payload_bytes(frame) for frame in frames) < 2_000_000
    assert simulator.retained_frame_count == 0
