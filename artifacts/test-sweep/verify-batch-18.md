# Verify (amend cycle) — Batch 18 — integration/launcher/notifications (SECURITY)

Codex gpt-5.5 high, READ-ONLY. 8 findings: 5 fixed (test-only), 3 deferred (need src seam). Codex
confirmed CLEAN: phase_swap (unconditional type+series), predictor_bootstrap (patches hint + real
_start_engine), composition late_binding (renames manager) + cleanup_loop (real _cleanup_loop),
analytics_view F8 text, launcher QTimer-module-import. diagnostic_alarm_pipeline stayed deferred (item 6).

## FIXED (test-only)
- **F1 SECURITY `test_secret_str.py:44/56/69`** — the runtime token-leak walker only scanned __dict__
  VALUES. Hardened: now walks __dict__ values + __slots__ across the full class MRO + nested
  mappings/sequences, stops at SecretStr (the only allowed raw-token container) and at non-cryodaq objects
  (no Mock/stdlib false positives), and asserts `isinstance(_bot_token, SecretStr)` for ALL THREE classes
  (TelegramNotifier, TelegramCommandBot, PeriodicReporter). Sentinel token. Teeth: a plain-str token attr
  is caught.
- **F5-F8 `test_f27_telegram_photo.py:190/238/253/277`** — substring/non-None/called-once → EXACT URL +
  EXACT payload from prod (telegram_commands.py:601-682): download_file CDN URL; sendMessage url+payload
  (chat_id/text/parse_mode/reply_markup); editMessageText url+payload; answerCallbackQuery url+payload;
  removed a duplicated assert_called_once. F6 teeth: wrong payload → FAIL.

## DEFERRED (need src seam — ledger item 10)
- **F2 argparse** — `launcher.main()` builds the parser inline; testing the REAL parser needs a prod
  `_parse_args(argv)` helper extracted from main(). Test currently duplicates the parser.
- **F3 window-title + F4 no-duplicate-QTimer** — want a real offscreen `LauncherWindow`, but
  `LauncherWindow.__init__` calls `_start_engine()` unconditionally (launcher.py:341) → not constructable
  test-only without an injectable/skippable engine-start seam. Kept inspect.getsource / module-level
  QTimer-is-Qt guards (the no-dup-QTimer module check can't catch a local UnboundLocalError binding without
  real construction).

Independently re-verified: 38 pass (3 files, -m "not ollama") + ruff-clean. Security walker teeth-checked.
