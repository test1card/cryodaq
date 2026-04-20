# Block Spec Authoring Template — CryoDAQ Phase II/III

**Purpose:** Canonical structure for every block spec handed to Claude
Code. Ensures specs ship with autonomy mode, /codex self-review, DS
v1.0.1 gates, and Host Integration Contract baked in — no per-spec
recopy of boilerplate.

**Audience:** Whoever writes the next block spec (web Claude, architect).

**Output:** One file per block at
`CC_PROMPT_<BLOCK_ID>_<SHORT_TITLE>.md` in repo root.

---

## Structural skeleton

Every block spec uses this section order:

```
# <BLOCK_ID> — <short title>
(one-paragraph goal, K-criticality, expected size)

## Autonomy declaration
(inherit playbook — no continue STOPs)

## Workflow overview
(one line per stage, explicitly naming Stage 6 Codex review)

## Stage 0 — Verification reads
(read-only list; CC proceeds after analysis, does NOT stop)

## Stage 1 — Implementation
(file structure, component breakdown, DS token requirements)

## Stage 2 — Host Integration Contract
(three-point wiring in MainWindowV2, plus test file to add)

## Stage 3 — Tests
(overlay test count + wiring test count with coverage categories)

## Stage 4 — Docs
(CHANGELOG + operator manual + DS spec — mandatory per block)

## Stage 5 — Verify + commit + push
(pre-commit gates + targeted tests + commit + push)

## Stage 6 — Codex self-review (autonomous)
(invoke /codex, handle verdict per playbook, amend loop)

## Out of scope
(explicit NOT-TOUCH list)

## Completion criteria
(Codex PASS checklist)
```

---

## Boilerplate block — paste verbatim into every spec

Replace placeholders in `<ANGLE BRACKETS>`. Everything else is
canonical and should NOT be rephrased.

```markdown
# <BLOCK_ID> — <Short Title>

<Goal: one paragraph. What this block ships, what it replaces, and
its K-criticality rating (K1-critical = safety; K2 = calibration /
irreversible ops; K3 = operator workflow correctness; K4 = cosmetic
polish). Expected block size: <LOC estimate>, <test count estimate>,
<MEDIUM findings expected on first Codex review>.>

---

## Autonomy declaration

This spec follows `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` in autonomy
mode. CC drives the entire block end-to-end without waiting for
architect `continue` acknowledgements.

- Stage 0 findings are informational; CC proceeds directly to Stage 1.
- Stages 1-5 are sequential, autonomous.
- Stage 6 invokes `/codex` with `gpt-5.4` + high reasoning (NOT the
  default o3 — verify response header). CC handles verdict per the
  decision tree in the playbook.
- Amend cycles autonomous up to the 3-cycle limit.
- **STOP only when:** genuine architectural fork in Stage 0,
  design-decision FAIL from Codex, 3 amend cycles without PASS, or
  Codex requires out-of-spec scope.

## Workflow overview

1. **Stage 0** — Verification reads (read-only recon).
2. **Stage 1** — Overlay / feature implementation.
3. **Stage 2** — Host Integration Contract wiring.
4. **Stage 3** — Targeted tests (overlay + host wiring).
5. **Stage 4** — Docs (CHANGELOG, operator manual, DS spec).
6. **Stage 5** — Pre-commit gates + commit + push.
7. **Stage 6** — `/codex` self-review + autonomous amend loop.
8. **Report** — final SHA + Codex verdict summary + residual risks.

---

## Stage 0 — Verification reads

<List files to read with specific questions to answer. Example:>

1. `<legacy widget path>` — confirm class structure, unwired buttons,
   legacy tokens, hardcoded hex locations.
2. `<engine file>` — confirm command contracts the overlay will use.
3. `<main_window_v2.py>` — confirm current wiring (readings routing,
   `_OVERLAY_FACTORIES` entry, lazy attr name).
4. `<test file>` — count existing tests that must stay passing.

Report findings briefly (3-5 bullets) and proceed to Stage 1 without
waiting. **Do NOT stop and say "STOP. Waiting for continue."** —
that pattern is retired.

---

## Stage 1 — Implementation

<Block-specific: new file path, component breakdown, public API,
layout, user workflow, DS token list.>

**DS v1.0.1 — mandatory:**

Required tokens: SURFACE_WINDOW, SURFACE_CARD, SURFACE_MUTED,
BORDER_SUBTLE, FOREGROUND, MUTED_FOREGROUND, STATUS_OK,
STATUS_WARNING, STATUS_FAULT, STATUS_CAUTION, STATUS_INFO, SPACE_1..6,
RADIUS_MD on cards, RADIUS_SM on inputs, FONT_BODY, FONT_MONO (for
tabular numbers).

**Forbidden tokens / helpers (zero hits — grep-verified in Stage 5):**
`TEXT_PRIMARY`, `TEXT_SECONDARY`, `TEXT_MUTED`, `TEXT_DISABLED`,
`TEXT_ACCENT`, `apply_panel_frame_style`, `apply_button_style`,
`apply_status_label_style`, `apply_group_box_style`, `PanelHeader`,
`StatusBanner`, `build_action_row`, `create_panel_root`,
`setup_standard_table`, emoji (U+1F300–U+1FAFF, U+2600–U+27BF,
including ✓ U+2713), hardcoded hex colors outside
`PLOT_LINE_PALETTE` indexing.

---

## Stage 2 — Host Integration Contract

Wiring in `src/cryodaq/gui/shell/main_window_v2.py`:

1. **Import switch** — replace `from cryodaq.gui.widgets.<x> import ...`
   with `from cryodaq.gui.shell.overlays.<x> import ...` if overlay
   supersedes legacy widget in the shell.
2. **`_tick_status()` mirror** — add `set_connected` mirror if
   overlay has engine-dependent controls.
3. **`_dispatch_reading()` state sinks** — add routing for any
   new readings the overlay consumes.
4. **`_ensure_overlay()` replay** — replay cached state on lazy
   construction (`set_connected` from `_last_reading_time`; any
   block-specific state caches).

---

## Stage 3 — Tests

### `tests/gui/shell/overlays/test_<block>.py` (NEW)

<List test categories with case count. Minimum categories:>

- Smoke / structure
- Public API
- DS compliance (no legacy tokens via import-check)
- Connection gating
- <Block-specific functional behaviors>

Use **plain-Python stubs** for `ZmqCommandWorker`. MagicMock across
Qt signal boundary segfaults (lesson from II.2). Pattern:

```python
class _StubWorker:
    def __init__(self, *a, **kw) -> None:
        class _FakeSignal:
            def connect(self, *_a) -> None:
                return None
        self.finished = _FakeSignal()
    def start(self) -> None:
        return None
    def isRunning(self) -> bool:
        return False
```

**Offscreen Qt quirk:** use `isHidden()` not `isVisible()` for
visibility assertions when the widget's top-level isn't shown
(lesson from II.5 amend).

**Pre-test connect guard:** if overlay gates controls on
`set_connected`, call `panel.set_connected(True)` before testing
any button click — otherwise clicks are no-ops (lesson from II.7).

### `tests/gui/shell/test_main_window_v2_<block>_wiring.py` (NEW)

- Connection mirror (tick True/False propagates)
- Readings routing (relevant channels reach overlay; others don't)
- Lazy replay (state replayed on first open)
- <Block-specific wiring>

---

## Stage 4 — Docs

All three updates are mandatory per block (CLAUDE.md doc discipline):

1. **`docs/design-system/cryodaq-primitives/<block>.md`** — follow
   structure of `calibration-panel.md` or `archive-panel.md`.
2. **`CHANGELOG.md`** → `[Unreleased]` → `### Changed` with the
   block summary: what replaces what, which commands/tokens/patterns
   changed, K-rating context, Host Integration Contract confirmation,
   legacy v1 DEPRECATED marker.
3. **`docs/operator_manual.md`** — update section relevant to this
   block's operator-facing workflow. Russian, with all new buttons /
   modes / behaviors described.

---

## Stage 5 — Verify + commit + push

Pre-commit gates (abort on any hit):

```bash
# Forbidden token scan
grep -E 'TEXT_PRIMARY|TEXT_SECONDARY|TEXT_MUTED|TEXT_DISABLED|TEXT_ACCENT|apply_panel_frame_style|apply_button_style|apply_status_label_style|apply_group_box_style|PanelHeader|StatusBanner|build_action_row|create_panel_root|setup_standard_table' \
  src/cryodaq/gui/shell/overlays/<block>.py && echo "FORBIDDEN TOKEN HIT" && exit 1 || echo "forbidden tokens clean"

# Emoji scan
python3 -c "
import re
with open('src/cryodaq/gui/shell/overlays/<block>.py', encoding='utf-8') as f:
    src = f.read()
emoji = re.findall(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF\u2713]', src)
if emoji: raise SystemExit(f'EMOJI FOUND: {emoji}')
print('emoji clean')
"

# Hardcoded hex scan (OK only inside PLOT_LINE_PALETTE indexing)
grep -E '#[0-9a-fA-F]{6}' src/cryodaq/gui/shell/overlays/<block>.py && echo "HEX HIT — review" || echo "hex clean"

# Ruff
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src/cryodaq/gui/shell/overlays/<block>.py tests/gui/shell/overlays/test_<block>.py tests/gui/shell/test_main_window_v2_<block>_wiring.py

# Targeted tests only (CI budget rule — full suite runs in architect's
# parallel terminal, not here)
.venv/bin/pytest tests/gui/shell/overlays/test_<block>.py \
  tests/gui/shell/test_main_window_v2_<block>_wiring.py \
  --tb=short -q
```

Commit message template:

```
feat(ui): <BLOCK_ID> <Short Title> — DS v1.0.1

<2-3 sentences: what changed, why it matters, K-criticality link>

Host Integration Contract wired. Targeted tests: N passed.
Legacy <v1 path> marked DEPRECATED (Phase III.3 removal).
```

Push to `origin master`.

---

## Stage 6 — Codex self-review (autonomous)

Invoke `/codex` per `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` with model
override `gpt-5.4` + reasoning `high`. Verify response header shows
gpt-5.4 (NOT o3) before trusting verdict.

Prompt template below (substitute SHA and block context):

```
Model: gpt-5.4
Reasoning effort: high

Working dir: /Users/vladimir/Projects/cryodaq
Role: read-only code review. Do NOT modify files.

Review HEAD commit <SHA> — <BLOCK_ID> <Short Title>.

Context: <one paragraph pulled from the block's Goal section>.

Project invariants that MUST hold:
1. No blocking I/O on GUI thread.
2. Russian operator text throughout overlay.
3. UTF-8 without BOM in Python sources.
4. DS v1.0.1 tokens only; zero legacy token/helper hits.
5. No emoji, no hardcoded hex outside PLOT_LINE_PALETTE.
6. <BLOCK-SPECIFIC invariant>.

Focus questions:
1. **DS compliance** — grep-verify zero legacy tokens / helpers /
   emoji / hex in `src/cryodaq/gui/shell/overlays/<block>.py`.
2. **<Block-specific: feature preservation / command wiring /
   workflow correctness>** — walk through what to check.
3. **Host Integration Contract** — verify `_tick_status` mirror,
   `_dispatch_reading` routing (if applicable), `_ensure_overlay`
   replay all present.
4. **Test coverage** — overlay tests ≥<N> cases covering <list
   categories>; wiring tests ≥<M> cases.
5. **<Block-specific safety / data-integrity question>**.
6. **Legacy disposition** — v1 widget has DEPRECATED marker.

Process: git show HEAD; read touched files fully; cross-reference
<relevant engine/backend files>; grep for forbidden patterns.

Output format:
- First line: PASS or FAIL
- Findings by severity: CRITICAL / HIGH / MEDIUM / LOW with
  file:line + one-sentence reason + suggested fix
- If PASS, list residual risks worth tracking

Do not create new tests or propose refactors. <N>-minute cap.
```

### Handling Codex verdict

**PASS** → Report final SHA + PASS summary + any residual risks.
Block closed. Remove this spec file:
```bash
rm CC_PROMPT_<BLOCK_ID>_<SHORT_TITLE>.md
```

**FAIL** → Classify each finding per playbook decision tree:

- **CRITICAL / HIGH** → autonomous amend.
- **MEDIUM, <3 files, clearly-scoped** → autonomous amend.
- **MEDIUM, broader scope** → surface to architect.
- **LOW, trivial** → autonomous amend.
- **LOW, non-trivial** → residual risks, close.
- **Design-decision FAIL** → STOP + surface.

Amend commit semantics:

- If HEAD == block commit → `git commit --amend` + `git push --force-with-lease`.
- If HEAD != block commit (intervening commits) → follow-up commit
  `fix(ui): <BLOCK_ID> residual — <fix description>` + `git push`.

Re-invoke `/codex` on amended SHA. Max 3 amend cycles. 4th cycle →
STOP, surface to architect: «3 amend cycles without PASS — something
structural is off».

---

## Out of scope

<Explicit list of files / modules / concerns NOT to touch. Be
specific. Example:>

- Do NOT modify `src/cryodaq/analytics/<x>.py` — backend final.
- Do NOT modify `src/cryodaq/engine.py` command handlers.
- Do NOT touch other overlays.
- Do NOT remove the legacy v1 widget; add DEPRECATED marker only.
- Do NOT attempt feature additions beyond the wiring scope described
  in Stage 1.

## Completion criteria

Codex PASS on:

1. DS compliance (zero forbidden token/helper/emoji/hex hits).
2. <Block-specific functional criterion>.
3. Host Integration Contract wired + tested.
4. Tests cover <specified categories>.
5. Legacy v1 marked DEPRECATED.
6. DS spec + CHANGELOG + operator manual updated.
7. Targeted tests pass; ruff clean.

---

## Final cleanup

After Codex PASS, delete spec file from repo root.
```

---

## Per-block customization checklist

When drafting a concrete block spec from this template:

- [ ] Replace `<BLOCK_ID>` with e.g. `II.4`, `II.8`, `III.2`.
- [ ] Replace `<Short Title>` with e.g. `AlarmOverlay`, `InstrumentsOverlay`.
- [ ] Replace `<block>` in file paths with actual filename stem.
- [ ] Stage 0: list 3-6 specific files to read with verification questions.
- [ ] Stage 1: describe file structure, components, public API, DS layout.
- [ ] Stage 2: Host Integration Contract — list exact wiring lines in
  `main_window_v2.py`.
- [ ] Stage 3: test counts per category.
- [ ] Stage 4: block-specific CHANGELOG bullet + operator manual
  section number.
- [ ] Stage 6 prompt: fill block-specific invariants and focus
  questions.
- [ ] Out of scope: explicit exclusions for this block.
- [ ] Completion criteria: block-specific functional criterion.

## Anti-patterns to avoid in new specs

1. **Do not include `STOP. Waiting for "continue".`** — retired.
   CC drives through autonomously.
2. **Do not include full pytest suite in Stage 5** — targeted tests
   only per CI budget rule. Architect runs full suite in parallel.
3. **Do not skip the Codex stage.** Every initial block commit gets
   Codex review. No exceptions outside the «NEVER invoke» list in
   the playbook.
4. **Do not default to git amend** without checking HEAD. If
   intervening commits landed (very common between block spec and
   Codex review), use follow-up commit.
5. **Do not specify MagicMock for Qt signal boundaries.** Always
   plain-Python stubs.
6. **Do not forget doc triple (CHANGELOG + README-if-needed +
   operator_manual).** Missing docs = technical debt that compounds.

## Template evolution

When a new pattern emerges (e.g. new DS token category, new test
infrastructure quirk, new workflow lesson), update this file FIRST,
then apply to next spec. Do not let specs drift by ad-hoc additions —
the template is the source of truth for block structure.
