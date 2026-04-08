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
    for yaml_file in config_src.glob("*.yaml"):
        if ".local." in yaml_file.name:
            continue  # skip machine-specific files
        shutil.copy2(yaml_file, config_dst / yaml_file.name)
        copied += 1
    for example in config_src.glob("*.local.yaml.example"):
        shutil.copy2(example, config_dst / example.name)

    # Experiment templates subdirectory
    templates_src = config_src / "experiment_templates"
    if templates_src.exists():
        templates_dst = config_dst / "experiment_templates"
        templates_dst.mkdir(exist_ok=True)
        for tpl in templates_src.glob("*.yaml"):
            shutil.copy2(tpl, templates_dst / tpl.name)

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
    print("  data/, logs/, plugins/ created")
    print("  README_OPERATOR.txt written")


if __name__ == "__main__":
    main()
