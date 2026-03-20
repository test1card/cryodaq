#!/bin/bash
cd "$(dirname "$0")"
echo "=== CryoDAQ — запуск системы ==="
python -m cryodaq.launcher
