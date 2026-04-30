#!/usr/bin/env python3
"""F29 periodic report smoke: real Ollama + EventBus + audit/router path."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from cryodaq.agents.assistant.live.agent import AssistantConfig, AssistantLiveAgent
from cryodaq.agents.assistant.live.context_builder import ContextBuilder
from cryodaq.agents.assistant.live.output_router import OutputRouter
from cryodaq.agents.assistant.shared.audit import AuditLogger
from cryodaq.agents.assistant.shared.ollama_client import OllamaClient
from cryodaq.core.event_bus import EventBus
from cryodaq.engine import _periodic_report_tick


AUDIT_DIR = Path("data/agents/assistant/f29-smoke-audit")
TIMEOUT_S = 120.0


@dataclass
class SmokeEntry:
    timestamp: datetime
    message: str
    tags: tuple[str, ...]
    source: str = "auto"


def _cyrillic_ratio(text: str) -> float:
    cyrillic = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    alpha = sum(1 for c in text if c.isalpha())
    return cyrillic / max(alpha, 1)


def _count_audit_files() -> int:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    date_dir = AUDIT_DIR / today
    if not date_dir.exists():
        return 0
    return len(list(date_dir.glob("*.json")))


async def _wait_for_new_audit(files_before: int) -> dict | None:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    date_dir = AUDIT_DIR / today
    t0 = time.monotonic()
    while time.monotonic() - t0 < TIMEOUT_S:
        await asyncio.sleep(1.0)
        if not date_dir.exists():
            continue
        files = sorted(date_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
        if len(files) > files_before:
            return json.loads(files[-1].read_text(encoding="utf-8"))
    return None


async def _run_tick_once(cfg: AssistantConfig, bus: EventBus, em: MagicMock) -> None:
    """Run the engine timer long enough to publish one scheduled request."""
    sleep_count = 0

    async def fake_sleep(_delay_s: float) -> None:
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count > 1:
            raise asyncio.CancelledError
        await asyncio.sleep(0)

    task = asyncio.create_task(_periodic_report_tick(cfg, bus, em, sleep=fake_sleep))
    try:
        await asyncio.sleep(0.2)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def run_smoke() -> bool:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    entries = [
        SmokeEntry(now - timedelta(minutes=14), "Аларм Т1_высокая: T1=8.5 K", ("auto", "alarm")),
        SmokeEntry(now - timedelta(minutes=12), "Переход фазы: подготовка -> охлаждение", ("auto", "phase_transition")),
        SmokeEntry(now - timedelta(minutes=9), "Operator note: проверена стабильность термопары T1", (), "operator"),
        SmokeEntry(now - timedelta(minutes=5), "Калибровка: поправка T1 +0.02 K", ("auto", "calibration")),
    ]

    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=entries)

    em = MagicMock()
    em.active_experiment_id = "f29-дымовой-001"
    em.get_current_phase = MagicMock(return_value="охлаждение")

    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    event_logger = AsyncMock()
    event_logger.log_event = AsyncMock()

    bus = EventBus()
    gui_q = await bus.subscribe("smoke_gui")

    cfg = AssistantConfig(
        enabled=True,
        default_model="gemma4:e2b",
        timeout_s=TIMEOUT_S,
        max_tokens=2048,
        max_concurrent_inferences=1,
        max_calls_per_hour=10,
        output_telegram=True,
        output_operator_log=True,
        output_gui_insight=True,
        audit_enabled=True,
        audit_dir=AUDIT_DIR,
        periodic_report_enabled=True,
        periodic_report_interval_minutes=15,
        periodic_report_skip_if_idle=True,
        periodic_report_min_events=1,
    )
    ollama = OllamaClient(
        base_url="http://localhost:11434",
        default_model="gemma4:e2b",
        timeout_s=TIMEOUT_S,
    )
    agent = AssistantLiveAgent(
        config=cfg,
        event_bus=bus,
        ollama_client=ollama,
        context_builder=ContextBuilder(reader, em),
        audit_logger=AuditLogger(AUDIT_DIR, enabled=True),
        output_router=OutputRouter(
            telegram_bot=telegram,
            event_logger=event_logger,
            event_bus=bus,
            brand_name=cfg.brand_name,
            brand_emoji=cfg.brand_emoji,
        ),
    )

    await agent.start()
    files_before = _count_audit_files()
    t0 = time.monotonic()
    await _run_tick_once(cfg, bus, em)
    record = await _wait_for_new_audit(files_before)
    latency = time.monotonic() - t0

    if record is None:
        await agent.stop()
        print("FAIL: no audit record produced")
        return False

    response = record.get("response", "")
    sent = telegram._send_to_all.call_args[0][0] if telegram._send_to_all.await_count else ""
    gui_event = None
    while not gui_q.empty():
        candidate = gui_q.get_nowait()
        if candidate.event_type == "assistant_insight":
            gui_event = candidate

    ratio = _cyrillic_ratio(response)
    print("ACTIVE WINDOW")
    print(f"latency_wall_s={latency:.1f}")
    print(f"latency_audit_s={record.get('latency_s')}")
    print(f"tokens={record.get('tokens')}")
    print(f"russian_ratio={ratio:.1%}")
    print(f"dispatched={record.get('outputs_dispatched')}")
    print(f"telegram_prefix_ok={sent.startswith('🤖 Гемма (отчёт за час):')}")
    print(f"gui_trigger={gui_event.payload.get('trigger_event_type') if gui_event else None}")
    print("response:")
    print(response)

    reader.get_operator_log = AsyncMock(return_value=[])
    before_idle_telegram = telegram._send_to_all.await_count
    before_idle_log = event_logger.log_event.await_count
    before_idle_audits = _count_audit_files()
    await _run_tick_once(cfg, bus, em)
    await asyncio.sleep(2.0)
    idle_skipped = (
        telegram._send_to_all.await_count == before_idle_telegram
        and event_logger.log_event.await_count == before_idle_log
        and _count_audit_files() == before_idle_audits
    )
    print("\nIDLE WINDOW")
    print(f"idle_skipped={idle_skipped}")

    await agent.stop()

    quality_ok = len(response) > 50 and ratio >= 0.9
    grounded_ok = all(marker in response for marker in ("T1",)) and "охлажд" in response.lower()
    dispatch_ok = (
        sent.startswith("🤖 Гемма (отчёт за час):")
        and "telegram" in record.get("outputs_dispatched", [])
        and "operator_log" in record.get("outputs_dispatched", [])
        and "gui_insight" in record.get("outputs_dispatched", [])
        and gui_event is not None
    )
    return quality_ok and grounded_ok and dispatch_ok and idle_skipped


if __name__ == "__main__":
    ok = asyncio.run(run_smoke())
    sys.exit(0 if ok else 1)
