# REPO_HARDENING_MASTER_DOSSIER

## 0. Document purpose
This execution-guidance dossier defines the factual repository state, exposes critical hallucinations in prior audits, and outlines a safe hardening and diagnostic roadmap for the CryoDAQ agent swarm. It acts as the single source of truth for execution.

## 1. Inspection completeness
INCOMPLETE corpus access. The mandatory arbitration file (`.omc/artifacts/ask/audit-final-2026-04-20.md`) and the individual reviewer artifacts (`codex-regression`, `gemini-adversarial`, etc.) are missing from the filesystem. This dossier relies on cross-referencing `ZERO_TRUST_AUDIT_2026-04-20.md` with direct code inspection to bridge the gap.

## 2. Trust model actually used
Precedence applied in strict order:
1. Current code and configuration files.
2. `audit-final-2026-04-20.md` (Not used, missing).
3. `ZERO_TRUST_AUDIT_2026-04-20.md`.
4. Handoff (`HANDOFF_2026-04-20_GLM.md`) and session notes (`SESSION_DETAIL_2026-04-20.md`).

## 3. Repo ground truth now
- **ID:** F-01
- **Statement:** The IV.6 watchdog cooldown fix prevents restart storms.
- **Label:** VALIDATED
- **Primary evidence file:** `src/cryodaq/launcher.py:915-928`
- **Short rationale:** Code contains `_last_cmd_watchdog_restart`, 60-second gate, and `return`. The prior audit hallucinated its absence.

- **ID:** F-02
- **Statement:** Disconnected T4 sensor is still actively evaluated in hardware interlocks.
- **Label:** VALIDATED
- **Primary evidence file:** `config/interlocks.yaml:20`
- **Short rationale:** Overheat regex remains `Т[1-8] .*`. Handoff claims of its exclusion were local edits on Ubuntu, uncommitted.

- **ID:** F-03
- **Statement:** Launcher startup/restart logic explicitly assumes IPv4 TCP loopback.
- **Label:** VALIDATED
- **Primary evidence file:** `src/cryodaq/launcher.py:155-184`
- **Short rationale:** `_ping_engine` and `_is_port_busy` hardcode `AF_INET` and `127.0.0.1`, which will break an `ipc://` migration.

- **ID:** F-04
- **Statement:** `_ping_engine()` tests direct engine REP reachability only.
- **Label:** VALIDATED
- **Primary evidence file:** `src/cryodaq/launcher.py:172-184`
- **Short rationale:** The ping bypasses the bridge's forwarding path and creates its own ZMQ context to ping the engine directly.

- **ID:** F-05
- **Statement:** Ephemeral REQ socket commands share a single global `zmq.Context()`.
- **Label:** VALIDATED
- **Primary evidence file:** `src/cryodaq/core/zmq_subprocess.py:86`
- **Short rationale:** `ctx = zmq.Context()` is initialized once and reused by `_new_req_socket()`, persisting TCP multiplexing and routing tables.

## 4. Claims that were downgraded or excluded
- **Original claim:** Watchdog cooldown fix is missing.
- **Source:** `ZERO_TRUST_AUDIT_2026-04-20.md`
- **Why downgraded:** Code inspection proved the fix is fully present.
- **Status:** Contradicted.

- **Original claim:** T4 alarm groups were updated to publish warnings and drop interlock.
- **Source:** `HANDOFF_2026-04-20_GLM.md`
- **Why downgraded:** Code inspection proved T4 is still in the `Т[1-8] .*` interlock regex and explicitly commented out of `alarms_v3.yaml` groups.
- **Status:** Contradicted.

- **Original claim:** `alarm_v2` triggers `KeyError` on `threshold_expr`.
- **Source:** `ZERO_TRUST_AUDIT_2026-04-20.md`
- **Why downgraded:** `config/alarms_v3.yaml:237` already replaced this with a static `threshold: 150` and a comment.
- **Status:** Stale.

## 5. Contradiction map
- **Contradiction ID:** C-01
- **Side A:** Zero-Trust Audit claims the IV.6 watchdog cooldown is missing.
- **Side B:** `launcher.py` contains the exact cooldown logic.
- **Stronger evidence:** `launcher.py`
- **Current ruling:** Audit is wrong. Code is protected from restart storms.
- **What would settle it completely:** N/A.

- **Contradiction ID:** C-02
- **Side A:** Handoff documentation claims T4 config changes were deployed.
- **Side B:** The repository configuration files lack these changes.
- **Stronger evidence:** Current config files.
- **Current ruling:** Edits were made locally on the Ubuntu PC but never committed.
- **What would settle it completely:** Committing the T4 config changes.

## 6. Reviewer-quality corrections
- **Lead (GLM-5.1):**
  - Strongest contribution: Methodical execution of simple patches.
  - Strongest mistake: Trusting handoff text over direct git state.
  - Safe for next steps: Yes, but requires strict supervision to verify claims first.
- **Codex Regression/Lifecycle:**
  - Strongest contribution: Concurrency safety analysis.
  - Strongest mistake: Likely authored the Zero-Trust Audit segment that hallucinated the missing watchdog cooldown by scanning an outdated branch.
  - Safe for next steps: Yes, for pure architectural logic, but NOT for current-state assessment.
- **Gemini Adversarial/Alternatives:**
  - Strongest contribution: Spotting the `zmq.Context()` routing state persistence.
  - Strongest mistake: None explicitly identified due to missing artifacts.
  - Safe for next steps: Yes, highly reliable for hypothesis generation.
- **Kimi Contradiction:**
  - Strongest contribution: Correctly falsifying the TIME_WAIT exhaustion hypothesis and pushing back on TCP leaps.
  - Strongest mistake: None explicitly identified due to missing artifacts.
  - Safe for next steps: Yes, crucial for epistemic reality checks.

## 7. Hardening work packages
**WP-01: T4 Interlock Configuration Alignment**
- **Title:** T4 Interlock Configuration Alignment
- **Objective:** Prevent the disconnected T4 sensor from triggering `emergency_off`.
- **Why justified now:** Documented as fixed, but actively breaking hardware in repo state.
- **Findings addressed:** F-02, C-02
- **Files in scope:** `config/interlocks.yaml`, `config/alarms_v3.yaml`
- **Files out of scope:** Python files.
- **Minimal expected change:** Change `overheat_cryostat` regex to `Т(1|2|3|5|6|7|8) .*`. Add T4 to `uncalibrated` and `all_temp` groups in `alarms_v3.yaml`.
- **Likely collateral damage:** None.
- **Required validation:** Diff verification.
- **Reviewer most needed:** Gemini 2.5 Pro
- **Status:** IMPLEMENT NOW

**WP-02: Launcher TCP Probe Decoupling**
- **Title:** Launcher TCP Probe Decoupling
- **Objective:** Abstract `_is_port_busy` and `_ping_engine` to be transport-agnostic.
- **Why justified now:** Blocked the proposed IV.7 `ipc://` migration.
- **Findings addressed:** F-03, F-04
- **Files in scope:** `src/cryodaq/launcher.py`
- **Files out of scope:** `engine.py`, ZMQ cores.
- **Minimal expected change:** Handle file socket existence checks for `ipc://` paths.
- **Likely collateral damage:** False engine-start modals.
- **Required validation:** App launch and shutdown.
- **Reviewer most needed:** Codex Lifecycle
- **Status:** DEFER (Until Diag-01 is complete)

## 8. Diagnostic work packages
**Diag-01: ZMQ Context State Falsification**
- **Objective:** Determine if the global `zmq.Context()` retains routing state that poisons ephemeral REQ sockets.
- **Files/components involved:** `src/cryodaq/core/zmq_subprocess.py`
- **Signal needed:** Does `diag_zmq_idle_hypothesis.py` pass if `_new_req_socket()` creates and destroys a local `zmq.Context()` per command?
- **Hypothesis it tests:** Gemini's Context Multiplexing hypothesis.
- **Invasiveness:** Low (test script only).
- **Before/after relation to hardening:** BEFORE any transport migration.

## 9. Agent assignment guide
- **WP-01 (T4 Config Fix):**
  - Lead model role: Execute file edits.
  - Codex role: None.
  - Gemini 2.5 Pro role: Verify semantic YAML layout.
  - Kimi role: None.
  - Human checkpoint required: No.
- **WP-02 (Launcher TCP Decoupling):**
  - Lead model role: Code implementation.
  - Codex role: Review startup/shutdown race conditions.
  - Gemini 2.5 Pro role: Review abstraction purity.
  - Kimi role: None.
  - Human checkpoint required: Yes.
- **Diag-01 (Context State):**
  - Lead model role: Write temporary test patch.
  - Codex role: None.
  - Gemini 2.5 Pro role: Analyze failure/success logs.
  - Kimi role: Challenge conclusions.
  - Human checkpoint required: Yes (to run the script on physical hardware).

## 10. No-go list
- **Do not "fix" the watchdog cooldown:** It is present and correct.
- **Do not migrate to `ipc://`:** Wait for Diag-01 results, as launcher hardcoding (F-03) will break.
- **Do not fix `threshold_expr` in `alarm_v2`:** It is a stale bug replaced by a static config value.
- **Do not rely on `ZERO_TRUST_AUDIT_2026-04-20.md` for current code state.**

## 11. Recommended execution order
1. Execute WP-01 (T4 Config Fix).
2. Execute Diag-01 (ZMQ Context Test).
3. Await human review of Diag-01 results.
4. Execute WP-02 (Launcher TCP Decoupling) only if Diag-01 proves `ipc://` is strictly required.

## 12. What must be manually rechecked before trusting this dossier
1. Spot-check `launcher.py` lines 915-928 to confirm the watchdog cooldown is indeed present, overturning the Zero-Trust Audit.
2. Spot-check `config/interlocks.yaml` line 20 to confirm the T4 sensor regex remains `Т[1-8] .*`, proving the handoff was uncommitted.
3. Spot-check `config/alarms_v3.yaml` line 237 to confirm `threshold_expr` was removed in favor of a static threshold, rendering the alarm_v2 bug stale.