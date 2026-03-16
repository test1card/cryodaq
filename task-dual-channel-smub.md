# Задача: Dual-channel Keithley (smua + smub параллельно) + 3 contract bugs

Две части в одном коммите. Это архитектурное изменение.

---

## ЧАСТЬ А: Dual-channel Keithley smub

### Архитектурные решения (зафиксированы, не обсуждать)

1. **SafetyManager: один global state machine.** FAULT на любом канале → оба OFF. RUNNING = хотя бы один канал активен. `request_run(channel, p, v, i)` и `request_stop(channel)` — per-channel. `emergency_off()` — оба безусловно.

2. **Keithley driver: один инстанс, per-channel runtime.** Один физический прибор = один драйвер. Внутри — `dict[str, ChannelRuntime]` для smua и smub.

3. **TSP: один шаблонный скрипт.** `{SMU}` подставляется перед загрузкой. Два инстанса работают параллельно.

4. **Watchdog: per-channel.** Потеря heartbeat smua → smua OFF, smub продолжает. Потеря heartbeat обоих → FAULT.

---

### A-01. Keithley driver — per-channel runtime

**Файл:** `src/cryodaq/drivers/instruments/keithley_2604b.py`

#### Новый dataclass:

```python
@dataclass
class ChannelRuntime:
    """Runtime state одного SMU канала."""
    smu: str                              # "smua" или "smub"
    p_target: float = 0.0
    v_comp: float = 40.0
    i_comp: float = 1.0
    active: bool = False
    heartbeat_task: asyncio.Task | None = None
    script_running: bool = False
    script_error: str = ""
```

#### Изменения в Keithley2604B:

**Конструктор:**
```python
def __init__(self, name, resource, *, mock=False, on_heartbeat_failure=None):
    ...
    self._channels: dict[str, ChannelRuntime] = {
        "smua": ChannelRuntime(smu="smua"),
        "smub": ChannelRuntime(smu="smub"),
    }
    # Убрать: self._p_target, self._script_running, self._heartbeat_task, self._script_error
    # Всё это теперь в ChannelRuntime
```

**read_channels() — читать оба канала:**
```python
async def read_channels(self) -> list[Reading]:
    readings = []
    for smu_name in ("smua", "smub"):
        # Отправить: print({smu}.measure.iv())
        # Парсить: voltage, current
        # Вычислить: resistance = V/I, power = V*I
        # 4 readings per channel: voltage, current, resistance, power
        # channel format: f"{self.name}/{smu_name}/voltage" etc.
    return readings  # 8 readings total
```

В mock режиме — генерировать данные для обоих каналов. smub mock values могут быть немного другими (offset).

**start_source(channel: str, p_target, v_comp, i_comp):**
```python
async def start_source(self, channel: str, p_target: float, v_comp: float, i_comp: float) -> None:
    """Запустить P=const на указанном канале (smua или smub)."""
    if channel not in self._channels:
        raise ValueError(f"Unknown channel: {channel}")
    rt = self._channels[channel]
    if rt.active:
        raise RuntimeError(f"{channel} already active")
    
    rt.p_target = p_target
    rt.v_comp = v_comp
    rt.i_comp = i_comp
    
    # Загрузить TSP с подстановкой {SMU} → channel
    tsp_code = self._load_tsp_template(channel, p_target, v_comp, i_comp)
    await self._transport.write(tsp_code)
    
    rt.active = True
    rt.script_running = True
    rt.heartbeat_task = asyncio.create_task(
        self._heartbeat_loop(channel), name=f"heartbeat_{channel}"
    )
```

**stop_source(channel: str):**
```python
async def stop_source(self, channel: str) -> None:
    rt = self._channels[channel]
    if not rt.active:
        return
    # Отправить команду остановки для конкретного канала
    await self._transport.write(f"{channel}.source.output = {channel}.OUTPUT_OFF")
    await self._cancel_heartbeat(channel)
    rt.active = False
    rt.script_running = False
    await self._verify_output_off(channel)
```

**emergency_off() — ОБА канала безусловно:**
```python
async def emergency_off(self) -> None:
    """Аварийное отключение ОБОИХ каналов."""
    for smu_name, rt in self._channels.items():
        try:
            await self._transport.write(f"{smu_name}.source.output = {smu_name}.OUTPUT_OFF")
            await self._cancel_heartbeat(smu_name)
            rt.active = False
            rt.script_running = False
        except Exception:
            log.exception("Ошибка отключения %s", smu_name)
    # Финальная проверка
    for smu_name in self._channels:
        await self._verify_output_off(smu_name)
```

**_heartbeat_loop(channel: str) — per-channel:**
```python
async def _heartbeat_loop(self, channel: str) -> None:
    rt = self._channels[channel]
    try:
        while rt.active:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
            await self._send_heartbeat(channel)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.critical("СБОЙ HEARTBEAT %s — аварийное отключение!", channel)
        try:
            await self.stop_source(channel)  # только этот канал
        except Exception:
            log.critical("Ошибка отключения %s при сбое heartbeat", channel)
        if self._on_heartbeat_failure:
            try:
                self._on_heartbeat_failure(self.name, f"{channel}: {exc}")
            except Exception:
                pass
```

**_verify_output_off(channel: str):**
```python
async def _verify_output_off(self, channel: str) -> None:
    resp = await self._transport.query(f"print({channel}.source.output)")
    # Проверить что output == OUTPUT_OFF
```

**_load_tsp_template(channel, p, v_comp, i_comp):**
```python
def _load_tsp_template(self, channel: str, p_target: float, v_comp: float, i_comp: float) -> str:
    """Загрузить TSP шаблон с подстановкой канала."""
    tsp_path = self._tsp_dir / "p_const.lua"  # переименовать из p_const_single.lua
    template = tsp_path.read_text(encoding="utf-8")
    # Подстановка
    code = template.replace("{SMU}", channel)
    code = code.replace("{P_TARGET}", str(p_target))
    code = code.replace("{V_COMP}", str(v_comp))
    code = code.replace("{I_COMP}", str(i_comp))
    return code
```

**disconnect() — emergency_off() обоих, затем close:**
```python
async def disconnect(self) -> None:
    await self.emergency_off()  # оба канала
    await self._transport.close()
```

#### Свойства для обратной совместимости:

```python
@property
def any_active(self) -> bool:
    return any(rt.active for rt in self._channels.values())

@property  
def active_channels(self) -> list[str]:
    return [name for name, rt in self._channels.items() if rt.active]
```

---

### A-02. TSP — параметризованный шаблон

**Файл:** `tsp/p_const.lua` (переименовать из `p_const_single.lua`)

Заменить все жёсткие `smua` на `{SMU}`:

```lua
-- Было:
smua.reset()
smua.source.func = smua.OUTPUT_DCVOLTS
smua.source.levelv = V_initial
smua.measure.nplc = 1
smua.nvbuffer1.clear()

-- Стало:
{SMU}.reset()
{SMU}.source.func = {SMU}.OUTPUT_DCVOLTS
{SMU}.source.levelv = {P_TARGET_V_INITIAL}
{SMU}.measure.nplc = 1
{SMU}.nvbuffer1.clear()
```

Аналогично для `{P_TARGET}`, `{V_COMP}`, `{I_COMP}`.

**Watchdog — per-channel:** Каждый инстанс скрипта имеет свой watchdog timer. Потеря heartbeat для этого канала → этот канал OFF.

```lua
-- Watchdog: если нет heartbeat {HEARTBEAT_TIMEOUT}с → {SMU}.source.output = {SMU}.OUTPUT_OFF
```

Оригинал `p_const_single.lua` — оставить как есть для истории (или удалить, на усмотрение).

---

### A-03. SafetyManager — per-channel source control

**Файл:** `src/cryodaq/core/safety_manager.py`

#### Новые поля:

```python
self._active_sources: set[str] = set()  # {"smua", "smub"} — какие каналы активны
```

#### request_run(channel, p_target, v_comp, i_comp):

```python
async def request_run(
    self, channel: str, p_target: float, v_comp: float, i_comp: float,
) -> dict[str, Any]:
    """Запросить включение источника на указанном канале."""
    # 1. State checks (как сейчас)
    # 2. Preconditions (как сейчас)
    # 3. P/V/I limits (как сейчас)
    # 4. Если state == SAFE_OFF → transition(READY) → transition(RUN_PERMITTED)
    #    Если state == RUNNING (другой канал уже активен) → пропустить transitions
    # 5. keithley.start_source(channel, p, v, i)
    # 6. self._active_sources.add(channel)
    # 7. Если не RUNNING → transition(RUNNING)
    # 8. Publish state
```

#### request_stop(channel):

```python
async def request_stop(self, channel: str) -> dict[str, Any]:
    """Остановить указанный канал."""
    if channel in self._active_sources:
        await self._keithley.stop_source(channel)
        self._active_sources.discard(channel)
    # Если больше нет активных каналов → transition(SAFE_OFF)
    if not self._active_sources:
        self._transition(SafetyState.SAFE_OFF, f"Источник {channel} остановлен")
    return {"ok": True, "state": self._state.value, "channel": channel}
```

#### emergency_off():

```python
async def emergency_off(self) -> dict[str, Any]:
    await self._ensure_output_off()  # вызывает keithley.emergency_off() → оба канала
    self._active_sources.clear()
    # ... transition logic как сейчас
```

#### Heartbeat — per-channel check:

В `_run_checks()`, проверка heartbeat для каждого активного канала:
```python
for ch in list(self._active_sources):
    # Найти последний reading для этого канала
    # Если stale → stop_source(ch) + log
    # Если ВСЕ каналы потеряли heartbeat → FAULT
```

---

### A-04. engine.py — channel в командах

**Файл:** `src/cryodaq/engine.py`

Обработчик `keithley_start`:
```python
if action == "keithley_start":
    channel = cmd.get("channel", "smua")  # default smua для обратной совместимости
    p = cmd.get("p_target", 0.0)
    v = cmd.get("v_comp", 40.0)
    i = cmd.get("i_comp", 1.0)
    return await safety_manager.request_run(channel, p, v, i)
```

Обработчик `keithley_stop`:
```python
if action == "keithley_stop":
    channel = cmd.get("channel", "smua")
    return await safety_manager.request_stop(channel)
```

`emergency_off` — без изменений (оба канала).

---

### A-05. GUI — Keithley panel с двумя рабочими вкладками

**Файл:** `src/cryodaq/gui/widgets/keithley_panel.py`

Обе вкладки (smua, smub) полностью функциональны:
- Каждая: 4 графика (V/I/R/P), 3 spinbox (P, V_comp, I_comp), кнопки Start/Stop/Emergency
- Start отправляет `{"cmd": "keithley_start", "channel": "smua"|"smub", ...}`
- Stop отправляет `{"cmd": "keithley_stop", "channel": "smua"|"smub"}`
- Emergency — глобальный (оба канала)

**Убрать:** disabled state для smub tab. Обе вкладки одинаковые по функционалу.

---

### A-06. GUI — OverviewPanel Keithley strip

**Файл:** `src/cryodaq/gui/widgets/overview_panel.py`

KeithleyStrip показывает ОБА канала:
```
smua: V=0.152  I=0.0033  R=46.1  P=0.50 мВт  │  smub: V=0.085  I=0.0012  R=70.8  P=0.10 мВт
```

- Обновлять `_smub_label` и `_smub_data` из readings (убрать заглушку)
- При `power > 0` → "ON", при `power <= 0` или нет данных → "OFF"
- Оба обновляются из `/smua/` и `/smub/` readings

---

### A-07. Config — alarms и interlocks для smub

**Файл:** `config/alarms.yaml`

Добавить alarms для smub (по аналогии с smua):
```yaml
- name: keithley_smub_overpower
  channel_pattern: ".*/smub/power"
  condition: "> 5.0"
  severity: CRITICAL
  hysteresis: 0.5
  message: "Keithley smub: мощность {value:.2f} W > 5.0 W"
```

**Файл:** `config/interlocks.yaml`

Добавить interlocks для smub если есть smua-specific interlocks.

---

### A-08. AutoSweep — выбор канала

**Файл:** `src/cryodaq/gui/widgets/autosweep_panel.py`

Dropdown выбора канала: `["smua", "smub"]` (оба доступны). Команда включает `"channel": selected_channel`.

---

### A-09. conductivity_panel — smub каналы

**Файл:** `src/cryodaq/gui/widgets/conductivity_panel.py`

Если `Keithley_1/smub/power` в каналах — обновить чтобы работало корректно (readings приходят).

---

### A-10. Тесты smub

**Новые тесты:**
- `test_keithley_read_channels_returns_8_readings`: mock → 4 smua + 4 smub
- `test_keithley_start_smub`: start_source("smub", ...) → smub active
- `test_keithley_start_both`: start smua, start smub → both active
- `test_keithley_stop_one_channel`: start both → stop smua → smub still active
- `test_keithley_emergency_off_both`: start both → emergency_off → both OFF
- `test_safety_request_run_with_channel`: request_run("smub", ...) → ok
- `test_safety_dual_channel_running`: request_run smua, request_run smub → RUNNING
- `test_safety_stop_one_stays_running`: stop smua → still RUNNING (smub active)
- `test_safety_stop_both_safe_off`: stop both → SAFE_OFF

---

## ЧАСТЬ Б: 3 Contract Bugs

### B-01. AlarmEngine.acknowledge() не публикует event

**Файл:** `src/cryodaq/core/alarm.py`

В `acknowledge(name)`, ПОСЛЕ изменения state:
```python
await self._publish_alarm_reading(AlarmEvent(
    alarm_name=name,
    event_type="acknowledged",
    ...
))
await self._publish_alarm_count()
```

Убрать из `engine.py` вызов приватного `alarm_engine._publish_alarm_count()`. AlarmEngine делает это сам.

**Тест:** `test_alarm_acknowledge_publishes_event`: acknowledge → DataBroker получает Reading с event_type="acknowledged"

### B-02. Case mismatch: safe_off vs SAFE_OFF

**Файл:** `src/cryodaq/gui/widgets/overview_panel.py`

SafetyManager публикует lowercase (`safe_off`, `running`, `fault_latched`). GUI должен принимать lowercase:

В `StatusStrip.set_safety_state(state_str)`:
```python
def set_safety_state(self, state: str) -> None:
    s = state.upper()  # нормализация
    # Дальше сравнивать с uppercase как сейчас
```

В `KeithleyStrip.set_safety_state(state_str)`:
```python
def set_safety_state(self, state: str) -> None:
    self._visible = state.upper() != "SAFE_OFF"
    self.setVisible(self._visible)
```

**Тест:** `test_status_strip_handles_lowercase_state`: set_safety_state("safe_off") → корректный цвет/текст

### B-03. Keithley strip залипает на ON

**Файл:** `src/cryodaq/gui/widgets/overview_panel.py`

В `_handle_reading()`, для Keithley power readings:
```python
if channel.endswith("/power"):
    power = reading.value
    smu = "smua" if "/smua/" in channel else "smub"
    if power > 0.001:  # threshold для "ON"
        self._keithley_strip.set_channel_status(smu, f"P={power:.3f}W", is_on=True)
    else:
        self._keithley_strip.set_channel_status(smu, "OFF", is_on=False)
```

Добавить `set_channel_status(smu, text, is_on)` в KeithleyStrip если его нет.

---

## ЧАСТЬ В: Документация

### Обновить после завершения:

1. **CLAUDE.md** — Keithley smua+smub (dual-channel), убрать "(smub planned)"
2. **README.md** — Keithley smua+smub, test count, убрать все "planned"
3. **CHANGELOG.md** — [0.13.0] entry
4. **config/alarms.yaml** — smub alarms
5. **docs/architecture.md** — dual-channel описание

### Документация test count:
Прогнать `pytest --co -q | tail -1` и обновить ВСЕ упоминания количества тестов в README, CLAUDE, CHANGELOG.

---

## Команда

| Роль | Модель | Scope |
|------|--------|-------|
| Backend Engineer | Opus | keithley_2604b.py (ChannelRuntime, dual read/start/stop/emergency/heartbeat), safety_manager.py (channel in request_run/stop, active_sources), engine.py (channel routing), tsp/p_const.lua (параметризация) |
| GUI Engineer | Sonnet | keithley_panel.py (обе вкладки рабочие), overview_panel.py (strip обоих каналов + case fix + OFF path), autosweep_panel.py (channel dropdown), conductivity_panel.py (smub channels) |
| Test Engineer | Sonnet | Тесты A-10 + B-01/B-02/B-03, config/alarms.yaml smub entries |

Dependencies: Backend → GUI (API: start_source(channel, ...), read_channels returns 8). Backend → Test (API signatures).

## Критерии приёмки

1. `read_channels()` в mock → 8 readings (4 smua + 4 smub)
2. `start_source("smua", ...)` + `start_source("smub", ...)` → оба активны параллельно
3. `stop_source("smua")` → smua OFF, smub продолжает, SafetyManager RUNNING
4. `stop_source("smub")` → smub OFF, нет активных → SafetyManager SAFE_OFF
5. `emergency_off()` → оба OFF безусловно
6. GUI Keithley: обе вкладки функциональны, Start/Stop per-channel
7. OverviewPanel: оба канала в strip, OFF при power <= 0
8. Heartbeat: потеря smua heartbeat → smua OFF, smub продолжает
9. AlarmEngine.acknowledge() → публикует "acknowledged" event + count
10. StatusStrip/KeithleyStrip принимают lowercase safety state
11. `config/alarms.yaml` покрывает smub
12. Все тесты проходят
13. Docs обновлены, test count точный
