---
title: Adapting CryoDAQ to a new laboratory
audience: coding agent performing the adaptation, plus the engineer who signs it off
scope: config-level adaptation of a fork to different cryogenic hardware
status: canonical
last_updated: 2026-07-26
companion: docs/new_lab_acceptance_checklist.md, docs/instruments.md, docs/alarms_tuning_guide.md, docs/lab_verification_checklist.md
---

# Adapting CryoDAQ to a new laboratory

This document is the adaptation path for a fork of CryoDAQ that must run on
different cryogenic hardware. It is written to be executed by a coding agent
with no prior context about this repository, and it is deliberately made of
decidable steps: every step states what to change, what enforces it, and how
you know it is **complete** rather than merely attempted.

Read `AGENTS.md` first — it is the governing contract and it wins over this
file on safety, evidence, and publication questions. `docs/instruments.md`
covers the physical wiring and per-instrument connection detail; this document
covers what has to be *declared* so the software is not silently blind to your
hardware.

## 0. What an agent may decide, and what it may not

| Decision | Owner |
|---|---|
| Which instruments exist, their addresses, their channel labels | agent, from the lab's wiring record |
| Descriptor identity, units, roles, display grouping | agent |
| Which channels are `safety_critical_input` | **engineer** — a physical claim about what is bolted where |
| Numeric alarm / interlock thresholds | **engineer** — see §6; the agent derives candidates and records the source, the engineer signs |
| Whether a calibration curve may be applied at runtime | **engineer** — see §4 |
| Adding a hazardous actuator (a driver with source authority) | **nobody — the path does not work yet.** Not covered here; see §8 before you try |

Where a step below says **ESCALATE**, the agent must stop and put the question
to a human, with the evidence it has gathered. Producing a plausible number is
not the same as deriving one, and this system energizes heaters inside a
cryostat.

## 1. Which files are tracked policy and which are machine-local

This split is the first thing to get right, because it decides what a fork
commits and what stays on one PC.

**Tracked, committed, reviewed — fork-wide physical policy.** These describe
the *physics and the safety argument* of your stand when the tracked
`instruments.yaml` is selected, and they belong in your fork's history so a
reviewer can see them change:

| File | What it holds |
|---|---|
| `config/channel_descriptors.yaml` | base-manifest channel identity, units, roles, safety classes |
| `config/alarms_v3.yaml` | every alarm, its thresholds, its operator message |
| `config/interlocks.yaml` | hard trips that cut the source |
| `config/safety.yaml` | critical channels, stale timeouts, source limits |
| `config/physical_alarms.yaml` | cooldown/vacuum guards, operator vocabulary (`landmarks`) |
| `config/channels.yaml` | per-channel UI name, group, thermal zone, alarm band |
| `config/cooldown.yaml` | which channel is the cold stage and which the warm stage |
| `config/housekeeping.yaml` | throttling and housekeeping budgets |

**Gitignored, machine-local — addresses and secrets.** `.gitignore` ignores
`config/*.local.yaml` (`.gitignore:33`). Each has a tracked `.example`
template you copy:

| Local file | What it holds |
|---|---|
| `config/instruments.local.yaml` | VISA resources, COM ports, GPIB addresses of *this* PC |
| `config/channel_descriptors.local.yaml` | the **effective** descriptor manifest whenever `instruments.local.yaml` is selected; it replaces the base manifest and must be reviewed with that machine's physical roster |
| `config/notifications.local.yaml` | Telegram bot token — a secret, never commit it |
| `config/web.local.yaml`, `config/sinks.local.yaml` | host-specific endpoints |

Two mechanics you must know before editing anything:

- **Local overrides are whole-file replacements, not merges.** For
  `instruments`, `interlocks`, `housekeeping`, `safety`, `plugins`, `cooldown`
  and `notifications`, the engine picks `<name>.local.yaml` if it exists and
  otherwise `<name>.yaml` (`src/cryodaq/engine.py:2235-2238`). There is no
  key-level merge. A local file that omits a key does not inherit it.
- **The descriptor manifest is coupled to the instrument manifest.**
  `config/channel_descriptors.local.yaml` is selected **only** when the engine
  selected `config/instruments.local.yaml`, and then it is *mandatory* — a
  missing or invalid local manifest never falls back to the tracked base
  (`src/cryodaq/engine.py:2247-2250`;
  `src/cryodaq/storage/channel_descriptors.py:431-446`). If you create one you
  must create the other. Thus a tracked descriptor is not the effective
  reviewed physical policy on a machine using local instruments: the mandatory
  local descriptor is. Preserve its reviewed roster/sign-off with the lab's
  local acceptance record; the base file is not consulted in that mode.
- **`config/alarms_v3.yaml` and `config/physical_alarms.yaml` have no local
  override at all.** The engine reads them from the tracked path
  unconditionally (`src/cryodaq/engine.py:6432`, `:6612`, `:6645`), as does
  `config/channels.yaml` (`src/cryodaq/core/channel_manager.py:25`). Your
  alarm thresholds are therefore *committed policy in your fork* by
  construction. That is the intended design: a threshold is a physical claim
  and must be reviewable, whereas a COM port is not.

Calibration curves are neither: they are runtime data under
`data/calibration/curves/` (`src/cryodaq/engine.py:6382-6386`), and `data/*`
is gitignored (`.gitignore:74`). Export and archive them out-of-band; do not
commit them into the fork.

**DONE when** every file you changed is in exactly one of the three
categories above, `git status` shows no `*.local.yaml` staged, and no secret
appears in a tracked file.

## 2. Declare your instruments

Edit `config/instruments.local.yaml` (copied from
`config/instruments.local.yaml.example`). Each entry needs at minimum `type`
and `name`; the rest is per-type.

The driver registry is a **closed allowlist** — there is no plugin discovery,
no entry-point scan, no module-name lookup
(`src/cryodaq/drivers/registry.py:1-6`). The built-in types today are:

| `type` | Class | Trust |
|---|---|---|
| `lakeshore_218s` | `LakeShore218S` | passive measurement |
| `thyracont_vsp63d` | `ThyracontVSP63D` | passive measurement |
| `etalon_multiline` | `MultiLineDriver` | passive measurement |
| `asc_reference_tcp` | `ASCReferenceTCP` | passive extension |
| `keithley_2604b` | `Keithley2604B` | reviewed source (hazardous) |

An unknown `type` fails startup with `UnknownDriverTypeError`
(`src/cryodaq/drivers/registry.py:561-569`). If your hardware is not on this
list you need a **new driver**, which is production code in
`src/cryodaq/drivers/` and outside the config-level adaptation this document
describes. A passive sensor driver is ordinary work. An actuator that can put
energy into the cryostat is **not currently supported at all** — read §8
before spending any effort on it.

`name` is a stable identity, not a path: no whitespace, no `/`, `\`, `:` or
`..` (`src/cryodaq/drivers/registry.py:703-719`). It is the `instrument_id`
that the descriptor manifest must match exactly.

**DONE when** `cryodaq-engine --mock` gets past the line
`Прибор сконфигурирован: <name> (<type>) …` for every instrument you declared.

## 3. Build the descriptor manifest

The descriptor manifest is the identity authority for the whole system. A
channel that is not in it cannot be persisted, and because persistence is
ordered before publication, a reading on an undeclared channel is not
published either. `SQLiteWriter.begin_committed` binds *every* reading
through the catalog owner
(`src/cryodaq/storage/sqlite_writer.py:6795-6808`), and `bind()` raises for a
`(instrument_id, emitted_channel)` pair it does not know
(`src/cryodaq/storage/channel_descriptors.py:827-837`). There is no
best-effort path. Completeness is not a nicety here.

### 3.1 File shape

The manifest grammar is exact — extra or missing keys are rejected, YAML
aliases are refused, and the file must be a single-link regular file under
256 KiB (`src/cryodaq/storage/channel_descriptors.py:52-73`, `:241-349`,
`:352-428`). The root has exactly three keys:

```yaml
schema_version: 1
descriptors:
  - schema_version: 1
    channel_id: T1              # stable identity; NO whitespace anywhere
    instrument_id: LS218_1      # must equal the instruments.yaml `name`
    source_key: input.1.temperature   # lowercase dotted device-local grammar
    quantity: temperature
    unit: K
    role: primary_measurement
    safety_class: observational
    display_group: cryostat
    display_name: Cryostat top  # human text; spaces allowed here
    visible_by_default: true
    display_order: 0
    descriptor_revision: 1
bindings:
  - instrument_id: LS218_1
    emitted_channel: "Cryostat top"   # the label the DRIVER emits
    channel_id: T1                    # the canonical identity above
```

Hard rules the loader enforces, each of which fails startup:

- `descriptors` and `bindings` must have **the same length**, and the binding
  set must be one-to-one and cover every descriptor exactly once
  (`src/cryodaq/storage/channel_descriptors.py:367-370`, `:421-423`,
  `:771-788`).
- `channel_id`, `instrument_id` and `source_key` are the immutable identity
  anchor. `quantity` and `unit` are immutable too: changing either requires a
  **new** `channel_id`, not a new revision
  (`src/cryodaq/channels/descriptors.py:94-103`, `:304-331`).
- `unit` must be legal for `quantity`. The allowed sets are fixed:
  `temperature` → `K`/`°C`; `raw_sensor` → `sensor_unit`; `pressure` →
  `mbar`/`hPa`; `length` → `mm`; `relative_humidity` → `%`; `voltage` → `V`;
  `current` → `A`; `resistance` → `Ohm`; `power` → `W`; `event_state` →
  `state`; `derived` → any of those plus `1`
  (`src/cryodaq/channels/descriptors.py:73-89`).
- `channel_id` and `instrument_id` must be NFC-normalized and contain **no
  whitespace at all**, including internal spaces
  (`src/cryodaq/channels/descriptors.py:122-140`). `display_name` and
  `display_group` may contain spaces.
- The manifest's instrument set must equal the configured instrument set
  **exactly** — no missing, no extra
  (`src/cryodaq/storage/channel_descriptors.py:811-825`, called at
  `src/cryodaq/engine.py:2256`).

### 3.2 The `emitted_channel` column is not decorative

`emitted_channel` is the label the *driver* puts on `Reading.channel` before
binding; `channel_id` is the canonical identity everything downstream sees.
They are usually different, and getting the emitted label wrong is the most
common way to produce a manifest that loads cleanly and then drops every
reading.

For `lakeshore_218s`, the emitted label is the value from the instrument's
`channels:` map, or `CH<n>` if that channel number is not mapped
(`src/cryodaq/drivers/instruments/lakeshore_218s.py:239`, `:253`, `:328`).
Read your own driver's `Reading.now(channel=…)` call sites rather than
guessing.

### 3.3 Every raw channel must be declared too

Calibration acquisition republishes each raw sensor reading under a *derived*
channel name — the source channel with a `_raw` suffix
(`src/cryodaq/core/calibration_acquisition.py:129-143`). Those readings go
through the same persistence path as everything else, so if the `_raw`
channels are missing from the manifest **the calibration session fails to
persist**, and you will only discover it during a calibration run.

So the manifest is a superset of what is emitted in steady state. For a
sensor you intend to calibrate, declare a second descriptor with
`quantity: raw_sensor`, `unit: sensor_unit`,
`role: reference_measurement`, and a `channel_id` distinguishable from the
temperature channel; bind it to `"<emitted temperature label>_raw"`. The
shipped `config/channel_descriptors.yaml` shows the pattern (`Т1` and
`Т1.raw`).

Declaring a channel that is never emitted is harmless — an unused binding
simply never fires. Failing to declare one that *is* emitted is fatal.

### 3.3.1 Sensor-diagnostics classification comes from the descriptor

The temperature sensor-diagnostics engine receives an immutable snapshot of
the selected descriptor catalog at startup. For every channel present in that
catalog, its descriptor is the sole classifier: it reaches the temperature
noise/drift scorer only when `quantity: temperature`, `unit: K`, and `role` is
`primary_measurement`, `reference_measurement`, or `environment`. In
particular, `source_readback`, `derived`, and `event` roles are excluded even
when a channel name looks like a thermometer.

Pressure, voltage, current, resistance, power, and other non-temperature
quantities do not use this scorer. A pressure diagnostic needs its own scorer,
with pressure units and thresholds; do not repurpose the temperature health
values for it.

Only a channel absent from the catalog uses the limited legacy/test fallback:
the historical `Т1`/`T1` and `/temperature` name patterns. That fallback must
never override a known descriptor, and it is not a substitute for declaring a
lab's physical roster in the manifest.

### 3.4 `safety_class` — the one field an agent must not guess

`safety_class` is one of four values
(`src/cryodaq/channels/descriptors.py:55-59`):

- `observational` — the default. Measured, recorded, shown, alarmed on, but
  no part of the safety FSM's existence conditions.
- `safety_critical_input` — a channel whose *staleness* is a fault. Use it
  only for sensors that are **physically fixed between experiments**. A
  mobile, per-experiment sensor declared critical produces spurious faults
  every time it is moved (`config/safety.yaml:9-14` records that reasoning
  for this stand).
- `hazardous_source_readback` — voltage/current/power read back from a
  reviewed source. It is **mutually bound** to `role: source_readback`: each
  requires the other, and declaring one without the other fails validation
  (`src/cryodaq/channels/descriptors.py:217-221`).
- `legacy_unknown` — reserved for synthetic rows recovered from pre-descriptor
  archives. Never write it in a manifest; the catalog rejects it
  (`src/cryodaq/channels/descriptors.py:388-389`).

`safety_critical_input` is enforced, not advisory — **but only once you have
declared at least one such channel.** At startup the liveness validator computes
the set of temperature channels classified `safety_critical_input`. **If that set
is non-empty**, it requires the set to be **exactly** the set matched by
`critical_channels` in `config/safety.yaml`, and a mismatch in either direction
fails startup (`src/cryodaq/core/safety_pattern_liveness.py:646-664`; note the
`if critical_manifest_ids and ...` guard at `:657`). So this field and that
config list are one decision recorded twice, and they must be decided together.

**If your manifest declares no `safety_critical_input` temperature channel, this
check does not run at all.** You then have `critical_channels` patterns in
`safety.yaml` with no manifest counterpart, and nothing tells you so. Declaring
the empty set switches the guard off; it is not a way to defer the decision.
Resolve the ESCALATE below before the first energized run rather than leaving
the manifest empty.

**ESCALATE** the `safety_critical_input` list. Which sensors are permanently
bolted to which stage is a physical fact about the hardware; an agent cannot
read it out of the repository.

### 3.5 Generating a first draft

`build_channel_descriptors_local` in `src/cryodaq/gui/first_run_config.py:200`
derives a local manifest from a declared instrument set, and the first-run
wizard calls it. Understand its limit before relying on it: it selects rows
from the shipped descriptor **template** by matching instrument *type*, and
raises `descriptor template lacks a '<type>' instrument slot` when your
configuration has an instrument type the template does not cover
(`src/cryodaq/gui/first_run_config.py:279-294`). It rebuilds emitted-channel
bindings from the live wizard configuration, so it is reliable for "same
driver types, different count/labels/addresses" — which is the common case —
and useless for genuinely new hardware.

For genuinely new hardware, write the manifest by hand against §3.1–§3.4.

**DONE when** `cryodaq-engine --mock` starts and stays up (see §7), and a
short mock run produces at least one persisted row for every channel you
expect to be emitted in steady state.

## 4. Calibration acceptance

A calibration curve converts a raw sensor reading into a temperature that
alarms and interlocks then act on. An unacceptable curve is a safety problem,
not a data-quality problem.

### 4.1 What a curve must carry

A `CalibrationCurve` records `curve_id`, `sensor_id`, `fit_timestamp`,
`raw_unit`, `sensor_kind`, the source session ids, its zones, and a metrics
dict (`src/cryodaq/analytics/calibration.py:143-207`). Each zone carries its
own `raw_min`, `raw_max`, polynomial `order`, `rmse_k`, `max_abs_error_k` and
`point_count` (`:99-107`). A fit additionally records `sample_count`,
`zone_count`, overall `rmse_k` and `max_abs_error_k`, the raw and temperature
spans, and the sensitivity range (`:295-313`).

**Reference traceability** is carried per sample, not per curve: every
`CalibrationSample` records `reference_channel`, `reference_temperature`,
`reference_instrument_id`, `sensor_channel`, `sensor_raw_value` and the
`experiment_id` it came from (`src/cryodaq/analytics/calibration.py:55-65`).

### 4.2 Acceptance criteria

A curve is acceptable for runtime use when **all** of the following hold.
The stored curve can show that it contains reference identifiers, spans,
residual statistics and an assigned `channel_key`; it cannot establish a valid
certificate, the lab's operating envelope or alarm band, or the physical
sensor-to-channel binding. Treat those as external-evidence gates, not as
metadata checks.

1. **The reference is identified and traceable.** Every sample's
   `reference_instrument_id` / `reference_channel` names a thermometer whose
   own calibration certificate exists and is in date. The stored identifier is
   only a pointer: attach or cite the actual valid certificate. A fit whose
   samples name no reference instrument is not a calibration; it is a curve
   fit. **NOT PASSED** without that external certificate.
2. **The valid range covers the operating range with margin.** Compare the
   curve's `raw_min`/`raw_max` span (and hence `temperature_min_k` /
   `temperature_max_k`) against the temperatures this channel will actually
   see, including cooldown and warmup transients — not just the setpoint. The
   operating envelope is a lab document, not a property inferred from a curve.
   **NOT PASSED** until that document or an engineer signature supplies it.
3. **The residuals are within the uncertainty you are claiming.** Both the
   overall `rmse_k` and the worst-zone `max_abs_error_k` must be small
   compared with the tightest alarm band that will be applied to this channel
   (§6). The fitter's default target is `target_rmse_k = 0.05` K
   (`src/cryodaq/analytics/calibration.py:241`); that is a *default*, not a
   specification for your sensor. The alarm band is external physical policy;
   statistics alone cannot pass this criterion.
4. **The curve is assigned to the right channel and only that channel.**
   Assignment is by `channel_key`, held in the store's assignment index
   (`src/cryodaq/analytics/calibration.py:691-735`). That proves only the
   software assignment. Confirm the physical sensor-to-channel correspondence
   with the wiring record and a signed channel-mapping observation; metadata
   alone cannot establish it. **NOT PASSED** without that physical evidence.
5. **It has been compared against real hardware.** Software agreement is not
   evidence. `docs/lab_verification_checklist.md` §3 is the hardware gate:
   the curve must be exercised against the real thermometer, and the
   out-of-range fallback must be observed. **This gate cannot be closed in
   mock mode**, and an agent must not report it closed.
6. **An engineer has signed the runtime enable.** See §4.4.

### 4.3 Fallback behaviour you are relying on

Runtime curve application fails *safe*, and you should know which safe. In
`_merge_runtime_readings`
(`src/cryodaq/drivers/instruments/lakeshore_218s.py:506-613`) the driver falls
back to the instrument's native reading, tagging the reason, when:

- there is no fresh raw reading for the channel (`missing_srdg`);
- the raw value is **outside the calibrated span** (`raw_out_of_cal_range`);
- evaluating the curve raised (`curve_evaluate_failed`).

The out-of-range case matters more than it looks. `CalibrationCurve.evaluate`
clips an out-of-span raw to the zone boundary, which would freeze the reported
temperature and drive `dT/dt` to zero — blinding every rate-based safety
check. `raw_in_range` therefore performs **no** clipping and is checked first
(`src/cryodaq/analytics/calibration.py:165-179`;
`src/cryodaq/drivers/instruments/lakeshore_218s.py:552-575`). If you add a new
calibrated driver, reproduce this ordering exactly.

### 4.4 Enabling a curve at runtime is a two-key operation

Nothing is applied until *all* of these are true
(`src/cryodaq/analytics/calibration.py:610-689`): the store's `global_mode` is
`on`; the channel's `reading_mode_policy` is not `off`; the assignment's
`runtime_apply_ready` flag is `true`; and the named curve is loaded. Any one
missing resolves to `effective_mode: off` with an explicit `reason`, and the
native reading is published instead. An imported vendor curve is deliberately
assigned with `runtime_apply_ready=False`
(`src/cryodaq/analytics/calibration.py:436-442`) — importing a `.340` file
does not enable it.

**ESCALATE** the flip of `runtime_apply_ready` to `true`. That is the moment a
fitted polynomial starts feeding the interlocks.

**DONE when**, for every channel you intend to run calibrated: criteria 1–4
have their required external certificate, operating-envelope/alarm-band, and
physical-binding evidence recorded in writing, criterion 5 has a dated
hardware observation in `docs/instruments.md`, and criterion 6 is signed. A channel that does not
clear all six stays uncalibrated — which is a supported, safe state.

## 5. Channel coverage: mapping every declared channel to every surface

The reviewer's finding was that "startup succeeds" is not evidence of
coverage. This section is the antidote: for **every** `channel_id` in your
manifest, make an explicit entry in a coverage table, and record either the
mapping or the justified exclusion. Some surfaces are enforced at startup;
some are not, and those are where silent gaps live.

### 5.1 Surfaces that are automatic once the descriptor exists

You do not have to do anything per channel for these, and you cannot break
them per channel:

- **Persistence.** Every published reading is descriptor-bound and stored with
  its `descriptor_hash` (`src/cryodaq/storage/channel_descriptors.py:1114`,
  `:1201-1219`).
- **Replay and reports.** A non-legacy report reading *requires* a descriptor
  and cross-checks instrument, channel and unit against it
  (`src/cryodaq/reporting/data.py:53-68`).
- **Archive rotation.** Descriptors travel with the rows
  (`src/cryodaq/storage/descriptor_archive.py`).

### 5.2 Surfaces enforced at startup — fail loudly

`validate_safety_pattern_liveness`
(`src/cryodaq/core/safety_pattern_liveness.py:424-613`) checks five "planes"
against the manifest the engine actually selected, and raises
`SafetyPatternLivenessError` naming every dead pattern:

| Plane | Config | Failure it prevents |
|---|---|---|
| 1 | `config/interlocks.yaml` `channel_pattern` | an interlock matching no channel |
| 2 | `config/safety.yaml` `critical_channels` | a critical channel that cannot be resolved to exactly one emitted label |
| 3 | `config/safety.yaml` `keithley_channels` | a source-heartbeat pattern matching nothing |
| 4 | throttle-protected patterns | a protected channel expression that cannot be resolved |
| 5 | `config/alarms_v3.yaml` channel references, **at every severity** | a misspelled alarm channel that loads cleanly and annunciates nothing, forever |

Plane 5 exists because adding a channel alarm is the single most common
adaptation a new lab makes. If a channel is legitimately absent at your lab,
you declare that per-reference with an `optional_channels` list on that alarm
(`src/cryodaq/core/safety_pattern_liveness.py:100-109`, `:206-210`) — silence
is opt-in and visible in the config, never a blanket severity exclusion.

Additionally, an alarm's channel selector must be one of `channel`,
`channels` or `channel_group`, at most one of them, and it must resolve to at
least one channel; the loader rejects the empty and mixed forms that would
otherwise produce a permanently dead annunciator
(`src/cryodaq/core/alarm_config.py:298-331`).

### 5.3 Surfaces **not** enforced — you must check these by hand

Nothing fails if a channel is missing from these. This is where your coverage
table earns its keep.

| Surface | File / key | What a missing entry costs |
|---|---|---|
| Dashboard name, visibility, group | `config/channels.yaml` (`name`, `visible`, `group`) | channel appears with a raw identity, ungrouped |
| Cryogenic-state indicator | `config/channels.yaml` `is_cold` | **defaults to `true`** — a warm flange sensor left unmarked drags the cold-state indicator |
| Phase-aware alarm bands | `config/channels.yaml` `thermal_zone`, `alarm_band` | no band; falls through to whatever `config/alarms_v3.yaml` happens to cover |
| Cooldown prediction | `config/cooldown.yaml` `channel_cold` / `channel_warm` | prediction runs against the wrong stage |
| Cooldown / vacuum guards | `config/physical_alarms.yaml` `cold_channel`, `warm_channel`, `pressure_channel`, `reference_temp_channel` | guard armed against a channel that is not the one you think |
| Operator vocabulary | `config/physical_alarms.yaml` `landmarks` aliases | the operator assistant cannot resolve the phrase an operator actually uses |
| Operator wording | `config/alarms_v3.yaml` `message` | an alarm fires with text describing hardware you do not have |

Two specific traps:

- `config/channels.yaml` has **no** local override and **no** completeness
  check against the descriptor manifest. A channel present in the manifest and
  absent here silently takes defaults.
- Operator-facing strings in this fork are Russian, and the design system
  requires that to stay consistent (`AGENTS.md`, GUI/UX gate). Adopt your own
  operators' language deliberately and completely; do **not** leave shipped
  Russian alarm messages describing a cryostat you did not build. Every
  `message` in `config/alarms_v3.yaml` names a physical situation and an
  action — both must be true at your lab.

### 5.4 The coverage table

Produce a table with one row per `channel_id` and one column per surface in
§5.3, plus the §5.2 planes. Each cell is either a concrete reference (the key
you wrote) or an explicit exclusion with a reason. "Not applicable" is a valid
answer; a blank cell is not.

**DONE when** the table has no blank cells, every exclusion carries a reason,
and the §5.2 planes pass at startup (§7).

## 6. Deriving thresholds before anything is energized

`docs/alarms_tuning_guide.md` is the layer-by-layer reference for *where* each
threshold lives (SafetyManager / interlocks / AlarmEngine) and what the
shipped values are. This section is the *method* for arriving at a number for
a stand that has never run.

The guide's own baseline procedure — run one or two full cycles, look at
observed maxima, add 20–30 % headroom (`docs/alarms_tuning_guide.md:316-326`)
— is sound for tuning **nuisance** thresholds *after* the stand is known safe.
It cannot be used to set the thresholds that must already be correct the first
time the heater is switched on, because it requires having run.

### 6.1 The two classes of threshold

**Class A — protective.** Its job is to prevent damage or a hazard:
interlock trip points, `source_limits` in `config/safety.yaml`, the vacuum
guard, absolute sensor-fault bounds. These must be derived **before** the
first energized run, from a stated physical source, and they must be
conservative under the uncertainty of that source.

**Class B — operational.** Its job is to draw attention: rate warnings, stall
detection, drift, disk space. These may start from a defensible estimate and
be tuned against observed behaviour using the guide's baseline procedure.

Classify every threshold you set before you set it. When in doubt it is
Class A.

### 6.2 Deriving a Class A threshold

For each one, record — in the fork, next to the value or in the physics
document §6.4 asks you to write — all five of:

1. **The physical quantity being bounded**, in words. Not "T12 max" but "the
   temperature above which the detector bond line is at risk".
2. **The source of the limit**, with a citation: a component datasheet, a
   material property, a vendor's stated maximum, a documented calculation, or
   a measurement on this hardware. "This is what the shipped config said" is
   not a source — the shipped values describe a different cryostat.
3. **The uncertainty of that source**, and it must be a real interval. A
   datasheet maximum with no tolerance, a property extrapolated outside its
   measured range, or a number recalled from a similar stand all carry large
   uncertainty and must be treated as such.
4. **The margin**, and why it is enough. Fold in: the source uncertainty from
   (3); the sensor's own uncertainty (§4 — a curve with `max_abs_error_k` of
   0.3 K cannot support a 0.1 K band); the detection latency, which is the
   poll interval plus any `sustained`/`cooldown_s` debounce
   (`config/interlocks.yaml`, `config/physical_alarms.yaml`); and the rate at
   which the quantity can move, so you trip before the limit rather than after
   it.
5. **What happens when it trips**, and that this is acceptable. An
   `emergency_off` on a channel that also alarms on ordinary cooldown is not a
   protection, it is an outage. Interlock actions are `emergency_off` or
   `stop_source` (`config/interlocks.yaml:12`).

Two rules that are not negotiable:

- **Absolute physical bounds are not operating ranges.** The shipped
  `[0, 350] K` sensor-fault bounds mean "no real cryogenic sensor reads
  outside this", not "this is our working range"
  (`docs/alarms_tuning_guide.md:434-443`). Set your working range separately,
  as an `alarm_band` in `config/channels.yaml`.
- **A protective threshold must be reachable by the sensor that guards it.**
  If the guarding channel is calibrated, its valid range (§4.2 criterion 2)
  must extend past the threshold. A trip point outside the calibrated span is
  guarded by the fallback path, not by the curve.

### 6.3 Ordering between the layers

The layers must be ordered so the softer one fires first, and the ordering has
to hold for *your* numbers, not just the shipped ones:

For an **upper-bound** trip (`above` / `>`), the numeric order is:

```
alarm threshold  <  interlock threshold  <  hardware limit
```

For a **lower-bound** trip (`below` / `<`), danger increases as the value
falls, so the numeric order reverses:

```
hardware minimum  <  interlock threshold  <  alarm threshold
```

This follows the implemented comparisons: an alarm with `below` fires for
`value < threshold` (`src/cryodaq/core/alarm_v2.py:322-342`) and an interlock
with `<` fires for `value < threshold`
(`src/cryodaq/core/interlock.py:117-121`).

Staleness has the same shape and the shipped values already demonstrate it:
`stale_timeout_s: 10` in `config/safety.yaml` is a fault; the alarm-level
stale/loss timeouts in `config/alarms_v3.yaml` are looser
(`docs/alarms_tuning_guide.md:395-404`). Keep safety strictest.

Check the ordering explicitly after you set the numbers; nothing in the code
enforces it.

### 6.4 Write the physics document

`config/alarms_v3.yaml` refers to a physics rationale file that **does not
exist in this repository** (`docs/alarms_tuning_guide.md:447-470` says so
plainly and gives the structure). Your fork should create it as a tracked
document and record, per threshold, items 1–5 from §6.2. Without it, the next
operator inherits magic numbers, and the next agent has no way to tell a
derived value from a copied one.

**ESCALATE** every Class A threshold for engineer sign-off before the first
energized run. The agent's deliverable is the derivation and the candidate
number; the decision is not the agent's.

**DONE when** every Class A threshold has all five records, the §6.3 ordering
holds, and the sign-off exists. Class B thresholds may be marked "provisional,
to be tuned per `docs/alarms_tuning_guide.md`".

## 7. Definition of done

There is **no single command** in this repository that answers "is my
adaptation complete". That is a real gap, stated here rather than papered
over: the checks below are genuine and each has an exit code, but you must run
all of them, and the last two rows cannot be closed by software at all.

Run from the repository root with the project's interpreter and
`PYTHONPATH` set to `<repo>/src` (see `AGENTS.md`, "Verification baseline",
for the exact platform forms).

**1. Tracked config conformance.** Validates the *tracked* `config/*.yaml`
against the production loaders — descriptor manifest, interlocks, safety,
alarms, physical alarms, cooldown:

```bash
python -m pytest -q tests/config/ \
  tests/core/test_alarm_config_validation.py \
  tests/core/test_alarm_reference_liveness.py \
  tests/core/test_interlock_descriptor_canonical.py \
  tests/core/test_physical_alarm_exactness.py \
  tests/core/test_safety_pattern_liveness.py \
  tests/core/test_startup_safety_liveness_gate.py
```

Pass signal: exit 0. **Limit: this validates the tracked base manifest only.**
It does not see `config/*.local.yaml`, so on a machine that uses local
overrides a green run here proves nothing about what the engine will actually
load.

**2. Selected-configuration startup.** This is the only check that exercises
the configuration the engine will really use, local overrides included:

```bash
cryodaq-engine --mock
```

Pass signal: the process **stays up** and logs
`Alarm Engine v2: загружено N алармов`. Fail signal: it exits with code **2**
and logs `CONFIG ERROR (<layer> config): exception=<Error>`; the launcher
deliberately does not auto-restart that code
(`src/cryodaq/engine.py:7691`, `:7769-7796`). A dead alarm channel reference,
for instance, exits 2 with `SafetyPatternLivenessError`.

**Limit: there is no bounded "validate and exit" mode.** On success the engine
runs until you stop it, so this cannot be a CI gate as it stands. Closing that
gap requires new production code (a validate-only entry point), which is
outside the scope of this document.

**3. Documentation and changed-file gates.** Run the documentation tests, and
for Python files changed in your slice run the same changed-files formatting
gate that `AGENTS.md` specifies. Do **not** substitute a repository-wide Ruff
format command: the repository has pre-existing formatting debt and that
command is known red on a clean tree.

```bash
python -m pytest -q tests/docs/
git diff --name-only --diff-filter=ACMR -z <FORMAT_BASE>...HEAD -- '*.py' \
  | xargs -0 -n 100 python -m ruff format --check --no-cache --
```

`AGENTS.md` "Verification baseline" supplies the exact platform command and
the current `FORMAT_BASE`. Run `ruff check --no-cache` only on the Python paths
you changed.

**4. Coverage table (§5.4).** No blank cells. Manual; nothing checks it.

**5. Threshold derivations (§6).** Every Class A threshold has its five
records and its sign-off. Manual; nothing checks it.

**6. Hardware acceptance.** `docs/new_lab_acceptance_checklist.md`, filled in
for your hardware. **Mock mode cannot close any row of it**
(`AGENTS.md`, "Mission and safety boundary").

The adaptation is complete when 1–3 are green, 4–5 are written and signed, and
6 is closed with real evidence. Anything less is an adaptation in progress,
and must be reported as such.

## 8. What is out of scope here

- **Adding a passive sensor driver** — production code in
  `src/cryodaq/drivers/`, plus a registry entry. Ordinary engineering work,
  but not config-level adaptation.
- **Adopting a different hazardous actuator — NOT POSSIBLE TODAY. Do not
  attempt it.** The driver registry does keep an explicit roster of bindings
  that passed hazardous-source review (`REVIEWED_SOURCE_BINDINGS`,
  `src/cryodaq/drivers/registry.py:133-149`), and structural conformance to the
  driver protocol never by itself confers source authority
  (`src/cryodaq/drivers/registry.py:255-272`). But **the loader is the only
  part of that path that generalises.** Downstream of it the system is still
  built around one vendor's SMU:

  - `SafetyManager` is internally Keithley-shaped — `_keithley`,
    `_keithley_patterns`, `_keithley_channel_states`,
    `_has_fresh_keithley_data` and the `require_keithley_for_run` config field
    (`src/cryodaq/core/safety_manager.py:83`, `:2645`, `:2796`, `:2830`),
    constructed from a `keithley_driver` parameter
    (`src/cryodaq/core/safety_manager.py:140-158`).
  - Its global OFF and channel-state publication iterate a hardcoded
    `("smua", "smub")` pair (`src/cryodaq/core/safety_manager.py:2203`,
    `:2434`, `:2605`) and publish under
    `analytics/keithley_channel_state/<smu_channel>`
    (`src/cryodaq/core/safety_manager.py:2214-2215`).
  - `ReviewedSourceBinding` retains `adapter_module`, `adapter_class` and
    `contract_version` as the declared adapter-contract identity
    (`src/cryodaq/drivers/registry.py:116-130`). The present loader does not
    yet dispatch through those fields; retain them for the future
    capability-tier adapter contract rather than deleting them.

  So adding a roster entry gets a second actuator past the loader and then
  into a supervisor that cannot drive it. The extension contract and its
  evidence contract are not finished. **TODO: this section will be written
  once they are.** Until then this is an engineer-led activity requiring hazard
  analysis, an honest OFF-capability disclosure and physical bench evidence per
  `AGENTS.md`, and an agent must not present the roster as a working extension
  point.
- **The plugin-authoring path** — inactive; see `AGENTS.md`, "Future
  agent-native plugin authoring". Do not assume `PLUGIN_CONTRACT.md`,
  `tests/conformance/` or `plugins/_template/` exists.

## 9. Known adaptation traps in the current code

Report these rather than working around them silently.

- **One analytics feed is bound to this stand's exact cold-stage descriptor.**
  `src/cryodaq/gui/shell/main_window_v2.py:133-143` recognises the cold stage
  by an exact identity match on `channel_id`, `instrument_id`, `source_key`,
  quantity, unit, role, safety class **and** `display_group`. A lab whose cold
  stage is any other descriptor loses that analytics feed with no error. This
  needs a production fix (select by role/classification, not identity); until
  then, note it in your coverage table.
- **The descriptor draft generator is template-bound.** §3.5 — it cannot
  produce a manifest for an instrument type absent from the shipped template.
- **No completeness check ties `config/channels.yaml` to the manifest.** §5.3.
