#!/bin/bash
cd "$(dirname "$0")"
echo "=== CryoDAQ — режим эмуляции ==="
CRYODAQ_MOCK=1 python -m cryodaq.launcher
