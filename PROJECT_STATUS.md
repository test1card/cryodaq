# CryoDAQ — PROJECT_STATUS

**Дата:** 2026-04-14
**Ветка:** master
**Последний commit:** `89ed3c1`
**Тесты:** 890 passed, 6 skipped
**Phase 2d COMPLETE. Phase 2e IN PROGRESS.**

---

## Масштаб проекта

| Метрика | Значение |
|---|---|
| Python файлы (src/cryodaq/) | 102 |
| Строки кода (src/cryodaq/) | ~33,900 |
| Тестовые файлы (tests/) | 113 |
| Тесты | 890 passed, 6 skipped |
| Версия | 0.13.0 |
| Python | 3.12+ (dev: 3.14.3) |

---

## Физическая установка

| Прибор | Интерфейс | Каналы | Драйвер |
|---|---|---|---|
| LakeShore 218S (x3) | GPIB | 24 температурных | `lakeshore_218s.py` |
| Keithley 2604B | USB-TMC | smua + smub | `keithley_2604b.py` |
| Thyracont VSP63D | RS-232 | 1 давление | `thyracont_vsp63d.py` |

### Аппаратные инварианты (верифицированы по DOC_REALITY_MAP.md)

1. **SAFE_OFF** — состояние по умолчанию. Source ON = непрерывное доказательство здоровья.
2. **Persistence-first:** SQLiteWriter.write_immediate() → DataBroker → SafetyBroker.
3. **SafetyState FSM:** 6 состояний — SAFE_OFF → READY → RUN_PERMITTED → RUNNING → FAULT_LATCHED → MANUAL_RECOVERY → READY.
4. **Fail-on-silence:** stale data → FAULT (только в RUNNING; вне RUNNING блокирует readiness через preconditions).
5. **Rate limit:** dT/dt > 5 K/мин → FAULT (конфигурируемый default в safety.yaml, не жёсткий инвариант).
6. **Keithley connect:** forces OUTPUT_OFF на обоих SMU (best-effort: при ошибке логирует CRITICAL и продолжает).
7. **Keithley disconnect:** вызывает emergency_off() первым.
8. **No blocking I/O на engine event loop** (исключение: `reporting/generator.py` sync subprocess.run для LibreOffice).
9. **No numpy/scipy в drivers/core** (исключение: `core/sensor_diagnostics.py` — MAD/корреляция).

### Инварианты добавленные Phase 2d

10. **OVERRANGE/UNDERRANGE** persist с status (±inf валидные REAL в SQLite). SENSOR_ERROR/TIMEOUT (NaN) отфильтровываются.
11. **Cancellation shielding** на _fault() post-fault paths: emergency_off, fault_log_callback (before publish), _ensure_output_off в _safe_off.
12. **Fail-closed config:** safety.yaml, alarms_v3.yaml, interlocks.yaml, housekeeping.yaml, channels.yaml → subsystem-specific ConfigError → engine exit code 2 (без auto-restart).
13. **Atomic file writes** для experiment sidecars и calibration index/curve через core/atomic_write.
14. **WAL mode verification:** raises RuntimeError если PRAGMA journal_mode=WAL вернул не 'wal'.
15. **Calibration KRDG+SRDG** persist в одной транзакции per poll cycle. State mutation deferred to on_srdg_persisted.
16. **Scheduler.stop()** — graceful drain (configurable via safety.yaml scheduler_drain_timeout_s, default 5s) перед forced cancel.
17. **_fault() ordering:** post-mortem log callback BEFORE optional broker publish (Jules R2 fix).

---

## Архитектура

```
Instruments → Scheduler → SQLiteWriter → DataBroker → ZMQ → GUI
                                       → SafetyBroker → SafetyManager
                                       → CalibrationAcquisition
```

- **Engine** (headless asyncio): drivers, scheduler, persistence, safety, alarms, interlocks, plugins
- **GUI** (PySide6): owned by `feat/ui-phase-1-v2`, out of scope for master track
- **Web** (FastAPI): optional monitoring dashboard
- **IPC:** ZeroMQ PUB/SUB :5555 (data, msgpack) + REP/REQ :5556 (commands, JSON)

---

## Phase 2d — COMPLETE (2026-04-13)

14 commits, +61 tests (829 → 890), zero regressions. Triple-reviewer pipeline (CC tactical + Codex second-opinion + Jules architectural) validated across Safety, Persistence, and Config Fail-Closed subsystems.

### Commits (chronological)

| # | Commit | Описание | Codex |
|---|---|---|---|
| 1 | `88feee5` | Block A.1: Web XSS + _fault() shield + RUN_PERMITTED + safety.yaml fail-closed + Latin T | BLOCKING |
| 2 | `1446f48` | Block A.1 fix: heartbeat gap in RUN_PERMITTED + SafetyConfigError class | CLEAN |
| 3 | `ebac719` | Block A.1 fix2: SafetyConfig coercion wrapper + critical_channels type validation | CLEAN |
| 4 | `1b12b87` | Block A.2: phantom interlocks + AlarmConfigError + safety→operator_log + acknowledge | SIGNIFICANT |
| 5 | `e068cbf` | Block A.2 fix: keithley_overpower restore + engine label + broker publish + re-ack guard | CLEAN |
| 6 | `5cf369e` | Jules R1 followup: shield _fault_log_callback + _ensure_output_off in _safe_off | MINOR |
| 7 | `d3abee7` | Block B-1: atomic file writes (experiment + calibration) + WAL verification | MINOR |
| 8 | `104a268` | Block B-2: OVERRANGE persist + calibration KRDG/SRDG atomic + scheduler drain | BLOCKING |
| 9 | `21e9c40` | Block B-2 fix: drop NaN-valued statuses from persist set | CLEAN |
| 10 | `23929ca` | Checkpoint: PROJECT_STATUS update | — |
| 11 | `efe6b49` | Chore: ruff --fix lint debt (830 → 445 errors) | — |
| 12 | `f4c256f` | Chore: remove accidental logs/, add .gitignore | — |
| 13 | `74f6d21` | Jules R2 fix: _fault() ordering + calibration state mutation deferral | CLEAN |
| 14 | `89ed3c1` | Block C-1: interlocks/housekeeping/channels fail-closed + drain timeout config + on_readings deprecation | MINOR |

### Themes closed

#### Safety hardening
- Web stored XSS escape (escapeHtml helper)
- _fault() hardware emergency_off shielded from cancellation
- _fault() _fault_log_callback shielded (Jules R1)
- _fault() ordering: callback BEFORE publish (Jules R2)
- _safe_off() fault-latched branch shielded (Jules R1)
- RUN_PERMITTED heartbeat monitoring (stuck start_source detection)
- safety.yaml + alarms_v3.yaml + interlocks.yaml + housekeeping.yaml + channels.yaml fail-closed
- Latin T / Cyrillic Т regression fix in housekeeping.yaml
- safety→operator_log bridge with broker publish
- AlarmStateManager.acknowledge real implementation with idempotent re-ack guard
- SafetyConfigError / AlarmConfigError / InterlockConfigError / HousekeepingConfigError / ChannelConfigError hierarchy

#### Persistence integrity
- Atomic file writes via core/atomic_write (experiment sidecars, calibration index/curve)
- WAL mode verification (refuse startup if not enabled)
- OVERRANGE/UNDERRANGE readings persist with status field
- NaN-valued statuses (SENSOR_ERROR, TIMEOUT) dropped to avoid IntegrityError
- Calibration KRDG+SRDG atomic per poll cycle (single write_immediate)
- Calibration state mutation deferred to on_srdg_persisted (Jules R2)
- Scheduler.stop() graceful drain (configurable, default 5s) before forced cancel

#### Operational polish
- _DRAIN_TIMEOUT_S exposed via SafetyConfig.scheduler_drain_timeout_s
- Legacy on_readings converted to deprecation shim
- Ruff lint debt reduced 830 → 445
- Engine config error handler: unified label dispatch for all 5 config error types

---

## Phase 2e — IN PROGRESS (started 2026-04-14)

### Primary goal

Parquet experiment archive stage 1 — write readings.parquet in artifact_dir when experiment finalizes. Enables long-term archival, offline analytics, and reproducibility. First of 4 stages.

### Parallel track — operational hardening (deferred from Phase 2d Block C-2)

- K.1 — requirements-lock.txt hash verification in build path
- K.2 — post_build.py copies plugin YAML sidecars alongside .py files
- J.1 — Runtime root outside bundle directory (writable state separation)
- H.1 — Runtime plugin loading trust boundary (read-only or disabled in production)
- G.1 — Web dashboard auth or loopback-only default
- G.2 — Web history/log query size bounds
- F.1 — Telegram bot persist last update_id, discard backlog on restart
- CONFIG_AUDIT C.1 — .local.yaml merge instead of replace

### Other Phase 2e candidates

- A.7.5 — Semantic config errors in _parse_engine_config / _expand_alarm
- A.9.1 — Engine command handler serializes acknowledged state through ZMQ
- A.8.1 + C-1 test gaps — batch cleanup for accumulated minor test findings
- Structural tests → behavioral rewrite (for Phase 2d structural regression locks)
- Jules Q2 — Pre-flight config check in launcher with operator-visible diagnostic
- P2 — DataBroker exception isolation from SafetyBroker
- P3 — Day-boundary batch splitting

### Deferred to Phase 3 (hardware validation required)

- B.1.2 — NaN statuses via sentinel or schema migration
- C.1 — Ubuntu 22.04 SQLite version gating (WAL-reset bug on libsqlite3 < 3.51.3)
- C.3 — synchronous=FULL decision with UPS deployment note

---

## Открытые дефекты (non-Phase-2d)

See `DEEP_AUDIT_CC_POST_2C.md`, `HARDENING_PASS_CODEX.md`, `MASTER_TRIAGE.md` for full audit finding lists. Phase 2d closed ~20 of the highest-severity findings. Remaining findings tracked in Phase 2e candidates or Phase 3 deferrals above.

---

## В работе

**Phase 2e IN PROGRESS.** Primary: Parquet archive. Parallel: operational hardening (Block C-2 items).

---

## Parallel track

`feat/ui-phase-1-v2` continues independently on GUI rewrite (shell scaffold + dashboard with real pyqtgraph plots). Not touched by Phase 2d master track. Will be merged to master after UI stabilization.

---

## Ключевые решения

1. **Dual-channel Keithley (smua + smub)** — confirmed operational model.
2. **Persistence-first** — SQLite WAL commit BEFORE any subscriber sees data.
3. **Fail-closed config** — all 5 safety-adjacent configs (safety, alarm, interlock, housekeeping, channels) prevent engine start on missing/malformed files.
4. **Cancellation shielding** — hardware emergency_off, post-mortem log emission, _safe_off cleanup all asyncio.shield'd. Log callback ordered BEFORE optional publish.
5. **OVERRANGE/UNDERRANGE persist** — ±inf stored as REAL in SQLite. NaN-valued statuses dropped until Phase 3.
6. **Atomic sidecar writes** — experiment metadata, calibration index/curve use core/atomic_write.
7. **WAL mode verification** — engine refuses to start if SQLite can't enable WAL.
8. **Graceful scheduler drain** — configurable via safety.yaml scheduler_drain_timeout_s (default 5s).
9. **Three-layer review** — CC tactical + Codex second-opinion + Jules architectural.
10. **Calibration state deferral** — prepare_srdg_readings computes pending state, on_srdg_persisted applies atomically after successful write.

---

## Команды

```bash
pip install -e ".[dev,web]"
cryodaq                        # Operator launcher
cryodaq-engine --mock          # Mock engine
cryodaq-gui                    # GUI only
pytest                         # 890 passed, 6 skipped
ruff check src/ tests/         # 445 remaining (from 830)
ruff format src/ tests/
```

---

## Audit pipeline meta-observations

Phase 2d established a **three-layer review pattern** for safety-critical changes:

1. **CC tactical review** — implementer verifies each change against the prompt spec, writes tests, runs suite.
2. **Codex second-opinion** — independent gpt-5.4 review of the committed diff. Finds issues CC missed:
   - RUN_PERMITTED heartbeat gap (gated on `_active_sources` which is empty during source start)
   - `housekeeping.py` reads the alarms_v3 `interlocks:` section that CC deleted as "dead config"
   - NaN vs ±inf IEEE 754 distinction (SQLite treats NaN as NULL, violating NOT NULL)
   - Engine log label said "safety config" for alarm errors
3. **Jules architectural review** — looks at the entire fault path holistically, not individual diffs:
   - **Round 1:** Found `_fault_log_callback` not shielded + `_ensure_output_off` in `_safe_off` not shielded
   - **Round 2:** Found `_fault()` ordering vulnerability (callback after publish = escape path) + calibration state mutation before persistence (t_min/t_max divergence on write failure)

**Key insight:** Codex excels at line-level semantic analysis (wrong type, wrong API, wrong filter). Jules excels at cross-cutting architectural analysis (cancellation propagation, ordering dependencies across multi-commit refactors). Neither replaces the other.

**Phase 2d total:** 14 commits, 17 Codex reviews, 2 Jules rounds. Every review found at least one real issue. The iterative correction pattern (initial → Codex BLOCKING → fix → re-review → CLEAN) is the expected workflow for safety-critical code.
