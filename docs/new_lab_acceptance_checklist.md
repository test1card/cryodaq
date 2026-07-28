---
title: Hardware acceptance checklist for a new laboratory
audience: coding agent preparing the run, engineer signing it off
scope: instantiable acceptance template for a fork on different cryogenic hardware
status: canonical
last_updated: 2026-07-26
companion: docs/new_lab_adaptation.md, docs/lab_verification_checklist.md, docs/instruments.md
---

# Hardware acceptance checklist for a new laboratory

`docs/lab_verification_checklist.md` is **not** a generic checklist. It is
*this* stand's instance: three LakeShore 218S controllers, a Thyracont gauge, a
Keithley 2604B with its TSP watchdog, on a specific Ubuntu lab PC. Its A8a–A8e
gates test the Keithley's nonce-bound OFF grammar; its §3 tests the LakeShore
KRDG/SRDG fallback; its §1 pins a SQLite version range for one machine. Reusing
it verbatim on different hardware produces a checklist-shaped artifact that
verifies nothing about the hardware actually present.

This document is the **template** a fork instantiates. Copy it into your fork,
fill in the hardware column, delete rows that genuinely do not apply (recording
why), and add rows for hardware classes not listed. The result — not this
template — is your acceptance record.

Complete `docs/new_lab_adaptation.md` first. This checklist assumes the
instruments, descriptor manifest, coverage table and thresholds already exist.

## How to use this template

**Every row is NOT PASSED until its evidence exists.** That is the fail-closed
default and it is not a formality: an open gate that is reported closed is the
single most damaging outcome of an adaptation.

For each row record:

| Field | Meaning |
|---|---|
| Gate ID | stable identifier you can cite in a report |
| Applies to | the exact instrument / channel / actuator, by `name` and `channel_id` |
| Procedure | what is physically done, in enough detail to repeat |
| Pass criterion | decidable before the run, not chosen afterwards |
| Evidence | log excerpt, measured value, photograph, instrument readout — with a date |
| Verdict | PASSED / NOT PASSED / NOT APPLICABLE (+ reason) |
| Signed | the person accountable for the physical judgement |

Rules that hold for every row:

- **Software simulation, mocks and loopback do not satisfy a physical gate.**
  A green `cryodaq-engine --mock` is a configuration result, never a hardware
  result (`AGENTS.md`, "Mission and safety boundary").
- **An instrument's own status readback is diagnostic, not an independent
  oracle.** Where a gate asserts absence of energy or absence of motion, the
  confirming measurement must come from something other than the device under
  test.
- **Record the measured value, not the nominal one.** "Trip expected at 5 s" is
  a design intent; "tripped at 6.1 s" is evidence.
- **A gate whose evidence has expired is open again.** Give safety-relevant
  gates an explicit validity period and re-run them after any change to the
  hardware, the wiring, the thresholds or the driver.

## G0 — Preconditions (before any instrument is connected)

| Gate | What it establishes |
|---|---|
| **G0.1 Runtime** | The interpreter, dependencies and platform match what you will run in production. `docs/deployment.md` is the installation authority. |
| **G0.2 Storage integrity** | The SQLite build in use is not in a range with known WAL-reset behaviour. `docs/lab_verification_checklist.md` §1 shows how this stand pins it; **your** platform needs its own equivalent check, verified against the sqlite3 implementation the engine really imports. |
| **G0.3 Disk headroom** | Free space exceeds the alarm thresholds you set, with margin for the longest planned run. |
| **G0.4 Configuration** | `docs/new_lab_adaptation.md` §7 items 1–3 are green, and 4–5 are written and signed. |

## G1 — Per passive instrument

Instantiate this block **once per instrument** in
`config/instruments.local.yaml` that is not a hazardous source.

| Gate | Procedure | Pass criterion |
|---|---|---|
| **G1.1 Identity** | Connect and read the instrument's identification response. | The engine binds the intended physical device, not another unit on the same bus. Serial number recorded. |
| **G1.2 Channel mapping** | For each channel, apply a *distinguishable* physical stimulus — warm one sensor by hand, open one gauge line — one channel at a time. | The value that moves is the one the manifest says it should be. This is the only real test that `emitted_channel` → `channel_id` is correct; a manifest can be internally consistent and wired to the wrong sensor. |
| **G1.3 Units and sign** | Compare against an independent reading of the same quantity. | Magnitude and sign are physically plausible; the unit in the descriptor is the unit the instrument actually reports. |
| **G1.4 Timing** | Observe over at least one hour. | Actual update rate is at or better than the configured `poll_interval_s`; no channel is silently slower than the staleness thresholds you set. |
| **G1.5 Disconnection** | Unplug the transport during acquisition. | The channel resolves visibly to stale/disconnected. It must **not** hold its last value looking healthy, and must not report an optimistic default. |
| **G1.6 Recovery** | Reconnect. | Acquisition resumes without an engine restart, and the recovery is visible in the log. |
| **G1.7 Out-of-range** | Where safe, drive one channel outside its measurement range (disconnected sensor lead is usually enough). | The reading is reported as a fault/overrange state, not as a plausible number. |

## G2 — Descriptor and persistence

| Gate | Procedure | Pass criterion |
|---|---|---|
| **G2.1 Every channel persists** | Run acquisition against real hardware for a bounded period. Query the stored rows per `channel_id`. | Every channel expected in steady state has rows. A channel with zero rows is either a wiring fault or a binding fault — find out which. |
| **G2.2 Raw channels persist** | Run one calibration acquisition session. | The `_raw` channels persist. If they do not, the manifest is missing them (`docs/new_lab_adaptation.md` §3.3). |
| **G2.3 Identity survives the round trip** | Read a stored row back and render a report over the same interval. | Instrument, channel and unit agree with the descriptor at every stage. |
| **G2.4 Rotation** | Cross a daily file boundary. | No channel is lost or renamed across rotation. |

## G3 — Calibration on real hardware

Only for channels you intend to run calibrated. Fill in per channel.

| Gate | Procedure | Pass criterion |
|---|---|---|
| **G3.1 Reference traceability** | Record the reference thermometer's certificate identifier and date. | In date, and its uncertainty is small compared with the band the calibrated channel will be alarmed against. |
| **G3.2 Agreement in range** | Compare curve output against the reference across the operating range, including transients. | Residuals within the uncertainty claimed in `docs/new_lab_adaptation.md` §4.2 criterion 3. |
| **G3.3 Out-of-range fallback** | Drive the sensor outside the calibrated span. | The published value falls back to the instrument's native reading and `dT/dt` stays alive. A frozen value at the span boundary is a **failure**: it blinds every rate-based safety check. |
| **G3.4 Enable is deliberate** | Inspect the runtime resolution for the channel. | It reports `effective_mode: on` only after the engineer signed the enable, and reports an explicit reason whenever it is off. |

## G4 — Alarms and interlocks against real behaviour

| Gate | Procedure | Pass criterion |
|---|---|---|
| **G4.1 Every alarm is reachable** | For each alarm, identify how its condition could physically arise. | No alarm exists whose condition cannot occur on this hardware — such an alarm is decoration. Either remove it or record why it is retained. |
| **G4.2 Each protective trip fires** | Exercise each Class A threshold (`docs/new_lab_adaptation.md` §6.1) by a **safe** route: a bench substitution, a dummy load, a disconnected sensor — never by approaching the real hazard. | It trips, at the measured value and within the measured latency you recorded during derivation. |
| **G4.3 No false trip in normal operation** | One full normal cycle. | No protective trip fires. A Class A threshold that fires during ordinary operation is wrong and must be re-derived, not silenced. |
| **G4.4 Layer ordering holds** | Drive one quantity slowly past alarm, then interlock. | Alarm fires strictly before interlock. |
| **G4.5 Operator wording is true** | Read each alarm message as an operator would. | Every message names a situation that can occur here and an action that is possible here, in the operators' language. |
| **G4.6 Annunciation reaches the operator** | Trigger one alarm of each notification class. | It arrives on every configured channel. |

## G5 — Safety supervision

| Gate | Procedure | Pass criterion |
|---|---|---|
| **G5.1 Stale critical channel** | Interrupt one `safety_critical_input` channel during operation. | A fault is latched within the configured stale timeout. |
| **G5.2 Fault latches** | After G5.1. | The fault does **not** self-clear when the channel returns. Operator acknowledgement is required. |
| **G5.3 Recovery is gated** | Attempt to resume immediately after acknowledging. | The configured re-arm cooldown is enforced and the required reason is demanded. |
| **G5.4 Disk exhaustion** | Use a **dedicated disposable test volume** (not the production data volume and never the OS volume), with a recorded fixed capacity. Point only the test engine's data directory at it. Reserve **at least 256 MiB** that the fill procedure never consumes; abort immediately if the next 1-MiB fill step would enter that reserve, if the path is not the dedicated volume, or if the engine writes anywhere else. Set the test's critical-free-space threshold above the 256-MiB reserve, then fill in 1-MiB steps only until free space is below that configured threshold. Stop the engine, remove the fill files, delete the test database/volume, and record free space after cleanup. | Persistence degrades safely, the fault is latched, and no reading is published that was not persisted: the scheduler returns on write failure/disk-full before `DataBroker.publish_batch()` (`src/cryodaq/core/scheduler.py:1320-1408`). The evidence records the dedicated-volume path, capacity, configured threshold, lowest free-space value, abort/cleanup result, and the persistence-failure log. |

## G6 — Hazardous source

**TODO — not written, because the path it would document does not work yet.**

If your stand uses the same Keithley 2604B this fork was built around, use
`docs/lab_verification_checklist.md` §4 (A8-0 … A8e) — that is the real gate
set for that SMU, and several of its own rows are recorded there as still
open.

If your stand uses **any other** actuator, stop. The driver registry keeps an
explicit roster of reviewed bindings
(`REVIEWED_SOURCE_BINDINGS`, `src/cryodaq/drivers/registry.py:133-149`) and a
second rostered binding is admitted by the loader, but nothing downstream of
the loader is vendor-neutral yet: `SafetyManager` is internally Keithley-shaped
and its global OFF iterates a hardcoded `("smua", "smub")` pair
(`src/cryodaq/core/safety_manager.py:151`, `:2203`, `:2434`, `:2605`), and the
binding's `adapter_module` / `adapter_class` / `contract_version` fields
(`src/cryodaq/drivers/registry.py:116-130`) remain the declared
adapter-contract identity, but the current loader does not dispatch through
them. A rostered actuator therefore reaches a supervisor that cannot drive it. See
`docs/new_lab_adaptation.md` §8.

Treat every hazardous-source gate as **NOT PASSED** and engineer-led. §4 of
the existing checklist is still worth reading as a *model* of the shape such
gates take — independent measurement of the final element, host-death
behaviour, measured trip time, common-cause analysis — but it is not a
procedure for your hardware.

If an actuator accepts an OFF command but supplies no evidence that it is
physically off, record the result exactly as **"OFF commanded, unverified"**.
That is a lower disclosed capability, not proof of a safe physical state; it
does not by itself require the lab to add a compensating external final
element. The generic hazardous-source adaptation contract is still not
implemented, so this disclosure does not close G6.

Do not energize a heater inside a cryostat to close any gate in this document.

## G7 — Endurance

| Gate | Procedure | Pass criterion |
|---|---|---|
| **G7.1 Soak** | Run the full stack against real instruments for at least one intended experiment duration. | No memory growth trend, no unexplained gap in any channel, no restart. |
| **G7.2 Full cycle** | One complete operating cycle end to end. | Every phase transition behaves as configured; the archive and the report for that cycle are complete. |
| **G7.3 Restart mid-run** | Record the configured maximum poll interval `P` and the last committed receipt before the stop. Stop and restart the engine, using a stopwatch; obtain the first new committed receipt within **60 s** of the stop command. The acknowledged in-flight window is the single measured restart interval, bounded per channel by **60 s + 2P** between its last pre-stop and first post-restart persisted timestamps. Query both receipt batches and compare each ordered entry identity `(instrument_id, channel_id, timestamp)` with the stored rows. `commit_revision` is per writer, so record it inside each run but do not compare its value across the restart. | `CommittedBatchReceipt` carries entries and a per-writer `commit_revision` (`src/cryodaq/storage/sqlite_writer.py:700-724`, `:7227-7249`); every entry in the last pre-stop receipt and first post-restart receipt must persist exactly once. Every channel's measured timestamp gap must be at or below `60 s + 2P`; a longer or unexplained gap, duplicate, reordered row, or missing receipt leaves G7.3 **NOT PASSED**. |

## G8 — Platform and packaging

| Gate | What it establishes |
|---|---|
| **G8.1 Target OS** | Everything above was verified on the OS and machine that will run production, not on a developer workstation. |
| **G8.2 Packaged build** | If you ship a frozen build, the gates were re-run against **that build**. A source-mode pass does not transfer. |
| **G8.3 Unattended start** | The production launch path (shortcut, service, whatever you use) reaches a working state without a developer present. |

## Closing the record

The adaptation may be declared accepted only when every row is PASSED or
explicitly NOT APPLICABLE with a reason, G6 has been addressed by whatever
procedure your engineer defines, and the record is signed and dated.

Report open gates as open. A gate left open is a known limit on where the
system may be used; a gate reported closed without its evidence is a false
statement about a cryostat.
