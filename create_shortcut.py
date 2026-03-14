"""Создать ярлык CryoDAQ на рабочем столе (Windows).

Запуск: python create_shortcut.py

Создаёт ярлык CryoDAQ.lnk, который запускает pythonw -m cryodaq.launcher
без окна терминала. Оператору достаточно дважды кликнуть по ярлыку.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def create_shortcut() -> None:
    """Создать ярлык на рабочем столе Windows."""
    if sys.platform != "win32":
        print("Этот скрипт предназначен только для Windows.")
        print("На Linux/macOS используйте: pythonw -m cryodaq.launcher")
        return

    try:
        import winshell  # type: ignore[import-untyped]
    except ImportError:
        # Fallback: использовать COM напрямую
        _create_shortcut_com()
        return

    desktop = winshell.desktop()
    shortcut_path = os.path.join(desktop, "CryoDAQ.lnk")

    pythonw = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable)

    project_root = Path(__file__).resolve().parent

    winshell.CreateShortcut(
        Path=shortcut_path,
        Target=str(pythonw),
        Arguments="-m cryodaq.launcher",
        StartIn=str(project_root),
        Description="CryoDAQ — Система сбора данных криогенной лаборатории",
    )
    print(f"Ярлык создан: {shortcut_path}")


def _create_shortcut_com() -> None:
    """Создать ярлык через Windows COM (без winshell)."""
    try:
        # pylint: disable=import-error
        from win32com.client import Dispatch  # type: ignore[import-untyped]
    except ImportError:
        # Последний fallback: PowerShell
        _create_shortcut_powershell()
        return

    desktop = Path.home() / "Desktop"
    shortcut_path = str(desktop / "CryoDAQ.lnk")

    pythonw = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable)

    project_root = Path(__file__).resolve().parent

    shell = Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(shortcut_path)
    shortcut.TargetPath = str(pythonw)
    shortcut.Arguments = "-m cryodaq.launcher"
    shortcut.WorkingDirectory = str(project_root)
    shortcut.Description = "CryoDAQ — Система сбора данных криогенной лаборатории"
    shortcut.save()
    print(f"Ярлык создан: {shortcut_path}")


def _create_shortcut_powershell() -> None:
    """Создать ярлык через PowerShell (fallback без COM/winshell)."""
    import subprocess

    desktop = Path.home() / "Desktop"
    shortcut_path = str(desktop / "CryoDAQ.lnk")

    pythonw = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable)

    project_root = Path(__file__).resolve().parent

    ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut('{shortcut_path}')
$s.TargetPath = '{pythonw}'
$s.Arguments = '-m cryodaq.launcher'
$s.WorkingDirectory = '{project_root}'
$s.Description = 'CryoDAQ'
$s.Save()
"""
    result = subprocess.run(
        ["powershell", "-Command", ps_script],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"Ярлык создан: {shortcut_path}")
    else:
        print(f"Ошибка создания ярлыка: {result.stderr}")


if __name__ == "__main__":
    create_shortcut()
