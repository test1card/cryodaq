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
install.bat
```

Делает: проверяет Python 3.12+, запускает
`python -m pip install -r requirements-lock.txt`, затем
`python -m pip install -e . --no-deps --no-build-isolation` и создаёт ярлык
`CryoDAQ` на рабочем столе. Командный слой batch-файла намеренно ASCII-only для
надёжного запуска в штатном `cmd.exe`; русские инструкции находятся здесь.

Ручная установка (Windows/Linux, dev-окружение):

```bash
pip install -e ".[dev,web]"
```

## 4. Локальная конфигурация

```powershell
Copy-Item config\instruments.local.yaml.example config\instruments.local.yaml
Copy-Item config\notifications.local.yaml.example config\notifications.local.yaml
```

Заполните адреса приборов в `config/instruments.local.yaml` и токен
Telegram-бота в `config/notifications.local.yaml`.

## 5. Bootstrap модели предиктора охлаждения (один раз на новой машине)

```bash
make bootstrap-predictor
```

## 6. Проверка без приборов (mock mode)

```bash
cryodaq-engine --mock
```

В другом терминале:

```bash
cryodaq-gui
```

## 7. Запуск с реальными приборами

```bash
cryodaq-engine
cryodaq-gui
```

Либо одной командой (операторский launcher, engine + GUI в одном процессе):

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
cryodaq-cooldown build/predict   # cooldown ML: обучение и прогноз ETA
cryodaq-trends scan/drift        # межэкспериментные тренды: feature-таблица / drift-проверка
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
