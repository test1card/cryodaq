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


# Print a traceback when a NATIVE fault kills a process (SIGBUS, SIGSEGV).
# The engine died with SIGBUS six times on 2026-09-02 and left no evidence:
# without this, Python dies silently on a fault, so the launcher's stderr
# capture had nothing to forward and the cause could not be named. It costs
# nothing in normal operation -- it prints only when a process is already
# dying -- and it is the difference between "code=-7" and a library and line.
export PYTHONFAULTHANDLER=1

echo "=== CryoDAQ — запуск системы ==="
echo "Интерпретатор: $CRYODAQ_PY"
exec "$CRYODAQ_PY" -m cryodaq.launcher "$@"
