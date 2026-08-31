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

# Owner-authorised (Vladimir, 2026-08-31): permit energizing while the
# lane-P2 qualification-receipt issuer does not exist. Covers ONLY the
# absent-receipt case; every other safety precondition still applies, and
# the engine logs CRITICAL once per run when it is used. Remove this line
# to restore the signed-qualification requirement.
export CRYODAQ_LAB_QUALIFICATION_OVERRIDE=1

echo "=== CryoDAQ — запуск системы ==="
echo "Интерпретатор: $CRYODAQ_PY"
echo "ВНИМАНИЕ: energizing разрешён без qualification receipt (CRYODAQ_LAB_QUALIFICATION_OVERRIDE=1)"
exec "$CRYODAQ_PY" -m cryodaq.launcher "$@"
