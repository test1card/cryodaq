@echo off
chcp 65001 >nul 2>&1
echo.
echo  ╔═══════════════════════════════════════════════╗
echo  ║   Установка CryoDAQ — АКЦ ФИАН              ║
echo  ╚═══════════════════════════════════════════════╝
echo.

REM Проверка Python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  ОШИБКА: Python не найден.
    echo  Установите Python 3.12+ с https://python.org
    echo  При установке отметьте "Add Python to PATH".
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  Python: %PYVER%

REM Проверка версии >= 3.12
python -c "import sys; exit(0 if sys.version_info >= (3, 12) else 1)" 2>nul
if %ERRORLEVEL% neq 0 (
    echo  ОШИБКА: Требуется Python 3.12 или новее. Установлен: %PYVER%
    pause
    exit /b 1
)

echo  Устанавливаю зависимости...
pip install -e ".[dev,web,archive]" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  ОШИБКА: pip install завершился с ошибкой.
    echo  Попробуйте: pip install -e ".[dev,web,archive]"
    pause
    exit /b 1
)
echo  Зависимости установлены.
echo.

REM Создание ярлыка на рабочем столе
echo  Создаю ярлык на рабочем столе...
python create_shortcut.py
echo.

REM Подсказка о локальной конфигурации
echo  ═══════════════════════════════════════════════
echo.
echo  Установка завершена!
echo.
echo  Следующие шаги:
echo    1. Скопируйте config\instruments.local.yaml.example
echo       в config\instruments.local.yaml
echo       и укажите адреса ваших приборов.
echo.
echo    2. Скопируйте config\notifications.local.yaml.example
echo       в config\notifications.local.yaml
echo       и укажите токен Telegram-бота.
echo.
echo    3. Дважды кликните по ярлыку CryoDAQ на рабочем столе.
echo.
echo  Для тестирования без приборов:
echo    cryodaq-engine --mock
echo.
pause
