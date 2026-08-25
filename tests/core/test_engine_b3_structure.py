"""Structural gates for the engine wiring decomposition."""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import cryodaq.engine as engine_mod


def _engine_tree() -> ast.Module:
    path = pathlib.Path(engine_mod.__file__)
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_run_engine_contains_no_nested_defs_or_lambdas() -> None:
    tree = _engine_tree()
    run_engine = next(
        node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_engine"
    )
    offenders = [
        node
        for node in ast.walk(run_engine)
        if node is not run_engine and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    rendered = [f"{type(node).__name__}:{getattr(node, 'name', '<lambda>')}:{node.lineno}" for node in offenders]
    assert rendered == [], f"_run_engine still owns nested callables: {rendered}"


def test_engine_wiring_submodules_import_without_engine_reverse_cycle() -> None:
    # The probe records, in order, the first import-machinery request for each
    # tracked name while the REAL production entry chain runs in a fresh
    # interpreter. The owned SQLite binding must be requested before pyarrow:
    # on Ubuntu 22.04 conda Python the reverse order loads system libstdc++
    # first and the fresh engine import dies with a missing CXXABI_1.3.15
    # symbol. This assertion fails on every platform if that order is
    # reversed again, not only where the ABI failure manifests.
    snippet = (
        "import sys\n"
        "_order = []\n"
        "class _OrderProbe:\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname in ('pyarrow', 'cryodaq.storage._sqlite') and fullname not in _order:\n"
        "            _order.append(fullname)\n"
        "        return None\n"
        "sys.meta_path.insert(0, _OrderProbe())\n"
        "import cryodaq.engine_wiring.runtime_tasks\n"
        "import cryodaq.engine_wiring.supervision\n"
        "assert 'cryodaq.engine' not in sys.modules\n"
        "missing = {'pyarrow', 'cryodaq.storage._sqlite'} - set(_order)\n"
        "assert not missing, f'production import never loaded: {sorted(missing)}'\n"
        "assert _order.index('cryodaq.storage._sqlite') < _order.index('pyarrow'), (\n"
        "    f'owned SQLite binding must load before pyarrow, saw {_order}'\n"
        ")\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_engine_production_entry_chain_loads_sqlite_before_pyarrow() -> None:
    # The submodule probe above binds only engine_wiring.runtime_tasks. The REAL
    # production engine entry is `import cryodaq.engine`, whose dependency list
    # reaches storage.cold_rotation through many earlier modules (core.broker,
    # analytics.*, drivers.*, notifications.*). A new TOP-LEVEL `import pyarrow`
    # — or lancedb, whose own import requests pyarrow — in any earlier engine
    # dependency would restore the Ubuntu 22.04 conda startup death (pyarrow
    # loads system libstdc++.so.6 first, then conda ICU dies on the missing
    # CXXABI_1.3.15 symbol) while the submodule probe stays green.
    #
    # This probe therefore starts a fresh interpreter and imports the real
    # production entry module, recording the first import-machinery request for
    # each tracked name along the actual chain. pyarrow must be requested at
    # all (cold_rotation imports it unconditionally at entry): if it ever goes
    # missing this guard fails loudly instead of passing vacuously. lancedb is
    # ordered when present but not required, since the engine chain does not
    # import it today. The assertion fails on every platform where the order
    # is wrong, not only where the ABI failure manifests.
    snippet = (
        "import sys\n"
        "_order = []\n"
        "class _OrderProbe:\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname in ('pyarrow', 'lancedb', 'cryodaq.storage._sqlite') and fullname not in _order:\n"
        "            _order.append(fullname)\n"
        "        return None\n"
        "sys.meta_path.insert(0, _OrderProbe())\n"
        "import cryodaq.engine\n"
        "missing = {'pyarrow', 'cryodaq.storage._sqlite'} - set(_order)\n"
        "assert not missing, f'production entry import never loaded: {sorted(missing)}'\n"
        "_sqlite_at = _order.index('cryodaq.storage._sqlite')\n"
        "_premature = [n for n in ('pyarrow', 'lancedb') if n in _order and _order.index(n) < _sqlite_at]\n"
        "assert not _premature, f'owned SQLite binding must load before {_premature}, saw {_order}'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_runtime_helpers_remain_compatibly_importable_from_engine() -> None:
    expected = {
        "_AlarmRingBuffer",
        "_alarm_ring_buffer_loop",
        "_alarm_v2_feed_loop",
        "_format_diag_telegram_messages",
    }
    assert expected <= set(vars(engine_mod))


def test_run_engine_wires_every_extracted_runtime_task() -> None:
    tree = _engine_tree()
    run_engine = next(
        node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_engine"
    )
    loaded_names = {
        node.id for node in ast.walk(run_engine) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    expected = {
        "alarm_ring_feed",
        "alarm_v2_feed_readings",
        "alarm_v2_tick",
        "assistant_event_relay_loop",
        "cold_rotation_scheduler",
        "cooldown_alarm_tick_loop",
        "leak_rate_feed",
        "sensor_diag_feed",
        "sensor_diag_tick",
        "track_runtime_signals",
        "vacuum_guard_tick_loop",
        "vacuum_trend_feed",
        "vacuum_trend_tick",
    }
    assert expected <= loaded_names
