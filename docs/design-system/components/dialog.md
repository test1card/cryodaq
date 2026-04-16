---
title: Dialog
keywords: dialog, alert, confirm, prompt, question, modal, message, qmessagebox
applies_to: simple Q&A overlays with fixed title / body / actions structure
status: partial
implements: QMessageBox usage in legacy dialogs; purpose-built replacement proposed
last_updated: 2026-04-17
references: rules/interaction-rules.md, rules/color-rules.md, components/modal.md
---

# Dialog

Small overlay with title + body + 1-2 action buttons. The Q&A primitive — use when asking operator a single question or delivering a short message.

**When to use:**
- Simple confirmations: «Завершить эксперимент?»
- Alerts that require acknowledgement: «Keithley отключён. Эксперимент будет остановлен.»
- Final-step confirmations for destructive actions (alongside hold-confirm button pattern)
- Blocking error messages that must be dismissed before operator continues

**When NOT to use:**
- Rich structured confirmations with multiple options / context — use `Modal`
- Forms with multiple fields — use `Modal`
- Transient non-blocking notifications — use `Toast`
- Inline validation errors — use `InputField` error state
- Contextual menus — use `Popover`

## Dialog vs Modal — what's the difference?

| Property | Dialog | Modal |
|---|---|---|
| Structure | Fixed: title + body + actions | Flexible: any content |
| Size | Small (typically 400-560px wide) | Up to ~1400px (proposed `OVERLAY_MAX_WIDTH`) |
| Typical content | Short message + 1-2 buttons | Forms, drill-down detail, bento grids |
| Backdrop dismisses? | No (protects against accidental dismiss of question) | Often yes (configurable) |
| Use frequency | Many — one per question | Fewer — drill-down navigation |

A Dialog is a specialized Modal with opinionated structure. Use Dialog when the interaction is "system asks, operator answers"; use Modal when the interaction is "navigate into detail" or "fill multi-part form".

## Anatomy

```
         ┌─────────────────────────────────────┐
         │ ◀── dialog card                     │
         │     bg: SURFACE_ELEVATED             │
         │     radius: RADIUS_LG                │
         │     padding: SPACE_5                 │
         │                                      │
         │  ┌───────────────────────────────┐   │
         │  │ Title                         │   │ ◀── FONT_TITLE (22px semibold)
         │  │                               │   │     FOREGROUND color
         │  └───────────────────────────────┘   │
         │                                      │ ◀── SPACE_3 gap
         │  ┌───────────────────────────────┐   │
         │  │ Body text — 1-3 sentences     │   │ ◀── FONT_BODY
         │  │ explaining context / impact   │   │     FOREGROUND color
         │  │                               │   │
         │  └───────────────────────────────┘   │
         │                                      │ ◀── SPACE_5 gap (actions separated)
         │  ┌───────────────────────────────┐   │
         │  │            [Cancel]  [Apply]  │   │ ◀── Actions right-aligned
         │  │                               │   │     SPACE_2 between buttons
         │  └───────────────────────────────┘   │
         │                                      │
         └─────────────────────────────────────┘
           Width: 400-560 typical
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Dialog card** | Yes | Card surface — inherits Card anatomy + Modal behavior |
| **Title** | Yes | Short question or statement, FONT_TITLE preset |
| **Body** | Optional | 1-3 sentences of context. Actionable per RULE-COPY-004 |
| **Icon** | Optional | Status icon (alert/info/warning) next to title for destructive / faulted contexts |
| **Actions row** | Yes | 1 or 2 buttons: primary action + optional cancel |

## Invariants

1. **Inherits all Modal invariants** — single surface, symmetric padding, Escape dismisses, focus trap, animation asymmetry.
2. **Title is interrogative for questions, statement for alerts.** «Завершить эксперимент?» (question), «Keithley отключён» (statement). (RULE-COPY-007)
3. **Body is actionable.** Describes what happened + what will happen next. (RULE-COPY-004)
4. **Action buttons right-aligned.** Cancel first (left), primary action second (right). Latin pattern: destination on right.
5. **Default focus on CANCEL** for destructive actions. Safe default — Enter key triggers safe action, not destructive.
6. **Backdrop does NOT dismiss.** Dialog is a blocking question — accidental backdrop click shouldn't close without answer.
7. **Max 2 buttons.** 3+ buttons = this should be a Modal with richer choice presentation, or a dropdown.
8. **One dialog at a time.** Don't stack dialogs. If action opens another dialog, close first one first.

## States

| State | Visual treatment |
|---|---|
| Default (open) | Backdrop dimmed, card centered, focus trapped inside |
| Focus on Cancel (default) | 2px ACCENT ring on Cancel button (RULE-A11Y-001) |
| Focus on Primary | 2px ACCENT ring on Primary button (operator Tabbed to it) |
| Hover on button | Button hover state per `components/button.md` |
| Disabled action | Primary button dimmed (TEXT_DISABLED), not focusable |
| Destructive variant | Primary button uses DESTRUCTIVE chrome; default focus on Cancel (RULE-INTER-004) |
| Dismiss (Escape) | Overlay closes; focus returns to opener (RULE-INTER-002) |

## API (proposed)

```python
# src/cryodaq/gui/widgets/dialog.py  (proposed)

class Dialog(QWidget):
    """Title + body + actions overlay. Thin wrapper around ModalCard."""
    
    # Response constants
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DISMISSED = "dismissed"
    
    finished = Signal(str)  # emits ACCEPTED / REJECTED / DISMISSED
    
    def __init__(
        self,
        parent: QWidget,
        title: str,
        body: str = "",
        *,
        primary_label: str = "OK",
        primary_role: str = "default",     # "default" | "destructive"
        cancel_label: str | None = "Отмена",  # None for alert-only
        icon_status: str | None = None,    # "warning" | "caution" | "fault" | None
        default_focus: str = "cancel",     # "cancel" | "primary"
    ) -> None: ...

    @classmethod
    def confirm(cls, parent, title, body, **kwargs) -> str:
        """Show dialog modally, return response."""
        dialog = cls(parent, title, body, **kwargs)
        dialog.open()
        # Block on event loop, return finished value
        ...
```

## Variants

### Variant 1: Simple confirmation (safe default)

Non-destructive action requiring confirm.

```python
# DESIGN: RULE-COPY-007 (interrogative title)
dialog = Dialog(
    parent=self,
    title="Сохранить изменения?",
    body="Несохранённые параметры датчика Т11 будут утеряны при переходе.",
    primary_label="Сохранить",
    cancel_label="Отмена",
    default_focus="primary",  # safe default — Enter saves
)
dialog.finished.connect(self._on_save_confirm_result)
dialog.open()
```

### Variant 2: Destructive confirmation

Irreversible action. Cancel is default focus for safety.

```python
# DESIGN: RULE-COPY-004 (actionable), RULE-INTER-004 (destructive confirmation)
dialog = Dialog(
    parent=self,
    title="Удалить эксперимент?",
    body=(
        "Эксперимент 'calibration_run_042' будет удалён безвозвратно. "
        "Архивные данные сохранятся, но текущая сессия будет утеряна."
    ),
    primary_label="Удалить",
    primary_role="destructive",
    cancel_label="Отмена",
    icon_status="fault",
    default_focus="cancel",  # safe default — Enter cancels
)
dialog.finished.connect(self._on_delete_confirm_result)
dialog.open()
```

### Variant 3: Alert (acknowledge-only)

Notification requiring acknowledgement. No cancel — only OK.

```python
dialog = Dialog(
    parent=self,
    title="Keithley отключён",
    body=(
        "Потеряна связь с источником тока. Эксперимент автоматически "
        "переведён в безопасное состояние. Проверьте USB-подключение."
    ),
    primary_label="Понятно",
    cancel_label=None,  # alert — no cancel
    icon_status="fault",
)
dialog.open()
```

### Variant 4: Status info

Lightweight info / status check. Info status icon.

```python
dialog = Dialog(
    parent=self,
    title="Калибровка устарела",
    body=(
        "Последняя калибровка датчика Т5 выполнена 97 дней назад. "
        "Рекомендуется повторить до начала эксперимента."
    ),
    primary_label="Открыть калибровку",
    cancel_label="Позже",
    icon_status="warning",
    default_focus="primary",
)
```

## Actions row layout

```python
# DESIGN: RULE-SPACE-001 (SPACE_2 between related buttons)
actions = QWidget()
actions_layout = QHBoxLayout(actions)
actions_layout.setContentsMargins(0, 0, 0, 0)
actions_layout.setSpacing(theme.SPACE_2)
actions_layout.addStretch()  # push buttons right

if cancel_label:
    self._cancel_button = GhostButton(cancel_label)
    self._cancel_button.clicked.connect(lambda: self._finish(self.REJECTED))
    actions_layout.addWidget(self._cancel_button)

if primary_role == "destructive":
    self._primary_button = DestructiveButton(primary_label)
else:
    self._primary_button = SecondaryButton(primary_label)
self._primary_button.clicked.connect(lambda: self._finish(self.ACCEPTED))
actions_layout.addWidget(self._primary_button)

# Set focus per config
if default_focus == "cancel" and cancel_label:
    self._cancel_button.setFocus()
else:
    self._primary_button.setFocus()
```

## Icon header pattern (with status icon)

```python
# DESIGN: RULE-A11Y-002 (icon + title redundant channels)
header = QWidget()
header_layout = QHBoxLayout(header)
header_layout.setContentsMargins(0, 0, 0, 0)
header_layout.setSpacing(theme.SPACE_2)
header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

if icon_status:
    icon_color = {
        "info": theme.STATUS_INFO,
        "warning": theme.STATUS_WARNING,
        "caution": theme.STATUS_CAUTION,
        "fault": theme.STATUS_FAULT,
    }[icon_status]
    icon = QLabel()
    icon.setPixmap(
        load_colored_icon("alert-triangle", color=icon_color)
          .pixmap(theme.ICON_SIZE_MD, theme.ICON_SIZE_MD)  # proposed: theme.ICON_SIZE_MD — not yet in theme.py
    )
    icon.setFixedSize(theme.ICON_SIZE_MD, theme.ICON_SIZE_MD)  # proposed: theme.ICON_SIZE_MD — not yet in theme.py
    header_layout.addWidget(icon)

title_widget = QLabel(title)
title_font = QFont(theme.FONT_BODY, theme.FONT_TITLE_SIZE)
title_font.setWeight(theme.FONT_TITLE_WEIGHT)
title_widget.setFont(title_font)
header_layout.addWidget(title_widget)
header_layout.addStretch()
```

## Common mistakes

1. **Generic title «Ошибка» + generic body «Произошла ошибка».** Fails RULE-COPY-004 (actionable). Concrete: «Keithley отключён» + specific next step.

2. **3+ buttons.** «Сохранить / Не сохранять / Отмена» is a discoverable anti-pattern but tempts. Collapse: offer "Сохранить" primary + "Отмена" (with optional checkbox «Не сохранять изменения»). Or use a Modal with richer options.

3. **Primary focus on destructive.** Enter key should never trigger destructive by default. `default_focus="cancel"` for destructive variants.

4. **No body on alert.** Title alone is cryptic. Body provides context and next step (RULE-COPY-004).

5. **Stacking dialogs.** Dialog A opens Dialog B. Collapse into one decision or sequence flows properly.

6. **Dialog body with 5 paragraphs.** Dialog is for short messages. If it needs long explanation, use Modal with proper content layout.

7. **Backdrop dismisses.** Operator clicks outside, dialog closes with no answer recorded. For questions, always require button click.

8. **No icon for safety-critical alerts.** Fault alert without red triangle icon misses visual scan priority. RULE-A11Y-002 redundant channel.

## Related components

- `components/modal.md` — Richer / larger alternative
- `components/toast.md` — Non-blocking transient alternative
- `components/popover.md` — Anchored contextual alternative
- `components/button.md` — Dialog actions use SecondaryButton, GhostButton, DestructiveButton variants
- `patterns/destructive-actions.md` — Full pattern for confirming destructive operations

## Changelog

- 2026-04-17: Initial version. 4 variants (safe confirm, destructive confirm, alert, info status). `Dialog` class proposed — current code uses QMessageBox ad-hoc; consolidation to typed Dialog class tracked as Phase II.
- 2026-04-17 (v1.0.1): Added explicit States matrix (FR-015 / FR-020) — default-open, Cancel-focus, Primary-focus, hover, disabled, destructive variant, Escape dismiss.
