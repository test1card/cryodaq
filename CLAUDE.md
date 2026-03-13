# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# CryoDAQ

LabVIEW replacement for cryogenic lab (АКЦ ФИАН, Millimetron).

## Architecture

- Two-process: cryodaq-engine (headless, asyncio) + cryodaq-gui (PySide6)
- IPC: ZeroMQ PUB/SUB (data) + REQ/REP (commands)
- Storage: SQLite WAL (crash-safe, 1 file/day)
- Language: Python 3.12+, asyncio
- Cross-platform: Windows (primary) + Linux (future)

## Instruments

- 3x LakeShore 218S (GPIB, 24 temperature channels, SCPI: KRDG? 0)
- 1x Keithley 2604B (USB-TMC, TSP/Lua, P=const feedback loop inside instrument)
- Vacuum gauge (TBD, will be added as module)

## Key Rules

- Engine must run weeks without restart. No memory leaks. No unbounded buffers.
- GUI is separate process. Can be closed/opened without data loss.
- Keithley TSP scripts MUST have watchdog timeout -> source OFF.
- No blocking I/O anywhere in engine.
- All operator-facing text in Russian.
- No platform-specific code in business logic (pathlib, config-driven).

## Standards

- Calibration per ГОСТ Р 8.879-2014
- DT-670B1-CU silicon diodes, individual curves per sensor
