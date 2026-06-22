# Batch 19 — tier 1 — notifications/telegram + replay (96 tests, 10 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 3 HIGH / 2 MED / 1 LOW. 7 files clean.
SECURITY tests test_telegram_allowlist + test_telegram_ssl_verification: BOTH CLEAN
(genuinely exercise the control).

## HIGH
- test_replay_predictor.py:89 `..._nominal_cooldown_no_predictor_alarms` — patches
  _predictor_fires to always False; predictor branch untested. Fix: deterministic fake
  model + controlled predict(), or assert _predictor_fires with known progress/deviation.
- test_replay_predictor.py:111 `..._stuck_plateau_predictor_fires` — mocks _predictor_fires
  then asserts newly_fired>=0 (tautological). Fix: exercise real _predictor_fires, assert
  newly_fired>0 + fired records have cold channel/phase/plateau timestamps.
- test_telegram.py:369 `test_escalation_cancel_stops` — 60min delay but waits 0.05s; a no-op
  cancel passes. Fix: fake clock OR assert task cancelled/removed from _pending.

## MED
- test_replay_engine.py:155 `test_replay_engine_heartbeat` — never starts bridge/heartbeat;
  only checks one readings multipart. Fix: rename to first-reading PUB, or start bridge +
  assert heartbeat payload.
- test_replay_engine.py:286 `..._curve_data_pub` — len>=10 + (Т12 OR Т11); one channel
  passes; values unchecked; fixed sleep(0.05). Fix: {Т12,Т11}<=channels + decoded values +
  readiness loop.

## LOW
- test_telegram.py:346 `test_escalation_chain_sends` — sleep(0.05) timing flake. Fix: expose
  tasks / gather _pending after zero-delay.

Clean: test_telegram_allowlist, test_telegram_ssl_verification, test_telegram_phase_vocab,
test_v0_55_5_dispatch_policy, test_curve_transforms, test_replay_to_thread,
test_legacy_channel_map.
