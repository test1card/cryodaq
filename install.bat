@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 exit /b 1

REM Keep this command layer ASCII-only: stock cmd.exe does not reliably parse
REM UTF-8 Cyrillic batch text. Russian operator guidance lives in quickstart.
echo.
echo CryoDAQ installation
echo.

python --version
if errorlevel 1 goto :python_missing
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 goto :python_old
python -c "import sqlite3; v=tuple(sqlite3.sqlite_version_info); print('SQLite:', sqlite3.sqlite_version); raise SystemExit(0 if v in ((3,44,6),(3,50,7)) or v >= (3,51,3) else 1)"
if errorlevel 1 goto :sqlite_unsafe
if not exist requirements-lock.txt goto :lock_missing

echo Installing the version-pinned dependency set...
python -m pip install -r requirements-lock.txt
if errorlevel 1 goto :dependency_failed
python -m pip install -e . --no-deps --no-build-isolation
if errorlevel 1 goto :project_failed
python -m pip check
if errorlevel 1 goto :dependency_check_failed
python create_shortcut.py
if errorlevel 1 goto :shortcut_failed

echo.
echo Installation complete. See docs\quickstart.md for Russian setup guidance.
echo For a no-instrument check: cryodaq-engine --mock
echo.
pause
exit /b 0

:python_missing
echo ERROR: Python was not found. Install Python 3.12 or newer.
goto :failed
:python_old
echo ERROR: Python 3.12 or newer is required.
goto :failed
:sqlite_unsafe
echo ERROR: this Python uses an unsafe SQLite build. See docs\deployment.md.
goto :failed
:lock_missing
echo ERROR: requirements-lock.txt is missing beside install.bat.
goto :failed
:dependency_failed
echo ERROR: the pinned dependency installation failed.
goto :failed
:project_failed
echo ERROR: the no-isolation editable project installation failed.
goto :failed
:dependency_check_failed
echo ERROR: python -m pip check reported an incompatible environment.
goto :failed
:shortcut_failed
echo ERROR: the CryoDAQ desktop shortcut could not be created.
:failed
echo Installation did not complete. See docs\deployment.md.
pause
exit /b 1
