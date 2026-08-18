# Source-mode mock-stack soak

## Purpose

This runner qualifies the Linux source stack. The stack contains the launcher,
mock engine, GUI ZMQ bridge, assistant child, and H3 coordinator. The runner is
separate from `scripts/soak_mock_engine.py`. The engine-only nightly lane does
not supply whole-stack evidence.

The integrated runner supports the reviewed `short`, `12h`, `72h`, and `168h`
profiles. It owns process observation, fault injection, periodic artifacts, and
bounded cleanup. It rejects Windows and non-Linux POSIX hosts before it creates
an evidence bundle.

Run the qualification only from an exact clean SHA under the worktree's
`.venv/bin/python`:

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m scripts.soak_mock_stack \
  --profile short --evidence-dir artifacts/mock-stack-soak/preflight
```

There is no caller-supplied prerequisite or PASS option. A profile run must use
an exact clean SHA. Each duration gate stays open until its real Ubuntu 22.04
run completes with a sealed PASS.

Run a long profile only on the laboratory qualification host. Use one of the
reviewed names: `12h`, `72h`, or `168h`. For example:

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m scripts.soak_mock_stack \
  --profile 168h --evidence-dir artifacts/mock-stack-soak/168h
```

## Profiles

The short profile uses a 5-second sample interval and a 7.5-second maximum gap.
The long profiles use a 30-second sample interval and a 45-second maximum gap.

These are the ordinary inter-sample cadence bounds. Around each scheduled
injected fault there is one deliberate exception, because an injected fault
legitimately interrupts the observer: the allowlisted `SIGTERM` is followed by a
role restart and recovery, so the single sampling gap that spans a scheduled
fault may exceed the cadence. The validator exempts a gap only when a scheduled
fault time lies inside it and both edges stay within their bounds —
`max_cadence_gap_s` before the fault and `RECOVERY_CEILING_S` (60 seconds)
after it. The widest exempted gap is therefore `max_cadence_gap_s + 60`
seconds: 67.5 seconds for `short`, 105 seconds for `12h`, `72h`, and `168h`.
Each scheduled fault earns at most one exempt gap, so the worst-case unvalidated
observer time per profile, measured from the profile definitions in
`scripts/soak_mock_stack.py`, is: `short` 2 faults x 67.5 s = 135 s
(2.25 minutes); `12h` 6 faults x 105 s = 630 s (10.5 minutes); `72h` 10 faults
x 105 s = 1050 s (17.5 minutes); `168h` 18 faults x 105 s = 1890 s (31.5
minutes of the 168-hour run, 0.31%). Every gap that does not span a scheduled
fault must still satisfy the stated cadence bound, and no other relaxation
exists.
The final validator rejects a
sample file above 64 MiB or 25,000 records. Identity is `(pid, OS start time)`,
so PID reuse cannot select an unrelated process. Fault injection must re-check
that identity immediately
before sending the allowlisted `SIGTERM` through
`observer.signal_exact_identity/v1`; another signal, injection method,
PID-only selector, or global process name is not qualification evidence.

At 180 seconds the short run records and commits one healthy four-role
baseline sample. Sampling precedes injection, and the first engine fault is at
185 seconds. A dead-child or recovery-allocation sample therefore cannot
silently become the baseline.

| Profile | Duration | Warm-up | Engine faults | Assistant faults | RSS slope | Descriptor slope |
|---|---:|---:|---|---|---:|---:|
| `short` | 15 min | 3 min | 3 min 5 s | 5 min | screen only | screen only |
| `12h` | 12 h | 10 min | 1, 4, 8 h | 2, 6, 10 h | < 4 MiB/h | <= 1/h |
| `72h` | 72 h | 10 min | 1, 12, 24, 48, 60 h | 2, 18, 36, 54, 66 h | < 1 MiB/h | <= 0.25/h |
| `168h` | 168 h | 10 min | 1, 12, 24, 48, 60, 84, 108, 132, 156 h | 2, 18, 36, 54, 66, 90, 114, 138, 162 h | < 1 MiB/h | <= 0.25/h |

Every process replacement must have a new PID/start identity. Engine recovery
also requires bridge data readiness; assistant recovery requires a strictly
newer H3 health heartbeat/owner. Each recovery has a 60-second ceiling. Final
graceful shutdown has a 20-second ceiling and zero recorded live descendants.

Across 12/72/168-hour post-warm-up samples, robust fitted aggregate RSS growth must
remain below 50 MiB. The slope estimator deterministically keeps at most 257
evenly spaced points, including both endpoints, and computes at most 32,896
pairwise slopes. A 72-hour 30-second series therefore cannot trigger an
unbounded quadratic allocation. Process count must return to one launcher, one
engine, one positively identified bridge, and one assistant after recovery.

Samples carry per-role restart epochs. Missing descriptor/handle observations
fail qualification. Per-role descriptor, thread, and RSS envelopes are checked
within every epoch and at the final boundary. Profile RSS and descriptor slopes
are evaluated independently for every role and stable epoch, so one child's
leak cannot be hidden by another child's decline. Elapsed times and counters must be finite
and non-negative. Time must be strictly monotonic. The maximum cadence gap is
7.5 seconds for `short` and 45 seconds for long profiles, except the single
gap spanning a scheduled injected fault described in the recovery-window
exemption above. The series must cover
startup through the profile duration.

## Evidence contract

The evidence bundle is governed by a typed, fail-closed state machine:

```text
INITIAL_FAIL -> MANIFEST_FINALIZED -> PREREQUISITES_VERIFIED -> RUNNING
  -> SHUTDOWN_VERIFIED -> EVIDENCE_SEALED -> VALIDATED -> PASS
```

An invalid transition or failed validator terminates the run as `FAIL`.
Every public evidence mutation has one exception-total transaction boundary:
wrong containers, missing keys, non-JSON values, non-finite or oversized
numbers, serialization failures, and write failures all transition to the same
typed terminal `FAIL`. The first terminal summary is retained; repair attempts
and retries cannot advance the object.
The sole publication exception is loss of the pinned directory capability
itself. If its descriptor is closed or its integer is reused for a different
directory, the in-memory state becomes terminal `FAIL`,
`terminal_summary_available` is false, and the operation raises the typed
`EvidenceCapabilityError`. No replacement-path or mismatched-descriptor write
is attempted, so the last owned on-disk summary honestly remains the initial
`FAIL/incomplete` record rather than claiming a terminal update that could not
be provenance-bound.
Only the integrated runner can reach `EVIDENCE_SEALED` or `PASS`; it injects an
internal execution-produced exact-six result capability. A public mapping,
JSON/result file, asserted exit code, or arbitrary
command such as `true` is never acceptance authority. The foundation's public
`write_exact_six_result()` entry point therefore terminates the run as `FAIL`;
it exists only to make the rejection boundary explicit until the runner lands.
There is no caller-supplied PASS flag: once that runner exists,
`finish_pass()` will reread the sealed bytes,
recompute their ledger, compare all artifact hashes twice, and may publish
PASS only from `EVIDENCE_SEALED`. The completed runner writes:

- `manifest.json`: schema, clean Git SHA/dirty state, OS/Python, exact profile,
  source command, frozen thresholds, log allowlist, and capture policy;
- `prerequisites.json`: same-clean-SHA exact-six PASS plus locked observer,
  reviewed local-only publisher, and positive bridge-identity capability;
- `exact-six-result.json`: immutable same-SHA result for the canonical
  `.venv/bin/python -m pytest -q
  tests/integration/test_periodic_png_multiprocess.py` command and frozen test
  identity, bound into `prerequisites.json` by SHA-256;
- `samples.jsonl`: monotonic/wall time and per-identity plus aggregate RSS,
  threads, file descriptors or Windows handles;
- `faults.jsonl`: exact immediately preceding and rechecked pre-signal
  identity, allowlisted signal/injection method, replacement identity,
  readiness/health observation, and elapsed recovery;
- `shutdown.json`, `log_capture.json`, and captured logs: typed shutdown,
  identity, allowlist, and zero-unexpected-fatal-log evidence;
- `ledger.json`: canonical typed acceptance ledger with byte length and SHA-256
  for every evidence artifact;
- atomic `summary.json`: initial/terminal FAIL or the final PASS, including the
  manifest hash and canonical ledger hash.

Every run uses an empty unique evidence directory and immediately writes an
atomic `FAIL/incomplete` summary. SIGINT and SIGTERM converge on the same
idempotent cleanup/finalization path during setup, sampling, injection,
recovery, or shutdown. PASS may replace the initial FAIL only after complete
same-SHA prerequisite, duration/cadence/four-role resource, exact
fault/recovery, log, secrecy, bounded shutdown, and global exact-identity
survivor validation;
reparenting cannot hide a recorded child and PID reuse does not create a false
survivor.

At construction the evidence object opens that unique directory once with
`O_DIRECTORY | O_NOFOLLOW`, retains its device/inode identity, and treats the
descriptor as the run's directory capability. All artifact opens, appends,
atomic replacements, enumeration, quarantine, and removal are relative to that
descriptor. The pathname must still name the pinned directory before every
public mutation and again before state advance, seal, or PASS. If the whole
directory is renamed and its old pathname is replaced by a directory or
symlink, the run terminates as `FAIL`; the terminal summary is written only to
the pinned original directory and the replacement target is never read or
modified.

`Evidence` is an explicit context manager and also exposes idempotent
`close()`. Closing a live, valid capability before normal completion first
settles a terminal lifecycle FAIL in the owned directory and then releases the
descriptor. After close, every public mutator and finalizer raises
`EvidenceUnavailableError` without file I/O; a second close is a no-op. The GC
fallback follows the same settle-then-close rule, but callers and the CLI use
explicit close ownership. If capability identity has already been lost,
`close()` marks the object closed without writing through or closing a reused
external descriptor.

Fault acceptance is correlated against the sample history rather than trusted
as a standalone assertion. Launcher and bridge epochs may not change. Every
engine/assistant epoch transition must match exactly one scheduled fault, the
old identity must be the immediately preceding sample, and the replacement
epoch/identity may first appear only after injection and within the measured
recovery ceiling. Phantom, intermediate, duplicated, or unscheduled restarts
fail qualification.

The manifest and named log artifacts are write-once. Public mutators reject
calls after shutdown, seal, or PASS, and every sealed artifact is hashed. Any
byte change before PASS makes the second ledger reconstruction fail closed.
The evidence directory is a closed flat artifact tree: directories, symlinks,
device/socket entries, and unregistered regular files are rejected. Every
accepted qualification artifact is scanned and included in the artifact
ledger; `summary.json` and `ledger.json` are the only generated authority
outputs outside that input set.

Rejected non-regular entries are atomically detached and removed without
reading or following them; an external symlink target is never opened, copied,
or modified. Artifact scan, sanitization, log parsing, and hashing use
descriptor-based no-follow opens and require device/inode/size/mtime continuity
through EOF and the final pathname check. A path replacement is removed or
rejected within the pinned evidence directory; quarantine never follows it.
Whole-root replacement is rejected by pathname-to-capability identity checks,
not accepted as a new evidence authority. This
prevents a nested, linked, or post-topology-swap secret from surviving inside a
failed bundle. Any validation, parsing, topology, seal, or final PASS exception
atomically writes a terminal typed `FAIL` summary. The same evidence object
cannot be repaired and retried after that boundary.

Captured metadata is positively allowlisted; environment values are never
recorded. JSON/log/URL/argv text redacts bearer headers, credential query and
assignment forms, Telegram tokens, and adjacent secret-option values. A
separate detector scans every final artifact before PASS. Detector hits are
atomically redacted or replaced by a restrictive-permission quarantine stub;
the original/sanitized hashes and finding class are recorded and the run still
terminates as FAIL, so raw secret material is not retained. Missing
classification, skipped
faults, stale H3 health, duplicate children, ambiguous identity, fatal logs,
or missing final summary are failures.

Before each qualification run, execute and record the repository's exact-six-
node multiprocess election/failover test on the same clean SHA. The soak
assistant fault checks launcher restart and leader reacquisition; it does not
replace simultaneous-contender evidence.

## Honest gate boundary

A PASS proves source-mode, no-hardware integrated endurance only for the
named OS and SHA. It does not prove the frozen Windows ONEDIR launcher tree,
hidden-child sentinel/Job Object behavior under the real launcher, Unicode
installed paths, or any VISA/GPIB/serial instrument and watchdog behavior.

Real Windows ONEDIR evidence and physical dummy-load/final-element laboratory
procedures remain separate open gates. Never close them from this harness.
