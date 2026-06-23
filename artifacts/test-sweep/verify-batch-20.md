# Verify (amend cycle) — Batch 20 — replay/reporting/sinks/root

NOTE: Codex usage-limited (resets ~6:14 AM) — reviewed INLINE by Claude, same criteria. The 3 DEFERRED
items (shutdown-drain copy, summary-metadata-export, replay-predictor PUB handshake) stay deferred
(ledger items 2/3/6-style — need src helper extraction).

VERDICT: **VERIFY PASS — 0 fix-introduced problems** in the 5 fixed tests.

## Reviewed (all CLEAN)
- **test_frozen_entry.py:32 freeze_support_before_heavy_imports** — the AST ordering check now includes
  `_dispatch` (the real __main__ entry), not just `main_*` funcs: `n.name.startswith("main_") or n.name ==
  "_dispatch"`. freeze_support()-before-heavy-imports verified for the actual entry path.
- **test_replay_phases.py:302 blocks_safety_command** — now asserts `_is_command_blocked("safety_acknowledge")
  is True` directly (the real denylist), with a comment that ok=False alone is insufficient (unknown cmds
  also return ok=False). Plus the dispatch result ok is False.
- **test_report_generator.py:180 / :268 (archive tables / archived_measured_values)** — both DISABLE the
  live DB (`live_db.unlink()` / `db_path.unlink()`) and assert the SEEDED archived values surface: T_STAGE
  4.3 K appears as "4.30 К" in the generated doc text; the :268 test also asserts K1/smua/power,
  P_MAIN/pressure, T_STAGE in the archive CSV. Proves the archive path is read, not the live DB. (Reviewed
  statically + ruff — this file invokes the Gemma/Ollama report intro so it hangs on THIS machine's live
  ollama; it runs on CI and is the file deselected from local gates.)
- **test_instance_lock.py:36 double_acquire** — honestly renamed to `test_double_acquire_same_process` and
  now asserts a DEFINITE outcome `fd2 is None` (second acquire fails), not "accept both". Sibling lock tests
  (cross-process, released-on-death, pid-written) all assert definite outcomes.
- **test_rag_index_sink.py:85 default_config_when_yaml_missing** — the fake `_rebuild_index` now RECORDS the
  cfg (`seen.append(cfg)`) and the test asserts `seen == [{}]` (default empty config), not just success.

Independently re-verified: 48 pass (4 runnable files, -m "not ollama") + ruff-clean (all 5). report_generator
covered by static review + CI gate. No fixes needed. 3 DEFERRED items unchanged.
