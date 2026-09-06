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

# Put the environment's own libstdc++ ahead of the system one.
#
# MEASURED on lab53, 2026-09-06, in a clean interpreter:
#
#     import pyarrow   -> binds /usr/lib/x86_64-linux-gnu/libstdc++.so.6.0.30
#     import sqlite3   -> binds <env>/lib/libstdc++.so.6.0.36
#
#     import pyarrow; import sqlite3  -> ImportError: libstdc++.so.6:
#         version `CXXABI_1.3.15' not found (required by libicui18n.so.78)
#     import sqlite3; import pyarrow  -> fine
#
# The system libstdc++ is older than what this environment's libicui18n needs,
# so whichever of the two loads FIRST decides whether sqlite3 can load at all.
# `storage/cold_rotation.py` imports pyarrow before sqlite3 and therefore cannot
# be imported on its own; the stack survives only because `engine.py` happens to
# reach sqlite3 first. That is an accident of line order, not a guarantee, and a
# new entry point with the other order would fail at start.
#
# An `import sqlite3` inside the package was tried first and rejected: it fixes
# only the order where cryodaq is imported first, and a caller that reaches
# pyarrow before cryodaq still fails. This fixes the cause instead.
if [ "$CRYODAQ_PY" != "$(command -v python3 || true)" ]; then
    CRYODAQ_ENV_LIB="$(dirname "$(dirname "$CRYODAQ_PY")")/lib"
    if [ -d "$CRYODAQ_ENV_LIB" ]; then
        export LD_LIBRARY_PATH="$CRYODAQ_ENV_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    fi
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
