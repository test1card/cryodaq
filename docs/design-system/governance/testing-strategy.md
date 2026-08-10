---
title: Testing Strategy
keywords: testing, lint, token-lint, contrast-check, visual-regression, audit, automation
applies_to: how design-system compliance is verified automatically + manually
status: canonical
references: governance/token-naming.md, governance/versioning.md, accessibility/contrast-matrix.md, accessibility/wcag-baseline.md, ../MANIFEST.md
external_reference: UI UX Pro Max v2.5.0 validate-tokens.cjs pattern
last_updated: 2026-08-10
---

# Testing Strategy

How we verify that CryoDAQ code actually follows the design system. The rules and patterns in this system are only useful if they're enforced. Enforcement comes from three layers: automated linting, external audit, and manual review.

## Shipped F36.6 machine gates

| Gate | Real invocation surface | What it proves |
|---|---|---|
| Same-slice co-versioning | `tests/docs/test_docs_freshness.py::test_design_system_governed_sources_are_coversioned` in the active exact checkout and standalone docs workflow | A mapped shared semantic source cannot move without its canonical spec, an advanced `VERSION`, and a matching `CHANGELOG.md` heading relative to exact `TRUSTED_BASE_SHA` |
| Multi-theme contrast | `tests/gui/test_theme_loader.py::test_machine_accessibility_contrast_contract_matches_all_real_themes` in the `gui` candidate partition | Every declared pair is recomputed from every real `config/themes/*.yaml`; the exact failures must equal the structured exceptions in `MANIFEST.md` |
| Non-color state redundancy | `tests/gui/test_theme_loader.py::test_machine_accessibility_non_color_states_match_real_runtime_contract` in the `gui` candidate partition | Production state mapping retains Russian labels, tokens, accessible labels, and distinct geometry, including the legacy warning-to-caution alias |

These checks cover only mechanical evidence. Whole-shell keyboard and focus traversal, NVDA on the real Windows build, scripted operator tasks, visual judgment, and target-machine performance measurements remain human or environment-specific gates. A screenshot does not close them.

The lint and test snippets below describe intended rule checks. Unless a concrete repository node or tool is named as shipped above, a snippet is an implementation example rather than current CI evidence.

## Three enforcement layers

```
┌──────────────────────────────────────────────────────┐
│  Layer 3: Manual review                              │
│  Operator / architect / designer eyeballs            │
│  Catches: design sensibility, UX flow, judgment      │
├──────────────────────────────────────────────────────┤
│  Layer 2: External audit                                │
│  LLM audit with design system in context             │
│  Catches: rule references, consistency, violations   │
├──────────────────────────────────────────────────────┤
│  Layer 1: Automated linting                          │
│  Python / QSS / JSON regex + AST checks              │
│  Catches: hardcoded hex, missing tokens, syntax      │
└──────────────────────────────────────────────────────┘
```

Each layer catches different failure modes. Relying on any single layer leaves gaps.

## Layer 1: automated linting

### Token lint

Enforce RULE-COLOR-010: all color references go through `theme` module; no raw hex in component code.

```python
# tools/lint_tokens.py
import re
from pathlib import Path

HEX_PATTERN = re.compile(r'#[0-9a-fA-F]{6}')
ALLOWED_FILES = {
    "theme.py",           # tokens are DEFINED here
    "contrast-matrix.md", # documentation
}

def check_file(path: Path) -> list[str]:
    if path.name in ALLOWED_FILES:
        return []
    violations = []
    for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if HEX_PATTERN.search(line):
            if '# DESIGN-ALLOW-HEX' in line:  # escape hatch
                continue
            violations.append(f"{path}:{lineno}: raw hex detected: {line.strip()}")
    return violations

def main():
    root = Path("src/cryodaq/gui")
    all_violations = []
    for py_file in root.rglob("*.py"):
        all_violations.extend(check_file(py_file))
    if all_violations:
        for v in all_violations:
            print(v)
        raise SystemExit(1)
```

Runs as part of `pytest` pre-commit or CI. Fails build on violation.

### STONE_* legacy-usage lint

Flag any new use of deprecated STONE_* tokens:

```python
STONE_PATTERN = re.compile(r'\btheme\.STONE_')

def check_stone_usage(path: Path) -> list[str]:
    """Flag STONE_* references."""
    violations = []
    for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if STONE_PATTERN.search(line):
            violations.append(f"{path}:{lineno}: deprecated STONE_* reference: {line.strip()}")
    return violations
```

Report-only initially (warning), then error once migration reaches 100%.

### Font-size lint

Enforce RULE-TYPO-007: only approved font sizes, no ad-hoc pixel values.

```python
APPROVED_FONT_SIZES = {11, 12, 13, 14, 15, 16, 18, 22, 32}  # from tokens/typography.md
FONT_PATTERN = re.compile(r'font-size:\s*(\d+)px')

def check_font_sizes(path: Path) -> list[str]:
    violations = []
    for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        match = FONT_PATTERN.search(line)
        if match:
            size = int(match.group(1))
            if size not in APPROVED_FONT_SIZES:
                violations.append(f"{path}:{lineno}: font-size {size}px not in token scale")
    return violations
```

### Spacing lint

Enforce RULE-SPACE-001: only approved spacing values (`SPACE_0..SPACE_6`). Catches `margin: 18px` (not 16 or 24).

### Russian-text lint

Catch placeholder-as-label antipatterns (RULE-COPY violations):

```python
# Flag placeholders that read like instructions
INSTRUCTION_PLACEHOLDER_PATTERN = re.compile(r'setPlaceholderText\("Введите')

def check_placeholders(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [match.group(0) for match in INSTRUCTION_PLACEHOLDER_PATTERN.finditer(text)]
```

### Cyrillic Т vs Latin T lint

Catch Latin T in channel IDs:

```python
# Match "T" followed by digit (likely channel ID misspelled)
LATIN_T_CHANNEL = re.compile(r'"T\d+[ "]')

def check_channel_t(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [match.group(0) for match in LATIN_T_CHANNEL.finditer(text)]
```

### Contrast contract (shipped subset)

`MANIFEST.md` declares the exact token pairs, WCAG criterion, threshold, and per-theme exception set. The GUI test loads every real theme pack through the production validator and recomputes every ratio. A newly failing theme, a stale exception, or an exception without scope, rationale, fallback channels, and human verification fails the partition.

This is not a general AST proof of every QSS foreground/background use. Context discovery across arbitrary stylesheets remains review work until a production-path checker exists.

## Layer 2: External audit

The external audit pass operates with the full design system in context. Runs after every design-system-relevant change:

The reviewer is given the changed `src/cryodaq/gui/shell/**/*.py` files with
`docs/design-system/**/*.md` as context and checks rules, patterns and
cross-surface consistency.

The audit specifically checks:
- Does this widget declare its DESIGN: RULE-X comments?
- Do the comments match actual rule enforcement?
- Does this panel follow the scaffolds from `patterns/page-scaffolds.md`?
- Is cross-surface consistency maintained?
- Are state-visualization conventions followed?

The audit produces a report: violations, suggested fixes, rules referenced. Architect reviews and applies.

The external audit runs after each implemented block per the established workflow.

## Layer 3: manual review

Automated + LLM audit catch most issues. Manual review catches what they miss:

1. **Design sensibility** — "this dashboard is technically compliant but feels cluttered"
2. **UX flow** — "operator would have to click 5 times to do X"
3. **Russian idiom correctness** — «тревоги» vs «аварии» — which verb reads right
4. **Operator realism** — "real operator working in Moscow lab at 2am wouldn't use it this way"

Vladimir (architect) + lab operators do manual review at key milestones.

## Test categories

### Visual regression tests

Screenshot diff of rendered widgets:

```python
# tests/gui/test_visual.py
def test_experiment_card_dashboard_variant(qtbot, qapp):
    widget = ExperimentCard(phases=CANONICAL_PHASES, variant="dashboard")
    widget.set_snapshot(SAMPLE_SNAPSHOT)
    widget.show()
    qapp.processEvents()
    
    pixmap = widget.grab()
    pixmap.save("tests/gui/screenshots/_actual_experiment_card_dashboard.png")
    
    reference = QPixmap("tests/gui/screenshots/experiment_card_dashboard.png")
    diff = compare_images(pixmap, reference, tolerance=0.01)
    assert diff < 0.01, f"Visual diff > 1%: {diff}"
```

Reference screenshots tagged to design system version. Regenerate when design-system version bumps.

### Token-usage tests

Verify widgets use tokens, not literals:

```python
def test_keithley_panel_uses_tokens():
    panel = KeithleyPanel()
    stylesheet = panel.styleSheet()
    # Should not contain any hex literal
    assert not re.search(r'#[0-9a-fA-F]{6}', stylesheet)
```

### Rule-compliance tests

Per-rule test that exercises the rule:

```python
def test_rule_color_004_accent_reserved_for_focus():
    """RULE-COLOR-004: ACCENT color only for focus / selection state."""
    # Given: a non-focused button
    btn = SecondaryButton("Test")
    # ACCENT should NOT appear in default style
    assert theme.ACCENT not in btn.styleSheet()
    # Given: focus event
    btn.setFocus()
    # ACCENT now appears (focus ring)
    assert theme.ACCENT in btn.styleSheet() or theme.ACCENT in btn.property("focus_color")
```

### Accessibility tests

```python
def test_dialog_default_focus_cancel():
    """RULE-INTER-004: destructive Dialog default-focuses Cancel."""
    dialog = Dialog(
        title="Delete?",
        body="...",
        primary_role="destructive",
    )
    dialog.show()
    assert dialog.focusWidget() == dialog.cancel_button

def test_modal_escape_dismisses():
    """RULE-INTER-002: Escape dismisses modal."""
    modal = Modal(content=QWidget())
    modal.show()
    QTest.keyClick(modal, Qt.Key_Escape)
    assert not modal.isVisible()
```

### Contrast tests (programmatic)

```python
def test_foreground_on_card_passes_aa():
    """FOREGROUND on CARD surface passes WCAG AA body."""
    ratio = contrast_ratio(theme.FOREGROUND, theme.CARD)
    assert ratio >= 4.5, f"FG on CARD: {ratio:.2f} fails AA"

def test_status_fault_unused_as_body_text():
    """STATUS_FAULT must not be applied as body-text color anywhere."""
    # Scan all .py files for `color: {theme.STATUS_FAULT}` patterns on text-rendering widgets
    ...
```

## Test coverage target

- **Unit test coverage:** ≥ 80% for design-system widget classes
- **Rule coverage:** every RULE-ID has at least one test exercising it
- **Visual regression:** every component file has at least one screenshot test
- **Contrast:** every token pair in matrix has an explicit test or matrix-generation assertion

Not every test in every file, but systematic coverage via centralized fixtures.

## Testing tools

- **pytest** — primary test runner
- **pytest-qt / qtbot** — Qt widget interaction
- **Pillow / opencv-python** — image comparison for visual regression
- **coverage.py** — coverage reports
- **ruff** — general linting (integrated with design-system lint rules)
- Custom scripts in `tools/` for token-lint, contrast-lint, etc.

## CI integration

The real gates are already owned by repository CI:

- `python -m tools.ci_candidate_runner --suite gui` selects the GUI partition that contains the two mechanical accessibility nodes.
- `python -m tools.ci_active_checkout_runner --suite remaining --trusted-base <exact-commit> ...` runs exact-checkout guards, including `tests/docs/test_docs_freshness.py`.
- `.github/workflows/docs-gate.yml` also runs the full docs-freshness file and supplies the immutable pull-request base (or required manual-dispatch base).
- `ruff check --no-cache src/ tests/` remains the repository lint command; it is not a substitute for parsing or for either design-system guard.

## Test failure response

When a test fails:

1. **Automated lint fails:** fix the code. Don't silence the lint.
2. **Rule compliance fails:** either fix code OR argue for rule amendment through `governance/contribution.md`. Don't both at once.
3. **Visual regression fails:** compare diff; if intentional design change, regenerate reference screenshot + changelog entry.
4. **Accessibility test fails:** fix the token/component or amend the exact structured exception with scope, fallback channels, and human verification; prose-only or blanket waivers are not accepted.

## Failure as data

Per vladimir-voice principle (errors as data, not occasions for apology): test failures document where the gap between intent and implementation lives. Don't just fix the one instance; ask whether the same gap exists elsewhere. Update the lint / test / rule to catch the class.

## Rules applied

- **RULE-COLOR-010** — token-based references (enforced via lint)
- **RULE-TYPO-007** — off-scale font sizes protected (enforced via lint)
- **RULE-SPACE-001** — spacing scale (enforced via lint)
- **RULE-COPY-001** — Cyrillic Т (enforced via lint)
- All RULE-* — cumulatively tested via rule-compliance tests

## Common mistakes

1. **Running only automated lint.** LLM audit + manual review catch different issues. Skip those layers and design quality erodes.

2. **Silencing failed lints.** `# noqa`. Forgotten. Accumulates. Only silence with an explicit ticket to fix.

3. **Writing tests after bugs found.** Tests should codify the rules as they're written. Writing tests afterward means gaps stay open until discovered.

4. **Visual regression over-sensitive.** 1px anti-aliasing differences fail tests. Set reasonable tolerance (~1% per image).

5. **Contrast tests on fixed pairs only.** Checking FOREGROUND on BACKGROUND but not on CARD. Matrix should cover all used combinations.

6. **No CI integration.** Tests pass locally; not run in pipeline. Add CI gate that blocks merges on test failure.

7. **External audit as the only check.** Audits miss rule details sometimes; pair with lint to catch mechanical issues.

## Related governance

- `governance/token-naming.md` — token lint subject
- `governance/deprecation-policy.md` — STONE_* legacy-usage lint
- `governance/contribution.md` — new rule → new test required
- `accessibility/contrast-matrix.md` — contrast test baseline data

## Changelog

- 2026-08-10 (v4.2.0): Documented the shipped exact-base co-versioning and real-theme accessibility nodes, structured exceptions, real CI ownership, and the human evidence boundary.

- 2026-04-17: Initial version. Three enforcement layers (lint / audit / manual). Test categories (visual regression / token-usage / rule-compliance / accessibility / contrast). Tooling + CI integration. Failure-as-data principle applied.
