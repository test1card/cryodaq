# Задача: Интеграция cooldown predictor в CryoDAQ engine + GUI

## Контекст

Есть standalone cooldown predictor (`src/cryodaq/analytics/cooldown_predictor.py`, ~1300 строк).
Dual-channel progress-variable предиктор: ensemble референсных кривых, rate-based adaptive weighting, 
quality gate для ingest новых кривых, LOO cross-validation.

Нужно интегрировать его в engine как asyncio-сервис и отобразить в GUI на вкладке «Аналитика».

## Зависимость

Эта задача выполняется ПОСЛЕ task-persistence-ordering.md (SQLite commit before ZMQ publish).

## Часть 1: Рефакторинг cooldown_predictor.py

Файл уже лежит в `src/cryodaq/analytics/cooldown_predictor.py`. Превратить из CLI-скрипта в чистую библиотеку.

### Что убрать из модуля:
- **Все `print()` → `logging.getLogger(__name__)`**. Уровни: info для нормального хода, warning для skip/reject, error для ошибок.
- **`matplotlib.use("Agg")`** — удалить. Backend выбирается вызывающим кодом.
- **`import matplotlib` / `import matplotlib.pyplot as plt`** — перенести в функции plot_*() как ленивый импорт (`def plot_ensemble(...): import matplotlib.pyplot as plt`). Модуль не должен падать если matplotlib не установлен.
- **`generate_synthetic_curves()`** — вынести в `tests/analytics/conftest.py` как фикстуру. В production модуле не нужен.
- **`warnings.filterwarnings("ignore")`** — удалить. Подавление warnings — решение вызывающего кода.
- **Весь блок CLI** (cmd_build, cmd_predict, cmd_validate, cmd_demo, cmd_update, main(), argparse) — вынести в `tools/cooldown_cli.py`. Добавить entry point в pyproject.toml: `cryodaq-cooldown = "tools.cooldown_cli:main"`.

### Что оставить в модуле:
- Все dataclass'ы (ReferenceCurve, PredictionResult, ValidationResult, EnsembleModel)
- Константы (SMOOTH_WINDOW, W_COLD, W_WARM, etc.)
- Вся математика: compute_progress, prepare_curve, build_ensemble, predict, compute_rate_from_history
- Валидация: validate_new_curve, ingest_curve, ingest_from_raw_arrays
- LOO: validate_loo (полезна для тестов)
- Plot функции: plot_ensemble, plot_prediction, plot_validation (с ленивым matplotlib import)
- save_model, load_model

### Public API модуля (для cooldown_service.py):
```python
from cryodaq.analytics.cooldown_predictor import (
    load_model,
    predict,
    compute_rate_from_history,
    ingest_from_raw_arrays,
    EnsembleModel,
    PredictionResult,
)
```

## Часть 2: CooldownService — asyncio-сервис для engine

Новый файл: `src/cryodaq/analytics/cooldown_service.py`

### Архитектура

```
DataBroker
  └── CooldownService (подписчик, фильтр по каналам T_cold + T_warm)
        ├── Ring buffer текущего cooldown (deque, maxlen=100_000 ~28ч при 1Hz)
        ├── CooldownDetector (автодетекция начала/конца)
        ├── Periodic predict (каждые 30с)
        │     └── PredictionResult → DerivedMetric → DataBroker.publish()
        └── Auto-ingest (по окончании cooldown)
              └── ingest_from_raw_arrays() → model обновлена на диске
```

### Конфигурация: `config/cooldown.yaml`

```yaml
cooldown:
  enabled: true
  
  # Каналы для предиктора (имена из channels.yaml)
  channel_cold: "LS218_2/ch11"    # 2-я ступень криоголовки
  channel_warm: "LS218_2/ch10"    # Азотная плита
  
  # Модель
  model_dir: "data/cooldown_model"   # относительно CRYODAQ_ROOT
  
  # Детекция cooldown
  detect:
    start_rate_threshold: -5.0     # K/h, dT_cold/dt < этого = начало
    start_confirm_minutes: 10      # подтверждение в течение N минут
    end_T_cold_threshold: 6.0      # K, T_cold < этого = возможен конец
    end_rate_threshold: 0.1        # K/h, |dT/dt| < этого = стабильно
    end_confirm_minutes: 30        # подтверждение стабильности
  
  # Predict
  predict_interval_s: 30           # как часто вызывать predict()
  rate_window_h: 1.5               # окно для compute_rate_from_history
  
  # Auto-ingest
  auto_ingest: true                # автоматически добавлять кривую в модель
  min_cooldown_hours: 10.0         # минимальная длительность для ingest
```

### Класс CooldownService

```python
class CooldownService:
    """Asyncio-сервис предсказания cooldown для CryoDAQ engine."""

    def __init__(self, broker: DataBroker, config: dict, model_dir: Path):
        ...

    async def start(self) -> None:
        """Подписаться на DataBroker, загрузить модель, запустить задачи."""
        # Загрузить модель (может не существовать — тогда predict отключен до первого build)
        # Подписаться на broker с filter_fn по channel_cold и channel_warm
        # Запустить _consume_loop task

    async def stop(self) -> None:
        """Остановить задачи, отписаться."""

    async def _consume_loop(self) -> None:
        """Основной цикл: читает readings из очереди, обновляет состояние."""
        # Получить reading из очереди
        # Добавить в ring buffer
        # Обновить CooldownDetector
        # Если cooldown активен и прошло predict_interval_s — вызвать _do_predict()

    async def _do_predict(self) -> None:
        """Вызвать predict(), опубликовать результат как DerivedMetric."""
        # Собрать t_hours, T_cold, T_warm из ring buffer
        # compute_rate_from_history()
        # predict() — в executor (scipy может быть тяжёлым)
        # Опубликовать DerivedMetric:
        #   plugin_id = "cooldown_predictor"
        #   metric = "cooldown_eta"  (значение = t_remaining_hours)
        #   metadata = JSON с trajectory points, CI, progress, phase

    async def _on_cooldown_end(self) -> None:
        """Cooldown завершён: ingest кривой в модель."""
        # Если auto_ingest и duration >= min_cooldown_hours:
        #   ingest_from_raw_arrays() — в executor (disk I/O)
        #   Перезагрузить модель
        #   Логировать результат
```

### CooldownDetector (внутренний класс или отдельный)

```python
class CooldownDetector:
    """Автодетекция начала и конца cooldown цикла."""

    # Состояния: IDLE → COOLING → STABILIZING → COMPLETE
    # IDLE: ждём dT/dt < start_rate_threshold в течение start_confirm_minutes
    # COOLING: cooldown активен, predict() работает
    # STABILIZING: T_cold < end_T_cold_threshold, ждём стабильности
    # COMPLETE: cooldown завершён → вызвать ingest → IDLE
```

## Часть 3: Wiring в engine.py

```python
# После создания broker, перед scheduler.start():
cooldown_cfg = _cfg("cooldown")
cooldown_service: CooldownService | None = None
if cooldown_cfg.exists():
    cfg = yaml.safe_load(cooldown_cfg.open(...))
    if cfg.get("cooldown", {}).get("enabled", False):
        cooldown_service = CooldownService(
            broker=broker,
            config=cfg["cooldown"],
            model_dir=_PROJECT_ROOT / cfg["cooldown"]["model_dir"],
        )
        await cooldown_service.start()

# В shutdown:
if cooldown_service:
    await cooldown_service.stop()
```

## Часть 4: GUI — вкладка «Аналитика»

Вкладка «Аналитика» уже существует с двумя виджетами: «Тепловое сопротивление» (слева) и «Прогноз охлаждения» (справа), и pyqtgraph plot снизу.

### Виджет «Прогноз охлаждения» (правый верхний)

Расширить содержимое:
- **ETA крупным шрифтом**: «7ч 20мин ±45мин» (QLabel, font size 24+)
- **До 4K** — подпись
- **Progress bar**: визуальный QProgressBar + текстовый «68.5%»
- **Фаза**: «Фаза 1 (295K→50K)» / «Переход (S-bend)» / «Фаза 2 (50K→4K)» / «Стабилизация»
- **Статус модели**: «9 кривых, точность ±0.8ч» (маленький текст внизу)
- **Серый цвет когда cooldown не активен**: «Ожидание cooldown...»

### Plot (нижний pyqtgraph)

Во время cooldown:
- **Сплошная линия**: T_cold(t) — live данные (синий)
- **Пунктирная линия**: T_cold_predicted(t) — экстраполяция (голубой, style=DashLine)
- **Полупрозрачный band**: CI ±1σ (QColor с alpha=50)
- **Вертикальная зелёная пунктирная линия**: предсказанный момент достижения 4K
- **Ось X**: часы от начала cooldown
- **Ось Y**: log scale, 1-500K (как в plot_prediction)
- R_thermal продолжает показываться когда нет cooldown (текущее поведение)

### Данные для GUI

GUI получает DerivedMetric через ZMQ с:
- `plugin_id = "cooldown_predictor"`
- `metric = "cooldown_eta"` → обновить ETA label, progress bar
- `metadata` = JSON:
  ```json
  {
    "t_remaining_hours": 7.33,
    "t_remaining_ci68": 0.75,
    "progress": 0.685,
    "phase": "phase2",
    "n_references": 9,
    "cooldown_active": true,
    "future_t": [...],           // массив точек времени для пунктира
    "future_T_cold_mean": [...], // средняя экстраполяция
    "future_T_cold_upper": [...],// верхняя граница CI
    "future_T_cold_lower": [...] // нижняя граница CI
  }
  ```
- GUI парсит metadata, рисует пунктир. GUI НЕ импортирует cooldown_predictor напрямую.

## Часть 5: Тесты

### test_cooldown_predictor.py (юнит-тесты библиотеки)
- test_compute_progress: p=0 при 295K, p=1 при 4K/85K
- test_predict_with_synthetic: build ensemble из 3+ синтетических кривых, predict на разных точках
- test_ingest_quality_gate: reject кривые с duration < 10h, T_start < 150K, etc.
- test_ingest_updates_model: ingest → n_curves увеличился, model file перезаписан
- test_compute_rate_from_history: корректные rates на известных данных

### test_cooldown_service.py (интеграционные тесты сервиса)
- test_cooldown_detection_start: подать readings с dT/dt < -5 K/h → состояние = COOLING
- test_cooldown_detection_end: подать readings с T_cold < 6K + stable → состояние = COMPLETE
- test_predict_publishes_derived_metric: проверить что DerivedMetric попал в DataBroker
- test_auto_ingest_on_complete: cooldown завершён → ingest вызван → модель обновлена

### Синтетические данные для тестов
Перенести `generate_synthetic_curves()` в `tests/analytics/conftest.py` как pytest фикстуру:
```python
@pytest.fixture
def synthetic_curves():
    """9 синтетических cooldown кривых для тестов."""
    ...
```

## Команда

| Роль | Модель | Scope |
|------|--------|-------|
| Backend Engineer | Opus | cooldown_predictor.py рефакторинг, cooldown_service.py, engine.py wiring, config/cooldown.yaml |
| GUI Engineer | Sonnet | analytics_panel.py: виджет ETA + пунктир на plot |
| Test Engineer | Sonnet | test_cooldown_predictor.py, test_cooldown_service.py, conftest fixtures |

Dependencies: Backend → GUI (нужен формат DerivedMetric metadata). Backend → Test (нужен рефакторинг перед тестами).

## Критерии приёмки

1. `python -c "from cryodaq.analytics.cooldown_predictor import predict, load_model"` — работает, ничего не импортирует из matplotlib на уровне модуля
2. Engine запускается с `config/cooldown.yaml` (enabled: true) в mock режиме без падений
3. CooldownService детектирует начало cooldown по синтетическим данным в mock режиме
4. DerivedMetric с plugin_id="cooldown_predictor" появляется в DataBroker
5. GUI показывает ETA и пунктир на вкладке «Аналитика» (можно проверить визуально в mock)
6. После завершения cooldown модель обновлена на диске (ingest)
7. Все существующие + новые тесты проходят
8. CLI работает как раньше: `cryodaq-cooldown build/predict/validate/demo/update`
9. CLAUDE.md обновлён: новые модули, конфиг cooldown.yaml
