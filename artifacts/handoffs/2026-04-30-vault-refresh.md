# Vault refresh — 2026-04-30 docs-audit Phase 2 Group IV

## Notes refreshed (in-place, last_synced → 2026-04-30)

| Note | What changed |
|---|---|
| `60 Roadmap/Versions.md` | Added v0.42.0 + v0.43.0 rows; updated Current state (HEAD c44c575, pyproject 0.43.0, next release undefined) |
| `60 Roadmap/F-table backlog.md` | Full rewrite from ROADMAP post-v0.43.0; F1-F26 with current statuses; F19-F25 ✅ DONE |
| `10 Subsystems/Alarm engine v2.md` | Fixed AlarmEvent "frozen" → mutable @dataclass (frozen=False); added F20/F21/F22 sections |
| `10 Subsystems/Sensor diagnostics alarm.md` | F20 "## Deferred" → "## Shipped"; aggregation_threshold + escalation_cooldown_s documented |
| `10 Subsystems/Interlock engine.md` | Added F24 ZMQ acknowledge command section with operator workflow |
| `10 Subsystems/Persistence-first.md` | Added F25 SQLite WAL startup gate section (RuntimeError, bypass env var, F26 backport whitelist note) |
| `10 Subsystems/Safety FSM.md` | Added F23 RateEstimator measurement timestamp section; added HF1+HF3 update_target delayed-update section |
| `10 Subsystems/Analytics view.md` | Added F19 enrichment to ExperimentSummaryWidget entry (channel stats, top-3 alarms, clickable links) |
| `10 Subsystems/Plugin architecture.md` | Added F20 config additions section (aggregation_threshold, escalation_cooldown_s in plugins.yaml) |
| `30 Investigations/B1 ZMQ idle-death.md` | Status frontmatter: "OPEN" → "closed (H5 fix shipped v0.39.0 2026-04-27)"; body: "blocks v0.34.0" → closure note |
| `00 Overview/What is CryoDAQ.md` | Added F10/F19-F25 feature references to "What it does"; updated version/tag to v0.43.0 |
| `00 Overview/Architecture overview.md` | Added F20/F21/F22/F24/F25 subsystem map references |
| `_meta/build log.md` | Appended 2026-04-30 Group IV entry |

## Notes added

None — all edits in-place per architect OQ #7 decision.

## Source map

Build script not present (`artifacts/vault-build/build_source_map.py` missing).
Vault wikilink integrity not formally verified this session.
**ARCHITECT DECISION NEEDED:** add vault build script to repo, or accept informal
wikilink checking via Obsidian graph view.

## Coverage gaps closed

| Feature | Vault note extended |
|---|---|
| F19 W3 enrichment | Analytics view.md |
| F20 aggregation + cooldown | Sensor diagnostics alarm.md + Plugin architecture.md + Alarm engine v2.md |
| F21 hysteresis deadband | Alarm engine v2.md |
| F22 severity upgrade | Alarm engine v2.md |
| F23 RateEstimator timestamp | Safety FSM.md |
| F24 interlock acknowledge ZMQ | Interlock engine.md |
| F25 SQLite WAL gate | Persistence-first.md |

## Total notes

29 content notes (unchanged count — all in-place edits).
