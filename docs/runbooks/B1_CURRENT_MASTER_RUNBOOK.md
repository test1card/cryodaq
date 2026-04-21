# Runbook - B1 current-master truth recovery

## Purpose

Use this runbook to capture the current-master B1 behavior without changing transport, launcher, engine, or safety configuration. The goal is to record the command-channel shape on the code that is actually checked out, not to change the diagnosis.

The canonical capture tool is `tools/diag_zmq_b1_capture.py`. It runs three phases in order:

1. Sequential command burst
2. Concurrent command burst
3. 1 Hz soak

Those phases are implemented through the shared helpers in `tools/_b1_diagnostics.py` so the CLI and any future tooling stay aligned.

## Preconditions

- Start the engine first.
- Use the same environment you want to diagnose.
- Do not rely on bridge startup or heartbeats as proof that B1 is gone; this incident is about command replies.

Typical mock-engine setup:

```bash
CRYODAQ_MOCK=1 /Users/vladimir/Projects/cryodaq/.venv/bin/cryodaq-engine --mock
```

## Capture

Run the canonical capture from the project venv:

```bash
/Users/vladimir/Projects/cryodaq/.venv/bin/python -m tools.diag_zmq_b1_capture
```

Default capture parameters:

- 5 sequential commands
- 10 concurrent commands
- 60 second soak
- 1 second interval between soak commands

If you need a shorter evidence pass while iterating, keep the sequence structure intact and only shorten the counts or soak window for the local transcript.

## What To Look For

- `sequential` lines should show the first burst and their reply summaries.
- `concurrent` lines should show the parallel burst and whether one command starts failing earlier than the others.
- `soak` lines should show the long-run command behavior. This is the phase that usually exposes the current-master B1 shape.
- The final `summary` section counts total, ok, failed, slow, and the maximum elapsed time for each phase.

Interpretation:

- If the soak starts returning `ok=False` or timeouts after a period of otherwise healthy replies, record the first failing phase and index.
- If all three phases stay clean on a supposed current-master reproduction, treat that as environment-specific until you have reproduced the same result twice.
- A healthy data plane does not clear B1 by itself. This runbook is only about the command channel.

## Notes For Evidence Capture

- Save the full terminal transcript, not just the final summary.
- Keep the CLI defaults unless you are explicitly creating a shorter operator note.
- Use the same runbook command for future regressions so the transcript shape stays comparable.

