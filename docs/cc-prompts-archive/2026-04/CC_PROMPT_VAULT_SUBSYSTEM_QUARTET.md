# Vault subsystem notes quartet — spec

> **Spec authored 2026-04-29 by architect.** Implementation by Sonnet 
> per overnight runner.

---

## 0. Mandate

Four architectural vault notes deferred from 2026-04-26 vault build:

| Slot | Note path | Source files |
|---|---|---|
| 1 | `10 Subsystems/Web dashboard.md` | `src/cryodaq/web/` |
| 2 | `10 Subsystems/Cooldown predictor.md` | `src/cryodaq/core/cooldown_predictor.py`, `cooldown_service.py` |
| 3 | `10 Subsystems/Experiment manager.md` | `src/cryodaq/core/experiment_manager.py`, `experiment.py` |
| 4 | `10 Subsystems/Interlock engine.md` | `src/cryodaq/core/interlock.py` |

Each note ~60-100 lines following existing subsystem note patterns 
(cf. `Reporting.md`, `Calibration v2.md`, `ZMQ bridge.md`).

---

## 1. Note structure (template)

```markdown
---
source: <relevant src/ paths>
last_synced: 2026-04-29
status: synthesized
---

# <Subsystem name>

## Purpose
<1-2 paragraphs: what this subsystem does, why it exists>

## Architecture
<Bullet points or short prose: key classes, data flow, dependencies>

## Trigger / lifecycle
<When does this subsystem activate? What's its lifecycle within 
an experiment?>

## Configuration
<Config files, env vars, runtime parameters>

## Failure modes
<What can go wrong, what's the operator-visible symptom, what's the 
mitigation>

## Cross-links
<Wiki-links to related subsystems, investigations, decisions>

## Notes
<Any historical context, open questions, deferred work>
```

---

## 2. Per-note guidance

### 2.1 Web dashboard (`10 Subsystems/Web dashboard.md`)

Source files: `src/cryodaq/web/server.py`, `src/cryodaq/web/static/`, 
`src/cryodaq/web/templates/`.

Focus areas:
- FastAPI app structure
- Live readings WebSocket
- Read-only nature (no command channel via web)
- Current endpoints inventory
- Auth model (loopback default per ROADMAP F7 entry)
- Cross-link to F7 deferred extension

Avoid:
- Reproducing endpoint specs verbatim — link to `src/`
- Speculating about future endpoints (those are F7 territory)

### 2.2 Cooldown predictor (`10 Subsystems/Cooldown predictor.md`)

Source files: `src/cryodaq/core/cooldown_predictor.py`, 
`src/cryodaq/core/cooldown_service.py`.

Focus areas:
- Current predictor: simple regression
- Feature inputs (start T, current T, target T, time elapsed)
- Output: estimated time remaining
- Limitations (no uncertainty quantification, no per-cryostat tuning)
- Cross-link to F8 (research upgrade item)
- Cooldown_stall composite alarm relationship

Avoid:
- Detailed prediction math — link to source
- F8 design speculation

### 2.3 Experiment manager (`10 Subsystems/Experiment manager.md`)

Source files: `src/cryodaq/core/experiment_manager.py`, 
`src/cryodaq/core/experiment.py`.

Focus areas:
- 6-state FSM (idle → cooldown → measurement → warmup → 
  disassembly → idle, plus aborted)
- Phase transition triggers (manual operator vs automatic)
- ExperimentInfo dataclass and its `to_payload` shape (re. `experiment_id` 
  audit finding from F3 Cycle 4)
- Persistence: JSON metadata files at 
  `data/experiments/<id>/metadata.json`
- Finalize hook chain: report → Parquet → notification
- Lifecycle relationship with safety_manager

Cross-links:
- Safety manager FSM
- Reporting subsystem
- F3 W3 experiment_summary widget consumer

### 2.4 Interlock engine (`10 Subsystems/Interlock engine.md`)

Source file: `src/cryodaq/core/interlock.py`.

Focus areas:
- 3-rule current state (overheat_cryostat, overheat_compressor, 
  detector_warmup) per `config/interlocks.yaml`
- Action types (`emergency_off`, `stop_source`)
- Cooldown windows
- Pattern matching channel selection (regex)
- Distinction from alarm engine (interlocks are hard safety; alarms 
  are soft notifications)
- Relationship to safety_manager FSM transitions

Cross-links:
- Safety manager
- Alarm engine v2
- Cyrillic homoglyph investigation (Т vs T in alarm config — 
  same risk class applies to interlock channel patterns)

---

## 3. Constraints

- Each note ≤120 lines
- No code blocks longer than 5 lines (link to source instead)
- Wikilinks `[[Path/Note]]` resolved within vault
- Frontmatter mandatory with `last_synced: 2026-04-29`
- Tone matches existing `10 Subsystems/` notes (factual, concise, 
  cross-linked)

---

## 4. Acceptance

After all 4 notes written:

1. Run vault source map regen:
   `python3 ~/Projects/cryodaq/artifacts/vault-build/build_source_map.py`
2. Verify 0 broken wikilinks
3. Total note count: 75 (was 71 + 4 new)
4. Append build log entry:
   `~/Vault/CryoDAQ/_meta/build log.md`

---

## 5. Dispatching

Single Sonnet session, sequential note writing. Per note:
- Read source files briefly (don't dump full contents into thinking)
- Synthesize into note structure
- Write via Obsidian MCP

After all 4 written: source map + build log + final report.

No audit pass needed — these are vault hygiene notes, not code.

If Sonnet stuck on any single note (unfamiliar subsystem, ambiguity):
- Write what's known
- Flag gaps in note's "Open questions" section
- Move to next note
- Architect refines in morning if needed

Spec deviations welcome and encouraged.
