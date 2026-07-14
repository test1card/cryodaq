# Roadmap 10/10 execution ledger — Phase A→E (handoff scratchpad/montana/HANDOFF_ROADMAP_EXECUTION.md)
# Base: master f5d6434 (v0.64.1). Branch: feat/montana-phase-a.
# Protocol: Sonnet=S items, Opus=M/L; Fable reviews+commits per item; Codex gate per phase boundary.
# NOTE: docs/ORCHESTRATION.md absent from main tree (hygiene train); contract read from .worktrees/v0.56.1-audit copy.
2026-07-09 WAVE A1 dispatch: A2(Opus,engine.py) | A4(Opus,launcher.py) | A1b+A8(Opus,tsp+keithley+smoke) | A10(Opus,safety_manager+GUI confirm) | A6(Sonnet,sqlite_writer) | A7(Sonnet,install.bat+CI+docs) | A9(Sonnet,physical_alarms.yaml). A1(a) config flip = Fable direct. A3 waits on A2+A4 (engine.py+launcher.py overlap). Reports → scratchpad/montana/exec/impl_a*.md.
2026-07-09 ROUTING UPDATE (Vladimir, mid-wave): "sonnet s and m and l, opus for xl only. sonnet 5 is very capable" — wave A1's 4 Opus dispatches stay (in flight); ALL further dispatches Sonnet except genuinely XL (C1 PID class).
A4: complete (commit 93dab79, Fable review clean — retry-forever cap 120s, modals→banner+bell, 19 tests green, ruff clean; Codex in phase batch)
A9: complete (commit d44fcfa, Fable review clean — consumer path verified not-dead-key, 37 tests green, 0 tests pinned default; Codex in phase batch)
A6: complete (commit 642155b, Fable review: +warning ниже порога (silent-loss gap закрыт Fable-правкой), 18 tests green, ruff clean; re-raise policy flagged for Codex batch)
A10: complete (commit 90f8695, Fable review clean — flag-before-lock, verbatim extraction, RED→GREEN proven, 68 tests; shared-flag race → Codex batch)
A1a+A1b+A8: complete (commit dac1fad, Fable review clean — lua eyeballed (pcall degrade, честный PARKED-статус), 41+4skip green, ruff clean, yaml valid; BENCH GATE: trip-test awaiting Vladimir+2604B)
A2: complete (commit 97a548a, Fable review clean — supervision core+wiring+shutdown sweep verified, 111 tests green, ruff clean; private-attr supervision of safety tasks flagged for architect+Codex batch)
A7: complete (commit 8ea127b, Fable review: +pyzmq lock 26.4.0→27.1.0 (Fable fix — 26.4.0 без cp314 Windows-колёс убил бы lock-install), CI 3.13→3.14, drift gate 5 passed; CI-прогон Actions = проверка при пуше; pre-existing: unmocked Ollama call in test_experiment (env gap, flagged))
A3: complete (commit 8a3e7b9, Fable review clean — dispatch-side done, 67 tests green; GAP найден Fable-верификацией: alarm_fired не пересекает границу процесса, звукового потребителя в GUI нет → дозадача A3b (ring buffer + REQ recent_alarms + GUI beep); bridge-restart silent path в launcher — отмечено, Codex batch)
2026-07-09 ~01:2x RATE-LIMIT EVENT: A3b agent (sound carrier: ring buffer + REQ recent_alarms + GUI beep) killed mid-edit by session limit (resets 3:40 MSK). Partial engine.py edits (+81 строка, unverified) RESET — tree clean at 8a3e7b9 (A3 committed). RESUME PLAN: after ~3:40 re-dispatch A3b (Sonnet, same brief: engine ring buffer + REQ recent_alarms since_seq + GUI poll/beep + FAULT_LATCHED repeating beep) → Fable review+commit → PHASE A GATE: detached full suite (uv run pytest tests/ -q) + Codex gpt-5.5 high batch over master..HEAD diff → ledger gate entry → then B1||B2 (Sonnet, engine.py serialized). Bench items parked (A1b trip-test, A8 hw, lab checklist).
A3b: complete (commit 4589d9f, Fable review clean — chokepoint+supervised feed+restart-rebaseline verified, 33 new tests, battery 67 green, ruff clean). PHASE A SOFTWARE-COMPLETE (9 commits). Opening PHASE A GATE: detached full suite + Codex batch.
PHASE A GATE LAUNCHED: suite → full_suite_phaseA.log (bg), Codex gpt-5.5 high → codex_phaseA_gate.md (bg, prompt codex_phaseA_prompt.md, diff phaseA_diff.patch 3366 строк). Double-green → gate entry + B1/B2 dispatch; FAIL → fix wave (Sonnet) → re-run.
PHASE A GATE: Codex verdict FAIL — 1 CRIT (locked-DB ломает persistence-first: publish непpersisted батча, scheduler гейтится только на is_disk_full), 1 HIGH (stale singleShot рестарта после ручного рестарта → _engine_external=True → shutdown оставляет engine живым; механизм подтверждён в исходнике), 2 MED (lifetime-счётчик надзора false-латчит FAULT на разреженных транзиентах; readback-fail после run() оставляет firmware armed при _wdog_armed=False — сюрпризный kill без петов). Все 4 REAL. Suite killed (moot). Fixer F1-F4 dispatched (Sonnet, impl_gatefixA.md). Verified-OK list Codex: verified-OFF, A10 interleaving, re-entrant restart safety-петель, REP-socket на мусорном since_seq, GUI worker lifecycle, banner recovery, executor I/O, shutdown ordering.
Gate fix wave: committed (8f9f580) — F1 CRIT persistence-first (last_batch_dropped gate, оба брокера), F2 HIGH stale-shot guard, F3 MED consecutive counter (reset ≥300с healthy run), F4 MED best-effort disarm после run(). RED→GREEN на всех, 35+7+9+45 targeted green, ruff clean. Гейт перезапущен: authoritative suite (full_suite_phaseA.log) + Codex re-check (codex_phaseA_recheck.md). Pre-existing env gap: test_experiment Ollama-сеть блокируется в песочнице агентов (не наша регрессия).
Codex re-check: F2 CLOSED, F3 CLOSED, F1 PARTIAL (CRIT residual: shared last_batch_dropped флаг гоняется между конкурентными poll-тасками — нужен per-call return), F4 PARTIAL (MED residual: run_issued после write — неоднозначный отказ write пропускает disarm), +LOW (bool vs generation token в рестарте — RESIDUAL ACCEPTED: старый выстрел лишь съедает backoff-слот, engine всё равно рестартует, безопасная сторона). Suite killed (moot). Микро-фиксер R1/R2 dispatched (impl_gatefixA2.md).
2026-07-09 PROTOCOL UPDATE (Vladimir): 'fan out subagents in parallel, not in sequence' — параллелизм максимальный, сериализация только на реальных файловых конфликтах. DISPATCHED в параллель к R1/R2: B2 (Sonnet, engine.py+alarm v1 deletion — engine.py его) | B4 (Sonnet, gui/shell/overlays base panel). B1 и B5 ждут только B2 (конфликт по engine.py imports). Phase A close-suite побежит в отдельном git worktree на committed SHA (чистый от B-правок).
R1/R2: committed (8fbecb9) — persistence как per-call return (shared flag удалён), run_issued до write; RED→GREEN оба, 81+71 green, ruff clean; +pre-existing тестовый капкан substring fail_on исправлен. GATE CLOSE запущен: authoritative suite в изолированном worktree .worktrees/gateA @8fbecb9 (чист от B-правок) + Codex final confirm (codex_phaseA_final.md). B2/B4 продолжают параллельно.
Codex final confirm: F1 CLOSED, F4 CLOSED, PASS; +LOW (deprecated on_readings игнорировал bool) — исправлено Fable напрямую (commit 15828e6, 15 tests green). Гейт фазы A ждёт только worktree-suite.
B4: complete (commit b7cf4a3, Fable review clean — честный survey, sound-hooks отклонены как спекуляция, 206 battery green; остальные панели = mechanical follow-up)
ЛОВУШКА (урок): B2-агент сделал git rm (staged) — git add+commit подмёл чужие staged-удаления в B4-коммит (77cfb6b, битое дерево: engine.py ссылался на удалённый alarm.py). Исправлено reset --soft + переcommit b7cf4a3 (только 6 файлов B4). Правило дальше: коммитить формой git commit -- <paths> при параллельных агентах; агентам повторить запрет staging.
B2: complete (commit a1b3375, Fable review: канальные фиксы сверены с драйвером/DiskMonitor/instruments.yaml — v2-правила теперь реально матчатся; alarm_count gap закрыт; 233+128 green, boot OK; GUI v1-карточка + telegram.py dead code → follow-up)
B2: committed a1b3375 (после amend опечатки). DISPATCHED параллельно: B1 (Sonnet, извлечение Гемма+RAG в отдельный процесс — engine.py/launcher.py его) | B5 (Sonnet, replay-переименование, engine.py/launcher.py ЗАПРЕЩЕНЫ — координаторский патч в отчёте). B3 (декомпозиция _run_engine) — после B1. Worktree-suite @8fbecb9 ещё бежит (CPU-контеншн от параллельных прогонов).
PHASE A GATE CLOSED: suite 3716 passed / 11 skipped / 0 failed @8fbecb9 (isolated worktree, 26.5 мин), Codex: initial FAIL (1C/1H/2M) → fix wave 8f9f580 → re-check (F2/F3 CLOSED, F1/F4 PARTIAL) → R-wave 8fbecb9 → final PASS (F1/F4 CLOSED, +LOW fixed 15828e6). Осталось bench-parked: A1(b) trip-test, A8 hw-прогоны, lab checklist — Trust Gate на Phase C держится.
B5: complete (commit см. выше, Fable review clean — broker_replay.py, zero координаторских патчей, 206 тестов green)
B1: агент умер на старте от session limit (reset 14:30 MSK), правок нет — re-dispatch.
2026-07-09 ~15:5x FAN-OUT расширен по вопросу Владимира: пять параллельных агентов — B1 (extraction, in flight) + D5 (shifts.yaml wire-or-delete) + D4+soak (nightly replay-regression + bounded mock soak, новые workflow-файлы) + D3 (cross-experiment analytics backend+CLI) + E2 (quickstart + docs freshness gate + troubleshooting). Все файл-дизъюнктны с B1 (engine.py/launcher.py/agents только у B1; main.yml никто не трогает). B3 остаётся за B1; C bench-blocked; D2 ждёт B1 (agents/); E4 ждёт B1 (zmq_bridge).
D5: complete (commit b70df27, Fable review clean — DELETE выбран верно, живой assistant-путь не тронут; 53 green)
D3: complete (commit 612aa63, Fable review clean — честные non-derivables, pyproject-строка выделена из B1-контаминации patch-стейджингом; 23 green)
E2: complete (commit 06abe23, Fable review clean — gate поймал реальную гниль на первом прогоне; follow-ups: README-нарратив после B1, RAG-ингест новых доков, design-system staleness)
D4+soak: complete (commit eab1340, Fable review clean — golden доказан инъекцией, soak локально прогнан; ВНИМАНИЕ Владимиру: mock-строки записались в реальный data/data_2026-07-09.db (~15:59-16:09, gitignored) — решить, чистить ли)
2026-07-09 ~18:00 MSK HANDOFF EVENT (Vladimir's limits nearly out): loop STOPPED, coordination handed to next Fable. Wave died on session limit (reset 20:10 MSK): E4(proto ver, near-complete), B3(engine decomp, substantial+UNVERIFIED, impl_b3.md progress-log EMPTY), E1(first-run wizard, partial), D2(escalation copilot, ZERO edits). TREE LEFT DIRTY on purpose — next Fable salvages-or-resets per HANDOFF_CURRENT_STATE.md. State: Phase A COMPLETE+GATE PASSED (bench A1b/A8/checklist PARKED); Phase B 4/5 committed (B3 dirty, gates Phase B); Phase D 3/5 (D1/D2 open); Phase E 1/4 (E1/E4 dirty, E3 deferred); Phase C fully Trust-Gate-blocked. Full snapshot: scratchpad/montana/HANDOFF_CURRENT_STATE.md.
2026-07-09 NEW COORDINATOR RECON: live branch/head/dirty tree matched handoff exactly. Native Terra reviewed B3; native Luna reviewed E1/E4; GLM-5.2 + Claude Opus 4.8 supplied advisory passes. All three dirty items classified FIX-THEN-SALVAGE, not reset. Advisor findings were verified locally; GLM's initial B3 missing-argument claim was false because the old closures were still live, while its later process-boundary warning was real.
E4 SALVAGED + COMMITTED b1bf899: explicit engine/assistant identity independent of address, assistant protocol discovery routing, additive proto field across REP replies, REST version endpoint, client warn-once, docs/CHANGELOG and compatibility/error-path tests. Independent final review PASS; 69 focused + 100 adjacent regression tests, plus authoring lane 633 expanded pass; Ruff/compile/diff/hygiene clean. No push/tag.
B3 STRUCTURAL SLICE SALVAGED + COMMITTED 7fa3f11: `_run_engine` now has zero nested defs/lambdas; 13 runtime factories wired from engine_wiring; module-level command/safety/interlock/signal contexts; durable TaskSupervisor integration tests. Independent Terra PASS: 195 focused + 1584 broad pass, live mock boot/SIGINT teardown clean, Ruff/compile/AST/reverse-cycle/diff clean. IMPORTANT: Phase B remains OPEN — engine still owns CompositionPhotoHandler, PeriodicReporter and ReportGenerator. No lazy-import gate gaming. Report/photo process isolation is a separate architecture item.
E1 SALVAGED + COMMITTED ec7b42a: lock-before-wizard, nonblocking tray start, forced-local preservation+backup confirmation, strict safety validation, secret masking/0600, and versioned crash transaction with durable recovery snapshots before engine startup. Initial independent review reproduced a done+pending crash hole; second author fixed it; original author re-verified PASS across every transaction boundary. 100 focused + 90 expanded + 21 boundary-detail pass; static gates clean. Protected frozen install still needs a shared writable OS state/config root and installer ACL policy; current path fails safely without partial mutation. No push/tag.
ARCHITECTURE DECISION IN PROGRESS: prefer subtraction over literal score-chasing. Keep composition-photo confirmation with the engine-owned Telegram/operator state for now; do not weaken the read-only assistant boundary. Design one crash-tolerant report worker for PeriodicReporter/ReportGenerator with durable queued jobs and explicit completion/error semantics. Writable frozen config becomes a Phase-E packaging prerequisite (two-root base/write overlay), not a reason to hide E1 safe failure.
POST-SALVAGE CLEAN-SHA CHECKPOINT @ec7b42a: isolated detached worktree full suite 3857 passed / 11 skipped / 1 deselected / 0 failed in 516.89s. This validates commits b1bf899 + 7fa3f11 + ec7b42a together before report-boundary work; it is NOT the Phase-B close gate because report-generation isolation remains open.
REPORT-BOUNDARY ARBITRATION: Terra's initial fourth-worker/report_jobs.db design was challenged by Opus 4.8 and GLM-5.2. Final accepted hybrid (scratchpad/montana/REPORT_WORKER_DESIGN.md): no fourth daemon/DB; existing supervised assistant gains report-only coordination independent of LLM config; all matplotlib/docx/report rendering runs in bounded ephemeral children; per-experiment immutable generations + atomic current manifest/state; one bounded periodic_state.json for Telegram dedup/delivery ambiguity; persistent kernel-lock inodes; whole process-tree timeout cleanup. CompositionPhotoHandler stays engine-side as explicit Telegram-glue exception. Implementation split H0/H1→H2→H3; Phase B remains open through H4/full-suite/frozen/72h gates.
REPORT H0/H1 COMMITTED 9ce834e: manual `experiment_generate_report` now runs in a bounded ephemeral child; immutable generation directories publish through a manifest-last atomic selector; path/root/symlink jails, bounded input/output hashing, durable file+directory flushes, persisted owner fencing, stable-inode locks, exact result schemas, engine lazy-import boundary, manifest-first archive resolution, and development/frozen dispatch are covered. Terra final PASS; Luna 29/29 compatibility PASS + commit-hygiene PASS. Final repository suite: 3930 passed / 7 skipped / 1 deselected / 0 failed in 498.24s; post-hygiene focused gate 213 passed and final textual delta 28 passed. Real Windows ONEDIR `--mode=report-render` smoke remains OPEN and blocks final platform/H1 sign-off, but not this code commit. No push/tag.
2026-07-10 WATCHDOG TRUTH PATCH (uncommitted): primary 2600B manual + GLM-5.2 + Opus 4.8 + hardware deep research invalidate the old autonomous timer implementation. Lua v3 deletes invalid timer/action calls and explicitly reports autonomous=0; required now refuses v3 before activation, best_effort visibly runs late-pet-only. Public claims and 5 W language corrected; A1(b) reopened as architecture+physical proof; A8 split a-e with evidence expiry and Phase C still blocked. Timeout config now rejects bool/string/NaN/Inf/out-of-range and documents os.time one-second + strict `>` boundary. Final focused/adjacent battery 186 pass + 4 hardware skips; Ruff/compile/YAML/diff/trace clean. Report: exec/impl_watchdog_truth.md. No stage/commit/push/tag.
2026-07-10 WATCHDOG POST-REVIEW REPAIR (uncommitted): Terra exact-parser/evidence findings and Opus stale-latch recovery lockout reproduced and fixed. Version=exact finite 3; all flags exact finite 0/1; only literal TSP nil is fresh; malformed latch never uploads. Shutdown is global. Pre-existing/in-session trip evidence sets host pending, blocks RUN before monitor, and is consumed only by operator reason + repeated verified both-output OFF + exact ack/reactivation readback; failed ack remains FAULT with visible reconnect/mode action. Power-cycle nil uses the same audited v3 re-upload path. PROJECT_STATUS/A8 and categorical 2604B OE-not-safety-interlock docs corrected. Final battery 254 pass + 4 hardware skips; no stage/commit/push/tag.
2026-07-10 WATCHDOG TRUTH COMMITTED f9025b1: source-level Opus 4.8 PASS (0 P0/P1); GLM-5.2 requested exact code and its later timeout/update findings were locally rejected as scope/semantic mismatches. Post-commit gate 254 passed + 4 hardware skips. A8c-A8e remain physical and Phase C stays blocked. No push/tag.
2026-07-10 REPORT H2 COMMITTED 559aa72: automatic terminal reports now reconcile from durable metadata in the report-only assistant, independent of LLM availability, through bounded children, strict state/cursor contracts, persistent kernel locks, immutable generations, poison/backoff and manifest repair. Opus 4.8 source-level PASS (0 P0/P1); GLM-5.2 design PASS with locally rejected PID/SQLite assumptions. Post-commit focused gate 180 passed. No push/tag.
POST-H2 CLEAN-SHA CHECKPOINT @559aa72: unrestricted full suite 4106 passed / 7 skipped / 1 deselected / 0 failed in 495.18s; Ruff/compile/YAML/diff gates clean. This closes the Linux/full-suite evidence for f9025b1+559aa72, not Windows ONEDIR, real process-death, 72h soak, or physical A8c-A8e.
PRE-H3 AUTHORITY REORDER: native Terra/Luna both reproduced stale canonical GUI fallback and implicit exhausted-poison reset. One isolated patch before H3 will add four-way manifest authority plus exact confirmed/audited force CAS; H2 automatic policy stays unchanged. Opus rates these H4/low severity but agrees the patch is safe; GLM/native reviews prefer early closure, matching the closest-to-perfect directive.
PRE-H3 AUTHORITY COMMITTED 686cdbc: four-way manifest/legacy/none/invalid truth, click-time manifest revalidation, unknown payload fail-closed, exact force=true/operator/context propagation, experiment-lock transition fence, immutable before/after audit, visible completion-audit failure, prior-manifest preservation, and disconnected/selection-safe GUI confirmation. Initial Terra/Luna verification found 7 combined P1s; 5 repaired, filesystem-CAS injection withdrawn after every production state writer was proven to hold the same kernel lock, and the stray GUI expression removed. Final Terra PASS + Luna PASS + Opus 4.8 PASS; GLM findings locally checked with no surviving blocker. Focused 285 + H2/authority 220 passed; exact dirty-tree full suite 4159 passed / 7 skipped / 1 deselected in 494.91s. No push/tag.
H3 BOUNDED HYDRATION DESIGN PASS: Terra design underwent three Luna FAIL waves before final PASS. Closed temp-B-tree SQLite sort, pre-ParquetFile footer allocation, missing path containment, discovery/timestamp/duplicate/completeness precision, and unbounded SQLite TEXT materialization via SQLITE_LIMIT_LENGTH. Final plan: keyset SQLite, capped same-handle Parquet batches/footer, exact hot/cold authority, peak-intermediate tests. No tracked H3 code yet.
H3.0 LEGACY CHARACTERIZATION COMMITTED 1792024: semantic matplotlib/Agg oracles capture layout, ordering, pressure filtering/limits, alarm line styling, caption behavior, and figure cleanup without pixels/fonts/hashes. Luna's first FAIL caught a normal-colour assertion, savefig leak, and weak endpoint oracle; all repaired. Final 9 passed under warnings-as-errors. Two legacy defects are explicitly not normative: chart/caption can observe different alarm snapshots, and caption uses an unsafe blind HTML slice. No push/tag.
H3.1 CONTRACTS IN ADVERSARIAL REPAIR (uncommitted): initial 66-test author pass was rejected by Terra for hostile YAML escapes, unsafe/absorbing transition edges, weak high-water/unknown authority, swallowed fsync, mutation races, and duplicate YAML keys. First repair reached 86 tests and closed those probes, but independent re-verification found a deeper P0: exact current fences still allowed fabricated candidate documents, including DELIVERING->READY resend authority and artifact/destination rebinding. A closed durable current->candidate transition relation plus hostile state-JSON totality is now the active repair gate. Do not stage/commit yet.
H3.2 BOUNDED HYDRATION/PROJECTIONS NATIVE PASS (uncommitted): first 21-test author pass was rejected for ten real P1s (wire/snapshot shape, false alarm completeness, channel lifetime growth, discovery intermediate/duplicates, midnight boundary, nullable Parquet, import leak, index race). Three further re-verifier P1s were found and repaired: large-budget >64 live channels, overlap-prone alarm snapshot cuts, and hot->cold index-publish/unlink false-complete authority. Final independent Terra PASS: exact 16 + focused 41 -W error + expanded 352; Ruff/compile/diff clean. External GLM/Opus implementation review and commit remain pending; no stage/commit/push/tag.
H3.3 PROTOCOL PREP: Luna rejected the otherwise-sound blueprint as insufficiently exact at the frozen input boundary. Accepted delta in exec/h3_3_protocol_resolution.md defines a stdlib-only closed parser, frozen display time/caps/errors, minimal alarm schema, one-instrument/unit/null series rules, token-safe HTML truncation, semantic-not-pixel parity, and immutable READY artifact retry identity. Terra review is in progress. GLM call was attempted but Codex external-execution quota is blocked until 11:05 MSK; preserve as a pending gate, do not bypass.
H3.1 CONTRACTS NATIVE PASS (uncommitted): closed durable current->candidate replay authority, strict duplicate/hostile <=64 KiB YAML totality, exact typed state fences, OLD-DELIVERING-bound unknown evidence, strict atomic file+directory fsync, and bounded hostile JSON now pass independent Terra authority review with 0 P0/P1/P2. Gates: 139 periodic + 180 combined -W error + 1,329 mutation/edge/hostile probes; Ruff/compile/import/diff clean. External GLM/Opus implementation review remains mandatory before commit.
H3.3 CHILD/RENDER PROTOCOL NATIVE PASS (uncommitted): stdlib closed input/result boundaries, owner+RENDERING fences, final-generation recovery/fsync, nofollow/hardlink/replacement persistent locks, bounded quarantine, exact argv authority, semantic renderer parity and process cleanup pass independent Terra and Luna with 0 P0/P1. Root integrated gate 334 passed; author/independent expanded gates 362/343. Real Windows frozen render remains H4. External GLM/Opus review remains mandatory before commit.
H3.4 OUTBOUND TELEGRAM DESIGN PASS (implementation parked): Luna closed JSON integer/message-id, timeout-field and fixed error-vocabulary exactness. Terra closed full PNG CRC/aspect/IEND validation, DummyCookieJar, and the send/close race via a synchronous pre-await send claim, result-free completion Future, and one shielded close task. No runtime wiring. Implementation waits until H3.1 external review and separate commit because periodic_config.py overlaps.
OFFLINE PRE-EXTERNAL GATE: repository Ruff + compileall clean. Sandbox suite reached 1,738 passed / 1 skipped / 1 deselected before only loopback-bind tests failed under EPERM; run stopped after 12 failures + 5 setup errors, all at socket.bind. Unrestricted full suite remains queued for the 11:05 MSK execution gate.
H3.1 COMMITTED 36dabde: strict periodic config/state authority plus durable frozen display_time. Native Terra final PASS (209 display/state/child + prior hostile transition matrix); GLM-5.2 body found no P0/P1 despite contradictory raw FAIL label; Opus 4.8 PASS. 151 periodic root rerun; no push/tag.
H3.2 COMMITTED 691bbaa: bounded hot/cold hydration, live/alarm projections, alarm_cleared relay. GLM raised four P0/P1 candidates; local EXPLAIN/storage/schema checks rejected all, and Opus 4.8 independently PASSed with no P0/P1. Root focused 41 -W error; no push/tag.
H3.3 COMMITTED 1d6b669: periodic child/renderer protocol plus persistent-lock hardening and public fenced artifact reader. Native Luna reproduced one real dirfd raw-OSError escape; Terra normalized every ordinary fault and cleanup path, Luna reverified CLOSED with real fd/fault harness. GLM candidates rejected locally; Opus 4.8 final repaired-source PASS. Root 306 -W error; no push/tag.
H3.6 ATOMIC CUTOVER DESIGN PASS / PRODUCTION NO-GO: production completeness requires engine-session + global sequence on readings/events/barrier, Queue.join/task_done drain under the same PUB send lock, DataBroker drop baseline, and canonical active-alarm snapshot hash matched by bounded 64 KiB REQ snapshot+barrier before every freeze. H3.5 stays unwired pure-DI; shared ZMQ/EngineQueryClient cannot authorize completeness. Real loopback/multiprocess/restart/replay/frozen/fault gates remain mandatory before legacy sender removal.
H3.4 COMMITTED 59d953c: strict unwired outbound Telegram client, exact token grammar, closed four-outcome certainty and bounded response/PNG/multipart/secret lifecycle. Native Luna found and closed explicit `parameters:null` schema defect; final 129 sender tests. GLM-5.2 PASS; Opus 4.8 PASS; real FormData/path P2 oracles added. Exact locked aiohttp 3.13.5 sender gate 129 passed; full config/secret locked gate 192 before the final oracle. No runtime wiring, real Telegram, push, or tag.
POST-H3.4 EXACT CLEAN-SHA CHECKPOINT @59d953c: detached `/tmp/cryodaq-h34-gate` with its `src` explicitly first on PYTHONPATH (preventing editable-main contamination) passed 4617 / 11 skipped / 1 deselected / 0 failed in 491.03s. An earlier 4617-pass detached run was rejected as authoritative because warning paths revealed the editable venv imported main-workspace source; only the forced-PYTHONPATH rerun is accepted.
H3.6 DESIGN FINAL NATIVE/GLM/OPUS PASS, PRODUCTION STILL NO-GO: amended with explicit bounded async queue drain, publisher failure count, alarm mutation revision + post-send stability check, mandatory PyInstaller ONEDIR smoke, durable domain-wide H3 leader heartbeat with launcher monotonic freshness, exact H3.2 `(timestamp,instrument_id,channel)` live-priority overlap identity, and independent replay-off gate even when LLM remains alive. Terra final re-review PASS. Implementation waits on accepted H3.5 plus real gates.
2026-07-10 H3.5 NATIVE FREEZE: pure-DI unwired coordinator/supervisor converged after authority repair waves covering repeatable seals, heartbeat truth, non-ready-before-orderly-leader-release, stop/admission races, deterministic immutable-input reuse bindings, exact recovery, and repeated-cancellation cleanup. Terra final PASS with no P0/P1; author gates 71 focused `-W error`, 525 broad H3, and 84 H2/legacy/inbound compatibility; root gates 71 focused + 601 adjacent H3/reporting, Ruff/compile/import/diff clean. Luna compatibility review remains in flight; no stage/commit/push/tag.
2026-07-10 H3.5 EXTERNAL GATE DEFERRED: sandboxed GLM-5.2 fetch failed; required unrestricted retry was rejected by the Codex execution-credit gate with reset stated as 16:50 MSK. Claude Opus 4.8 CLI independently reported `Not logged in`. Do not bypass either gate; retry on a later heartbeat after access recovers. H3.5 remains uncommitted.
2026-07-10 H3.6 DESIGN CORRECTION: `DataBroker.DROP_OLDEST` currently removes a queued item without `task_done()`. Because H3.6 barriers rely on bounded `Queue.join()`, implementation must pair every dropped-oldest `get_nowait()` with `task_done()` and prove overflow/drain/join exactness; otherwise one historical overflow permanently poisons all future barriers.
2026-07-10 H3.5 FINAL NATIVE PASS / EXTERNAL HOLD: Luna's compatibility pass found and closed nine further long-uptime/concurrency defects after the initial Terra freeze: render and delivery heartbeat stalls, repeated startup-cleanup cancellation, full-ledger/newer-slot false-ready, unbounded retry memoization, initial-loader task latch, source-failure/health-load false-ready, corrupt invalid-config leadership retention, and cleanup-error/nonready ordering. Delivery heartbeat is serialized with every post-send state settlement to prevent stale CAS overwrite while proving exactly one send. Final exact hashes recorded in `verify_h3_5_coordinator_luna.md`; Terra/Luna/root gates: 82 focused `-W error`, Luna 357 compatibility, root 612 adjacent `-W error`, Ruff/compile/import/diff clean. Only the five intended untracked files remain. H3.5 is structurally accepted but MUST NOT commit until pending GLM-5.2 and Opus 4.8 reviews run after external access recovers.
2026-07-10 H3.5 ALARM-CONVERGENCE AMENDMENT / FINAL NATIVE PASS: H3.6 preflight exposed that strict snapshot/seal revision equality rejected a safe trigger+clear round trip that restored the identical canonical active-set token. H3.5 now accepts only non-null `snapshot_revision <= seal_revision` plus exact token equality and continuous cuts; lower seal revision/token/session discontinuity remains incomplete. Final production hash `1bab09ad42cb26feb0b3bda6bc307c9809d67ee537bc311e7730165a7598b7e5`; Terra 84 focused + 538 broad + 84 compatibility, Luna 84 focused + 357 compatibility, root 84 focused + 614 adjacent, all `-W error` and static gates green. External hold remains.
2026-07-10 H3.5 ALLOWED-IDLE AMENDMENT / FINAL NATIVE FREEZE: H3.6 preflight also exposed ambiguous normal return and missed hot enable when periodic mode was allowed but config unrequested. Exact-off remains the sole pre-config return; allowed-unrequested now stays alive in bounded zero-state/lock/runtime polling and supports enable→disable (nonready before release)→reenable without assistant restart. Root caught and repaired a test-only private-heartbeat concurrency race; affected probes pass 40/40 across ten repeats. Final production hash `897defcaeee744647acb9a4fdb9381bac773640ed973c8b3c4526defdba69f3b`; Terra 85 focused + 539 broad + 84 compatibility, Luna 85 focused + 357 compatibility, root 85 focused + 615 adjacent, static gates green. Exactly five intended untracked files; external hold remains.
2026-07-10 H3.6 PREFLIGHT COMPLETE / DESIGN AMENDED: Terra found seven P0/P1 mismatches and two integration constraints before implementation. Normative corrections now cover DROP_OLDEST unfinished accounting; persistence-authority bit/filter for mixed broker readings; required REP `proto`; alarm convergence inequality and detached AlarmEvent copies; whole barrier deadline/cancellation and under-lock publisher recheck; allowed-idle supervisor polling; replay-compatible publisher API; explicit ONEDIR inclusion. Exact A-I slices and atomic no-dual-send boundary: `exec/h3_6_preflight_terra.md`. Production remains NO-GO until implementation plus real loopback/multiprocess/restart/replay/frozen/full-suite/external gates.
2026-07-10 H3.6A BROKER NATIVE PASS / UNCOMMITTED: `DataBroker` now pairs every dropped-oldest queue item with exact `task_done()` and carries an exact default-false persistence-authority bit on detached Reading/metadata copies without changing queue item type. Luna found and closed a post-enqueue metadata-forgery path by requiring detach even for false. Terra 36 focused + 139 affected compatibility; root 36 focused; Ruff/format/compile/diff green. Broad core diagnostic reached 962 passes before 20 loopback tests hit managed-sandbox bind EPERM. Only `core/broker.py` and `test_broker.py` tracked diffs plus five frozen H3.5 untracked files; no stage/commit/push/tag. External implementation review remains mandatory.
2026-07-10 H3.5 COMMITTED 5c79e32: GLM-5.2 PASS and Claude Opus 4.8 bounded source review PASS, both with no P0/P1. External P2 notes were locally verified as intentional/fenced: operator-local frozen caption time, bounded H3.6 alarm adapters, SecretStr equality, independent H3.1 full-ledger capacity, fail-honest reload health, and serial transaction ownership. Final pre-commit gate 85 focused `-W error`, hash `897defca...a69f3b`; exact five-file commit with H3.6A broker changes left unstaged. No push/tag.
POST-H3.5 EXACT CLEAN-SHA CHECKPOINT @5c79e32: detached `/tmp/cryodaq-h35-gate` with its own `src` forced first on `PYTHONPATH` passed 4702 / 11 skipped / 1 deselected / 0 failed in 495.17s. Initial full run had one unrelated archive-panel XLSX failure after 4701 passes; the exact test then passed isolated, the full 55-test archive-panel module passed, and the authoritative full rerun passed. Classified non-reproducing suite-order flake, not H3.5 regression. No push/tag.
2026-07-10 H3.6A COMMITTED 6176158: GLM-5.2 PASS and Claude Opus 4.8 PASS with no P0/P1. Opus/Luna P2 hardening exposed a public integration symbol for the reserved marker and gave each filter a private sanitized Reading view while preserving one shared normalized queued Reading. Final 38 focused + 139 affected compatibility; root focused/static green; broker hash `1e9e50a0...`, tests `b5031594...`. Exact two-file commit, clean worktree, no push/tag. H3.6B canonical alarm authority is next.
2026-07-10 H3.6B COMMITTED fca35c2: AlarmStateManager now owns exact active-state revision across normal/diagnostic/ack mutations, detaches every input/output alias, and emits a bounded privacy-minimal canonical active mapping/token. Luna found and closed UTF-8 character-vs-byte and post-dedup traversal bounds. Opus PASS/no P0/P1; its P2 cleanup removed a dead guard and suppressed hostile cause chains. GLM's four raw blockers were locally rejected as contradicted by exact code/tests. Final 79 focused + 255 expanded `-W error`, static gates clean. Slice C must cap the complete serialized REP response, not only the 60 KiB canonical active payload. No push/tag.
2026-07-10 H3.6C NATIVE FINAL PASS / OPUS HOLD: common persistence-aware reading/event/barrier session+sequence, exact queue fence, closed proto command envelope, exact-once compact finite reply bytes, complete 60 KiB snapshot cap, replay compatibility, and no-stale-success shutdown are implemented in the exact six-file dirty scope. Final lifecycle audit found and repaired caller-cancellation swallowing, prefailed-drain cleanup bypass, and combined cancellation transformed by a drain-finally error; cleanup now settles under the send lock before cancellation/error propagation. Terra/Luna final PASS; root 73 focused/adjacent `-W error`, author 75 focused + 116 replay/ZMQ, Ruff/compile/diff green. GLM raw FAIL was preserved but all four claims were locally rejected (queue-consumer task_done ownership, query-vs-response schema, detached primary-broker marker, closed stat sampler failure). Claude Opus 4.8 session resets at 21:50 MSK; do not commit C until its bounded final public-source review passes and every plausible finding is locally verified. H3.6D starts only in disjoint new files with Luna worker / Terra verifier routing.
2026-07-10 H3.6D TERRA CONDITIONAL PASS / EXECUTION HOLD: Luna implemented the private resource-free periodic runtime and closed ephemeral engine query in exactly two new files; Terra independently reproduced and drove repairs for stale-cut generation aliasing, stop/ready cleanup races, count-only provisional growth, monitor-stop gaps, permissive marker/alarm schemas, token mismatch, msgpack duplicate keys, event authority forgery, async callback stalls, post-invalidation callbacks, public surface drift, barrier failure classification, and the 60 KiB boundary. Frozen hashes runtime `78fb84b4815...`, tests `77bf97561b5...`; 13 focused pure + 115 adjacent pass `-W error`, Ruff/compile/diff green. Six mandatory real-loopback nodes plus GLM-5.2/Opus 4.8 reviews remain blocked by the managed execution gate until 22:23 MSK. D is uncommitted; H3.6F proceeds only in disjoint bootstrap files with Luna worker / Terra verifier routing.
2026-07-10 H3.6F NATIVE PASS / EXTERNAL HOLD: assistant bootstrap now has an exact-off lazy H3 gate, independent H2/H3/optional-LLM composition, fatal unexpected H2/H3 completion, nonfatal LLM failure, and one cancellation-safe ordered teardown that settles H3 before H2 and cannot leak signal handlers or mask startup/cleanup authority. Terra reproduced constructor/start cancellation, simultaneous shutdown+critical failure, and signal-removal cleanup gaps; Luna repaired all. Frozen hashes bootstrap `23bdb4f9...`, focused `93723a28...`, H2 compatibility `92a2a2bf...`; 33 focused + 70 adjacent `-W error`, Ruff/format/compile/diff PASS. No native P0/P1/P2; GLM/Opus and atomic integration remain. H3.6G is independently implemented under Terra review; H3.6I packaging starts disjointly with Luna worker/Terra verifier.
2026-07-10 H3.6G NATIVE PASS / EXTERNAL HOLD: launcher now uses a strict live-only periodic request probe, overwrites the assistant H3 env flag on every spawn, owns zero H3 probe/monitor state in replay, and monitors domain-wide ready heartbeats by local monotonic observation. A dedicated persistent amber reporting-degraded banner/tray status is explicitly non-safety and never starts the engine alarm or changes engine restart/fault state. Terra reproduced a wall-step P1 where an unchanged future heartbeat became fresh; Luna added independent last-observed authority so wall time alone cannot refresh, future rejection does not poison corrected recovery, and nonready high-water still blocks rewind. Final hashes launcher `5efb4820...`, tests `046a47cc...`; 26 focused + 220 expanded, Ruff/compile/diff PASS, no native P0/P1/P2.
2026-07-10 H3.6I NATIVE/STATIC PASS / WINDOWS OPEN: PyInstaller now explicitly lists H3 runtime/coordinator/sender, ZMQ/msgpack/aiohttp and pyarrow closure independent of broad submodule collection; ONEDIR EXE+COLLECT, recursive freeze-support ordering, exact-on assistant import isolation, replay exact-off, periodic-only live harness, and fixed frozen self-reexec argv are pinned. Terra repaired initial structural/test gaps. Frozen hashes spec `6237223f...`, spec tests `9d34a86a...`, frozen-entry tests `ef12416b...`; 15 focused + H2/report/subprocess compatibility gates PASS. Real Windows ONEDIR execution, Job Object descendant death, and spaces/Cyrillic path evidence remain honestly OPEN. H3.6H now performs the destructive legacy owner cut to establish the atomic no-dual-send dirty-tree boundary.
2026-07-10 H3.6H NATIVE PASS / INTEGRATION REPAIR OPEN: engine legacy PeriodicReporter annotation/import+construction/start/stop/logs are deleted while TelegramCommandBot, CompositionPhotoHandler, escalation/query proxy, assistant relay, H3.6C commands/samplers, and the dead legacy module/characterization tests remain. Terra rejected fake/source-only one-owner evidence; Luna replaced it with the real production factory graph plus actual PeriodicPngSupervisor+PeriodicPngCoordinator due-slot flow using leaf fakes, proving one immutable PNG, one Telegram destination, SUCCEEDED durable state, and no legacy import/fallback. Cross-product enabled=H3 only, disabled=neither, replay LLM=H3 exact-off, readiness failure=no send/fallback. Independent 208-test affected gate + static checks PASS, no H-native P0/P1/P2. Separate cross-slice audit reproduced launcher theme `execv` orphaning the assistant and normal shutdown stopping engine before H3; Luna repair is mandatory before integrated freeze.
2026-07-10 H3.6 MULTIPROCESS/CRASH NATIVE PASS: bounded six-node multiprocess module reached Terra static CONDITIONAL PASS at `73b00d83...`, with real engine death/rebind, fresh-session old-cut rejection, callback quiescence, one leader/takeover and replay exact-off; runtime remains NOT_RUN until the 22:23 gate. Dedicated H3-CRASH-001..012 matrix was initially rejected despite 14/14 green because three claims lacked production authority. Luna repaired exact rebuilt-input fencing, immutable artifact/bytes/caption/destination binding, and true interrupted-DELIVERING handoff to a fresh coordinator. Terra final PASS/no findings at `566e2e36...`; 67 expanded pure tests plus static gates green.
2026-07-10 ASC SCALABILITY ROADMAP COMMITTED/PUSHED d5b2233: public F35 plus internal Montana B6 promote multi-lab hardware extensibility from a loose plugin idea to an acceptance-gated contract: model-free allowlisted driver registry, narrow passive/shared-bus/source/verified-OFF capabilities, public mixed-cadence bus recovery, stable channel descriptors through persistence/replay/reporting/GUI, registry-driven setup/frozen packaging, conformance kit and no-central-edit reference driver. Hazardous actuators remain explicitly reviewed, hazard-analyzed and bench-proved rather than hot-loaded. Terra first rejected missing shared-bus cadence/reset and descriptor replay authority; both amended, final PASS. Docs freshness 4 passed. Remote branch updated; no tag/release/merge.
2026-07-10 H3.6C COMMITTED/PUSHED e3a3c61: Claude Opus 4.8 returned PASS/no P0/P1 on the exact six-file public stream/engine-command scope and independently confirmed the stop/cancellation attack plus GLM dissent adjudication. Five Opus P2s were locally retained as intentional/bounded or non-production hypotheticals; disposition preserved in `external_opus_h3_6c.md`. Root exact worktree and staged-index panels both passed 74 tests with Ruff/compile/diff clean. Partial engine staging proved legacy `PeriodicReporter` variable/import/construction/start/stop remained in the C commit and only the later dirty H cut removes them, avoiding a broken intermediate owner state. Remote branch updated; no tag/release/merge.
2026-07-10 H3.6/H4 FORMATTED INTEGRATION NATIVE PASS / REAL GATES OPEN: final formatted crash matrix `566e2e36...` and six-node harness `f1636c65...` retain Terra PASS/CONDITIONAL PASS; crash 14/14, nodes4-6 18/18 including five stress batches, exact nodes1-3/all-six remain held until managed localhost execution reopens 2026-07-11 01:27 MSK. Post-format pure panels passed (runtime 22 with 7 localhost deselected, root lifecycle/H4 165, crash/lock/frozen 53, broad adjacent worker panels >500) plus Ruff/format/compile/diff. Windows production hard-kill mismatch was repaired with a hidden-child graceful sentinel and bounded terminate/kill fallback. Terra twice broke provisional path-only hardening (link following, then parent replacement TOCTOU); final frozen identity authority around create/observe closes both symlink and real-directory swaps, preserves H3->H2 cleanup, and PASSes 58 focused + 32 cutover/supervisor + 130 adversarial repetitions with no P0/P1/P2. Real Windows ONEDIR remains OPEN. Claude Code still reports `loggedIn:false`; GLM fetch is network-blocked. Final integrated external reviews and commit/push remain mandatory.
2026-07-11 H3.6/H4 INTEGRATED COMMITTED/PUSHED 026bf50: exact final delta received GLM-5.2 PASS and Claude Opus 4.8 PASS. Focused final matrix 214 passed. Detached clean-SHA worktree with its own `src` first on `PYTHONPATH` passed 4939 / 11 skipped / 1 deselected / 0 failed in 510.51s. Remote `origin/feat/montana-phase-a` updated; no tag/release/merge. Real Windows ONEDIR launcher tree, long soak, and physical gates remain open.
2026-07-11 META/F35/F36 PARALLEL CAMPAIGN: tracked canonical guidance is being restored as root `AGENTS.md` + thin `CLAUDE.md` + tool-neutral `docs/ORCHESTRATION.md`; Claude-Mem now targets ignored `.claude/claude-mem-context.md`; local Claude command shims/hook point to the canonical flow. Product-assistant `EngineQueryClient` now enforces an exact nine-action read-only allowlist before ZeroMQ creation. Terra found and closed F36.0 measurement-claim ambiguity, release-snapshot labeling drift, and design-system safety/code-precedence contradictions; final substantive guidance verdict PASS, with tracking intentionally pending staging. F35 static capability/registry foundation and F36.0 twelve-scenario evidence contract have native Terra PASS; F36.1 immutable operator models and a source stack-soak harness are in parallel Luna/Terra work. Fable/GLM/Grok final guidance reviews plus GLM/Opus F35/F36/query reviews, staging, commit, and push wait for the managed external/Git gate at 06:51 MSK. No workaround; safe local verification continues.

2026-07-11 11:18 MSK USER-REQUESTED HARD PAUSE — ALL WORK STOPPED:

- User instruction: pause immediately, update this ledger, stop all work. No implementation, review, tests, external-model calls, Git staging/commit/push, soak, CI rerun, or agent work may resume without a new explicit user request.
- Native agent state at pause: `luna_f36_2_gui_preflight` interrupted; `terra_f36_round5_verify` interrupted; `luna_soak_round5_repair` had already completed. No child agent was intentionally left running.
- Branch: `feat/montana-phase-a`.
- Reviewed local HEAD and remote `origin/feat/montana-phase-a`: exact same SHA `4f49242b8a72ee4f73f4cca87fd1677f956e29ea` (`feat(acquisition): add explicit shared-bus timing contracts`). Nothing from the dirty tree was staged, committed, or pushed for this pause.
- Reviewed/pushed commits after checkpoint `e3a3c61`: `026bf50` single-owner periodic runtime; `b70c809` capability-bound driver registry; `4d7b59d` canonical repository guidance; `9af39a8` F36.0 operator-scenario contract; `8ad1cae` canonical operator snapshot/session truth; `ff62b7c` fail-closed soak evidence foundation; `4f49242` shared-bus timing/recovery contracts.
- Exact detached clean-SHA full gate at current `4f49242`, with detached source first on `PYTHONPATH`: 5291 passed, 10 skipped, 1 deselected, 0 failed in 537.26 s.
- CURRENT CI IS RED, despite the local clean-SHA pass. GitHub Actions run `29144914439` failed on both platforms: Ubuntu failed `tests/integration/test_periodic_png_multiprocess.py::test_killed_elected_assistant_replacement_makes_one_forward_result` because supervisor shutdown reached `run()` with `_coordinator is None`; Windows hit periodic-runtime oversize test setup errors because an environment value exceeded the Windows 32767-character limit. Green Ubuntu+Windows CI on the exact final candidate SHA is an OPEN hard pre-lab gate. Do not repeat the stale roadmap claim that the current branch matrix is green; v0.64 historical CI green is release-baseline evidence only.

DIRTY WORKTREE PRESERVATION AT PAUSE — DO NOT RESET/CLEAN/CHECKOUT OR BULK-STAGE:

- Modified tracked: `PROJECT_STATUS.md`, `ROADMAP.md`, `docs/design-system/CHANGELOG.md`, `docs/design-system/MANIFEST.md`, `docs/design-system/VERSION`, `src/cryodaq/gui/zmq_client.py`, `src/cryodaq/launcher.py`.
- Untracked design/POD/navigation: `docs/design-system/cryodaq-primitives/operator-snapshot-components.md`, `docs/design-system/patterns/operator-snapshot-presentation.md`, `src/cryodaq/gui/shell/navigation.py`, `src/cryodaq/gui/shell/operator_components/**`, `src/cryodaq/gui/shell/views/operator_display.py`, `tests/gui/shell/operator_components/**`, `tests/gui/shell/test_navigation.py`, `tests/gui/shell/views/test_operator_display.py`.
- Untracked soak/lifecycle: `scripts/soak_mock_stack_runner.py`, `tests/scripts/test_soak_mock_stack_runner.py`, `tests/scripts/test_soak_mock_stack_runner_bridge_handshake.py`, `tests/test_launcher_bridge_handshake.py`.
- Untracked persistence P1A: `src/cryodaq/storage/persistence_spool.py`, `tests/storage/test_persistence_spool.py`, `tests/storage/test_persistence_spool_crash_recovery.py`.

FROZEN/REVIEW STATUS AT PAUSE:

- Canonical guidance commit `4d7b59d`: tracked `AGENTS.md`, thin `CLAUDE.md`, and tool-neutral `docs/ORCHESTRATION.md` are committed/pushed and passed exact clean-SHA tests. Fable 5 materially reviewed an earlier near-final draft and found physical-gate ambiguity, external/private transmission ambiguity, local/global instruction elevation, brittle SHA/campaign tests, version mismatch, token-count drift, and untracked canonical files; verified repairs were applied. However Fable did NOT return an exact-final PASS on committed `4d7b59d`: the prior final session reset, and the 2026-07-11 retry returned session-limit reset at 12:50 MSK. Do not claim final Fable certification. Also do not claim native task names selected GPT-5.6 Luna/Terra: the native spawn API exposed no model selector; those names were worker/verifier role labels only.
- Guidance durable workflow remains model-neutral: recon -> design -> author -> verify -> challenge -> local adjudication -> integrate -> clean-SHA proof. On resume, amend wording/reporting so differentiated model tiers are claimed only when actual model routing is exposed and verified.
- F36.2 navigation and operator snapshot atoms had native verifier PASSes before pause, but remain uncommitted and must retain exact scope separation plus external/product integration review.
- F36.2 POD worker reported 26 focused pass, 25 repeated passes, 238 combined pass, static clean, and an offscreen 1280x900 inspection. Intended worker freeze was `operator_display.py` hash `df94e6b0...`, but live file at pause hashes `b86dff7cef23154413977b09382be0e4f56e134aab6bf63bf95a5620c549e01b`; test hash remains `99ade6bf50701f3483f241e66ce2e6ce47997c57b2e56369311bdf9eab05cb4b`. Terra detected the mismatch and was interrupted before adjudication. POD has NO frozen PASS. First resume action is to identify who changed `operator_display.py`, diff `df94` evidence against live `b86`, choose and refreeze intentionally, then restart independent review. Do not restore by destructive Git operations.
- H4 runner R1/R2 had native verifier PASSes; H4 R3 architecture preflight completed in `scratchpad/montana/exec/h4_soak_runner_r3_preflight_terra.md`. Critical amendment: local ACK must not impersonate Telegram/HTTP ACCEPTED. Required split is R3a provider-neutral delivery receipt/state migration and R3b launcher-owned AF_UNIX socketpair forwarded with `pass_fds`, bounded framed PNG/caption, durable runner write+ledger before ACK, and no path/control/HTTP authority. R3 implementation was not started. Real Windows and long soaks remain open.
- Persistence transient-loss P1A worker freeze hashes at pause: source `3e051558d442566975309355f76798100f97d8a11b3ffe6c39c6958068db3078`; contract tests `be9bca3488a6909301451f7a0aff13fcb27d98710d3fabfefe9f18b43084059d`; crash tests `e3563ac36f402963c254cb29e4db8aac87c5d936267c7f743dbc35ce65d1656d`. Worker evidence: 15 focused, 173 complete storage, Ruff/format clean. Terra verdict is REJECT with two P1 and one P2 in `scratchpad/montana/exec/persistence_spool_p1a_terra.md`: (P1) `reject_pending` can evict an accepted oldest envelope and release the day guard without destination proof; (P1) ACK/reject tombstones grow physical DB indefinitely while caps count pending payload only; (P2) corrupt `row_count`/`payload_size` metadata passes reopen verification and defeats cap/health semantics. Do not integrate or commit P1A until repaired and re-reviewed. Pending batches must never gain DROP_OLDEST behavior.
- F35.1 registry and F35.2 shared-bus timing are committed/pushed. F35.3 descriptor durability through persistence/archive/replay/report/UI and its conformance/reference-driver proof remain open. Persistence P1 repair precedes overlapping persistence schema work.
- ROADMAP/PROJECT_STATUS dirty drafts are not reconciled: they still understate completed F35.1/F35.2/F36.1 and contain a stale F18 statement that the matrix/full suite is green. On resume, update them only in a reviewed coherent slice and distinguish historical release CI from current-branch CI.

HONEST OPEN GATES AT PAUSE:

1. Repair and independently re-review persistence P1A, then design/integrate P1B destination/publish authority separately.
2. Resolve/refreeze/review F36.2 POD hash mismatch; integrate navigation/atoms/POD with snapshot ingress and design-system evidence.
3. Diagnose/fix current Ubuntu and Windows GitHub CI failures; require green exact candidate SHA.
4. Finish H4 R3 delivery receipt/capability path, short runnable soak, then 12 h/72 h on appropriate isolated host(s).
5. Finish F35.3 descriptor persistence/replay/conformance and remaining lab-critical F36 work.
6. Obtain exact-final external guidance review from Fable 5 after reset; preserve earlier draft findings but do not call them final certification. GLM/Opus reviews remain required where current task scope mandates them.
7. Run genuine Windows ONEDIR workflow/Job Object/Unicode path evidence. Physical SQLite/ZMQ/LakeShore/Keithley/dummy-load/independent-final-element gates remain open and cannot be closed by software evidence.

SAFE RESUME ENTRYPOINT — ONLY AFTER EXPLICIT USER REQUEST:

1. Read root `AGENTS.md`, this final pause entry, `git status --short --branch`, and current HEAD/remote; preserve every listed dirty path.
2. Confirm no agents/external reviews/tests/soaks are still running before dispatching anything new.
3. Reconcile the POD live hash mismatch and persistence Terra REJECT before assigning repairs.
4. Use bounded workers and independent verifiers, but call them worker/verifier unless the platform exposes actual model selection. External model identity may be claimed only from the actual invoked provider/model.
5. Keep each repaired slice frozen, locally adjudicated, tested, committed, and pushed independently; no tag/release/merge. Require green CI on the exact candidate SHA before software-side lab readiness.

PAUSE STATE: work intentionally stopped. No further autonomous continuation is authorized until the user resumes it.

2026-07-11 ~21:00 MSK CAMPAIGN RESUMED BY USER — HEAVY PARALLEL:

- User explicitly resumed ordinary autonomous work and requested heavy parallelism. Native routing remains role-based because the available spawn API exposes no Luna/Terra model selector; reports must say worker/verifier unless an actual model is externally invoked and identified.
- Three disjoint lanes restarted: persistence P1A repair/review, F36.2 POD hash/adversarial repair/review, and current-SHA Ubuntu/Windows CI diagnosis/repair. Coordinator retained integration/Git authority.
- CI root cause and repair committed/pushed as `e08b6e2 fix(ci): close periodic supervisor stop races`. Ubuntu failure was a real external-stop race at two coordinator access windows; Windows failure was pytest's autogenerated 61 KiB parameter node ID being written to `PYTEST_CURRENT_TEST`, exceeding Win32's 32767-character environment limit. Production guards now stop orderly on requested stop and fail closed/re-elect on unexplained coordinator loss; explicit bounded test IDs preserve the full 60 KiB+1 parser payload. Deterministic race nodes: 60/60 across 20 repetitions; killed-leader replacement 20/20 with exactly one render/send; independent verifier 120 adjacent localhost PASS; root genuine-localhost panel 99 PASS; Ruff/format/diff clean. Opus PASS/no P0-P2. GLM's initial missing-test concern was accepted and closed; its final double-stop/leader/ZMQ-health claims were locally rejected because coordinator stop shares one idempotent stop task, `run()` releases the lock in `finally`, and the supervisor has no ZMQ health-publication path. No tag/release/merge.
- Canonical guidance exact Fable 5 review completed on frozen `4d7b59d`: CONDITIONAL PASS, no P0/P1, one P2. Fable confirmed `docs/ORCHESTRATION.md` contains no named-model/provider routing or invalid Luna/Terra assumption. P2 was an incomplete model-routing test alternation; optional raw-SHA and whitespace brittleness were also repaired. Fable re-review PASS, focused 8 tests/static clean. Follow-up committed/pushed as `6988379 test(agents): close guidance routing tripwires`. This closes the exact-final Fable guidance gap. Remaining Fable P3s (AST direct-ZMQ expansion, precedence cross-reference, product-docstring coupling, stale status metric) remain coordinator follow-ups, not blockers for the test repair.
- Current exact remote HEAD is `69883793c980f53df5afa1ce9bb9aad9608900b4`; GitHub Actions run `29163353278` is in progress. Earlier `e08b6e2` run was concurrency-cancelled by the immediate guidance push, so only the `6988379` run can close current-SHA CI.
- Persistence P1A underwent two repair/reject waves. Round 1 verifier found unproven UUID-only acknowledgement, physical-cap overshoot from rejection metadata, weak same-name schema/index verification, and inconsistent rejection counters. Round 2 closed both P1s and most P2s with typed batch+envelope receipt capability, page-aware physical caps, bounded rejection ring/counters, exact schema/index checks, and no pending eviction; verifier still rejected one P2 because live `verify_integrity()` omitted semantic-schema verification, plus one P3 overclaiming HMAC as unforgeable against arbitrary same-interpreter introspection. Round 3 worker now owns only the exact three spool files to close that final live-integrity/P3 wording gap; P1A remains uncommitted and has no destination/broker/control authority.
- F36.2 POD hash mismatch was provenance-resolved: same worker made a deliberate spacing change after visual inspection. Adversarial review then rejected three P1s: synchronous child render could tear one-cut truth; fail-closed content could be reshown; attention rows clipped detail; scenario/DS closure was overstated. Round 2 repairs closed most, but verifier found public `_owner` capability forgeability after root commit and partial-row geometry. Round 3 worker now uses root-only private owned plan/commit paths, no public owner kwarg, direct/queued/modelReset barriers, exact complete-row viewport, truthful scenario scope, dedicated POD design-system pattern, and README index. Frozen round-3 native evidence reported 259 combined + 120 adversarial; independent re-review is active. Do not stage/commit POD/DS until exact final verifier and GLM/Opus passes.
- User added a post-frontend requirement: after the full frontend/shell integration is accepted, assign a dedicated visual-QA agent to launch CryoDAQ only in isolated mock/replay mode, enumerate every reachable screen/state, capture controlled screenshots, and audit each against the design system/operator scenarios. No hardware or production data. Do not begin this before the new POD/navigation/atoms are actually integrated into the shell; component-only screenshots are insufficient.
- Safe new parallel lane opened: F35.3A-1 pure inert channel descriptor contract/parser in new `src/cryodaq/channels/**` + `tests/channels/**` only, following Terra's amended blueprint. It must not touch production config/Reading/drivers/registry/engine/scheduler/storage or activate descriptor behavior.

2026-07-11 LATE-CAMPAIGN ACCEPTANCE / DEFERRED EXTERNAL REVIEWS:
- Windows cutover CI harness repair received an independent native PASS: exact node 50/50, genuine localhost adjacent panel 70 passed, exact six-node multiprocess suite 60/60. It was committed/pushed as `3f95167 test(ci): stabilize periodic cutover scheduling`. Exact-SHA GitHub Actions status remains OPEN because the managed external-execution gate is quota-closed until 2026-07-12 01:58 Europe/Moscow; do not infer green CI from the local pass.
- Persistence P1A round 5 frozen hashes: source `6b552c62522c127925fd3be16a0d7ee30731cf561cd2b92d27993ae672f9cf14`, unit `d0d5d57807ed2381133c9889509c9b3bbf686a5789dbd3785fb8a48496536f8e`, crash/lifecycle `b4f2aa93c9082c3ed99f3852e7d80156b5daf80242224e3451c2be1a6d39cf47`. Independent native verdict PASS/no P0-P3 after 203 storage tests and 300 repeated cancellation/crash cases. GLM-5.2 final review DID NOT HAPPEN: sandbox fetch failed and the required elevated retry was denied by the managed usage gate until 01:58. Claude Opus final review DID NOT HAPPEN: Claude Code returned `Not logged in` with zero tokens. Preserve this exact scope for later external replay; user explicitly authorized continued native acceptance meanwhile.
- F35.3A-1 pure inert descriptor contract final native PASS/no P0-P3 after identifier repair. Frozen hashes include `descriptors.py` `e267371f3fd5e8f78725d1fd7997bce51bcbaee2f65eb4879d57499200658976`, `config.py` `6f31e6e22cce9254af11c24f0807a356e34519ee18c29c09af4ab4d787798ad7`, and descriptor tests `4824f49be737239930584ae3fef51242fc4feab0a875df216cc00671b0769d2d`; full frozen six-file hashes are in the verifier report. Evidence: 2,247 test executions, static/import inertness clean. GLM/Opus reviews are deferred under the same currently confirmed unavailable external gates; exact hashes must be replayed later, not silently treated as externally certified.
- F36.2 POD runtime final native review has no P0-P2; the final documentation inventory follow-up now has PASS/no P0-P3 with 127 relevant tests. Runtime/test hashes remain `5e629eeebf8408e5e29faa75e168c31a9dac0c6b748c9d577efd48460aec2f68` / `6a117b0d2b9f296808fbf415b6413b717f528f736849d5ed7afd22b662e06afd`; README final hash `6faea56cda66016c81603c2bec7118d326fd0bb5043d3c0f81b818b345edc3c1`. Full operator-shell integration, external replay, commit/push, and post-integration every-screen mock/replay screenshots remain open.

2026-07-12 F36 S1 SNAPSHOT INGRESS PREFLIGHT COMPLETE / IMPLEMENTATION DEFERRED:
- Read-only architecture audit froze `scratchpad/montana/exec/operator_snapshot_ingress_preflight.md` at SHA-256 `e55d4ea8c26c9a0732c84adc3e653430b681ed8eb7d83792929df20c6be3944e`. No active source, bridge, GUI, or shell file was edited.
- The committed neutral v1 protocol and single-owner GUI store are ready, but a truthful live producer is not: readiness, plant-health, experiment, and data-integrity authorities still need typed immutable engine adapters; F36.3 durable attention/cooldown and F36.4/F36.5 infrastructure/support authorities are absent. Activating now would force GUI aggregation, private-state reads, or optimistic placeholders, so implementation is postponed rather than falsifying a complete coherent cut.
- Accepted design: one event-loop backend composer owns the complete revision and stable leadership source; compose all eight detached summaries without an intervening await, allocate revision only after successful validation, then publish at <=2 Hz. Replay uses the identical contract with `SnapshotMode.REPLAY`; no GUI synthesis.
- Transport design: dedicated `operator_snapshot` PUB topic on the existing sole `ZMQPublisher` socket/send lock; strict bounded two-frame codec; dedicated capacity-2 newest-cut subprocess queue; separate GUI decode/drain and monotonic snapshot health; malformed/oversized frames never enter `OperatorSnapshotStore`. Reading heartbeat, reading-flow health, and snapshot-flow health remain independent. Snapshot failure only degrades presentation and never triggers control/remediation.
- Proposed order is pure frame codec, typed backend authority adapters, producer, publisher/lifecycle, subprocess/GUI ingress, one shell store, replay parity, then operator/performance/localhost/spawn/full/static gates and only afterward mock/replay screenshots. Real Windows and physical gates remain open.

2026-07-12 CONTINUOUS CAMPAIGN CHECKPOINT:
- Persistence P1A native-reviewed slice committed/pushed as `836ac80 feat(storage): add bounded persistence spool`. External GLM-5.2/Opus review remains explicitly deferred as recorded above; do not call it externally certified.
- F35.3A-1/A-2 inert descriptor and persistence-envelope contracts passed independent final reviews. A-2 initially failed aliasing review, then reconstructed/owned exact descriptors and normalized corrupted/missing slots; final 131 tests + 2,620 repeated executions PASS/no P0-P3. Commit is in progress after this ledger point; actual SHA must be appended after Git hook completion.
- H4 R1/R2 inherited bridge repair passed independent review after closing ambient inheritable-FD P2: both pipe ends remain non-inheritable, intended child receives only via `pass_fds`, unintended `close_fds=False` child does not. 180 combined + 1,150 repeated boundary tests PASS; R3 activation remains fused and R3a/R3b open.
- Exact-SHA CI run `29164529529` for `3f95167` is NOT green: Windows failed the real supervisor/coordinator cutover again and Ubuntu remained stuck for hours. Completed Windows job log proved a production cross-platform artifact-authorization race: ancestor directory full metadata fencing treats legitimate concurrent `periodic_state.json` writes as artifact replacement. Candidate repair uses stable directory identity (device/inode/mode) while keeping full PNG/content fencing and replacement/symlink rejection. Native verifier CONDITIONAL PASS: 63 report + 10 cutover, 100 state-churn, 60 replacement, 30 ancestor attacks; exact cutover 50x. Windows junction/reparse explicit rejection or real-Windows gate remains P2/open and is not silently closed.
- Legacy-shell safety preflight found and repaired three P1 classes: no source enablement before authoritative safety, no false-green cold start, and replay hard-disables mutation surfaces. Follow-up review found replay sensor rename/hide could still persist `channels.yaml`; repair now gates visible/keyboard/direct/queued/rebuild paths and updates design-system contracts. Final independent review is active. New POD/store remains not production-wired; screenshots remain blocked until authoritative snapshot ingress and real-shell scenario integration.
- External-model policy for the remainder: unavailable reviews are recorded with exact hashes/scope in this ledger and deferred; internal independent review continues. Grok remains postponed by user instruction. No hardware/physical gate is closed by these software results.

2026-07-12 PUSHED ACCEPTED SLICES / NEXT PARALLEL WAVE:
- `22e0295 feat(channels): add inert descriptor persistence contracts` committed/pushed after final native PASS; this includes F35.3A-1 pure descriptors and F35.3A-2 inactive persistence envelope. Actual SQLite/archive/replay/report/UI propagation remains open.
- `249504a fix(reporting): tolerate safe state-file churn` committed/pushed. It closes the Windows CI artifact re-authorization race by separating stable ancestor directory identity from mutable child-entry metadata while retaining full PNG/content/replacement fences. Native final PASS on cleaned diff; Windows junction/reparse and real-Windows execution remain explicit open P2/external gates.
- `63a6407 feat(soak): add fail-closed launcher evidence bridge` committed/pushed. H4 R1/R2 now keeps both pipe ends parent-noninheritable and transfers only by exact `pass_fds`; activation remains fused. H4 R3a provider-neutral delivery/state-v2 is dirty under independent review; R3b socket/ACK/ledger remains open.
- `8ac1c7c feat(gui): add fail-closed operator truth foundation` committed/pushed. Legacy shell cold-start/source/replay/config mutation P1s are closed; reviewed POD/navigation/components/design-system/roadmap/status foundation is tracked. New POD is still not production-wired. Broad one-process Qt collection can native-segfault during graphics teardown; each affected file passed in a fresh process (280 tests in the final coordinator rerun). Screenshot gate remains after real snapshot ingress/shell cutover.
- F36 ingress architecture preflight was REJECTED as implementation-ready with five P1s: durable global ordering, two differently capped SUB sockets, common cross-authority cut, separate subprocess decoder/latest-only queue, and atomic removal of reading-age authority. No producer was activated. Dark pure wire codec and durable revision allocator atoms were implemented independently and are under final verification; they grant no engine/GUI/control authority.
- Exact candidate GitHub CI is now run `29173723531` for `8ac1c7c` and remains IN PROGRESS at this checkpoint. Intermediate runs were concurrency-cancelled by intentional accepted pushes. Do not claim green until the final candidate SHA completes both Ubuntu and Windows.

2026-07-12 DARK F36 FOUNDATION PUSHED:
- `26fa878 feat(protocol): add operator snapshot wire contract` committed/pushed after independent PASS/no P0-P3. The exact two-frame `operator.snapshot` codec is inactive, bounded at 8 MiB before decode, canonical, cause/context-sanitized for hostile input, and imports no ZMQ/Qt/engine/replay authority.
- `80ccc16 feat(storage): add durable snapshot revision allocator` committed/pushed after independent PASS/no P0-P3. It provides process-safe global 63-bit ordering and nonregressing timestamps across restart/live/replay-equivalent contention; cancellation may create gaps but never reuse. It is inactive and isolated from daily DB/F35/control authority.
- The earlier F36 S1 producer design remains REJECTED and must not be activated. Next order is pure typed authority receipts, composer, publisher, two-SUB subprocess decoder, GUI ingress, replay wiring, live wiring, then atomic shell truth cutover. F36.3-F36.5 missing authorities remain explicitly unavailable, never fabricated OK/empty.
- H4 R3a first freeze was REJECTED by native verifier: local factory received Telegram config secrets, accepted receipt kind was not bound to destination provider, corrupted results could leave DELIVERING, and caption was absent from fenced context. Round-2 repair is active; R3b stays fused.
- Current exact-SHA CI is run `29173856244` for `80ccc16`, IN PROGRESS. Do not treat intentionally cancelled intermediate runs as failures or passes.

2026-07-12 CONTINUATION AFTER `80ccc16`:
- F36 typed snapshot-authority receipts reached independent final native PASS/no P0-P3. Frozen hashes: `engine_wiring/__init__.py` `44258b5217d3e8cebd3af0e2452459d7c8751af6086c3f30a32b7473c40b1b0d`; `operator_snapshot_authorities.py` `7c29c636ae41e476d022641fd65c2aeb16b9993e0a5697549abe9a8b26bdb6ce`; test `02fdc40d7c9dd72c810bb15a6077a4960d3ae881556fd7627359c0a3e1098f31`. Evidence: 520 repeated focused executions, 34 compatibility/isolated-import checks, 72 neutral protocol/transport tests, static gates clean. All earlier eager-import, datetime alias/subclass, revision-zero, Unicode, and common-cut defects are closed. Commit/push DID NOT HAPPEN because the managed Git gate rejected the required index write for usage quota until 07:50 MSK; no workaround attempted. Preserve the unstaged atom for later publication.
- F35.3A-3 hot SQLite catalog first freeze is REJECTED. Independent verifier reproduced transactional catalog/readings separation, missing rollback after partial `executemany`, concurrent migration TOCTOU, noncanonical envelope acceptance, disabled reader foreign keys, incomplete hot value object, and postcommit catalog validation allowing trigger-injected corruption. A bounded worker is repairing all findings; do not stage the rejected freeze.
- H4 R3a provider-neutral delivery/state-v2 final native PASS remains frozen: 224 focused + 180 repeated, no P0-P3. R3b remains fused/unimplemented. Publication waits for the overlapping Windows cutover test repair to be independently accepted and for the Git gate to reopen.
- Current Windows CI failure was traced to the test harness publishing a non-production artifact (direct final write, missing `result.json`, no staging rename). Frozen bounded repair touches only `tests/core/test_periodic_legacy_cutover.py`, hash `9663b74d04c00dc7aab2b3c4a7dbc08c6944caeecffb81720222a17add7c7f7d`; worker evidence exact node 100/100 and 117 adjacent. Independent verification is active. Runtime localhost panel is postponed because this environment returned ZMQ bind `EPERM`; it is not counted.
- GitHub status refresh DID NOT HAPPEN because `gh` could not connect to `api.github.com`. Exact green Ubuntu+Windows CI remains open and must be checked on the eventual final candidate SHA.
- Broad dirty-tree `pytest -q tests/` DID NOT RUN beyond collection: `tests/replay_engine/test_replay_predictor.py` requires a genuine `127.0.0.1` bind and this managed environment returned `PermissionError: [Errno 1] Operation not permitted`. The failure is an execution-facility gate, not a test pass/fail and not counted. Focused non-network coordinator panel remains 177 passed. Re-run the exact broad gate in a localhost-capable environment; do not mock or bypass the property.
- Windows cutover harness repair itself received independent PASS at hash `9663b74d04c00dc7aab2b3c4a7dbc08c6944caeecffb81720222a17add7c7f7d`: exact real supervisor/coordinator node 100/100, production-shaped two-file atomic publication, unchanged default reader, exact one-send/no-legacy assertions, static clean. The integrated H4 R3a slice is nevertheless REJECTED for a separate P1: `periodic_state.py` imports `cryodaq.agents.assistant.periodic_delivery`, so invalid report-child preflight loads `cryodaq.agents*` (213 adjacent pass, 1 fail). A bounded repair is moving the durable receipt value contract to a neutral low-level module shared by state and assistant delivery; do not publish R3a until the 214-test adjacent panel and independent re-review pass.
- F35.3A-3 round-2 remains REJECTED after most prior fixes closed. Remaining P1 reproductions: an unexpected `AFTER INSERT ON readings` trigger can inject a corrupt catalog row or null the inserted reading's descriptor hash after prevalidation, and the write commits successfully. Required final fence: exact trigger inventory includes `readings` (expected no readings triggers), validate before inserts and again after `executemany`, then reload all envelopes and run FK check before the single commit. P2: exact legacy six-column read currently leaks raw `OperationalError`; add stable legacy feature detection/value semantics. Repair/re-review remains active; no rejected SQLite atom is staged.
- F36 dark pure composer worker freeze is source `60ae0428cd0d7340c161498030d23c913c3ccb45db6d69d23b03e4b05b1dcd43`, test `d366851ede5174119f451bc6bb76fd0f4c7da6281ddd3335dcd3313ce8e8a0c8`; worker evidence 200 focused repetitions +127 adjacent/static clean. Independent review is active and must specifically adjudicate its synchronous durable allocator call against the engine-loop no-blocking-I/O invariant. It grants no lifecycle/ZMQ/GUI/control activation and is not accepted yet.
- F36 composer first freeze is REJECTED. P1: synchronous `compose()` performs durable SQLite allocation on the engine loop; an 80 ms allocator delayed a 10 ms loop timer to 91 ms. P1: allocator output older than the sampled cut is rejected only after consuming a durable revision. P2: datetime subclasses/identity aliasing cross the cut. Repair architecture is synchronous sample+complete validation -> immutable prepared cut, awaited off-loop allocation with atomic `not_before=observed` lower bound, then synchronous pure finalize with exact newly-owned datetime; cancellation after durable allocation may create a documented gap but never reuse. The original freeze must not be staged.
- H4 R3a neutral import repair now adds low-level `periodic_delivery_receipt.py`; `periodic_state.py` imports it and assistant delivery reexports the identical class. Worker evidence: 82 focused, invalid-child preflight 20/20, static clean. Independent full integrated re-review is active; no acceptance claim yet.
- H4 R3a + Windows harness FINAL NATIVE PASS/no P0-P3. Frozen principal hashes: neutral receipt `f7dfc0e74bc135420d7d500bc6aae8bb811b8791445763fd124b2e76b0ffb8df`; periodic state `ecaaa0e221275a4be7df9a71ca625b737f16b985b6ea7cd80383a4894c538f26`; assistant delivery `75a9306e84a93f95e57bb5ac37a7988f04a91bc2482272086d4959533053ddd4`; runtime `9eebc784341d085524936089e57961acc5236e602911dfa3c70951915d303b05`; cutover test `9663b74d04c00dc7aab2b3c4a7dbc08c6944caeecffb81720222a17add7c7f7d`; delivery test `fc2693791481e409e840b1793380380e84ba3f68b94344ae737a1819fb24645a`. Evidence: invalid preflight 20/20 and isolated import zero agents modules, adjacent 214, state/delivery 2,760 repeated, exact cutover 100/100, Telegram 48, static clean. Localhost ZMQ panel remains environment-postponed. Commit/push waits for managed Git gate; R3b must not overlap runtime until R3a is published.
- F35 Atom A round-3 was rejected for TEMP table shadowing that diverted successful-looking writes into temp tables. Coordinator repair now rejects protected TEMP objects by name/tbl_name and main-qualifies authority PRAGMAs, catalog/readings DML, and reader paths. Frozen candidate hashes pending independent review: channel descriptors `d7328fdd83f95d3dcffb240c65c6ab6127d47d5f1c7be8ec1e76d51208a10e5e`; writer `3d09b3a2d2e3e3ec25f68110e5d0d39a58be4927bd945fc8a12f0394ba8da8ec`; tests `72203ff2dd3b941baf0ac46ccb6f8d86d969655a64c78dd889838bd3cfc8f4b2`; inert tripwire unchanged. Coordinator evidence: focused 33, 20/20 full repetitions, TEMP cases 50/50, storage+channels 386, static clean. Independent review is active.
- F36 composer second freeze was rejected only for missing lifetime async serialization; concurrent compose calls could invert observed cut vs durable revision. Coordinator added a composer-local async lock across prepare -> cancellation-settled off-loop allocation -> finalize, plus deterministic reordering and cancellation-follower tests. Current combined focused/adjacent 132 and 20/20 composer+allocator repetitions pass; final independent re-review is active.
- F35.3A-3 Atom A FINAL NATIVE PASS/no P0-P3 at the hashes above. Independent verifier added a six-case TEMP object matrix (table/view/index/trigger by protected name and index/trigger by protected tbl_name): 300/300 across 50 repetitions. Focused 660 repeated; storage+channels 386; SQLite 3.53.2 exercised main-qualified ALTER/DML/PRAGMAs; static clean. All transaction, rollback, migration, canonical-envelope, trigger, FK, legacy, value-object, catalog-copy, and inertness findings are closed. Commit/push waits for the Git gate. Atom B cold descriptor sidecar worker is now active; Atom A production caller activation remains absent.
- F36 composer+allocator FINAL NATIVE PASS/no P0-P3. Frozen hashes: allocator `15d4a5e500c5a9845326239c7852e78d33d8affc273db276d781af9157cfacdf`; composer `6f873b42dcbf53aeecfe087fb5644f021ad55d06a19b306b76e89bf90a0c8473`; allocator tests `b2283a984372536a8730269f5ef6fd2b4cae1cdb48e93a89bb6d60f274139de6`; composer tests `4ea7a3d74a8b4f405769bc4effd8c44242171b36fcc81a32279a85e64f93f67b`. Evidence: 680 repeated focused, 132 adjacent, storage 255, static clean. Lifetime lock now preserves sample/allocation/revision/observation order through concurrency and cancellation settlement; off-loop I/O, atomic lower bound, exact datetime ownership, validation-before-allocation, common-cut/unavailable semantics and inertness remain closed. Commit/push waits for Git gate. A dark publisher/lifecycle worker is active; no live/GUI activation.
- F35 Atom B cold descriptor sidecar worker freeze is `cold_rotation.py` `330b79b265140789011ac472df3309f537954fed692edec392bf85b3d44f8a82`, test `cbef96a7da6cf3b5443ce7bb598c858441440e8c8090bbd4aaff05fcb5c149db`. Worker evidence: 29 focused, 580 repeated, storage 267, static clean. Independent child verification is active; no acceptance/publication claim yet.
- F36 dark publisher/lifecycle worker freeze prefixes: existing `core/zmq_bridge.py` `7aecd2f3`, new service `63778c95`, tests `050e8d46`. Worker evidence: 79 focused/adjacent, focused x20, broader adjacent 223 with 14 genuine-localhost cases unavailable because sandbox bind/elevated gate is closed until 07:50. Independent verifier is active. The atom is unwired, uses the sole existing ZMQPublisher socket/send lock, and grants no GUI/control activation; no acceptance claim yet.
- F36 dark publisher/lifecycle FINAL NATIVE PASS/no P0-P2 after monotonic/cadence repair. Final hashes: `core/zmq_bridge.py` `7aecd2f34dba52e197714e5325a2d29592e9ed600b24e1ae986135c8e872a2ec`; service `259ba2f66df3193107c0ffc253e7007e93336e3d925cfd7e041e0d27c3295224`; tests `43ac29492ed4bcaad9388d164181b19eb9383292e9dd8fdf7add9a2f3b42cac1`. Evidence: 28 focused x20, verifier broad pure 244, static clean. NaN/inf/regression/raising clocks fail before send or lifecycle spin; cancellation has priority; subnormal cadence rejected. Atom remains dark/unwired; localhost socket adjacency remains postponed until managed execution reopens. Second-SUB decoder/GUI-ingress worker is active under the frontend/design-system gate.
- F35 Atom B first freeze REJECTED with three P1 and one P2. P1: source rows could mutate between read and late source checksum, allowing a new row to be omitted and hot DB deleted. P1: sweep treated descriptor-bearing readings as legacy when all optional sidecar index fields were removed. P1: post-index exception recovery trusted scalar index fields and could delete hot DB after actual sidecar corruption. P2: direct `cryodaq.channels` import violated the bounded storage-adapter tripwire. Repair must bind one stable source cut, always inspect archived descriptor references, reopen/rehash/revalidate both artifacts after index commit before deletion, and route channel contracts through a bounded storage leaf. Original Atom B freeze must not be staged; repair/re-review active.
- F35 Atom B repaired freeze under independent re-review: cold rotation `07d0f347135983d78ad4e88793286b53f196270846ea95291764ac51ced02053`; new bounded storage adapter `e745103f19736f482759a3abe2b7cf58ed2da2a25ec13ae0b39c3b74ee1e5ffd`; tests `6ed510e33450832a8763c9aaa325eaf33042de7a0851f5b1a88320029fa4081b`; inert tripwire `488a6a6098270b8f9659f8b888471d9911b5413b44d7ff7386d89374a8069db1`. Worker evidence: 820 repeated focused, storage+tripwire 279, static clean. Repair uses locked logical source cut, repeated source digest checks, mandatory sidecar inference from readings, and actual post-index artifact reopen/checksum/schema/reference proof. No acceptance claim until child verdict.
- F36 second-SUB snapshot ingress freeze under independent child review: ingress `186633e3`, subprocess `81eb9943`, GUI client `4a0b3df6`, tests `9d95e6c2`. Worker evidence: focused 15 x20, adjacent 111, pure real-spawn queue pass, static clean. It keeps reading/snapshot sockets at distinct 2 MiB/8 MiB caps, capacity-2 newest-cut queue with balanced task_done, independent health, no store/control authority. Real spawn+ZMQ integration exists but localhost bind execution is postponed until 07:50. Design-system assessment: no new visual/state semantic, so no design-system version/doc change in this transport-only atom.
- F36 snapshot ingress FINAL NATIVE PASS/no P0-P3 after exact-topic/restart repair. Final hashes: ingress `186633e31fbf3391a16f794a051768e99773099b6b99bcca2f2bcdf26980b515`; subprocess `cf5d53fe164ccc4ed2b6f7daeda3965622dd3f8ddf1dcd95399bad78fd68822d`; GUI client `2f6f7c899ea7f7d3d83e38e3ee818324a21cf15123f3c63621e410b829552c33`; tests `d97023ff531f5f9ec9af1fe47e47d3ebd8576e5b9d0facf2b4988d18f7da4c2b`. Evidence: worker 23 x20 +119 adjacent; verifier 460 focused, 106 adjacent, 100 failed-spawn, 500 queue bursts, static/fresh-GUI-no-zmq. `readings.evil` is rejected before msgpack and snapshot freshness/queue invalidate before any restart/spawn cleanup. Real two-SUB localhost remains postponed. Next single GUI-thread store-owner atom is active; visible shell cutover/live/replay remain open.
- F36 single GUI-thread Store ingress FINAL NATIVE PASS/no P0-P3 after atomic qualification repair. Final hashes: owner `e2dbc59b3465e25e9a9f6f7b352d84935cb1344276e62fe379062b9fb0acdaeb`; app `54d6b11b06c8ba9cb762cea2aa10806b28d4a4d19237724ec8a8341e2452f706`; tests `55e2dc76d038dcc43af9bb33ec52035abb94925110cdd9807dfe10f24666df96`. Original P1 raw-before-stale signal is closed: age6/stale5 and two-cut coalescing each emit exactly once, already qualified/newest. Evidence worker 380 focused repeated +162 adjacent; verifier 380 focused +203 adjacent; static clean. Exactly one private Store, read-only presented snapshot, queued GUI batch, epoch teardown/restart and mode/source high-water; no panel cutover/live producer/control. Replay parity worker is active.
- F35 Atom C first checkpoint: 34 bounded archive tests and 118 combined archive/cold/hot/inert pass. Candidate behavior resolves old hot/Parquet to deterministic legacy-neutral descriptors and new hot/cold to equal frozen exact descriptors; seven issue-code corruption cases do not emit/downgrade affected rows; overlap dedup keeps value+descriptor atomic; envelope bytes/cardinality are bounded. Full repeats/storage/static and independent verdict remain open.
- F35 Atom C first freeze REJECTED after 920 focused passes. P1: compressed sidecar could be fully decompressed before byte-bound enforcement. P1: multiple path opens allowed replace/read/restore TOCTOU; require one no-follow fd for identity/checksum/Parquet decode. P1: deadline was not observed during hashing/row-group decoding. P2: missing hot catalog used wrong stable issue code. Repair must preflight Parquet metadata/uncompressed bounds, decode bounded row groups from one retained fd with fstat fences, check deadline per hash chunk/row group, and emit `descriptor_catalog_missing`. Original freeze must not be staged; repair/re-review active.
- F35 Atom C repaired refreeze under independent re-review: archive reader `1e909209245f92aa8da171c5289b94a378aab46de3e8cee2e95a4faa11fc1594`; descriptor adapter `11b7c4d981b37e26115a01d3d31a443cebf5d81335feb554be22ef252f9f8d9c`; bounded tests `0e738eb26441929327083cca80f8985329827f6000b2ff5732f6055098f62408`. Evidence: 1,020 focused repeated, storage+inert 296, archive+nonnetwork replay 87, static clean. Repair opens one no-follow fd, preflights Parquet metadata/compressed+uncompressed totals, checks deadline per hash chunk/row group, and emits exact missing-catalog issue. No acceptance claim until current verifier completes.
- F36 replay audit correctly found production ReplayEngine lacks reviewed typed authorities for a complete snapshot, so server/live wiring remains absent. A pure conservative REPLAY session candidate was frozen with detached typed archive evidence only and explicit unavailable authorities, but independent review REJECTED two P1s: reentrant seek/restart could mix epoch/source across compose, and future observed evidence was clamped to zero age. Repair serializes session lifecycle and rejects future evidence; no readings/command/GUI synthesis or live mixing is allowed.

2026-07-12 GIT/EXTERNAL GATE REOPENED — REVIEWED SLICES PUSHED:
- `312cc5d feat(engine): add snapshot authority receipts`
- `63c246a feat(engine): compose ordered operator snapshots`
- `0177e08 feat(protocol): add dark snapshot publisher`
- `9c7809b feat(gui): add bounded snapshot ingress` (includes GLM-derived bounded shared-counter lock hardening; independent functional PASS, formatter debt closed before commit)
- `87df02a feat(gui): own qualified snapshot store ingress`
- `8b58fde feat(replay): add conservative snapshot session`
- `6036a47 feat(engine): add conservative live snapshot authorities`
- `ab307d8 feat(reporting): add provider-neutral delivery state`
- `19b1126 feat(storage): preserve descriptors through archive`
All were independently native-reviewed, committed as coherent atoms/stacks, and pushed to `origin/feat/montana-phase-a`; no tag/release/merge. Current exact-SHA CI run `29185442809` for `19b1126` is IN PROGRESS. Intermediate runs were concurrency-cancelled by intentional immediate pushes and are not evidence.
- GLM-5.2 reviews DID HAPPEN after the external gate reopened. F36 GLM found one useful subprocess-death/shared-lock concern; coordinator added 10 ms bounded shared-counter acquisition plus cached diagnostic fallback, focused pure ingress 24 pass and independent killed-child proof PASS. Other GLM F36 claims were locally rejected: restart deliberately discards stale latest-cut presentation data, not historical acquisition; `multiprocessing.Value` is valid parent-child shared state; visible stale qualification is owned by the Store atom. F35 GLM's catalog race was factually inconsistent with `BEGIN IMMEDIATE` and append-only INSERT semantics; FK objection conflicted with intentional fail-closed corruption handling; missing dataclass import was hallucinated. Its long logical-source digest concern is off event loop via `asyncio.to_thread` and not a bounded query path. H4 GLM findings were locally rejected: Telegram transport is lazy with no constructor session, corrupted result reconstruction is inside the broad persist-unknown try, v1 could only encode Telegram receipts, context mismatch terminal failure is intentional/fail-closed, and hash grammars are equivalent.
- Claude Opus 4.8 reviews DID NOT HAPPEN despite retry: Claude Code 2.1.207 returned `Not logged in · Please run /login` for both F35 and F36 prompts. Preserve exact current commits for later Opus replay; do not claim certification.
- F35 Atom C final native PASS/no P0-P3 closed all deadline/TOCTOU/cardinality findings before `19b1126`: archive reader `fa08134f...` was further repaired to final committed hashes through post-StopIteration, per-row/per-scalar, metadata group/column, and bounded adapter checks. Final worker/verifier evidence is recorded in agent reports; current clean HEAD contains the accepted stack.
- H4 R3b implementation/preflight audit is active now that R3a is published. Runner terminal PASS/CLI activation remains fused pending full socketpair/ACK/ledger integration evidence.

2026-07-12 H4 R3B / CI CONTINUATION:
- `e2dd938 test(storage): keep spool crash fixtures fresh` independently verified (200/200 crash tests, exact parent/child created_at identity, no product age-cap change), committed/pushed.
- `0a823ec docs: reconcile pre-lab roadmap status` committed/pushed after docs freshness 4 PASS and GLM review locally adjudicated. GLM suggestions that observational UNKNOWN should trigger SafetyManager remediation were rejected because that violates the explicit no-health-remediation/product-assistant boundary.
- `5eead4c feat(soak): add acknowledged local artifact capability` independently PASS/no P0-P3 and pushed. R3b implements pathless AF_UNIX capability transfer, pass_fds/at-fork containment, bounded frame/ACK, exact identity/generation/slot/owner/artifact joins, nofollow durable file+canonical ledger before ACK, cancellation ambiguity, and local-mode no-Telegram/no-control. Runner activation/terminal PASS remains fused. Elevated real localhost evidence after commit: 34 R3b capability tests PASS and 123 wider periodic runtime/multiprocess tests PASS. Short-run activation worker and independent audit are active; 72h soak not started yet.
- Exact-SHA CI run `29185442809` for `19b1126` failed for two concrete software/test issues, not physical gates: Windows path separator mismatch in the bounded-storage import tripwire; Ubuntu native PySide/Qt graphics teardown segfault at `test_deleted_body_host_during_first_commit_fails_closed` in the monolithic process. A dedicated CI repair worker is active: normalize path semantics exactly and repair explicit Qt lifecycle or isolate the proven-correct file into its own CI process while retaining assertions.
- Current pushed HEAD is `5eead4c`; latest CI runs after subsequent pushes supersede older run IDs. Green exact final SHA remains OPEN.
- Atom B re-verifier ran unusually long without a checkpoint and was interrupted rather than trusted as implicit PASS. It has been resumed with bounded commands and must report the exact interrupted case plus a prompt PASS/REJECT. The repaired Atom B freeze remains unaccepted and unpublishable meanwhile.
- F35 Atom B repaired freeze received a replacement independent FINAL PASS/no P0-P3 after the original verifier remained unresponsive and was stopped. Exact hashes remain `07d0f347` / `e745103f` / `6ed510e3` / `488a6a60`. Evidence: focused cold/wiring/inert 63, critical 200 repeated, storage 277, committed-WAL logical-cut probe, bounded adapter import and static clean. Six source mutation boundaries preserve hot DB; stripped sidecar fields cannot downgrade non-null hashes; post-index artifact corruption preserves hot source; actual Parquet and sidecar are reopened/checksummed/semantically verified before unlink; legacy all-null/no-sidecar and Windows-style sweep remain compatible/conservative. Commit/push waits for Git gate. Atom C hot/cold archive resolution worker is active; replay/report/UI threading remains open.
- H4 activation audit rejected a cosmetic `_PosixSoakRunner.run()`/CLI fuse removal as a false-PASS path: the committed runner still lacks the execution owner, locked observer/signal/reap, clean-SHA collector, private Evidence authority, and exact durable H3 pre/post join; `psutil` is also absent from the declared/locked environment. Work continued on the smallest safe prerequisite instead. Dirty runner hash `2e2373c5...` plus new joined-receipt tests `5ca0e847...` now require ACK+canonical ledger+copied-byte rehash+direct-child PID/start+active H3 SUCCEEDED state+local destination+slot/generation/owner/artifact+state/health cut, then require exactly two ordered, full-record-hash-bound receipts at g1/s1 and g2/s1 with a different assistant identity and strictly newer slot/owner/update. Every partial/duplicate/unresolved/reused-identity path rejects and these values still cannot remove the activation fuse. Focused H4/R3 battery 52 PASS plus 150/150 repeated joined-proof cases; broader periodic/H4/artifact integration 236 PASS; Ruff check/format clean. Independent verification is active; 15-minute/72-hour runner execution remains OPEN and no Git action occurred.

2026-07-12 CONTINUATION CHECKPOINT — CI ACCEPTED / GIT DEFERRED:
- Independent CI verifier FINAL PASS/no P0-P3 for the exact frozen three-file repair. Windows importer normalization preserves the exact three-file allowlist. Qt deferred-delete handling is scoped to the owned host. The dedicated operator-ownership shard passed all 68 tests. Exact collection accounting proved 5,984 nodeids represented once across monolith, app-palette, and operator shards, with zero missing/extra/duplicate tests; focused boundaries passed 20 repetitions and static/diff gates are clean.
- Git staging/commit was attempted only after acceptance and rejected by the managed execution-credit gate, which stated retry after 15:54 MSK. No workaround was attempted. The accepted CI files remain dirty and frozen: `.github/workflows/main.yml`, `tests/channels/test_inert_activation.py`, and `tests/gui/shell/operator_components/test_freshness_and_card.py`. Commit/push and the required exact-SHA Ubuntu+Windows CI run are postponed, not waived.
- The F35 live descriptor carrier is under distinct verification while H4 joined-receipt verification continues. External Opus review remains unavailable/login-blocked and must be replayed later; native author/verifier evidence continues to gate implementation. Real Windows, 15-minute/72-hour soak, and physical-lab evidence remain OPEN.
- H4 joined-receipt prerequisite first freeze REJECTED. P2: the pre/post validator trusted publicly constructible `_JoinedReceiptEvidence` carriers and could accept fabricated PID/start/generation/slot/owner/artifact/destination fields without invoking the raw ledger/process/file join. P2: health evidence only had to be numeric/present and could predate delivery completion. Activation stayed fused. Repair requires raw full-cut validation through `_validate_joined_receipt`, adversarial fabricated-carrier coverage, and health freshness/status reaching the delivery cut; author repair plus independent re-verification are active.
- F35 live descriptor carrier first freeze REJECTED. P1: arbitrary callable/custom metadata survived `deepcopy`, contradicting the data-only/no-control-authority contract. P2: the frozen wrapper exposed a reachable mutable private `Reading`, so later public snapshots could be changed through `_owned_reading`. Stable identity/current revision/instrument/unit and no-alias/no-legacy behavior were otherwise correct. Repair requires exact field validation, a recursively bounded data-only immutable private payload, fresh consumer reconstruction, and callback/custom/cycle/depth/size/mutation regressions; author repair is active and will require a fresh independent verdict.
- F35 activation preflight established the no-dual-truth architecture: explicit bounded descriptor manifest -> one immutable live catalog -> SQLite commit-owned typed receipts -> DataBroker/ZMQ publication of the same canonical envelope -> replay/report/GUI parity. Merely passing a catalog to `SQLiteWriter` is insufficient because downstream live/replay/report/UI paths would remain descriptor-less and keep inferring semantics from channel names/units. Recommended ordered atoms are D1 manifest, D2 persistence activation, D3 committed receipts, D4 wire envelope, D5 replay parity, D6 reporting parity, D7 design-system-gated GUI routing, then conformance kit/reference passive driver. `config/channels.yaml` is not authoritative enough; initial IDs must match current emitted channel IDs, including calibration/raw and all configured device channels.
- F35 carrier repair refrozen after the authority rejection: source `d357a73192a5e0a04c579040237818a6ef78661b1811b9bce9983a74603c2fc2`, test `64033a1cc8c95d1e51f0ee6c5bc7f6a7bfa02fb1a8f7f091b0f6a33b034c48c0`. The private payload is recursively immutable/data-only with exact field validation and bounded metadata grammar; consumers receive fresh detached `Reading` objects. Author evidence: 19 focused, 475 repeated, 269 compatibility, 323 full storage, static/diff clean. Independent re-verification is active; no acceptance/publication claim yet.
- H4 repaired freeze closed fabricated-carrier and stale/degraded-health findings, but independent re-verification REJECTED a new P2: pre/post assistant generations could present different local capability nonces/destination fingerprints. The launcher contract retains one original endpoint/nonce across assistant replacement, so restart evidence must preserve identical destination authority. The positive fixture itself used distinct nonces and reproduced `CHANGED_CAPABILITY_ACCEPTED True`. Next repair must use and require one exact destination fingerprint/nonce across both full joins and add a changed-capability adversarial rejection; activation fuse remains intact.
- F35 live descriptor carrier FINAL NATIVE PASS/no P0-P2 at source `d357a73192a5e0a04c579040237818a6ef78661b1811b9bce9983a74603c2fc2`, test `64033a1cc8c95d1e51f0ee6c5bc7f6a7bfa02fb1a8f7f091b0f6a33b034c48c0`. Independent evidence: 203 focused compatibility, 570 repeated adversarial, 454 full storage+channels, static/diff clean. Prior callable/custom/cycle/unbounded metadata authority and reachable mutable payload findings are closed. Two activation P3s are carried forward: only catalog-produced bindings may become receipts, and aggregate metadata bytes must align with the 2 MiB wire cap. D1 explicit manifest/loader authoring is active; no Git action occurred.
- H4 joined-receipt prerequisite FINAL NATIVE PASS/no P0-P3 at runner `afe82b5601e0b193bb671e176860a94e5a5909d1aa410e4c3a5073e8457fe7fd`, tests `efbbf8915142dea519b412d2454b1907ff29b21ac54a6544844ecf489794d5b3`. Independent verifier closed all three repair waves: raw full-cut join prevents fabricated carriers; ready health reaches the delivery cut; one exact launcher-retained nonce/destination persists g1s1 -> g2s1 across assistant replacement. Additional generation/owner/destination/parent/role/ledger-order attacks reject. Evidence: 34 runner, joined 25 repeated, static clean. Activation/PASS fuse remains intact; the next execution-owner/evidence-authority atom is active and must be independently challenged before a real short soak.
- H4 process-observer/clean-SHA prerequisite first freeze REJECTED before semantic review: `pyproject.toml` declared exact-bounded dev psutil but `uv.lock` was unmodified and contained no psutil resolution; `requirements-lock.txt` alone is not the project dependency authority. Required `uv lock --offline` needs the managed `~/.cache/uv`; escalation was rejected by the execution-credit gate until 15:54 MSK. No hand-edit/cache-redirect workaround is allowed. Exact next commands after the gate: `uv lock --offline`, `uv lock --check`, graph/drift/focused/static checks, new hashes, same-child review. Runner semantics remain unaccepted and terminal PASS remains fused. H4 is temporarily postponed while disjoint F35/F36 work continues.
- F35.3-D1 manifest/loader first freeze under independent review: manifest `5fa6a277...`, combined carrier+loader `0fd80769...`, loader tests `f19f963e...`, carrier tests `8c2ddac...`. It maps 64 exact base emissions: 24 full-label LakeShore temperatures, 24 calibration `_raw` rows, 8 Keithley readbacks, one Thyracont pressure, four MultiLine lengths, and three environment readings. Because emitted LakeShore labels contain spaces while canonical stable IDs forbid them, an explicit immutable `(instrument_id, emitted_channel) -> canonical descriptor` binding was added; stable IDs remain machine anchors and no identifier grammar/driver output was widened or renamed. Loader bounds: 256 KiB, strict single-link regular snapshot, strict UTF-8/YAML exact schemas/types/count/depth, one-to-one complete binding, and complete-replacement local semantics. Activation P3s close via <=1 MiB aggregate metadata and owner-issued receipt provenance/forgery rejection. Author evidence: focused 40 x20, channel+descriptor 200, storage 344, static clean. Ignored local MultiLine 1..8 vs base 1..4 requires a reviewed complete local manifest or config alignment before production activation; never merge/synthesize.
- F35 D1 first freeze REJECTED despite correct 64-channel coverage. P1: WeakSet receipt ownership survived `object.__setattr__` payload/descriptor swaps and accepted a mismatched reading/descriptor join. P2: same-inode/same-length manifest replacement with restored mtime was accepted because ctime/content stability was absent. P2: a manifest beneath a symlinked parent directory was accepted because only the final component used no-follow. P2: emitted/live binding text accepted NUL/control/non-NFC data. Repair is active: issuance-time integrity fingerprint/capability revalidation, ctime/content cut, symlink-free dirfd path walk, and canonical NFC/control-free text, with exact adversarial regressions.
- F36 mandatory-authority preflight REJECTED live activation and found an existing safety P0: `Keithley2604B.disconnect()` discards a failed OFF result, closes, and later disconnected `emergency_off()` returns True, so `SafetyManager` can clear tracked active sources without terminal OFF proof. Local code trace confirmed the path. A priority author is implementing an exact reviewed-source lifecycle callback owned by SafetyManager/Scheduler integration: only readback True permits disconnect/bookkeeping clear; false/exception/cancellation preserves active/unverified truth and latches fault; passive drivers retain their path. No F36 safety adapter may activate until this is independently closed.
- F36 preflight also established that no coherent persistence presentation owner or recording owner exists. Future order after P0: SafetyManager-native constant-time immutable cut; one persistence owner over spool/materialization/archive typed receipts; same-loop experiment/recording owner with cancellation-settled worker adoption; only then live adapter/publication activation. The existing dark UNAVAILABLE authorities are correct and must not be bypassed.
- F35.3-D1 repaired freeze FINAL NATIVE PASS/no P0-P3: manifest `5fa6a277...`, source `ece6ee6f...`, config tests `4ea19baa...`, catalog tests `44a5bc6c...`. Independent verifier replayed payload-only and payload+descriptor swaps, nested payload/descriptor/token mutations, same-inode same-length fsync rewrite with restored mtime, symlinked parents, NUL/Cf/non-NFC text, and 1,500 valid/invalid path loads with zero fd leak; all attacks reject. Evidence: focused 194, storage+channels 491, D1 repeated 1,120, actual driver/calibration 95, static clean. The 64 tracked bindings, local replacement, bounds, no heuristics, SQLite compatibility, and no control authority remain closed. Real Windows path fallback and ignored local MultiLine 1..8 manifest remain explicit activation gates.
- F35.4 passive conformance harness first freeze is new-test-only and under independent review: `tests/driver_conformance/__init__.py` `1eec8869...`, `passive.py` `cc94c94f...`, self-tests `7a16431c...`. It covers public/external-probe lifecycle, cancellation, serialization, malformed/nonfinite readings, reconnect identity, mock locality, release, exact descriptor binding, and no source authority; downstream persistence/replay/report/UI interfaces are explicitly deferred rather than faked. Author evidence: self 4, related 123, x100 repetitions, static/compile clean.
- F35.4 conformance harness first freeze REJECTED as self-fulfilling/fake-shaped. P1: descriptor case required `source_key == emitted channel`, contradicting accepted explicit runtime binding for LakeShore labels. P1: malformed case required at least three error Readings rather than allowing exact fail-closed alternatives (unusable batch, empty, declared exception). P1: raw `wait_for` cannot bound a cancellation-resistant coroutine. P2: reconnect compared order rather than stable identity set. Negative mutant coverage and a real/reference application were absent. Repair is active with D1 binding semantics, owned cancellation settlement, outcome alternatives, set-stable identity, and negative mutants.
- Verified-OFF reviewed-source disconnect P0 first freeze under independent review: driver `8a29ff3c...`, SafetyManager `5eec7309...`, Scheduler `8629f364...`, engine `a3ee654a...`, driver tests `da05ae69...`, safety tests `ab4adc68...`. Connection-scoped per-channel proof resets on reconnect/start; only exact successful writes plus readback stamp OFF; failures preserve runtime and direct disconnect refuses close/disarm; SafetyManager owns exact identity/True/lock/abort/shield authority; confirmed proof may clear active evidence but never unlatches a prior fault; Scheduler routes only sealed REVIEWED_SOURCE while passive drivers retain legacy path; engine injects authority. Author evidence: focused 19/34, core 67, broad 260 +4 skip, boundary x50 =950, static/diff clean. No acceptance claim until current challenger verdict.
- Verified-OFF first freeze REJECTED with two reproduced P0s. P0: `_verify_output_off` treated `float(response) > 0.5` as ON, so `nan`, negative and fractional values became verified OFF; exact bounded finite-zero parsing is required. P0: Scheduler `wait_for` timeout could cancel `disconnect_reviewed_source` while it waited for `_cmd_lock`; its `finally` cleared the pending-abort bool, allowing the competing slow `request_run` to commit RUNNING with zero OFF calls. Repair is active: exact readback grammar plus cancellation-safe owned abort intent/generation that survives timeout until the competing start and shutdown settle, with deterministic Scheduler race regression. First freeze remains unaccepted.
- Verified-OFF second freeze closed parser and single-channel timeout P0s but REJECTED a dual-channel P0: with `smub` already active, a timed-out full-device disconnect intent during slow `smua` start aborted only `smua` and transitioned global SAFE_OFF while `smub` remained tracked/live. Third repair is active: scoped monotonic abort authority, full-device disconnect settles both channels, narrow abort preserves RUNNING when prior sources remain, and invariant forbids SAFE_OFF with nonempty active sources.
- F35 passive conformance harness FINAL NATIVE PASS/no P0-P3 after repair: `__init__` `b1853430...`, harness `b48051d7...`, tests `c3454403...`. Broad/base/harness/control exception declarations are rejected; only exact declared device errors may satisfy malformed outcome, while bounded timeout/cancellation and shape/usability assertions remain outside classification. Explicit D1 runtime bindings, fail-closed outcome alternatives, Counter identity, negative mutants, resistant-task settlement, and real LakeShore public-only cases pass. Evidence: focused 23, repeated 1,150, related 103, static/compile clean.
- F35 passive ASC reference TCP first freeze REJECTED P2: cancellation during disconnect could detach the shielded `writer.wait_closed` inner task beyond the configured timeout. Repair is active with explicit owned close task, bounded cancellation settlement/cancel+observe, and never-closing writer task-count regression. Pure driver behavior otherwise passed; four real localhost tests remain postponed by the managed gate until 15:54 MSK.
- F35 passive ASC reference TCP FINAL NATIVE PASS/no P0-P3 after repair: module `3d194f95...`, driver later doc-corrected to `4571a40b...`, tests `a2338dfe...`. Explicit owned close/settlement tasks survive repeated caller cancellation and leave zero waiters after deadline; independent stress ran 100 disconnects x25 cancellations. Protocol/bounds/UTF-8/finite/status, partial cancellation, idempotence, zero-I/O mock, stable identity and no source authority pass. Four real localhost cases remain explicitly postponed.
- F35 reference registry + exact packaging FINAL NATIVE PASS/no P0-P3: registry `714d5b3e...`, registry tests `a9f8e435...`, adoption `0fe85169...`, spec `fbe70492...`, spec tests `31979183...`, reference docs `4571a40b...`. Runtime registry and frozen driver allowlist are set-equal; Etalon/reference included; runtime PyInstaller filter retained 269 application modules with zero instrument/passive-extension leaf leakage and all required engine/H3/report modules. Reference receives sealed PASSIVE_EXTENSION only, no source/verified-OFF authority; unknown aliases fatal. Evidence: 145 pass/4 localhost skips, repeated focused, static clean. Real Windows remains open.
- F36 ExperimentRecordingOwner went through three verifier repair waves: P1 old-generation receipt replay/session collision; P2 shipped deterministic generation cloning seam; P1 shallow owner copy duplicating counters/session ID. FINAL NATIVE PASS/no P0-P3 at source `4c5e4c5e...`, tests `ca5792b7...`. Fresh process-bound generation is HMAC-bound, one-shot, non-copy/deepcopy/pickle/reduce/state; old generation and post-fork use reject; detached worker envelope remains exact data-only serializable. Loss/unavailable/stop/finalize/replacement end recording and never auto-resume without explicit epoch. Evidence: focused 45, repeated 2,250, adjacent 131, real fork/envelope smuggling probes, static clean. Integration with actual loop-owned experiment/acquisition/persistence feeds remains open.
- Verified-OFF reviewed-source disconnect P0 FINAL FUNCTIONAL PASS/no P0-P3 at driver `0dc7bba5...`, SafetyManager `6680905e...`, Scheduler `8629f364...`, engine `a3ee654a...`, driver tests `43bc6f9f...`, safety tests `e26e4757...`. Repair waves closed permissive NaN/negative/fractional/Unicode OFF parsing, cancellation-cleared abort intent, and dual-channel SAFE_OFF-with-live-source. Exact ASCII finite-zero proof is connection-scoped; full disconnect scope dominates overlaps and settles both channels; narrow abort preserves prior RUNNING source; sealed reviewed-source callback only; passive path unchanged. Evidence: focused 60, repeated 1,200, broad 304 +4 expected skips, Ruff lint/new tests clean. `ruff format --check src tests` independently shows 342 baseline files would reformat, so the three inherited touched-source format diffs are recorded repository-wide baseline debt, not isolated safety churn; no broad formatter rewrite was performed.
- F36 S1 pure safety snapshot contract first freeze under independent review: source `a9dcf832...`, tests `50670099...`; exact immutable lifecycle/readiness/verified-OFF/blocker/plant facts, bounds and nonoptimistic invariants, no owner mutation/I/O/control. Author evidence: 13 focused, earlier x20=240, static clean. SafetyManager cache integration remains a separate atom after review.
- F36 S1 pure safety snapshot contract FINAL NATIVE PASS/no P0-P3 after sealing/matrix repair: source `1cbbdae3...`, tests `05bb4ae2...`. UNKNOWN always has blocker+non-OK health; READY requires current verified-OFF; running/run-permitted/fault/recovery and SAFE_OFF remain blocked; top/nested subclass/callable/mutable alias attacks reject. Evidence: adjacent 81, focused x30, static clean. SafetyManager cache/adapter integration is active; real READY must retain explicit current proof and never derive from state name/empty active set/private driver cache.
- F36 pure PersistenceAuthorityOwner repair FINAL NATIVE PASS/no P0-P3: source `a57653b1...`, tests `cba8f537...`. Terminal STOP/CANCELLATION allows late pending settlement while remaining unavailable; distinct unused epoch only after pending zero; owner-lifetime tombstones reject append/epoch/failure reuse; exact record_count drives pending/dropped; global revisions and destination joins explicit; late ACK after terminal failure rejects. Evidence: focused 46, repeated 1,380, adjacent 117, static clean. Activation must provide one engine-loop global sequence, exact record counts, monitor 100k fail-closed identity capacity, and rotate owner only at pending zero.
- F35.3-D5 replay descriptor parity FINAL NATIVE PASS/no P0-P3: descriptor archive `9fa3a20f...`, broker replay `e3f25c97...`, tests `8083c9e4...`. Exact envelope plus display fields survives hot/cold/pure-cold/overlap archive-wins atomic dedup; corrupt/future drift omitted with issues, never legacy downgrade; genuine legacy explicit unknown/None; frozen carrier no control/metadata forgery. Cancellation now owns the to-thread task, survives repeated cancellation without Python 3.14 shield exception leakage, retrieves outcome, and re-raises first cancellation only after bounded ArchiveReader settlement. Evidence: focused 80, repeated 270, broader 477, static clean. Descriptor-aware broker/wire cutover remains later; never copy envelope into Reading metadata.
- 2026-07-12 15:58 MSK managed gate reopened. H4 process-observer dependency authority repaired without workaround: `uv lock --offline` resolved 97 packages and added exact psutil 7.2.2; `uv lock --check` PASS. Exact hashes: pyproject `3c765e9a...`, requirements lock `b9eb9427...`, uv lock `9d0b983c...`, runner `383d19b7...`, static runner test `14d71293...`, process-authority tests `5d69350f...`, joined receipts `efbbf891...`. Focused lock/process/join 34 PASS; Ruff/diff clean. The previous dependency rejection is closed, but runner/process semantics still require independent re-review before activation/PASS fuse work.
- F35.3-D6 reporting descriptor parity FINAL NATIVE PASS/no P0-P3: data `48f5cdf9...`, sections `a5199117...`, projection `578f9c06...`, tests `27da87bf...`. Canonical envelope is re-decoded/byte-canonicalized and every identity/quantity/unit/role/safety/display/visibility/hash/revision field rejoined; corrupt rows omitted with visible bounded issue; canonical report classification uses quantity/role/visibility only; explicit legacy_unknown alone receives bounded legacy name/unit fallback; no envelope in Reading metadata/control. Evidence: reporting/replay/archive/storage 327 pass, projection repeated 40, static clean.
- Dirty accepted-foundation aggregate coordinator gate: 212 passed / 4 real-localhost skips across report projection, descriptor replay, experiment/persistence/safety value contracts, passive conformance/reference driver, and health suite; `git diff --check` clean. This is not a clean-SHA/full-suite/Windows claim.
- F36.4 pure HealthTelemetryDevice + 100/2000 simulator FINAL NATIVE PASS/no P0-P3 after four adversarial repair waves: pinned descriptor, exact nested/tuple boundaries, positive `{health_descriptor, read_health_snapshot}` surface, factory-only private reader issuance, and lifetime-pinned metric schema/counter map <=64. Final source `eb9ba137...`, tests `de3f1ecd...`, init `ec3811d5...`, simulator `53783940...`. All descriptor swap/subclass/callable/dynamic/unbounded iterable/direct reader construction and rotating-ID attacks reject. Evidence: 55 tests x20, hashseed-stable exact 100 devices/2000 metrics/10 stale/2 fault, median pure materialization 6.845 ms, no retained frames, static/import clean. This is pure simulator evidence only; static factory-issued wiring, scheduler cadence, virtualized GUI, Qt/RSS/Windows/lab evidence remain open.
- F36 SafetyManager cache + LiveSafetyReadinessAuthority FINAL NATIVE PASS/no P0-P2: safety manager final `7455caa7...` plus live adapter `8519637f...` and focused tests. Child collector/monitor normal return/exception/cancel immediately invalidates READY/verified-OFF with generation-safe callbacks; expected stop settles; exact-True interlock required; truthy non-bools fault and retain active evidence. Missing reviewed-source connect callback stays conservative UNKNOWN/false/disconnected; getter O(1)/no I/O; adapter exact-type/monotonic/equivocation/corruption fail unavailable. Evidence: focused 70 x20, interlock matrix repeated, broad nonlocal safety/Keithley/P0/P1 all pass; Ruff/diff clean. Two legacy test files remain part of repo-wide formatter debt; production source formatting clean.
- F35.3 D2+D3 activation is now active as one ordered lane: off-loop manifest selection -> SQLite catalog transaction -> owner-issued commit receipt -> Scheduler publish only committed receipt. It must preserve safety scheduler changes, forbid post-commit relookup/metadata smuggling, and fail startup on incomplete local manifest (current ignored MultiLine 1..8 mismatch) rather than synthesize.
- 2026-07-12 CONTINUATION/RESUMABILITY NOTE: the visible pause after a worker usage-limit failure was a coordinator reporting defect, not a technical stop condition. The live worktree and agent topology were rechecked before resuming; `pkcs11.txt` remains unexplained/user-owned and untouched. All four native slots are active: F35 D2+D3 authoring, support-bundle adversarial repair, bounded H4 process-authority verification, and root coordination/adjudication. No Git or external-model action is authorized in this stretch; those evidence gates remain recorded for the later joint pass. Before any future unavoidable boundary, append exact accepted hashes/tests/open findings here and immediately reroute failed work when an internal slot is available.
- H4 coordinator rerun: process/runner/joined focused panel 29 PASS and Ruff lint PASS. A fresh `uv lock --check` could not read the managed `~/.cache/uv` in the sandbox; the required escalated retry was rejected by the platform usage gate until 2026-07-18 10:01. No cache redirect, copied cache, or other workaround was attempted. The earlier authorized post-resolution `uv lock --check` PASS remains the collected lock evidence; this new exact rerun is postponed and must be repeated when the managed gate reopens. Source/test work continues independently.
- F35.3 D2+D3 AUTHOR FREEZE, NOT YET INDEPENDENTLY ACCEPTED: engine `3ee686d9...`, scheduler `b6ec623f...`, sqlite writer `f40bf06b...`, descriptor catalog `0b96de8a...`, local eight-channel example `55b40654...`, receipt tests `c42dfc20...`, scheduler tests `8c280c16...`, activation tests `32c79ff3...`. Author evidence: 518 pass with nine inherited calibration deprecation warnings; concurrent commit and cancellation ambiguity each repeated 25 times; scoped Ruff/format/diff clean. The slice implements off-loop complete base/local authority, exact configured-instrument set, atomic catalog+row transaction, owner-only post-commit typed receipts, and receipt-only broker publication. Distinct adversarial review remains mandatory. Future third-party plugin preflight still needs a registry-owned emitted-channel manifest callback; unknown runtime emissions currently fail closed.
- F36.5 pure support-bundle contract FINAL INDEPENDENT PASS/no P0-P3: `bundle.py` `aba36368...`, package init `0e32bd80...`, tests `9644947a...`. Four verifier repair waves closed direct-constructor redaction bypass, secret/opaque-token and Unicode/punctuation leaks, mutable timezone authority, POSIX/Windows/UNC/rooted path leakage and traversal, normalized-key collision, global work/cycle/byte bounds, fingerprint provenance, hash-seed nondeterminism, and contradictory unavailable evidence. Evidence: focused 99, x50 repetitions, adjacent 184, hash seeds 0..49 one digest, Ruff/format/adversarial matrix clean. Live capture and jailed atomic write adapter remain a later integration atom.
- ORCHESTRATION FAILURE/HANDOFF: a request to spawn a replacement bounded H4 verifier hung inside the native delegation call for about 4.4 hours and was aborted by the app. It performed no known repository edit. The original H4 verifier is interrupted and gave no verdict. All other workers completed. A self-contained continuation handoff was written to `scratchpad/montana/exec/HANDOFF_2026-07-12_NATIVE_DELEGATION_ABORT.md`. Do not interpret the hang as a CryoDAQ runtime failure.

## 2026-07-13 independent strategic coordinator review — READ BEFORE CONTINUING

The live branch/CI/roadmap direction was independently rechecked after push
`0c57846`. Detailed findings, including the likely production Windows
`os.O_BINARY` defect, Ubuntu offscreen repair assessment, missing descriptor
configuration documentation, review/publication accounting, and recommended
green-CI -> D4 -> F36 -> soak sequence are here:

**[Strategic coordinator review — 2026-07-13](reviews/STRATEGIC_COORDINATOR_REVIEW_2026-07-13.md)**

Headline: architecture is moving in the right direction, but actual GitHub run
`29207903245` is red on both Ubuntu and Windows. Close the target-OS and docs
gates before stacking more overlapping integration. Do not count the empty
external-review transcript files as reviews, and keep `pkcs11.txt` untouched.

## 2026-07-13 live follow-up — READ BEFORE THE NEXT CI/SAFETY SLICE

The branch advanced to `d85c89f`, but exact-SHA run `29247772531` exposed a
new Windows periodic-recovery failure while Ubuntu was still running. The
follow-up also reviews the dirty alarm-pattern liveness slice, the missing
runtime check against a selected local descriptor manifest, current
ROADMAP/PROJECT_STATUS drift, and the now-resolved provider-specific
`CLAUDE.md` governance decision:

**[Current coordinator insight — 2026-07-13](reviews/CURRENT_COORDINATOR_INSIGHT_2026-07-13.md)**

User clarification: the Claude-specific orchestra in `CLAUDE.md` is
intentional and authorized. Claude may keep ecosystem-specific routing there;
`AGENTS.md` remains the higher repository-wide safety/product/evidence
contract. Do not restore the thin pointer or treat provider specificity alone
as a finding.

## 2026-07-13 coordinator resumption — Windows/WSL gate explicitly deferred

Vladimir returned coordination to Codex and explicitly chose to diagnose the
remaining Windows-only CI failures later on his own Windows + WSL machine,
where the platform behavior can be reproduced interactively. This is a
postponement, not a waiver: do not skip, xfail, delete, or weaken the failing
test, and do not claim an exact-SHA green candidate or final software-side lab
readiness until the packet below passes.

Current published truth:

- branch: `feat/montana-phase-a`;
- exact HEAD/remote SHA: `c1e26e21bcae06f87a3f26729f753d0138ee5461`;
- GitHub Actions run: `29251698616`;
- Windows job `86821588853`: **FAIL** in the full test step after lint,
  lock-drift, app-palette, and operator-ownership preflights passed;
- Ubuntu job `86821588842`: still running when this entry was written;
- unresolved Windows node:
  `tests/integration/test_periodic_png_crash_recovery.py::test_crash_after_pending_before_input_rebuilds_once`;
- observed divergence: restart reconstruction terminalized the durable attempt
  `FAILED` where the contract/test requires exactly one `SUCCEEDED` rebuild and
  no dual send. The test already calls `reconcile_once()` after startup, so do
  not relabel this as the earlier sleep/poll race without a Windows trace.

Deferred Windows/WSL evidence packet:

```powershell
git switch feat/montana-phase-a
git pull --ff-only
git rev-parse HEAD
$env:PYTHONPATH = "$PWD/src"
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python.exe -m pytest -vv -s --tb=long `
  tests/integration/test_periodic_png_crash_recovery.py::test_crash_after_pending_before_input_rebuilds_once
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider `
  tests/integration/test_periodic_png_crash_recovery.py `
  tests/agents/assistant/test_periodic_png_recovery.py
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/
```

Run the corresponding focused and full commands in WSL with
`PYTHONPATH="$PWD/src"` and `QT_QPA_PLATFORM=offscreen`. Retain the failing
temporary directory/state JSON, traceback, Python/OS/filesystem versions, and
whether the checkout/data directory is NTFS-mounted or native WSL storage.
Use the focused Windows loop to identify the real file-semantics boundary;
do not burn repeated remote `-x` cycles discovering one node at a time.

Work that remains safe to advance meanwhile: adjudicate the dirty startup
safety-pattern liveness slice, continue non-overlapping F35 descriptor
wire/replay/report/UI work, continue F36 backend-truth/design-system work, and
prepare local/physical evidence procedures. `pkcs11.txt` remains user-owned and
must not be opened, staged, edited, or deleted.

### Startup pattern-liveness diagnostic — independently accepted temporary scope

The earlier Sol REJECT of the proposed immediate fail-closed gate was accepted
and repaired rather than overridden. The current slice is explicitly a
temporary pre-lab diagnostic, not final refusal-to-boot enforcement:

- `_run_engine` passes the exact legacy + alarms-v3 union used by
  `AdaptiveThrottle` to the validator;
- it catches only `SafetyPatternLivenessError`, logs CRITICAL, and continues;
  unrelated validator defects still abort startup;
- wiring tests prove the selected local descriptor replacement reaches both
  validator and writer, and prove non-default effective Keithley patterns;
- the three currently raw-dead legacy throttle regexes are exposed rather than
  hidden, so the shipped config intentionally produces a loud diagnostic until
  they are repaired;
- final fail-closed activation remains open until the exact lab-selected
  manifest/hash produces zero dead patterns and the raw-plane legacy patterns
  are repaired or deliberately translated.

Independent verifier verdict: **PASS for temporary CRITICAL-diagnostic scope,
no P0/P1/P2**. Root rerun after documentation corrections:

```text
106 passed in 24.17s
ruff check: PASS
ruff format --check: PASS (3 files already formatted)
git diff --check: PASS
```

The exact deferred Windows crash node also passed on macOS (`1 passed in
0.06s`); this supports but does not prove the Windows-specific classification.
No Windows/WSL or exact-SHA-green claim is made.

Committed locally, not pushed: `519b0f7 feat(safety): expose dead startup
channel patterns`.

### Roadmap/status evidence reconciliation

`ROADMAP.md` and `PROJECT_STATUS.md` were updated in a separate bounded docs
slice to reflect committed truth at `c1e26e2`: F35 D1-D3 and D5-D6 plus the
conformance/reference/packaging foundations are complete; D4/D7/full e2e remain
open. F36 live safety/readiness is available and conservative; production
recording/integrity integration and shell cutover remain open. The docs record
run `29251698616`, the deferred Windows failure, last-known-running Ubuntu, and
all real Windows/soak/physical gates without claiming the dirty safety or D4
slices accepted.

Committed locally, not pushed: `ac65aa4 docs(roadmap): reconcile pre-lab
implementation truth`.

## 2026-07-13 cheap-worker landing order — READ BEFORE DOING ANY GIT WORK

The difficult F35 D4/D7.0 design, implementation, adversarial repair, loopback
evidence, and independent review are complete. A deliberately mechanical
handoff now exists for a lower-capability worker to re-run the frozen gate,
commit the isolated diff, cherry-pick only if the main checkout is exactly at
`ac65aa4`, verify, record evidence, and stop:

**[Cheap-worker D4 landing handoff](CHEAP_WORKER_HANDOFF_D4_LANDING_2026-07-13.md)**

Do not let the cheap worker implement D7, persistence-authority activation,
F36 composition/publication, soak activation, or conflict resolution. Those
remain strong-coordinator work.

## 2026-07-13 cheap-worker D4 landing evidence

- D4_SHA: `16cd14b52b46c89b6bd35e8699c890ebe476fe99`
- cherry-picked main commit: `e2151fd feat(channels): carry canonical descriptors over live wire`
- focused pytest: 128 passed
- adjacent safety pytest: 60 passed
- ruff check: PASS
- ruff format --check: PASS
- git diff --check: PASS
- independent review verdict already obtained: PASS, no reachable P0/P1/P2
- no push, no CI, no Windows claim
- next task: strong coordinator implements D7.1 descriptor store and later persistence-authority activation

## 2026-07-13 strong-coordinator continuation after D4

- Three disjoint lanes are active: shared-worktree D7.1 descriptor-store/GUI
  ingress authoring, an independent read-only D7.1 adversarial verifier, and an
  isolated `/private/tmp/cryodaq-h4-soak-activation` H4 runner-activation
  author. No push, CI, Windows work, dependency installation, or `pkcs11.txt`
  access is authorized in these lanes.
- D7.1 acceptance requires one atomic switch from `poll_readings()` to
  `poll_readings_with_descriptor()` (never both drains), exact-once mixed-batch
  delivery, a GUI-owner-thread descriptor Store, monotonic revisions with
  equivocation/regression refusal, bounded absent-vs-refused diagnostics, and
  no visual redesign yet.
- The next F36 backend sequence is frozen in the
  **[F36 live-activation blueprint](F36_LIVE_ACTIVATION_BLUEPRINT_2026-07-13.md)**.
  Key finding: the live path currently proves direct SQLite commit, while
  `PersistenceAuthorityOwner` claims durable spool/materialization/ACK truth;
  those must be honestly integrated, not relabeled into fake green integrity.

## 2026-07-13 wrap-up checkpoint — user-requested stop

All active lanes were stopped; do not treat partial work as reviewed or
accepted.

- Main HEAD remains `e2151fddd576a0d0d8d385205f58012c4da99142`, branch
  `feat/montana-phase-a`, ahead of origin by 3. No commit, push, CI, Windows,
  dependency, soak, or hardware action occurred in this continuation.
- Partial **unreviewed/untested D7.1** work remains in the shared worktree:
  `src/cryodaq/gui/app.py` (`3c5928fc...`),
  `src/cryodaq/gui/shell/main_window_v2.py` (`3e6aca05...`), new
  **src/cryodaq/channels/live_display.py** (`99376cbb...`), and new
  **src/cryodaq/gui/state/channel_descriptor_store.py** (`ec8a02c7...`).
  It changes the GUI to one descriptor-aware drain, adds paired dispatch, and
  begins the GUI-thread descriptor store/label contract. No D7.1 tests or docs
  were added before the stop; the slice is incomplete. Root inspection already
  flagged forged/non-Reading carrier hardening and hot-path validation cost for
  repair before review.
- The D7 verifier completed only the pre-diff acceptance matrix. There is no
  implementation verdict. Required next review includes exact-once mixed-batch
  delivery, GUI thread affinity, revision/equivocation/capacity bounds, lazy
  cache behavior, stale roadmap/status truth, and the SensorCell design-system
  authority statement.
- H4 isolated worktree `/private/tmp/cryodaq-h4-soak-activation`, branch
  `codex/h4-soak-activation`, remains clean at `e2151fd`; no edits or tests.
- `F36_LIVE_ACTIVATION_BLUEPRINT_2026-07-13.md` is coordinator analysis only;
  its independent challenge was interrupted by this stop and it is not yet an
  accepted implementation design.
- `pkcs11.txt` remains the only protected unrelated untracked file and was not
  opened, edited, staged, or removed.

Exact safe resume order: inspect the four D7.1 files and hashes above; finish
the bounded tests/docs; obtain an independent frozen-diff verdict; only then
commit locally if authorized. Separately re-challenge the F36 blueprint before
any persistence/spool activation. H4 may resume from its clean isolated
worktree after D7.1 is settled.

## 2026-07-14 PC CI checkpoint — docs freshness

- Exact-SHA run `29286279027` first failed both OS jobs at docs freshness under
  `pytest -x`, after 2,348 Windows and 2,350 Ubuntu passing tests; no later-suite
  result is claimed.
- The CI-006 exact hydration node passed locally on native Windows. At that
  checkpoint, the full suite was still running and independent review remained
  open; this historical state is superseded by the reviewed evidence below.

## 2026-07-14 reviewed PC/WSL evidence checkpoint

- Independently reviewed commits are `c67aeb2` (CI-006), `63d5e15` (ledger),
  `7762fbe` (H4-C1), `de1e0c8` (TCP tests), and `bb87282` (WSL filesystem
  handling and guidance).
- On WSL2 Ubuntu 24.04 with Python 3.12.3 at exact `bb87282`, the main no-`-x`
  CI topology completed with 6,580 passed, 7 skipped, and 76 deselected in
  709.02 seconds. The isolated GUI shards passed 7 and 68 tests; the focused
  WSL-fix set passed 20 tests.
- On native Windows, the full CI-006 multiprocess module passed 6 tests; the
  selector regression and exact hydration node passed; and the GUI shards
  passed 7 and 68 tests. A separate full local inventory ended with 192
  failures and 1 error, but is **not software evidence**: that local CPython
  lacks `socket.AF_UNIX`, the account lacks symlink privilege (`WinError 1314`),
  and ACL-destructive base-temp failures cascaded through the run. Hosted
  `windows-latest` remains required.
- All five slices received independent review. The WSL-fix reviewers could not
  access WSL; root execution supplied the 20-test and full-suite evidence above.
- Push and GitHub exact-SHA verification remain pending. Physical hardware,
  frozen-build, and soak gates remain open.

## 2026-07-14 hosted POSIX-capability CI repair

- Exact-SHA run `29297856378` at `6a4edb8` proved the safe conda-forge SQLite
  runtime gate on both hosted operating systems. Windows GUI/core and Ubuntu
  GUI/core completed successfully. The remaining failures were capability
  binding errors, not product-behavior failures: Ubuntu H4 could not find its
  reviewed exact interpreter alias, Windows attempted POSIX directory-descriptor
  evidence, and Windows attempted inherited AF_UNIX durable artifact delivery.
- The reviewed repair binds `.venv/bin/python` on Linux only to the currently
  executing conda interpreter and verifies it against `/proc/self/exe`, while
  refusing any ambient `.venv`. It does not broaden H4 interpreter authority.
- `Evidence` and the durable artifact receipt sink now reject non-POSIX hosts
  before filesystem or socket side effects. Real POSIX tests are selectively
  platform-marked; pure validators remain cross-platform. No TCP substitute,
  fake durability, or relaxed safety contract was introduced.
- Native Windows focused evidence: **64 passed, 84 POSIX-capability skips**.
  WSL2 Ubuntu 24.04 complementary evidence: **102 passed, 2 Windows-refusal
  skips**. Ruff check, Ruff format check, workflow YAML parse, and
  `git diff --check` passed. Independent frozen-diff review: **PASS, no P0-P3**.
- A new exact-SHA hosted run is still required after publication. Physical
  hardware, frozen-build, and soak-duration gates remain open.

## 2026-07-14 reviewed D7.1 descriptor-qualified GUI ingress

- The two production GUI drains now consume only
  `poll_readings_with_descriptor()`. One GUI-thread-owned descriptor store
  ingests exact qualified carriers before each valid bare reading reaches the
  existing sinks exactly once. Malformed carriers are dropped; store
  thread-ownership violations remain fatal instead of being hidden.
- Descriptor authority is invalidated before every data-plane restart and
  teardown, including engine exit, delayed auto-restart, command/data
  watchdogs, standalone shutdown, theme re-exec, and normal launcher shutdown.
  The delayed callback invalidates again immediately before restart so queued
  old-session data cannot regain authority during backoff.
- Production-executing regressions cover both app and launcher drains,
  valid/malformed/valid ordering, exactly-once delivery, all shutdown paths,
  and no late dispatch after timer settlement. Independent final review:
  **PASS, no P0-P3**. Main-worktree focused evidence: **81 passed, 5 deselected**;
  the deselected tests require Windows symlink privilege unavailable to this
  account and are unrelated to D7 behavior. Ruff check/format and diff check
  passed.
- D7 is not complete: real localhost ZeroMQ mixed-batch/restart/shutdown proof,
  remaining channel-name inference removal, generic instrument presentation,
  and acquisition-to-health-display end-to-end evidence remain open. No
  physical or frozen-build gate is closed by this slice.

## 2026-07-14 second hosted CI adjudication

- Exact-SHA run `29299230850` at `ccce8a7` passed Windows/Ubuntu GUI and Ubuntu
  core, then exposed three later-suite boundaries after 1,000+ tests per shard:
  a short-lived Ubuntu exact-six descendant became a zombie between enumeration
  and identity capture; a Windows test invoked the deliberately POSIX-only
  inherited bridge-handshake pipe; and Windows text-mode PNG header reading
  translated the PNG signature and failed the real report subprocess protocol.
- Descendant settlement now treats only typed already-exited zombies and
  `NoSuchProcess` causes as gone. Invalid timestamps, access denial, PID reuse,
  unknown observation errors, leader continuity, and exact signaling remain
  fail-closed. The bridge lifecycle test is POSIX-only and Windows proves typed
  rejection before pipe allocation; pure parsers and identity guards still run
  on both hosts.
- PNG validation now adds the Windows `O_BINARY` flag while retaining no-follow,
  lstat/fstat identity fences, regular/single-link checks, bounded 24-byte read,
  and post-read verification. The genuine Windows report subprocess test stays
  enabled and passes. Symlink security tests skip only WinError 1314 when the
  account lacks creation privilege; hardlink rejection still executes, and
  POSIX mode bits are not misrepresented as Windows ACL evidence.
- Native Windows evidence: H4 process/bridge panel **16 passed, 2 POSIX skips**;
  periodic child/renderer panel **71 passed, 3 symlink-privilege skips**. Ruff
  and diff checks passed. Independent H4 and Windows failure-surface reviews:
  **PASS, no P0-P3** after repair. A new exact-SHA Windows/Ubuntu run remains
  required; physical, frozen-build, soak-duration, and hardware gates remain
  open.

## 2026-07-14 reviewed Linux H4 and F36 projection evidence

- A clean native WSL2 Ubuntu 24.04 snapshot at `7f67631` repeated the exact
  failure-prone six-command execution boundary **20/20 passes**. The full H4
  process/handshake/artifact capability panel then passed **60 tests with 3
  expected host-selection skips**. This supplements, but does not replace, the
  required hosted exact-SHA Ubuntu job and does not close a soak-duration gate.
- F36 now has exact-owner live recording and persistence projection adapters.
  Cold, incomplete, corrupt, regressed, or equivocated cuts remain unavailable;
  storage failure is represented separately from authority unavailability.
  The existing identity-only adapter remains intact and no engine/app/shell
  activation occurred. Direct SQLite commit truth was not relabeled as durable
  spool/materialization/ACK evidence.
- F36 focused/adjacent evidence: **168 passed**; the 47-test live-authority
  module repeated 20 times for **940 passes**. Ruff check/format and diff check
  passed. Independent review initially found and repaired one P1 invalid
  cross-domain revision comparison; final verdict **PASS, no P0-P2**.
- Production recording remains `UNKNOWN` and production integrity unavailable
  until actual loop-owned feeds and a truthful persistence architecture are
  activated. Atomic shell cutover, all 12 operator scenarios, real localhost,
  frozen-build, hardware, and physical gates remain open.

## 2026-07-14 third hosted CI adjudication and Windows/WSL repair

- Exact-SHA run `29301178065` at `80b844b` passed Windows/Ubuntu core and GUI.
  The later shards exposed three deterministic boundaries: Ubuntu process-group
  enumeration wrapped an already-exited process in the typed foundation error;
  a Windows report assertion compared a POSIX separator string; and Windows
  archive reads compared incompatible path/handle `ctime` semantics before
  hashing binary Parquet bytes through CRT text mode.
- Process-group settlement now skips only typed gone/zombie observations or a
  foundation error directly caused by locked `psutil.NoSuchProcess`; access
  denial, unrelated OS/type/value errors, live descendants, missing leaders,
  PID reuse, and exact pre-signal identity checks remain fail-closed. Report
  selection now proves the exact platform-native relative path under the
  experiment root.
- Archive index path/handle identity uses Windows birth time only for the
  cross-API comparison, while same-handle `ctime` still fences mutation. All
  raw archive descriptors open with `O_BINARY` on Windows. POSIX retains the
  rename-open-inode race proof; Windows separately proves WinError 32 blocks
  replacement of the open descriptor authority and then completes both hashes
  and the verified read.
- Native Windows evidence across the bounded archive, H4 process, and report
  target: **64 passed, 1 intentional POSIX skip, 1 local symlink-privilege
  deselection**. Native WSL2 Ubuntu 24.04 H4 evidence: **21 passed, 1
  Windows-only skip**. The full safe-SQLite agent/reporting shard passed once
  verbosely and then three consecutive repeats: **1494 passed, 4 skips, 1
  deselection** each repeat, all in about 49-51 seconds. This adjudicates the
  hosted Ubuntu agent-shard 40-minute cancellation as non-reproduced; a new
  exact-SHA hosted run remains mandatory.
- Ruff check, applicable Ruff format checks, and `git diff --check` passed.
  Independent expanded-diff reviews: **PASS, no P0-P3**. No timeout increase,
  unjustified skip, assertion weakening, SQLite safety bypass, or fake hardware
  evidence was introduced; the POSIX rename semantic is paired with the
  Windows replacement-denial proof. Physical hardware, frozen-build, and
  soak-duration gates remain open.

## 2026-07-14 fourth hosted CI adjudication, D7.2, and full-shard hardening

- Exact-SHA run `29303819142` at `a19e92c` passed Windows/Ubuntu core and GUI
  plus Ubuntu remaining. Windows agents failed after 1,129 passes because a
  test required POSIX directory-descriptor opens on a host where `os.stat`
  lacks `dir_fd`; Windows remaining failed after 1,819 passes because a test
  required POSIX unlink-and-replace semantics while the open lock correctly
  held Windows sharing authority. Ubuntu agents remained anomalously in
  progress for hours; four prior safe-WSL runs and the post-repair run below
  complete the same shard in about 50 seconds, so the hosted job is not treated
  as passing evidence.
- Report-artifact tests now require real POSIX replacement detection on POSIX
  and real WinError 5/32 replacement denial followed by verified original-byte
  completion on Windows. Directory-descriptor fault tests run only where both
  required APIs support `dir_fd`; fallback-path fault coverage remains active
  on Windows. Lock tests make the same explicit split while preserving
  identity-checked acquisition and `unlink=False` ownership on the Windows
  no-replacement branch. Symlink skips remain limited to local WinError 1314.
- A no-`-x` native-Windows agent/reporting run exposed three additional test
  portability defects without changing product behavior: a Cyrillic vault
  fixture now writes explicit UTF-8; the generation flush test requires one
  file flush on Windows and the same file plus two directory flushes on POSIX;
  and the genuine 10 MiB+1 invalid PNG case uses a bounded pytest ID so
  `PYTEST_CURRENT_TEST` cannot exceed Windows' environment limit. Two recovery
  tests now use the coordinator's serialized `reconcile_once()` barrier instead
  of a racy 100 ms scheduler poll; the three-node boundary repeated **20/20**
  for **60 passes** after a pre-fix failure reproduced on repeat 11.
- Native Windows evidence: report-process plus instance-lock modules **64
  passed, 13 intentional platform/privilege skips**; the new portability nodes
  **5 passed**; the expanded shard reached **1,445 passed, 35 skipped, 1
  deselected**, with only 17 local WinError-1314 symlink-creation failures plus
  the then-unfixed sibling timing poll. The repaired recovery boundary then
  supplied the 60-pass repeat above. Safe WSL2 Ubuntu 24.04 evidence: report
  process **64 passed**, instance lock **13 passed**, new portability nodes **5
  passed**, and the full agent/reporting shard **1,494 passed, 4 skipped, 1
  deselected** in 49.75 seconds. Ruff and `git diff --check` passed.
- Independent report, lock, portability, and final frozen-diff reviews: **PASS,
  no P0-P3**. The reviewed patch ID is
  `974b8c88ec2baf43deb6028c5862933974abfb2d`. A new exact-SHA hosted run remains
  mandatory after publication.
- D7.2 removes inferred vendor/channel identity from GUI presentation. Exact
  descriptor tuple authority, bounded unavailable/fault states, cached
  transition-only styling, design-system governance, focused **56-pass** main
  evidence, and the independent **PASS, no P0-P3** verdict are integrated as
  local commit `dcf1a82`; no physical or hardware gate is closed by it.

## 2026-07-14 fifth hosted CI adjudication and reviewed D7.4 integration

- Exact-SHA run `29305772213` at `fb420b0` passed Windows/Ubuntu agents, core,
  and GUI. This closes the prior Windows portability failures and the anomalous
  hosted Ubuntu agent stall at that SHA. Both remaining jobs stopped at the
  same architecture guard after **310 passed, 2 skipped**: D7.2's passive
  instruments panel intentionally imports the canonical descriptor contract,
  but the exact approved-importer set had not been updated. The guard now names
  only that observational adapter; it grants no source or control authority.
- A native-Windows no-`-x` remaining shard reached **2,173 passed, 83 skipped**
  and exposed the later host-contract cluster in one run. Five
  positive POSIX pipe/mode/replacement handshake tests and one POSIX `pass_fds`
  capability test now carry exact host markers; cross-platform denial, partial
  environment, descriptor stripping, and PID-hint validators remain active.
  Architecture source reads use explicit UTF-8. A Windows symlink setup skips
  only WinError 1314; the real-directory lost-authority proof remains active.
- Focused native Windows evidence for the remaining-shard repair: **12 passed
  including the two importer guards, 18 intentional capability/privilege
  skips**. Safe WSL2 Ubuntu 24.04 focused evidence: **30 passed** including the
  two importer guards. The full safe-WSL remaining shard reached **2,266
  passed, 11 skipped**; its only two failures were `_RunnerActivationDisabled`
  because the local checkout deliberately lacked the workflow-created and
  verified `.venv/bin/python` alias. With that exact alias temporarily bound to
  the same safe interpreter, both strict exact-six nodes passed **2/2**, and the
  alias was removed afterward. No H4 interpreter authority was relaxed. Ruff
  check/format and `git diff --check` passed. Independent final review: **PASS,
  no P0-P3**.
- Claude delivered D7.4 as a test-only real-localhost ZeroMQ suite. Direct
  cherry-pick of its original `be50f07` onto current main produced **14 passed,
  5 failed** because that branch carried stale D7.1 wiring. No stale production
  commit was imported. The suite was adapted to current production seams: the
  real app drain helper, the real private launcher invalidation wrapper, exact
  branch-level AST checks, and OS-uptime-independent watchdog triggering.
- The adapted D7.4 suite exercises real `ZMQPublisher`, real `ZmqBridge`
  subprocesses, canonical descriptor envelopes, mixed qualified/legacy/
  malformed/capacity batches, all three launcher restart paths with
  invalidate-before-start capture, both GUI launch paths, and repeated socket
  shutdown/rebind. Engine/timer pieces alone are stubbed; app closure restart
  branches remain honestly static plus shared-invariant evidence. Native
  Windows passed **19/19** three consecutive times; safe WSL passed **19/19**.
  Ruff check/format and diff check passed. Independent adaptation review:
  **PASS, no P0-P3**. Integrated test-only commit: `c150d4c`.
- A new exact-SHA hosted run is mandatory after publication. Physical hardware,
  frozen-build, and soak-duration gates remain open.

## 2026-07-14 sixth hosted CI adjudication and Windows sentinel hardening

- Exact-SHA run `29309849548` at `95b712f` passed all four Ubuntu jobs plus
  Windows agents, core, and GUI. Windows remaining reached **1,883 passed, 93
  skipped** before the genuine launcher lifecycle test exposed a broken-link
  shutdown-sentinel gap: Windows create-exclusive open followed a pre-existing
  broken symlink, created its external target, and initially treated the open
  as sufficient graceful-shutdown authority.
- The shutdown path now rejects any pre-existing link/reparse/multi-link object
  before opening. A newly opened object must still match `lstat` and `fstat`
  identity, be an ordinary single-link file, and remain under the captured
  data/runtime directory identities before it can authorize the graceful wait.
  The bounded fallback remains terminate(10 seconds) then kill(5 seconds).
- Independent review found that the first repair still allowed pathname cleanup
  to delete a replacement installed during the wait and allowed an unsafe
  hardlink entry to be removed. The final repair performs no pathname unlink:
  per-launch UUID sentinel names remain inert, while broken-link targets,
  hardlinks, and post-validation replacements cannot be deleted by the
  launcher. Regression tests assert all three properties.
- Native Windows full launcher-runtime evidence on Python 3.14: **34 passed, 5
  exact WinError-1314 symlink-privilege skips**. Independent focused evidence:
  **5 passed, 3 exact privilege skips**. Ruff check/format and `git diff
  --check` passed. Final sentinel review and documentation review: **PASS, no
  P0-P3**.
- The previously used local WSL distro was not registered in this Windows
  session, and restoration was blocked by the environment installation gate;
  no Linux result is claimed for this new sentinel slice. A new exact-SHA
  hosted Ubuntu/Windows run remains mandatory. Physical hardware,
  frozen-build, and soak-duration gates remain open.

## 2026-07-14 native Windows broad-suite inventory

- A no-`-x` Python 3.14 run reached 60% before its bounded ten-minute stop; after
  forced termination, the interrupted process reported a Qt/Python access
  violation, so that attempt is not a suite verdict. A second run stopped
  normally at 20 failures after **1,973 passed, 2 skipped, 1 deselected** in
  162 seconds and supplied the bounded first-20-failure inventory.
- Thirteen failures were exact WinError-1314 symlink-creation privilege
  artifacts across assistant, archive, and path-jail tests. The affected
  topologies and combined symlink/hardlink cases were inventoried separately;
  no broad Windows skip, mock substitute, or production relaxation was added.
  Hosted agents/core jobs at `95b712f` had already passed these areas, while
  the local account cannot execute the symlink-specific property without the
  OS capability.
- Five SQLite gate assertions were contaminated by the machine's ambient
  `CRYODAQ_ALLOW_BROKEN_SQLITE=1`. The module fixture now removes that variable
  only inside each test and restores the caller environment afterward; the
  explicit override test still sets `1` and proves the warning/override
  contract. The full module passed **14/14** while launched under a deliberately
  hostile ambient `1`; production fail-closed logic is unchanged.
- Four Cyrillic safety YAML fixtures now write explicit UTF-8 to match the
  production UTF-8 reader. The load-config selection passed **9/9** on native
  Windows. One cross-kind delivery test replaced a racy 100 x 1 ms poll with
  the coordinator's lock-serialized `reconcile_once()` barrier while retaining
  exact `DELIVERY_UNKNOWN`, error-code, and receipt assertions; it passed
  **20/20** separate repetitions.
- Ruff check and `git diff --check` passed. Independent SQLite/UTF-8 and
  delivery-barrier reviews: **PASS, no P0-P3**. These are deterministic
  test-isolation repairs, not new physical, hardware, frozen-build, or full-CI
  evidence.
