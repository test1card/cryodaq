# RELEASE_CHECKLIST.md

## Назначение

Этот чеклист используется перед RC-релизом или merge release-candidate ветки.
Он должен проверять только текущую реализованную реальность CryoDAQ, без пунктов про будущие функции.

## 1. Git и рабочее дерево

- [ ] Работа ведётся в worktree `CRYODAQ-CODEX`
- [ ] Текущая ветка совпадает с intended release branch
- [ ] `git status --short` просмотрен до начала финальной проверки
- [ ] Dirty worktree не затирается и не маскирует пользовательские изменения
- [ ] Merge в `master/main` не выполняется ad hoc до завершения RC-проверки

## 2. Установка и packaging path

- [ ] Поддерживаемый dev/test path: `pip install -e ".[dev,web]"`
- [ ] Базовый runtime path: `pip install -e .`
- [ ] Optional web path: `pip install -e ".[web]"`
- [ ] `pytest` запускается из того же environment, где выполнен `pip install -e ...`
- [ ] GUI/test workflow не проверяется без установленных `PySide6` и `pyqtgraph`
- [ ] Web dashboard не считается частью базового smoke path без extra `web`

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
- [ ] `Keithley 2604B`
- [ ] `Аналитика`
- [ ] `Теплопроводность`
- [ ] `Автоизмерение`
- [ ] `Алармы`
- [ ] `Журнал оператора`
- [ ] `Архив`
- [ ] `Калибровка`
- [ ] `Приборы`
- [ ] `Обзор` показывает summary/status widgets без старого layout drift
- [ ] `Keithley 2604B` не показывает ложный `ON` без backend truth
- [ ] `Журнал оператора` позволяет добавить запись и честно показывает empty state
- [ ] `Архив` не падает на missing report или partial artifacts
- [ ] `Калибровка` читает LakeShore channels из конфигурации и не делает вид, что calibration уже применена в runtime

## 5. Tray behavior

- [ ] Tray logic соответствует `src/cryodaq/gui/tray_status.py`
- [ ] Если системный tray недоступен, GUI продолжает работать без него
- [ ] `healthy` показывается только при connected backend, `alarm_count == 0` и допустимом safety state
- [ ] Unknown state не маскируется под healthy
- [ ] Tray не рекламирует здоровое состояние без backend truth

## 6. Experiment / report / archive workflow

- [ ] Experiment templates грузятся из `config/experiment_templates/*.yaml`
- [ ] Start/finalize experiment создают ожидаемый artifact layout
- [ ] Для эксперимента создаётся `data/experiments/<experiment_id>/metadata.json`
- [ ] Reports сохраняются в `data/experiments/<experiment_id>/reports/`
- [ ] Guaranteed artifact: `report.docx`
- [ ] Optional artifact: `report.pdf`
- [ ] Отсутствие PDF само по себе не считается RC-блокером
- [ ] Archive GUI читает `data/experiments/*/metadata.json`, а не отдельную archive DB
- [ ] Archive filters/search/details работают на текущем metadata contract
- [ ] Regenerate report идёт через существующий backend command path

## 7. Operator log workflow

- [ ] Operator log пишет записи в SQLite
- [ ] `log_entry` / `log_get` path работает end-to-end
- [ ] Записи журнала попадают в report generation
- [ ] Empty state журнала и подписи остаются операторскими и русскоязычными

## 8. Calibration workflow

- [ ] Calibration session start / capture / finalize path работает
- [ ] Fit и export JSON/CSV path работает
- [ ] Calibration artifacts пишутся в:
- [ ] `data/calibration/sessions/<session_id>/`
- [ ] `data/calibration/curves/<sensor_id>/<curve_id>/`
- [ ] GUI показывает raw points и fitted curve
- [ ] Apply path в runtime/instrument не реализован и это явно зафиксировано
- [ ] Кнопка `Применить в CryoDAQ` остаётся disabled, пока backend path не реализован

## 9. Report language and wording

- [ ] Operator-facing report text остаётся русскоязычным
- [ ] Section titles, field labels и empty states используют согласованный словарь
- [ ] Термины `эксперимент`, `оператор`, `шаблон`, `журнал оператора`, `алармы`, `снимок конфигурации` используются последовательно
- [ ] Technical ids и backend keys не утекли в operator-facing подписи без необходимости

## 10. Housekeeping and storage

- [ ] Persistence-first contract не нарушен
- [ ] Safety path не throttled
- [ ] Retention/compression не трогает experiment-linked DBs
- [ ] Housekeeping policy не удаляет experiment artifact folders
- [ ] Daily SQLite DB layout и artifact layout соответствуют текущим docs

## 11. Documentation sync

Проверить:

- [ ] `README.md`
- [ ] `CLAUDE.md`
- [ ] `CHANGELOG.md`
- [ ] `docs/operator_manual.md`
- [ ] `docs/deployment.md`
- [ ] `docs/architecture.md`

Сверить:

- [ ] состав и названия 10 вкладок
- [ ] tray behavior и caveats
- [ ] experiment/report/archive paths
- [ ] calibration limitation wording
- [ ] PDF best-effort wording
- [ ] TSP script naming: runtime path `tsp/p_const.lua`, `tsp/p_const_single.lua` как legacy/fallback artifact
- [ ] install/test instructions и packaging assumptions

## 12. Known RC caveats

- [ ] Применение calibration curve в runtime не реализовано
- [ ] PDF-конвертация отчётов остаётся best-effort и зависит от внешнего `LibreOffice` / `soffice`
- [ ] На новых версиях Python остаются deprecation warnings вокруг `asyncio.WindowsSelectorEventLoopPolicy`
- [ ] Эти caveats явно отражены в docs и не замаскированы под уже закрытые задачи
