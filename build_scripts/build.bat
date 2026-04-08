@echo off
cd /d "%~dp0\.."
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller build_scripts\cryodaq.spec --clean --noconfirm
if errorlevel 1 exit /b 1
python build_scripts\post_build.py
echo.
echo Build complete: dist\CryoDAQ\
