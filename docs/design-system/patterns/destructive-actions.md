---
title: Destructive Actions
keywords: destructive, confirmation, hold-confirm, dialog, irreversible, emergency, abort, delete, safety
applies_to: how to present and confirm actions that are irreversible or safety-critical
status: canonical
references: components/button.md, components/dialog.md, rules/interaction-rules.md, cryodaq-primitives/keithley-panel.md
last_updated: 2026-04-17
---

# Destructive Actions

Rules for actions that cannot be undone and could cause data loss, safety issues, or equipment damage. CryoDAQ has both mundane destructive actions (delete an experiment record) and safety-critical ones (emergency stop of current output on a running experiment). The pattern scales across the severity spectrum — more severe = more layers of protection.

## What counts as destructive

Any action that:
- Cannot be undone by clicking "undo" in the next 5 seconds
- Causes loss of captured data (even if persisted elsewhere, the "current view" is lost)
- Modifies hardware state in a way the operator didn't just do
- Aborts a running process (experiment, calibration, measurement)
- Disconnects a resource currently in use
- Changes permissions, settings, or configuration affecting future runs
- Emits a physical signal to equipment (apply voltage, enable current)

If in doubt, treat as destructive. The cost of over-protecting a safe action is a tiny amount of friction. The cost of under-protecting a destructive action is equipment damage or lost experiment time.

## Three-severity classification

### Level 1 — Low-stakes destructive (undo-able within context)

Examples: clearing operator log filter; resetting chart zoom; canceling an unsaved form.

**Protection:** Secondary button with clear label. No confirmation. Undo is implied (they can redo whatever they just did without consequence).

```python
reset_btn = SecondaryButton("Сбросить фильтр")
reset_btn.clicked.connect(self._reset_filter)
```

### Level 2 — Standard destructive

Examples: delete an archived experiment record; clear an alarm history; remove a saved preset.

**Protection:** DestructiveButton + Dialog confirmation.

Pattern:
```python
delete_btn = DestructiveButton("Удалить")
delete_btn.clicked.connect(self._confirm_delete)

def _confirm_delete(self):
    dialog = Dialog(
        parent=self.window(),
        title="Удалить эксперимент?",
        body=(
            "Запись эксперимента 'calibration_run_042' будет удалена "
            "безвозвратно. Архивные данные останутся."
        ),
        primary_label="Удалить",
        primary_role="destructive",
        cancel_label="Отмена",
        default_focus="cancel",    # DESIGN: RULE-INTER-004 safe default
        icon_status="warning",
    )
    # ... connect finished, wait for accept/reject
```

Key: **default focus on Cancel** (safe direction). Enter key must not trigger destructive.

### Level 3 — Safety-critical destructive

Examples: emergency stop of Keithley output; abort running experiment; disconnect Keithley during active run.

**Protection:** HoldConfirmButton (press-and-hold 1s) + often additional Dialog.

Rationale: a panic click cannot trigger safety-critical action. Operator must deliberately press, hold, and wait — time enough to think "wait, am I sure?"

```python
emergency_btn = HoldConfirmButton("АВАР. ОТКЛ.")
emergency_btn.triggered.connect(self._emergency_stop)
# HoldConfirmButton emits `triggered` only after 1000ms continuous hold.
```

For the most critical actions, layer Dialog on top of HoldConfirmButton:
```python
abort_btn = HoldConfirmButton("Прервать эксперимент")
abort_btn.triggered.connect(self._confirm_abort_dialog)

def _confirm_abort_dialog(self):
    # Hold-confirm already provided deliberate-gesture safety.
    # Dialog adds cognitive "are you sure" layer for high-stakes case.
    dialog = Dialog(
        parent=self.window(),
        title="Прервать эксперимент?",
        body="...",
        primary_label="Прервать",
        primary_role="destructive",
        cancel_label="Отмена",
        default_focus="cancel",
    )
    ...
```

## The two-layer protection pattern

For destructive actions where the consequence is both irreversible AND costly (abort experiment → multi-hour re-run; emergency stop → equipment attention required):

**Layer 1: Deliberate gesture (hold-confirm).** 1-second press-and-hold filters accidental clicks.

**Layer 2: Cognitive confirmation (dialog).** Describes consequences; requires explicit «Подтвердить» / «Прервать» click; default focus on Cancel.

Two layers address two different failure modes:
- Single-click destructive: catches hand slips, pocket-kids, stray cats on keyboard.
- Layered destructive: catches "yeah yeah I know" muscle-memory click-throughs. Forces reading.

## Directional safety

Not all "destructive buttons" are equally risky in both directions:

**Enable-output:** destructive (energizes hardware). Requires confirmation.
**Disable-output:** safe (de-energizes). No confirmation.

**Start experiment:** destructive (engages hardware, starts recording). Requires confirmation.
**Stop experiment:** destructive too (loses time), but DIFFERENTLY destructive — stopping has its own consequences.

When a toggle button flips between two states, each direction has its own protection level. A single button with variable `on_click` per current state is clearer than two separate buttons.

```python
def _toggle_output(self):
    if self._output_enabled:
        # Safe direction — disable immediately
        self.output_toggle.emit(False)
    else:
        # Destructive direction — confirm first
        self._confirm_enable_dialog()
```

## Confirmation dialog content rules

From `components/dialog.md` — but specific to destructive context:

1. **Title is a question.** «Удалить эксперимент?» or «Прервать эксперимент?» — interrogative. Not a statement; not a command.
2. **Body describes what will happen.** Concrete consequence + what's preserved + what's lost. Not «Вы уверены?» — that's content-free.
3. **Primary button label = action verb.** «Удалить», «Прервать», «Включить». Matches title. Not «OK» (meaningless) or «Подтвердить» (weak).
4. **Cancel button is present and focused.** Default focus on Cancel. Enter/Escape both dismiss via Cancel path.
5. **Icon:** use `alert-triangle` with STATUS_WARNING color for standard destructive, STATUS_FAULT for truly dangerous.
6. **No secondary action.** Only Cancel or Primary. Three+ options is a Modal, not a Dialog.

## Copy examples

| Action | Title | Body | Primary | Notes |
|---|---|---|---|---|
| Delete archive record | «Удалить эксперимент?» | «Запись 'calibration_run_042' удалится безвозвратно. Архивные данные SQLite останутся.» | «Удалить» | Default focus: Cancel |
| Abort running experiment | «Прервать эксперимент?» | «Собранные данные сохранятся в архив. Эксперимент завершится сейчас.» | «Прервать» | Layer 1: hold-confirm; Layer 2: dialog |
| Emergency stop (Keithley) | «АВАР. ОТКЛ. (Ctrl+Shift+X)» | — (no dialog; hold-confirm is sole protection for maximum speed) | «ПОДТВЕРДИТЬ (удерживать)» | Single layer; button itself is the protection; also global shortcut |
| Enable SMU output | «Включить выход канала А?» | «Будет подан {setpoint} А на оборудование. Убедитесь, что подключение корректно.» | «Включить» | Default focus: Cancel |
| Disable SMU output | — (no dialog) | — | (button: «Откл выход») | No confirmation — safe direction |
| Disconnect Keithley | «Отключить Keithley?» | «Перед отключением выполнится emergency_off. Активный эксперимент прервётся.» | «Отключить» | |
| Discard form changes | «Закрыть без сохранения?» | «Несохранённые параметры будут потеряны.» | «Закрыть» | Only shown if form has unsaved changes |

## What NOT to protect

Over-protection breeds click-through fatigue. Don't confirm:
- Collapsing a panel (reversible)
- Scrolling / panning / zooming
- Typing in a form (not yet submitted)
- Viewing a record (read-only)
- Opening ToolRail slots
- Dismissing a non-destructive modal
- Clicking a tile for drill-down (reversible — just click Close)

Rule of thumb: if you click it accidentally and the consequence is "oh, I'll click it away again", no confirmation needed.

## Global emergency shortcut

`Ctrl+Shift+X` triggers АВАР. ОТКЛ. from anywhere. This is the one exception to «no shortcut without visible affordance» — emergency stop is too critical to hunt for.

Registration at application level (not panel-local). Always available.

On trigger, it behaves identically to pressing-and-holding the АВАР. ОТКЛ. button: emits emergency_off_requested signal, which the engine handles as immediate hardware-level stop.

No dialog confirmation on Ctrl+Shift+X — the gesture itself is deliberate (three-key combo). Speed matters.

## Keyboard behavior in destructive dialogs

Per RULE-INTER-004:

- **Escape:** dismiss via Cancel. Safe direction.
- **Enter:** trigger whichever button has focus. Since destructive dialogs default-focus Cancel, Enter dismisses safely by default. Operator must deliberately Tab to primary button then press Enter — or just click Primary with mouse.
- **Tab:** move focus to Primary button (operator's path to confirm).
- **Shift+Tab:** back to Cancel.

## Destructive chrome in Buttons

Destructive button visual (from `components/button.md`, Variant 3):
- Background: STATUS_FAULT
- Text: ON_DESTRUCTIVE
- Label UPPERCASE for maximum emergency («АВАР. ОТКЛ.») OR sentence-case verb («Удалить») depending on severity

Don't overuse destructive chrome. Dashboard littered with red buttons becomes either ignored (operator tunes it out) or terrifying (operator afraid to click anything). Reserve for actual destructive actions.

## "Don't show this again" patterns

**Don't implement «Don't show this again» checkboxes.** They create state divergence (operator A never sees warning, operator B does) and training regressions (returning operator forgot what the warning said).

If a dialog is being dismissed-through by the same operator many times per week, the UX is wrong — either the dialog isn't needed, or the action is being triggered too easily. Fix the root cause; don't add opt-out.

## Rules applied

- **RULE-INTER-004** — destructive actions require confirmation
- **RULE-INTER-002** — Escape dismisses overlays (safe direction)
- **RULE-COLOR-007** — DESTRUCTIVE vs STATUS_FAULT distinction (same color, different semantic)
- **RULE-COPY-004** — error / consequence messages must be actionable
- **RULE-COPY-007** — imperative verbs on action buttons

## Common mistakes

1. **Single-click delete.** Operator double-clicks a row to edit; second click triggers delete-on-hover button that popped up. Gone. Always confirm.

2. **Default focus on Primary in destructive dialog.** Operator hits Enter (maybe from keyboard muscle memory) and irreversible action fires. Always default-focus Cancel.

3. **«Вы уверены?» as body.** Content-free. Use concrete consequence description per RULE-COPY-004.

4. **No visible destructive chrome.** «Delete» button styled same as «Save». Operator's eye doesn't register risk. Use DestructiveButton variant.

5. **Every button is destructive.** Overuse turns chrome into noise. Reserve for real destructive actions.

6. **Double-confirmation on low-stakes.** «Удалить фильтр → Подтвердите → Да, удалить → Точно удалить?» Three clicks to clear a filter. Cumulative friction.

7. **No Cancel option.** Dialog with only «Подтвердить» button. Operator wants out → hits X → hidden consequence unclear. Always offer Cancel.

8. **Hold-confirm on a trivial action.** Hold-to-delete a chart legend entry. Overkill. Use Dialog instead.

9. **Destructive action triggering on hover.** Menu item styles destructive-red; hover alone fires. Never. Click (with explicit button press) is minimum.

10. **"Don't ask again" checkboxes.** Creates hidden state; eventual forgetting. Fix root cause instead.

11. **Destructive icon without destructive chrome.** Trash icon on a plain-grey button. Missed visual cue. Pair icon with DestructiveButton styling.

12. **Wrong direction of toggle protection.** Adding hold-confirm to «Disable output». De-energizing is safe; confirming makes operators afraid to turn things off. Only protect the dangerous direction.

## Related patterns

- `patterns/state-visualization.md` — STATUS_FAULT used here and there distinctly
- `patterns/copy-voice.md` — destructive action copy norms (imperative verbs, concrete consequences)
- `cryodaq-primitives/keithley-panel.md` — primary worked example of layered destructive protection
- `components/dialog.md` — Dialog API variants (destructive variant)
- `components/button.md` — DestructiveButton + HoldConfirmButton

## Changelog

- 2026-04-17: Initial version. Three-severity classification. Two-layer protection pattern. Directional safety (enable vs disable toggle). Worked examples. Ctrl+Shift+X global emergency shortcut documented. Anti-pattern list including "Don't show again" rejected.
