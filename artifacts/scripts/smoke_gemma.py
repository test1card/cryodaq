#!/usr/bin/env python3
"""
Гемма smoke test — real Ollama inference end-to-end.

Tests GemmaAgent alarm flow with real gemma4:e4b via Ollama.
No full engine needed; synthetic alarm event, real LLM call.

Usage: python3 artifacts/scripts/smoke_gemma.py
"""
import asyncio
import sys
import time
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from cryodaq.agents.gemma import GemmaAgent, GemmaConfig
from cryodaq.agents.ollama_client import OllamaClient
from cryodaq.agents.context_builder import ContextBuilder
from cryodaq.agents.audit import AuditLogger
from cryodaq.agents.output_router import OutputRouter
from cryodaq.core.event_bus import EngineEvent, EventBus
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock


async def run_smoke():
    print("=" * 60)
    print("Гемма smoke test — real Ollama inference")
    print("=" * 60)

    # Minimal mocks for non-Ollama paths
    mock_telegram = AsyncMock()
    mock_telegram._send_to_all = AsyncMock()
    mock_event_logger = AsyncMock()
    mock_event_logger.log_event = AsyncMock()
    mock_em = MagicMock()
    mock_em.active_experiment_id = "smoke-test-001"
    mock_em.get_current_phase = MagicMock(return_value="COOL")
    mock_em.get_phase_history = MagicMock(return_value=[])

    # Real components
    audit_dir = Path("data/agents/gemma/smoke-audit")
    audit_dir.mkdir(parents=True, exist_ok=True)

    bus = EventBus()
    ollama = OllamaClient(
        base_url="http://localhost:11434",
        default_model="gemma4:e4b",
        timeout_s=120.0,
    )
    ctx = ContextBuilder(MagicMock(), mock_em)
    audit = AuditLogger(audit_dir, enabled=True)
    router = OutputRouter(
        telegram_bot=mock_telegram,
        event_logger=mock_event_logger,
        event_bus=bus,
    )

    cfg = GemmaConfig(
        enabled=True,
        default_model="gemma4:e4b",
        timeout_s=120.0,
        temperature=0.3,
        max_tokens=300,
        max_concurrent_inferences=1,
        output_telegram=True,
        output_operator_log=True,
        output_gui_insight=False,
        audit_enabled=True,
    )

    agent = GemmaAgent(
        config=cfg,
        event_bus=bus,
        ollama_client=ollama,
        context_builder=ctx,
        audit_logger=audit,
        output_router=router,
    )

    print("\n[1] Checking Ollama availability...")
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("http://localhost:11434/api/tags", timeout=aiohttp.ClientTimeout(total=5)) as r:
                data = await r.json()
                models = [m["name"] for m in data.get("models", [])]
                print(f"    Ollama running. Models: {models}")
                if "gemma4:e4b" not in models:
                    print(f"    WARNING: gemma4:e4b not found! Available: {models}")
    except Exception as e:
        print(f"    FAIL: Ollama not reachable — {e}")
        return False

    print("\n[2] Starting GemmaAgent...")
    await agent.start()
    print("    GemmaAgent started, subscribed to EventBus")

    alarm_event = EngineEvent(
        event_type="alarm_fired",
        timestamp=datetime.now(UTC),
        payload={
            "alarm_id": "smoke_test_T1_high",
            "level": "WARNING",
            "channels": ["T1", "T2"],
            "values": {"T1": 8.5, "T2": 9.1},
            "message": "Temperature above threshold during cooldown",
        },
        experiment_id="smoke-test-001",
    )

    print("\n[3] Publishing synthetic alarm_fired event...")
    t0 = time.monotonic()
    await bus.publish(alarm_event)
    print(f"    Event published. Waiting for Гемма inference (model: gemma4:e4b)...")

    # Wait for inference to complete (up to 120s)
    deadline = 120.0
    poll_interval = 1.0
    audit_file = None
    while (time.monotonic() - t0) < deadline:
        await asyncio.sleep(poll_interval)
        # Check if audit file appeared
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        date_dir = audit_dir / today
        if date_dir.exists():
            files = list(date_dir.glob("*.json"))
            if files:
                audit_file = max(files, key=lambda f: f.stat().st_mtime)
                break
        elapsed = time.monotonic() - t0
        if int(elapsed) % 10 == 0:
            print(f"    Waiting... {elapsed:.0f}s elapsed")

    latency = time.monotonic() - t0

    if audit_file is None:
        print(f"\n    FAIL: No audit file found after {latency:.1f}s")
        await agent.stop()
        return False

    print(f"\n[4] Audit file found: {audit_file}")
    print(f"    Latency: {latency:.1f}s")
    record = json.loads(audit_file.read_text(encoding="utf-8"))

    response_text = record.get("response", "")
    print(f"\n[5] Гемма response ({len(response_text)} chars):")
    print("-" * 50)
    print(response_text)
    print("-" * 50)

    # Russian language check (look for Cyrillic characters)
    cyrillic_count = sum(1 for c in response_text if 'Ѐ' <= c <= 'ӿ')
    total_alpha = sum(1 for c in response_text if c.isalpha())
    russian_ratio = cyrillic_count / max(total_alpha, 1)

    print(f"\n[6] Language analysis:")
    print(f"    Cyrillic chars: {cyrillic_count}")
    print(f"    Total alpha: {total_alpha}")
    print(f"    Russian ratio: {russian_ratio:.1%}")
    print(f"    Tokens in/out: {record.get('tokens', {})}")
    print(f"    Audit latency_s: {record.get('latency_s', '?')}s")
    print(f"    Dispatched: {record.get('outputs_dispatched', [])}")

    # Verify Telegram mock was called
    telegram_called = mock_telegram._send_to_all.await_count > 0
    log_called = mock_event_logger.log_event.await_count > 0
    print(f"\n[7] Dispatch verification:")
    print(f"    Telegram._send_to_all called: {telegram_called}")
    print(f"    event_logger.log_event called: {log_called}")

    await agent.stop()

    # Results
    print("\n" + "=" * 60)
    english_drift = russian_ratio < 0.5 and total_alpha > 20
    latency_ok = latency < 30.0
    quality_ok = not english_drift and total_alpha > 20

    print("SMOKE TEST RESULTS:")
    print(f"  Latency: {latency:.1f}s {'✓' if latency_ok else '⚠ SLOW'}")
    print(f"  Russian ratio: {russian_ratio:.1%} {'✓' if not english_drift else '⚠ ENGLISH DRIFT'}")
    print(f"  Dispatch: Telegram={'✓' if telegram_called else '✗'} Log={'✓' if log_called else '✗'}")
    print(f"  Audit file: ✓ {audit_file.name}")

    if quality_ok and latency_ok and telegram_called and log_called:
        print("\n✓ SMOKE TEST PASSED")
        return True
    else:
        print("\n⚠ SMOKE TEST CONDITIONAL — review above")
        return False


if __name__ == "__main__":
    result = asyncio.run(run_smoke())
    sys.exit(0 if result else 1)
