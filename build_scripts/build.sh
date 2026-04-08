#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf build/ dist/
pyinstaller build_scripts/cryodaq.spec --clean --noconfirm
python build_scripts/post_build.py
echo ""
echo "Build complete: dist/CryoDAQ/"
du -sh dist/CryoDAQ/
