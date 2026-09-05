"""The vacuum fit must stay cheap, and must never run on the event loop.

On 2026-09-01 02:39 this update ran inline on the asyncio loop and blocked it
for ~8 s. In that window a bus-scoped instrument read passed its deadline, the
GPIB session for one LakeShore was quarantined and never recovered, its driver
then re-opened and cleared the shared bus every ~4 s for six hours, and the
second LakeShore died too. The run lost its temperature data overnight.
"""

import ast
import time
from pathlib import Path

from cryodaq.analytics.vacuum_trend import _MAX_FIT_POINTS, VacuumTrendPredictor, _thin_for_fitting

# Generous: the point is to catch a return to tens of seconds, not to police
# normal variation on a loaded machine.
_BUDGET_S = 8.0


def _six_hours_of_samples() -> VacuumTrendPredictor:
    predictor = VacuumTrendPredictor(
        config={"window_s": 21600, "update_interval_s": 0, "min_points": 60}
    )
    predictor.push(0.0, 1000.0)
    # 6 h at 2 s, the real cadence of the pressure channel.
    for index in range(1, 10800):
        t = index * 2.0
        predictor.push(t, 0.05 + 40.0 * (t + 600.0) ** -1.0)
    return predictor


def test_a_full_window_fit_stays_within_budget():
    predictor = _six_hours_of_samples()
    started = time.monotonic()
    predictor.update()
    assert time.monotonic() - started < _BUDGET_S


def test_fit_input_is_thinned_regardless_of_sample_rate():
    predictor = _six_hours_of_samples()
    assert len(predictor._buffer) > _MAX_FIT_POINTS
    thinned = _thin_for_fitting(list(predictor._buffer), _MAX_FIT_POINTS)
    assert len(thinned) == _MAX_FIT_POINTS


def test_thinning_keeps_the_ends():
    points = [(float(i), float(i)) for i in range(5000)]
    thinned = _thin_for_fitting(points, 100)
    assert thinned[0] == points[0]
    assert thinned[-1] == points[-1]


def test_thinning_is_a_no_op_below_the_limit():
    points = [(float(i), float(i)) for i in range(10)]
    assert _thin_for_fitting(points, 100) == points


def test_the_tick_never_runs_the_fit_on_the_event_loop():
    """Asserted on the source: a blocking call here stops the whole engine.

    Checked structurally rather than by timing, because the failure is not
    slowness — it is that acquisition, persistence and every timer stop while
    the fit runs.
    """
    source = Path("src/cryodaq/engine_wiring/runtime_tasks.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    tick = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "vacuum_trend_tick"
    )
    calls = [node for node in ast.walk(tick) if isinstance(node, ast.Call)]

    def is_update_call(node: ast.Call) -> bool:
        return isinstance(node.func, ast.Attribute) and node.func.attr == "update"

    # update() must not be invoked directly; it must be handed to a thread.
    assert not any(is_update_call(node) for node in calls), (
        "vacuum_trend.update() is called inline in the event loop"
    )
    offloaded = [
        node
        for node in calls
        if isinstance(node.func, ast.Attribute) and node.func.attr == "to_thread"
    ]
    assert offloaded, "the vacuum fit must be offloaded with asyncio.to_thread"
    assert any(
        isinstance(arg, ast.Attribute) and arg.attr == "update" for node in offloaded for arg in node.args
    )


def test_samples_survive_a_writer_running_during_a_fit():
    """push() is on the event loop, update() is now in a worker thread.

    That makes the sample buffer genuinely shared. Taking a list() of a deque
    while another thread appends raises "deque mutated during iteration", so
    the copy has to be guarded — and the guard must not be held across the fit
    itself, which is the entire point of moving it off the loop.
    """
    import threading
    import traceback

    predictor = _six_hours_of_samples()
    errors: list[str] = []
    stop = threading.Event()

    def writer() -> None:
        t = 30000.0
        while not stop.is_set():
            t += 2.0
            try:
                predictor.push(t, 0.05 + 40.0 * (t + 600.0) ** -1.0)
            except Exception:  # pragma: no cover - recorded, asserted below
                errors.append(traceback.format_exc())

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        for _ in range(3):
            predictor.update()
    except Exception:  # pragma: no cover - recorded, asserted below
        errors.append(traceback.format_exc())
    finally:
        stop.set()
        thread.join(timeout=5)

    assert errors == []
