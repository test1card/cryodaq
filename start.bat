@echo off
title CryoDAQ
cd /d "%~dp0"
echo ============================
echo   CryoDAQ — запуск системы
echo ============================
echo.
echo Запуск engine + GUI...
pythonw -m cryodaq.launcher
