---
title: PhaseStepper
keywords: phase, stepper, progression, experiment, cooldown, warmup, sequence, active-phase, next-phase
applies_to: sequential phase progression display + manual advance controls
status: active
implements: src/cryodaq/gui/dashboard/phase_stepper.py (extracted Phase B.5.5); src/cryodaq/gui/dashboard/phase_aware_widget.py (parent; Phase B.5 + B.5.6)
last_updated: 2026-04-17
references: rules/color-rules.md, rules/typography-rules.md, tokens/colors.md
---

# PhaseStepper

Horizontal sequential phase indicator with optional manual-advance controls. Shows the experiment's current phase, preceding completed phases, and upcoming phases in a single timeline.

> **Implementation status.** The shipped phase stepper at
> `src/cryodaq/gui/dashboard/phase_stepper.py` is aligned with
> this spec. Active phase uses `STATUS_OK`.

**When to use:**
- Experiment card / experiment overlay — showing progression through phases
- Compact inline use in dashboard tile (`compact=True` variant per B.5.6)
- Any process that is known to proceed through a fixed ordered sequence

**When NOT to use:**
- Parallel sibling navigation (not sequential) — use `TabGroup`
- Hierarchical path (navigation history, not progression) — use `Breadcrumb`
- Progress percentage for one action — use progress bar widget
- User-selectable tabs — stepper is system-driven progression, not manual selection

## Why this is NOT a breadcrumb or tab group

- **Breadcrumb** = path taken (hierarchical, navigable back)
- **Tab group** = parallel siblings (only one viewable at a time, user-selectable)
- **PhaseStepper** = sequential progression (linear, system-driven, past phases completed, current phase active, future phases pending)

Each has distinct visual convention. Stepper uses arrows/connectors between nodes.

## Anatomy (6-phase canonical)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│   ●──────●──────●──────●──────○──────○                                       │
│   │      │      │      │      │      │                                       │
│   │      │      │      │      │      │                                       │
│  Готов  Ох-е  Захол  Изм-е  Отогр  Завер                                    │
│                       ▲                                                      │
│                       └── active phase label UPPERCASE + STATUS_OK         │
│                                                                              │
│                       [  Следующая фаза →  ]                                 │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
  ◀── node: 12-16px circle
  ◀── connector: 2px line between nodes
  ◀── gap node-to-label: SPACE_1
  ◀── gap between stepper nodes: stretch (equal)
```

Phase count is parameterizable (typically 6 for canonical experiment, 7 for extended with preflight). B.5 implemented 6; B.5.5 extended.

## Visual states

| Phase state | Node | Connector | Label |
|---|---|---|---|
| **Completed** (past) | ●  filled STATUS_OK, check icon optional | solid STATUS_OK line | MUTED_FOREGROUND, regular |
| **Active** (current) | ●  filled STATUS_OK, glow or ring | STATUS_OK line before it; BORDER line after | FOREGROUND, UPPERCASE + letter-spacing, semibold |
| **Pending** (future) | ○  outlined BORDER, hollow | BORDER dashed or dim line | MUTED_FOREGROUND, regular |
| **Skipped** | ○  outlined STATUS_STALE, dim | BORDER line | STATUS_STALE |
| **Faulted** | ✕ filled STATUS_FAULT | STATUS_FAULT line into it | STATUS_FAULT label |

**Color caveat:** Active phase uses STATUS_OK (green) — NOT ACCENT. This is the correction from Phase 0 dashboard PhaseStepper which used ACCENT violet; that violated RULE-COLOR-004. «Active operational state» IS a status (running healthy), hence STATUS_OK. If ACCENT were used, it would mean selection — but operator did not select this phase, the system transitioned to it.

## Parts

| Part | Required | Description |
|---|---|---|
| **Node** | Each phase | Circle indicating phase state |
| **Connector** | Between adjacent nodes | Line showing progression |
| **Label** | Each phase | Short phase name below (or above) the node |
| **Advance button** | Optional | Manual «Следующая фаза →» to trigger ZMQ `experiment.advance_phase` |
| **Abort button** | Optional | «Прервать» — destructive, requires confirmation per RULE-INTER-004 |

## Invariants

1. **Active phase uses STATUS_OK, NOT ACCENT.** Per Phase 0 product decision. (RULE-COLOR-002, RULE-COLOR-004)
2. **Fixed phase order.** Phases cannot be reordered at runtime. The sequence is part of the experiment template.
3. **Only one phase active at a time.** No two circles simultaneously filled green with glow. Progression is strictly sequential.
4. **Labels UPPERCASE for active phase only** per RULE-TYPO-008 category emphasis. Other labels sentence case.
5. **Manual advance button only active when allowed.** Automatic transitions (time-based, temperature-based) do not need manual advance; button hidden or disabled. Button enable state driven by engine.
6. **Abort requires confirmation.** Destructive action — uses Dialog confirm or hold-confirm button pattern. (RULE-INTER-004)
7. **Connector color matches the earlier-side node state.** Line between completed and active is STATUS_OK (from completed node). Line between active and pending is BORDER (toward pending side).
8. **No animation on state transitions by default.** Phase transitions are important events; snapping is OK. Optional fade for visual polish, 200ms max.
9. **Cyrillic labels only.** Phase names are Russian: «Готов», «Охлаждение», «Захолаживание», «Измерение», «Отогрев», «Завершение». (RULE-COPY-001, RULE-COPY-002)
10. **Keyboard: Right arrow advances if allowed.** Optional — depends on context (works in experiment card overlay where stepper has focus).

## API

```python
# src/cryodaq/gui/dashboard/phase_stepper.py  (extracted from phase_aware_widget.py)

@dataclass
class PhaseDef:
    key: str           # "cooldown"
    label: str         # "Захолаживание"
    
@dataclass
class PhaseState:
    active_index: int           # current phase index
    completed_indices: set[int] # phases marked done (usually 0..active_index-1)
    skipped_indices: set[int]   # explicitly skipped phases
    faulted: bool               # True if current phase is in fault


class PhaseStepper(QWidget):
    """Sequential phase progression widget."""
    
    advance_requested = Signal()   # emitted on «Следующая фаза» click
    abort_requested = Signal()     # emitted on «Прервать» (after confirmation)
    
    def __init__(
        self,
        phases: list[PhaseDef],
        parent: QWidget | None = None,
        *,
        show_manual_controls: bool = True,
        compact: bool = False,
    ) -> None: ...
    
    def set_state(self, state: PhaseState) -> None: ...
    def set_advance_enabled(self, enabled: bool) -> None:
        """Enable/disable the advance button based on engine signal."""
```

## Node widget reference

```python
class PhaseNode(QWidget):
    """Single node + label. Auto-sizes to content."""
    
    STATE_PENDING = "pending"
    STATE_ACTIVE = "active"
    STATE_COMPLETED = "completed"
    STATE_SKIPPED = "skipped"
    STATE_FAULTED = "faulted"
    
    NODE_SIZE_DEFAULT = 16
    NODE_SIZE_COMPACT = 12
    
    def __init__(self, label: str, parent=None, *, compact=False):
        super().__init__(parent)
        self._compact = compact
        self._label_text = label
        self._state = self.STATE_PENDING
        
        self.setMinimumWidth(80)
        
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_1)
        col.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        
        node_size = self.NODE_SIZE_COMPACT if compact else self.NODE_SIZE_DEFAULT
        self._node = QFrame()
        self._node.setFixedSize(node_size, node_size)
        col.addWidget(self._node, 0, Qt.AlignmentFlag.AlignHCenter)
        
        self._label = QLabel(label)
        self._label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(self._label)
        
        self._apply_state()
    
    def set_state(self, state: str) -> None:
        self._state = state
        self._apply_state()
    
    def _apply_state(self) -> None:
        # DESIGN: RULE-COLOR-002, RULE-COLOR-004 (active=STATUS_OK not ACCENT)
        node_style_map = {
            "pending":   (theme.SURFACE_CARD, theme.BORDER),         # hollow, BORDER
            "active":    (theme.STATUS_OK,    theme.STATUS_OK),       # filled OK
            "completed": (theme.STATUS_OK,    theme.STATUS_OK),       # filled OK (same as active but label differs)
            "skipped":   (theme.SURFACE_CARD, theme.STATUS_STALE),    # hollow stale
            "faulted":   (theme.STATUS_FAULT, theme.STATUS_FAULT),   # filled fault
        }
        bg, border = node_style_map[self._state]
        node_size = self.NODE_SIZE_COMPACT if self._compact else self.NODE_SIZE_DEFAULT
        
        self._node.setStyleSheet(f"""
            QFrame {{
                background: {bg};
                border: 2px solid {border};
                border-radius: {node_size // 2}px;
            }}
        """)
        
        # Label styling per state
        if self._state == "active":
            # DESIGN: RULE-TYPO-005 (Cyrillic letter-spacing), RULE-TYPO-008 (UPPERCASE for active)
            self._label.setText(self._label_text.upper())
            active_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
            active_font.setWeight(theme.FONT_WEIGHT_SEMIBOLD)
            active_font.setLetterSpacing(
                QFont.SpacingType.AbsoluteSpacing, 0.05 * theme.FONT_LABEL_SIZE
            )
            self._label.setFont(active_font)
            self._label.setStyleSheet(f"color: {theme.FOREGROUND};")
        elif self._state == "faulted":
            self._label.setText(self._label_text)
            self._label.setStyleSheet(f"color: {theme.STATUS_FAULT};")
        elif self._state == "skipped":
            self._label.setText(self._label_text)
            self._label.setStyleSheet(f"color: {theme.STATUS_STALE};")
        else:
            # DESIGN: RULE-COPY-003 sentence case
            self._label.setText(self._label_text)
            default_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
            self._label.setFont(default_font)
            self._label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
```

## Connector widget reference

```python
class PhaseConnector(QFrame):
    """Line between two phase nodes."""
    
    def __init__(self, parent=None, *, compact=False):
        super().__init__(parent)
        self.setFixedHeight(2)
        self.setMinimumWidth(40)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._state = "pending"
        self._apply_state()
    
    def set_state(self, state: str) -> None:
        """state reflects the phase preceding this connector."""
        self._state = state
        self._apply_state()
    
    def _apply_state(self) -> None:
        color = {
            "completed": theme.STATUS_OK,
            "active":    theme.STATUS_OK,
            "pending":   theme.BORDER,
            "skipped":   theme.STATUS_STALE,
            "faulted":   theme.STATUS_FAULT,
        }.get(self._state, theme.BORDER)
        self.setStyleSheet(f"QFrame {{ background: {color}; }}")
```

## PhaseStepper reference

```python
class PhaseStepper(QWidget):
    advance_requested = Signal()
    abort_requested = Signal()
    
    def __init__(
        self,
        phases: list[PhaseDef],
        parent=None,
        *,
        show_manual_controls=True,
        compact=False,
    ):
        super().__init__(parent)
        self._phases = phases
        self._compact = compact
        
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACE_4)
        
        # Stepper row
        stepper_row = QHBoxLayout()
        stepper_row.setContentsMargins(0, 0, 0, 0)
        stepper_row.setSpacing(0)
        stepper_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        self._nodes: list[PhaseNode] = []
        self._connectors: list[PhaseConnector] = []
        
        for i, phase in enumerate(phases):
            node = PhaseNode(phase.label, compact=compact)
            self._nodes.append(node)
            stepper_row.addWidget(node, 0, Qt.AlignmentFlag.AlignVCenter)
            
            if i < len(phases) - 1:
                connector = PhaseConnector(compact=compact)
                self._connectors.append(connector)
                stepper_row.addWidget(connector, 1, Qt.AlignmentFlag.AlignVCenter)
        
        outer.addLayout(stepper_row)
        
        # Manual controls (optional)
        if show_manual_controls:
            controls = self._build_controls()
            outer.addWidget(controls)
    
    def _build_controls(self) -> QWidget:
        # DESIGN: RULE-COPY-007 imperative labels
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)
        
        # Abort is destructive — hold-confirm pattern
        self._abort = HoldConfirmButton("Прервать")
        self._abort.triggered.connect(self.abort_requested)
        layout.addWidget(self._abort)
        
        layout.addStretch()
        
        self._advance = SecondaryButton("Следующая фаза →")
        self._advance.clicked.connect(self.advance_requested)
        layout.addWidget(self._advance)
        
        return row
    
    def set_state(self, state: PhaseState) -> None:
        # DESIGN: RULE-DATA-001 atomic
        for i, node in enumerate(self._nodes):
            if state.faulted and i == state.active_index:
                node.set_state("faulted")
            elif i == state.active_index:
                node.set_state("active")
            elif i in state.completed_indices:
                node.set_state("completed")
            elif i in state.skipped_indices:
                node.set_state("skipped")
            else:
                node.set_state("pending")
        
        for i, conn in enumerate(self._connectors):
            # Connector i is between node i and node i+1
            if i < state.active_index:
                conn.set_state("completed")
            else:
                conn.set_state("pending")
        
        # Fault flag overrides
        if state.faulted and state.active_index > 0:
            self._connectors[state.active_index - 1].set_state("faulted")
    
    def set_advance_enabled(self, enabled: bool) -> None:
        if hasattr(self, '_advance'):
            self._advance.setEnabled(enabled)
```

## Compact variant

Per Phase B.5.6, inline use in dashboard tile needs smaller footprint. `compact=True`:

- Node size 12 instead of 16
- Labels FONT_SIZE_XS (11) instead of FONT_LABEL_SIZE (12)
- Manual controls hidden (dashboard tile is read-only; advance done from full experiment card)
- Horizontal only, no vertical variant

## Integration with engine

```
ZMQ PUB from engine:
    topic: experiment.state
    payload: {
        "active_phase": "cooldown",  // or index
        "phase_started_at": 1700000000.0,
        "phase_can_advance": false,  // engine permits manual advance
        "faulted": false
    }
    
GUI ZMQ SUB:
    PhaseStepper.set_state(PhaseState(...))
    PhaseStepper.set_advance_enabled(can_advance)

GUI emits on user action:
    advance_requested -> ZMQ REQ: "experiment.advance_phase"
    abort_requested   -> Dialog confirmation -> ZMQ REQ: "experiment.abort"
```

## Phase naming convention (6-phase canonical)

| Index | Key | Label | Description |
|---|---|---|---|
| 0 | `ready` | Готов | Standby — preconditions met, awaiting operator start |
| 1 | `cooling` | Охлаждение | Initial cooling to setpoint |
| 2 | `cooldown` | Захолаживание | Stabilization at cold temperature |
| 3 | `measurement` | Измерение | Active experiment data collection |
| 4 | `warmup` | Отогрев | Controlled warmup |
| 5 | `complete` | Завершение | Finalization, archive, report |

B.5.5 added 7th phase (`preflight`) before index 0.

## Common mistakes

1. **Active phase in ACCENT (violet).** Violates RULE-COLOR-004. Phase 0 dashboard bug — corrected to STATUS_OK. Active phase IS a status (operational), not a selection.

2. **All phases UPPERCASE.** Over-emphasis. Only active phase uppercase per RULE-TYPO-008 discipline.

3. **Advance button always enabled.** Operator clicks, engine rejects — frustration. Button enable state mirrors engine's `phase_can_advance` signal.

4. **Abort as regular button.** Single click aborts experiment. Violates RULE-INTER-004. Use HoldConfirmButton.

5. **Animated node fill on transition.** Glitch-prone. Atomic is safer.

6. **Connector state from wrong side.** Connector between active and pending: using active side (STATUS_OK) makes upcoming path look "already done". Should use pending side (BORDER).

7. **Latin phase keys in operator-facing labels.** `"cooldown"` shown to operator; should be `«Захолаживание»`. Keys stay internal, labels are Russian.

8. **Too many phases.** 12-phase stepper with tiny nodes and labels. Above ~8 phases, rethink: group phases into meta-stages, or use a dedicated progress page.

9. **Stepper without hint of where we are temporally.** Time-remaining or phase-started-at helpful. Add subtle text near active phase label: «(42 мин)».

10. **Confusing stepper with TabGroup.** Stepper nodes are not clickable for navigation. Don't give them pointer cursor or click handlers for jumping. Manual advance is sequential.

## Related components

- `cryodaq-primitives/experiment-card.md` — Hosts PhaseStepper as primary widget
- `components/tab-group.md` — Parallel siblings (different paradigm)
- `components/breadcrumb.md` — Hierarchical path (different paradigm)
- `components/button.md` — Advance button (Secondary) + Abort (Hold-confirm)

## Changelog

- 2026-04-17: Initial version. Documents Phase B.5 / B.5.5 / B.5.6 implementations. Active phase color corrected to STATUS_OK per Phase 0 product decision (was ACCENT violet). Compact variant for inline dashboard tile use.
