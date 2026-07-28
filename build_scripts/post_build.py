"""Post-build: copy configs, create runtime directory structure, write README.

Run after ``pyinstaller build_scripts/cryodaq.spec``. Seeds the dist tree
with the contents that ``paths.py`` expects to find next to the exe under
``sys.executable.parent``.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    dist_dir = project_root / "dist" / "CryoDAQ"

    if not dist_dir.exists():
        print(f"ERROR: {dist_dir} not found. Run pyinstaller first.", file=sys.stderr)
        sys.exit(1)

    # --- config/ next to exe (NOT inside _internal/) ---
    config_dst = dist_dir / "config"
    config_dst.mkdir(exist_ok=True)
    config_src = project_root / "config"
    copied = 0
    for yaml_file in config_src.rglob("*.yaml"):
        if ".local." in yaml_file.name:
            continue  # skip machine-specific files
        destination = config_dst / yaml_file.relative_to(config_src)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(yaml_file, destination)
        copied += 1
    for example in config_src.rglob("*.local.yaml.example"):
        destination = config_dst / example.relative_to(config_src)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(example, destination)

    themes_src = config_src / "themes"
    themes_copied = 0
    if themes_src.exists():
        themes_dst = config_dst / "themes"
        shutil.copytree(themes_src, themes_dst, dirs_exist_ok=True)
        themes_copied = sum(1 for path in themes_dst.glob("*.yaml") if path.is_file())

    # LICENSE next to exe (Phase 2c O.1)
    license_src = project_root / "LICENSE"
    if license_src.exists():
        shutil.copy2(license_src, dist_dir / "LICENSE")

    # --- runtime directories ---
    (dist_dir / "data").mkdir(exist_ok=True)
    (dist_dir / "logs").mkdir(exist_ok=True)
    (dist_dir / "plugins").mkdir(exist_ok=True)

    # Copy plugin examples if any
    plugins_src = project_root / "plugins"
    if plugins_src.exists():
        for plugin in plugins_src.glob("*.py"):
            shutil.copy2(plugin, dist_dir / "plugins" / plugin.name)

    # --- operator README (Russian) ---
    readme = dist_dir / "README_OPERATOR.txt"
    readme.write_text(
        "CryoDAQ — инструкция для оператора\n"
        "====================================\n\n"
        "Запуск: двойной клик по CryoDAQ (CryoDAQ.exe на Windows).\n\n"
        "Структура каталога:\n"
        "  CryoDAQ[.exe]     главный исполняемый файл\n"
        "  config/           настройки приборов (GPIB, COM, пороги)\n"
        "  data/             SQLite база с измерениями\n"
        "  logs/             логи engine и GUI\n"
        "  plugins/          analytics плагины (горячая перезагрузка)\n"
        "  _internal/        библиотеки Python (НЕ ТРОГАТЬ)\n\n"
        "Перед первым запуском:\n"
        "  1. Проверьте config/instruments.yaml\n"
        "  2. Скопируйте config/notifications.local.yaml.example\n"
        "     в config/notifications.local.yaml и вставьте Telegram token\n"
        "  3. (Linux) убедитесь что linux-gpib установлен\n"
        "     (Windows) убедитесь что NI-VISA Runtime установлен\n"
        "  4. Если SQLite < 3.51.3 (Ubuntu 22.04), см. docs/deployment.md\n",
        encoding="utf-8",
    )

    print("Post-build complete:")
    print(f"  {copied} configs copied to {config_dst}")
    print(f"  {themes_copied} theme packs copied to {config_dst / 'themes'}")
    print("  data/, logs/, plugins/ created")
    print("  README_OPERATOR.txt written")


if __name__ == "__main__":
    main()
