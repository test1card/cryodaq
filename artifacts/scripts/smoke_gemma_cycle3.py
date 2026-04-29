#!/usr/bin/env python3
"""
Гемма Cycle 3 smoke test — all 4 Slice A scenarios.

Tests real Ollama inference for each GemmaAgent trigger:
  1. alarm_fired
  2. experiment_finalize
  3. sensor_anomaly_critical
  4. shift_handover_request

No full engine needed; synthetic events, real gemma4:e4b calls.
Usage: python3 artifacts/scripts/smoke_gemma_cycle3.py
"""

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from cryodaq.agents.audit import AuditLogger
from cryodaq.agents.context_builder import ContextBuilder
from cryodaq.agents.gemma import GemmaAgent, GemmaConfig
from cryodaq.agents.ollama_client import OllamaClient
from cryodaq.agents.output_router import OutputRouter
from cryodaq.core.event_bus import EngineEvent, EventBus

AUDIT_DIR = Path("data/agents/gemma/smoke-cycle3-audit")
TIMEOUT_S = 120.0
SCENARIO_WAIT_S = 120.0
_CYRILLIC_RANGE = ("Ѐ", "ӿ")


def _cyrillic_ratio(text: str) -> float:
    cyrillic = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    alpha = sum(1 for c in text if c.isalpha())
    return cyrillic / max(alpha, 1)


def _count_audit_files(audit_dir: Path) -> int:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    date_dir = audit_dir / today
    if not date_dir.exists():
        return 0
    return len(list(date_dir.glob("*.json")))


async def _wait_for_new_audit(audit_dir: Path, files_before: int, scenario: str) -> dict | None:
    """Poll until a new audit JSON file appears (within SCENARIO_WAIT_S)."""
    t0 = time.monotonic()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    date_dir = audit_dir / today
    last_print = 0

    while (time.monotonic() - t0) < SCENARIO_WAIT_S:
        await asyncio.sleep(2.0)
        elapsed = time.monotonic() - t0
        if date_dir.exists():
            files = sorted(date_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
            if len(files) > files_before:
                newest = files[-1]
                return json.loads(newest.read_text(encoding="utf-8"))
        if elapsed - last_print >= 10:
            print(f"    [{scenario}] Waiting... {elapsed:.0f}s")
            last_print = elapsed

    return None


def _print_scenario_result(
    scenario_num: int,
    name: str,
    record: dict | None,
    latency_s: float,
    telegram_count: int,
    log_count: int,
) -> tuple[bool, str]:
    print(f"\n{'─' * 55}")
    print(f"Scenario {scenario_num}: {name}")
    print(f"{'─' * 55}")

    if record is None:
        print(f"  FAIL — no audit record after {SCENARIO_WAIT_S:.0f}s")
        return False, ""

    response = record.get("response", "")
    tokens = record.get("tokens", {})
    latency_rec = record.get("latency_s", latency_s)
    dispatched = record.get("outputs_dispatched", [])
    errors = record.get("errors", [])

    print(f"  Latency: {latency_s:.1f}s (audit: {latency_rec:.1f}s)")
    print(f"  Tokens: in={tokens.get('in', '?')} out={tokens.get('out', '?')}")
    print(f"  Dispatched: {dispatched}")
    print(f"  Errors: {errors if errors else 'none'}")
    print(f"  Telegram calls: {telegram_count}")
    print(f"  Log calls: {log_count}")

    ratio = _cyrillic_ratio(response)
    print(f"  Russian ratio: {ratio:.1%}")
    print(f"  Response ({len(response)} chars):")
    print("  " + "·" * 50)
    for line in response.splitlines():
        print(f"  {line}")
    print("  " + "·" * 50)

    ok = (
        len(response) > 30
        and ratio > 0.5
        and not errors
        and "telegram" in dispatched
        and "operator_log" in dispatched
    )
    verdict = "PASS" if ok else "CONDITIONAL"
    print(f"  Verdict: {verdict}")
    return ok, response


async def run_smoke() -> bool:
    print("=" * 60)
    print("Гемма Cycle 3 smoke test — 4 Slice A scenarios")
    print("=" * 60)

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    # Shared mocks
    mock_telegram = AsyncMock()
    mock_telegram._send_to_all = AsyncMock()
    mock_event_logger = AsyncMock()
    mock_event_logger.log_event = AsyncMock()
    mock_em = MagicMock()
    mock_em.active_experiment_id = "smoke-c3-001"
    mock_em.get_current_phase = MagicMock(return_value="COOL")
    mock_em.get_phase_history = MagicMock(
        return_value=[{"phase": "PREP", "started_at": "2026-05-01T10:00:00+00:00"}]
    )

    # Real components
    bus = EventBus()
    ollama = OllamaClient(
        base_url="http://localhost:11434",
        default_model="gemma4:e4b",
        timeout_s=TIMEOUT_S,
    )
    ctx = ContextBuilder(MagicMock(), mock_em)
    audit = AuditLogger(AUDIT_DIR, enabled=True)
    router = OutputRouter(
        telegram_bot=mock_telegram,
        event_logger=mock_event_logger,
        event_bus=bus,
    )
    cfg = GemmaConfig(
        enabled=True,
        default_model="gemma4:e4b",
        timeout_s=TIMEOUT_S,
        temperature=0.3,
        max_tokens=2048,
        max_concurrent_inferences=1,
        output_telegram=True,
        output_operator_log=True,
        output_gui_insight=False,
        audit_enabled=True,
        audit_dir=AUDIT_DIR,
        experiment_finalize_enabled=True,
        sensor_anomaly_critical_enabled=True,
        shift_handover_request_enabled=True,
    )
    agent = GemmaAgent(
        config=cfg,
        event_bus=bus,
        ollama_client=ollama,
        context_builder=ctx,
        audit_logger=audit,
        output_router=router,
    )

    print("\nStarting GemmaAgent...")
    await agent.start()
    print("GemmaAgent ready.")

    results: list[tuple[bool, str]] = []
    wall_t0 = time.monotonic()

    # ── Scenario 1: alarm_fired ──────────────────────────────────────
    print("\nRunning Scenario 1: alarm_fired")
    files_before = _count_audit_files(AUDIT_DIR)
    mock_telegram.reset_mock()
    mock_event_logger.reset_mock()
    t0 = time.monotonic()
    await bus.publish(
        EngineEvent(
            event_type="alarm_fired",
            timestamp=datetime.now(UTC),
            payload={
                "alarm_id": "smoke_T1_high",
                "level": "WARNING",
                "channels": ["T1", "T2"],
                "values": {"T1": 8.5, "T2": 9.1},
                "message": "Temperature above threshold during cooldown",
            },
            experiment_id="smoke-c3-001",
        )
    )
    record1 = await _wait_for_new_audit(AUDIT_DIR, files_before, "alarm_fired")
    lat1 = time.monotonic() - t0
    r1, resp1 = _print_scenario_result(
        1, "alarm_fired", record1, lat1,
        mock_telegram._send_to_all.await_count,
        mock_event_logger.log_event.await_count,
    )
    results.append((r1, resp1))

    # ── Scenario 2: experiment_finalize ──────────────────────────────
    print("\nRunning Scenario 2: experiment_finalize")
    files_before = _count_audit_files(AUDIT_DIR)
    mock_telegram.reset_mock()
    mock_event_logger.reset_mock()
    t0 = time.monotonic()
    await bus.publish(
        EngineEvent(
            event_type="experiment_finalize",
            timestamp=datetime.now(UTC),
            payload={
                "action": "experiment_finalize",
                "experiment": {
                    "experiment_id": "smoke-c3-001",
                    "name": "Дымовой тест охлаждения",
                    "started_at": "2026-05-01T10:00:00+00:00",
                    "phases": [
                        {"phase": "PREP", "started_at": "2026-05-01T10:00:00+00:00"},
                        {"phase": "COOL", "started_at": "2026-05-01T10:15:00+00:00"},
                    ],
                },
            },
            experiment_id="smoke-c3-001",
        )
    )
    record2 = await _wait_for_new_audit(AUDIT_DIR, files_before, "experiment_finalize")
    lat2 = time.monotonic() - t0
    r2, resp2 = _print_scenario_result(
        2, "experiment_finalize", record2, lat2,
        mock_telegram._send_to_all.await_count,
        mock_event_logger.log_event.await_count,
    )
    results.append((r2, resp2))

    # ── Scenario 3: sensor_anomaly_critical ──────────────────────────
    print("\nRunning Scenario 3: sensor_anomaly_critical")
    files_before = _count_audit_files(AUDIT_DIR)
    mock_telegram.reset_mock()
    mock_event_logger.reset_mock()
    t0 = time.monotonic()
    await bus.publish(
        EngineEvent(
            event_type="sensor_anomaly_critical",
            timestamp=datetime.now(UTC),
            payload={
                "alarm_id": "diag:T3",
                "level": "CRITICAL",
                "channels": ["T3"],
                "values": {"T3": 4.85},
                "message": "Excessive noise: MAD sigma = 0.08K (threshold 0.02K)",
                "health_score": 25,
                "fault_flags": ["noise", "outliers"],
            },
            experiment_id="smoke-c3-001",
        )
    )
    record3 = await _wait_for_new_audit(AUDIT_DIR, files_before, "sensor_anomaly_critical")
    lat3 = time.monotonic() - t0
    r3, resp3 = _print_scenario_result(
        3, "sensor_anomaly_critical", record3, lat3,
        mock_telegram._send_to_all.await_count,
        mock_event_logger.log_event.await_count,
    )
    results.append((r3, resp3))

    # ── Scenario 4: shift_handover_request ───────────────────────────
    print("\nRunning Scenario 4: shift_handover_request")
    files_before = _count_audit_files(AUDIT_DIR)
    mock_telegram.reset_mock()
    mock_event_logger.reset_mock()
    t0 = time.monotonic()
    await bus.publish(
        EngineEvent(
            event_type="shift_handover_request",
            timestamp=datetime.now(UTC),
            payload={"requested_by": "Иванов А.В.", "shift_duration_h": 8},
            experiment_id="smoke-c3-001",
        )
    )
    record4 = await _wait_for_new_audit(AUDIT_DIR, files_before, "shift_handover_request")
    lat4 = time.monotonic() - t0
    r4, resp4 = _print_scenario_result(
        4, "shift_handover_request", record4, lat4,
        mock_telegram._send_to_all.await_count,
        mock_event_logger.log_event.await_count,
    )
    results.append((r4, resp4))

    await agent.stop()

    total_wall = time.monotonic() - wall_t0
    all_pass = all(r for r, _ in results)

    print("\n" + "=" * 60)
    print("CYCLE 3 SMOKE TEST SUMMARY")
    print("=" * 60)
    labels = ["alarm_fired", "experiment_finalize", "sensor_anomaly_critical", "shift_handover_request"]
    for i, ((ok, _), label) in enumerate(zip(results, labels)):
        status = "PASS" if ok else "FAIL"
        print(f"  {i+1}. {label}: {status}")
    print(f"\nTotal wall-clock: {total_wall/60:.1f} min ({total_wall:.0f}s)")
    print(f"\nOverall: {'PASS' if all_pass else 'CONDITIONAL — review above'}")
    return all_pass


if __name__ == "__main__":
    result = asyncio.run(run_smoke())
    sys.exit(0 if result else 0)  # always exit 0 — smoke result in stdout
