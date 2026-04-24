Model: gemini-2.5-pro

## CLAUDE.md

| Claim (quoted, ≤ 20 words) | Status | Evidence file:line | Severity |
|---|---|---|---|
| Design System: v1.0.0, 66 файлов | STALE | `docs/design-system/MANIFEST.md` | Low |
| Design System: 139 tokens in `theme.py` | STALE | `docs/design-system/MANIFEST.md` | Low |
| Deprecated tokens: `STONE_*` семейство | TRUE | `src/cryodaq/gui/theme.py:240` | Low |
| Command: `pip install -e ".[dev,web]"` | TRUE | `pyproject.toml` | Low |
| `pyarrow` is a base dependency | TRUE | `pyproject.toml` | Low |
| Command: `cryodaq-engine --mock` | TRUE | `src/cryodaq/engine.py:1906` | Low |
| Command: `cryodaq-cooldown` | TRUE | `pyproject.toml` | Low |
| Env Var: `CRYODAQ_ROOT` | TRUE | `src/cryodaq/paths.py:19` | Low |
| Env Var: `CRYODAQ_MOCK=1` | TRUE | `src/cryodaq/engine.py:1917` | Low |
| `SafetyManager` has 6-state FSM | TRUE | `src/cryodaq/core/safety_manager.py:40` | Medium |
| Fail-on-silence: stale data -> FAULT | TRUE | `src/cryodaq/core/safety_manager.py:889` | High |
| Rate limit > 5 K/min -> FAULT | TRUE | `config/safety.yaml:29`, `src/cryodaq/core/safety_manager.py:931` | High |
| Persistence-first ordering in scheduler | TRUE | `src/cryodaq/core/scheduler.py:474-497` | High |
| GUI Module Index (`dashboard`) is complete | STALE | `src/cryodaq/gui/dashboard/` | Medium |
| GUI Module Index (`widgets`) is complete | STALE | `src/cryodaq/gui/widgets/` | Medium |
| A silent `utils` directory exists in `src` | FALSE | `src/cryodaq/utils/` | Low |

## PROJECT_STATUS.md

| Claim (quoted, ≤ 20 words) | Status | Evidence file:line | Severity |
|---|---|---|---|
| Project version `0.13.0` | TRUE | `pyproject.toml` | High |
| Python files in `src/cryodaq/`: 139 | STALE | `find src/cryodaq -name "*.py"` | Medium |
| Test files in `tests/`: 150 | STALE | `find tests -name "*.py"` | Medium |
| Invariant 10: OVERRANGE/UNDERRANGE persist | TRUE | `src/cryodaq/storage/sqlite_writer.py:314` | Medium |
| Invariant 11: Cancellation shielding on `_fault()` | TRUE | `src/cryodaq/core/safety_manager.py:704` | High |
| Invariant 12: Fail-closed config loading | TRUE | `src/cryodaq/engine.py:1947-1958`| High |
| Invariant 14: WAL mode verification | TRUE | `src/cryodaq/storage/sqlite_writer.py:251` | Medium |
| Invariant 17: `_fault()` ordering (log before publish) | TRUE | `src/cryodaq/core/safety_manager.py:722` | High |
| Invariant 18: `_fault()` re-entry guard | TRUE | `src/cryodaq/core/safety_manager.py:679` | High |
| IPC: ZeroMQ PUB/SUB `:5555` | TRUE | `src/cryodaq/core/zmq_bridge.py:27` | Low |
| IPC: ZeroMQ REP/REQ `:5556` | TRUE | `src/cryodaq/core/zmq_bridge.py:28` | Low |

## ROADMAP.md

| Claim (quoted, ≤ 20 words) | Status | Evidence file:line | Severity |
|---|---|---|---|
| F2 - Debug mode toggle (`logging/debug_mode`) | TRUE | `src/cryodaq/logging_setup.py:32` | Low |
| Bug B1 (ZMQ hang) is OPEN | TRUE | `ROADMAP.md` | High |
| Plan is to move to `ipc://` transport for B1 fix | TRUE | `CC_PROMPT_IV_7_IPC_TRANSPORT.md` | High |

## README.md

| Claim (quoted, ≤ 20 words) | Status | Evidence file:line | Severity |
|---|---|---|---|
| "Текущее состояние (v0.33.0)" | FALSE | `pyproject.toml` | High |
| `asyncio.WindowsSelectorEventLoopPolicy` warnings | UNVERIFIABLE | (No Windows access) | Low |

## Cross-Document Inconsistencies

1.  **Project Version:** This is the most critical inconsistency.
    *   `README.md` claims **v0.33.0**.
    *   `PROJECT_STATUS.md` references commits for **v0.33.0** and its release candidates.
    *   `CHANGELOG.md` describes features for versions up to **v0.33.0**.
    *   `pyproject.toml` declares the version as **`0.13.0`**.
    *   **Conclusion:** The official package version (`pyproject.toml`) is severely out of sync with all high-level documentation. This impacts release tracking, dependency management, and operator understanding.

2.  **Code Statistics:**
    *   `PROJECT_STATUS.md` claims **139** `src` files and **150** test files.
    *   The live codebase has **145** `src` files and **192** test files.
    *   **Conclusion:** The project status document is not being updated with code growth. This misrepresents the project's scale and maintenance burden.

3.  **Design System Stats:**
    *   `CLAUDE.md` has two conflicting claims for the Design System: **v1.0.0 / 66 files** and **v1.0.1 / 67 files**. It also claims **139 tokens**.
    *   `docs/design-system/MANIFEST.md` (the source of truth) states **v1.0.1 / 67 files / 141 tokens**.
    *   **Conclusion:** `CLAUDE.md` is internally inconsistent and partially stale regarding the design system details.

## Undocumented Features

*   **`src/cryodaq/utils/`:** A top-level `utils` directory exists in the source tree but is not mentioned in any of the audited architectural documents.
*   **`src/cryodaq/gui/dashboard/experiment_card.py`:** This key UI component is missing from the module index in `CLAUDE.md`.
*   **`src/cryodaq/gui/widgets/overview_panel.py` and `vacuum_trend_panel.py`:** These legacy widgets are not listed in the `CLAUDE.md` index.

## Top 10 Prioritized Fix List

1.  **(CRITICAL)** Resolve the version number conflict between `pyproject.toml` (`0.13.0`) and all other documentation (`0.33.0`). Decide on a single source of truth and update all other locations.
2.  **(HIGH)** Update `README.md` to reflect the correct current version number. An incorrect version on the main entrypoint for users is highly misleading.
3.  **(HIGH)** Update the file count statistics in `PROJECT_STATUS.md` to reflect the current codebase size (145 `src`, 192 `tests`). This gives a more accurate picture of the project's state.
4.  **(MEDIUM)** Update the GUI module index in `CLAUDE.md` to include the missing files, especially `experiment_card.py`. This is important for agent-facing documentation.
5.  **(MEDIUM)** Update the `CLAUDE.md` documentation to consistently state the correct Design System version, file count, and token count from `MANIFEST.md`.
6.  **(LOW)** Add the `src/cryodaq/utils/` directory to the architectural overview in `CLAUDE.md`.
7.  **(LOW)** Update the GUI `widgets` module index in `CLAUDE.md` to be complete.
8.  **(LOW)** Correct the stale Design System file count claim (66 files) in `CLAUDE.md`.
9.  **(LOW)** Correct the stale Design System token count claim (139 tokens) in `CLAUDE.md`.
10. **(LOW)** Add a note to `ROADMAP.md` confirming that the `pyarrow` dependency for F1 was successfully added to the base dependencies.
I have completed the audit and created the report as requested.
=== gemini-03-doc-reality finished at 01:30:55 ===
