# CryoDAQ — PROJECT_STATUS

**Дата:** 2026-04-13
**Ветка:** master
**Последний commit:** `21e9c40`
**Тесты:** 880 passed, 6 skipped

---

## Масштаб проекта

| Метрика | Значение |
|---|---|
| Python файлы (src/cryodaq/) | 102 |
| Строки кода (src/cryodaq/) | ~33,800 |
| Тестовые файлы (tests/) | 113 |
| Тесты | 880 passed, 6 skipped |
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
11. **Cancellation shielding** на _fault() post-fault paths: emergency_off, fault_log_callback, _ensure_output_off в _safe_off.
12. **Fail-closed config:** safety.yaml и alarms_v3.yaml → SafetyConfigError/AlarmConfigError → engine exit code 2 (без auto-restart).
13. **Atomic file writes** для experiment sidecars и calibration index/curve через core/atomic_write.
14. **WAL mode verification:** raises RuntimeError если PRAGMA journal_mode=WAL вернул не 'wal'.
15. **Calibration KRDG+SRDG** persist в одной транзакции per poll cycle.
16. **Scheduler.stop()** — graceful 5s drain перед forced cancel.

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

## Phase 2d — Block A + B COMPLETE

9 commits on master, each с Codex (gpt-5.4) review.

### Block A.1 — Safety hardening

| Commit | Описание | Codex |
|---|---|---|
| `88feee5` | Web XSS escapeHtml + _fault() shield + RUN_PERMITTED stale/rate + safety.yaml fail-closed + Latin T | BLOCKING |
| `1446f48` | Heartbeat gap in RUN_PERMITTED + SafetyConfigError class | SIGNIFICANT → MINOR |
| `ebac719` | SafetyConfig coercion wrapper + critical_channels type validation | CLEAN |

### Block A.2 — Alarm config + safety bridge

| Commit | Описание | Codex |
|---|---|---|
| `1b12b87` | Phantom interlocks removed + AlarmConfigError + safety→operator_log + acknowledge real impl | SIGNIFICANT |
| `e068cbf` | Restore keithley_overpower + engine log label + None path msg + docstring + broker publish + re-ack guard | CLEAN |

### Block A.8 followup — Jules architectural review

| Commit | Описание | Codex |
|---|---|---|
| `5cf369e` | Shield _fault_log_callback + shield _ensure_output_off in _safe_off | MINOR |

### Block B-1 — Atomic file writes

| Commit | Описание | Codex |
|---|---|---|
| `d3abee7` | Experiment sidecars + calibration index/curve atomic write + WAL mode verification | MINOR |

### Block B-2 — Persistence integrity

| Commit | Описание | Codex |
|---|---|---|
| `104a268` | OVERRANGE persist + calibration KRDG/SRDG atomic + scheduler graceful drain | BLOCKING |
| `21e9c40` | Drop NaN-valued statuses (SENSOR_ERROR, TIMEOUT) from persist set | CLEAN |

### Итоги Phase 2d

- **Тесты:** 829 → 880 (+51 regression tests)
- **Codex review iterations:** 9 commits, 14 Codex reviews (several commits went through 2-3 iterations)
- **Final verdicts:** 4 CLEAN, 3 MINOR, 0 outstanding BLOCKING/SIGNIFICANT
- **Jules findings:** 2 cancellation shielding holes caught by architectural review that tactical CC+Codex missed

---

## Deferred items

### From Phase 2d commit messages

1. **A.7 semantic config errors** — alarm_v2.py `_expand_alarm` / `_parse_engine_config` don't validate unknown keys or semantic correctness. Medium-sized audit. Source: `e068cbf`.
2. **A.9.1 consumer wiring** — engine command handler `alarm_v2_status` drops acknowledged/acknowledged_at/acknowledged_by fields. GUI/web/Telegram can't see acknowledgment state. Source: `e068cbf`.
3. **B.1.2 NaN statuses via sentinel or schema migration** — SENSOR_ERROR/TIMEOUT readings (NaN value) currently dropped; full post-mortem requires nullable value column or sentinel value. Source: `21e9c40`.
4. **C.1 Ubuntu SQLite version gating** — `sqlite_writer.py` warns about WAL-reset corruption bug in SQLite 3.7.0–3.51.2 but does not block. Needs hardware validation. Source: MASTER_TRIAGE.md.
5. **C.3 synchronous=FULL decision** — currently NORMAL (loses ~1s on power loss). UPS-dependent. Source: MASTER_TRIAGE.md.
6. **P2 DataBroker exception blocks SafetyBroker** — if DataBroker publish raises, SafetyBroker publish is skipped. Separate isolation fix. Source: `PERSISTENCE_INVARIANT_DEEP_DIVE.md`.
7. **P3 day-boundary batch splitting** — batch spanning midnight can split across daily DB files mid-transaction. Source: `PERSISTENCE_INVARIANT_DEEP_DIVE.md`.
8. **Test timeout bounding** — cancellation shield tests use `asyncio.sleep(0.2)` as proxy instead of `asyncio.wait_for(...)`. Codex flagged as MINOR. Source: `5cf369e` Codex review.

### MASTER_TRIAGE.md Block C scope (potential next work)

- Enforce `requirements-lock.txt` hash verification and pin `hatchling`
- Fix `post_build.py` to copy plugin sidecars + document POSIX symlink-preserving deployment
- Move writable runtime state out of bundle directory
- Remove executable runtime plugin loading from production bundles or mark as trusted/read-only
- Bound web history/log queries + isolate heavy background executor consumers

**Effort:** ~12-20 CC hours. **Risk:** low to medium.

---

## Открытые дефекты (non-Phase-2d)

See `DEEP_AUDIT_CC_POST_2C.md`, `HARDENING_PASS_CODEX.md`, `MASTER_TRIAGE.md` for full audit finding lists. Phase 2d closed ~15 of the highest-severity findings. Remaining findings are tracked in Block C/D scope or deferred to Phase 3.

---

## В работе

**Phase 2d CHECKPOINT.** Block A + Block B complete. Awaiting Jules round 2 architectural review before deciding Block C vs Phase 2e.

---

## Parallel track

`feat/ui-phase-1-v2` continues independently on GUI rewrite (shell scaffold + dashboard). Not touched by Phase 2d master track. Will be merged to master after UI stabilization.

---

## Ключевые решения

1. **Dual-channel Keithley (smua + smub)** — confirmed operational model.
2. **Persistence-first** — SQLite WAL commit BEFORE any subscriber sees data.
3. **Fail-closed safety config** — missing/malformed safety.yaml or alarms_v3.yaml prevents engine start (exit code 2, no auto-restart).
4. **Cancellation shielding** — hardware emergency_off AND post-mortem log emission AND _safe_off cleanup are all asyncio.shield'd against outer cancellation.
5. **OVERRANGE/UNDERRANGE persist** — ±inf stored as REAL in SQLite. NaN-valued statuses dropped until Phase 3 schema/sentinel work.
6. **Atomic sidecar writes** — experiment metadata, calibration index/curve use core/atomic_write (temp+fsync+os.replace).
7. **WAL mode verification** — engine refuses to start if SQLite can't enable WAL.
8. **Graceful scheduler drain** — 5s window for in-flight polls to complete persist+publish before forced cancel.
9. **Three-layer review** — CC tactical + Codex second-opinion + Jules architectural. See audit pipeline section.

---

## Команды

```bash
pip install -e ".[dev,web]"
cryodaq                        # Operator launcher
cryodaq-engine --mock          # Mock engine
cryodaq-gui                    # GUI only
pytest                         # 880 passed, 6 skipped
ruff check src/ tests/
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
3. **Jules architectural review** — looks at the entire fault path holistically, not individual diffs. Found two cancellation holes that both tactical layers missed:
   - `_fault_log_callback` not shielded (post-mortem evidence lost on cancellation)
   - `_ensure_output_off` in `_safe_off` fault-latched branch not shielded

**Key insight:** Codex excels at line-level semantic analysis (wrong type, wrong API, wrong filter). Jules excels at cross-cutting architectural analysis (cancellation propagation through multi-step fault paths). Neither replaces the other.

**Block A.1 specifically** went through 3 iterations (initial + fix + micro-fix) before reaching CLEAN — this is normal for safety-critical code and the iterative pattern should be expected.
