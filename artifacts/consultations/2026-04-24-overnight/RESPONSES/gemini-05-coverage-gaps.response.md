Model: gemini-2.5-pro

## 1. Subsystem Coverage

| Subsystem       | Source file count | Test file count | Qualitative rating | Evidence                                                                                                                                                                                            |
| --------------- | ----------------- | --------------- | ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **core**        | 26                | 53              | `STRONG`           | Excellent test-to-source ratio. Critical components like `SafetyManager`, `Scheduler`, and `InterlockEngine` have multiple dedicated, complex test files (`test_safety_manager.py`, `test_persistence_ordering.py`, `test_interlock.py`). |
| **drivers**     | 7                 | 11              | `STRONG`           | Good ratio. All major instruments (`Keithley2604B`, `LakeShore218S`, `ThyracontVSP63D`) have dedicated test files. Safety-critical connection logic appears to be covered (`test_keithley_connect_safety.py`). |
| **storage**     | 6                 | 7               | `MODERATE`         | 1:1 ratio is adequate. All export formats and the replay function have tests. `sqlite_writer.py` is a large, critical file; while it has tests, its complexity suggests there may still be gaps. The presence of `test_disk_full_handling.py` is a positive sign for robustness. |
| **analytics**   | 8                 | 10              | `STRONG`           | Good ratio. All major analytics plugins (`calibration`, `cooldown_predictor`, `vacuum_trend`) have corresponding tests.                                                                            |
| **notifications** | 5                 | 4               | `MODERATE`         | Decent ratio, but tests focus on the `TelegramNotifier` and secret redaction. Critical logic in `escalation.py` and complex command parsing in `telegram_commands.py` appear less thoroughly tested. |
| **reporting**   | 3                 | 1               | `WEAK`             | A single test file for three source files is a low ratio. `sections.py` is a large, 32KB file responsible for report generation logic, which is unlikely to be well-covered by the single `test_report_generator.py`. |
| **web**         | 2                 | 2               | `WEAK`             | The main `server.py` file is over 20KB, and it is unlikely that two test files (`test_web_dashboard.py`, `test_xss_escaping.py`), one of which is for XSS, provide sufficient coverage for the API surface. |
| **gui**         | ~65               | ~75             | `MODERATE`         | The file ratio is good, and there's clear testing of design system rules, themes, and individual components/overlays. However, GUI testing is inherently difficult. Coverage is likely focused on component state and wiring rather than complex, multi-step user interaction flows. |

## 2. Untested Critical Code Paths (Safety-Only)

1.  **`SafetyManager` FSM transition: stuck start.**
    -   **File:** `src/cryodaq/core/safety_manager.py:1010` (in `_run_checks`)
    -   **Risk:** If a `keithley.start_source()` call hangs, the system could be stuck in `RUN_PERMITTED` without timing out. The code correctly handles this by faulting, but this specific transition path is not explicitly tested.
2.  **`SafetyManager` FSM transition: partial stop.**
    -   **File:** `src/cryodaq/core/safety_manager.py:848` (in `_safe_off`)
    -   **Risk:** When stopping one of two active SMU channels, the system should transition from `RUNNING` back to `RUNNING`. An error here could incorrectly move the system to `SAFE_OFF`, stopping a valid running measurement on the second channel.
3.  **`InterlockEngine` soft-stop failure escalation.**
    -   **File:** `src/cryodaq/core/safety_manager.py:1125` (in `on_interlock_trip`)
    -   **Risk:** An interlock with `action="stop_source"` attempts a soft shutdown. If the underlying `emergency_off()` call fails, the logic correctly escalates to a hard `_fault`. This escalation path is safety-critical but not covered by `test_interlock_action_dispatch.py`.
4.  **`SafetyManager` fail-on-silence state gate.**
    -   **File:** `src/cryodaq/core/safety_manager.py:1001` (in `_run_checks`)
    -   **Risk:** Stale data must cause a fault *only* in `RUNNING` or `RUN_PERMITTED` states. The logic correctly gates this. Lack of an explicit test means a future refactor could cause stale data in `READY` or `MANUAL_RECOVERY` to incorrectly trigger a fault.

## 3. Top 10 Missing Tests

| Test name                                                        | Priority (1-10) | Safety-relevant? (Y/N) | What it would assert                                                                                                                                  | File it would live in                               |
| ---------------------------------------------------------------- | --------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `test_safety_stuck_in_run_permitted_causes_fault`                | 1               | Y                      | Mocks `keithley.start_source` to hang, verifies `SafetyManager` transitions from `RUN_PERMITTED` to `FAULT_LATCHED` after the heartbeat timeout.        | `tests/core/test_safety_manager.py`                 |
| `test_interlock_stop_source_failure_escalates_to_fault`          | 2               | Y                      | Triggers a `stop_source` interlock, mocks `keithley.emergency_off` to raise an exception, and asserts `SafetyManager` transitions to `FAULT_LATCHED`.   | `tests/core/test_interlock_action_dispatch.py`      |
| `test_stale_data_does_not_fault_in_non_running_states`           | 3               | Y                      | Verifies that critically stale data does NOT cause a fault when the `SafetyManager` is in `SAFE_OFF`, `READY`, or `MANUAL_RECOVERY` states.         | `tests/core/test_safety_manager.py`                 |
| `test_safety_manager_partial_stop_remains_running`               | 4               | Y                      | With two active sources, stops one and asserts the state remains `RUNNING`.                                                                           | `tests/core/test_safety_manager.py`                 |
| `test_report_section_generation_logic`                           | 5               | N                      | For each type of report section in `reporting/sections.py`, provides mock data and asserts the generated output structure is correct.               | `tests/reporting/test_report_generator.py`          |
| `test_web_server_api_endpoints`                                  | 6               | N                      | Mocks the engine and sends requests to each FastAPI endpoint in `web/server.py`, asserting correct status codes and response schemas.               | `tests/web/test_server.py`                          |
| `test_notification_escalation_service`                           | 7               | Y                      | Mocks `asyncio.sleep` and notifiers to verify that an un-cleared alarm triggers the full, timed escalation chain specified in config.               | `tests/notifications/test_escalation.py`            |
| `test_telegram_command_parser_edge_cases`                        | 8               | N                      | Tests the command parser in `telegram_commands.py` with malformed input, missing arguments (`/log`), and unknown commands.                        | `tests/notifications/test_telegram_commands.py`     |
| `test_scheduler_stops_polling_on_persistence_failure`            | 9               | Y                      | Mocks `SQLiteWriter` to fail and asserts the main `Scheduler` polling loop is gracefully stopped to prevent data loss or silent broker publishing. | `tests/core/test_scheduler.py`                      |
| `test_crash_recovery_force_off_fails_logs_critical`              | 10              | Y                      | Mocks `Keithley2604B.connect` where the initial `emergency_off` fails, and asserts a `CRITICAL` error is logged.                                  | `tests/drivers/test_keithley_connect_safety.py`     |

## 4. Anti-Pattern Tests

1.  **Asserting exact log/message strings.**
    -   **File:** `tests/notifications/test_telegram.py:100` (`test_format_message_activated`)
    -   **Fragility:** `assert "ТРЕВОГА" in msg` and `assert "Тревога снята" in msg` check for specific presentational text. If this Russian-language UI text is rephrased for clarity, the test will break even if the underlying logic is correct.
2.  **Asserting specific redaction format.**
    -   **File:** `tests/test_logging_setup.py:38` (`test_telegram_token_redacted_in_msg`)
    -   **Fragility:** `assert "bot***" in output` tests that the token is replaced with a specific string. A better implementation might use `[REDACTED]`. The test should assert the *absence* of the secret, not the *presence* of a specific placeholder.
3.  **Asserting exact timestamp string format.**
    -   **File:** `tests/notifications/test_telegram.py:186` (`test_format_message_time_format`)
    -   **Fragility:** `assert "09:05:03" in msg` tests a specific `H:M:S` format. This is brittle. If the format changes for localization or clarity (e.g., to include AM/PM), the test will fail unnecessarily.
4.  **Asserting mock call counts.**
    -   **File:** `tests/notifications/test_telegram.py:290` (`test_escalation_chain_sends`)
    -   **Fragility:** `assert notifier.send_message.call_count == 2` is tightly coupled to the implementation detail that two notifications are sent. A future change to bundle these into a single notification would break this test, even if the user experience is identical or better.
5.  **Inspecting mock call arguments.**
    -   **File:** `tests/notifications/test_telegram.py:228` (`test_cmd_status_formats_message`)
    -   **Fragility:** `text: str = bot._send.call_args[0][1]` directly inspects the arguments passed to the mocked `_send` method. This is an implementation detail. The test should focus on the observable outcome, not how the method was called internally.
I have completed the audit and written the results to `artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-05-coverage-gaps.response.md`.
=== gemini-05-coverage-gaps finished at 01:36:14 ===
