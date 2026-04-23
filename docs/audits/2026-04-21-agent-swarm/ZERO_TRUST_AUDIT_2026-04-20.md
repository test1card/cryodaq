# CryoDAQ Zero-Trust Audit Report
**Date:** 2026-04-20  
**Scope:** Repository state verification, B1 transport-layer analysis, doc/code truth alignment  
**Auditor:** Claude Opus 4.7 with Codex + Gemini adversarial review  
**Status:** COMPLETE — 6 reviewers, Kimi contradiction review finalized

---

## Executive Summary

This audit establishes the current truth of the CryoDAQ repository by separating validated facts from claims, stale documentation, and unproven hypotheses. The critical finding is a **documentation-reality gap around the B1 watchdog fix** — the cooldown mechanism described in handoffs does not exist in committed code.

---

## Label Definitions

- **VALIDATED**: Claim supported by direct code/config evidence
- **PARTIALLY_VALIDATED**: Implemented but runtime behavior unverified
- **PLAUSIBLE**: Consistent with evidence but unproven
- **CONTRADICTED**: Direct evidence refutes the claim
- **STALE**: Claim was once true but no longer reflects reality
- **UNKNOWN**: Insufficient evidence to evaluate

---

## Critical Finding 1: IV.6 Watchdog Cooldown Fix — DOCUMENTED BUT NOT COMMITTED

**Claim (from HANDOFF_2026-04-20_GLM.md:67-115):**  
> "Hotfix applied in-place on Ubuntu's `src/cryodaq/launcher.py` adding 60 s cooldown + missing `return` after restart"

**Label:** 🔴 CONTRADICTED

**Evidence:**
- `src/cryodaq/launcher.py:910-921` (current HEAD 9b047a4):
```python
if self._bridge.command_channel_stalled(timeout_s=10.0):
    logger.warning(
        "ZMQ bridge: command channel unhealthy "
        "(recent command timeout). Restarting bridge."
    )
    self._bridge.shutdown()
    self._bridge.start()
```
- **No `_last_cmd_watchdog_restart` attribute exists**
- **No 60s cooldown check implemented**
- **No `return` after restart**

**What would verify/falsify:**
- FALSIFIED: Current code shows immediate restart on any command timeout
- VERIFY: Look for commit with message "launcher: watchdog cooldown prevents restart storm" — it does not exist in `git log --oneline -20`

**Impact:** CRITICAL — The watchdog regression described (30-40 restarts/min) would occur on any command-channel failure. Current code restarts bridge on every poll tick where `command_channel_stalled()` returns True.

---

## Critical Finding 2: IV.6 Ephemeral REQ Implementation — CORRECT

**Claim:** IV.6 implemented per-command ephemeral REQ socket

**Label:** 🟢 VALIDATED

**Evidence:**
- `src/cryodaq/core/zmq_subprocess.py:157-239`:
  - `_new_req_socket()` creates fresh REQ per command (line 209)
  - `req.close(linger=0)` in `finally` block (line 229)
  - Comments explicitly reference IV.6 (lines 160-172)
- `REQ_RELAXED` and `REQ_CORRELATE` correctly removed (lines 178-184)
- TCP_KEEPALIVE removed from command path as specified (lines 180-184)

**What would falsify:**
- Finding shared REQ socket reuse across commands — NOT FOUND

---

## Critical Finding 3: B1 Root Cause — STILL UNKNOWN

**Claim (original):** B1 caused by shared REQ socket state accumulation

**Label:** 🔴 CONTRADICTED

**Evidence:**
- `docs/bug_B1_zmq_idle_death_handoff.md:553-576`:
  > "IV.6 landed at `be51a24` but did NOT fix B1"
  > "Codex's shared-REQ-state hypothesis FALSIFIED"
- Post-IV.6 diag runs: cmd #8 FAIL at 56s (vs pre-fix cmd #10 at ~30s)
- Rate dependence still present: RAPID_5Hz clean, SPARSE_0.33Hz fails

**Alternative Hypotheses (per Gemini adversarial review):**
1. **ZMQ Context routing state** — Both `sub_drain_loop` and `cmd_forward_loop` share same `zmq.Context()`; routing ID cache may persist across socket recreation
2. **TIME_WAIT socket exhaustion** — Ephemeral REQ creates new TCP connection per command; 120s Ubuntu failure correlates with TCP 2×MSL
3. **REP socket wedging** — If REQ closes mid-transaction, ZMQ REP enters unrecoverable "awaiting reply" state
4. **Python 3.14 + pyzmq asyncio integration** — Platform-specific timing differences suggest library edge case

**Label:** 🟡 UNKNOWN

**What would verify:**
- IV.7 `ipc://` implementation resolves B1 → transport layer confirmed
- Fresh context per REQ (not just fresh socket) resolves B1 → context routing state hypothesis confirmed
- `netstat` shows TIME_WAIT accumulation → socket exhaustion confirmed

---

## Critical Finding 4: IV.7 ipc:// Transport — SPECIFIED BUT NOT IMPLEMENTED

**Claim (CC_PROMPT_IV_7_IPC_TRANSPORT.md):** Ready for implementation

**Label:** 🟡 UNKNOWN (implementation status)

**Evidence:**
- Spec exists at `CC_PROMPT_IV_7_IPC_TRANSPORT.md` with detailed stages
- Current code still uses `tcp://127.0.0.1:5555/5556`:
  - `src/cryodaq/core/zmq_bridge.py:27-28`
  - `src/cryodaq/core/zmq_subprocess.py:31-32`
- `_prepare_ipc_path()` helper not implemented

**Impact:** IV.7 is the next planned B1 fix attempt. Not yet started.

---

## Finding 5: alarm_v2 threshold_expr — CONFIGURED BUT NOT IMPLEMENTED

**Label:** 🔴 CONTRADICTED

**Evidence:**
- `config/alarms_v3.yaml:237` uses `threshold_expr: "T12_setpoint + 50"`
- `src/cryodaq/core/alarm_v2.py:225-265` (`_eval_condition`):
  - Handles `any_below`, `any_above`, `above`, `below`, `rate_above`, `rate_below`, `rate_near_zero`
  - **No handling for `threshold_expr`**
- `src/cryodaq/core/alarm_v2.py:294-334` (`_eval_rate`):
  - Accesses `cfg["threshold"]` directly (lines 308, 310) — will raise KeyError if threshold_expr used

**Impact:** `cooldown_stall` alarm will raise KeyError during evaluation (as noted in CHANGELOG.md line 76-79).

---

## Finding 6: Launcher Hardcoded TCP References

**Label:** 🟢 VALIDATED (present and problematic)

**Evidence:**
- `src/cryodaq/launcher.py:53`: `_ZMQ_PORT = 5555` (TCP port constant)
- `src/cryodaq/launcher.py:159-163`: `_is_port_busy()` uses `socket.AF_INET` (TCP only)
- `src/cryodaq/launcher.py:184`: `_ping_engine()` hardcodes `tcp://127.0.0.1:{_ZMQ_PORT + 1}`

**Impact:** If IV.7 switches to `ipc://`, these launcher functions will fail to detect running engine (will try to start second instance).

---

## Finding 7: ROADMAP Status Accuracy

| Entry | Claimed | Actual | Label |
|-------|---------|--------|-------|
| IV.4 | ✅ CLOSED | `7cb5634` committed | 🟢 VALIDATED |
| IV.5 | Pending B1 fix | Not started | 🟢 VALIDATED |
| B1 | "🔧 root cause identified, fix spec prepared" | Root cause falsified, IV.6 didn't fix | 🔴 STALE |
| IV.6 | "partial B1 mitigation" | Did not fix B1 at all | 🟡 PLAUSIBLE (still valuable architecturally) |
| IV.7 | Ready for implementation | Spec exists, code unchanged | 🟢 VALIDATED |

---

## Finding 8: safety.yaml Config vs SafetyManager Code

**Label:** 🟢 VALIDATED

**Evidence:**
- Config values match SafetyManager defaults:
  - `stale_timeout_s: 10.0` (config) → `stale_timeout_s: 10.0` (code line 62)
  - `heartbeat_timeout_s: 15.0` → `heartbeat_timeout_s: 15.0` (line 63)
  - `max_dT_dt_K_per_min: 5.0` → `max_dT_dt_K_per_min: 5.0` (line 66)
- `require_keithley_for_run: true` correctly implemented (line 65, 25)

---

## Production Readiness Assessment

| Component | Status | Blocker |
|-----------|--------|---------|
| ZMQ Data Plane (PUB/SUB) | 🟢 Operational | — |
| ZMQ Command Plane (REQ/REP) | 🔴 Unreliable | B1 — fails ~30-120s |
| Safety System | 🟢 Operational | — |
| Alarm System | 🟡 Partial | cooldown_stall KeyError |
| Launcher Watchdog | 🔴 Defective | Missing cooldown — restart storm risk |
| GUI Shell v2 | 🟢 Operational | — |
| Engine Core | 🟢 Operational | — |

**Overall:** NOT production-ready for long-duration experiments (>2 minutes) without IV.7 fix OR watchdog cooldown fix.

---

## Unverified Claims Requiring Runtime Verification

1. **Ephemeral REQ creates fresh TCP connection each time** — Could be verified with `netstat -p` during operation
2. **Engine REP socket healthy during B1 failure** — Verified by prior direct Python client test, but not automated
3. **ipc:// will resolve B1** — Only verifiable by implementing IV.7 and running diag tools
4. **60s watchdog cooldown prevents restart storm** — Implementation missing, cannot verify

---

## Recommendations

### Immediate (Before Any Code Change)
1. **Commit the watchdog cooldown fix** — It's documented in handoff but not in code. Risk: restart storm.
2. **Fix alarm_v2 threshold_expr handling** — Defensive access or implement expression evaluation.

### Short Term (Next 1-2 Days)
3. **Implement IV.7 ipc:// transport** — Only remaining hypothesis for B1 not yet tested.
4. **Update launcher TCP probes** — Make `_ping_engine()` and `_is_port_busy()` transport-agnostic.

### Verification Required
5. **Runtime diag on Ubuntu** — Run diag tools with `netstat` monitoring to test TIME_WAIT hypothesis.
6. **Context-per-command experiment** — Test Gemini's hypothesis by creating fresh zmq.Context per REQ.

---

---

## Kimi Contradiction Review — Key Findings

**Reviewer:** Kimi K2.5 (independent, via Chutes)  
**Date:** 2026-04-20

### Confirmed Accurate
- **Claim A (missing watchdog cooldown):** 95% confidence — documentation accurately describes uncommitted fix
- **Claim D (alarm_v2 KeyError):** 90% confidence — technically correct

### Challenged As Confirmation Bias
- **Claim B (shared-REQ-state falsified):** Only 30% confidence
  - Kimi: "Conflates 'insufficient fix' with 'wrong hypothesis'"
  - ZMQ Context (not socket) may retain routing state
  - Engine-side REP state not ruled out
  - Multiple contributing factors possible

### Challenged As Unsupported Leap  
- **Claim C (TCP layer root cause):** Only 25% confidence
  - No TCP-level diagnostics (strace, tcpdump, socket monitor)
  - No direct evidence of TCP failures
  - Asyncio task-level stall not excluded

### Missing Evidence Kimi Identified
1. ZMQ socket monitor events at failure time
2. Asyncio task inspection (`all_tasks()`, `get_stack()`)
3. Context-per-command test (not just socket-per-command)
4. Packet capture of loopback traffic

---

## Revised Confidence Levels Post-Kimi

| Finding | Original | Post-Kimi | Reason |
|---------|----------|-----------|--------|
| Watchdog cooldown missing | 🔴 CONTRADICTED | 🔴 CONTRADICTED (95%) | Kimi confirmed |
| Ephemeral REQ correct | 🟢 VALIDATED | 🟢 VALIDATED (unchanged) | Code evidence clear |
| B1 at TCP layer | 🟡 UNKNOWN | 🟡 UNKNOWN (lower confidence) | Kimi: unsupported leap |
| threshold_expr KeyError | 🔴 CONTRADICTED | 🟡 PLAUSIBLE (caught) | Exception is caught |
| IV.7 as solution | 🟡 PLAUSIBLE | 🟡 PLAUSIBLE (diagnostic value) | Worth testing but not certain |

---

---

## Complete Reviewer Artifact Index

All reviewer outputs are persisted in OMC artifact store:

| Reviewer | Artifact Path | Key Contribution |
|----------|---------------|------------------|
| Codex Regression | `.omc/artifacts/ask/codex-regression-2026-04-20.md` | Restart storm mechanics, in-flight command loss, collateal damage analysis |
| Codex Lifecycle | `.omc/artifacts/ask/codex-lifecycle-2026-04-20.md` | Port binding race, ping/bridge decoupling, subprocess termination analysis |
| Gemini Adversarial | `.omc/artifacts/ask/gemini-adversarial-2026-04-20.md` | Confirmation bias challenge, watchdog priority inversion, IV.7 confidence downgrade |
| Gemini Alternatives | `.omc/artifacts/ask/gemini-alternatives-2026-04-20.md` | 8 competing hypotheses, discrimination matrix, diagnostic sequence |
| Kimi Contradiction | `.omc/artifacts/ask/kimi-contradiction-2026-04-20.md` | TIME_WAIT falsification, alarm_v2 recalibration, 3 omissions identified |
| **Final Arbitration** | `.omc/artifacts/ask/audit-final-2026-04-20.md` | Full label matrix, reviewer contribution map, human checkpoint |

---

## Final Arbitrated Summary

### Blockers (Before Production)

| Rank | Issue | Final Label | Action Required |
|------|-------|-------------|-----------------|
| 1 | Watchdog cooldown missing | **VALIDATED** | Implement 60s cooldown + return after restart |
| 2 | Ping/bridge decoupling | **VALIDATED** | Fix health check to test bridge forward path |
| 3 | B1 root cause | **UNKNOWN** | Runtime diagnostics before speculative fixes |

### Consensus Achieved
- Ephemeral REQ implementation: correct (unanimous)
- IV.6 did NOT fix B1 (unanimous)
- Watchdog cooldown: missing, implement defensively (agreed)
- TIME_WAIT hypothesis: falsified by direct REQ test (Kimi ruling)

### Persistent Disagreements
- Watchdog severity: CRITICAL (Codex) vs HIGH (Gemini/Kimi) — implement regardless
- IV.7 priority: Next 1-2 days (Lead) vs Diagnose first (Gemini) — **defer to diagnostic phase**

---

*Report finalized: 2026-04-20*  
*Reviews completed: Lead + Codex (2) + Gemini (2) + Kimi (1) = 6 independent reviewers*  
*Total artifacts: 7 documents, 11 labeled findings, 5 gaps identified*  
*Status: COMPLETE pending human checkpoint*
