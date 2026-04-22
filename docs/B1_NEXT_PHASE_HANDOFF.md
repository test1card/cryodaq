# B1 Next-Phase Authoritative Handoff

**Date:** 2026-04-22  
**Branch:** `codex/safe-merge-b1-truth-recovery`  
**Base:** `origin/master` (256da7a5)  
**HEAD:** 0a4ae040  

---

## TL;DR for Next Engineer

B1 is **reproduced with evidence**, not fixed. IV.6 shipped but did not resolve. IV.7 is a **bounded diagnostic experiment**, not an approved migration. TCP is a **hypothesis**, not a proven culprit.

Your next action: **prepare IV.7 branch for falsification testing** OR **collect OS-level telemetry during next B1 reproduction**.

---

## Current Branch State

```bash
git branch --show-current  # codex/safe-merge-b1-truth-recovery
git rev-parse HEAD         # 0a4ae040bf0698b3804d0b440391be2b9643ff2b
git rev-parse origin/master # 256da7a5b0adaf6ed3cd16313f19e106558d6caa
```

---

## Authoritative Inputs (Current Truth)

| File | Purpose | Status |
|------|---------|--------|
| `artifacts/diagnostics/b1-devmac-current-master.jsonl` | **Raw runtime evidence** | ✅ 56 samples, 52.5s to failure, 175.6s wall-clock |
| `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md` | **Canonical capture procedure** | ✅ Defines classification rules |
| `CODEX_ARCHITECTURE_CONTROL_PLANE.md` | **Architecture authority** | ✅ IV.7 scope, no-go list, human checkpoints |

---

## Historical / Provenance Only (Do Not Treat as Authority)

| File | Why It's Historical |
|------|---------------------|
| `docs/bug_B1_zmq_idle_death_handoff.md` | 2026-04-20 state; IV.6 was thought to fix B1, but runtime proven otherwise |
| `REPO_HARDENING_PLAN.md` | Premise "cooldown missing" is stale (cooldown now in working tree) |
| `REPO_HARDENING_FINAL.md` | Documents hardening as implemented, but pre-B1-reproduction |
| `ZERO_TRUST_AUDIT_2026-04-20.md` | Launcher cooldown finding is stale |

---

## B1 Status: REPRODUCED WITH EVIDENCE

### Runtime Facts (from JSONL)

| Metric | Value | Source |
|--------|-------|--------|
| Sample count | 56 | `seq` field |
| Time to failure | ~52.5 seconds | `ts_utc` delta (first sample → seq 53) |
| Wall-clock capture | ~175.6 seconds (~2m56s) | `ts_utc` delta (first → final sample) |
| Failure mode | Both paths timeout | `bridge_reply.ok=false`, `direct_reply.ok=false` |
| Data plane | Healthy | `heartbeat_stale=false`, `data_flow_stalled=false` |
| Command plane | Failed | `command_channel_stalled=true` |
| Restart triggered | No | `restart_count=1` throughout |

### Supported Claims

✅ **"B1 reproduced with evidence"**
✅ **"~52 seconds to failure after first sample"**
✅ **"~176 seconds wall-clock capture"**
✅ **"Both bridge and direct paths fail together"**
✅ **"Engine REP path or lower transport implicated"** (per runbook classification rule)

### Unsupported Claims

❌ "TCP is the culprit" — not isolated; could be REP state, shared context, FD exhaustion
❌ "B1 is fixed" — IV.6 did not prevent reproduction
❌ "Runtime ~56 seconds" — actual was ~176s
❌ "Stopped at ~56s" — capture continued through failures

---

## IV.7 Status: BOUNDED EXPERIMENT

### What IV.7 Is

- A **diagnostic test** to discriminate transport hypotheses
- **Falsification design:** If B1 reproduces on `ipc://`, TCP-specific hypothesis weakened; if not, TCP-specific transport hypothesis gains support but remains unproven
- **Bounded scope:** IPC transport only, not launcher rewrite or grand redesign

### What IV.7 Is NOT

- An approved migration path
- Guaranteed to resolve B1
- A replacement for root-cause understanding

### Current Justification

**JUSTIFIED as bounded experiment** — baseline evidence exists for comparison.

NOT "strongly justified" — evidence enables testing, does not predict success.

---

## Exact Next Actions (Choose One)

### Option A: Prepare IV.7 Branch (if transport test is priority)

```bash
# 1. Create branch from current working tree
git checkout -b experiment/iv7-ipc-transport

# 2. Implement ipc:// transport (bounded scope)
#    - config: allow ipc:// transport option
#    - launcher: remove TCP coupling in _is_port_busy, _ping_engine
#    - zmq_bridge.py: support ipc:// endpoints
#    - zmq_subprocess.py: support ipc:// endpoints

# 3. Execute canonical runbook on IV.7 branch
CRYODAQ_MOCK=1 cryodaq-engine --mock  # Terminal 1
python tools/diag_zmq_b1_capture.py \
  --duration 180 \
  --interval 1.0 \
  --output artifacts/diagnostics/b1-iv7-ipc.jsonl  # Terminal 2

# 4. Compare to baseline (~52s on TCP)
```

### Option B: OS-Level Telemetry Collection (if root-cause is priority)

During next B1 reproduction, capture:
- `lsof -p $(pgrep -f cryodaq-engine)` — FD counts
- `netstat -an | grep 5556` — socket state
- Direct engine REQ probe while bridge path fails (requires diag tool)

---

## No-Go Rules (Binding)

1. **No IV.5 feature work** — B1 blocks 0.36.0 tag
2. **No transport migration as default** — until IV.7 evidence supports it
3. **No safety-semantic config changes** without Vladimir approval
4. **No claim B1 is fixed** without fresh runtime evidence
5. **No TCP-culprit language** without isolation proof

---

## Human Checkpoints (Require Vladimir)

Before:
- Merging IV.7 transport changes to master
- Changing `config/interlocks.yaml`, `config/alarms_v3.yaml`, or `config/safety.yaml`
- Tagging 0.36.0 while B1 unresolved
- Committing T4 interlock exclusion (repo vs lab divergence)

---

## Key Documents Cross-Reference

This handoff is consistent with:
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md` section 6.2-6.4 (IV.7 scope)
- `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md` classification rules
- `ROADMAP.md` B1/IV.7 status after wording corrections

This handoff supersedes:
- `docs/bug_B1_zmq_idle_death_handoff.md` (historical 2026-04-20)

---

## Artifact Verification

To verify this handoff against source evidence:

```bash
# Duration claims
grep -n "52\|176" artifacts/diagnostics/b1-devmac-current-master.jsonl

# Transport claim ceiling
grep -n "engine REP path or lower transport" docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md

# Runbook execution
grep -n "Executed\|56 samples" artifacts/diagnostics/b1-devmac-run-note.md
```

---

*Authoritative handoff complete. Up-to-date as of 2026-04-22. When in doubt, trust `artifacts/diagnostics/b1-devmac-current-master.jsonl` over any prose summary.*
