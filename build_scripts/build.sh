#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Phase 2c M.1: install from lockfile first for reproducible builds.
# Two operators building on different days now get the exact same
# transitive deps. The --no-deps install of cryodaq itself avoids
# pulling in `>=` resolutions that would shadow the locked versions.
if [ -f requirements-lock.txt ]; then
    echo "Installing from requirements-lock.txt (reproducible build)..."
    pip install --require-hashes -r requirements-lock.txt 2>/dev/null \
        || pip install -r requirements-lock.txt
    pip install -e . --no-deps
fi

rm -rf build/ dist/
pyinstaller build_scripts/cryodaq.spec --clean --noconfirm
python build_scripts/post_build.py
echo ""
echo "Build complete: dist/CryoDAQ/"
du -sh dist/CryoDAQ/
