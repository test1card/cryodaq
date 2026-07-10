---
title: Настройка приборов
audience: lab tech, operator on duty
scope: физическое подключение + конфигурация приборов CryoDAQ
status: canonical
last_updated: 2026-07-08
companion: docs/deployment.md, docs/safety-operator.md, config/instruments.yaml
---

# Настройка приборов CryoDAQ

Этот документ — для лаборанта, который разворачивает CryoDAQ на новом
стенде или меняет железо на работающем. В основном это редактирование
`config/instruments.yaml` и проверка связи через mock / live mode. Код
`src/cryodaq/drivers/` трогать не надо.

Схема стека с точки зрения оператора:

```
физический прибор ──► transport (GPIB / USB-TMC / RS-232)
                      │
                      ▼
              driver (instruments/*.py)
                      │
                      ▼
              Scheduler (persistence-first)
                      │
                      ▼
              SQLite → DataBroker → GUI / алармы
```

## Пять поддерживаемых приборов

Текущая конфигурация — в `config/instruments.yaml`. Если нужны
машинно-зависимые параметры (COM-порт, GPIB-адрес не совпадает с
шаблонным), лучше создать `config/instruments.local.yaml` — он
gitignored и переопределяет основной файл.

### LakeShore 218S (температура)

**Интерфейс:** GPIB. На стенде используются три контроллера по 8
каналов — суммарно 24 температурных канала Т1–Т24.

**Адреса на шаблоне:**

| Прибор | Resource | Каналы |
|---|---|---|
| LS218_1 | `GPIB0::12::INSTR` | Т1–Т8 |
| LS218_2 | `GPIB0::14::INSTR` | Т9–Т16 (в том числе Т11 / Т12 — **позиционно фиксированные** референс-каналы) |
| LS218_3 | `GPIB0::16::INSTR` | Т17–Т24 |

**Проверить подключение без запуска engine:**

```bash
python3 -c "
import pyvisa
rm = pyvisa.ResourceManager()
for res in rm.list_resources():
    print(res)
"
```

Должны быть видны `GPIB0::12::INSTR`, `GPIB0::14::INSTR`,
`GPIB0::16::INSTR` (точные номера — см. `instruments.yaml` или наклейки
на приборах; здесь приведён шаблон).

**Если прибор не виден:**

- Питание включено, GPIB-адрес на передней панели соответствует YAML.
- GPIB-USB адаптер (NI GPIB-USB-HS) подключён; в диспетчере устройств /
  `lsusb` отображается.
- Linux: `sudo modprobe ni_usb_gpib` если ядерный модуль не
  загружен; для Keysight USB используется `usbtmc` модуль.
- Windows: NI-VISA runtime установлен; без него PyVISA не видит GPIB.

**Смена GPIB-адреса прибора:**

1. На передней панели: `Menu` → `Interface` → `Address` → ввести новый
   номер.
2. Обновить `resource` в `config/instruments.yaml` для
   соответствующей записи.
3. Перезапустить engine.

### Keithley 2604B (источник мощности)

**Интерфейс:** USB-TMC. Двухканальный source-measure unit — оба канала
`smua` и `smub` активны одновременно (инвариант уровня кодовой базы;
см. `docs/architecture.md`).

**Адрес на шаблоне:**

| Прибор | Resource | Каналы |
|---|---|---|
| Keithley_1 | `USB0::0x05E6::0x2604::04052028::INSTR` | `smua` + `smub` |

Серийный номер (`04052028` в примере) **уникален для каждого прибора**
— на новом стенде он будет другим. Остальные поля (`USB0`, vendor
`0x05E6`, product `0x2604`, суффикс `INSTR`) одинаковые для всех
Keithley 2604B. Подставь фактический серийник из «Проверить
подключение» ниже в `resource` для записи Keithley в
`config/instruments.yaml` (или в `instruments.local.yaml`).

**Проверить подключение:**

```bash
python3 -c "
import usb.core
dev = usb.core.find(idVendor=0x05E6, idProduct=0x2604)
print('Found:', dev.serial_number if dev else None)
"
```

Серийный номер из вывода — это значение, которое идёт в середину
строки `USB0::0x05E6::0x2604::<СЕРИЙНЫЙ>::INSTR`.

**Язык команд:** TSP (Lua), не SCPI. Драйвер
`src/cryodaq/drivers/instruments/keithley_2604b.py` ходит через
`print(...)` TSP-invocations. **UI не посылает SCPI-строки** — если
в коде появилось `:SOUR:VOLT` или подобное, это баг.

**Host-side P=const режим:** текущая реализация держит `P = const`
программным циклом на хосте.

**TSP late-pet watchdog:** программная TSP-проверка дедлайна
под host SafetyManager, выбирается оператором через
`config/instruments.yaml` → `keithley.watchdog.mode`:

| mode | поведение на connect | покрытие |
|------|----------------------|----------|
| `off` (дефолт драйвера) | TSP-скрипт не загружается; host SafetyManager — единственный авторитет; байт-идентичный поток команд | только host |
| `best_effort` | активировать на connect; CRITICAL сообщает, что автономной защиты нет | late-pet stall-recovery + latch + reconcile |
| `required` | требует `cryodaq_wdog_autonomous == 1`; v3 сообщает 0, поэтому `connect()` бросает → прибор недоступен → SAFE_OFF | зарезервирован для доказанной автономной реализации |

Легаси-алиас: `enabled: true` → `best_effort`, `enabled: false` → `off`
(при наличии обоих ключей выигрывает `mode`).

Иерархия покрытия (честно):
- `off` — защита только на хосте.
- `best_effort` (текущий механизм) — проверка
  **stall-recovery** (запоздавший pet убивает выходы + защёлкивает
  trip для reconcile). Полную смерть хоста этот механизм **не**
  покрывает: `cryodaq_wdog_run()` только взводит и возвращается (не
  крутит цикл — иначе занял бы single-threaded FIFO), а дедлайн
  проверяется внутри `cryodaq_wdog_pet()` на каждом polling-тике.
- `required` не принимает активный late-pet checker за автономную защиту:
  он читает отдельный bit и fail-closed отказывает с v3.
- Предыдущий вариант автономного таймера был не «непроверенным», а
  документированно некорректным: использовал отсутствующий атрибут timer,
  нулевой stimulus и неподходящий `SOURCE_IDLE` в source action. Он удалён.
- Полный host-death остаётся без автономного TSP-покрытия. Force-OFF при
  следующем connect — восстановление, а не защита во время смерти хоста.
  Предпочтительный финальный элемент — независимый защёлкивающийся cutout/
  interlock с анализом общих отказов. Внутренний SMU-прототип допустим только
  как гипотеза по документированному API и требует стендового доказательства.
  Output-enable/digital-I/O facility 2604B по reference manual не подходит для
  safety circuits и не должна управлять safety interlock; нужен отдельный
  application-appropriate safety circuit.

`SOURCE_IDLE` возвращает источник к idle level и не равен открытию реле/OFF.
Ни внутренний status bit, ни `source.output` не являются независимым
доказательством отсутствия энергии на клеммах.

Лимит 5 W — host-only target cap и исчезает вместе с хостом. Приборные
`limitv=40 V` и `limiti=1 A` ограничивают рабочую точку применимым envelope
нагрузки и прибора, но не гарантируют ≤5 W и не ограничивают накопленную
энергию при длительной подаче после смерти хоста.

`watchdog.timeout_s` принимает только конечное число от 1 до 300 секунд
(boolean, строка, NaN/Inf и значения вне диапазона валят загрузку конфига).
TSP `os.time()` имеет секундную гранулярность; сравнение строгое `elapsed >
timeout`, поэтому равенство дедлайну ещё не trip. Практический timeout должен
быть не меньше `2 * poll_interval_s`; меньший безопасно отклоняется не всегда,
но даёт явный warning о возможном ложном late-pet trip.

Version/active/tripped/autonomous readback принимают только конечные точные
protocol-значения (version 3; flags 0/1). До upload только буквальный TSP
`nil` означает свежий прибор; malformed/NaN/Inf/out-of-domain сохраняют
неизвестную latch-улику и запрещают upload. Найденный latch также не стирается
на connect: RUN блокируется сразу, SafetyManager латчит FAULT, а operator fault
ack после повторного verified both-output OFF явно потребляет latch и
реактивирует late-pet check. Если прибор power-cycle вернул `nil`, сохранённый
host pending-bit разрешает тот же audited ack/re-upload path. В `required`
текущий v3 реактивировать нельзя: выбрать `best_effort` и явно переподключить
прибор. `off` допустим только как осознанное отключение всего TSP-path после
фиксации evidence, а не как способ «успешно» consume latch.

**Disconnect требует emergency_off first** — автоматизировано в
engine, но при ручном вытаскивании USB-кабеля лучше сначала
остановить эксперимент / нажать «Отключить Keithley» в панели.

### Thyracont VSP63D / VSM77DL (давление)

**Интерфейс:** RS-232 через FTDI USB→Serial. Порт обычно `COM3`
(Windows) или `/dev/ttyUSB0` (Linux). Baudrate `9600` (см.
`instruments.yaml`).

**Проверить порт:**

```bash
# Linux
ls -l /dev/ttyUSB* /dev/ttyS*
# Windows (PowerShell)
[System.IO.Ports.SerialPort]::GetPortNames()
```

**Автодетект протокола:** драйвер пробует сначала V1 (старый
формат 9600/E/7/1), затем MV00 (9600/N/8/1). Ручная конфигурация
протокола в YAML не нужна — пусть подбирает.

**Если прибор не отвечает:** проверить, что кабель RS-232 —
именно от Thyracont (бывает, что используется кабель от другого
прибора с несовместимой распайкой), и что на приборе не включена
модема-эмуляция.

### Etalon MultiLine (интерферометрическая метрология длины)

**Интерфейс:** TCP/IP (Ethernet). Адрес хоста и порт — в
`config/instruments.yaml` (секция прибора MultiLine); машинно-зависимые
значения удобно держать в `instruments.local.yaml`.

Абсолютная интерферометрическая метрология длины (несколько каналов).
Драйвер `src/cryodaq/drivers/instruments/etalon_multiline.py`. Режимы: **averaged**
(усреднённые отсчёты) и **continuous**; поддерживается burst-захват
вибрации с записью в Parquet. Операторский workflow (в т.ч. «Захват
вибрации») — в overlay «MultiLine»; подробности в
`docs/operator_manual.md`.

## Как добавить / заменить прибор

1. Отредактировать `config/instruments.yaml` (или создать
   `instruments.local.yaml` — gitignored, формат тот же; значения
   `.local` переопределяют).
2. Добавить / изменить блок:
   ```yaml
   instruments:
     - type: lakeshore_218s
       name: "LS218_4"
       resource: "GPIB0::18::INSTR"
       poll_interval_s: 2.0
       channels:
         1: "Т25 Новый канал"
         # ...
   ```
3. Перезапустить engine. Новый прибор виден в панели «Приборы»
   (`Ctrl+D`) — должна появиться строка со статусом / heartbeat.
4. Новые каналы нужно ещё добавить в `config/channels.yaml`
   (для отображения и группировки); иначе они будут собраны и
   записаны в SQLite, но не показаны на дашборде.

## Mock mode для разработки

Engine можно запустить без физических приборов:

```bash
cryodaq-engine --mock
```

В mock-режиме driver возвращает синтетические данные: температуры
имитируют охлаждение, давление — pump-down профиль, Keithley — нулевой
ток и заданное напряжение. Полезно для разработки GUI без
лабораторного стенда и для быстрой проверки, что конфиг не сломан.

Аналог: переменная окружения `CRYODAQ_MOCK=1` — тот же эффект.

## Конфигурируемые таймауты

В `config/instruments.yaml` на каждую запись:

- **`poll_interval_s`** — как часто Scheduler запрашивает прибор.
  2.0 с для LakeShore по умолчанию (ограничено GPIB-timing + KRDG?
  response time), 1.0 с для Keithley, 2.0 с для Thyracont.
- Более агрессивный polling допустим, но учти нагрузку на GPIB-шину.

В `config/safety.yaml`:

- **`stale_timeout_s`** (default 10 с) — если от канала нет данных
  дольше, система переходит в `fault_latched`. Должен быть ≥ 2–3 ×
  `poll_interval_s`.
- **`heartbeat_timeout_s`** (default 15 с) — защита от застрявшего
  `run_permitted`.

## Известные гонки / особенности

- **`KRDG?` без аргумента** — для LakeShore 218S **правильная** команда
  (возвращает все 8 каналов одной строкой). Не менять на `KRDG? 0`
  или `KRDG? 1..8` — парсер драйвера заточен под строку-с-запятыми от
  `KRDG?`.
- **Keithley: `connect()` форсит OUTPUT OFF** на обоих каналах
  перед assume-control и readback-verify. Если OFF не удалось
  подтвердить, драйвер выставляет `output_state_unverified`, а
  SafetyManager fail-closed блокирует RUN до успешного emergency-off.
- **Thyracont VSP63D vs VSM77DL** — старые версии документации
  упоминают VSM77DL; код поддерживает оба (драйвер автодетектирует
  протокол). Имя в YAML пишем по фактической модели на стенде.
- **Mock + live одновременно нельзя.** `CRYODAQ_MOCK=1` исключает
  подключение к реальным приборам — даже если их
  `resource:` валидный. Это специально, чтобы не ошибиться.

## Добавление нового типа прибора (для разработчика)

1. Написать драйвер, наследующийся от
   `src/cryodaq/drivers/base.InstrumentDriver`. Реализовать
   `read_channels() -> list[Reading]`, `connect()`, `disconnect()`.
2. Зарегистрировать тип в `src/cryodaq/engine.py` фабрикой.
3. Добавить пример записи в `config/instruments.yaml` с комментарием
   «# type: <ваш_type>».
4. Написать unit-тест в `tests/drivers/`.

Этот флоу выходит за рамки «настройки прибора» — это уже dev-задача.
См. `docs/architecture.md` (раздел «Subsystem map», строка Drivers) для
карты драйверных модулей.

## См. также

- `docs/architecture.md` — архитектурный контекст приборного стека и ключевые
  правила (persistence-first, TSP-not-SCPI, dual-channel Keithley).
- `docs/safety-operator.md` — что делать при `fault_latched` из-за
  потери связи с прибором.
- `docs/deployment.md` — первичная установка ПО.
- `config/instruments.yaml` — текущая канонич. конфигурация на
  тестовом стенде.
- `config/safety.yaml` — пределы по времени / скоростям, влияющие
  на логику fault при потере связи.
