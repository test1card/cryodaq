#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Install the tracked version-pinned Python dependency set first. The
# --no-deps/--no-build-isolation project install avoids a second
# unconstrained runtime or build-backend resolution.
if [ ! -f requirements-lock.txt ]; then
    echo "ERROR: requirements-lock.txt is required for a supported build." >&2
    exit 1
fi
echo "Installing version-pinned dependencies from requirements-lock.txt..."
python -m pip install -r requirements-lock.txt
python -m pip install -e . --no-deps --no-build-isolation
python -m pip check

rm -rf build/ dist/
python -m PyInstaller build_scripts/cryodaq.spec --clean --noconfirm
python build_scripts/post_build.py
echo ""
echo "Build complete: dist/CryoDAQ/"
du -sh dist/CryoDAQ/
