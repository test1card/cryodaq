@echo off
cd /d "%~dp0\.."

REM Install the tracked version-pinned Python dependency set first.
if exist requirements-lock.txt (
    echo Installing from requirements-lock.txt ...
    pip install -r requirements-lock.txt
    if errorlevel 1 exit /b 1
    pip install -e . --no-deps
    if errorlevel 1 exit /b 1
    pip check
    if errorlevel 1 exit /b 1
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller build_scripts\cryodaq.spec --clean --noconfirm
if errorlevel 1 exit /b 1
python build_scripts\post_build.py
echo.
echo Build complete: dist\CryoDAQ\
