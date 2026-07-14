#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Install the tracked version-pinned Python dependency set first. The
# --no-deps project install avoids a second unconstrained resolution.
if [ -f requirements-lock.txt ]; then
    echo "Installing version-pinned dependencies from requirements-lock.txt..."
    pip install -r requirements-lock.txt
    pip install -e . --no-deps
    pip check
fi

rm -rf build/ dist/
pyinstaller build_scripts/cryodaq.spec --clean --noconfirm
python build_scripts/post_build.py
echo ""
echo "Build complete: dist/CryoDAQ/"
du -sh dist/CryoDAQ/
