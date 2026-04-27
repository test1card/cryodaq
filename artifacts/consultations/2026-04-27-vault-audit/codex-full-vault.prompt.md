Model: gpt-5.5
Reasoning effort: high

# Full-vault audit — Codex literal verifier (post-build)

## Mission
Read every markdown note under ~/Vault/CryoDAQ/ except `_meta/`. For each
factual claim that has a `source:` reference in the note's frontmatter,
cross-reference the claim against the actual repo file. Flag what's
factually wrong.

This is post-build verification. The vault was built overnight 2026-04-26
and passed self-driven audit gates during build. This pass is independent
adversarial review on the full integrated artifact.

## Scope of vault to audit
- ~/Vault/CryoDAQ/00 Overview/*.md (4 notes — What is CryoDAQ, Hardware setup, Architecture overview, UI and design system)
- ~/Vault/CryoDAQ/10 Subsystems/*.md (6 notes — Web/Cooldown/Experiment/Interlock deferred, not present)
- ~/Vault/CryoDAQ/20 Drivers/*.md (3 notes)
- ~/Vault/CryoDAQ/30 Investigations/*.md (6 notes)
- ~/Vault/CryoDAQ/40 Decisions/*.md (7 notes — 4 mirrored ADRs + 3 synthesized ADR-001..003)
- ~/Vault/CryoDAQ/50 Workflow/*.md (4 notes)
- ~/Vault/CryoDAQ/60 Roadmap/*.md (2 notes — Versions, F-table backlog)
- ~/Vault/CryoDAQ/README.md
- skip 90 Archive/ (intentionally empty)
- skip _meta/ (build log + glossary + source map are CC-internal)

## Source files in repo for cross-reference
- ~/Projects/cryodaq/CLAUDE.md
- ~/Projects/cryodaq/PROJECT_STATUS.md
- ~/Projects/cryodaq/ROADMAP.md
- ~/Projects/cryodaq/CHANGELOG.md
- ~/Projects/cryodaq/docs/decisions/*.md
- ~/Projects/cryodaq/docs/ORCHESTRATION.md
- ~/Projects/cryodaq/.claude/skills/*.md
- ~/Projects/cryodaq/src/cryodaq/core/safety_manager.py
- ~/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py
- ~/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py
- ~/Projects/cryodaq/src/cryodaq/analytics/calibration.py
- ~/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py
- ~/Projects/cryodaq/src/cryodaq/analytics/base_plugin.py
- ~/Projects/cryodaq/src/cryodaq/analytics/plugin_loader.py
- ~/Projects/cryodaq/src/cryodaq/core/alarm_v2.py
- ~/Projects/cryodaq/src/cryodaq/core/alarm_config.py
- ~/Projects/cryodaq/config/instruments.yaml
- ~/Projects/cryodaq/config/alarms_v3.yaml
- ~/Projects/cryodaq/config/safety.yaml
- ~/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py
- ~/Projects/cryodaq/src/cryodaq/drivers/instruments/keithley_2604b.py
- ~/Projects/cryodaq/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
- (read additional files as cited by individual notes' source: headers)

## Severity scale (use exactly these labels)
- CRITICAL: claim contradicts source code or repo doc
  (homoglyph-class — actively wrong)
- HIGH: claim is overstatement vs source
  (technically partial-true but reader will draw wrong conclusion)
- MEDIUM: claim is true but missing important caveat
- LOW: minor wording / clarity / style
- DEFERRED-COVERAGE: source declares something exists that vault has
  zero mention of (only when totally absent — for partial coverage use HIGH)

## What NOT to flag
- Stylistic preferences (prose density, paragraph length, voice)
- Information density: vault is digest by design, not exhaustive mirror
- Structural choices (folder layout, ADR template choice — CC's domain)
- "I would have written it differently" — only flag what's WRONG
- Coverage gaps already deferred per
  ~/Projects/cryodaq/artifacts/handoffs/2026-04-27-vault-build-handoff.md
  §"Deferred coverage gaps" (4 specific notes — Web/Cooldown/Experiment/Interlock)

## Output format

```
## Finding NN
**Severity:** CRITICAL | HIGH | MEDIUM | LOW | DEFERRED-COVERAGE
**Vault file:** path/to/note.md
**Vault line(s):** line numbers (or section heading)
**Source file:** ~/Projects/cryodaq/path/to/source
**Source line(s):** line numbers
**Claim in vault:** "exact quote from vault"
**What source says:** "exact quote from source OR plain statement of source state"
**Why this is wrong:** 1-2 sentences
**Suggested fix:** specific text replacement OR "remove sentence" OR "add caveat: ..."
```

After all findings:

```
## Verdict
- Total findings: N
- By severity: CRITICAL=A HIGH=B MEDIUM=C LOW=D DEFERRED=E
- PASS / FAIL / CONDITIONAL with one-sentence reason

## Confidence notes
- Areas where you weren't sure / source was ambiguous / 30-second-rule cases
```

Hard cap: **5000 words total**. Prefer specificity over volume —
better 10 well-cited findings than 30 noise.

## Response file
~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/codex-full-vault.response.md

If your sandbox is read-only, do NOT attempt to write the response file
yourself. Emit the full response to stdout — the wrapper redirect captures it.
