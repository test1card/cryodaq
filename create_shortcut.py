"""Создать ярлык CryoDAQ на рабочем столе (Windows).

Запуск: python create_shortcut.py

Создаёт ярлык CryoDAQ.lnk, который запускает pythonw -m cryodaq.launcher
без окна терминала. Оператору достаточно дважды кликнуть по ярлыку.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _ps_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _get_desktop_path() -> Path:
    """Получить путь к рабочему столу (корректно для OneDrive, русской локали и т.д.)."""
    if sys.platform != "win32":
        return Path.home() / "Desktop"

    # PowerShell возвращает правильный путь во всех случаях
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())

    # Fallback
    return Path.home() / "Desktop"


def _get_pythonw() -> Path:
    """Получить путь к pythonw.exe (или python.exe как fallback)."""
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    return pythonw if pythonw.exists() else Path(sys.executable)


def create_shortcut() -> int:
    """Создать ярлык на рабочем столе Windows."""
    if sys.platform != "win32":
        print("Этот скрипт предназначен только для Windows.")
        print("На Linux/macOS используйте: python -m cryodaq.launcher")
        return 0

    desktop = _get_desktop_path()
    shortcut_path = desktop / "CryoDAQ.lnk"
    pythonw = _get_pythonw()
    project_root = Path(__file__).resolve().parent

    ps_script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut({_ps_literal(shortcut_path)}); "
        f"$s.TargetPath = {_ps_literal(pythonw)}; "
        "$s.Arguments = '-m cryodaq.launcher'; "
        f"$s.WorkingDirectory = {_ps_literal(project_root)}; "
        "$s.Description = 'CryoDAQ'; "
        "$s.Save()"
    )

    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        print(f"Ярлык создан: {shortcut_path}")
        return 0
    else:
        print(f"Ошибка создания ярлыка: {result.stderr}")
        return 1


if __name__ == "__main__":
    raise SystemExit(create_shortcut())
