# CryoDAQ — Alarm / Interlock / Safety Tuning Guide

> Живой документ. Обновлён 2026-04-20 после IV.3 close (HEAD `b06c657`).
>
> **Цель:** дать инженеру установки понимание трёх слоёв защиты
> CryoDAQ, где какие пороги живут, и какие значения предстоит подогнать
> под реальную криовакуумную установку (Millimetron / АКЦ ФИАН) перед
> production deployment.
>
> **Аудитория:** Vladimir Fomenko (архитектор + оператор), следующие
> инженеры лаборатории криогеники.

---

## TL;DR

У CryoDAQ **три независимых слоя контроля безопасности**, от жёсткого
к мягкому:

1. **SafetyManager** (`config/safety.yaml`) — FSM `SAFE_OFF → READY →
   RUN_PERMITTED → RUNNING → FAULT`. Не даёт **ВКЛЮЧИТЬ** источник при
   нарушении preconditions. Плюс stale-data fault и rate-limit fault.
2. **Interlock Engine** (`config/interlocks.yaml`) — хардкорные
   triggers, которые **ВЫКЛЮЧАЮТ** источник при превышении порогов.
   Два действия: `emergency_off` (полное отключение Keithley) и
   `stop_source` (только источник тока).
3. **Alarm Engine v2** (`config/alarms_v3.yaml`) — композитный уровень:
   уведомления (GUI / Telegram / звук), severity levels, phase-aware,
   composite conditions через AND/OR, rate monitoring, stale detection.

Ещё есть **Alarm Engine v1** (`config/alarms.yaml`) — legacy, почти
всё отключено через `enabled: false`. Не трогай, новые алармы идут
в v3.

---

## Архитектурная схема

```
  ┌───────────────────────────────────────────────────────────────┐
  │                   Криовакуумная установка                     │
  │   Т1..Т20 · P1 · Keithley smua/smub · heartbeat · disk        │
  └──────────────────────────────┬────────────────────────────────┘
                                 │  readings
                                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │              DataBroker (engine, asyncio)                    │
  │  persistence-first: SQLite WAL commit → затем subscribers    │
  └──┬────────────────┬─────────────────┬─────────────────┬──────┘
     │                │                 │                 │
     ▼                ▼                 ▼                 ▼
  ┌──────┐     ┌──────────┐     ┌──────────────┐   ┌──────────┐
  │Safety│     │Interlock │     │ Alarm v2     │   │ Alarm v1 │
  │Mgr   │     │Engine    │     │ Evaluator    │   │ Engine   │
  │(fsm) │     │          │     │ + State Mgr  │   │ (legacy) │
  └──┬───┘     └────┬─────┘     └──────┬───────┘   └────┬─────┘
     │              │                  │                │
     ▼              ▼                  ▼                ▼
  блокирует    emergency_off /    GUI badge +       (отключено)
  запуск       stop_source        Telegram +
  источника                       звук
```

**Персистентность на диск идёт ДО publish в подписчики** — если
SQLite не смог записать, fault. Все слои защиты живут параллельно и
независимо.

---

## Слой 1: SafetyManager — `config/safety.yaml`

Это не пороги-на-значения, это **правила готовности**. Источник тока
нельзя включить пока хоть одно условие не выполнено.

### Текущая конфигурация

```yaml
critical_channels:              # обязательны для перехода в RUN
  - "Т1 .*"                     # верх криостата
  - "Т7 .*"                     # детектор
  - "Т11 .*"                    # 1-я ступень GM-cooler (калиброванный)
  - "Т12 .*"                    # 2-я ступень, холодная точка (калиброванный)

stale_timeout_s: 10.0           # без обновления >10с → FAULT
heartbeat_timeout_s: 15.0       # Keithley молчит >15с → FAULT
max_safety_backlog: 100         # очередь > 100 → FAULT
require_keithley_for_run: true  # в проде true; false для mock

rate_limits:
  max_dT_dt_K_per_min: 5.0      # >5 K/мин на любом канале → FAULT

recovery:
  require_reason: true
  cooldown_before_rearm_s: 60.0

source_limits:
  max_power_w: 5.0              # хардкап Keithley
  max_voltage_v: 40.0
  max_current_a: 1.0

keithley_channels:
  - ".*/smu.*"                  # regex для heartbeat check

scheduler_drain_timeout_s: 5.0
```

### Семантика FSM

- `SAFE_OFF` — старт. Источник выключен.
- `READY` — все preconditions выполнены; оператор может нажать START.
- `RUN_PERMITTED` — START нажат, идёт переход в RUNNING.
- `RUNNING` — источник включён. `Fail-on-silence` активен: stale data
  → FAULT.
- `FAULT_LATCHED` — залочен, требует manual recovery.
- `MANUAL_RECOVERY` → обратно в `READY` после acknowledge.

### Что подгонять под реальность

| Параметр | Текущее | Что учесть |
|---|---|---|
| `critical_channels` | 4 канала | Расширь по списку ключевых датчиков твоей установки. Если Т7 (детектор) у тебя нигде не установлен — убери. |
| `stale_timeout_s` | 10.0 | LakeShore опрос 2с = 5 poll'ов. Если шум GPIB вызывает ложные timeouts, подними до 15-20с. |
| `heartbeat_timeout_s` | 15.0 | Keithley USBTMC обычно отвечает <1с. 15с достаточно. |
| `max_dT_dt_K_per_min` | 5.0 | Консервативно. Mock и calibration runs могут выдать больше. Отслеживай — если false positives, подними до 8-10. |
| `max_power_w` | 5.0 | Проверь по datasheet Keithley 2604B (100W per channel) и по thermal budget твоего нагревателя (обычно 100-500 mW). 5W — разумный cap. |
| `max_voltage_v` / `max_current_a` | 40 / 1.0 | 40V × 1A = 40W > 5W max_power_w. Это OK (защита многослойная). Можно ужесточить: если I<100 mA нормально, поставь 0.2A. |
| `require_keithley_for_run` | true | В mock должен быть false, в production — true. |

### Что **не** менять без физического обоснования

- Fail-on-silence принцип — это инвариант #4.
- FSM transitions — safety-критично, регрессия = потеря управляемости.
- Cancellation shielding в `_fault()` — Phase 2d invariant #11.

---

## Слой 2: Interlock Engine — `config/interlocks.yaml`

Жёсткие triggers. Формат: **условие → действие**.

### Текущая конфигурация

```yaml
interlocks:
  - name: "overheat_cryostat"
    channel_pattern: "Т[1-8] .*"   # любой из Т1-Т8
    threshold: 350.0               # K
    comparison: ">"
    action: "emergency_off"        # полное отключение
    cooldown_s: 10.0

  - name: "overheat_compressor"
    channel_pattern: "Т(9|10|11|12) .*"
    threshold: 320.0
    comparison: ">"
    action: "emergency_off"
    cooldown_s: 10.0

  - name: "detector_warmup"
    channel_pattern: "Т12 .*"
    threshold: 10.0                # K
    comparison: ">"
    action: "stop_source"           # мягкая остановка
    cooldown_s: 5.0
```

### Actions — разница

- `emergency_off` — полный shutdown Keithley через hardware path
  (`_ensure_output_off`). Вызывается для критических аварий.
- `stop_source` — мягкая остановка источника тока через
  `SafetyManager.request_stop()`. Без hard-disconnect.

### Что подгонять

| Interlock | Текущий порог | Что учесть |
|---|---|---|
| `overheat_cryostat` Т1-Т8 | >350 K | Консервативно. Можно оставить. Если Т1 (верх криостата) в проде редко доходит до 300К — OK. |
| `overheat_compressor` Т9-Т12 | >320 K | Компрессор GM-cooler реально греется до 50-100°C = 323-373 K. Проверь паспорт твоего криокулера — может ужесточить до 310 K. |
| `detector_warmup` Т12 | >10 K | **Основной рабочий порог**. Т12 = 2-я ступень, рабочая температура 3-4K. При >10K детектор warmup, источник надо выключить. **В mock режиме срабатывает сразу** (T12=77.57K) — это нормально, не ошибка. |

### Важные замечания

- **Interlocks работают в любой фазе эксперимента.** Это железная
  защита, phase filter тут не применяется.
- **Regex pattern** — `"Т[1-8] .*"` матчит `"Т1 Криостат верх"`,
  `"Т2 ..."` и т.д. Точка с пробелом важна — это разделитель
  `channel_id <space> description`.
- **Cooldown** — минимальный интервал между повторными срабатываниями.
  10 сек означает: если interlock тригернулся, следующие 10 сек он не
  будет пере-тригерить даже если условие сохраняется.
- `undercool_shield` — удалённый interlock. Ложное срабатывание при
  штатном cooldown. Не возвращать.

---

## Слой 3: AlarmEngine v2 — `config/alarms_v3.yaml`

Основная система уведомлений. Четыре типа условий.

### Типы alarm_type

| Тип | Семантика | Пример |
|---|---|---|
| `threshold` | значение выше/ниже/вне диапазона | `check: above, threshold: 4.0` |
| `rate` | скорость изменения за окно | `check: rate_below, threshold: -5.0, rate_window_s: 120` |
| `composite` | AND/OR несколько условий | `operator: AND, conditions: [...]` |
| `stale` | данных нет >N секунд | `timeout_s: 30` |

### Уровни (level)

- `INFO` — заметка в GUI, без уведомления
- `WARNING` — GUI + опциональный Telegram
- `CRITICAL` — GUI + Telegram + звуковое уведомление

### Notification channels

- `gui` — badge в TopWatchBar + alarm panel
- `telegram` — сообщение в настроенный chat_id
- `sound` — системный звуковой сигнал

### Engine settings (`alarms_v3.yaml:engine`)

```yaml
engine:
  poll_interval_s: 0.5           # проверка alarm conditions
  rate_window_s: 120             # окно для rate calculation
  rate_min_points: 60            # минимум точек для rate
  rate_method: linear_fit

  setpoints:
    T12_setpoint:
      source: experiment_metadata   # из карточки эксперимента
      default: 4.2                  # если не указан
      unit: K
```

**Setpoint T12** — задаётся в `custom_fields` карточки эксперимента.
Используется в `detector_drift`, `detector_unstable`, `cooldown_stall`.

### Channel groups

```yaml
calibrated:    [Т11, Т12]
# Т4 (Радиатор 2), Т8 (Калибровка) — отключённые датчики, исключены
uncalibrated:  [Т1, Т2, Т3, Т5, Т6, Т7, Т9, Т10, Т13..Т20]
all_temp:      [Т1..Т20 без Т4, Т8]
```

**Фильтрация Т4 и Т8** — это изначально отключённые датчики. Если в
твоей установке они подключены — переведи их в `uncalibrated`.

---

## Текущий состав v2 алармов (19 штук)

### Global (работают всегда, 11 штук)

| Имя | Условие | Уровень | Notify |
|---|---|---|---|
| `vacuum_loss_cold` | Т11/Т12 <200K AND P1 >1e-3 mbar | CRITICAL | gui+tg+sound |
| `vacuum_loss_cold_early` | Т11/Т12 <200K AND P1 >1e-4 AND dP/dt>0 | WARNING | gui+tg |
| `sensor_fault` | Uncalibrated канал вне 0-350K | WARNING | gui |
| `sensor_fault_intermittent` | ≥1 скачок за 0/350K в 5 мин | WARNING | gui |
| `calibrated_sensor_fault` | Т11/Т12 вне 1-350K | CRITICAL | gui+tg+sound |
| `data_stale_temperature` | temp канал не обновлялся >30с | WARNING | gui |
| `data_loss_temperature` | temp канал не обновлялся >120с | CRITICAL | gui+tg+sound |
| `data_loss_pressure` | P1 не обновлялся >60с | CRITICAL | gui+tg+sound |
| `keithley_overpower` | smua/smub power >4W | CRITICAL | gui+tg+sound + stop_source |
| `disk_space_warning` | диск <10 GB | WARNING | gui |
| `disk_space_critical` | диск <2 GB | CRITICAL | gui+tg |

### Phase-aware

#### vacuum (2)

| Имя | Условие | Уровень |
|---|---|---|
| `vacuum_insufficient` | P1 >1e-4 mbar через 60 мин | WARNING |
| `vacuum_stall` | \|dP/P\| <1% за окно при P >1e-5 | INFO |

#### cooldown (2)

| Имя | Условие | Уровень |
|---|---|---|
| `excessive_cooling_rate` | Т11/Т12 rate < -5 K/мин | WARNING |
| `cooldown_stall` | Т12 rate≈0 >15мин AND far from setpoint | WARNING |

#### measurement (3)

| Имя | Условие | Уровень |
|---|---|---|
| `detector_drift` | Т12 отклон. от setpoint >0.5K >60с | WARNING |
| `detector_unstable` | Т12 отклон. >2K >10с | CRITICAL |
| `shield_warming` | Т11 rate >0.5 K/мин >5 мин | WARNING |

#### warmup (1)

| Имя | Условие | Уровень |
|---|---|---|
| `excessive_warmup_rate` | Т11/Т12 rate >5 K/мин | WARNING |

---

## План настройки под реальную установку

### Рабочий процесс

1. **Baseline run без срабатываний.** Провести 1-2 полных цикла
   (vacuum → cooldown → measurement → warmup) в mock/lab, собрать
   статистику реальных rates, pressures, temperatures.
2. **Log review.** Посмотреть в `logs/alarm_events.log` что реально
   срабатывало, какие — false positives.
3. **Настройка по +20-30% запаса** от наблюдённых maxima, чтобы не
   триггериться на нормальный шум, но ловить аномалии.
4. **Неделя обкатки** — сводка false positives / missed faults → крутить
   пороги.

### Приоритет 1 — критичные, точно надо настроить

**1.1 `vacuum_loss_cold` порог P**
```yaml
# Сейчас: P1 > 1e-3 mbar при Т11/Т12 < 200K
```
**Что учесть:** твой конкретный криостат теряет молекулярный режим
при другом давлении — зависит от геометрии, свободной длины пробега,
наличия тёплых поверхностей. Проверь при каком давлении реально
начинается заметная передача тепла. Обычно 1e-3 mbar правильно, но
для больших объёмов может быть 5e-4.

**1.2 `keithley_overpower`**
```yaml
# Сейчас: 4W alarm, 4.5W interlock, 5W hardcap
```
**Что учесть:** для P=const feedback на маленьком нагревателе (типично
30-100 mW) порог 4W никогда не сработает. Подгони под реальный
рабочий диапазон: если рабочая мощность <200 mW, alarm на 500 mW.

**1.3 `calibrated_sensor_fault` границы**
```yaml
# Сейчас: Т11/Т12 вне 1-350K → CRITICAL
```
**Что учесть:** для DT-670 калибровка начинается с ~1.4K. Если у тебя
другой тип датчика (LakeShore rhodium-iron, Cernox) — границы свои.

**1.4 `detector_drift` / `detector_unstable`**
```yaml
# Сейчас: 0.5K drift (60с) / 2K unstable (10с)
# setpoint: 4.2K (default)
```
**Что учесть:** для setpoint 4.2K с DT-670 stability ±10 mK — 0.5K
drift слишком грубо. Можно ужесточить до 0.1K. Для 3K setpoint —
0.5K это 17% отклонение, слишком много; ставь 0.05K.

**Где прописать setpoint per experiment:** в template
`config/experiment_templates/<template>.yaml`:
```yaml
custom_fields:
  - id: T12_setpoint
    label: "Рабочая температура Т12, K"
    default: "4.2"
```

### Приоритет 2 — важные

**2.1 Cooling / warmup rate limits**
```yaml
# excessive_cooling_rate: rate < -5 K/мин
# excessive_warmup_rate: rate > 5 K/мин
```
**Что учесть:** thermal shock опасен на больших rates, но для
маленьких криостатов 10 K/мин штатно. Смотри реальные cooldown curves,
поставь +30% от observed max.

**2.2 `shield_warming`**
```yaml
# Т11 rate > 0.5 K/мин → WARNING
```
**Что учесть:** зависит от расхода LN2. Стабильный турбулентный расход
держит dT/dt < 0.1 K/мин. Если у тебя регулярные thermal cycles при
доливке — подними до 1 K/мин.

**2.3 Stale / data loss timeouts**
```yaml
# stale_timeout_s: 10 в safety.yaml
# data_stale_temperature: 30s в alarms_v3.yaml
# data_loss_temperature: 120s в alarms_v3.yaml
```
**Что учесть:** `safety.yaml:stale_timeout_s` — это fault. `alarms_v3.
yaml:data_stale_temperature` — это warning. Safety должен быть строже
(10с), alarm v2 мягче (30-60с для warning, 120с для critical). Сейчас
так и есть.

### Приоритет 3 — удобство / долгосрочное

**3.1 `vacuum_insufficient` timeout**
```yaml
# P1 > 1e-4 через 60 мин
```
**Что учесть:** для маленького объёма 60 мин — долго, вакуум
достигается за 30. Для большого — может быть мало. Подгоняй.

**3.2 Disk thresholds**
```yaml
# warning <10GB, critical <2GB
```
**Что учесть:** эксперимент 24ч с 22 каналами @ 0.5Hz = ~2 млн записей
= ~200 MB. Если у тебя эксперименты недельные — warning на 10GB может
срабатывать слишком рано. Поставь пропорционально: `expected_days × 200 MB × 5`.

**3.3 `cooldown_stall` window**
```yaml
# Т12 rate≈0 (<0.1 K/мин) за 15 мин
```
**Что учесть:** при approach to setpoint rate естественно падает.
Если твой криостат делает soft landing — 15 мин может быть мало,
подними до 30 мин чтобы не ложить warning на финальный approach.

---

## Что **не** настраивать без физики

- **Физические границы `[0, 350]K`** в `sensor_fault` — это абсолютные
  границы физики, не рабочий диапазон. Не менять.
- **Hysteresis values** — устроены для предотвращения дребезга.
  Изменение требует симуляции.
- **`poll_interval_s: 0.5` и `rate_window_s: 120`** в engine секции —
  baseline движка. Менять только при измеренной необходимости.
- **interlock `cooldown_s`** — минимум 5-10 сек. Слишком маленький =
  re-trigger storm в логах. Слишком большой = поздняя реакция.

---

## Где посмотреть физическое обоснование

`alarm_tz_physics_v3.md` упоминается в комментариях `alarms_v3.yaml`,
но **файла на данный момент нет в репо.** Если тебе предстоит писать
обоснования после настройки — вот структура:

```markdown
# alarm_tz_physics_v3.md

## vacuum_loss_cold @ P>1e-3 mbar
Обоснование: при P=1e-3 mbar mean free path ~10 см (по Крамерсу).
Для нашего криостата диаметром 50 см это уже переходный режим,
радиационная теплопередача начинает дополняться газовой.
Source: Roth "Vacuum Technology" §3.2.

## excessive_cooling_rate @ 5 K/мин
Обоснование: CTE mismatch между CFRP и Ti при 5 K/мин создаёт
σ = E·α·ΔT/2·Δt ≈ 45 MPa < σ_yield(6Al-4V)=880 MPa. Запас ×20.

## ...
```

**Рекомендация:** после настройки реальных значений написать этот
doc. Это снимет "магические числа" для следующего оператора.

---

## Reference: конфиги

- `config/safety.yaml` — инварианты запуска, rate-limit, source cap
- `config/interlocks.yaml` — жёсткие отключения
- `config/alarms.yaml` — **legacy, не трогать**
- `config/alarms_v3.yaml` — основная alarm система
- `config/experiment_templates/*.yaml` — setpoints через custom_fields
- `config/notifications.yaml` — Telegram bot token, chat IDs
- `config/safety.local.yaml` — override для конкретной машины
  (production lab-PC specific)

---

## Modules

- `src/cryodaq/core/safety_manager.py` — FSM + preconditions
- `src/cryodaq/core/interlock.py` — Interlock Engine
- `src/cryodaq/core/alarm.py` — Alarm Engine v1 (legacy)
- `src/cryodaq/core/alarm_v2.py` — AlarmEvaluator + StateManager
- `src/cryodaq/core/alarm_config.py` — загрузчик YAML v3
- `src/cryodaq/core/alarm_providers.py` — ExperimentPhaseProvider,
  ExperimentSetpointProvider
- `src/cryodaq/core/rate_estimator.py` — linear fit rates
- `src/cryodaq/core/channel_state.py` — stale tracking

---

---

## F20 — Диагностические алармы: агрегация и cooldown (v0.43.0)

Sensor diagnostics engine (F10) теперь поддерживает:

**Агрегация** (`plugins.yaml → aggregation_threshold`, default `3`):
Если в одном тике N > threshold каналов переходят в warning/critical
одновременно, вместо N отдельных Telegram-сообщений отправляется одно
батчевое: "5 каналов critical: T1, T3, T5, T7, T9".

**Per-channel escalation cooldown** (`plugins.yaml → escalation_cooldown_s`,
default `120`):
Предотвращает повторную нотификацию при oscilling канале вблизи порога.
Первая нотификация НИКОГДА не подавляется. Critical всегда проходит вне
зависимости от cooldown.

Конфигурация в `config/plugins.yaml`:
```yaml
sensor_diagnostics:
  aggregation_threshold: 3
  escalation_cooldown_s: 120.0
```

---

## F21 — Alarm hysteresis deadband (v0.43.0)

Поле `hysteresis` в alarm rule (`config/alarms_v3.yaml`):
Аларм не очищается пока значение не выйдет за границу `threshold - hysteresis`
(для `check: above`) или `threshold + hysteresis` (для `check: below`).

Особенность реализации: deadband применяется только к каналам, которые
изначально триггернули аларм (`active_channels` parameter). Незатронутые
каналы не наследуют alarm state.

Пример конфигурации:
```yaml
alarm_type: threshold
check: above
threshold: 200.0
hysteresis: 5.0   # аларм очищается только при T < 195.0
```

---

## F22 — Severity upgrade: WARNING → CRITICAL (v0.43.0)

`AlarmStateManager.publish_diagnostic_alarm()` теперь поддерживает upgrade
severity в рамках одного `alarm_id`. Если warning уже активен и приходит
critical — severity обновляется in-place. История записывает событие
`SEVERITY_UPGRADED`.

Оператор видит **одно** уведомление с эскалацией severity, не дублирующиеся
warning + critical.

---

## Changelog

- 2026-04-30: добавлены F20/F21/F22 секции (aggregation, cooldown, hysteresis,
  severity upgrade). Обновлено после v0.43.0 ship (`c44c575`).
- 2026-04-20: первая редакция после IV.3 close (`b06c657`). Собрано
  из `safety.yaml`, `interlocks.yaml`, `alarms.yaml`, `alarms_v3.yaml`.
