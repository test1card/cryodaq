# Задача: Streamlining оператора + Калибровка датчиков (финальная версия)

Две части. Выполнять последовательно: сначала Часть 1, потом Часть 2.

---

# ЧАСТЬ 1: Рабочий процесс оператора

Цель: автоматические отчёты, журнал, архив, управление жизненным циклом данных.

---

## 1.1. Политика записи данных

### Принцип: engine пишет ВСЕГДА, но адаптивно

Engine запущен как сервис 24/7. Данные пишутся всегда — crash-safe инвариант не нарушается.

**Адаптивная частота вне эксперимента:**

Если ВСЕ условия выполнены одновременно:
- Все температуры > 250K (комнатная)
- |dT/dt| < 0.01 K/ч для всех каналов (стабильно)
- Нет активного эксперимента
- Прошло > 2 часов стабильности

→ Частота записи снижается до 1 раз в 60 секунд (вместо 1 Hz).

При ЛЮБОМ изменении → немедленно возврат к 1 Hz.

Throttle НЕ влияет на SafetyBroker — safety мониторинг 1 Hz всегда.

### Retention policy

Данные старше 90 дней и НЕ привязанные к эксперименту → автоматический gzip. Данные привязанные к эксперименту → хранятся вечно. DiskMonitor при проверке сканирует data/ на старые .db файлы.

---

## 1.2. Журнал оператора

Панель внизу вкладки «Обзор» (collapsible). QLineEdit + Enter или F5. Каждая запись: timestamp + текст + snapshot значений.

Telegram-бот: `/log текст` → запись.

Storage: таблица operator_log в daily SQLite.

ZMQ: `{"cmd": "log_entry", "text": "..."}` и `{"cmd": "log_get", ...}`.

Файлы: `src/cryodaq/storage/operator_log.py`, `src/cryodaq/gui/widgets/operator_log.py`.

---

## 1.3. Эксперименты: создание и ретроспективная разметка

Данные пишутся ВСЕГДА. Эксперимент = метка на timeline. Можно создать постфактум.

Диалог «Новый»: шаблон (dropdown), название, оператор (запоминается), поля из шаблона, галочка «Ретроспективный» с datetime.

Диалог «Завершить»: результат (успешный/частично/неудачный), комментарий, чекбоксы (PDF+DOCX, CSV, PNG).

После завершения → ReportGenerator → папка → «Открыть PDF / папку».

---

## 1.4. Шаблоны экспериментов (YAML)

`config/experiment_templates/`: cooldown_test, thermal_conductivity, thermocycling, cte_measurement, calibration, debug.

Формат: name, description, fields (dynamic), report_sections (список секций), auto (generate_report, export_csv, export_plots).

---

## 1.5. Модульный генератор отчётов

`src/cryodaq/reports/`: generator.py, context.py, elements.py, sections/*.py.

Секция = ABC: title(), generate(ctx) → list[ReportElement], export_data(ctx, dir) → list[Path].

Секции: title_page, cooldown_section, thermal_section, pressure_section, cycling_section, calibration_section, operator_log_section, alarms_section, config_section.

DOCX через python-docx. PDF через docx2pdf (если Word есть) или soffice --convert-to pdf (LibreOffice). Если ни одного нет → только DOCX, warning.

---

## 1.6. Структура файлов

```
data/experiments/
├── 2026-03/
│   └── 002_2026-03-15_теплопроводность_Cu-OFHC-14/
│       ├── report_raw.pdf
│       ├── report_editable.docx
│       ├── data/ (CSV файлы)
│       ├── plots/ (PNG графики)
│       ├── operator_log.txt
│       ├── config_snapshot.yaml
│       └── metadata.json
└── index.json
```

Именование: `{NNN}_{YYYY-MM-DD}_{sanitized_name}`. index.json — массив metadata для поиска.

---

## 1.7. Архив экспериментов

«Эксперимент → Архив» → QDialog: поиск, фильтр по типу/году, таблица, открыть PDF/папку, перегенерировать.

---

## 1.8. Минимальные требования

Добавить в docs/deployment.md: 4 GB RAM, любой HDD, Windows 10+, Python 3.12+. Нагрузка: ~50 КБ/сек при записи, ~1 КБ/сек при простое.

---

## Dependencies

`python-docx>=1.1` в pyproject.toml.

---

## Команда Части 1

| Роль | Модель | Scope |
|------|--------|-------|
| Backend | Opus | operator_log.py, reports/*, ExperimentManager (metadata, retroactive, auto-generate), scheduler.py (adaptive throttle), disk_monitor.py (retention), engine.py (log + experiment + report commands) |
| GUI | Sonnet | operator_log panel, experiment dialogs (create/finish/archive), QProgressDialog, templates/*.yaml |
| Test | Sonnet | operator_log, report generator (mock → DOCX), experiment lifecycle, throttle, retention |

## Критерии приёмки Части 1

1. F5 → журнал → Enter → запись с snapshot
2. Telegram /log → запись
3. Новый эксперимент с полями из шаблона
4. Ретроспективное создание
5. Завершение → PDF + DOCX + CSV + PNG
6. Архив с поиском
7. Adaptive throttle: комнатная стабильная → 1/мин
8. Retention: >90 дней без эксперимента → gzip
9. Все тесты проходят

---

# ЧАСТЬ 2: Калибровка датчиков

---

## 2.1. SRDG в LakeShore

Запрос `SRDG? 0` — raw voltage 8 каналов. Только в `_calibration_mode`. Channels: `{name}/ch{i}/raw`, unit="V". Mock: обратная DT-670 + noise. Poll interval при калибровке: configurable (default 0.3с).

---

## 2.2. CalibrationStore

Полная замена заглушки. Multi-zone Chebyshev fit:
- Зоны определяются по dV/dT автоматически
- Порядок подбирается cross-validation (7-12)
- Post-hoc downsampling: равномерно по T (~5000 точек)

Методы: T_from_V(), fit_curve(), export_340() (200 adaptive breakpoints), import_330(), import_340(), save/load_json().

---

## 2.3. CalibrationService

ZMQ: calibration_start/stop/fit/apply/export_340/status. Включает SRDG, пишет raw_data.csv, fit → JSON, apply → index.yaml + reload.

---

## 2.4. Файлы калибровки

```
config/calibrations/
├── index.yaml        ← канал → кривая
├── curves/           ← JSON, .330, generic
├── exports/          ← .340 для LakeShore
└── sessions/         ← raw data по сессиям
```

---

## 2.5. Вкладка «Калибровка»

8-я вкладка. Верх: таблица назначений + импорт. Низ: эталон, калибруемые, точность, запись/стоп/fit/export. График V vs T. Результаты fit: RMS, residuals. «Применить» одним кликом.

---

## Команда Части 2

| Роль | Модель | Scope |
|------|--------|-------|
| Backend | Opus | calibration.py (CalibrationStore), calibration_service.py, lakeshore_218s.py (SRDG), engine.py |
| GUI | Sonnet | calibration_panel.py, main_window.py (8 вкладок) |
| Test | Sonnet | Chebyshev fit, zone detection, .340 roundtrip, .330 import, downsampling |

## Критерии приёмки Части 2

1. SRDG readings в калибровочном режиме
2. fit_curve() RMS < 50мК
3. T_from_V() < 50мК
4. Downsampling равномерно по T
5. .340 export: 200 adaptive breakpoints
6. .330 import
7. Вкладка работает: запись → fit → apply → export
8. Все тесты проходят

---

## TODO (в CLAUDE.md)

- Etalon MultiLine TCP/IP драйвер: нужен протокол (MATLAB исходники или Wireshark capture)
> Статус (2026-03-16): частично реализовано / в значительной степени superseded.
>
> Сверка:
> - Этот файл смешивает уже доставленный workflow и устаревшие target-assumptions.
> - Основная операторская модель теперь строится вокруг experiment-card lifecycle, а не append-only operator log.
> - Целевой внешний отчётный контракт: `report_raw.pdf` + `report_editable.docx`; старые формулировки `report.pdf` / `report.docx` считать legacy.
> - Calibration RC state уже включает `.330` / `.340`, task-level Chebyshev FIT и runtime apply с per-channel policy.
> - Оставшаяся работа относится к дальнейшему operator rollout и non-blocking polish, а не к отсутствующему core backend scope.
