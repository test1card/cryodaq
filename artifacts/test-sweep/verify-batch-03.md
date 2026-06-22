# Verify (amend cycle) — Batch 03 — core experiment/photos

Codex gpt-5.5 high, READ-ONLY. 4 findings, all test-only fixable.

## FIXED (test-only)
- **F1 `test_experiment.py:524` test_experiment_sidecars_use_atomic_write** — only asserted
  "some .json" went through atomic_write_text; prod writes BOTH photo sidecar AND
  metadata.json atomically, so a non-atomic sidecar regression (with metadata still atomic)
  would pass. Now asserts the `composition/` photo-sidecar path explicitly + metadata.json
  by name — two independent checks (585-597).
- **F2 `test_experiment.py:537` test_experiment_wal_verification** — called private
  `em._get_connection()` directly; didn't prove the PUBLIC path propagates WAL failure. Now
  patches sqlite3.connect with a SQL-inspecting fake (PRAGMA journal_mode=WAL → "delete")
  and drives the public `start_experiment()`, asserting RuntimeError. Teeth: fake returning
  "wal" does NOT raise, only "delete" does → the test really keys on the verification
  (592-635).
- **F3 `test_f27_experiment_photos.py:376` test_html_escape_in_caption_prevents_injection**
  — real handle_photo was invoked but the assert had an escape-hatch (`or "script" not in
  text`) that passed even if the caption vanished, and never required escaped username/title.
  Removed the `or` branches; now asserts exact escaped fragments present
  (`&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;`, escaped user/title) and raw forms
  absent (417-434).
- **F4 `test_f27_experiment_photos.py:386` ..._restores_max_height** — fix introduced a real
  QApplication widget test without the headless guard (CI-Linux abort risk). Added repo idiom
  `os.environ.setdefault("QT_QPA_PLATFORM","offscreen")` before PySide6 import (line 23), per
  tests/gui/test_preflight_dialog.py:7.

## Clean (Codex concurs)
- test_no_english_debug_switch_string_remains_in_src — now exercises set_app_mode behaviorally.

Independently re-verified: 43 pass (2 files, 61s — real experiment flows) + ruff-clean. No
DEFERRALS.
