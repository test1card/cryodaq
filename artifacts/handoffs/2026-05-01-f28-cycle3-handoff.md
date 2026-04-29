# F28 Гемма — Cycle 3 Handoff

Date: 2026-05-01  
Branch: `feat/f28-hermes-agent` at `b99cd0a`  
Codex: PASS (1 amend — CRITICAL placeholder lifecycle fix in GemmaInsightPanel)

---

## What was implemented

### Three new Slice A triggers (all four Slice A triggers now wired)

| Trigger | Handler | EventBus source |
|---|---|---|
| `alarm_fired` | `_handle_alarm_fired` | `_alarm_v2_tick()` — Cycle 2 |
| `experiment_finalize/stop/abort` | `_handle_experiment_finalize` | engine.py experiment command hook — Cycle 2 |
| `sensor_anomaly_critical` | `_handle_sensor_anomaly` | `_sensor_diag_tick()` — **NEW Cycle 3** |
| `shift_handover_request` | `_handle_shift_handover` | `shift_handover_summary` ZMQ cmd — **NEW Cycle 3** |

### GUI insight panel

- `src/cryodaq/gui/shell/views/gemma_insight_panel.py` — 238 LOC
- Shows last 10 insights as DS-compliant cards
- `push_insight(text, trigger_event_type, timestamp)` public API
- Trigger type chips: АЛАРМ/ЭКСП/ПРЕРВАН/ДАТЧИК/СМЕНА with status colors
- Placeholder when empty, scroll to top on new insight

### New prompt templates

- `SENSOR_ANOMALY_SYSTEM/USER` — sensor health analysis, 60-100 words
- `SHIFT_HANDOVER_SYSTEM/USER` — shift summary, 120-200 words, structured

### New ZMQ command

- `shift_handover_summary` → publishes `shift_handover_request` to EventBus → returns `{"ok": true, "status": "queued"}` immediately (async, Гемма responds later)
- Payload: `{"requested_by": operator, "shift_duration_h": N}`

---

## Codex findings

| # | Finding | Severity | Action |
|---|---|---|---|
| 1 | `_rebuild_cards()` called `deleteLater()` on `self._placeholder` (persistent widget), then re-added same instance — `Internal C++ object already deleted` risk | **CRITICAL** | Fixed: skip `deleteLater()` for placeholder, toggle `.setVisible()` |
| 2 | `duration_str` variable name misleading (held `float` before `_format_age()` call) | LOW | Fixed: renamed to `age_float` |
| 3-6 | Handler isolation, sensor publish indentation, shift_handover placement, missing tests | INFO/OK | No action needed pre-test |

---

## Architecture decisions embedded in Cycle 3

1. **sensor_anomaly_critical gate**: only CRITICAL events (`_sd_ev.level.upper() == "CRITICAL"`) are published to EventBus. WARNING events go to Telegram only (existing behavior). Rationale: operator overload risk if every WARNING triggers a 48s Гемма inference.

2. **shift_handover_summary returns immediately**: ZMQ caller gets `{"ok": true, "status": "queued"}` — Гемма generates the summary asynchronously. GUI should show "Гемма готовит сводку..." while waiting.

3. **GemmaInsightPanel push-only for Cycle 3**: no ZMQ polling wired. Shell (MainWindowV2) wires `push_insight()` when receiving gemma_insight EventBus events via ZMQ PUB subscription — Cycle 4 concern.

4. **context stubs remain**: all three new contexts include `[... wired in Cycle 2]` stubs for historical data (SQLite alarm history, active interlocks, recent readings). Cycle 2 SQLite wiring work still pending.

---

## Tests

- 18 existing `test_gemma_alarm_flow.py` tests pass unchanged
- New handler tests + GUI panel tests: pending (Cycle 3 test extension)
- Second Slice A smoke test (all 4 triggers): pending (requires real Ollama session)

---

## Remaining Cycle 3 work (post-architect verification)

Per original scope, test extension is separate from main implementation:

1. `tests/agents/test_gemma_alarm_flow.py` — add tests for 3 new handlers
   - experiment_finalize routing (verify EXPERIMENT_FINALIZE template used)
   - sensor_anomaly_critical routing (verify SENSOR_ANOMALY template)
   - shift_handover_request routing (verify SHIFT_HANDOVER template)
   - config flag gating (experiment_finalize_enabled=False → skip)
   - Empty/truncated response → dispatch skipped, audit logged
2. `tests/gui/shell/views/test_gemma_insight_panel.py` — panel lifecycle
   - push_insight shows card, max 10 kept, placeholder toggles correctly
   - clear() restores placeholder state

---

## Go / No-Go for test extension

**GO** — all main implementation complete, Codex PASS, lint clean, 18 existing tests pass.

Architect can direct:
- A: Proceed with test extension (recommended)
- B: Proceed to Cycle 4 (Slice B) — skip test extension
- C: Run second smoke test first (4 Slice A scenarios)
