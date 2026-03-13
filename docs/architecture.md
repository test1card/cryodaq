# CryoDAQ — Архитектура системы сбора данных и управления криогенным стендом

**Версия:** 2.0  
**Дата:** 2026-03-13  
**Автор:** В. Фоменко / Claude  
**Статус:** Проектный документ, обсуждение

---

## 1. Назначение и scope

CryoDAQ — замена LabVIEW для криогенной лаборатории АКЦ ФИАН (проект Миллиметрон).

**Не просто DAQ.** Это измерительно-управляющая система с:
- Непрерывным сбором данных 24+ каналов при 1 Hz
- Замкнутым контуром поддержания мощности нагревателя (P = const) через Keithley 2604B
- Inline-аналитикой: тепловое сопротивление, cooldown curves, level detection
- Работой неделями без остановки
- Модульной архитектурой для расширения (интерферометр, новые приборы)

**Качественный рост относительно LabVIEW:**

| Аспект | LabVIEW сейчас | CryoDAQ |
|---|---|---|
| Устойчивость к crash ОС | Потеря всех данных | SQLite WAL: потеря ≤1с данных |
| Windows Update | Принудительный reboot в середине цикла | Контролируемые апдейты + Linux-ready |
| GUI crash | Всё умирает | Engine продолжает писать данные |
| Аналитика | Постфактум, вручную | Real-time: R_thermal, τ, dT/dt |
| Добавить прибор | Переписать VI | Добавить YAML + Python-файл |
| Удалённый мониторинг | Нет | Web + Telegram |
| Аудит конфигурации | Нет | Git versioning |
| Автоматические тесты | Нет | pytest, mock instruments |

---

## 2. Ограничения и решения

### 2.1 Кросс-платформенность (Windows → Linux)

**Ограничение:** Сейчас нет Linux-машины. Разработка и первое развёртывание — на Windows.

**Решение:** Весь стек кросс-платформенный. Platform-specific только тонкий слой:

| Компонент | Windows | Linux |
|---|---|---|
| pyvisa backend | NI-VISA (установлен) | linux-gpib или pyvisa-py |
| USB-TMC (Keithley) | NI-VISA | usbtmc kernel module |
| Serial порты | COM3, COM4... | /dev/ttyUSB0, /dev/ttyUSB1... |
| Service manager | NSSM / pywin32 Service | systemd |
| Watchdog | Внутренний (supervisor process) | systemd WatchdogSec |
| Paths | C:\CryoDAQ\data\ | /data/cryodaq/ |

Абстракция через `platform_config.yaml`:

```yaml
# Автоопределение при запуске, override вручную
platform:
  visa_backend: "ni"         # "ni" | "linux-gpib" | "py"
  data_path: "auto"          # auto = platform-dependent default
  service_manager: "nssm"    # "nssm" | "systemd" | "none"
```

### 2.2 Непрерывная работа (недели без остановки)

**Требование:** 24/7 запись, 1 Hz, 30+ каналов, нулевая потеря данных.

**Архитектурные решения:**

1. **Engine/GUI split** — два процесса. Engine пишет данные независимо от GUI.
2. **SQLite WAL** — crash-safe хранилище. Kill -9, BSOD, обрыв питания → потеря ≤1 записи.
3. **Process watchdog** — engine рестартует за 3 секунды при падении.
4. **Ring buffer в GUI** — фиксированный размер, нет memory leak.
5. **Disk rotation** — один файл на день, автоархивация, мониторинг свободного места.
6. **Instrument isolation** — один прибор завис → остальные работают.
7. **Graceful degradation** — потеря связи с прибором = красный статус, не crash.

### 2.3 Feedback loop: Keithley 2604B P=const

**Требование:** Подать мощность, поддерживать P=const при изменении R(T). Оба канала (smua/smub) опционально.

**Решение: TSP primary + Python supervisor.**

```
┌─────────────────────────┐
│ Keithley 2604B          │
│                         │
│  TSP Script (Lua):      │
│  • P_target = заданное  │
│  • Измерить V, I        │
│  • R = V/I              │
│  • V_new = sqrt(P×R)    │
│  • Применить V_new      │
│  • Rate: 10-50 Hz       │  ◄── Аппаратный контур, не зависит от ПК
│  • Timeout: если нет    │
│    heartbeat 30с →      │
│    source OFF           │
│  • Буфер: V, I, R, P   │
│    каждые 100 мс        │
└────────────┬────────────┘
             │ USB-TMC
┌────────────┴────────────┐
│ CryoDAQ Engine          │
│                         │
│  Keithley Supervisor:   │
│  • Загрузить TSP при    │
│    старте               │
│  • Задать P_target      │
│  • Heartbeat каждые 10с │
│  • Читать буфер V,I,R,P │
│  • Аварийный OFF        │
│  • Compliance limits    │
└─────────────────────────┘
```

**Failsafe:** TSP-скрипт содержит watchdog. Если Python-supervisor не отправил heartbeat за 30 секунд → Keithley сам выключает source. Это защита от зависания софта с поданным напряжением при 4K.

---

## 3. Приборы первой версии

### LakeShore 218S × 3 (Temperature Monitor)

- **Интерфейс:** GPIB (IEEE-488), три адреса на одном bus
- **Каналов:** 8 × 3 = 24 канала температуры
- **Протокол:** SCPI-like. `KRDG? 0` — все 8 каналов разом
- **Polling:** Читать все 8 одной командой (~100 мс), три прибора ≈ 300-400 мс. Запас для 1 Hz.
- **Данные:** DT-670B1-CU silicon diodes, 1.4K — 500K, ±0.05K calibrated
- **Калибровка:** Кривые по ГОСТ Р 8.879, хранятся и в приборе и в CryoDAQ

### Keithley 2604B (Source-Measure Unit)

- **Интерфейс:** USB-TMC
- **Каналов:** 2 (smua, smub), использование зависит от эксперимента
- **Протокол:** TSP (Lua), НЕ SCPI
- **Режим:** P=const feedback loop внутри TSP, supervisor из Python
- **Данные:** V, I, R, P с обоих каналов, буферизация внутри Keithley
- **Safety:** Compliance voltage/current limits в TSP; software interlock на перегрев

### Вакуумметр (TBD)

- Добавится позже как отдельный модуль
- Архитектура готова: новый драйвер + YAML-конфиг

### Интерферометр (planned, LAN)

- Будущее расширение через TCP-драйвер
- Возможно проприетарный протокол поверх TCP

---

## 4. Архитектура

### 4.1 Процессная модель

```
┌─────────────────────────────────────────────────────────────────┐
│                        Operator PC (Windows / Linux)            │
│                                                                 │
│  ┌─────────────────────────────────┐  ┌──────────────────────┐  │
│  │        cryodaq-engine           │  │    cryodaq-gui       │  │
│  │        (background process)     │  │    (desktop app)     │  │
│  │                                 │  │                      │  │
│  │  ┌───────────┐ ┌────────────┐  │  │  PySide6 + pyqtgraph │  │
│  │  │ Scheduler │ │ DataBroker │──┼──┼──▶ Live plots        │  │
│  │  │ (asyncio) │ │ (pub/sub)  │  │  │  Alarm panel         │  │
│  │  └─────┬─────┘ └──┬───┬────┘  │  │  Instrument status    │  │
│  │        │          │   │       │  │  Experiment control    │  │
│  │  ┌─────┴─────┐   │   │       │  │                      │  │
│  │  │ Drivers   │   │   │       │  │  Можно закрыть/       │  │
│  │  │ (async)   │   │   │       │  │  открыть без потери   │  │
│  │  └───────────┘   │   │       │  │  данных               │  │
│  │               ┌──┴┐ ┌┴────┐  │  └──────────┬───────────┘  │
│  │               │SQL│ │Alarm│  │             │              │
│  │               │WAL│ │Eng. │  │         ZeroMQ             │
│  │               └───┘ └──┬──┘  │      PUB/SUB + REQ/REP     │
│  │                     ┌──┴──┐  │             │              │
│  │  ┌───────────┐      │Notif│  │  ┌──────────┴───────────┐  │
│  │  │ Plugin    │      │TG+WS│  │  │    cryodaq-web       │  │
│  │  │ Pipeline  │      └─────┘  │  │    (optional)        │  │
│  │  │ (analytics│               │  │    FastAPI + WS       │  │
│  │  │  hot-load)│               │  │    → phone/browser    │  │
│  │  └───────────┘               │  └──────────────────────┘  │
│  └─────────────────────────────────┘                          │
│            │              │             │                      │
│         USB-TMC        GPIB          Serial/TCP                │
│            │              │             │                      │
│     Keithley 2604B   LakeShore      Vac.gauge                │
│     (TSP P=const)    218S × 3      (future)                  │
│                      (24 ch)                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Data flow

```
Instrument Drivers (async)
    │
    ▼
DataBroker (in-process pub/sub, asyncio.Queue per subscriber)
    │
    ├──▶ SQLiteWriter (WAL mode, 1 file/day, flush every 1s)
    │
    ├──▶ ZMQ Publisher (tcp://localhost:5555) ──▶ GUI / Web
    │
    ├──▶ AlarmEngine (state machine, hysteresis)
    │       │
    │       ├──▶ Telegram Bot
    │       └──▶ WebSocket push
    │
    └──▶ PluginPipeline (hot-reloadable analytics)
            │
            ├── LevelDetector
            ├── ThermalCalculator (R_th = ΔT/Q)
            ├── CooldownEstimator
            └── CustomPlugin (user-defined)
                    │
                    ▼
            Enriched data ──▶ SQLite (derived_data table)
                           ──▶ ZMQ (analytics channel)
```

### 4.3 Компоненты

#### DataBroker

```python
class DataBroker:
    """In-process pub/sub. Zero-copy для внутренних subscribers."""
    
    async def publish(self, readings: list[Reading]) -> None:
        """Рассылает readings всем подписчикам. Non-blocking."""
        for queue in self._subscribers.values():
            try:
                queue.put_nowait(readings)
            except asyncio.QueueFull:
                # Subscriber не успевает — дропнуть oldest
                queue.get_nowait()
                queue.put_nowait(readings)
    
    def subscribe(self, name: str, maxsize: int = 100) -> asyncio.Queue:
        """Подписаться. maxsize предотвращает OOM при медленном subscriber."""
        q = asyncio.Queue(maxsize=maxsize)
        self._subscribers[name] = q
        return q
```

#### SQLiteWriter (crash-safe storage)

```python
class SQLiteWriter:
    """Crash-safe запись данных.
    
    - WAL mode: concurrent read/write, crash recovery
    - 1 файл на день: data_2026-03-13.db
    - Batch insert каждую секунду (50 readings × 1 batch vs 50 отдельных INSERT)
    - PRAGMA journal_size_limit для ограничения WAL-файла
    """
    
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,        -- time.time(), UTC
        instrument_id TEXT NOT NULL,
        channel TEXT NOT NULL,
        value REAL NOT NULL,
        unit TEXT NOT NULL,
        status TEXT DEFAULT 'OK',
        -- Composite index for fast time-range queries
        UNIQUE(timestamp, instrument_id, channel)
    );
    CREATE INDEX IF NOT EXISTS idx_time ON readings(timestamp);
    CREATE INDEX IF NOT EXISTS idx_instrument ON readings(instrument_id, timestamp);
    
    -- Keithley source data (separate table, higher rate possible)
    CREATE TABLE IF NOT EXISTS source_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,
        channel TEXT NOT NULL,           -- 'smua' | 'smub'
        voltage REAL,
        current REAL,
        resistance REAL,
        power REAL,
        compliance_hit INTEGER DEFAULT 0
    );
    
    -- Derived analytics data
    CREATE TABLE IF NOT EXISTS derived_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,
        plugin_id TEXT NOT NULL,         -- 'thermal_calculator', 'level_detector'
        metric TEXT NOT NULL,            -- 'R_thermal', 'tau', 'is_stable'
        value REAL,
        metadata TEXT                    -- JSON for complex data
    );
    
    -- Experiment metadata
    CREATE TABLE IF NOT EXISTS experiments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_time REAL NOT NULL,
        end_time REAL,
        name TEXT NOT NULL,
        operator TEXT,
        cryostat TEXT,
        sample TEXT,
        description TEXT,
        config_snapshot TEXT,            -- JSON dump of instruments.yaml at start
        status TEXT DEFAULT 'RUNNING'    -- RUNNING | COMPLETED | ABORTED
    );
    """
    
    async def init(self, date: str):
        path = self.data_dir / f"data_{date}.db"
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")  # Faster, still crash-safe with WAL
        self.conn.execute("PRAGMA journal_size_limit=104857600")  # 100 MB WAL limit
        self.conn.executescript(self.SCHEMA)
    
    async def write_batch(self, readings: list[Reading]):
        """Batch INSERT. Вызывается раз в секунду."""
        self.conn.executemany(
            "INSERT OR IGNORE INTO readings VALUES (NULL,?,?,?,?,?,?)",
            [(r.timestamp, r.instrument_id, r.channel, r.value, r.unit, r.status)
             for r in readings]
        )
        self.conn.commit()  # Одна транзакция на весь batch
```

#### AlarmEngine

```python
@dataclass
class AlarmState:
    name: str
    status: str = "OK"           # OK → ACTIVE → ACKNOWLEDGED
    last_trigger: float = 0.0
    trigger_count: int = 0
    
class AlarmEngine:
    """State machine per alarm. Hysteresis prevents flapping."""
    
    async def evaluate(self, reading: Reading):
        for alarm in self._alarms_for(reading.instrument_id, reading.channel):
            triggered = self._check_condition(alarm, reading.value)
            state = self._states[alarm.name]
            
            if triggered and state.status == "OK":
                state.status = "ACTIVE"
                state.last_trigger = reading.timestamp
                state.trigger_count += 1
                await self._notify(alarm, reading, "TRIGGERED")
                
            elif not triggered and state.status in ("ACTIVE", "ACKNOWLEDGED"):
                # Clear only if value crosses threshold - hysteresis
                if self._below_hysteresis(alarm, reading.value):
                    state.status = "OK"
                    await self._notify(alarm, reading, "CLEARED")
```

#### Plugin Pipeline (hot-reload analytics)

```python
class PluginPipeline:
    """Загружает .py файлы из plugins/, перезагружает при изменении.
    
    Каждый плагин — Python-файл с классом, наследующим AnalyticsPlugin.
    Файлы мониторятся через watchdog (filesystem events).
    При изменении: reload модуль, пересоздать экземпляр, без рестарта engine.
    """
    
    def __init__(self, plugins_dir: Path):
        self.plugins_dir = plugins_dir
        self._plugins: dict[str, AnalyticsPlugin] = {}
        self._observer = Observer()  # watchdog filesystem observer
    
    async def process(self, readings: list[Reading]) -> list[DerivedMetric]:
        """Прогнать readings через все активные плагины."""
        results = []
        for name, plugin in self._plugins.items():
            try:
                metrics = await plugin.process(readings)
                results.extend(metrics)
            except Exception as e:
                logger.error(f"Plugin {name} failed: {e}")
                # Плагин упал — не роняем pipeline
        return results

class AnalyticsPlugin(ABC):
    """Базовый класс для плагинов аналитики."""
    
    @abstractmethod
    async def process(self, readings: list[Reading]) -> list[DerivedMetric]:
        ...
    
    def configure(self, config: dict) -> None:
        """Вызывается при загрузке/перезагрузке. Override опционально."""
        pass
```

Пример плагина — thermal calculator:

```python
# plugins/thermal_calculator.py
class ThermalCalculator(AnalyticsPlugin):
    """Расчёт теплового сопротивления R_th = ΔT / Q.
    
    Нужны:
    - Keithley: P (мощность нагревателя)
    - LakeShore: T_hot (температура горячей стороны), T_cold (холодной)
    
    Конфигурация в plugins/thermal_calculator.yaml:
      hot_sensor: {instrument: ls218_1, channel: "1"}
      cold_sensor: {instrument: ls218_1, channel: "5"}
      heater: {instrument: keithley_2604b, channel: "smua"}
    """
    
    async def process(self, readings):
        T_hot = self._find(readings, self.cfg["hot_sensor"])
        T_cold = self._find(readings, self.cfg["cold_sensor"])
        P = self._find(readings, self.cfg["heater"])
        
        if all(v is not None for v in [T_hot, T_cold, P]) and P > 0:
            R_th = (T_hot - T_cold) / P
            return [DerivedMetric(
                plugin_id="thermal_calculator",
                metric="R_thermal",
                value=R_th,
                metadata=json.dumps({"T_hot": T_hot, "T_cold": T_cold, "P": P})
            )]
        return []
```

#### Data Replay

```python
class ReplaySource:
    """Подменяет live-драйверы данными из SQLite.
    
    Использование: DataBroker не знает откуда данные.
    Replay подаёт записи с тем же timing что был при записи,
    или ускоренно (×10, ×100).
    
    Это позволяет:
    - Прогнать новый плагин аналитики по старым данным
    - Отладить GUI без подключённого железа
    - Показать результат коллегам без запуска стенда
    """
    
    async def replay(self, db_path: Path, speed: float = 1.0):
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT * FROM readings ORDER BY timestamp")
        
        prev_ts = None
        for row in cursor:
            reading = Reading(*row[1:])  # skip id
            if prev_ts is not None:
                delay = (reading.timestamp - prev_ts) / speed
                await asyncio.sleep(delay)
            await self.broker.publish([reading])
            prev_ts = reading.timestamp
```

#### Interlock Engine

```python
class InterlockEngine:
    """Программные блокировки. НЕ заменяет аппаратные, дополняет.
    
    Примеры:
    - Keithley source OFF если T > T_max (перегрев)
    - Запрет подачи мощности если P_vacuum > threshold (нет вакуума)
    - Запрет увеличения P если dT/dt > threshold (слишком быстрый нагрев)
    
    Каждый interlock:
    - Проверяется КАЖДЫЙ цикл (1 Hz)
    - При срабатывании: немедленное действие + alarm + лог
    - Автоматический взвод после устранения условия (с задержкой)
    - Нельзя override из GUI без ввода кода/пароля
    """
    
    @dataclass
    class Interlock:
        name: str
        condition: str              # Python expression: "T_hot > 350"
        action: str                 # "keithley.source_off('smua')"
        severity: str               # "CRITICAL" | "WARNING"
        auto_reset_delay_s: float   # Задержка перед автосбросом
        requires_ack: bool          # Нужно ручное подтверждение?
```

### 4.4 Калибровочные кривые

```python
class CalibrationStore:
    """Хранение и применение калибровочных кривых.
    
    Каждый DT-670B1-CU имеет индивидуальную кривую (калибровка по ГОСТ Р 8.879).
    LakeShore хранит кривые внутри прибора, но CryoDAQ дублирует их для:
    - Аналитики (пересчёт сырых данных)
    - Верификации (сравнить свою кривую с приборной)
    - Архивации (привязка кривой к эксперименту)
    
    Формат: JSON или CSV (serial_number, T_K[], R_Ohm[] или V_mV[])
    Интерполяция: scipy.interpolate.CubicSpline (monotonic)
    """
    
    def __init__(self, curves_dir: Path):
        self.curves_dir = curves_dir  # config/calibration/
        self._curves: dict[str, CubicSpline] = {}
    
    def voltage_to_temp(self, serial: str, voltage_mV: float) -> float:
        """Пересчёт напряжения в температуру по индивидуальной кривой."""
        return float(self._curves[serial](voltage_mV))
```

---

## 5. Структура проекта

```
cryodaq/
├── pyproject.toml              # Project metadata, dependencies
├── .claude/
│   └── skills/
│       └── cryodaq-team-lead.md  # Agent Teams SKILL.md
├── config/
│   ├── instruments.yaml        # Приборы: адреса, каналы, polling
│   ├── alarms.yaml             # Пороги, гистерезис, нотификации
│   ├── interlocks.yaml         # Программные блокировки
│   ├── platform.yaml           # Platform-specific: paths, VISA backend
│   ├── experiments.yaml        # Шаблоны экспериментов
│   └── calibration/            # Калибровочные кривые (.json)
│       ├── DT670_SN001.json
│       ├── DT670_SN002.json
│       └── ...
├── tsp/                        # TSP-скрипты для Keithley
│   ├── p_const_single.lua      # P=const, один канал
│   ├── p_const_dual.lua        # P=const, оба канала
│   ├── iv_sweep.lua            # I-V характеристика
│   └── safe_shutdown.lua       # Аварийное выключение source
├── plugins/                    # Hot-reloadable analytics
│   ├── thermal_calculator.py
│   ├── thermal_calculator.yaml
│   ├── cooldown_estimator.py
│   ├── level_detector.py
│   └── README.md               # Как написать плагин
├── src/
│   └── cryodaq/
│       ├── __init__.py
│       ├── engine.py           # Entry point для headless engine
│       ├── gui_app.py          # Entry point для GUI
│       │
│       ├── core/
│       │   ├── broker.py       # DataBroker (pub/sub)
│       │   ├── scheduler.py    # Instrument polling scheduler
│       │   ├── alarm.py        # AlarmEngine (state machine)
│       │   ├── interlock.py    # InterlockEngine
│       │   ├── config.py       # YAML config loader (pydantic validation)
│       │   ├── experiment.py   # Experiment lifecycle management
│       │   ├── watchdog.py     # Self-monitoring + heartbeat
│       │   └── zmq_bridge.py   # ZMQ PUB/SUB + REQ/REP for GUI
│       │
│       ├── drivers/
│       │   ├── base.py         # ABC: InstrumentDriver + Reading dataclass
│       │   ├── transport/
│       │   │   ├── gpib.py     # GPIB via pyvisa
│       │   │   ├── serial.py   # Serial via pyserial-asyncio
│       │   │   ├── tcp.py      # TCP/socket
│       │   │   └── usbtmc.py   # USB-TMC via pyvisa
│       │   └── instruments/
│       │       ├── lakeshore_218s.py
│       │       ├── keithley_2604b.py  # TSP loader + supervisor
│       │       └── _mock.py           # Mock drivers for testing
│       │
│       ├── storage/
│       │   ├── sqlite_writer.py  # Primary crash-safe storage
│       │   ├── hdf5_export.py    # Export to HDF5 for analysis
│       │   ├── csv_export.py     # Export to CSV
│       │   └── replay.py         # Data replay from SQLite
│       │
│       ├── analytics/
│       │   ├── plugin_loader.py  # Hot-reload plugin pipeline
│       │   ├── base_plugin.py    # ABC: AnalyticsPlugin
│       │   └── calibration.py    # CalibrationStore
│       │
│       ├── gui/
│       │   ├── main_window.py
│       │   ├── widgets/
│       │   │   ├── temp_panel.py         # 24-ch temperature overview
│       │   │   ├── keithley_panel.py     # SMU status, P/V/I/R plots
│       │   │   ├── analytics_panel.py    # R_thermal, cooldown curves
│       │   │   ├── live_plot.py          # pyqtgraph with ring buffer
│       │   │   ├── alarm_panel.py        # Active alarms + acknowledge
│       │   │   ├── instrument_status.py  # Green/yellow/red per instrument
│       │   │   ├── experiment_panel.py   # Start/stop/describe experiment
│       │   │   └── interlock_panel.py    # Interlock status + manual override
│       │   └── themes/
│       │       └── dark.qss
│       │
│       ├── web/                  # Optional remote monitoring
│       │   ├── server.py         # FastAPI + WebSocket
│       │   └── static/           # Minimal web dashboard
│       │
│       └── notifications/
│           ├── telegram.py
│           └── websocket.py
│
├── tests/
│   ├── conftest.py
│   ├── test_drivers/
│   │   ├── test_lakeshore_218s.py
│   │   └── test_keithley_2604b.py
│   ├── test_core/
│   │   ├── test_broker.py
│   │   ├── test_alarm.py
│   │   ├── test_interlock.py
│   │   └── test_experiment.py
│   ├── test_storage/
│   │   ├── test_sqlite_writer.py   # Including crash simulation
│   │   └── test_replay.py
│   ├── test_analytics/
│   │   └── test_thermal_calculator.py
│   └── fixtures/
│       ├── mock_scpi_responses.py
│       ├── mock_tsp_responses.py
│       └── sample_data.db          # SQLite with real test data
│
└── docs/
    ├── operator_manual.md     # Инструкция для операторов (РУС)
    ├── plugin_guide.md        # Как написать плагин аналитики
    ├── instrument_protocols.md
    └── deployment.md
```

---

## 6. Конфигурация

### instruments.yaml

```yaml
instruments:
  ls218_cryostat_1:
    driver: lakeshore_218s
    address: "GPIB0::12::INSTR"
    channels: [1, 2, 3, 4, 5, 6, 7, 8]
    poll_interval_s: 1.0
    read_mode: "all_at_once"        # KRDG? 0 — все каналы одной командой
    calibration:
      1: "DT670_SN001"
      2: "DT670_SN002"
      # ...
    labels:                          # Человеческие имена каналов
      1: "Образец, горячая сторона"
      2: "Образец, холодная сторона"
      3: "1-й экран"
      # ...
    description: "Криостат 1, датчики образца и экранов"

  ls218_cryostat_2:
    driver: lakeshore_218s
    address: "GPIB0::14::INSTR"
    channels: [1, 2, 3, 4, 5, 6, 7, 8]
    poll_interval_s: 1.0
    read_mode: "all_at_once"
    description: "Криостат 1, датчики холодного стола"

  ls218_cryostat_3:
    driver: lakeshore_218s
    address: "GPIB0::16::INSTR"
    channels: [1, 2, 3, 4, 5, 6, 7, 8]
    poll_interval_s: 1.0
    read_mode: "all_at_once"
    description: "Криостат 1, доп. точки"

  keithley_2604b:
    driver: keithley_2604b
    address: "USB0::0x05E6::0x2604::auto::INSTR"
    channels: ["smua", "smub"]       # Оба доступны, использование по задаче
    mode: "tsp_managed"              # TSP скрипт управляет source
    tsp_script: "p_const_single.lua" # Default, override per experiment
    poll_interval_s: 1.0             # Чтение буфера раз в секунду
    safety:
      compliance_v: 40.0             # Max voltage, V
      compliance_i: 1.0              # Max current, A
      max_power_w: 5.0               # Software power limit
      watchdog_timeout_s: 30         # TSP auto-off if no heartbeat
    description: "SMU для нагревателей"
```

### interlocks.yaml

```yaml
interlocks:
  - name: "Перегрев образца"
    description: "Выключить нагреватель если T > 350 K"
    trigger:
      instrument: "ls218_cryostat_1"
      channel: "1"
      condition: "value > 350.0"
    action:
      type: "keithley_source_off"
      target: "keithley_2604b"
      channel: "smua"
    severity: "CRITICAL"
    auto_reset: false                # Только ручной сброс
    notify: [telegram]

  - name: "Слишком быстрый нагрев"
    description: "Снизить мощность если dT/dt > 2 K/min"
    trigger:
      type: "rate_of_change"
      instrument: "ls218_cryostat_1"
      channel: "1"
      condition: "rate > 2.0"        # K/min
      window_s: 60                   # Окно для расчёта dT/dt
    action:
      type: "keithley_reduce_power"
      target: "keithley_2604b"
      factor: 0.5                    # Снизить P до 50%
    severity: "WARNING"
    auto_reset: true
    auto_reset_delay_s: 120
```

---

## 7. Стек технологий

| Компонент | Технология | Кросс-платформ? |
|---|---|---|
| Язык | Python 3.12+ | Да |
| Async | asyncio | Да |
| GPIB | pyvisa (NI-VISA на Win, linux-gpib на Linux) | Да* |
| USB-TMC | pyvisa | Да |
| Serial | pyserial-asyncio | Да |
| TCP | asyncio stdlib | Да |
| GUI | PySide6 + pyqtgraph | Да |
| GUI↔Engine IPC | ZeroMQ (pyzmq) | Да |
| Storage (primary) | SQLite3 (WAL mode) | Да |
| Storage (export) | h5py (HDF5) | Да |
| Config | YAML (pyyaml) + pydantic validation | Да |
| Analytics | Plugin pipeline (importlib + watchdog) | Да |
| Notifications | aiohttp (Telegram) | Да |
| Web dashboard | FastAPI + WebSocket (optional) | Да |
| Tests | pytest + pytest-asyncio | Да |
| Service (Win) | NSSM or pywin32 | Win only |
| Service (Linux) | systemd | Linux only |

*pyvisa backend varies by OS but API is identical

---

## 8. Этапы разработки

### Phase 1: Core + LakeShore read-only (6-8 недель)

**Deliverable:** Engine читает 24 канала температуры, пишет в SQLite, GUI показывает live-графики.

- [ ] Project scaffold (pyproject.toml, structure, CI)
- [ ] Reading dataclass, InstrumentDriver ABC
- [ ] GPIB transport (pyvisa)
- [ ] LakeShore 218S driver (read all channels, mock mode)
- [ ] DataBroker (pub/sub)
- [ ] SQLiteWriter (WAL, batch insert, daily rotation)
- [ ] Scheduler (per-instrument async tasks)
- [ ] Engine entry point (engine.py)
- [ ] ZMQ bridge (engine → GUI)
- [ ] GUI: main window + temp panel (pyqtgraph, ring buffer)
- [ ] GUI: instrument status panel (green/yellow/red)
- [ ] Basic alarms (threshold → console log)
- [ ] Config loading + validation (pydantic)
- [ ] Tests: driver mock, broker, sqlite crash simulation
- [ ] Platform abstraction (paths, VISA backend)

**Exit criteria:** 72 часа непрерывной записи, данные корректны, GUI responsive, zero memory growth.

### Phase 2: Keithley + analytics (4-6 недель)

- [ ] USB-TMC transport
- [ ] Keithley 2604B driver (TSP loader, buffer reader, supervisor)
- [ ] TSP scripts (p_const_single.lua, safe_shutdown.lua)
- [ ] Keithley watchdog (heartbeat, auto-off)
- [ ] Plugin pipeline (hot-reload)
- [ ] ThermalCalculator plugin
- [ ] CooldownEstimator plugin
- [ ] LevelDetector plugin
- [ ] GUI: Keithley panel (P/V/I/R plots)
- [ ] GUI: analytics panel (R_thermal, cooldown curve)
- [ ] Experiment metadata (start/stop/describe)
- [ ] Calibration store
- [ ] Interlock engine (basic: overheat → source off)

**Exit criteria:** Полный цикл измерения теплопроводности: P подана → T стабилизировалась → R_thermal рассчитан → данные записаны с metadata.

### Phase 3: Reliability + monitoring (3-4 недели)

- [ ] Full alarm engine (state machine, hysteresis, escalation)
- [ ] Telegram notifications
- [ ] Web dashboard (FastAPI + WebSocket)
- [ ] Data replay
- [ ] HDF5 export
- [ ] CSV export
- [ ] Full interlock set
- [ ] Config versioning (git hook on save)
- [ ] Disk space monitoring + rotation
- [ ] NSSM service setup (Windows)
- [ ] Operator manual (Russian)
- [ ] Plugin developer guide

**Exit criteria:** Недельный тест без вмешательства. Алармы приходят в Telegram. Web-dashboard работает с телефона. Engine пережил имитацию crash (taskkill) и восстановился за <5с.

### Phase 4: Linux migration (когда будет железо, 1-2 недели)

- [ ] Ubuntu 24.04 LTS setup
- [ ] linux-gpib / pyvisa-py backend
- [ ] USB-TMC udev rules
- [ ] systemd service + watchdog
- [ ] Validation: результаты идентичны Windows

---

## 9. Sizing и производительность

### Данные

```
24 каналов LakeShore × 1 Hz = 24 readings/s
2 канала Keithley × 1 Hz (buffer dump) = ~20 readings/s (10 Hz internal → 1s batch)
Analytics: ~10 derived metrics/s

Total: ~55 rows/s → 4.7M rows/day → 33M rows/week

SQLite row ≈ 80 bytes → 380 MB/day → 2.6 GB/week
С индексами: ~500 MB/day → 3.5 GB/week

HDF5 export (compact): ~200 MB/day
```

### Memory

```
Engine:
  Python baseline: ~50 MB
  pyvisa: ~20 MB
  SQLite buffers: ~10 MB
  DataBroker queues: ~5 MB
  Total: ~100 MB (stable, no growth)

GUI:
  PySide6 baseline: ~100 MB
  pyqtgraph (24 plots × 3600 points ring buffer): ~50 MB
  ZMQ receiver: ~10 MB
  Total: ~200 MB (stable, ring buffer prevents growth)
```

### CPU

```
Polling 3 GPIB + 1 USB-TMC: ~5% single core
SQLite writes: <1%
GUI updates at 1 Hz: <5%
Analytics plugins: <5%
Total: <20% single core. Скучающая machine.
```
