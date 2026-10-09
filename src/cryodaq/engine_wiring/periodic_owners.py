"""Declared ownership class for every periodic engine task.

The engine runs a dozen timer- and queue-driven loops. Whether a given one may
compute in a worker thread is not a style question -- it decides whether a slow
callback costs acquisition an observation window, and whether shared state is
mutated from the wrong thread. Both mistakes have already been made here:

* a 250 ms sensor-diagnostics pass ran inline and reduced a one-second
  acquisition window to a single read and a single write;
* the fix over-corrected and sent the whole of ``update()`` to a worker,
  carrying AlarmStateManager mutation off the event loop with it.

Neither was caught by review, because nothing recorded what each loop is
allowed to do. This registry records exactly that, and
``tests/engine_wiring/test_periodic_owner_registry.py`` enforces it against the
source, so a new loop cannot quietly be added in either wrong shape.

The four classes and their rules:

``LOOP_OWNED_SAFETY``
    Owns safety, interlock or alarm state. Runs entirely on the event loop and
    MUST NOT offload: moving it to a worker reproduces the cross-thread
    mutation bug. Its work must stay small enough to belong on the loop.

``LOOP_OWNED_INGRESS``
    Drains a queue into a buffer or tracker. Cheap per item, on the loop, and
    ordered with respect to acquisition. Must not offload; the appends it makes
    are what a worker's snapshot is taken from.

``OFFLOADED_BEST_EFFORT``
    Analytics. May be slow, owes nothing to safety, and MUST offload its
    computation through the analytics admission control so that being slow
    costs it its own turn rather than costing acquisition. Anything it computes
    is applied back on the event loop.

``HOUSEKEEPING``
    Infrequent maintenance -- rotation, retention. Blocking file work belongs in
    a thread; it holds no live state and no deadline.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PeriodicOwnerClass(Enum):
    LOOP_OWNED_SAFETY = "loop_owned_safety"
    LOOP_OWNED_INGRESS = "loop_owned_ingress"
    OFFLOADED_BEST_EFFORT = "offloaded_best_effort"
    HOUSEKEEPING = "housekeeping"


@dataclass(frozen=True, slots=True)
class PeriodicOwnerSpec:
    """One periodic task and the rule it is held to."""

    name: str
    owner_class: PeriodicOwnerClass
    why: str


#: Every periodic owner defined in ``engine_wiring.runtime_tasks``.
PERIODIC_OWNERS: tuple[PeriodicOwnerSpec, ...] = (
    PeriodicOwnerSpec(
        "alarm_v2_tick",
        PeriodicOwnerClass.LOOP_OWNED_SAFETY,
        "evaluates alarms and mutates AlarmStateManager; offloading it moves alarm transitions off-loop",
    ),
    PeriodicOwnerSpec(
        "cooldown_alarm_tick_loop",
        PeriodicOwnerClass.LOOP_OWNED_SAFETY,
        "arms and fires the cooldown alarm; owns alarm state",
    ),
    PeriodicOwnerSpec(
        "vacuum_guard_tick_loop",
        PeriodicOwnerClass.LOOP_OWNED_SAFETY,
        "interlock guard on pressure versus reference temperature; owns safety state",
    ),
    PeriodicOwnerSpec(
        "alarm_v2_feed_readings",
        PeriodicOwnerClass.LOOP_OWNED_INGRESS,
        "drains readings into the alarm state tracker; cheap per reading",
    ),
    PeriodicOwnerSpec(
        "alarm_ring_feed",
        PeriodicOwnerClass.LOOP_OWNED_INGRESS,
        "appends alarm events to the ring buffer the GUI reads",
    ),
    PeriodicOwnerSpec(
        "sensor_diag_feed",
        PeriodicOwnerClass.LOOP_OWNED_INGRESS,
        "appends samples the diagnostics worker later snapshots under the buffer lock",
    ),
    PeriodicOwnerSpec(
        "vacuum_trend_feed",
        PeriodicOwnerClass.LOOP_OWNED_INGRESS,
        "appends pressure samples for the trend worker",
    ),
    PeriodicOwnerSpec(
        "leak_rate_feed",
        PeriodicOwnerClass.LOOP_OWNED_INGRESS,
        "appends pressure samples to the leak-rate estimator; the finalize it triggers is not yet offloaded",
    ),
    PeriodicOwnerSpec(
        "track_runtime_signals",
        PeriodicOwnerClass.LOOP_OWNED_INGRESS,
        "feeds adaptive-throttle signals from the broker",
    ),
    PeriodicOwnerSpec(
        "assistant_event_relay_loop",
        PeriodicOwnerClass.LOOP_OWNED_INGRESS,
        "relays engine events to the assistant process over ZMQ; awaits I/O, computes nothing",
    ),
    PeriodicOwnerSpec(
        "sensor_diag_tick",
        PeriodicOwnerClass.OFFLOADED_BEST_EFFORT,
        "per-channel statistics and a pairwise correlation; compute() in a worker, apply() on the loop",
    ),
    PeriodicOwnerSpec(
        "vacuum_trend_tick",
        PeriodicOwnerClass.OFFLOADED_BEST_EFFORT,
        "curve_fit over the pressure history; a C extension that does not yield the loop",
    ),
    PeriodicOwnerSpec(
        "cold_rotation_scheduler",
        PeriodicOwnerClass.HOUSEKEEPING,
        "daily rotation of hot databases to Parquet; blocking file work, no deadline",
    ),
)

PERIODIC_OWNERS_BY_NAME: dict[str, PeriodicOwnerSpec] = {spec.name: spec for spec in PERIODIC_OWNERS}

#: Classes that must never move their work off the event loop.
LOOP_OWNED_CLASSES = frozenset(
    {PeriodicOwnerClass.LOOP_OWNED_SAFETY, PeriodicOwnerClass.LOOP_OWNED_INGRESS}
)
