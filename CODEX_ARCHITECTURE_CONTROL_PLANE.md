# CODEX Architecture Control Plane

Date: 2026-04-21
Repo: CryoDAQ
Role: Codex architecture-owner handoff for next-phase work

## Baseline State

This document is written against the current working tree, not only committed `HEAD`.

- Current `HEAD`: `256da7a` (`docs: sync B1 status and next-phase control plane`)
- Relevant B1/watchdog/alarm hardening is now committed on `master`, not only present in a working tree.
- Relevant working-tree drift vs `HEAD` exists in:
  - `src/cryodaq/launcher.py`
  - `src/cryodaq/gui/zmq_client.py`
  - `config/alarms_v3.yaml`
  - `config/channels.yaml`
  - `ROADMAP.md`
  - `CHANGELOG.md`
  - `docs/bug_B1_zmq_idle_death_handoff.md`
- Relevant files unchanged vs `HEAD` in this surface:
  - `src/cryodaq/core/zmq_bridge.py`
  - `src/cryodaq/core/zmq_subprocess.py`
  - `src/cryodaq/core/alarm_v2.py`
  - `config/interlocks.yaml`
  - `config/safety.yaml`

Architecture decisions below are made against the current working tree. Drift from `HEAD` is recorded explicitly. Do not blur them.

## 1. Current Architectural Truth

### 1.1 Definitely true in code now

- CryoDAQ still runs a split local transport architecture:
  - engine owns PUB/REP in `src/cryodaq/core/zmq_bridge.py`
  - launcher GUI owns a subprocess bridge in `src/cryodaq/gui/zmq_client.py`
  - bridge subprocess owns both SUB drain and command forwarding in `src/cryodaq/core/zmq_subprocess.py`
- IV.6 ephemeral REQ per command is present in code now. Each command in `cmd_forward_loop()` creates, uses, and closes a fresh REQ socket (`src/cryodaq/core/zmq_subprocess.py:157-239`). This stays.
- The bridge subprocess still uses one shared `zmq.Context()` for both SUB and ephemeral REQ sockets (`src/cryodaq/core/zmq_subprocess.py:86`). Ephemeral sockets did not eliminate that shared-context surface.
- Bridge heartbeat proves only the SUB/data path is alive because heartbeat is emitted by `sub_drain_loop()`, not the command path (`src/cryodaq/core/zmq_subprocess.py:90-155`).
- Command-plane failures are surfaced indirectly: timed-out REQ operations emit `{"__type": "cmd_timeout"}` into the data queue, and the launcher watches `command_channel_stalled()` (`src/cryodaq/core/zmq_subprocess.py:215-225`, `src/cryodaq/gui/zmq_client.py:188-199`, `src/cryodaq/launcher.py:910-928`).
- The current working tree contains a 60-second cooldown on command-watchdog restarts via `_last_cmd_watchdog_restart` plus a `return` after restart (`src/cryodaq/launcher.py:915-928`). `HEAD` does not.
- The current working tree contains bridge diagnostic instrumentation:
  - `_restart_count` increments on every bridge start, including initial start (`src/cryodaq/gui/zmq_client.py:93-94`, `133-134`)
  - exit code logging on bridge shutdown (`src/cryodaq/gui/zmq_client.py:275-280`)
  - `HEAD` does not.
- The launcher still hardcodes TCP assumptions:
  - `_is_port_busy()` uses `AF_INET` and `127.0.0.1` (`src/cryodaq/launcher.py:155-169`)
  - `_ping_engine()` uses a direct `tcp://127.0.0.1:5556` REQ (`src/cryodaq/launcher.py:172-190`)
  - default bridge addresses are still `tcp://127.0.0.1:5555/5556` (`src/cryodaq/core/zmq_subprocess.py:31-32`, `src/cryodaq/core/zmq_bridge.py:27-28`)
- The new launcher discrepancy log is not a real ping-vs-bridge check. `_check_engine_health()` uses `_is_engine_alive()`, which is process liveness or raw port occupancy, while `_ping_engine()` is only used during startup (`src/cryodaq/launcher.py:311-318`, `490-496`, `1132-1140`). Current code logs "engine ping OK but bridge unhealthy" without actually performing that ping in the health path.
- `alarm_v2` still does not implement `threshold_expr`. Composite condition checks still read `cond["threshold"]` directly for `above`, `below`, `rate_above`, and `rate_below` (`src/cryodaq/core/alarm_v2.py:225-288`).
- The current working tree mitigates `cooldown_stall` by replacing `threshold_expr` with a static `threshold: 150` in `config/alarms_v3.yaml:227-240`. `HEAD` still has the older config.
- `config/interlocks.yaml` still includes T4 in the cryostat overheat regex via `Т[1-8] .*` (`config/interlocks.yaml:17-24`). The repo does not contain the lab-side T4 exclusion described in handoff text.
- `config/safety.yaml` still makes `Т1`, `Т7`, `Т11`, and `Т12` the critical safety channels (`config/safety.yaml:8-18`).
- B1 is not fixed in code. No current code path proves otherwise.

### 1.2 Only inherited claim unless re-verified at runtime

- That the 60-second watchdog cooldown is operationally effective during real B1 events.
- That Ubuntu lab-side local config already excludes T4 from emergency interlock behavior.
- That IV.7 `ipc://` will resolve B1 rather than only perturb its timing.
- That the current hardening instrumentation is already sufficient for operators rather than only for controlled diagnostics.

### 1.3 Still unresolved

- Actual B1 root cause.
- Whether the remaining B1 mechanism is transport-layer, shared-context-related, REP-loop state related, or another race.
- Whether current bridge diagnostics are enough to discriminate those hypotheses without one more bounded probe.
- Repo-vs-lab truth for T4/interlock semantics.

## 2. Architecture-Critical Surviving Findings

Only the findings that still matter for decisions survive.

1. B1 remains open. IV.6 improved the command path shape but did not close the failure.
2. IV.6 ephemeral REQ is a keeper. It is now part of the intended architecture, not a disposable experiment.
3. Data-plane health and command-plane health are separate. Heartbeats and readings do not prove command reachability.
4. The current discrepancy logging is semantically overstated. It is process/port-vs-bridge logging, not direct-engine-ping-vs-bridge logging. Do not use those log lines as transport evidence.
5. The launcher remains transport-coupled to TCP loopback. Any future `ipc://` experiment must account for launcher startup and health helpers, not only bridge defaults.
6. The bridge subprocess still shares one `zmq.Context()` across SUB and per-command REQ sockets. Shared REQ state is gone; shared context is not.
7. `threshold_expr` is still unsupported in `alarm_v2`. The current config change is a workaround, not a feature completion.
8. T4 config reality is still unresolved at repo level. The git-tracked repo still allows T4 to participate in cryostat emergency interlock matching.
9. Current hardening changes are committed on `master`. Future reviews must still distinguish code truth from inherited runtime claims, but they must no longer describe the cooldown / restart-count / config mitigation tranche as unpublished drift.

## 3. State-Drift Reconciliation

### 3.1 Where earlier audits looked at different repo states

- `ZERO_TRUST_AUDIT_2026-04-20.md` inspected a state where the launcher cooldown was absent. That finding is stale against the current working tree but still matches `HEAD`.
- `REPO_HARDENING_PLAN.md` was written from the same earlier state. Its "cooldown missing" premise is stale against the working tree.
- `REPO_HARDENING_FINAL.md` and `REPO_HARDENING_CHANGELOG.md` describe the hardening items as implemented, which is true for the working tree but false for committed `HEAD`.

### 3.2 Documents now stale or partially stale

- `ZERO_TRUST_AUDIT_2026-04-20.md`
  - stale on launcher cooldown absence
  - stale on current `cooldown_stall` config
  - still useful on transport hardcoding and "B1 unresolved"
- `REPO_HARDENING_PLAN.md`
  - stale as a live truth document
  - still useful as scope-control history
- `REPO_HARDENING_FINAL.md`
  - stale if read as repository `HEAD` truth
  - still useful if read as working-tree hardening summary
- `REPO_HARDENING_CHANGELOG.md`
  - inaccurate on one important point: it claims the new launcher log proves direct engine ping vs bridge divergence
  - current code does not do that check
- `agentswarm/.../02_code_truth/CODE_TRUTH_FINDINGS.md`
  - incorrect on commit-state framing
  - it says the hardening exists in `HEAD`; it does not

### 3.3 Documents still useful

- `HANDOFF_2026-04-20_GLM.md`
  - useful for sequencing, preserved uncertainty, and "do not revert IV.6"
  - not authoritative for repo config truth
- `SESSION_DETAIL_2026-04-20.md`
  - useful as hypothesis ledger and provenance record
- `docs/bug_B1_zmq_idle_death_handoff.md`
  - useful for B1 evidence history and why IV.6 stays
  - filename remains historically misleading because B1 is not an "idle death"
- `GEMINI_READING_LEDGER.md`
  - useful as reading provenance only
- `agentswarm/.../06_runtime_runbooks/GEMINI25_B1_DIAGNOSTIC_RUNBOOK.md`
  - useful as a diagnostic scaffold
  - requires one correction: current discrepancy logs do not prove direct engine ping success

## 4. Decision Boundaries

| Issue | Boundary | Reason |
|---|---|---|
| Preserve IV.6 ephemeral REQ + command watchdog | Decide now | This is architectural improvement independent of root-cause closure. |
| Treat current working tree as baseline for next phase | Decide now | Relevant code and docs differ from `HEAD`; pretending otherwise will contaminate every review. |
| Use current discrepancy logs as proof of direct engine reachability | Decide now: reject | Current code does not perform that runtime ping in `_check_engine_health()`. |
| B1 root-cause conclusion | Diagnose now | The remaining uncertainty is still too large for architecture-level closure. |
| IV.7 `ipc://` as default direction | Diagnose now, not decide | It is still a bounded experiment, not a committed migration path. |
| T4 interlock / alarm semantics | Human checkpoint required | This changes operator-facing safety behavior. Repo and lab claims diverge. |
| Dynamic `threshold_expr` support in `alarm_v2` | Defer | Current static config is enough for now; this is not the next-phase B1 blocker. |
| Broad transport abstraction cleanup | Defer | Premature before deciding whether transport migration even survives diagnostics. |
| Grand engine/bridge redesign | Defer | Too much blast radius while basic runtime truth is still incomplete. |

## 5. Repo Hardening Priorities

Short and surgical.

1. Freeze the baseline in writing.
   - This document is step one.
   - Every next-phase run must say whether it is operating on current working tree or committed `HEAD`.
2. Correct health-semantics confusion before relying on logs.
   - Do not run a major B1 diagnostic pass while the team is still calling process/port liveness a "ping OK" signal.
3. Run one disciplined B1 evidence pass on the current working tree.
   - Use the existing cooldown, restart-count, exit-code, and `cmd_timeout` surfaces.
   - Add external OS telemetry in the run, not speculative code churn.
4. Resolve T4 repo-vs-lab config reality with Vladimir.
   - Either commit the intended behavior after approval or stop talking as if repo already reflects it.
5. Only then choose whether IV.7 is worth a bounded experiment branch.

## 6. B1 Next-Phase Architecture Stance

### 6.1 What not to do yet

- Do not revert IV.6.
- Do not claim the cooldown workaround fixes B1.
- Do not treat current discrepancy logs as direct engine-ping evidence.
- Do not start a broad `ipc://` abstraction cleanup across launcher, bridge, tools, and docs as if migration were already approved.
- Do not jump to in-process threading, pyzmq replacement, queue redesign, or engine breakup.
- Do not mix B1 work with safety-semantic config work.

### 6.2 What evidence must be gathered next

- A fresh B1 reproduction run against the current working tree, not an older branch.
- Timestamped correlation of:
  - `cmd_timeout` events
  - bridge `restart_count`
  - bridge subprocess exit codes
  - launcher watchdog restarts
  - direct external command success/failure over time
- OS-side telemetry during failure:
  - socket states for 5555/5556
  - file-descriptor counts for the bridge subprocess
  - whether the engine REP path still answers a direct probe when the bridge-forwarded command path fails

### 6.3 What instrumentation is sufficient

Current repo instrumentation is sufficient for the next phase if it is used honestly:

- sufficient:
  - `cmd_timeout` markers
  - launcher cooldown behavior
  - bridge start count
  - bridge exit-code logging
  - existing diag tools
- not sufficient by itself:
  - the current "ZMQ health discrepancy" line
  - any inference that bridge heartbeat implies command health
  - any inference that process/port liveness implies REP command responsiveness

The next run needs operational telemetry layered around the current code, not a new speculative instrumentation spree.

### 6.4 What migration or redesign ideas remain premature

- defaulting the product to `ipc://`
- removing subprocess isolation
- rewriting the launcher health model wholesale
- replacing pyzmq/libzmq
- engine/bridge architectural breakup for "cleanliness"

All of these are downstream of evidence, not substitutes for evidence.

## 7. Model-Role Guidance

### Codex should own

- code-grounded architecture truth
- lifecycle and restart-path analysis
- affected-caller and collateral-surface review
- interpretation of runtime evidence against actual code
- arbitration on what is a real architectural finding vs a document artifact

### Gemini 2.5 should be asked

- to attack overclaim
- to design falsification-oriented runbooks
- to challenge whether collected telemetry actually proves the stated mechanism
- to call out when "instrumented" is being misrepresented as "understood"

### Gemini 3.1 should be asked

- to synthesize large corpora after the next run
- to maintain provenance and reading ledgers
- to reconcile many documents and logs without losing sequence
- to build next-phase work packages after evidence exists

### Kimi should always check

- stale-claim contamination
- hypothesis inflation
- commit-state confusion
- whether a proposed fix is actually warranted by evidence
- whether wording quietly upgrades "possible" into "true"

## 8. No-Go List

- No deleting or moving original artifacts.
- No `rm`, no `git clean`, no destructive reset.
- No claim that B1 is fixed without fresh runtime evidence on the current working tree.
- No reverting IV.6 because it did not fully resolve B1.
- No treating the mitigation tranche as if it were still unpublished drift.
- No safety-semantic config edits without Vladimir approval.
- No transport migration presented as a cleanup task.
- No broad refactor justified by file size or aesthetics.
- No operator-facing wording that suggests command-path health from the current discrepancy log.
- No `0.34.0` release claim while B1 remains unresolved.

## 9. Human Checkpoints

Vladimir approval is required before:

1. Any change to `config/interlocks.yaml`, `config/alarms_v3.yaml`, or `config/safety.yaml` that alters safety semantics.
2. Any repo change meant to mirror the reported Ubuntu-local T4 behavior.
3. Any transport migration beyond a bounded diagnostic branch.
4. Any operator-facing health message or runbook language that could mislead staff about what has actually been verified.
5. Any release or tag decision that implies B1 is no longer blocking.

## 10. Recommended Next Run Structure

### Preparation

- Freeze the baseline:
  - record `HEAD`
  - record working-tree diff
  - state explicitly that the run uses current working tree
- Preserve the current hardening surfaces; do not fold in unrelated fixes.
- Predeclare hypotheses and falsification criteria.

### Lead baseline

- Lead model writes the baseline run note:
  - exact repo state
  - exact hypotheses under test
  - exact telemetry to capture
  - exact stop conditions

### Codex review

- Codex verifies the code surfaces under test:
  - launcher health path
  - bridge subprocess lifecycle
  - engine REP semantics
  - diag-tool coverage
- Codex rejects any runbook claim not matched by code.

### Gemini adversarial pass

- Gemini 2.5 reviews the runbook for overclaim and weak falsification.
- It should specifically challenge:
  - whether the measurements distinguish transport from context from REP-state failure
  - whether any collected signal is only correlated, not causal

### Kimi contradiction pass

- Kimi reviews the assembled conclusions before they are accepted.
- Kimi must explicitly test:
  - whether commit-state drift polluted the conclusion
  - whether wording overstates what the telemetry proves
  - whether "did not fix" is being quietly rewritten into "falsified" without enough support

### Final arbitration

- Lead model writes the final decision memo.
- Codex signs off only on code-grounded conclusions.
- Kimi contradiction findings must be answered explicitly, not hand-waved.
- Output must classify each result as:
  - code truth
  - runtime truth
  - inherited claim
  - still unresolved

---

Bottom line: the next phase is not a redesign phase. It is a controlled truth-recovery phase around B1, with IV.6 preserved, working-tree drift made explicit, hardening overclaims corrected, and safety/config changes held behind human checkpoints.
