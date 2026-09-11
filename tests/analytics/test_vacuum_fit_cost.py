"""The vacuum fit must stay cheap, and must never run on the event loop.

On 2026-09-01 02:39 this update ran inline on the asyncio loop and blocked it
for ~8 s. In that window a bus-scoped instrument read passed its deadline, the
GPIB session for one LakeShore was quarantined and never recovered, its driver
then re-opened and cleared the shared bus every ~4 s for six hours, and the
second LakeShore died too. The run lost its temperature data overnight.
"""

import ast
import pathlib
import time
from pathlib import Path

import pytest

from cryodaq.analytics.vacuum_trend import _MAX_FIT_POINTS, VacuumTrendPredictor, _thin_for_fitting

# Generous: the point is to catch a return to tens of seconds, not to police
# normal variation on a loaded machine.
_BUDGET_S = 8.0


def _six_hours_of_samples() -> VacuumTrendPredictor:
    predictor = VacuumTrendPredictor(config={"window_s": 21600, "update_interval_s": 0, "min_points": 60})
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
        node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "vacuum_trend_tick"
    )
    calls = [node for node in ast.walk(tick) if isinstance(node, ast.Call)]

    def is_update_call(node: ast.Call) -> bool:
        return isinstance(node.func, ast.Attribute) and node.func.attr == "update"

    # update() must not be invoked directly; it must be handed to a thread.
    assert not any(is_update_call(node) for node in calls), "vacuum_trend.update() is called inline in the event loop"
    offloaded = [node for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == "to_thread"]
    assert offloaded, "the vacuum fit must be offloaded with asyncio.to_thread"
    assert any(isinstance(arg, ast.Attribute) and arg.attr == "update" for node in offloaded for arg in node.args)


#: How long the parent waits for the whole scenario. Three fits take about
#: 1.2 s with the writer yielding; thirty seconds is generous, and it is a real
#: bound because the parent kills the child rather than asking it to stop.
_CONCURRENT_FIT_TIMEOUT_S = 30.0


def run_concurrent_fit_scenario() -> None:
    """The scenario itself: a writer thread against three fits.

    Module level, because the test runs it in a CHILD PROCESS. A reviewer
    showed why that matters: an assertion after the three fits is only an
    observation, and with the yield removed it reports at 3 x 118.51 s, not in
    the half minute I claimed. Python cannot terminate a running fit from
    another thread, so the only bound that holds is a process the parent can
    kill.
    """
    import threading
    import time
    import traceback

    predictor = _six_hours_of_samples()
    errors: list[str] = []
    stop = threading.Event()
    pushes = 0

    def writer() -> None:
        nonlocal pushes
        t = 30000.0
        while not stop.is_set():
            t += 2.0
            try:
                predictor.push(t, 0.05 + 40.0 * (t + 600.0) ** -1.0)
                pushes += 1
            except Exception:  # pragma: no cover - recorded, asserted below
                errors.append(traceback.format_exc())
            # A YIELD, and the suite hung without it -- for a reason that is not
            # about locks. MEASURED 2026-09-11: one `update()` takes 0.40 s with
            # this sleep and 118.51 s without, and in the second case the writer
            # got through 212,866,205 pushes. The fit's residual function is
            # PYTHON (`_exponential_model`), called thousands of times from
            # inside scipy, so an unthrottled pure-Python writer starves it
            # through the GIL: a 296x slowdown, three fits, and a run that reads
            # as frozen. `maxfev` is set, the deque is bounded, nothing
            # deadlocks.
            #
            # It also models nothing: the engine pushes one reading per poll
            # interval, about one every two seconds. 232 pushes still land
            # inside a single fit, which is the concurrency this exercises.
            time.sleep(0.001)

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

    assert not thread.is_alive(), "the writer thread did not stop"
    assert errors == [], errors
    # The concurrency the scenario is about actually happened.
    assert pushes > 50, f"only {pushes} pushes landed during three fits"
    print("SCENARIO OK")


def test_samples_survive_a_writer_running_during_a_fit():
    """push() is on the event loop, update() is now in a worker thread.

    That makes the sample buffer genuinely shared. Taking a list() of a deque
    while another thread appends raises "deque mutated during iteration", so
    the copy has to be guarded -- and the guard must not be held across the fit
    itself, which is the entire point of moving it off the loop.

    IN A CHILD PROCESS, with the parent holding the clock. This test used to
    hang the whole suite and had to be killed from outside: `pytest --timeout`
    printed its banner and the process stayed alive, because the hang outlived
    the cancellation. An assertion on elapsed time does not fix that -- it runs
    after the fits return, which is exactly when a starved run is not returning.
    A process can be killed; a thread running scipy cannot.
    """
    import subprocess
    import sys
    import textwrap

    # THIS file, by its own path: the child re-imports the module it is running
    # from, so the scenario and the bound never drift apart.
    here = str(pathlib.Path(__file__).resolve())
    probe = textwrap.dedent(
        f"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("fit_scenario", {here!r})
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.run_concurrent_fit_scenario()
        """
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=_CONCURRENT_FIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise AssertionError(
            f"three fits did not finish in {_CONCURRENT_FIT_TIMEOUT_S}s — the writer is starving the fit again"
        ) from None

    assert done.returncode == 0, f"the scenario failed: {done.stdout[-600:]}{done.stderr[-600:]}"
    assert "SCENARIO OK" in done.stdout, done.stdout[-400:]


def test_the_parent_actually_enforces_its_bound(monkeypatch):
    """The boundary is only a boundary if the parent kills what overruns it.

    Removing the parent's timeout cannot be caught by the healthy case -- the
    scenario finishes in about a second either way, so the run stays green and
    the bound looks present while doing nothing. Shrinking the bound to a value
    the scenario cannot meet is what shows it is enforced.
    """
    monkeypatch.setattr("tests.analytics.test_vacuum_fit_cost._CONCURRENT_FIT_TIMEOUT_S", 0.01, raising=False)
    import tests.analytics.test_vacuum_fit_cost as module

    monkeypatch.setattr(module, "_CONCURRENT_FIT_TIMEOUT_S", 0.01)

    with pytest.raises(AssertionError, match="did not finish in"):
        module.test_samples_survive_a_writer_running_during_a_fit()
