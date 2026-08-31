#!/bin/bash
# CryoDAQ operator launcher.
#
# Resolves the supported runtime (docs/deployment.md: conda env from
# environment.yml, which pins the Python-linked SQLite past the WAL gate).
# Falls back to PATH python3 only so the script stays portable; on a stock
# Ubuntu 22.04 box that fallback will stop at the SQLite gate by design.
cd "$(dirname "$0")"

CRYODAQ_PY="${CRYODAQ_PYTHON:-$HOME/miniforge3/envs/cryodaq/bin/python}"
if [ ! -x "$CRYODAQ_PY" ]; then
    CRYODAQ_PY="$(command -v python3 || true)"
fi
if [ -z "$CRYODAQ_PY" ]; then
    echo "ОШИБКА: интерпретатор Python не найден." >&2
    echo "Ожидалось conda-окружение cryodaq (см. docs/deployment.md)." >&2
    exit 1
fi

echo "=== CryoDAQ — режим эмуляции ==="
echo "Интерпретатор: $CRYODAQ_PY"
CRYODAQ_MOCK=1 exec "$CRYODAQ_PY" -m cryodaq.launcher "$@"
