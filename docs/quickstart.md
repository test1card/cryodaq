# Быстрый старт CryoDAQ

Одна страница: zero → первое измерение на лабораторном ПК. Только команды,
без предисловий. Полное руководство — `docs/operator_manual.md`, детали
установки — `docs/deployment.md`, разбор неисправностей —
`docs/troubleshooting.md`.

## 1. Требования

- Windows 10/11 или Linux
- Python `>=3.12`
- Git
- (опционально) VISA backend / драйверы приборов, `LibreOffice`/`soffice`
  для best-effort PDF-отчётов

## 2. Получение кода

```powershell
git clone https://github.com/test1card/cryodaq.git
cd cryodaq
```

## 3. Установка

Windows, воспроизводимая установка из lockfile (рекомендуется для
операторского ПК):

```powershell
.\install.bat
```

Делает: проверяет Python 3.12+ и fail-closed SQLite policy, устанавливает
`requirements-lock.txt` и проект без повторного dependency resolution,
выполняет `pip check`, затем создаёт ярлык `CryoDAQ` на рабочем столе. Если
SQLite попадает в запрещённый WAL-reset диапазон, установка останавливается;
см. раздел SQLite в `docs/deployment.md`. Командный слой batch-файла намеренно
ASCII-only для надёжного запуска в штатном `cmd.exe`.

Ручная установка (Windows/Linux, dev-окружение):

```bash
python -m pip install -e ".[dev,web]"
```

## 4. Локальная конфигурация

```powershell
Copy-Item config\instruments.local.yaml.example config\instruments.local.yaml
Copy-Item config\notifications.local.yaml.example config\notifications.local.yaml
Copy-Item config\channel_descriptors.local.yaml.example config\channel_descriptors.local.yaml
```

Заполните адреса приборов в `config/instruments.local.yaml` и токен
Telegram-бота в `config/notifications.local.yaml`. Descriptor local-файл —
обязательная парная authority при выбранном `instruments.local.yaml` и полная
замена base manifest, не частичный merge. Если используется base
`instruments.yaml`, engine выбирает base descriptor manifest независимо от
наличия local descriptor-файла. Сверьте физический roster и свяжите каждый
`(instrument_id, emitted_channel)` ровно с одним стабильным `channel_id`.
Ошибка или неполный roster блокирует startup; descriptor задаёт идентичность,
но не выдаёт capability или source authority.

## 5. Bootstrap модели предиктора охлаждения

Текущий tracked helper требует POSIX-compatible `make` и shell:

```bash
make bootstrap-predictor
```

Это **не** поддерживаемая команда развёртывания на Windows. Пока отдельный
кроссплатформенный helper не поставлен, Windows launcher честно показывает
предиктор как недоступный; этот packaging gap нельзя закрывать ручным
копированием, не зафиксированным в процедуре развёртывания.

## 6. Проверка без приборов (mock mode)

```bash
cryodaq-engine --mock
```

В другом терминале:

```bash
cryodaq-gui
```

## 7. Реальные приборы — только после допуска

Не запускайте candidate на реальном стенде, пока descriptor roster не сверен и
не выполнены применимые гейты из `docs/lab_verification_checklist.md`.

```bash
cryodaq-engine
cryodaq-gui
```

Для полного операторского runtime используйте lifecycle-owning launcher: его
процесс содержит Qt GUI и наблюдает отдельные engine/bridge/optional
assistant. Bounded report children принадлежат engine или assistant, который
их запросил. Прямой `cryodaq-engine` + `cryodaq-gui` выше — сокращённый
диагностический путь без launcher-owned assistant/periodic delivery; on-demand
engine reporting остаётся доступным:

```bash
cryodaq
```

## 8. Первое измерение

1. Дождитесь `Engine: работает` в верхней вахтенной панели.
2. Откройте `Приборы` (Ctrl+D) — каждый прибор online, каждый датчик
   здоров. Полная проверка реального железа (SQLite-гейт, TSP watchdog,
   frozen-сборка и т.д.) — отдельный протокол:
   **`docs/lab_verification_checklist.md`**.
3. `Новый эксперимент` в ToolRail → выберите шаблон → заполните карточку.
4. Наблюдайте `Дашборд` и `Тревоги` во время прогона.
5. По завершении: оверлей `Эксперимент` → `Завершить эксперимент`, затем
   проверьте запись в `Архив` (Ctrl+R, «Ещё» → «Архив»).

Что-то пошло не так на любом из шагов — см. `docs/troubleshooting.md`.

## 9. Прочие CLI

Не нужны для первого измерения, но существуют в комплекте:

```bash
cryodaq-cooldown build --help    # параметры обучения cooldown ML
cryodaq-cooldown predict --help  # параметры прогноза ETA
cryodaq-trends scan --help       # параметры межэкспериментной feature-таблицы
cryodaq-trends drift --help      # параметры drift-проверки
cryodaq-replay-curve             # трансформация кривых для replay
cryodaq-rag-index                # построение индекса базы знаний (RAG)
cryodaq-rag-search               # семантический поиск по базе знаний
cryodaq-assistant                # standalone-процесс локального LLM-ассистента + RAG (B1),
                                  # подключается к работающему engine по ZMQ
cryodaq-report-render            # внутренний одноразовый renderer отчёта; запускается engine
```

`cryodaq-frozen`, `cryodaq-frozen-engine`, `cryodaq-frozen-gui`,
`cryodaq-frozen-assistant`, `cryodaq-frozen-report-render` — точки входа для
frozen-сборки (PyInstaller),
не для ручного запуска из venv; см. `build_scripts/build.sh` /
`build_scripts/build.bat`.
