# Repo Cleanup Audit — 2026-04-30

## Top-level files (root of repo)

### Legitimate (keep as-is)
- README.md, LICENSE, CHANGELOG.md, ROADMAP.md, CLAUDE.md, RELEASE_CHECKLIST.md
- pyproject.toml, requirements-lock.txt, .gitignore, .gitattributes, .graphifyignore
- create_shortcut.py, release_notes.py, install.bat, start*.bat, start*.sh
- THIRD_PARTY_NOTICES.md

### CC_PROMPT_* files to archive (scope completed)
- CC_PROMPT_IV_2_ORCHESTRATOR.md (IV.2 → v0.34.0) — git-tracked
- CC_PROMPT_IV_3_BATCH.md (IV.3 → v0.34.0) — git-tracked
- CC_PROMPT_IV_4_BATCH.md (IV.4 safe features F1/F2/F6/F11 → v0.34.0) — git-tracked
- CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md (IV.6 ZMQ ephemeral REQ → v0.34.0) — git-tracked
- CC_PROMPT_IV_7_IPC_TRANSPORT.md (IV.7 ipc:// experiment, superseded H5 fix v0.39.0) — git-tracked
- CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md (closed, v0.36.0-era) — git-tracked
- CC_PROMPT_VAULT_BUILD_2026-04-26.md (vault construction session) — git-tracked
- CC_PROMPT_VAULT_AUDIT_2026-04-27.md (vault audit session) — git-tracked
- CC_PROMPT_F3_ANALYTICS_WIRING.md (F3 spec → v0.40.0) — untracked
- CC_PROMPT_F3_OVERNIGHT_RUNNER.md (F3 5-cycle runner → v0.40.0) — untracked
- CC_PROMPT_F10_SENSOR_DIAGNOSTICS_ALARM.md (F10 spec → v0.41.0) — untracked
- CC_PROMPT_VAULT_SUBSYSTEM_QUARTET.md (4 vault notes → v0.41.0) — untracked
- CC_PROMPT_OVERNIGHT_RUNNER_2026-04-29.md (multi-track overnight → v0.41.0) — untracked
- CC_PROMPT_METASWARM_2026-04-29.md (24-dispatch metaswarm session) — untracked

### CC_PROMPT_* files to keep (active or pending)
- CC_PROMPT_CALIBRATION_2026-04-30.md — RUNNING (calibration session complete as of this cleanup)
- CC_PROMPT_REPO_CLEANUP_2026-04-30.md — THIS PROMPT
- CC_PROMPT_METASWARM_F17.md — PENDING: F17 "Cold-storage rotation spec", not yet implemented

### Stale top-level docs to archive
- HANDOFF_2026-04-20_GLM.md (2026-04-21, 9 days old, single-session handoff) — git-tracked
- SESSION_DETAIL_2026-04-20.md (2026-04-20, 10 days old, 93KB session log) — git-tracked
- CODEX_ARCHITECTURE_CONTROL_PLANE.md (2026-04-24, belongs in docs/) — git-tracked

### Living docs requiring update
- PROJECT_STATUS.md (last modified 2026-04-24, 6 days stale)
- DOC_REALITY_MAP.md (last modified 2026-04-17, 13 days stale)
- docs/NEXT_SESSION.md (last modified 2026-04-23, 7 days stale)

### Suspicious files (Phase 1 investigates)
- draft.py (2026-04-28, untracked)
- draft2.py (2026-04-28, untracked)
- ~/  directory (shell mkdir mistake — architect confirmed safe to remove)
- tsp/p_const.lua (Keithley TSP script — documented in architecture.md, KEEP)

---

## Investigation results (Phase 1)

### draft.py
**Contents:** Word-count utility for a CryoDAQ release narrative text (4-paragraph
feature overview). Uses `re.findall` to count words. Unrelated to production code.
Likely a one-off scratch script used during changelog/release-notes drafting.

**Git-tracked:** No (untracked).
**References in codebase:** None (only referenced in CC_PROMPT_REPO_CLEANUP_2026-04-30.md
as a suspicious file subject to investigation).
**Recommendation:** ARCHITECT DECISION NEEDED — safe to delete; not production code and
not referenced. If the text inside is needed, it belongs in CHANGELOG.md or docs/.

### draft2.py
**Contents:** Same release narrative text as draft.py but with minor wording variations
and two word-count methods (`.split()` vs `re.findall`). Variant of draft.py.

**Git-tracked:** No (untracked).
**References in codebase:** None.
**Recommendation:** ARCHITECT DECISION NEEDED — same as draft.py; safe to delete.

### ~/ directory (literal `~` in repo root)
**Contents:** Contains at least one file: `~/Projects/cryodaq/~/artifacts/consultations/
2026-04-28-pre-ultrareview/gemini-recon-audit.response.md`. The directory
mirrors a partial home-directory tree — created by a shell command that used
unquoted `~` as a relative path argument.

**Git-tracked:** No files tracked; directory not in git index.
**Recommendation:** ARCHITECT DECISION NEEDED — rm -rf ~/Projects/cryodaq/\~/ when
architect present. Not auto-deleted per safety rule. Contents appear to be a
duplicate of artifacts/consultations/ data (no unique information).

### tsp/p_const.lua
**Contents:** Parameterized constant-power TSP supervisor script for Keithley 2604B.
Uses `{SMU}` template placeholder (replaced by host before upload). Implements
P=const control loop with 30s watchdog and safe shutdown. Currently NOT uploaded
to instrument — host-side P=const in keithley_2604b.py is used instead.

**Git-tracked:** Yes (in git index).
**References:** docs/architecture.md:158, docs/instruments.md:123, docs/audits/ (multiple).
**Recommendation:** KEEP. Legitimate Phase 3 hardware watchdog preparation. Well-documented
in architecture.md and instruments.md. No cleanup action needed.

### agentswarm/
**Contents:** `2026-04-21-overnight-hardening/` directory — historical artifact from
overnight hardening swarm session.

**Git-tracked:** No — gitignored via `.gitignore:76` (`agentswarm/`).
**Recommendation:** No action (gitignored). Architect may move to `~/Projects/cryodaq-archive/`
outside repo at convenience. Not visible to git.

### graphify-out/ and graphify-out.stale-pre-merge/
**Contents:** Knowledge graph outputs — gitignored local caches.
Both directories gitignored (`.graphifyignore` / `.gitignore`).
`.stale-pre-merge` name indicates a pre-merge snapshot.

**Git-tracked:** No (gitignored).
**Recommendation:** No action. Architect can delete locally when convenient.
`graphify-out.stale-pre-merge/` is safe to remove (stale snapshot).

### .scratch, .swarm, .audit-run, .omc
All gitignored agent workspaces:
- `.scratch/` — zmq-exploration-2026-04-21 scratch
- `.swarm/` — swarm config + logs from 2026-04-27 session
- `.audit-run/` — 2026-04-20-zero-trust audit artifacts
- `.omc/` — OMC project memory + DS_Store; last written 2026-04-29 (active)

**Recommendation:** No action. All gitignored. `.omc/project-memory.json` is actively
used by oh-my-claudecode. Do not touch.
