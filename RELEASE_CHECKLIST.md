# RELEASE_CHECKLIST.md

## Назначение

Этот чеклист используется перед релизом CryoDAQ.
Он должен проверять только текущую реализованную реальность, без пунктов про будущие функции.

## 1. Git и рабочее дерево

- [ ] Работа ведётся на ветке `master`
- [ ] `git status --short` просмотрен до начала финальной проверки
- [ ] Нет незакоммиченных изменений в рабочем дереве
- [ ] Все тесты проходят

## 2. Установка и packaging path

- [ ] Поддерживаемый dev/test path: `pip install -e ".[dev,web]"`
- [ ] Базовый runtime path: `pip install -e .`
- [ ] Optional web path: `pip install -e ".[web]"`
- [ ] `pytest` запускается из того же environment, где выполнен `pip install -e ...`
- [ ] GUI/test workflow не проверяется без установленных `PySide6` и `pyqtgraph`
- [ ] Web dashboard не считается частью базового smoke path без extra `web`
- [ ] Parquet-экспорт работает из коробки — начиная с IV.4 `pyarrow>=15`
      входит в базовые зависимости, дополнительно ставить `[archive]`
      не требуется. Extra `archive` сохранён как no-op alias для
      обратной совместимости со старыми install-строками.

## 3. Обязательный regression matrix

Выполнить:

```powershell
python -m pytest tests/core -q
python -m pytest tests/storage -q
python -m pytest tests/drivers -q
python -m pytest tests/analytics -q
python -m pytest tests/gui -q
python -m pytest tests/reporting -q
```

- [ ] Все команды запущены и результаты зафиксированы
- [ ] Failures отделены от средовых проблем запуска pytest
- [ ] Warnings просмотрены и явно интерпретированы
- [ ] `WindowsSelectorEventLoopPolicy` deprecation warnings не приняты за функциональную регрессию продукта

## 4. GUI smoke checks

- [ ] `MainWindow` поднимается без расхождения с текущей документацией
- [ ] GUI содержит ровно 10 вкладок:
- [ ] `Обзор`
- [ ] `Эксперимент`
- [ ] `Keithley 2604B`
- [ ] `Аналитика`
- [ ] `Теплопроводность` (включает автоизмерение)
- [ ] `Алармы`
- [ ] `Служебный лог`
- [ ] `Архив`
- [ ] `Калибровка`
- [ ] `Приборы`
- [ ] `Обзор` показывает summary/status widgets без старого layout drift
- [ ] `Keithley 2604B` не показывает ложный `ON` без backend truth
- [ ] `Служебный лог` позволяет добавить запись и честно показывает empty state
- [ ] `Архив` не падает на missing report или partial artifacts
- [ ] `Калибровка` читает LakeShore channels из конфигурации и не показывает ложный applied state без подтверждённого backend runtime status

## 5. Tray behavior

- [ ] Tray logic соответствует `src/cryodaq/gui/tray_status.py`
- [ ] Если системный tray недоступен, GUI продолжает работать без него
- [ ] `healthy` показывается только при connected backend, `alarm_count == 0` и допустимом safety state
- [ ] Unknown state не маскируется под healthy
- [ ] Tray не рекламирует здоровое состояние без backend truth

## 6. Experiment / report / archive workflow

- [ ] Workflow задокументирован и проверен как experiment-card lifecycle, а не append-only operator log
- [ ] Во время активного эксперимента открыта ровно одна experiment card
- [ ] Завершение эксперимента закрывает карточку и переводит её в архивную запись
- [ ] Режим `Отладка` не создаёт архивные карточки экспериментов
- [ ] Режим `Отладка` не запускает автоматическую генерацию отчётов по эксперименту

- [ ] Experiment templates грузятся из `config/experiment_templates/*.yaml`
- [ ] Start/finalize experiment создают ожидаемый artifact layout
- [ ] Для эксперимента создаётся `data/experiments/<experiment_id>/metadata.json`
- [ ] Reports сохраняются в `data/experiments/<experiment_id>/reports/`
- [ ] Целевой внешний отчётный артефакт: `report_raw.pdf`
- [ ] Целевой внешний отчётный артефакт: `report_editable.docx`
- [ ] Отсутствие PDF само по себе не считается RC-блокером
- [ ] Archive GUI читает `data/experiments/*/metadata.json`, а не отдельную archive DB
- [ ] Archive filters/search/details работают на текущем metadata contract
- [ ] Regenerate report идёт через существующий backend command path

## 7. Operator log workflow

- [ ] Operator log пишет записи в SQLite
- [ ] `log_entry` / `log_get` path работает end-to-end
- [ ] Записи журнала прикрепляются к experiment card и участвуют в генерации отчёта как часть этой карточки
- [ ] Empty state журнала и подписи остаются операторскими и русскоязычными

## 8. Calibration workflow

- [ ] Поддержка `.330` / `.340` есть и покрыта тестами
- [ ] Chebyshev FIT следует task-level contour, и его статус явно отражён в docs
- [ ] Runtime apply и per-channel apply присутствуют, а их operator-facing ограничения описаны явно

- [ ] Calibration session start / capture / finalize path работает
- [ ] Fit и export `.330` / `.340` / JSON / CSV path работает
- [ ] Calibration artifacts пишутся в:
- [ ] `data/calibration/sessions/<session_id>/`
- [ ] `data/calibration/curves/<sensor_id>/<curve_id>/`
- [ ] Runtime apply path uses global on/off plus per-channel policy with conservative fallback to `KRDG`
- [ ] GUI не показывает misleading optimistic state, если runtime apply завершился fallback-сценарием

## 9. Язык и wording отчётов

- [ ] Operator-facing report text остаётся русскоязычным
- [ ] Section titles, field labels и empty states используют согласованный словарь
- [ ] Термины `эксперимент`, `оператор`, `шаблон`, `служебный лог`, `алармы`, `снимок конфигурации` используются последовательно
- [ ] Technical ids и backend keys не утекли в operator-facing подписи без необходимости

## 10. Housekeeping and storage

- [ ] Persistence-first contract не нарушен
- [ ] Safety path не throttled
- [ ] Retention/compression не трогает experiment-linked DBs
- [ ] Housekeeping policy не удаляет experiment artifact folders
- [ ] Daily SQLite DB layout и artifact layout соответствуют текущим docs

## 11. Синхронизация документации

- [ ] Устаревшие ожидания про `smub disable/hide/remove` явно выведены из контракта
- [ ] Терминология жизненного цикла карточки эксперимента синхронизирована
- [ ] Терминология режимов `Эксперимент / Отладка` синхронизирована
- [ ] Целевые названия отчётов `report_raw.pdf` / `report_editable.docx` синхронизированы

Проверить:

- [ ] `README.md`
- [ ] `CLAUDE.md`
- [ ] `CHANGELOG.md`
- [ ] `docs/operator_manual.md`
- [ ] `docs/deployment.md`
- [ ] `docs/architecture.md`

Сверить:

- [ ] состав и названия 10 вкладок
- [ ] поведение tray icon и ограничения
- [ ] пути experiment/report/archive
- [ ] формулировки ограничений калибровки
- [ ] формулировка PDF best-effort
- [ ] TSP скрипты: `tsp/p_const.lua` (runtime), `tsp/p_const_single.lua` (legacy/fallback)
- [ ] инструкции установки/тестирования и packaging

## 12. Известные caveat'ы RC

- [ ] PDF-конвертация остаётся best-effort и зависит от внешнего `LibreOffice` / `soffice`
- [ ] На новых версиях Python сохраняются deprecation warnings вокруг `asyncio.WindowsSelectorEventLoopPolicy`
- [ ] Эти ограничения явно отражены в документации и не скрыты как закрытые пробелы продукта
