# Batch 18 — tier 1 — integration/launcher/notifications (99 tests, 9 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 3 HIGH / 9 MED / 5 LOW. 1 file clean.

## HIGH — SECURITY-relevant (secret-leak guard weakly tested; NOT a confirmed leak)
- test_secret_str.py:44 `..._notifier_no_plain_url_attribute` — source grep rejects one
  spelling `self._api_url = f`; misses other attrs/containers/runtime leakage. Fix:
  instantiate with sentinel token, recursively inspect __dict__ (allow only SecretStr),
  patch _get_session, assert logs/attrs lack the token.
- test_secret_str.py:56 `..._command_bot_no_plain_api_attribute` — grep only checks
  "SecretStr" appears. Fix: instantiate TelegramCommandBot, inspect runtime attrs for raw
  token, assert URLs built at call time only.
- test_secret_str.py:69 `..._periodic_report_no_plain_url_attribute` — same. Fix: sentinel
  token, verify no runtime attr/log contains raw token except the outbound request URL.

## MED
- test_analytics_contract.py:279 `..._phase_swap_preserves_series_count` — post-swap assert
  guarded by `if isinstance(...)`; passes if widget not mounted at all. Fix: assert type
  unconditionally + replayed series.
- test_diagnostic_alarm_pipeline.py:45 — reimplements _sensor_diag_tick locally + sends via
  telegram_mock; prod uses notify_telegram/batching/_send_to_all/async. Fix: exercise prod
  tick/dispatch.
- test_launcher_replay.py:42 (argparse) — _parse_launcher_args duplicates prod parser;
  drift in main() not caught. Fix: expose prod parse_args() and test it.
- test_launcher_replay.py:286 `..._no_duplicate_qtimer_import` — inspect.getsource grep. Fix:
  instantiate LauncherWindow offscreen w/ patched startup, assert no UnboundLocalError.
- test_predictor_bootstrap.py:35/43 — source string search for hint call/suppression. Fix:
  patch _check_predictor_bootstrap_hint, call _start_engine (non-replay/replay), assert
  called/not-called.
- test_f27_composition_handler.py:342 `..._late_binding_reflects_renames` — never renames
  the manager; both asserts use original name. Fix: mutate manager between calls.
- test_f27_composition_handler.py:358 `..._cleanup_loop_removes_expired` — duplicates cleanup
  logic, never calls _cleanup_loop. Fix: extract _cleanup_expired(now) or run one real loop iter.

## LOW
- test_analytics_view_lifecycle.py:219 — only "R" in title, not F8 text. Fix: assert "F8".
- test_launcher_replay.py:90/303 — title built in test / token-before-class grep. Fix:
  instantiate / assert launcher.QTimer is Qt class.
- test_f27_telegram_photo.py:190/238/253 — download/edit/answer assert non-None or post-called
  -once; wrong endpoint/payload passes. Fix: assert exact bytes/URL/endpoint+payload.

Clean: test_periodic_report_v0_55_5.
