@echo off
cd /d "%~dp0\.."

REM Phase 2c M.1: install from lockfile first for reproducible builds.
if exist requirements-lock.txt (
    echo Installing from requirements-lock.txt ...
    pip install --require-hashes -r requirements-lock.txt 2>nul
    if errorlevel 1 pip install -r requirements-lock.txt
    pip install -e . --no-deps
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller build_scripts\cryodaq.spec --clean --noconfirm
if errorlevel 1 exit /b 1
python build_scripts\post_build.py
echo.
echo Build complete: dist\CryoDAQ\
