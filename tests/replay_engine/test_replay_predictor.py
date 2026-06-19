"""F-ReplayPredictor: CooldownService activates inside ReplayEngine.

Covers:
1. CooldownService starts when ``cooldown.yaml`` + predictor model are present,
   with the replay-mode channel override rewriting cold/warm channel names.
2. ReplayEngine starts cleanly when the predictor model is missing — best-effort
   wiring must not abort engine startup.
3. End-to-end: a derived ``analytics/cooldown_predictor/cooldown_eta`` reading
   reaches a ZMQ SUB subscriber, proving the source → broker → CooldownService
   → broker → ZMQPublisher fan-out is intact.

Tests bind to OS-assigned free ports (not fixed ones) so a stale process or a
parallel run cannot collide and flake the suite.
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import numpy as np
import pytest
import zmq
import zmq.asyncio


def _free_tcp_addr() -> str:
    """Return a tcp://127.0.0.1:<port> on an OS-assigned free port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{s.getsockname()[1]}"
    finally:
        s.close()


_TEST_PUB = _free_tcp_addr()
_TEST_CMD = _free_tcp_addr()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_curve_json(path: Path) -> None:
    """Write a fast-cooling curve covering the canonical replay channels Т12/Т11.

    20-hour cooldown sampled at 120 points so CurveReplay has enough data for the
    predictor to converge on a buffer (≥20 entries) within the test deadline.
    """
    n = 120
    t = np.linspace(0.0, 20.0, n).tolist()
    T_cold = np.linspace(295.0, 4.5, n).tolist()
    T_warm = np.linspace(295.0, 80.0, n).tolist()
    path.write_text(
        json.dumps(
            {
                "t_hours": t,
                "T_cold": T_cold,
                "T_warm": T_warm,
                "name": "test_replay_predictor",
            }
        ),
        encoding="utf-8",
    )


def _write_cooldown_yaml(
    config_dir: Path,
    *,
    enabled: bool = True,
    channel_cold: str = "Т7 Детектор",
    channel_warm: str = "Т5 Экран 77К",
    model_dir: Path | None = None,
) -> None:
    """Write a minimal cooldown.yaml with aggressive predictor cadence for tests.

    Default channel names are intentionally the "wrong" real-lab values so the
    replay-mode override path is exercised by every test that uses this helper.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    # as_posix() so the path uses forward slashes: a Windows path like
    # D:\a\... inside a double-quoted YAML scalar has invalid escapes (\a, \c)
    # and fails to parse ("while scanning a double-quoted scalar"). Path()
    # accepts forward slashes on every OS.
    md = model_dir.as_posix() if model_dir is not None else "data/cooldown_model"
    (config_dir / "cooldown.yaml").write_text(
        "cooldown:\n"
        f"  enabled: {'true' if enabled else 'false'}\n"
        f'  channel_cold: "{channel_cold}"\n'
        f'  channel_warm: "{channel_warm}"\n'
        f'  model_dir: "{md}"\n'
        "  predict_interval_s: 0.05\n"
        "  rate_window_h: 0.01\n"
        "  auto_ingest: false\n"
        "  min_cooldown_hours: 0.001\n"
        "  detect:\n"
        "    start_rate_threshold: -5.0\n"
        "    start_confirm_minutes: 0.005\n"
        "    end_T_cold_threshold: 6.0\n"
        "    end_rate_threshold: 0.1\n"
        "    end_confirm_minutes: 0.01\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_synthetic_reference_curves(n_curves: int = 4) -> list:
    """Generate ReferenceCurve objects shaped like cryocooler cooldowns.

    Self-contained — no dependency on operator-bootstrapped artifacts. Curves
    follow a double-exponential T_cold trajectory crossing the 50 K phase
    boundary, with sample count high enough for the predictor's
    progress-variable resampler to converge. Absolute amplitudes are not
    physically accurate but are sufficient for prepare_all + build_ensemble
    to accept the curves and exercise the CooldownService prediction path.
    """
    from cryodaq.analytics.cooldown_predictor import ReferenceCurve

    rng = np.random.RandomState(7)
    curves: list = []
    for i in range(n_curves):
        duration = 19.0 + 0.4 * i
        dt_h = 10.0 / 3600.0
        t = np.arange(0.0, duration + dt_h, dt_h)
        T_cold_final = 4.5 + 0.2 * i
        T_warm_final = 85.0 + 1.5 * i

        tau1 = duration / 2.5
        tau2 = duration / 1.2
        T_start_c = 280.0 + rng.uniform(-3.0, 3.0)
        T_cold = (
            T_cold_final
            + (T_start_c - 50.0) * 0.6 * np.exp(-t / tau1)
            + (50.0 - T_cold_final) * 1.0 * np.exp(-t / tau2)
        )
        T_cold = np.maximum.accumulate(T_cold[::-1])[::-1]
        T_cold = np.clip(T_cold, T_cold_final, T_start_c + 5.0)

        T_start_w = T_start_c + rng.uniform(-2.0, 2.0)
        tau_w = duration / 3.0
        T_warm = T_warm_final + (T_start_w - T_warm_final) * np.exp(-t / tau_w)
        T_warm = np.clip(T_warm, T_warm_final * 0.95, T_start_w + 5.0)

        cross_idx = int(np.searchsorted(-T_cold, -50.0))
        phase1 = float(t[min(cross_idx, len(t) - 1)])

        curves.append(
            ReferenceCurve(
                name=f"synthetic_{i:02d}",
                date=f"2026-{1 + i:02d}-01",
                t_hours=t,
                T_cold=T_cold,
                T_warm=T_warm,
                duration_hours=float(t[-1]),
                phase1_hours=phase1,
                phase2_hours=float(t[-1]) - phase1,
                T_cold_final=float(np.min(T_cold)),
                T_warm_final=float(np.min(T_warm)),
            )
        )
    return curves


@pytest.fixture
def predictor_model_dir(tmp_path: Path) -> Path:
    """Build a deterministic predictor model from synthetic reference curves.

    No dependency on the operator-bootstrapped ``data/cooldown_model/``
    artifact; the model is built fresh from tracked code so the predictor
    paths get exercised on every test run, including clean checkouts.
    """
    from cryodaq.analytics.cooldown_predictor import (
        build_ensemble,
        prepare_all,
        save_model,
    )

    md = tmp_path / "cooldown_model"
    md.mkdir()
    rcs = _build_synthetic_reference_curves()
    curves = prepare_all(rcs)
    model = build_ensemble(curves)
    save_model(model, md)
    assert (md / "predictor_model.json").exists(), "Synthetic model save failed"
    return md


@pytest.fixture
def isolated_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the replay server's get_config_dir() to a tmp directory.

    The replay engine reads ``cooldown.yaml`` via this resolver; isolating it
    lets each test write a tailored config without touching repo state.
    """
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setattr(
        "cryodaq.replay_engine.server.get_config_dir",
        lambda: cfg,
    )
    return cfg


# ---------------------------------------------------------------------------
# Test 1 — CooldownService starts and channel override fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_engine_starts_cooldown_service_when_model_present(
    tmp_path: Path,
    isolated_config_dir: Path,
    predictor_model_dir: Path,
) -> None:
    """With a model and enabled cooldown.yaml, CooldownService is wired and
    the replay channel override rewrites cold/warm names to Т12/Т11."""
    from cryodaq.replay_engine.server import ReplayEngine

    _write_cooldown_yaml(
        isolated_config_dir,
        channel_cold="Т7 Детектор",
        channel_warm="Т5 Экран 77К",
        model_dir=predictor_model_dir,
    )
    curve = tmp_path / "curve.json"
    _write_curve_json(curve)

    engine = ReplayEngine(curve, speed=0.0, pub_addr=_TEST_PUB, cmd_addr=_TEST_CMD)
    await engine.start()
    try:
        assert engine._cooldown_service is not None, (
            "CooldownService should be wired when model + yaml are present"
        )
        assert engine._cooldown_service._channel_cold == "Т12", (
            "Replay channel override must rewrite channel_cold to Т12"
        )
        assert engine._cooldown_service._channel_warm == "Т11", (
            "Replay channel override must rewrite channel_warm to Т11"
        )
        assert engine._broker is not None
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# Test 2 — Engine starts cleanly when predictor model is absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_engine_starts_without_predictor_when_model_missing(
    tmp_path: Path,
    isolated_config_dir: Path,
) -> None:
    """Best-effort guard: without a predictor model file, the engine still
    completes start() and only the predictor stays disabled."""
    from cryodaq.replay_engine.server import ReplayEngine

    nonexistent = tmp_path / "no_such_model"
    _write_cooldown_yaml(isolated_config_dir, model_dir=nonexistent)
    curve = tmp_path / "curve.json"
    _write_curve_json(curve)

    engine = ReplayEngine(curve, speed=0.0, pub_addr=_TEST_PUB, cmd_addr=_TEST_CMD)
    await engine.start()
    try:
        assert engine._cooldown_service is None, "Predictor must not start without a model file"
        assert engine._broker is not None
        assert engine._pub is not None
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# Test 3 — End-to-end derived metric reaches a ZMQ SUB subscriber
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_engine_publishes_derived_metrics_through_pub(
    tmp_path: Path,
    isolated_config_dir: Path,
    predictor_model_dir: Path,
) -> None:
    """Source emits Т12/Т11 → broker → CooldownService → broker → ZMQPublisher.

    A ZMQ SUB subscriber must observe at least one
    ``analytics/cooldown_predictor/cooldown_eta`` reading carrying the
    plugin_id metadata, proving the predictor's output traverses the broker
    fan-out and reaches external consumers.
    """
    import msgpack

    from cryodaq.replay_engine.server import ReplayEngine

    _write_cooldown_yaml(isolated_config_dir, model_dir=predictor_model_dir)
    curve = tmp_path / "curve.json"
    _write_curve_json(curve)

    engine = ReplayEngine(curve, speed=0.0, pub_addr=_TEST_PUB, cmd_addr=_TEST_CMD)
    await engine.start()

    ctx = zmq.asyncio.Context()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.connect(_TEST_PUB)
    sub.subscribe(b"readings")
    await asyncio.sleep(0.1)  # slow-joiner mitigation (matches test_replay_engine.py)

    source_task = asyncio.create_task(engine.run_source(), name="test_source")

    derived_seen = False
    try:
        deadline = asyncio.get_event_loop().time() + 10.0
        while not derived_seen:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                parts = await asyncio.wait_for(sub.recv_multipart(), timeout=remaining)
            except TimeoutError:
                break
            if len(parts) != 2:
                continue
            data = msgpack.unpackb(parts[1], raw=False)
            channel = data.get("ch", "")
            if "cooldown_predictor/cooldown_eta" in channel:
                meta = data.get("meta", {}) or {}
                assert meta.get("plugin_id") == "cooldown_predictor", (
                    f"Derived metric missing plugin_id metadata: {meta}"
                )
                derived_seen = True
                break
    finally:
        sub.close(linger=0)
        ctx.term()
        source_task.cancel()
        try:
            await source_task
        except asyncio.CancelledError:
            pass
        await engine.stop()

    assert derived_seen, (
        "No analytics/cooldown_predictor/cooldown_eta reading reached PUB within 10s — "
        "broker fan-out or CooldownService wiring is broken"
    )
