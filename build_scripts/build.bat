@echo off
cd /d "%~dp0\.."
if errorlevel 1 exit /b 1

REM Install the tracked version-pinned Python dependency set first.
if not exist requirements-lock.txt (
    echo ERROR: requirements-lock.txt is required for a supported build.
    exit /b 1
)
echo Installing from requirements-lock.txt ...
python -m pip install -r requirements-lock.txt
if errorlevel 1 exit /b 1
python -m pip install -e . --no-deps --no-build-isolation
if errorlevel 1 exit /b 1
python -m pip check
if errorlevel 1 exit /b 1

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller build_scripts\cryodaq.spec --clean --noconfirm
if errorlevel 1 exit /b 1
python build_scripts\post_build.py
if errorlevel 1 exit /b 1
echo.
echo Build complete: dist\CryoDAQ\
