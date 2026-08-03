---
title: Lab Profile v1 — a downstream declaration artifact for adapting laboratories
audience: coding agent performing a new-lab adaptation, plus the engineer who signs it off
scope: the v1 lab-profile grammar, its capability derivation, and its downstream boundary
status: canonical
last_updated: 2026-08-03
companion: docs/new_lab_adaptation.md
---

# Lab Profile v1

A **lab profile** is a small, typed, YAML-loadable declaration produced by an
ADAPTING laboratory — a fork of CryoDAQ that runs on different cryogenic
hardware. It answers three questions and nothing more:

1. Who is this lab? (`lab_id`, `display_name`)
2. Which registered instrument types does it have, under which stable names?
3. Which hazardous questions are still UNANSWERED?

It is a **downstream, data-only artifact**. Nothing in the engine consumes it
in v1: it is not read at startup, it activates no driver, and it changes no
runtime behaviour. Its only job is to make the adapting lab's self-description
validatable — and to make whole classes of wrong self-descriptions
**unrepresentable**.

## The v1 grammar

The exact schema lives in `src/cryodaq/lab_profile/schema.py` and the strict
loader in `src/cryodaq/lab_profile/loader.py`. A complete worked example of an
IMAGINARY lab (not the incumbent stand) is shipped at
`docs/examples/lab_profile.imaginary_lab.yaml`:

```yaml
schema_version: 1
lab:
  lab_id: imaginary-asc-lab
  display_name: Imaginary ASC Lab
instruments:
  - type: lakeshore_218s
    name: LS218_1
    note: Eight-channel thermometer on the imaginary cold head.
  - type: thyracont_vsp63d
    name: VSP63_1
  - type: etalon_multiline
    name: ML_1
questions:
  - kind: safety_critical_roster
    subject: Which sensors are permanently bolted to the cryostat?
    summary: The lab has no signed wiring record yet.
```

Grammar rules, all enforced by construction:

- `schema_version` must be the integer `1`. A YAML boolean (`true`) is
  rejected by the exact type check.
- Exact keys at every level. Root: `{schema_version, lab, instruments,
  questions}`. Lab: `{lab_id, display_name}`. Instrument: required `{type,
  name}`, optional `note` — nothing else. Question: exactly `{kind, subject,
  summary}`. Any extra key is rejected (see the next section).
- `instruments` is a non-empty list; instrument `name` values are unique,
  whitespace-free stable identities (no path syntax: no `/`, `\`, `:`, `..`,
  never `.` or `~`), NFC-normalized, at most 64 characters. `lab_id` follows
  the same identity grammar.
- `questions` is a (possibly empty) list. `kind` must be one of the four
  typed kinds below.
- The YAML grammar is strict: no aliases, no duplicate mapping keys, bounded
  nesting depth, strict UTF-8, and a hard 64 KiB file ceiling. The loader is
  an offline validation artifact, so the symlink/TOCTOU defense of the engine
  startup manifest path is deliberately not replicated.

## What is deliberately NOT representable, and why

A lab profile **cannot** express:

- any incumbent config surface — safety rosters, thresholds, interlocks,
  alarms, overrides, channel descriptors, or actuation;
- numeric limits, safety classes, or calibration enablement;
- a driver type outside the closed registry allowlist;
- any source-authority (actuating) instrument.

This is the point, not a limitation. The decision table in
`docs/new_lab_adaptation.md` §0 assigns those decisions to the **engineer**,
never to the adapting agent, and §8 states that adopting a hazardous actuator
is **not possible today**: the reviewed-source roster exists, but downstream
of the loader the supervisor is built around one vendor's SMU. A declaration
artifact that could smuggle a `thresholds:` block or a `keithley_2604b`
instrument past that boundary would be a second, unreviewed mutation path.
So the exact-key schema rejects unknown keys with a message that names the
incumbent surfaces, and declaring a reviewed-source type raises
`ActuationBoundaryError`, pointing at §8. The only reviewed source in the
registry today is `keithley_2604b`
(`src/cryodaq/drivers/registry.py`), so today every source-authority
declaration fails.

## How capabilities are derived

A lab profile never declares capabilities. It declares instruments, and
`src/cryodaq/lab_profile/capabilities.py` derives everything else by reading
**only** `BUILTIN_DRIVER_METADATA` from
`src/cryodaq/drivers/capability_metadata.py` — a deliberately authority-free
module that owns the trust taxonomy and the inert capability table. The
registry *consumes* that table and re-derives it from its live specs at
import time, failing closed on any drift, so the table and the registry
cannot silently disagree. The package never imports the registry at all: the
full `BUILTIN_DRIVER_SPECS` mapping carries public driver factories, and a
data-only artifact must not hold construction authority — not even via
reflection, which lands in the inert module where no constructor exists.
Derivation is the ONLY source of capability truth for a profile.

Worked example: the imaginary lab above declares `lakeshore_218s`,
`thyracont_vsp63d`, and `etalon_multiline`. The registry says the first two
are `passive_measurement` instruments with the `passive_sensor` capability,
and the third adds `burst_sensor`. The derived `LabCapabilities` is therefore:

- `instrument_types`: `("lakeshore_218s", "thyracont_vsp63d", "etalon_multiline")`
- `capabilities`: `{passive_sensor, burst_sensor}`
- `trust_classes`: `{passive_measurement}`
- `actuation_supported`: `False` — a constant; v1 cannot represent actuation
- `grants_control_authority`: `False` — a profile is data, not authority

`LabCapabilities.__post_init__` independently recomputes that union from the
registry and rejects any instance — derived or hand-built — whose values
disagree with it, whose instrument types leave the closed allowlist, or that
reach any source capability (`controlled_source`, `verified_off_source`) or
the `reviewed_source` trust class. An in-memory profile cannot smuggle
actuation in either.

## The four typed question kinds

`QuestionKind` is a closed enum with exactly the four ESCALATE points of
`docs/new_lab_adaptation.md`:

| Kind | ESCALATE point | The question |
|---|---|---|
| `safety_critical_roster` | §3.4 | Which channels are `safety_critical_input` — a physical claim about what is bolted where |
| `calibration_enablement` | §4.4 | May a calibration curve be applied at runtime (`runtime_apply_ready`) |
| `class_a_thresholds` | §6 | The Class A interlock/alarm thresholds, engineer-signed before anything is energized |
| `hazardous_actuation` | §8 | Adding a hazardous actuator — not possible today |

A profile with any question open is `is_fully_answered == False`: the
adaptation is in progress and must be reported as such. An unknown `kind`
string is rejected with a message listing the valid kinds — hazardous
questions cannot be invented.

## How to validate

```bash
python -m cryodaq.lab_profile docs/examples/lab_profile.imaginary_lab.yaml
```

Exit code 0 prints the lab identity, each instrument's derived trust class
and capabilities, `actuation_supported: false`, and every unanswered
question. Any failure exits 2 with `LAB PROFILE ERROR: ...`. There is no
console-script entry point; the module is the interface.

## Enforcement tests

The boundary above is enforced by tests, not by prose:

- `tests/lab_profile/test_imaginary_lab_acceptance.py` — the shipped
  imaginary example loads; its derived capabilities equal the union computed
  independently from the registry; every trust class is passive; the CLI
  validates it with exit 0.
- `tests/lab_profile/test_boundary_rejection.py` — every forbidden mutation
  (unknown driver type, a source-authority instrument, incumbent config keys
  at root or instrument level, bad `schema_version`, YAML aliases, duplicate
  keys, oversized or non-UTF-8 files, unknown question kinds, path-syntax or
  whitespace identities, empty/duplicate instruments) is rejected with the
  right error type and message.
- `tests/lab_profile/test_downstream_readonly.py` — an AST scan proves the
  package imports only stdlib, `yaml`, the inert
  `cryodaq.drivers.capability_metadata` symbols, and the
  `BUILTIN_DRIVER_METADATA` projection — with dynamic/reflective access
  (`importlib`, `__import__`, `.modules`, `inspect`, `gc`) treated as a
  violation; running the whole hostile corpus leaves the registry and the
  tracked incumbent config files byte-identical; the package exposes no
  authority objects.

## Non-goals

- **No engine consumption.** Nothing reads a lab profile at runtime in v1.
- **No plugin authoring.** That roadmap phase is inactive; do not assume any
  plugin contract surface exists.
- **No actuation contract.** A hazardous-actuator extension path does not
  exist today (`docs/new_lab_adaptation.md` §8); a lab profile will never be
  the mechanism that creates one.
