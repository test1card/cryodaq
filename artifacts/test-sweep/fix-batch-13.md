# Batch 13 Fix Report

**Files touched (tests only, no src/ changes):**
- `tests/agents/assistant/test_ollama_client.py`
- `tests/agents/assistant/test_periodic_report_handler.py`
- `tests/agents/assistant/test_query_adapters.py`
- `tests/agents/assistant/test_query_agent.py`
- `tests/agents/assistant/test_query_agent_archive.py`

---

## Per-finding table

| # | Severity | File:line | Finding | Status | Action |
|---|----------|-----------|---------|--------|--------|
| 1 | HIGH | test_query_agent.py:359 `test_query_agent_total_timeout_enforcement` | `_format_timeout_s` stored at `agent.py:90` but `_handle_query_inner` calls `await self._ollama.generate(...)` with **no** `asyncio.wait_for` wrapper (`agent.py:142-148`). Timeout is stored but never enforced. | **DEFERRED-PRODUCTION-BUG** | Renamed test to `test_query_agent_empty_format_response_returns_fallback`; added DEFERRED comment citing `agent.py:90` (store) vs `agent.py:142-148` (un-wrapped await). Test itself covers the whitespace-fallback path (real behavior) — kept as-is. src/ not changed. |
| 2 | MED | test_ollama_client.py:246 `test_smoke_real_ollama` | Asserts non-empty/non-truncated only; any text passes. | **FIXED** | `assert result.text.strip() == "PASS"` with diagnostic message. |
| 3 | MED | test_periodic_report_handler.py:131,148,164,187,202,252 | `asyncio.sleep(0.05/0.1)` races for all async dispatch tests. | **FIXED** | Replaced with `_wait_until(lambda: mock.await_count >= 1)` (positive signal tests) and `_wait_until(lambda: len(agent._handler_tasks) == 0)` (negative/skip tests). Helper uses `asyncio.wait_for` + polling coroutine (1 s deadline, 5 ms interval). |
| 4 | MED | test_periodic_report_handler.py:227 `test_periodic_report_prompt_does_not_hardcode_hour_window` | Production hardcodes `prefix_suffix="(отчёт за час)"` (`live/agent.py:865`) regardless of `window_minutes`. A test asserting `"30 минут"` in the dispatch prefix would require a src/ fix. | **DEFERRED-PRODUCTION-BUG** | Test (prompt-constant check) left unchanged — it already passes. A new behavioral test for `window_minutes=30` asserting `"30 минут"` in the sent message would need `agent.py:865` to derive the suffix dynamically. Logged as production gap; not touching src/. |
| 5 | MED | test_query_adapters.py:152 `test_vacuum_adapter_target_format` | Never asserts `eta_seconds`. | **FIXED** | Added `assert result.eta_seconds == pytest.approx(3600.0)` (value from `pred.eta_targets["1.00e-06"]`). Reordered: eta_seconds, target_mbar, trend, confidence. |
| 6 | MED | test_query_adapters.py:355 `test_composite_adapter_parallel_fetch` | Doesn't assert each adapter was awaited. | **FIXED** | Unpacked all 6 return values; added `assert_awaited_once()` for `snap.latest_with_labels`, `cooldown.eta`, `vacuum.eta_to_target`, `alarms.active`, `experiment.status`; added `assert result.cooldown_eta is None` and `assert result.vacuum_eta is None`. |
| 7 | MED | test_query_agent.py:199 `test_query_agent_out_of_scope_historical_response` | Only asserted 2 adapters not awaited (composite, cooldown). | **FIXED** | Added `assert_not_awaited()` for all 6 adapters: composite, cooldown, vacuum, alarms, experiment, sqlite. |
| 8 | MED | test_query_agent_archive.py:131 `test_archive_detail_none_renders_not_found` | `or "—"` matches any ordinary placeholder; weak. | **FIXED** | Replaced with specific sentinel assertions: `"(нет данных)" in prompt` (phases_text), `"(не указано)" in prompt` (cooldown_text), `"не найден" in prompt` (from template instruction "Если эксперимент не найден — скажи прямо."). |
| 9 | LOW | test_query_adapters.py:63 (3 broker snapshot tests) | Fixed `asyncio.sleep` for consume-loop synchronization. | **FIXED** | `test_broker_snapshot_latest_per_channel`: polls `snap.latest("T_cold") is not None`. `test_broker_snapshot_handles_no_data`: single `await asyncio.sleep(0)` yield (no data to wait for). `test_broker_snapshot_latest_all_returns_all_channels`: polls until both channels in `latest_all()`. |

---

## Exact pytest line

```
pytest tests/agents/assistant/test_ollama_client.py \
       tests/agents/assistant/test_periodic_report_handler.py \
       tests/agents/assistant/test_query_adapters.py \
       tests/agents/assistant/test_query_agent.py \
       tests/agents/assistant/test_query_agent_archive.py \
       -q --no-header -m "not ollama"
```

**Result: 65 passed, 1 deselected in 0.20s**

## Ruff

```
ruff check tests/agents/assistant/test_ollama_client.py \
           tests/agents/assistant/test_periodic_report_handler.py \
           tests/agents/assistant/test_query_adapters.py \
           tests/agents/assistant/test_query_agent.py \
           tests/agents/assistant/test_query_agent_archive.py
```

**Result: All checks passed!**

---

## DEFERRED-PRODUCTION-BUG details

### 1. Format-step timeout not enforced (`agent.py:142-148`)

```python
# agent.py:90 — stored
self._format_timeout_s = format_timeout_s

# agent.py:142-148 — NOT wrapped with asyncio.wait_for
result = await self._ollama.generate(
    user_prompt,
    model=self._format_model,
    system=system_prompt,
    temperature=self._format_temperature,
    max_tokens=2048,
)
```

Fix requires wrapping with `asyncio.wait_for(..., timeout=self._format_timeout_s)` in src/.

### 2. Periodic report prefix hardcodes "час" (`live/agent.py:865`)

```python
# live/agent.py:865 — hardcoded regardless of window_minutes
prefix_suffix="(отчёт за час)",
```

Fix requires deriving suffix from `window_minutes` event payload in src/.
