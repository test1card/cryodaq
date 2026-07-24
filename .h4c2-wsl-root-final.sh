#!/usr/bin/env bash
set -euo pipefail

src=/mnt/c/Users/3fall/Projects/cryodaq/.worktrees/codex-h4-c2
d=/tmp/cryodaq-h4c2-root-final-b2f0381a9d5a4094bb60a88958384499
mkdir "$d"
tar -xf "$src/.h4c2-base-871f49e918b2473aa66be56636171dd2.tar" -C "$d"
cp "$src/scripts/soak_mock_stack.py" "$d/scripts/soak_mock_stack.py"
cp "$src/scripts/soak_mock_stack_runner.py" "$d/scripts/soak_mock_stack_runner.py"
cp "$src/tests/scripts/test_soak_mock_stack_runner.py" "$d/tests/scripts/test_soak_mock_stack_runner.py"
cd "$d"
git init -q
git config user.name "CryoDAQ H4 verifier"
git config user.email "h4-verifier@invalid.local"
git add .
git commit -q -m "Frozen H4 verification snapshot"
ln -s /root/.venvs/cryodaq-h4-c2 "$d/.venv"
PYTHONPATH="$d/src" .venv/bin/python -m pytest -q \
  tests/scripts/test_soak_mock_stack.py \
  tests/scripts/test_soak_mock_stack_runner.py \
  tests/scripts/test_soak_mock_stack_runner_artifact_capability.py \
  tests/scripts/test_soak_mock_stack_runner_bridge_handshake.py \
  tests/scripts/test_soak_mock_stack_runner_joined_receipts.py \
  tests/scripts/test_soak_mock_stack_runner_process_authority.py \
  --basetemp=/tmp/pytest-h4c2-root-final-b2f0381a9d5a4094bb60a88958384499
