# Spec Authoring Checklist

> **Purpose:** Накапливаемый список ловушек которые мы поймали на собственном
> опыте при написании спек для CC. Применяется **до** отправки спеки в CC,
> не после. Каждый промах в Block A → A.9 добавляет одну строку. Через
> несколько блоков чеклист стабилизируется.
>
> **Аудитория:** spec writer (Claude в архитекторской роли). Не для CC, не
> для оператора.
>
> **Не правила, а напоминания.** Каждый пункт можно нарушить осознанно,
> если есть причина. Но просто «забыл» — это та категория ошибок которую
> мы хотим устранить.

---

## Перед написанием спеки

### Контекст

- [ ] Прочитал ли я current state кодовой базы — branch, last commit,
      tests baseline?
- [ ] Знаю ли я что **уже** есть в shell/widgets/core которое спека может
      затронуть? (`view` соответствующих файлов перед написанием)
- [ ] Есть ли downstream consumers того что я меняю? (например, если
      меняю MainWindow — кто его импортирует? launcher.py? gui/app.py?
      tests?)
- [ ] **Pre-spec investigation для крупных блоков** — если блок > 200 строк
      спецификации, я обязан **прочитать** существующий код через view
      (минимум 30 минут) до написания. Иначе спека «теоретическая» и CC
      найдёт недокументированные dependencies.

### Scope discipline

- [ ] Может ли блок быть **меньше**? Если задача звучит как «5 правок
      сразу» — реально нужны все 5 в одном коммите, или можно разбить?
- [ ] Что **точно НЕ** должно меняться? Список «do not touch» в спеке
      обязателен — без него CC уплывает.
- [ ] Есть ли стоп-условия? («stop after X, do not start Y»)
- [ ] **Sub-block strategy для rewrite** — если задача «переписать
      файл/класс с нуля», разбить на 4-8 sub-блоков по visible
      milestones, не один большой блок. Visual review между sub-блоками
      ловит ошибки рано.

---

## Технические грабли Qt / PySide6

### QSS селекторы (Block A.7 lesson)

- [ ] Если custom widget subclass (например `class TopWatchBar(QWidget)`)
      — QSS селектор **должен** ссылаться на Qt base class, не Python
      class name. Qt матчит C++ class names, Python subclasses
      игнорируются.
- [ ] **Правильно:** `QWidget#topWatchBar { ... }` (с object name через
      `setObjectName("topWatchBar")`) или `QWidget { background: ... }`
      на самом виджете через `self.setStyleSheet(...)`
- [ ] **Неправильно:** `TopWatchBar { background: ... }` — Qt не видит
      этот селектор, фон останется прозрачным
- [ ] **Правильнее всего для нового кода**: `setObjectName("widgetName")
      + "#widgetName { ... }"` — это **не каскадирует** на детей и явно
      привязывается к конкретному виджету

### Background и autoFillBackground (Block A.8 lesson)

- [ ] Если виджет должен иметь сплошной background — использовать ИЛИ
      `setAutoFillBackground(True) + palette`, ИЛИ
      `setStyleSheet("background: ...")`, не оба сразу
- [ ] Дочерние виджеты внутри панели по умолчанию должны быть
      **transparent**, иначе возникают seam'ы (рамки видны вокруг каждого
      child)
- [ ] **QSS селектор `QWidget { background: ... }` каскадирует на ВСЕ
      дочерние QLabel, QPushButton и т.д.** — это создаёт визуальные
      seam'ы. Решение: использовать `#objectName` selector чтобы
      ограничить scope только parent виджетом.
- [ ] `setAutoFillBackground(True)` **не пропагируется** на дочерние,
      но child может явно объявить свой background через stylesheet и
      сломать видимость

### setVisible() самопроизвольный (Block A.9 lesson)

- [ ] **Если widget убирается из layout через `.hide()`, проверить, нет
      ли в самом widget методов которые делают `setVisible(True)`** —
      например `KeithleyStrip._refresh_labels()` сам себя вызывал с
      visible=True когда приходили данные, отменяя наш hide()
- [ ] **Орфаны (widget без layout slot) рендерятся в (0, 0)** относительно
      родителя — поверх всего что там есть. Это создаёт «парящие окна».
- [ ] **Правильное решение для orphaned widgets во время transition** —
      no-op stub class через `__getattr__` который absorbs все method
      calls. Никаких QTimer, никаких ZMQ workers, никакого rendering.
      Класс-определения остаются для импортов, instance заменяется на
      stub.

### QTimer / ZMQ workers в `__init__`

- [ ] Если widget в `__init__` запускает `QTimer.singleShot(...)` или
      создаёт `ZmqCommandWorker` — это **создаёт side effects** которые
      переживают теста
- [ ] Eager construction всех таких widget'ов в test runner = тесты
      пересекаются, флаки
- [ ] **Решение:** lazy construction (создавать на первом
      `show_overlay()`), или test fixture stub'ит ZMQ
- [ ] Если CC спрашивает «eager или lazy» — почти всегда **lazy** для
      detail panels, eager только для always-visible chrome

### Worker stacking (Codex Finding 2 from A.8)

- [ ] **Periodic poll workers должны проверять `isFinished()` previous**
      worker перед запуском нового — иначе под slow backend стек worker'ов
      нарастает, дублируя backend requests
- [ ] Pattern:
      ```python
      if self._worker is not None and not self._worker.isFinished():
          return  # skip this tick, previous still in flight
      self._worker = ZmqCommandWorker(...)
      self._worker.finished.connect(...)
      self._worker.start()
      ```

### Embedded mode и multiple entry points

- [ ] CryoDAQ имеет **3 entry points** в `pyproject.toml`:
      `cryodaq` (launcher), `cryodaq-gui` (raw GUI), `cryodaq-engine`
      (headless)
- [ ] Если меняю что-то в `gui/app.py` — обязательно проверить что
      `launcher.py` тоже использует это или его аналог
- [ ] `LauncherWindow` **embed**'ит `MainWindow` через `embedded=True`
      kwarg — любой новый MainWindow class должен принимать этот kwarg
      даже если игнорирует
- [ ] Launcher `embed`'ed mode подразумевает что MainWindow может
      возвращать пустой `menuBar()` / `statusBar()` — launcher это
      должен handle

### Cyrillic и localization

- [ ] **Operator-facing text — только русский.** Это hard rule из
      `CLAUDE.md`, но я систематически забываю напомнить CC
- [ ] **Каждая** спека должна явно указать «all new operator-facing
      strings must be Russian, do not introduce English»
- [ ] **Технические термины** которые остаются английскими (Engine,
      Telegram, SMU, Keithley, LakeShore, GPIB) нужно перечислять явно
      как exception list
- [ ] Cyrillic/Latin homoglyphs (Т vs T, А vs A, С vs C) — катастрофически
      опасны в config files. Если спека касается YAML/config — добавить
      проверку charset
- [ ] **`__getattr__` инстансе initial state** — может быть проще иметь
      инициализированный английский placeholder, проверить что initial
      string тоже на русском (Codex A.8 Finding 6)

### ChannelManager API (discovered Block B prep)

- [ ] **Получить visible каналы:** `mgr.get_all_visible() -> list[str]`
      возвращает короткие IDs (Т1, Т2...). НЕ использовать `visible_channels()`
      — такого метода нет.
- [ ] **Получить display name:** `mgr.get_display_name("Т1") -> "Т1
      Криостат верх"`. Если канал не зарегистрирован — возвращает короткий ID.
- [ ] **Получить группы:** `mgr.get_channels_by_group() -> dict[group_name,
      list[ch_id]]` сохраняет порядок из YAML. Группы:
      «криостат», «компрессор», «оптика», «резерв», «» (пустая).
- [ ] **Подписка на изменения:** `mgr.on_change(callback)` — вызывается
      когда `save()` происходит. Полезно для DynamicSensorGrid чтобы
      перестроить grid при изменении channels.yaml в runtime.
- [ ] **Reading.channel format:** короткий ID `"Т1"` или **полный**
      `"Т1 Криостат верх"` зависит от вызывающего кода. ChannelManager
      handles both через `split(" ")[0]` нормализацию.

### Experiment phases (discovered Block B prep)

- [ ] **Six phases:** `ExperimentPhase` enum в `core/experiment.py:53`
      содержит preparation / vacuum / cooldown / measurement / warmup /
      teardown.
- [ ] **Получить current phase:** `experiment.get_current_phase() -> str
      | None`. None = нет активного эксперимента или фаза не задана.
- [ ] **Advance phase:** `experiment.advance_phase(phase: str, operator: str
      = "")` — manual transition. Auto-correction safety net — это **engine
      work track**, не Phase UI-1 v2 scope.
- [ ] **Через ZMQ:** `{"cmd": "experiment_status"}` возвращает dict с
      `active_experiment`, `current_phase`, `start_time`. Используется
      `TopWatchBar`, `experiment_workspace`, `shift_handover`.

---

## Спека format

### Структура

- [ ] **Branch** явно указан в начале (от какого HEAD создавать или на
      каком continue)
- [ ] **Baseline tests** явно указан (например «840 passed, 6 skipped»)
- [ ] **Goal** одним абзацем — что должно быть видно после блока
- [ ] **Tasks** пронумерованы, каждая task имеет:
  - что меняется
  - почему
  - investigation steps если нужно (для bug fix)
  - verification steps
- [ ] **Out of scope** список — что точно НЕ трогать
- [ ] **Success criteria** проверяемый список
- [ ] **Commit message** дан явно
- [ ] **Stop condition** дан явно — «print BLOCK X COMPLETE, do not start
      next»

### Что НЕ указывать в спеке

- [ ] **Точные пиксельные размеры** — это калибруется на лаб PC, не в
      коде. Использовать «compact / medium / large» или ссылки на
      `theme.SPACE_*` константы
- [ ] **Точную имплементацию** — давать **намерение** и **constraints**,
      не copy-paste код. Иначе CC превращается в text expander
- [ ] **«Try this, if it fails try that»** — разветвления делают спеку
      неоднозначной, CC уплывает на ветке которая ему проще

### Что обязательно указывать

- [ ] **Specific files и line ranges** где это применимо
- [ ] **Exact import paths** для новых модулей
- [ ] **Test expectations** — какие тесты должны добавиться/обновиться,
      какие НЕ должны меняться
- [ ] **Allowed test edits** — обычно «only update assertions on removed
      hex literals to reference theme tokens»
- [ ] **Anti-pattern reminders** — список из этого checklist'а
      применимый к данной спеке (QSS селекторы, child backgrounds, и т.д.)

---

## После того как спека написана

### Self-review checklist

- [ ] Прочитал спеку **с позиции CC** — понятна ли она без моего
      контекста?
- [ ] Прошёл по списку **«ловушки Qt»** выше — все ли применимы?
- [ ] Прошёл по **downstream consumers** — все ли entry points покрыты?
- [ ] Указал ли scope ограничения явно?
- [ ] Указал ли что НЕ трогать?
- [ ] Указал ли stop condition?

### Codex audit (mandatory gate, every block, no exceptions)

Codex audit runs on every block before commit. Not optional. Not
"only for large blocks". Not "skip if confident". Every block.

Why: Codex catches what tests miss — lifecycle leaks (workers, signals,
timers), race conditions, undefined behavior in error paths, defense
gaps in input validation. Tests verify happy path. Codex audits the
non-happy paths.

Empirical evidence: B.6.2 Codex found 1 HIGH (worker memory leak via
unretained ZmqCommandWorker) + 2 MEDIUM (no in-flight guard for
double-click, no validation that stored app_mode is a known value)
that all 14 unit tests passed without catching. Block was Small. Audit
took 2 minutes. Findings shipped clean.

#### Required Codex command

Always use the exact CLI form:

```bash
codex exec -c 'sandbox_permissions=["disk-full-read-access"]' "<audit prompt>"
```

Model and reasoning effort come from `~/.codex/config.toml`:

```toml
model = "gpt-5.4"
model_reasoning_effort = "high"
```

As of 2026-04-15 this is the strongest available Codex model on dev
machine. If config is missing or points to a weaker model — fix
config first. Do not run audits on default `gpt-5`.

NOT:
- `codex exec` without sandbox permissions (cannot read project files)
- `codex exec` on a machine without config.toml model override
  (default gpt-5 is weaker)
- `/codex` (slash command does not exist in CC)
- `codex --model=...` (wrong flag form, use `-c model="..."` if needed)

#### Required audit prompt template

Every audit prompt must include:

1. **Scope:** "Audit unstaged/staged changes for Block X.Y against the
   spec at <path>."
2. **Specific look-fors** for the block category (UI / safety / config
   / etc) — pick from below
3. **Severity scale:** "Report findings in numbered list with severity
   CRITICAL/HIGH/MEDIUM/LOW."
4. **Scope discipline:** "Do not suggest stylistic improvements, only
   correctness defects. Do not modify any files."

#### Universal look-fors (every block)

Include these in every audit prompt regardless of block type:

- Worker / signal / timer lifetime: are new ZmqCommandWorker, QTimer,
  signal connections retained on the parent and cleaned in closeEvent
  or finished handler? (B.6.2 lesson)
- In-flight guards: do periodic or click-triggered async operations
  check whether the previous operation is still in flight before
  starting a new one? (A.8 worker stacking lesson)
- Defense in depth: do validation checks cover unexpected values, not
  just expected ones? (B.6.2 unknown-mode lesson)
- QSS selectors: `#objectName` not Python class name (A.7 lesson)
- Child widget backgrounds: parent QSS does not cascade onto children
  causing seams (A.8 lesson)
- setVisible self-call: hidden orphan widgets do not call
  setVisible(True) themselves on data arrival (A.9 lesson)
- Russian text everywhere user-visible
- Cyrillic Т/А/С vs Latin homoglyphs in any new constants

#### Block-category-specific look-fors

For UI blocks add:
- Color-only state conveyance (must have text label too)
- Cursor change on clickable elements (PointingHandCursor)
- WA_StyledBackground on composite QWidget (B.4.5.2)
- Theme tokens used, no hardcoded hex
- Status meaning: backend truth as source, hidden when unknown

For safety/backend blocks add:
- Async paths shielded from cancellation where appropriate
- Atomic file writes for state persistence
- Error path test coverage
- Logging at appropriate levels

For config/data blocks add:
- Fail-closed defaults
- Schema validation
- Cyrillic homoglyph charset checks

#### Iteration on findings

After Codex output:

- **CRITICAL:** STOP, fix inline, re-run Codex, repeat until 0 CRITICAL
- **HIGH:** fix inline, re-run Codex once to confirm fix is correct, no
  need for full re-audit if no other changes
- **MEDIUM:** fix inline if scoped to the same files, otherwise log to
  block backlog with explicit deferral note in commit message
- **LOW:** log to backlog, no inline fix unless trivial

Block does not commit until 0 CRITICAL and 0 HIGH unaddressed. MEDIUM
deferral must be explicit in commit body, not silent.

#### Backlog format for deferred findings

In commit message body include section:

```
Codex findings deferred:
- MEDIUM: <description> — deferred to <block ID or "backlog general">
- LOW: <description> — deferred to <block ID or "backlog general">
```

If no deferrals — omit section entirely.

---

## Хроника поправок (что было поймано на собственной шкуре)

### Block A
- Забыл указать что `launcher.py` тоже импортирует MainWindow напрямую,
  не через app.py → пользователь видел старый UI при запуске через
  `cryodaq` → Block A.5/A.6 fix

### Block A
- Eager construction всех overlay panels в OverlayContainer создал
  test pollution через `QTimer.singleShot` в их `__init__` → CC
  переключился на lazy construction по своей инициативе → правильное
  решение, но я должен был указать в спеке

### Block A
- Не напомнил про русский язык operator-facing → CC написал «Connected»
  в bottom status bar → Block A.6 fix

### Block A.5
- Не указал что dashboard duplicate header (StatusStrip) теперь висит
  в overview_panel.py поверх watch bar → пользователь видел дубликат →
  Block A.5 fix

### Block A.6
- Launcher embedded mode имеет свой top bar и status bar которые
  визуально дублируют shell v2 chrome → Block A.6 fix через `.hide()`

### Block A.7
- Не подумал про QSS class name selectors → custom widget panels были
  прозрачные, dashboard протекал сквозь них → Block A.7 fix

### Block A.8
- `setAutoFillBackground(True)` belt-and-suspenders в Block A.7 не
  предотвратил seams вокруг child widgets → QSS selector `QWidget
  { background: ... }` каскадировал на детей. Block A.8 fix через
  `#objectName` selector.
- Codex audit (8 findings) показал что не все мои deferred решения
  были корректны — Finding 3 был misclassified как backlog но реально
  визуальный bug (orphan setVisible) → Block A.9 promotion to fix

### Block A.9
- `KeithleyStrip._refresh_labels()` вызывал `setVisible(True)` сам себя
  на data arrival, отменяя `hide()` из Block A → видимый orphan rendering
  в (0,0) поверх T1 → Block A.9 fix через `_OrphanedStub` no-op class

### Block A.9 (positive lesson)
- Codex audit полностью оправдал себя: 8 valid findings, 0 false
  positives, обнаружил bug который объяснял визуальный симптом
  ("5/5 норма") который я списал на warmup → Codex pipeline стал
  обязательным шагом для всех будущих блоков

---

## Категории ошибок

По частоте:

1. **Forgotten downstream consumer** (3 раза) — забыл что что-то ещё
   импортирует/использует то что я меняю
2. **Forgotten Qt platform quirk** (3 раза) — QSS selectors, child
   backgrounds, setVisible self-call
3. **Forgotten convention** (2 раза) — русский язык, eager vs lazy
4. **Missing scope constraint** (1 раз) — CC сделал больше чем я просил
5. **Misclassified severity** (1 раз) — Finding 3 в Codex triage был
   marked как backlog но реально визуальный

**Самая дорогая категория — №1.** Решение: перед каждой спекой делать
`grep -rn "MainWindow\|OverviewPanel\|<class I'm changing>" src/ tests/`
и проверять все callsites.

**Вторая дорогая — №2.** Решение: применить весь раздел «Технические
грабли Qt / PySide6» к каждой спеке которая создаёт новые виджеты.

---

## Команды-помощники

### Перед спекой — найти все downstream consumers

```bash
# для имени класса
grep -rn "ClassName" src/ tests/ --include="*.py"

# для модуля
grep -rn "from cryodaq.gui.module" src/ tests/ --include="*.py"

# для entry points в pyproject.toml
grep -A 5 '\[project.scripts\]' pyproject.toml
```

### После Block — Codex audit prompt template

```bash
codex exec -c 'sandbox_permissions=["disk-full-read-access"]' "Audit recent commits on master against the spec.

Look specifically for:
- QSS selectors using Python class names instead of Qt base class names (use #objectName instead)
- Child widgets with own backgrounds causing visual seams (parent QWidget {} cascade)
- ZMQ worker leaks in widget __init__ methods (eager construction problem)
- Worker stacking under slow backend (no isFinished() check before new poll)
- Embedded mode compatibility with launcher.py (LauncherWindow embeds via embedded=True)
- Russian localization gaps in shell/dashboard directories (any English string is defect)
- setVisible(True) self-call in widgets that should stay hidden (orphan widget anti-pattern)
- QTimer.singleShot lifetime management
- Channel state aggregation correctness through ChannelManager API
- Signal/slot wiring between widgets

Report findings in numbered list with severity CRITICAL/HIGH/MEDIUM/LOW.
Do not suggest stylistic improvements, only correctness defects.
Do not modify any files. This is read-only audit."
```

---

### Block B.6

- L6: Status forwarding pattern — when adding a new field to /status
  payload, reuse existing widget polling/signal mechanism rather than
  creating a new ZMQ command. Found in Block B.5 (Codex audit).
- L7: Phase labels must match across surfaces (TopWatchBar,
  PhaseAwareWidget, ExperimentWorkspace). Resolved permanently by
  extracting `core/phase_labels.py` as canonical source.
- L8: Test the actual call flow, not just the unit. B.6 unit tests
  passed because `_update_mode_badge` was tested directly. Add at
  least one integration-style test that feeds realistic ZMQ responses
  through the full handler (`_on_experiment_result`).
- L9: Destructive actions never default to confirm. QMessageBox
  default button = Отмена для любых переключений которые меняют
  системное состояние (mode switch, experiment finalize, etc.).
  Pattern: click → confirm dialog (default Cancel) → action.
- L16: Design system font tokens fail silently if fonts not actually
  loaded. Qt does font substitution and renders with wrong font.
  B.5.7.2: `addApplicationFont(path)` fails on macOS PySide6, use
  `addApplicationFontFromData(bytes)` instead. Always verify
  QFontDatabase.families() at startup.
- L15: Visual debt sometimes = implementation drift across blocks
  using different mechanisms for same job. B.4 used QFrame rectangles
  for context separators; B.5.7 added VLine widgets for zone
  separators. Two mechanisms = inconsistent visual rhythm. Fix: one
  mechanism per surface. B.5.7.1 consolidated to VLine wrapper +
  middle dot.
- L13: Visual debt accumulates per block and never gets paid by
  itself. After 2-3 UI blocks, run explicit polish pass enforcing
  skill rules. B.5.7 closed 6 issues accumulated over B.5.5+B.5.6.
- L14: Tooltip is for extra info, not primary identification. When
  width permits, prefer inline text over numbers+tooltip. B.5.6
  number-only stepper pills failed glanceability test (operator must
  hover for tooltip = not glanceable). B.5.7 returned short labels.
- L12: Wireframe height estimates are ESTIMATES until visual review.
  B.5.5 followed wireframe literally and produced ~210px widget that
  dominated dashboard. B.5.6 cut to ~55px after seeing actual render.
  Override wireframe density estimates with explicit max-height caps.
- L11: For widget rewrites spanning multiple modes/states, extract
  reusable primitives FIRST (HeroReadout, EtaDisplay etc), then
  compose. B.5.5 created 3 reusable primitives serving 6 modes —
  cleaner than 6 standalone implementations, reusable in B.10.
- L10: Codex audit is non-negotiable per block, regardless of size or
  confidence. B.6.2 Small block: 14 unit tests passed, Codex (gpt-5.4,
  reasoning_effort=high via config.toml) caught 1 HIGH worker leak +
  2 MEDIUM (race + undefined behavior). Empirical base rate of catches
  is too high to skip on any block. Always run with strongest model
  (verify config.toml), always block commit on CRITICAL/HIGH.

## Living document

Каждый новый промах добавляет строку в «Хроника поправок» и, если это
систематическая ошибка, новый пункт в один из верхних разделов.

Цель: через 5 блоков большинство грабель будет покрыто, и спеки начнут
проходить с первого раза без мини-блоков-фиксов.
