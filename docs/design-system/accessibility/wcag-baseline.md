---
title: WCAG Baseline
keywords: wcag, accessibility, aa, level, conformance, baseline, target, guidelines, wcag-2-2
applies_to: accessibility conformance target and scope across the product
status: canonical
references: rules/accessibility-rules.md, tokens/colors.md, patterns/state-visualization.md
external_reference: WCAG 2.2 (W3C Recommendation, October 2023)
last_updated: 2026-04-17
---

# WCAG Baseline

Accessibility conformance target and scope. Establishes which WCAG 2.2 criteria CryoDAQ commits to meeting, which are out of scope, and why.

## Target: WCAG 2.2 Level AA

**CryoDAQ targets WCAG 2.2 Level AA conformance** across all operator-facing UI. Level AAA is aspirational — some criteria are met, others not practicable given the industrial visual vocabulary (dense dashboards, technical data readouts).

Rationale for AA:
- AA is the widely-accepted industrial accessibility floor (Section 508, EN 301 549, industrial HMI standards align)
- Full AAA would require simplifications (fewer dense data displays, larger fonts) that conflict with the product's utility
- AA contrast + keyboard + non-text alternatives covers most practical operator needs

Level A is the minimum-viable floor; Level AA is the target; specific AAA improvements are opportunistic.

## Scope boundaries

**In scope:**
- All operator-facing text, controls, and data displays
- Keyboard operability across the full application
- Focus visibility
- Color-independent state signaling
- Screen-reader basic support (labels on all interactive elements, ARIA where needed)
- Respecting OS-level accessibility preferences (reduced motion)

**Out of scope (explicitly):**
- **Phone / tablet / touch-screen use** — CryoDAQ is desktop-only per `patterns/responsive-behavior.md`; touch target sizing (WCAG 2.5.5) not applicable
- **Print / PDF export accessibility** — reports go through separate pipeline, not governed by this baseline
- **Video / audio content** — CryoDAQ has none; 1.2.x criteria not applicable
- **Natural-language screen reader narration of charts** — chart data is complex numeric; operators read values directly; alt-text describes chart category/axes, not per-point data
- **Full AAA contrast** — some status colors (STATUS_FAULT, STATUS_INFO) do not reach AAA; documented in `accessibility/contrast-matrix.md`

## Criterion-by-criterion commitment (Level AA, adjusted for scope)

### Perceivable

| WCAG | Commitment | CryoDAQ mapping |
|---|---|---|
| **1.1.1 Non-text Content** (A) | Met | All icons have label OR tooltip (RULE-INTER-008); decorative SVG uses aria-hidden |
| **1.2.x Media** (A, AA) | N/A | No audio/video content |
| **1.3.1 Info and Relationships** (A) | Met | ARIA roles on semantic groups; form labels via QLabel + buddy widget |
| **1.3.2 Meaningful Sequence** (A) | Met | Tab order matches visual order (RULE-A11Y-006); F-pattern scan aligned with DOM |
| **1.3.3 Sensory Characteristics** (A) | Met | Instructions never refer only to shape/color/position (e.g., "click the red one") |
| **1.3.4 Orientation** (AA) | Met | Desktop-only; landscape is the only orientation |
| **1.3.5 Identify Input Purpose** (AA) | Met | Form autocomplete attributes where applicable (operator login, if present) |
| **1.4.1 Use of Color** (A) | Met | RULE-A11Y-002 two-channel signaling enforces this |
| **1.4.2 Audio Control** (A) | N/A | No audio |
| **1.4.3 Contrast (Minimum)** (AA) | Met for text; documented exceptions for status chrome | See `contrast-matrix.md` |
| **1.4.4 Resize Text** (AA) | Partial | Qt apps support OS-level DPI scaling; manual text zoom within app is out of scope |
| **1.4.5 Images of Text** (AA) | Met | No images of text; all text is actual text |
| **1.4.10 Reflow** (AA) | Partial | Desktop-only; reflow at 320px viewport not targeted |
| **1.4.11 Non-text Contrast** (AA) | Partial | BORDER token fails 3:1 against BACKGROUND (actual: 1.46:1). Card shapes provide visual grouping; focus rings use ACCENT (6.48:1, passes). Functional boundaries use ACCENT or STATUS_* with proven higher ratios. See `contrast-matrix.md`. |
| **1.4.12 Text Spacing** (AA) | Met | Line-height 1.5 default; letter-spacing adjustable via QSS |
| **1.4.13 Content on Hover / Focus** (AA) | Met | Tooltips dismissible (Escape closes); persistent while hovered; not obscuring |

### Operable

| WCAG | Commitment | CryoDAQ mapping |
|---|---|---|
| **2.1.1 Keyboard** (A) | Met | All functionality keyboard-accessible per `accessibility/keyboard-navigation.md` |
| **2.1.2 No Keyboard Trap** (A) | Met | Modal overlays trap focus deliberately; Escape always releases |
| **2.1.4 Character Key Shortcuts** (A) | Met | All shortcuts use modifier keys (Ctrl, Alt, Shift) — no single-character shortcuts |
| **2.2.1 Timing Adjustable** (A) | Partial | Hold-confirm buttons have fixed 1s timing; this is a safety feature, not a usability constraint — documented exception |
| **2.2.2 Pause, Stop, Hide** (A) | Met | No content auto-updates faster than 5s intervals; charts updating at 2 Hz are operator-requested not page-animation |
| **2.3.1 Three Flashes** (A) | Met | RULE-INTER-006 forbids flashing; fault indication is instant and persistent, not flashing |
| **2.4.1 Bypass Blocks** (A) | Met | ToolRail provides section navigation (Ctrl+[1-9] shortcuts) |
| **2.4.2 Page Titled** (A) | Met | QMainWindow.windowTitle always set and specific |
| **2.4.3 Focus Order** (A) | Met | Tab order matches visual (RULE-A11Y-006) |
| **2.4.4 Link Purpose** (A) | Met | Buttons have imperative verb labels (RULE-COPY-007); no «Click here» |
| **2.4.5 Multiple Ways** (AA) | Partial | ToolRail + keyboard shortcuts; no search functionality across panels |
| **2.4.6 Headings and Labels** (AA) | Met | Panel titles are descriptive; UPPERCASE category labels distinguish sections |
| **2.4.7 Focus Visible** (AA) | Met | 2px ACCENT focus ring per RULE-A11Y-001; see `focus-management.md` |
| **2.4.11 Focus Not Obscured** (AA, new in 2.2) | Met | Modal / Drawer overlays do not partially obscure the focused element within; focus-trap keeps it visible |
| **2.5.1 Pointer Gestures** (A) | Met | No multi-point / path-based gestures; click / double-click only |
| **2.5.2 Pointer Cancellation** (A) | Met | Destructive actions use up-event (mouseReleaseEvent), allow cancellation by dragging off |
| **2.5.3 Label in Name** (A) | Met | Accessible name matches visible label |
| **2.5.4 Motion Actuation** (A) | N/A | No motion-triggered actions |
| **2.5.7 Dragging Movements** (AA, new in 2.2) | Met | No drag-only interactions — all drag operations (rare in CryoDAQ) have click-based alternatives |
| **2.5.8 Target Size (Minimum)** (AA, new in 2.2) | Met | Interactive targets ≥ 24×24 CSS pixels; default ROW_HEIGHT 36 and icon-button 32×32 both exceed |

### Understandable

| WCAG | Commitment | CryoDAQ mapping |
|---|---|---|
| **3.1.1 Language of Page** (A) | Met | `lang="ru"` on shell; technical Latin subsystem names (Engine, ZMQ) within Russian context don't count as language switch |
| **3.1.2 Language of Parts** (AA) | Partial | Subsystem names in Latin not individually marked; operators treat them as borrowed vocabulary |
| **3.2.1 On Focus** (A) | Met | Focus never triggers context change; opening a panel requires click or Enter |
| **3.2.2 On Input** (A) | Met | Form input changes never trigger navigation |
| **3.2.3 Consistent Navigation** (AA) | Met | ToolRail identical across all screens; BottomStatusBar identical |
| **3.2.4 Consistent Identification** (AA) | Met | Same icon + label for same concept across surfaces (cross-surface-consistency.md) |
| **3.3.1 Error Identification** (A) | Met | Input fields show inline error text (RULE-COPY-004) |
| **3.3.2 Labels or Instructions** (A) | Met | QLabel + buddy for every input; no placeholder-as-label |
| **3.3.3 Error Suggestion** (AA) | Met | Errors describe cause + remedy: «Введите число от 0 до 1» |
| **3.3.4 Error Prevention (Legal, Financial, Data)** (AA) | Met | Destructive actions use Dialog confirmation (destructive-actions.md) |
| **3.3.7 Redundant Entry** (A, new in 2.2) | Met | No forms require repeat entry of previously-provided info |
| **3.3.8 Accessible Authentication (Minimum)** (AA, new in 2.2) | N/A | No authentication in operator shell |

### Robust

| WCAG | Commitment | CryoDAQ mapping |
|---|---|---|
| **4.1.1 Parsing** (A) — deprecated in 2.2 | N/A | |
| **4.1.2 Name, Role, Value** (A) | Met | QAccessible interface implemented via PySide6 widgets; custom widgets set accessibleName |
| **4.1.3 Status Messages** (AA) | Met | Alarms fire as Toasts with role="alert"; FSM state changes announced via BottomStatusBar (QAccessible notification) |

## AAA aspirations (opportunistic, not committed)

- **1.4.6 Contrast (Enhanced)** — 7:1 for body text. FOREGROUND (16.04:1) meets AAA; MUTED_FOREGROUND (5.95:1), ACCENT (6.48:1), COLD_HIGHLIGHT (5.46:1), and every STATUS_* token miss AAA on body; intentional for dense data display
- **2.4.8 Location** — breadcrumb provides location within drill-downs, but top-level nav doesn't
- **3.3.5 Help** — tooltips provide contextual help; not a full help system
- **2.2.4 Interruptions** — alarms use Toast (dismissable) + persistent state; critical faults require ack (blocking Dialog) by design

If operator reports specific AAA gaps in production, they can be addressed case-by-case.

## Operator-specific accommodations (not WCAG-coded)

Beyond WCAG, CryoDAQ has operator-specific accessibility features:

- **Russian as primary language** — not an accessibility criterion but a usability must-have for lab operators
- **Lab lighting conditions** — dark theme is the product default because most lab monitors run dim; bright/light theme not yet offered
- **Long-session fatigue** — small font discipline balanced against density (RULE-TYPO-009); reduced-motion respect prevents fatigue from flickering animations
- **Color-blindness** — two-channel signaling (RULE-A11Y-002) ensures operators with any color-vision profile can distinguish states; contrast-matrix documents specific hues

## Testing methodology

Per `governance/testing-strategy.md` (Batch 6):

1. **Automated** — token lint (no raw hex); contrast lint against BACKGROUND; focus-ring presence check via Qt test harness
2. **Manual** — keyboard-only operation through full task flow (create experiment → run → abort); screen-reader sanity check (NVDA on Windows)
3. **Browser/Qt** — visual regression via screenshot diff at known viewport sizes

## Conformance statement

When conformance is claimed externally (e.g., procurement doc, accessibility report):

> CryoDAQ operator UI conforms to WCAG 2.2 Level AA with the following documented exceptions:
> - Resize Text (1.4.4): supported via OS-level DPI scaling; manual in-app text zoom not provided
> - Reflow (1.4.10): desktop-only product; reflow at 320px not targeted
> - Non-text Contrast (1.4.11): BORDER token falls below 3:1 against BACKGROUND (1.46:1) — treated as visual grouping only; functional boundaries (focus, active, fault) use ACCENT or STATUS_* tokens that meet or exceed 3:1
> - Status color contrast: STATUS_FAULT and STATUS_INFO used as chrome accents only, not for body text; body text uses FOREGROUND (16.04:1 contrast)

## Rules applied

- **RULE-A11Y-001** — focus ring visibility (feeds 2.4.7)
- **RULE-A11Y-002** — two-channel status signaling (feeds 1.4.1, 3.3.1)
- **RULE-A11Y-003** — contrast-aware color application (feeds 1.4.3)
- **RULE-A11Y-005** — accessible names on custom widgets (feeds 4.1.2)
- **RULE-A11Y-006** — tab order matches visual (feeds 2.4.3)
- **RULE-A11Y-007** — reduced-motion respect (feeds 2.3.1 adjacent)
- **RULE-A11Y-008** — error identification inline (feeds 3.3.1, 3.3.3)

## Common mistakes

1. **Claiming AA without testing.** WCAG conformance requires actual verification, not just intent. Run keyboard walkthrough + screen-reader check before stamping AA.

2. **Treating AAA as "nice-to-have" to ignore.** AAA criteria often catch real problems (contrast issues, navigation gaps). Aspire; document gaps honestly.

3. **Confusing AA with full accessibility.** AA is a floor, not ceiling. Operator accommodations (language, lighting, fatigue) are separate requirements beyond WCAG.

4. **Skipping 2.2 new criteria.** 2.4.11 (focus not obscured), 2.5.7 (dragging), 2.5.8 (target size), 3.3.7 (redundant entry), 3.3.8 (auth) — all new in WCAG 2.2. Evaluate explicitly.

5. **Treating out-of-scope as N/A globally.** 1.2.x (media) truly N/A; but 1.4.4 (resize text) is "partial" not N/A — desktop still benefits from OS DPI scaling awareness.

## Related patterns

- `accessibility/keyboard-navigation.md` — 2.1.x and 2.4.x details
- `accessibility/focus-management.md` — 2.4.7, 2.4.11 details
- `accessibility/contrast-matrix.md` — 1.4.3, 1.4.11 specific token pairs
- `accessibility/reduced-motion.md` — animation-related criteria

## Changelog

- 2026-04-17: Initial version. WCAG 2.2 Level AA target committed. Scope boundaries explicit (desktop-only, no audio/video). Criterion-by-criterion commitment table with CryoDAQ mapping. AAA aspirations opportunistic not committed.
- 2026-04-17: v1.0.1 — Downgraded 1.4.11 Non-text Contrast from Met to Partial after recomputing BORDER contrast (1.46:1 actual vs 3.1:1 claimed). Corrected 1.4.6 AAA note (FOREGROUND meets AAA; MUTED_FOREGROUND misses). Added 1.4.11 exception to external conformance statement.
