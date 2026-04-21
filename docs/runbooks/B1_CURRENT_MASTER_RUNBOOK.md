# B1 Current-Master Runbook

This runbook exists to gather runtime truth on current `master` before any
IV.7 transport decision or `0.34.0` release discussion.

## Baseline capture

Run these first and paste their output into the run note:

```bash
git rev-parse HEAD
git status --short
```

Expected:
- `HEAD` is the commit under test
- only intentional local artifacts are dirty

## Engine startup

Mock path:

```bash
CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock
```

Real lab path:

```bash
./start.sh
```

## Canonical capture

```bash
.venv/bin/python tools/diag_zmq_b1_capture.py \
  --duration 180 \
  --interval 1.0 \
  --output artifacts/diagnostics/b1-current-master.jsonl
```

## Corroboration tools

```bash
.venv/bin/python tools/diag_zmq_bridge.py
.venv/bin/python tools/diag_zmq_bridge_extended.py
.venv/bin/python tools/diag_zmq_idle_hypothesis.py
```

## Result classification

- If `bridge_reply` fails while `direct_reply` stays healthy: bridge/subprocess path is still the primary suspect.
- If `bridge_reply` and `direct_reply` fail together: engine REP path or lower transport is still implicated; do not claim the bridge is uniquely at fault.
- If neither path fails during the full 180 s run: do not declare B1 fixed. Repeat on Ubuntu lab hardware before changing roadmap status.

## Explicit no-go conclusions

- Do not claim IV.6 closed B1.
- Do not treat IV.7 as approved because the runbook exists.
- Do not say `0.34.0` is ready unless B1 is closed by fresh runtime evidence.
