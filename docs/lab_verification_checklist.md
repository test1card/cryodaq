# Чек-лист лабораторной верификации CryoDAQ

Turnkey-процедуры для обязательной software prequalification и последующих
проверок, которые **невозможно** выполнить без физического доступа к приборам
и лабораторным ПК (Ubuntu-движок, Windows-операторская станция, криостат
Millimetron / АКЦ ФИАН). Каждый раздел: цель → команды → ожидаемый результат →
что записать обратно в репозиторий при успехе.

Общее правило: любую проверку с источником мощности вести на **безопасном
низком уровне** и на **макетной (dummy) нагрузке**, а не на нагревателе
криостата.

---

## Software qualification перед лабораторией: exact-SHA WSL short soak

Эта проверка не требует приборов, но обязательна перед переносом кандидата в
лабораторию. Qualification выполняется в отдельном WSL-клоне на нативной
Linux-файловой системе (`ext4`), а не в `/mnt/c` (`drvfs`/`9p`). На `drvfs`
разрешены быстрые developer-проверки (lint, docs и focused tests), но они не
сертифицируют POSIX filesystem/process semantics и не заменяют этот гейт.
Native-ext4 проверка доказывает lifecycle,
process ownership, restart, persistence и локальную доставку периодического PNG
для изолированного пассивного mock-стека. Она **не** проверяет production-набор
alarm/interlock/physical-alarm правил и не закрывает hardware-гейты ниже.

**Граница fixture.** Ровно один `LS218_1` с passive-measurement authority,
mock transport/driver, 16 canonical descriptors, 16 bindings и 8 readings за
опрос. Production alarms, interlocks и physical alarms намеренно отключены.
Полная топология и SHA-256 каждого сгенерированного config-файла записываются в
manifest и повторно проверяются после остановки процессов.

**Подготовка на Windows.** Зафиксировать полный SHA кандидата и создать новый
клон внутри выбранного WSL-дистрибутива:

```powershell
$sha = (git rev-parse HEAD).Trim()
$distro = "<WSL_DISTRO_NAME>"
$source = (wsl -d $distro -- wslpath -a (Resolve-Path .).Path).Trim()
$dest = "/home/<WSL_USER>/cryodaq-final-$sha"
wsl -d $distro -- bash -lc "git clone --no-local --no-checkout '$source' '$dest' && git -C '$dest' -c core.autocrlf=false checkout --detach '$sha'"
```

**Проверка среды внутри WSL.** Пути и имя дистрибутива адаптировать к машине,
но не менять выбранный SHA или lock-файл:

```bash
set -euo pipefail
repo=/home/<WSL_USER>/cryodaq-final-<FULL40>
cd "$repo"
test "$(git rev-parse HEAD)" = "<FULL40>"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
findmnt -no FSTYPE -T "$repo" | grep -E '^ext4$'

# Подключить заранее проверенный dedicated runtime, не копируя site-packages
# в tracked tree. .venv остаётся ignored и должен ссылаться только на него.
mkdir .venv
ln -s /root/cryodaq-soak-py313/bin .venv/bin
ln -s /root/cryodaq-soak-py313/lib .venv/lib
ln -s /root/cryodaq-soak-py313/pyvenv.cfg .venv/pyvenv.cfg

.venv/bin/python --version
.venv/bin/python -c "import sqlite3,sys; print(sys.executable); print(sqlite3.sqlite_version)"
.venv/bin/python -c "import psutil; assert psutil.__version__ == '7.2.2'"
.venv/bin/python -m pip check
.venv/bin/python scripts/check_lock_drift.py
.venv/bin/python -m pip install --dry-run --no-index --no-deps \
  -r requirements-lock.txt
test -z "$(git status --porcelain=v1 --untracked-files=all)"
```

Перед запуском сохранить вне evidence-каталога: `/etc/os-release`, `uname -a`,
`findmnt`, `pwd`, полный SHA, `sys.executable`, `sys.prefix`, Python, выбранную
SQLite, psutil, `pip freeze`, SHA-256 интерпретатора и точную команду. Этот
companion record нельзя добавлять внутрь уже sealed evidence topology.

Минимальная воспроизводимая фиксация неизменности runtime до и после soak:

```bash
companion=/root/cryodaq-soak-companion-<FULL40>
mkdir -m 700 "$companion"
cp /etc/os-release "$companion/os-release"
uname -a > "$companion/uname.txt"
findmnt -T "$repo" > "$companion/findmnt.txt"
printf '%s\n' "$repo" "$(git rev-parse HEAD)" > "$companion/source.txt"
.venv/bin/python -c "import sqlite3,sys; print(sys.executable); print(sys.prefix); print(sys.version); print(sqlite3.sqlite_version)" \
  > "$companion/runtime-before.txt"
.venv/bin/python -c "import psutil; print(psutil.__version__)" \
  >> "$companion/runtime-before.txt"
.venv/bin/python -m pip freeze --all > "$companion/pip-freeze-before.txt"
sha256sum "$(readlink -f .venv/bin/python)" > "$companion/interpreter-before.sha256"
```

**Запуск.** Evidence directory должен быть новым и пустым:

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m scripts.soak_mock_stack \
  --profile short \
  --evidence-dir "artifacts/mock-stack-soak/final-<FULL40>"

.venv/bin/python -m pip freeze --all > "$companion/pip-freeze-after.txt"
cmp "$companion/pip-freeze-before.txt" "$companion/pip-freeze-after.txt"
sha256sum "$(readlink -f .venv/bin/python)" > "$companion/interpreter-after.sha256"
cmp "$companion/interpreter-before.sha256" "$companion/interpreter-after.sha256"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
```

**Критерии PASS.** Код возврата 0; `summary.json` имеет `status=PASS` и
`state=PASS`; manifest указывает exact clean SHA и sealed passive fixture;
exact-six содержит ровно 6 passed без skip/deselect; присутствуют и согласованы
`samples.jsonl`, `faults.jsonl`, `shutdown.json`, `log_capture.json`,
`periodic-delivery-result.json`, ровно две canonical receipt-записи и два
content-addressed PNG. Первый receipt относится к latest completed slot,
выделенному при старте; второй — к единственной следующей динамически выровненной
границе после замены assistant. Ledger/manifest/artifact hashes пересчитываются,
после запуска Git tree остаётся чистым, Python/runtime hash и `pip freeze` не
изменились, живых или zombie descendants нет.

**Записать при успехе.** Полный SHA, дистрибутив/kernel, filesystem, Python,
SQLite, psutil, команды, длительность, список шести реально выполненных exact-six
node IDs и отсутствие skip/deselect в их pytest-выводе, SHA-256 companion record,
summary, ledger и evidence tree. Сам `exact_six` — артефакт со списком узлов и
хешами вывода, а не источник выдуманного числового поля `passed`. Не переносить
результат на более новый commit.

---

## 1. Гейт версии SQLite на лабораторном Ubuntu ПК

**Цель.** Убедиться, что интерпретатор, которым запускается `cryodaq-engine`,
слинкован с безопасной версией SQLite. `SQLiteWriter._check_sqlite_version`
(`src/cryodaq/storage/sqlite_writer.py`) жёстко падает на диапазоне повреждения
WAL-reset **`[3.7.0, 3.51.3)`** (март-2026).

**Команды.**

```bash
# Создать/обновить поддерживаемый runtime с фиксированным безопасным SQLite:
conda env update --file environment.yml --prune
conda activate cryodaq

# Авторитетная проверка — реализация sqlite3, реально используемая движком:
python -c "from cryodaq.storage._sqlite import sqlite_version_info; print(sqlite_version_info())"

# Дополнительная диагностика — сырой stdlib sqlite3 (до возможного fallback):
python -c "import sqlite3; print(sqlite3.sqlite_version)"

# CLI-версия как ещё один ориентир:
sqlite3 --version
```

**Ожидаемый результат.**

- Безопасно: выбранная реализация сообщает `≥ 3.51.3` **или**
  backport-safe `3.44.6` / `3.50.7`.
- В диапазоне `[3.7.0, 3.51.3)` запуск **запрещён**: обновить tracked Conda
  environment и повторить проверку. Небезопасный runtime нельзя выдавать за
  пройденный software gate.

**Если версия плохая.** Пересоздать runtime строго из `environment.yml` и
проверить, что активирован именно `cryodaq`. Опциональный сторонний fallback
допустим только если выбранная им версия сама проходит F25; по умолчанию такой
пакет не устанавливается.
`CRYODAQ_ALLOW_BROKEN_SQLITE=1` — только крайняя мера-подтверждение
(осознанный обход), **не** исправление.

**Записать при успехе.** Зафиксировать версию Python и SQLite лабораторного
ПК в `docs/deployment.md` (раздел развёртывания на операторском ПК).

---

## 2. Верификация фикса H5 / ZMQ idle-death (v0.39.0) на лабораторном ПК

**Цель.** Подтвердить, что закрыт баг B1 (ZMQ idle-death). Корневая
причина (см. CHANGELOG `[0.39.0]`):
`asyncio.wait_for(socket.recv(), timeout=1.0)` отменял pyzmq-корутину каждую
секунду; после ~50 отмен реактор libzmq заклинивал REP-сокет навсегда.
Фикс `1f88d2e`: `poll(timeout=1000)` + условный `recv()` после `POLLIN`.

**Команды.**

```bash
cryodaq-engine            # терминал 1: движок (реальные приборы)
cryodaq-gui               # терминал 2: GUI поверх ZMQ

# Регрессионный гейт (доказал причинность на стороне движка):
python tools/diag_zmq_direct_req.py     # чистые 180 с = pass
```

**Ожидаемый результат.** Оставить связку в простое существенно дольше минуты,
затем подать команды из GUI (статус / старт / стоп). Команды проходят,
REP-сокет не завис. `diag_zmq_direct_req.py` — 180 с без зависаний.
Подтверждено на Ubuntu lab PC в релизе, требуется повторить на текущем ПК.

**Записать при успехе.** Отметку о прохождении на лабораторном ПК добавить
в `CHANGELOG.md` рядом с релизным/ручным гейтом, если такой гейт ещё открыт.

---

## 3. Верификация runtime-калибровки LakeShore на реальном железе

**Цель.** Проверить per-channel политику чтения KRDG/SRDG + кривая и
консервативный откат на KRDG против реального термометра LakeShore 218S
(`src/cryodaq/drivers/instruments/lakeshore_218s.py`,
`src/cryodaq/analytics/calibration.py`).

**Что проверить на железе.**

- `KRDG?` и `SRDG?` без аргумента возвращают 8 значений; при сбое пакетного
  запроса драйвер уходит в per-channel режим (`KRDG? 1..8`) и восстанавливается.
- Runtime-политика с `reading_mode: curve` применяет кривую к сырому SRDG
  по каждому каналу отдельно.
- **Консервативный откат (CHANGELOG `b38c360`).** SRDG за пределами диапазона
  калибровки не «замораживается» на границе c `status=OK` (что обнуляло dT/dt и
  слепило rate-защиту) — публикуется нативный KRDG. Проверить, что при выходе
  за диапазон `dT/dt` остаётся живым.

**Ожидаемый результат.** Температуры по всем 8 каналам правдоподобны; при
выводе датчика за диапазон калибровки показание переключается на KRDG, а не
залипает на границе.

**Записать при успехе.** Результат прогона (каналы, поведение отката) занести
в `docs/instruments.md` (раздел LakeShore).

---

## 4. Keithley: отдельные гейты A8a–A8e

**Safety boundary.** Все тесты с подачей выполнять только на dummy-нагрузке,
с безопасными пассивно обоснованными V/I и физической кнопкой отключения.
Никогда не начинать с нагревателя криостата. Внутренний status/readback SMU —
диагностика, а не независимый oracle отсутствия энергии.

Текущий `tsp/cryodaq_wdog.lua` v3 намеренно неавтономен. Он проверяет дедлайн
только когда приходит следующий `pet`; поэтому покрывает stall-then-recover,
но не полную смерть хоста. Удалённый прежний timer-код был документированно
некорректным, а не просто непроверенным. `required` должен отказать с v3,
поскольку `cryodaq_wdog_autonomous == 0`; для A8a/A8b использовать
`best_effort` и ожидать один CRITICAL о деградации.

`timeout_s` должен быть конечным числом в диапазоне 1–300 s и не меньше двух
интервалов опроса. TSP `os.time()` имеет секундную гранулярность, а условие
строго `elapsed > timeout`; при точном равенстве trip наступит не раньше
следующей целой секунды. Учитывать это в критерии A8b/A8d и записывать
фактический измеренный trip time, а не вычисленный номинал.

### A8-0 — грамматика nonce-bound OFF на реальном 2604B (НЕ ПРОЙДЕНО)

До переноса software proof в лабораторный claim нужно на реальном Keithley
2604B, его фактической firmware и штатном Windows USBTMC/VISA path подтвердить,
что прибор принимает ровно однострочную ASCII-команду вида

```text
print(string.format("CRYODAQ_OFF_V1|<nonce>|%g", smuX.source.output))
```

для `smua` и `smub`, где `<nonce>` — свежие 32 lowercase hexadecimal symbols,
и возвращает ровно одну строку

```text
CRYODAQ_OFF_V1|<тот-же-32-lowercase-hex-nonce>|0
```

без префикса, суффикса, дополнительной строки, Unicode-подстановки или иной
числовой формы. Проверку выполнять только при уже подтверждённом OFF и без
подачи мощности. Сохранить сырые TX/RX bytes, модель/serial/firmware/VISA
backend, оба канала, commit SHA и UTC timestamp. Любое отличие означает FAIL:
software должен остаться fail-closed, а протокол — быть исправлен и заново
проверен. До этого evidence нельзя заявлять restart-durable или физически
подтверждённый OFF только на основании mock/unit/Windows CI.

### A8a — заливка, версия и честный контракт (автоматизировано)

Проверяет version stamp v3, `autonomous == 0`, software-active/tripped state и
командный verified-OFF. Это не физический host-death тест.

```bash
CRYODAQ_KEITHLEY_RESOURCE="USB0::0x05E6::0x2604::04052028::INSTR" \
  .venv/bin/pytest -m smoke tests/drivers/test_keithley_watchdog_smoke.py
```

### A8b — late-pet stall recovery (автоматизировано с подачей)

Скрипт подаёт безопасный низкий уровень, ждёт дольше `timeout_s`, затем
посылает поздний pet. Только этот более поздний command выполняет проверку и
переводит оба выхода в OFF, поднимая latch.

```bash
CRYODAQ_KEITHLEY_RESOURCE="USB0::0x05E6::0x2604::04052028::INSTR" \
  CRYODAQ_SMOKE_ALLOW_SOURCE=1 \
  .venv/bin/pytest -m smoke tests/drivers/test_keithley_watchdog_smoke.py
```

### A8c — настоящая смерть хоста без последующей команды (НЕ ПРОЙДЕНО)

1. Запустить отдельный операторский host process и подать безопасный уровень.
2. Записать точный PID, monotonic start и watchdog timeout.
3. Убить host/engine так, чтобы после kill ни один процесс CryoDAQ не отправил
   Keithley следующую команду; launcher auto-restart тоже отключить.
4. Не подключаться повторно до окончания окна измерения.

Pass допускается только если выход отключился в допустимое физически выведенное
время без более поздней команды. Текущая v3 ожидаемо этот тест не проходит;
результат нельзя подменять A8b или force-OFF при reconnect.

### A8d — независимый terminal V/I/P и trip time (НЕ ПРОЙДЕНО)

Параллельно A8c независимые DMM/осциллограф/шунт регистрируют напряжение,
ток, мощность и время отключения на клеммах. Записать приборы, серийные номера,
калибровку/uncertainty, sample rate, нагрузку, wiring и сырые traces. Проверить
не только `source.output`, но и реальную остаточную энергию. `SOURCE_IDLE` —
возврат к idle level, не открытие реле и не доказательство OFF.

5 W — только host-side target cap. После смерти хоста instrument compliance
ограничивает рабочую точку применимым envelope `limitv`, `limiti`, нагрузки и
самого прибора (в текущей конфигурации до 40 V и 1 A), но не гарантирует ≤5 W
и не ограничивает накопленную энергию при длительной подаче.

### A8e — независимый interlock/cutout и common-cause (НЕ ПРОЙДЕНО)

Предпочтительная архитектура — внешний защёлкивающийся de-energize-to-trip
cutout, не зависящий от host scheduler, USB, TSP, SMU output stage, GUI, БД и
сети. Reference manual категоричен: output-enable/digital-I/O facility
2601B/2602B/2604B **не подходит для safety circuits и не должна использоваться
для управления safety interlock**. Нужна отдельная схема, соответствующая
требованиям применения. Документировать питание, разрывную
способность, normally-safe state, welded-contact detection, reset policy,
shared power/wiring/environment failures и end-to-end proof test. Внутренний
SMU timer prototype разрешён только как документированная bench-гипотеза, не
как независимый финальный элемент.

### Срок действия доказательств

Повторить A8a–A8e и считать прежний PASS недействительным после изменения
firmware, TSP-скрипта/version, driver protocol, wiring, нагрузки, interlock,
compliance/offmode, измерительного oracle или power topology. Для каждого PASS
сохранить commit SHA, версии firmware/script, wiring photo/schematic, конфиг,
сырые traces, оператора/свидетеля, UTC+monotonic timestamps и критерий pass/fail.

До прохождения A8c–A8e Phase C остаётся заблокированной.

---

## 5. Smoke source-установки и ярлыка на Windows

**Цель.** Проверить установку и запуск на операторской Windows-станции
(`install.bat`, `create_shortcut.py`).

**Команды / действия.**

```bat
install.bat
```

`install.bat` проверяет Python ≥ 3.12, выполняет
`python -m pip install -r requirements-lock.txt`, затем
`python -m pip install -e . --no-deps --no-build-isolation` и вызывает
`create_shortcut.py`,
который создаёт на рабочем столе ярлык `CryoDAQ.lnk`, запускающий
`pythonw -m cryodaq.launcher` без окна терминала.
Batch-файл использует ASCII-only диагностические сообщения для штатного
`cmd.exe`; русские инструкции оператора находятся в `docs/quickstart.md`.

**Что кликнуть и что ожидать.**

- Установщик доходит до «Установка завершена!» без ошибок.
- На рабочем столе появился ярлык **CryoDAQ**.
- Двойной клик по ярлыку запускает лаунчер (без консольного окна).
- Проверка без приборов: `cryodaq-engine --mock`.

**Граница доказательства.** Этот editable source-install smoke проверяет только
`install.bat`, ярлык и source launcher. Он **не** является ONEDIR/frozen-build
доказательством и не снимает frozen gate.

**Записать при успехе.** Зафиксировать source-install/shortcut smoke отдельно и,
если менялись шаги, обновить `docs/deployment.md`.

---

## 6. Настоящий Windows ONEDIR/frozen smoke (НЕ ПРОЙДЕНО)

**Цель.** Проверить точный собранный ONEDIR-артефакт на операторской
Windows-станции без authority от source tree или ambient Python.

**Обязательные условия.** Записать commit SHA и digest артефакта; запустить
packaged launcher при недоступном source tree; подтвердить packaged allowlist
драйверов, mock POD/bridge startup, engine/bridge restart, отложенный выбор темы
без остановки process tree и bounded shutdown без оставшихся дочерних
процессов/потоков/IPC-очередей, с удержанием launcher lock до возврата Qt loop;
сохранить логи и скриншоты. Любая зависимость от editable checkout, ambient
`.venv`/Python или отсутствующий allowlisted driver означает FAIL.

**Записать при успехе.** Только этот отдельный прогон может снять ручной
Windows ONEDIR/frozen gate. Он не закрывает dummy-load, independent-final-element
или другие physical gates.
