# IV.7 — `ipc://` transport experiment for B1

**Goal:** test whether switching the CryoDAQ ZMQ transport from
`tcp://127.0.0.1:5555/5556` to `ipc:///tmp/cryodaq-*.sock` resolves
bug B1 (GUI command channel silently dies ~30-120 s after bridge
startup). Minimal-scope experiment — change two constants, verify
with diag tools on both macOS dev and Ubuntu lab PC.

**Rationale:** IV.6 ruled out shared-REQ-state as the root cause
(per-command ephemeral REQ did not fix B1). Idle-reap was already
ruled out by Linux `tcp_keepalive_time=7200s`. Everything above the
transport layer was shown healthy during the failure window
(engine asyncio loop alive, data plane unaffected, heartbeats flow).
The remaining candidate is the TCP-loopback layer itself — libzmq
loopback handling, pyzmq asyncio integration under rapid
connect/disconnect churn, kernel loopback state accumulation, or
similar. Unix domain sockets via `ipc://` bypass TCP entirely and
are libzmq's recommended transport for same-host IPC.

**If IV.7 resolves B1:** we tag `0.34.0` and close the chapter. The
change is minimal, backwards-compatible with existing code, keeps
subprocess crash-isolation model intact.

**If IV.7 does NOT resolve B1:** we have eliminated another hypothesis
and know the cause lies above the transport (engine-side REP task
state, or cross-process synchronisation in pyzmq itself). Next step
at that point would be in-process threading (subprocess removal) or
full pyzmq replacement — heavy scope, consider only after IV.7
verdict.

**K-criticality:** K1 (blocks GUI ↔ Engine command plane, every
operator action — experiment create, calibration, Keithley control,
alarm ack — becomes unreliable after ~60-120 s without IV.7).

**Expected size:** ~20 LOC source + 10 LOC tests. Single commit.

---

## Autonomy declaration

This spec follows `docs/CODEX_SELF_REVIEW_PLAYBOOK.md`.

- Stage 0 reads informational; proceed to Stage 1.
- Stages 1-5 sequential autonomous.
- Stage 6 (`/codex` self-review): **required** this time because
  the change touches the IPC transport layer, and verification of
  cross-platform semantics (macOS vs Linux `ipc://` behaviour) is
  worth a second set of eyes. Invoke with `gpt-5.4 high`.
- Amend-cycle limit 3.
- STOP only on: genuine architectural fork in Stage 0, design-decision
  FAIL from Codex, 3 amends without PASS, or diag tools still reproduce
  B1 post-fix (in which case B1 is NOT at transport layer — STOP to
  architect for next-strategy decision).

---

## Stage 0 — Verification reads

1. `docs/bug_B1_zmq_idle_death_handoff.md` — full evidence dump
   including Codex analysis and IV.6 outcome section. Understand why
   ipc:// is the current working hypothesis.
2. `HANDOFF_2026-04-20_GLM.md` — today's context including known
   state.
3. `src/cryodaq/core/zmq_bridge.py` — engine-side PUB/REP. Find:
   - `DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"` or similar
   - `DEFAULT_CMD_ADDR = "tcp://127.0.0.1:5556"` or similar
   - All `bind()` + `connect()` call sites
4. `src/cryodaq/core/zmq_subprocess.py` — GUI-side SUB/REQ. Same
   constants (imported or duplicated — find out which).
5. `src/cryodaq/gui/zmq_client.py` — `ZmqBridge` wrapper — confirm
   no transport-specific assumptions in client-side code.
6. `src/cryodaq/launcher.py` — engine lifecycle — confirm launcher
   does not hardcode `tcp://` anywhere.
7. `tools/diag_zmq_*.py` — check if diag tools hardcode `tcp://`.
   They likely do, for the soak tests.

Findings informational. Do NOT stop after reads. Proceed to Stage 1.

---

## Stage 1 — Implementation

### Option A (preferred) — hardcode `ipc://` switch

If `DEFAULT_PUB_ADDR` and `DEFAULT_CMD_ADDR` are defined as constants
in `zmq_bridge.py` and imported by `zmq_subprocess.py` /
`zmq_client.py`:

```python
# zmq_bridge.py
import sys

if sys.platform == "win32":
    # ipc:// on Windows = named pipes with different semantics;
    # fall back to tcp:// on Windows for now. Windows deployment
    # is not current lab target.
    DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
    DEFAULT_CMD_ADDR = "tcp://127.0.0.1:5556"
else:
    # On macOS and Linux, use Unix domain sockets via ipc://
    # to bypass TCP-loopback layer entirely. Resolves bug B1
    # (command channel silently dies after 30-120s uptime).
    # Socket files live in /tmp; auto-cleaned on restart.
    DEFAULT_PUB_ADDR = "ipc:///tmp/cryodaq-pub.sock"
    DEFAULT_CMD_ADDR = "ipc:///tmp/cryodaq-cmd.sock"
```

Keep any existing env-var override plumbing (e.g. `CRYODAQ_PUB_ADDR`)
intact so Vladimir can manually force tcp:// for diagnostics.

### Option B — environment-variable opt-in

If `DEFAULT_*_ADDR` are already env-var driven, just change the
default behaviour to compute from sys.platform and keep the env-var
override.

**Either option:** socket file cleanup. `ipc://` creates files at
the given path. On crash / ungraceful exit, stale socket files
remain and prevent rebind. Add:

- `bind()` call in engine should `os.unlink()` the socket path
  first (suppress FileNotFoundError), then bind. Matches libzmq
  convention for ipc:// transports.
- Graceful shutdown should unlink socket files too.

Reference pattern (adapt to actual code structure):

```python
def _prepare_ipc_path(addr: str) -> None:
    """If addr is ipc://<path>, unlink stale socket file before bind."""
    if addr.startswith("ipc://"):
        path = addr[len("ipc://"):]
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)
```

Call `_prepare_ipc_path(DEFAULT_PUB_ADDR)` and
`_prepare_ipc_path(DEFAULT_CMD_ADDR)` before the respective
`bind()` calls in engine startup.

### Also update diag tools

`tools/diag_zmq_bridge.py`, `tools/diag_zmq_bridge_extended.py`,
`tools/diag_zmq_idle_hypothesis.py`, `tools/diag_zmq_subprocess.py` —
if they hardcode `tcp://127.0.0.1:5556`, update to respect the same
defaults from `zmq_bridge.py` (import the constant). They are
regression reproducers — they must exercise the same transport the
real system uses.

---

## Stage 2 — Tests

1. **New unit test** in `tests/core/test_zmq_transport_defaults.py`:

   ```python
   import sys
   from cryodaq.core.zmq_bridge import DEFAULT_PUB_ADDR, DEFAULT_CMD_ADDR

   class TestDefaultTransport:
       def test_addr_prefixes_match_platform(self):
           if sys.platform == "win32":
               assert DEFAULT_PUB_ADDR.startswith("tcp://")
               assert DEFAULT_CMD_ADDR.startswith("tcp://")
           else:
               assert DEFAULT_PUB_ADDR.startswith("ipc://")
               assert DEFAULT_CMD_ADDR.startswith("ipc://")

       def test_pub_and_cmd_are_different(self):
           assert DEFAULT_PUB_ADDR != DEFAULT_CMD_ADDR
   ```

2. **Stale-socket cleanup test:**

   ```python
   import os, tempfile
   from cryodaq.core.zmq_bridge import _prepare_ipc_path

   class TestIpcPathPreparation:
       def test_unlinks_existing_socket_file(self, tmp_path):
           sock_path = tmp_path / "test.sock"
           sock_path.write_text("")   # simulate stale file
           addr = f"ipc://{sock_path}"
           _prepare_ipc_path(addr)
           assert not sock_path.exists()

       def test_noop_for_tcp_addr(self):
           _prepare_ipc_path("tcp://127.0.0.1:5555")
           # No exception, no side effect — just return.

       def test_noop_if_no_existing_file(self, tmp_path):
           addr = f"ipc://{tmp_path / 'nonexistent.sock'}"
           _prepare_ipc_path(addr)   # FileNotFoundError suppressed
   ```

3. **Existing bridge tests should still pass** with ipc:// default
   on non-Windows, tcp:// on Windows. Some tests may hardcode
   `tcp://` strings — update to use `DEFAULT_PUB_ADDR` /
   `DEFAULT_CMD_ADDR` imports.

---

## Stage 3 — Verification (REQUIRED before commit)

```bash
# Full subtree
.venv/bin/pytest tests/ --timeout=60 -q
# Expected: pass (baseline ~1785 + new tests)

# Targeted
.venv/bin/pytest tests/core/test_zmq_transport_defaults.py -v
.venv/bin/pytest tests/core/test_zmq_bridge.py \
                 tests/core/test_zmq_subprocess.py \
                 tests/gui/test_zmq_client_data_flow_watchdog.py -v
# Expected: pass

# Ruff
.venv/bin/ruff check src/cryodaq/core/zmq_bridge.py \
                    src/cryodaq/core/zmq_subprocess.py \
                    src/cryodaq/gui/zmq_client.py \
                    tools/diag_zmq_*.py
# Expected: clean

# Diag tool soak — CRITICAL.
# Start engine in background:
pkill -9 -f cryodaq; sleep 2
rm -f data/.engine.lock data/.launcher.lock /tmp/cryodaq-*.sock
CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock > /tmp/engine_iv7.log 2>&1 &
ENGINE_PID=$!; sleep 3

# Test 1: idle hypothesis (sparse commands)
.venv/bin/python tools/diag_zmq_idle_hypothesis.py 2>&1 \
  | tee /tmp/diag_iv7_idle.log
# EXPECTED: all 3 phases pass, 0 failures

# Test 2: extended soak
.venv/bin/python tools/diag_zmq_bridge_extended.py 2>&1 \
  | tee /tmp/diag_iv7_extended.log
# EXPECTED: 180s, 0 failures

kill $ENGINE_PID 2>/dev/null
```

**If either diag tool shows ANY failure:** STOP. Do NOT commit. Surface
to architect — B1 is NOT at TCP-loopback layer, next strategy needed.

**If both diag tools pass 0-failure:** proceed to commit. Also run
on Ubuntu lab PC before tagging 0.34.0 — same expectation.

---

## Stage 4 — Commit + push

Single commit. Message template:

```
zmq: switch loopback transport from tcp:// to ipc:// (B1 fix)

Resolves bug B1: GUI command channel silently dies 30-120s after
bridge startup on both macOS (stochastic) and Ubuntu (deterministic
~120s). Prior hypotheses disproved:

- Idle TCP reaping: Linux default tcp_keepalive_time=7200s rules
  out kernel-level reaping. Active polling never idled long enough
  anyway.
- Shared REQ socket state accumulation: IV.6 (be51a24) replaced
  shared with per-command ephemeral REQ. Unit tests green. Diag
  tools reproduced B1 unchanged. Hypothesis falsified.

Remaining candidate was the TCP-loopback layer itself (libzmq
handling, pyzmq asyncio integration, kernel loopback state under
rapid connect/disconnect churn). ipc:// via Unix domain sockets
bypasses TCP entirely.

Changes:
- src/cryodaq/core/zmq_bridge.py: platform-conditional defaults.
  sys.platform == 'win32' → tcp://127.0.0.1:5555/5556 (unchanged).
  Everything else → ipc:///tmp/cryodaq-pub.sock,
  ipc:///tmp/cryodaq-cmd.sock.
- src/cryodaq/core/zmq_subprocess.py: import the new defaults.
- src/cryodaq/gui/zmq_client.py: same.
- tools/diag_zmq_*.py: import the new defaults so diag tools
  exercise the real transport.
- _prepare_ipc_path() helper: unlink stale socket file before
  bind. Covers crash-recovery case (ipc socket files persist
  on ungraceful exit; bind refuses to overwrite).

Verification (macOS + Ubuntu, CRYODAQ_MOCK=1):
- diag_zmq_idle_hypothesis.py: all 3 phases 0 failures
- diag_zmq_bridge_extended.py: 180s soak, 0 failures
- Full pytest subtree: {passed}/{total}

Windows: still on tcp:// — ipc:// semantics differ on Windows
(named pipes, not Unix domain sockets). Not current lab target;
will revisit if Windows deployment becomes a requirement.

Companion IV.6 work (be51a24) kept in master as defence-in-depth:
ephemeral REQ + launcher command-channel watchdog match ZeroMQ
Guide ch.4 canonical reliable req-reply pattern, independent of
whether the transport fix alone resolves B1.
```

```bash
git push origin master
```

---

## Stage 5 — Codex self-review

Invoke `/codex` with `--model gpt-5.4 --reasoning high`. Prompt body
opens with:

```
Model: gpt-5.4
Reasoning effort: high

Review commit {SHA}. Context:
- CC_PROMPT_IV_7_IPC_TRANSPORT.md (this spec)
- docs/bug_B1_zmq_idle_death_handoff.md (full B1 evidence)
- HANDOFF_2026-04-20_GLM.md (today's session context)

Specifically verify:

1. ipc:// socket path cleanup logic is crash-safe (stale socket file
   after ungraceful exit does not prevent fresh bind).
2. No race conditions between engine bind(unlink + bind) and any
   concurrent subprocess trying to connect. Order-of-operations safe.
3. File permissions on /tmp/cryodaq-*.sock default are appropriate
   for single-user lab PC setup (Unix 0600 typical via umask).
4. Tests cover both path prefixes and stale-cleanup.
5. No accidentally-hardcoded tcp://127.0.0.1 remaining anywhere in
   the transport path. grep the whole src tree.
6. sys.platform branching captures all non-Windows cases correctly
   (Linux, Darwin, and any WSL edge cases).

Verdict: PASS / FAIL per standard format.
```

Autonomous amend cycles up to 3. STOP-to-architect if:
- Codex finds a security/permissions concern (file-based sockets
  have different access semantics than TCP loopback).
- Codex finds the change breaks Windows path (we said it keeps
  tcp:// on Windows, so this is unexpected).
- 3 amends without PASS.

---

## Stage 6 — ROADMAP update after PASS

`ROADMAP.md` Known Broken → B1:
- Status `🔧` → `✅` resolved at {SHA}.
- Add subsection "IV.7 resolution" recording the hypothesis tested
  (ipc:// bypasses TCP loopback layer) and verification outcome.
- Move the B1 entry out of "Known broken" into a historical "Fixed
  in 0.34.0" subsection if the section structure has one; otherwise
  leave in place with status ✅.

`CHANGELOG.md` new entry `## [0.34.0] — 2026-04-{DD}` with
sections for this release. Include B1 resolution as `### Fixed`
lead item.

Then tag:

```bash
git tag -a v0.34.0 -m "CryoDAQ 0.34.0: B1 resolved via ipc:// transport"
git push origin v0.34.0
```

---

## Out of scope

**NOT included in IV.7:**

- In-process threading (subprocess removal) — fallback only if
  ipc:// ALSO fails.
- Full pyzmq / libzmq replacement.
- ZMTP protocol-level heartbeats (not needed with working transport).
- Thyracont `_try_v1_probe` checksum consistency — separate mini-fix.
- `alarm_v2` KeyError `'threshold'` for `cooldown_stall` — separate
  config/code fix.
- F20 alarm management UI — separate feature.
- Any `config/channels.yaml` edits — architect's domain.
- B1 doc filename rename — leave `docs/bug_B1_zmq_idle_death_handoff.md`
  in place (history record).

---

## Hard rules

1. NEVER delete files in repo. Zero exceptions.
2. `/codex` is a slash command.
3. Model flags BOTH places: inline `--model gpt-5.4 --reasoning high`
   AND first two lines of prompt body `Model: gpt-5.4 /
   Reasoning effort: high`.
4. Diag tool verification is non-negotiable Stage 3 gate. No commit
   before both tools show 0 failures.
5. Single commit. If Codex requires amend, amend; do not split.
6. After Codex PASS: ROADMAP update + CHANGELOG entry in same
   commit OR immediate follow-up commit. Then tag 0.34.0.

---

## Completion criteria

- [ ] Stage 1 implementation complete (platform-conditional transport,
      stale socket cleanup).
- [ ] Stage 2 tests written.
- [ ] Stage 3 verification: both diag tools pass 0-failure.
- [ ] Full pytest subtree pass (baseline ~1785 + new tests).
- [ ] Single commit pushed to origin/master.
- [ ] Codex `/codex` review PASS within 3 amend cycles.
- [ ] ROADMAP.md B1 entry → ✅.
- [ ] CHANGELOG.md 0.34.0 entry created.
- [ ] Ubuntu lab PC smoke verification — real launcher runs 5+ min
      without REP timeout warnings (architect verifies on Vladimir's
      hardware).
- [ ] Tag `v0.34.0` created and pushed.

---

*Architect: Claude Opus 4.7 (web), 2026-04-20 evening, handing off
to GLM-5.1 via CCR. ETA: ~1-2 h autonomous including Codex review.*
