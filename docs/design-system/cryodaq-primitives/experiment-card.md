---
title: ExperimentCard
keywords: experiment, card, active-experiment, phase, dashboard, tile, metadata, elapsed
applies_to: compound widget showing active experiment metadata + phase progression
status: active
implements: src/cryodaq/gui/dashboard/experiment_card.py (Phase B.6 — dashboard variant)
last_updated: 2026-04-17
references: rules/data-display-rules.md, rules/surface-rules.md, patterns/real-time-data.md
---

# ExperimentCard

Compound widget showing the currently-active experiment's metadata, phase progression, and key vital. The dashboard's "there is currently an experiment running" signal.

> **Implementation status.** The shipped dashboard variant at
> `src/cryodaq/gui/dashboard/experiment_card.py` is aligned with this
> spec: header row with UPPERCASE category + experiment name + mode
> badge (STATUS_OK / STATUS_CAUTION mirroring TopWatchBar) + tabular
> elapsed time, compact `PhaseStepper`, two-line vitals (target
> channel Т11 / Т12 + pressure in Cyrillic мбар), actions row
> («Подробнее» → `open_requested`, «Завершить» → `finalize_requested`),
> empty state with «Создать эксперимент» → `create_requested`, and
> 3px STATUS_FAULT left border on faulted. Target-channel validation
> at `ExperimentCardData` construction enforces the positionally-fixed
> reference-channel invariant (#4). The overlay variant with full
> PhaseStepper + advance / abort controls is still tracked as later
> Phase II work; today the dashboard tile emits `open_requested` and
> the parent shell hosts the existing `experiment_overlay.py`.

**When to use:**
- Dashboard: one ExperimentCard visible when an experiment is active
- Experiment overlay: expanded version with all metadata + controls

**When NOT to use:**
- Historical experiment review — use Archive panel with list
- Multiple concurrent experiments — CryoDAQ product model is one-at-a-time, this card reflects that invariant
- Generic card for other domains — use `Card`

## Domain invariant (architect-level)

Per CryoDAQ product model: **one experiment = one ExperimentCard**, and during an active experiment exactly one card is open. Card lifecycle matches experiment lifecycle.

«Эксперимент» mode = card shows real data and contributes to archive. «Отладка» mode = card shows data but does NOT create archive records. Mode comes from `TopWatchBar`'s ModeBadge; ExperimentCard reflects the mode in its header treatment.

## Anatomy (dashboard variant)

```
┌──────────────────────────────────────────────────────────────────────┐
│  ◀── Card frame (RADIUS_LG, SPACE_5 padding, SURFACE_CARD)          │
│                                                                      │
│  ЭКСПЕРИМЕНТ                               ● Эксперимент  ● 47 мин  │
│  calibration_run_042                       ▲               ▲         │
│                                            │               │         │
│                                     mode badge     elapsed time     │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                                                               │   │
│  │  ●─────●─────●─────●─────○─────○                              │   │  ◀── PhaseStepper
│  │  Готов Ох-е Захол  ИЗМ-Е  Отогр Завер                         │   │     (compact variant)
│  │                                                                │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │                                                            │     │
│  │  Т11 (целевой канал):  4.21 K                              │     │  ◀── key vital
│  │  Давление:             1.23e-06 мбар                       │     │     (domain-specific
│  │                                                            │     │      subset of
│  └────────────────────────────────────────────────────────────┘     │      TopWatchBar)
│                                                                      │
│  [ Открыть  →]                                                       │  ◀── link to overlay
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Card frame** | Yes | Card base with standard chrome |
| **Header row** | Yes | Category label («ЭКСПЕРИМЕНТ») + mode badge + elapsed time |
| **Experiment name** | Yes | operator-assigned name (calibration_run_042) |
| **PhaseStepper (compact)** | Yes | Compact stepper showing current phase |
| **Key vitals row** | Yes | Target channel value + pressure — domain-specific subset |
| **Open-overlay link** | Dashboard variant | Button to expand into full experiment overlay |
| **Action buttons** | Overlay variant | Advance, Abort (hold-confirm), Export, etc. |

## Invariants

1. **Inherits Card invariants.** Single surface, symmetric padding, RADIUS_LG, transparent children. (RULE-SURF-001..007)
2. **Mode badge mirrors TopWatchBar.** Don't invent new mode colors; defer to the same source of truth.
3. **Elapsed time uses tabular mono.** Prevents jitter as seconds tick. (RULE-TYPO-003)
4. **Target channel is a positionally fixed reference channel** (Т11 or Т12) — physically immovable on the second stage (nitrogen plate). Required for quantitative decisions because thresholds based on relocatable channels lose meaning between experiments. Other channels can be shown as context but not as target for alarm thresholds.
5. **Phase stepper uses `compact=True` in dashboard variant.** Full stepper in overlay variant.
6. **Experiment name is operator-assigned freeform text.** May contain Latin chars (calibration_run_042), Cyrillic («Калибровка 2026-04»), or mix. Don't force Cyrillic-only. Apply same RULE-COPY-001 ONLY to channel IDs, not experiment names.
7. **No destructive controls in dashboard variant.** Destructive actions (abort) live in the overlay variant, not the dashboard tile.
8. **Real-time data updates ≤ 2Hz.** (RULE-DATA-002)
9. **Fault elevates card chrome.** If experiment enters fault state, add 3px left border STATUS_FAULT to card (equivalent to sensor cell fault pattern).
10. **Open-overlay link opens modal drill-down.** Uses Modal with DrillDownBreadcrumb `Дашборд / Эксперимент calibration_run_042`.

## API (proposed)

```python
# src/cryodaq/gui/widgets/experiment_card.py

@dataclass
class ExperimentSnapshot:
    name: str                     # operator-assigned
    mode: str                     # "experiment" | "debug"
    started_at: datetime
    phase_state: PhaseState       # feeds into PhaseStepper
    target_channel_id: str        # "Т11" or "Т12" — positionally fixed reference channel
    target_channel_value: float
    target_channel_unit: str      # typically "K"
    pressure_mbar: float | None
    faulted: bool


class ExperimentCard(Card):
    """Compound widget — active experiment overview."""
    
    open_requested = Signal()    # dashboard variant: user wants overlay
    advance_requested = Signal() # overlay variant: user advances phase
    abort_requested = Signal()   # overlay variant: user aborts (after confirm)
    
    def __init__(
        self,
        phases: list[PhaseDef],   # full phase list for stepper
        parent: QWidget | None = None,
        *,
        variant: str = "dashboard",  # "dashboard" | "overlay"
    ) -> None: ...
    
    def set_snapshot(self, snapshot: ExperimentSnapshot) -> None: ...
    def set_active_experiment(self, active: bool) -> None:
        """Switch between 'experiment running' and 'no active experiment' display."""
```

## Reference implementation (dashboard variant)

```python
class ExperimentCard(Card):
    open_requested = Signal()
    advance_requested = Signal()
    abort_requested = Signal()
    
    def __init__(self, phases, parent=None, *, variant="dashboard"):
        super().__init__(parent, surface="card")
        self._variant = variant
        self._phases = phases
        
        # Build header
        header = self._build_header()
        self.set_header(header)
        
        # Build content
        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        
        # DESIGN: RULE-SURF-006 radius cascade — stepper sits inside card
        self._stepper = PhaseStepper(
            phases=phases,
            show_manual_controls=(variant == "overlay"),
            compact=(variant == "dashboard"),
        )
        self._stepper.advance_requested.connect(self.advance_requested)
        self._stepper.abort_requested.connect(self._confirm_abort)
        col.addWidget(self._stepper)
        
        # Key vitals
        self._vitals_widget = self._build_vitals_row()
        col.addWidget(self._vitals_widget)
        
        # Open-overlay link (dashboard variant only)
        if variant == "dashboard":
            open_btn = GhostButton("Открыть →")
            open_btn.clicked.connect(self.open_requested)
            col.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignLeft)
        
        self.set_content(content)
    
    def _build_header(self) -> QWidget:
        # DESIGN: RULE-SURF-004 single baseline
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_3)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        # Category + name
        left = QWidget()
        left_col = QVBoxLayout(left)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(0)
        
        # DESIGN: RULE-TYPO-008 UPPERCASE category
        category = QLabel("ЭКСПЕРИМЕНТ")
        cat_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        cat_font.setWeight(theme.FONT_LABEL_WEIGHT)
        cat_font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing, 0.05 * theme.FONT_LABEL_SIZE
        )
        category.setFont(cat_font)
        category.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        left_col.addWidget(category)
        
        self._name_label = QLabel("—")
        name_font = QFont(theme.FONT_BODY, theme.FONT_TITLE_SIZE)
        name_font.setWeight(theme.FONT_TITLE_WEIGHT)
        self._name_label.setFont(name_font)
        self._name_label.setStyleSheet(f"color: {theme.FOREGROUND};")
        left_col.addWidget(self._name_label)
        
        layout.addWidget(left, 1)  # expand
        
        # Mode + elapsed
        right = QWidget()
        right_row = QHBoxLayout(right)
        right_row.setContentsMargins(0, 0, 0, 0)
        right_row.setSpacing(theme.SPACE_3)
        right_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        self._mode_indicator = InlineIndicator("Эксперимент", "ok")
        right_row.addWidget(self._mode_indicator)
        
        # DESIGN: RULE-TYPO-003 tnum for elapsed
        self._elapsed_label = QLabel("— мин")
        elapsed_font = QFont(theme.FONT_MONO, theme.FONT_LABEL_SIZE)
        elapsed_font.setFeature("tnum", 1)
        elapsed_font.setFeature("liga", 0)
        self._elapsed_label.setFont(elapsed_font)
        self._elapsed_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        right_row.addWidget(self._elapsed_label)
        
        layout.addWidget(right, 0)
        return row
    
    def _build_vitals_row(self) -> QWidget:
        row = QWidget()
        col = QVBoxLayout(row)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)
        
        # DESIGN: RULE-COPY-001 Cyrillic Т, RULE-COPY-006 units
        self._target_line = QLabel("Т11 (целевой канал): —")
        self._pressure_line = QLabel("Давление: —")
        
        vital_font = QFont(theme.FONT_MONO, theme.FONT_LABEL_SIZE)
        vital_font.setFeature("tnum", 1)
        vital_font.setFeature("liga", 0)
        for lbl in (self._target_line, self._pressure_line):
            lbl.setFont(vital_font)
            lbl.setStyleSheet(f"color: {theme.FOREGROUND};")
            col.addWidget(lbl)
        
        return row
    
    def set_snapshot(self, snapshot: ExperimentSnapshot) -> None:
        # DESIGN: RULE-DATA-001 atomic
        self._name_label.setText(snapshot.name)
        
        # Mode display — mirrors TopWatchBar ModeBadge
        mode_label, mode_status = {
            "experiment": ("Эксперимент", "ok"),
            "debug":      ("Отладка",     "caution"),
        }.get(snapshot.mode, (snapshot.mode, "stale"))
        self._mode_indicator.set(mode_label, mode_status)
        
        # Elapsed time
        elapsed = datetime.now(snapshot.started_at.tzinfo) - snapshot.started_at
        minutes = int(elapsed.total_seconds() / 60)
        self._elapsed_label.setText(f"{minutes} мин")
        
        # Phase stepper
        self._stepper.set_state(snapshot.phase_state)
        
        # Vitals
        target_formatted = f"{snapshot.target_channel_value:.2f} {snapshot.target_channel_unit}"
        self._target_line.setText(
            f"{snapshot.target_channel_id} (целевой канал): {target_formatted}"
        )
        if snapshot.pressure_mbar is not None:
            self._pressure_line.setText(f"Давление: {snapshot.pressure_mbar:.2e} мбар")
        else:
            self._pressure_line.setText("Давление: —")
        
        # Fault chrome
        self._apply_fault_chrome(snapshot.faulted)
    
    def _apply_fault_chrome(self, faulted: bool) -> None:
        """Add red left border if faulted."""
        # DESIGN: RULE-A11Y-002 — border is extra channel beyond PhaseStepper fault state
        if faulted:
            # Augment card frame stylesheet — may need to apply to inner frame
            self._card_frame.setStyleSheet(
                self._card_frame.styleSheet()
                + f"\n#panelCardFrame {{ border-left: 3px solid {theme.STATUS_FAULT}; }}"
            )
        # else revert to default (implementation specific — re-apply base style)
    
    def _confirm_abort(self) -> None:
        # DESIGN: RULE-INTER-004 — destructive requires confirmation
        # PhaseStepper's HoldConfirmButton already provides hold-to-confirm safety.
        # Additional Dialog for extra safety on experiment abort:
        dialog = Dialog(
            parent=self.window(),
            title="Прервать эксперимент?",
            body=(
                "Собранные данные будут сохранены в архив. "
                "Вернуться к текущему эксперименту будет невозможно."
            ),
            primary_label="Прервать",
            primary_role="destructive",
            cancel_label="Отмена",
            default_focus="cancel",
        )
        def on_result(result: str):
            if result == Dialog.ACCEPTED:
                self.abort_requested.emit()
        dialog.finished.connect(on_result)
        dialog.open()
```

## Dashboard vs Overlay variant

| Feature | Dashboard | Overlay |
|---|---|---|
| PhaseStepper | compact=True | compact=False (full) |
| Advance button | hidden | visible |
| Abort button | hidden | visible (with confirmation) |
| Vitals count | 2 (target + pressure) | 5+ (all relevant channels) |
| Size | 1 grid cell (4-6 col_span typical) | Modal full-width |
| Open-overlay link | visible | N/A |

The overlay is opened from the dashboard variant via `open_requested` signal → MainWindow opens a Modal containing the overlay-variant ExperimentCard.

## States

| State | Treatment |
|---|---|
| **No active experiment** | Card shows empty state: «Нет активного эксперимента» + button «Начать эксперимент» (opens Create Experiment modal) |
| **Active, healthy** | Normal chrome + STATUS_OK mode badge + live values |
| **Active, faulted** | 3px STATUS_FAULT left border + phase stepper shows faulted node + mode stays visible |
| **Active, debug mode** | Mode badge STATUS_CAUTION (amber); data displayed same but operator knows no archive |
| **Completing / closing** | Brief transition state (few seconds) then empty state |

## Common mistakes

1. **Using a relocatable channel as target.** Т5 as target — its physical position may differ across experiments, so thresholds built on it are not reproducible. Target must be Т11 or Т12 (positionally fixed). Enforce at ExperimentSnapshot validation level.

2. **Inventing new mode color.** Using custom blue for mode — should mirror TopWatchBar source of truth. STATUS_OK for Experiment, STATUS_CAUTION for Debug.

3. **Non-tnum elapsed counter.** «43 мин» → «44 мин» with digits shifting. FONT_MONO + tnum.

4. **Hiding when no experiment.** Card disappears from dashboard layout when no experiment. Breaks grid composition. Show empty state instead.

5. **Destructive abort in dashboard variant.** Dashboard cards are read-only overviews; destructive action lives in full overlay. Avoids accidental tab-to-button + Enter from dashboard.

6. **Phase stepper showing 12 phases.** Experiment phases are typically 6 (B.5) or 7 (B.5.5). Too many phases → reduce / group.

7. **Target channel value in STATUS_FAULT color.** Fails body contrast. Use FOREGROUND value + border fault channel per RULE-A11Y-003.

8. **Name truncation mid-word.** If experiment name is long («calibration_run_042_retry_v2»), use ellipsize or wrap, not sudden clip.

9. **Name input not sanitized.** Operator enters whitespace-only or 200-char name. Validate at creation time — at display time, just render what's there.

10. **Multiple ExperimentCard instances on dashboard.** Product model = one active experiment. Only one ExperimentCard visible.

## Related components

- `cryodaq-primitives/phase-stepper.md` — Embedded child
- `cryodaq-primitives/top-watch-bar.md` — Source of truth for mode
- `components/modal.md` — Overlay variant is hosted in Modal
- `components/dialog.md` — Abort confirmation
- `components/card.md` — Base primitive

## Changelog

- 2026-04-17: Initial version. Dashboard + Overlay variants. Target channel restricted to Т11 / Т12 — positionally fixed reference channels (second stage, nitrogen plate). Mode mirrors TopWatchBar. Fault chrome via 3px left border. Compact PhaseStepper for dashboard per Phase B.5.6. Abort uses Dialog-level confirmation on top of HoldConfirmButton hold safety.
