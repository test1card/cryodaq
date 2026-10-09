"""Every periodic engine task must declare what it is allowed to do.

This is the enforcement the two sensor-diagnostics defects got past. Inlining a
250 ms analytics pass cost acquisition an entire observation window; the fix
then moved the whole call to a worker and carried alarm-state mutation off the
event loop with it. Review caught neither, because nothing in the tree recorded
which loops may offload and which may not.

These tests read ``engine_wiring/runtime_tasks.py`` as source and hold each
periodic owner to the class it declared in ``engine_wiring/periodic_owners.py``.
They are deliberately structural: they cannot prove a callback is fast, but they
can prove nobody added a new one in a shape already known to be wrong.
"""

import ast
from pathlib import Path

import pytest

from cryodaq.engine_wiring.periodic_owners import (
    LOOP_OWNED_CLASSES,
    PERIODIC_OWNERS,
    PERIODIC_OWNERS_BY_NAME,
    PeriodicOwnerClass,
)

RUNTIME_TASKS = Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "engine_wiring" / "runtime_tasks.py"

# Naming conventions the engine's periodic owners follow.
PERIODIC_SUFFIXES = ("_tick", "_loop", "_feed", "_feed_readings", "_scheduler", "_signals")

# Calls that move work off the event loop.
OFFLOAD_CALLS = {"to_thread", "run_in_executor"}


def _module() -> ast.Module:
    return ast.parse(RUNTIME_TASKS.read_text(encoding="utf-8"))


def _public_periodic_functions() -> dict[str, ast.AsyncFunctionDef]:
    found = {}
    for node in _module().body:
        if not isinstance(node, ast.AsyncFunctionDef) or node.name.startswith("_"):
            continue
        if node.name.endswith(PERIODIC_SUFFIXES):
            found[node.name] = node
    return found


def _offloads(node: ast.AsyncFunctionDef) -> set[str]:
    """Names of offload mechanisms used anywhere in this function."""
    used: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute):
            if func.attr in OFFLOAD_CALLS:
                used.add(func.attr)
            # `job.run(...)` is the admission-controlled offload.
            elif func.attr == "run" and isinstance(func.value, ast.Name) and func.value.id == "job":
                used.add("admission.job.run")
    return used


# ---------------------------------------------------------------------------
# Registration is mandatory
# ---------------------------------------------------------------------------


def test_every_periodic_task_is_registered():
    """A new loop cannot be added without stating what it may do."""
    defined = set(_public_periodic_functions())
    registered = set(PERIODIC_OWNERS_BY_NAME)
    unregistered = defined - registered
    assert not unregistered, (
        f"periodic tasks with no declared owner class: {sorted(unregistered)}. "
        "Add a PeriodicOwnerSpec in engine_wiring/periodic_owners.py."
    )


def test_the_registry_names_no_task_that_does_not_exist():
    defined = set(_public_periodic_functions())
    stale = set(PERIODIC_OWNERS_BY_NAME) - defined
    assert not stale, f"registry names tasks that no longer exist: {sorted(stale)}"


def test_every_spec_explains_itself():
    for spec in PERIODIC_OWNERS:
        assert spec.why.strip(), f"{spec.name} declares a class with no reason"


# ---------------------------------------------------------------------------
# Loop-owned work stays on the loop
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    sorted(spec.name for spec in PERIODIC_OWNERS if spec.owner_class in LOOP_OWNED_CLASSES),
)
def test_loop_owned_tasks_never_offload(name):
    """Safety and ingress own live state; a worker must not touch it.

    This is the exact defect just fixed in sensor diagnostics: the offloaded
    call carried AlarmStateManager mutation into a worker thread. A task that
    owns alarm, interlock or buffer state has to stay where that state lives.
    """
    node = _public_periodic_functions()[name]
    used = _offloads(node)
    assert not used, (
        f"{name} is {PERIODIC_OWNERS_BY_NAME[name].owner_class.value} but offloads via {sorted(used)}; "
        "it owns state that belongs to the event loop"
    )


# ---------------------------------------------------------------------------
# Best-effort analytics stays off the loop
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    sorted(
        spec.name for spec in PERIODIC_OWNERS if spec.owner_class is PeriodicOwnerClass.OFFLOADED_BEST_EFFORT
    ),
)
def test_best_effort_analytics_offloads_its_computation(name):
    """Being slow must cost analytics its own turn, never an observation window."""
    node = _public_periodic_functions()[name]
    used = _offloads(node)
    assert used, (
        f"{name} is declared OFFLOADED_BEST_EFFORT but computes inline; "
        "a slow pass here is taken directly out of acquisition"
    )


def test_sensor_diagnostics_offloads_only_the_pure_half():
    """compute() crosses to the worker; apply() must not.

    Sending ``update`` instead is what moved alarm transitions off-loop.
    """
    node = _public_periodic_functions()["sensor_diag_tick"]
    offloaded_args: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        is_offload = isinstance(func, ast.Attribute) and (
            func.attr in OFFLOAD_CALLS
            or (func.attr == "run" and isinstance(func.value, ast.Name) and func.value.id == "job")
        )
        if not is_offload:
            continue
        for arg in child.args:
            if isinstance(arg, ast.Attribute):
                offloaded_args.append(arg.attr)

    assert offloaded_args, "sensor_diag_tick offloads nothing"
    assert "update" not in offloaded_args, (
        "sensor_diag_tick offloads update(), which mutates alarm state in the worker"
    )
    assert "apply" not in offloaded_args, "apply() mutates alarm state and must run on the event loop"
    assert "compute" in offloaded_args, "the pure half is what belongs in the worker"
