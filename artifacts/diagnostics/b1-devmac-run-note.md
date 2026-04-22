# B1 Dev-Mac Run Note

**Date:** 2026-04-22  
**Runbook:** docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md  
**Status:** EXECUTED - B1 successfully reproduced

---

## Baseline Capture

```bash
git rev-parse HEAD
# 0a4ae040bf0698b3804d0b440391be2b9643ff2b

git status --short
# M  artifacts/diagnostics/b1-devmac-current-master.jsonl
# M  artifacts/diagnostics/b1-devmac-run-note.md
```

---

## Execution Environment

| Requirement | Status |
|-------------|--------|
| Target branch | codex/safe-merge-b1-truth-recovery ✓ |
| Base branch | origin/master (256da7a5) ✓ |
| Diagnostic tools | Present (tools/diag_zmq_b1_capture.py) ✓ |
| CryoDAQ engine | RUNNING (mock mode) ✓ |
| Runtime | ~176 seconds wall-clock (~2m56s); capture continued through B1 failure |

---

## Executed Commands

```bash
# Terminal 1: Start engine
CRYODAQ_ROOT=/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery CRYODAQ_MOCK=1 cryodaq-engine --mock

# Terminal 2: Run 180s capture (B1 failure at ~52s; capture continued through failures)
CRYODAQ_ROOT=/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery \
  python tools/diag_zmq_b1_capture.py \
  --duration 180 \
  --interval 1.0 \
  --output artifacts/diagnostics/b1-devmac-current-master.jsonl
```

**Result:** Execution completed with B1 failure reproduced.

---

## B1 Failure Signature

**Time to Failure:** ~52 seconds after first sample  
**Capture Duration:** ~176 seconds wall-clock (expected 180s)  
**Total Samples:** 56  
**First Failure:** seq 53 (at ~52s after capture start)

### Last Healthy Sample (seq 52)
- bridge_reply: {"ok": true, "state": "ready"}
- direct_reply: {"ok": true, "state": "ready"}
- command_channel_stalled: false
- restart_count: 1

### First Failure Sample (seq 53)
- bridge_reply: {"ok": false, "error": "Engine не отвечает (TimeoutError: )"}
- direct_reply: {"ok": false, "error": "Engine did not reply within 5s"}
- command_channel_stalled: true
- restart_count: 1 (no restart triggered during capture)

### Subsequent Samples (54-56)
- Both paths remain failed
- Data plane: healthy (heartbeat continues, readings flow)
- Command plane: FAILED
- Bridge subprocess: did not restart during capture
- Note: 4 post-failure samples collected over ~123s before capture ended

---

## Classification per B1_CURRENT_MASTER_RUNBOOK.md

| Check | Result | Classification |
|-------|--------|----------------|
| 180s canonical capture | PARTIAL (56 samples, ~176s wall-clock) | B1 reproduced |
| Bridge health measurement | FAILED at ~52s | Both paths failed |
| Direct engine probe comparison | FAILED together | Rule: "If bridge_reply and direct_reply fail together: engine REP path or lower transport is implicated" |

**Classification:** Engine REP path or lower transport implicated (NOT bridge-specific)

---

## Key Findings

1. **B1 is real and reproducible on current master**
2. **Failure is NOT bridge-specific** - both bridge and direct engine paths fail together
3. **Failure is in command plane only** - data plane (PUB/SUB, heartbeat) remains healthy
4. **B1 is NOT fixed** - IV.6 watchdog cooldown did not prevent the failure
5. **Watchdog restart did not trigger** - restart_count stayed at 1 (failure may have happened too quickly post-startup)

---

## Evidence Quality

| Finding | Evidence | Confidence |
|---------|----------|------------|
| B1 is reproducible | 56-sample JSONL over ~176s wall-clock | HIGH |
| Failure at ~52s | Sample seq 53 timestamp | HIGH |
| Command plane only | bridge_healthy=true, command_channel_stalled=true | HIGH |
| Both paths fail | seq 53-56 direct_reply and bridge_reply | HIGH |
| Transport layer | Engine REP path or lower transport implicated per runbook | MEDIUM |
| Root cause (specific) | Unknown - requires IV.7 or further diagnostics | NOT DETERMINED |

---

## No-Go Conclusions

Per B1_CURRENT_MASTER_RUNBOOK.md:56-60:

✅ **Do not claim IV.6 closed B1** - B1 reproduced at 52s  
✅ **Do not treat IV.7 as approved** - remains bounded experiment candidate  
✅ **Do not say 0.36.0 is ready** - B1 blocks next formal tag  

---

## Status Update

**B1 Status:** open, with runtime evidence of failure  
**Previous Status:** open, insufficient evidence  
**New Status:** open, **reproduced with evidence** - more specific characterization possible

**CryoDAQ Repo Mode:** hardening (unchanged - B1 remains blocker)

**IV.7 Status:** justified as bounded experiment (unchanged - now has baseline evidence for comparison)

---

*This run note documents successful B1 reproduction on current master. Engine REP path or lower transport is implicated at ~52s, affecting both bridge and direct paths. Root cause still unknown; IV.7 ipc:// remains a bounded diagnostic path.*
