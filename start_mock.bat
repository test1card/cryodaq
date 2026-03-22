@echo off
title CryoDAQ [MOCK]
cd /d "%~dp0"
echo ================================
echo   CryoDAQ — режим эмуляции
echo ================================
echo.
set CRYODAQ_MOCK=1
echo Запуск engine (mock) + GUI...
python -m cryodaq.launcher
pause
