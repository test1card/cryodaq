# Первый деплой CryoDAQ на лабораторном компьютере

Версия документа: 0.13.0, март 2026

## Требования

- Windows 10/11
- Python >= 3.12
- Git
- NI-VISA или PyVISA-py backend
- COM/GPIB драйверы для приборов
- Рекомендуется: LibreOffice (для PDF генерации отчётов)

## Установка

1. Клонировать репозиторий:
   ```
   git clone https://github.com/test1card/cryodaq.git
   cd cryodaq
   ```

2. Установить пакет:
   ```
   pip install -e .
   ```

3. Проверить запуск в mock-режиме:
   ```
   cryodaq --mock
   ```
   Убедиться: окно открывается, 10 вкладок, данные mock идут.

## Конфигурация приборов

1. Скопировать шаблон:
   ```
   copy config\instruments.local.yaml.example config\instruments.local.yaml
   ```

2. Отредактировать `instruments.local.yaml`:
   - LakeShore 218S: указать GPIB адрес (например `GPIB0::12::INSTR`)
   - Keithley 2604B: указать GPIB адрес
   - Thyracont VSP63D: указать COM порт и baudrate

3. Проверить VISA backend:
   ```
   python -c "import pyvisa; rm = pyvisa.ResourceManager(); print(rm.list_resources())"
   ```

## Конфигурация каналов

Проверить `config/channels.yaml` — имена каналов должны соответствовать реальной конфигурации стенда.

## Конфигурация смен (опционально)

Отредактировать `config/shifts.yaml`:
- `operators` — список операторов
- `periodic_interval_hours` — интервал периодических проверок (по умолчанию 2 ч)

## Первый запуск

1. Запустить без mock:
   ```
   cryodaq
   ```

2. Проверить:
   - Engine подключился к приборам (зелёный индикатор в верхней панели)
   - Карточки температур показывают реальные значения
   - Графики температуры и давления обновляются
   - Keithley в состоянии ВЫКЛ

3. Тестовый эксперимент:
   - Вкладка «Эксперимент» → выбрать шаблон → заполнить поля → Создать
   - Подождать 5 минут
   - Завершить эксперимент
   - Проверить: архивная запись появилась, отчёт сгенерирован

4. Тестовая калибровка (если есть эталонный датчик):
   - Вкладка «Калибровка» → выбрать опорный канал → отметить целевые → «Начать калибровочный прогон»
   - Дождаться набора данных
   - Завершить эксперимент
   - Проверить: fit запускается, метрики отображаются

## Ярлык на рабочем столе

```
python create_shortcut.py
```

## Горячие клавиши

| Комбинация | Действие |
|------------|----------|
| Ctrl+1..9/0 | Переключение вкладок |
| Ctrl+L | Фокус на быстрый журнал |
| Ctrl+E | Вкладка «Эксперимент» |
| Ctrl+Shift+X | Аварийное отключение Keithley |
| F5 | Обновление |

## Настройка instruments.local.yaml

### Обнаружение VISA-ресурсов

```
python -c "import pyvisa; rm = pyvisa.ResourceManager(); print(rm.list_resources())"
```

Типичный вывод:
```
('GPIB0::11::INSTR', 'GPIB0::12::INSTR', 'GPIB0::13::INSTR', 'USB0::0x05E6::0x2604::04052028::INSTR', 'ASRL3::INSTR')
```

### Проверка каждого прибора

**LakeShore 218S:**
```python
import pyvisa
rm = pyvisa.ResourceManager()
ls = rm.open_resource("GPIB0::12::INSTR")
print(ls.query("*IDN?"))  # Ожидается: LSCI,MODEL218S,...
print(ls.query("KRDG? 0"))  # Все 8 каналов температуры
ls.close()
```

**Keithley 2604B:**
```python
k = rm.open_resource("USB0::0x05E6::0x2604::04052028::INSTR")
print(k.query("*IDN?"))  # Ожидается: Keithley Instruments Inc., Model 2604B,...
k.close()
```

**Thyracont VSM77DL (Protocol V1, 115200 бод):**
```python
import serial
s = serial.Serial("COM3", 115200, timeout=2)
s.write(b"001M^\r")
print(s.readline())  # Ожидается: b'001M100023D\r' (или аналогичное)
s.close()
```

### Пример instruments.local.yaml для АКЦ ФИАН

```yaml
instruments:
  - type: lakeshore_218s
    name: "LS218_1"
    resource: "GPIB0::12::INSTR"
    poll_interval_s: 0.5

  - type: lakeshore_218s
    name: "LS218_2"
    resource: "GPIB0::11::INSTR"
    poll_interval_s: 0.5

  - type: lakeshore_218s
    name: "LS218_3"
    resource: "GPIB0::13::INSTR"
    poll_interval_s: 0.5

  - type: keithley_2604b
    name: "Keithley_1"
    resource: "USB0::0x05E6::0x2604::04052028::INSTR"
    poll_interval_s: 1.0

  - type: thyracont_vsp63d
    name: "VSP63D_1"
    resource: "COM3"
    baudrate: 115200
    address: "001"
    poll_interval_s: 2.0
```

### Типичные проблемы настройки приборов

- **GPIB bus contention:** Три LakeShore на одной шине GPIB0 — CryoDAQ сериализует доступ через bus lock, но убедитесь что GPIB адреса не конфликтуют.
- **COM port baudrate:** Thyracont VSP63D использует 9600 бод, VSM77DL — 115200 бод. Неверный baudrate → таймаут или мусор.
- **NI-VISA не установлен:** `pyvisa.ResourceManager()` выбросит ошибку. Установите NI-VISA с ni.com или используйте `pyvisa-py` backend: `pip install pyvisa-py`.
- **USB VISA resource string:** Keithley resource string зависит от серийного номера. Используйте `list_resources()` для получения точной строки.

## Типичные проблемы

### «Engine уже запущен» при повторном запуске

```
taskkill /F /IM pythonw.exe
```
Подождать 3 секунды, запустить снова.

### Приборы не обнаружены

- Проверить физическое подключение
- Проверить NI-VISA / драйверы
- `pyvisa.ResourceManager().list_resources()`
- Убедиться что resource string в `instruments.local.yaml` совпадает

### PDF отчёт не генерируется

- Установить LibreOffice
- Убедиться что `soffice` доступен в PATH
- DOCX отчёт генерируется всегда — PDF опционален

## После успешного первого запуска

- Создать backup `config/instruments.local.yaml`
- Настроить Telegram notifications (`config/notifications.local.yaml`) если нужно
- Провести первый реальный прогон с полным циклом
