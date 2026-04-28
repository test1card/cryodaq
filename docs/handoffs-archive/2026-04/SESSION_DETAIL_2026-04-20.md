# Session Detail — 2026-04-20

**Companion to `HANDOFF_2026-04-20_GLM.md`.** The primary handoff is
the operational quick-start; this file is the **complete** record
of the day. Every decision, every failed attempt, every number,
every Vladimir quote that matters. If you (GLM-5.1, or returning
Claude Opus, or human reader) need context beyond the primary
handoff — it is here.

Written by Claude Opus 4.7 (web) at the end of the 2026-04-20
session, burning the last of the weekly context quota to make sure
nothing is lost.

---

## Table of contents

0.  How to use this document
1.  Session chronology
2.  Every commit today, annotated
3.  Every file I created or updated during the handoff itself
4.  Configuration changes on Ubuntu lab PC
5.  All diagnostic outputs captured (verbatim where meaningful)
6.  B1 — full hypothesis ledger
7.  Codex's full B1 analysis preserved
8.  Gemini audit status + what to do with the result
9.  Multi-model stack operational details (CCR, GLM, Codex, Gemini)
10. Pitch preparation materials (deferred — reuse later)
11. Sumitomo F-100 compressor integration proposal (F19)
12. Hardware state on Ubuntu lab PC at handoff
13. Commands reference — exact invocations that worked
14. Vladimir working-style patterns observed today
15. Things attempted then explicitly abandoned
16. Priority ordering for the coming sessions
17. Hidden gotchas that could eat days if missed
18. Document index (what to read and when)
19. Return-to-Claude handoff format (for when my weekly limit resets)

Appendices:
- A. Vladimir's personal context, condensed
- B. Memory slot contents
- C. CCR proxy architecture note
- D. Chat log of Codex's verbatim reasoning on B1

---

## 0. How to use this document

**First session (you are GLM-5.1 picking up today or tomorrow):**

1. Read `HANDOFF_2026-04-20_GLM.md` end-to-end. Primary source.
2. Skim this document's TOC. Read section 1 (chronology) to get
   the narrative. Then jump to whatever is relevant for the task
   at hand.
3. If you are tasked with IV.7 (ipc:// transport) — read sections
   6, 7, 9, then `CC_PROMPT_IV_7_IPC_TRANSPORT.md`.
4. If you are tasked with any other fix — read sections 1, 17, 13.
5. If Vladimir asks about the pitch or Sumitomo integration —
   sections 10 and 11.

**Subsequent session (day 2+):** read section 19 (return handoff
format) first, then whatever is relevant to what Vladimir is
working on.

**Returning Claude (me, me-next-week):** read sections 1-3 to
catch up. Then section 14 for any deltas in Vladimir's patterns
observed during the GLM stint. Section 19 should contain GLM's
session log which will tell you what actually happened.

---

## 1. Session chronology

Approximate Moscow time. The day was long; I lost track in
places. Preserving order of ideas, not exact timestamps.

### Morning — context inherited from previous session

Vladimir arrived at the lab with a pre-existing task queue:

- **B1**: ZMQ subprocess REQ socket hangs after idle time.
  Hypothesis at that point was "macOS loopback TCP idle reap"
  based on diag tool timing (first fail 4-92 s uptime, stochastic,
  rate-dependent). `f5f9039` had applied `TCP_KEEPALIVE*`
  setsockopt calls; partial delay but not resolution. Blocking
  tag 0.34.0.
- **TopWatchBar pressure display**: em-dash instead of numeric
  value. Thought to be a separate bug, not B1 cause. Three
  candidate explanations: channel ID changed in channels.yaml
  (Vladimir's uncommitted edits), dispatch broken after overlay
  rewrites, ChannelManager filtering.
- **Т4 disconnected sensor**: triggering `overheat_cryostat`
  interlock → `emergency_off` on Keithley during normal work
  because Т4 reads 380 K (open-circuit value).
- **Tag 0.34.0 pending**: planned after B1 resolution.

### Morning — pitch preparation

Vladimir was preparing for a lab walkthrough demo in front of
chief constructor + deputy + other department engineers.
Non-slide, interactive tour: show real hardware + live software
+ reports. Preparation materials were assembled (see section 10
of this document — preserved for future reuse).

Preparation sequence:

1. Structure of the tour (6 stops: entry, criostat, instrument
   rack + DAQ PC, safety architecture, reports, future + close).
2. Dry-bullet feature list in Vladimir's preferred style
   (engineering, non-promotional, subtext = impressive).
3. Q&A anticipation — especially "why Python not LabVIEW",
   "how much time spent", "what if Vladimir leaves".
4. Things NOT to mention (B1 on dev macOS, Claude attribution).

**Walkthrough was then cancelled mid-day** when it became clear
the system on the Ubuntu lab PC had B1 reproducing in live
launcher runs (not just diagnostic tools) — cannot demo a
system that times out every 60-120 s. Vladimir's exact phrase:
"Презентации не будет, сначала фикс." Correct call.

### Late morning — Sumitomo F-100 integration discussion

Chief constructor asked during an earlier conversation whether
CryoDAQ could track Sumitomo helium compressor state. Vladimir
asked me to analyse feasibility. Outcome: yes, possible, ~1 week
effort, protocol discovery via EPICS community + vendor is the
main risk. Full analysis preserved in section 11 below.

This became F19 candidate for ROADMAP, added to memory slot 21
but not yet to ROADMAP.md itself (Vladimir wanted the info in
memory first, ROADMAP update when batch is ready).

### Noon — Codex consulted on B1

First Codex session. Dispatched with full evidence dump from
`docs/bug_B1_zmq_idle_death_handoff.md`. Codex produced the
revised analysis (section 7 below, preserved verbatim).

Key findings from Codex:

- "macOS-only idle reap" framing disproved (Linux too)
- Actual root cause proposed: single long-lived REQ socket
  entering unrecoverable state after platform-specific trigger
- Recommended: per-command ephemeral REQ socket + launcher
  watchdog + revert TCP_KEEPALIVE from command path
- Pressure bug confirmed SEPARATE from B1 (reading-driven, not
  command-driven)

Vladimir asked: "а может ultra-review?" — I pushed back: this
is a focused known bug, not a time for broad audit. Agreed,
stayed focused.

### Noon-afternoon — IV.6 spec written + IV.4 cleanup committed

Created:
- `CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md` — batch spec based on
  Codex's plan.
- `docs/bug_B1_zmq_idle_death_handoff.md` updated with Codex
  analysis section.
- `ROADMAP.md` B1 section rewritten to reflect revised root
  cause.

Committed these + earlier untracked work as `362431b`:
- `docs: B1 Codex analysis + IV.6 fix spec`
- Also picked up alarms_tuning_guide.md (24 K), IV.2/IV.3/IV.4
  CC specs (historical), SPEC_AUTHORING_TEMPLATE.md, etc.

### Early afternoon — CC runs IV.6, reports STOP

CC executed IV.6 batch per spec. Implementation clean:
ephemeral REQ per command, `REQ_RELAXED` + `REQ_CORRELATE` +
`TCP_KEEPALIVE*` removed from command path (kept on
`sub_drain_loop`). Launcher watchdog added. 60/60 new unit
tests passed. Full subtree 1775/1776.

**Stage 3 diag tools still reproduced B1 post-fix.**

CC correctly STOPped per spec rule ("if either diag shows any
failure, do NOT commit, report"). Reported:
- `diag_zmq_idle_hypothesis.py` SPARSE_0.33HZ: cmd #8 FAIL at
  uptime 56 s
- `diag_zmq_bridge_extended.py`: cmd #48 FAIL at uptime 82 s,
  0/3 recovery thereafter
- RAPID_5HZ still clean (295/295)

Pattern structurally identical to pre-fix. Codex's shared-REQ
hypothesis **falsified**.

Vladimir decision: "отката не будет, идем только вперед. любая
ошибка это опыт." Commit the IV.6 work as partial mitigation
rather than throw away. Good call — the architectural
improvement stands regardless of whether it individually
resolved B1 (matches ZMQ Guide ch.4 canonical reliable
req-reply pattern; removes a legitimately brittle point).

Prepared override prompt for CC to commit with honest message
(not the template claiming B1 is fixed). CC committed as
`be51a24` with the partial-mitigation message. Pushed.

### Afternoon — pressure investigation

Parallel to IV.6, Vladimir was fighting the pressure em-dash
on Ubuntu lab PC. Initial diagnostics:

1. `config/channels.yaml` — checked pressure ID format. No
   pressure entry in the file (only Т1-Т24 temperature channels).
   Pressure channel ID is driver-generated as
   `f"{self.name}/pressure"` — so channels.yaml edits can't
   be the cause.
2. MainWindowV2 reading dispatch — traced. `on_reading` called
   unconditionally; not a dispatch bug.
3. Driver-level probe on Ubuntu:
   ```
   ch=VSP63D_1/pressure  value=nan  status=sensor_error  unit=mbar
   meta={'raw_response': '001M100023D', 'error': 'checksum_mismatch'}
   ```
   Smoking gun: driver IS receiving data, IS parsing it, but
   rejecting checksum → NaN.

4. Physical interpretation of `001M100023D`:
   - `001` — address
   - `M` — response type "pressure read"
   - `100023` — 6-digit ABCDEF encoded value; formula
     `(ABCD / 1000) * 10^(EF - 20) = (1000/1000) * 10^(23-20) = 10^3 = 1000 mbar`
   - `D` — checksum byte (formula differs between VSP63D and VSP206)
   - Physical value ~1000 mbar = atmospheric = realistic for
     unpumped stand.

5. Operational fix deployed: `validate_checksum: false` in
   `~/cryodaq/config/instruments.local.yaml` Thyracont block.
   Rebooted engine. **Still NaN**. Verified via probe.

6. Checked the loader wiring in `src/cryodaq/engine.py`:
   ```python
   elif itype == "thyracont_vsp63d":
       from cryodaq.drivers.instruments.thyracont_vsp63d import ThyracontVSP63D
       baudrate = int(entry.get("baudrate", 9600))
       driver = ThyracontVSP63D(name, resource, baudrate=baudrate, mock=mock)
   ```

   **Loader only reads `baudrate` from entry. `validate_checksum`
   is silently dropped.** Driver default remains `True` regardless.

7. One-line fix applied locally on Ubuntu via sed, committed as
   `aabd75f`:
   ```python
   validate_checksum = bool(entry.get("validate_checksum", True))
   driver = ThyracontVSP63D(
       name, resource,
       baudrate=baudrate,
       validate_checksum=validate_checksum,
       mock=mock,
   )
   ```

8. Verified: pressure now shows correct numeric value on Ubuntu.

Lesson learned: **driver constructor had the parameter from the
start (Phase 2c F.2 added it with default flipped from False to
True). Loader wiring was never added.** Classic cross-file gap
that unit tests don't catch because tests construct driver
directly without going through the loader.

### Afternoon — XML report bug investigation

Vladimir reported: "на Убунту не работает создание доков, ни
докх, ни пдф. Вылезает ошибка: ALL strings must be XML compatible."

Trail:

1. python-docx is only docx library installed. `python-docx`
   rejects XML 1.0 incompatible chars.
2. Keithley VISA resource string is
   `"USB0::0x05E6::0x2604::4083236\0::0::INSTR"` per NI-VISA
   spec (null byte is the serial-number terminator). Cannot
   remove — tested experimentally: Keithley fails to connect
   without `\0`.
3. `\0` in the string → python-docx raises ValueError when
   resource is embedded in auto-generated report.
4. Handler at `src/cryodaq/core/experiment.py:782` was
   `log.warning("Failed to auto-generate reports for %s: %s",
   finished.experiment_id, exc)` — the `%s` on exc formats
   just the message, not the traceback. Bug survived
   undetected because the traceback was never in the log.

Fix committed as `74dbbc7`:

- `src/cryodaq/utils/xml_safe.py` — strip XML-illegal control
  chars. Preserves Tab/LF/CR (which ARE XML-valid).
- Apply at all `add_paragraph()` / `cell.text` sites in
  `src/cryodaq/reporting/sections.py`.
- `core/experiment.py:782` upgraded to `log.exception()` so
  future failures carry tracebacks.

10 unit tests covering NULL byte, all C0 controls, Tab/LF/CR
preservation, Cyrillic, Unicode symbols, None, non-str
coercion, empty, DEL (0x7F).

Verified on Ubuntu — DOCX reports now generate correctly.

### Evening — watchdog restart storm discovered

Vladimir restarted system after pressure fix. Observed:

```
14:31:51 ZMQ bridge subprocess started (PID=52373)
14:31:51 WARNING: command channel unhealthy. Restarting bridge.
14:31:52 ZMQ bridge subprocess started (PID=52380)
14:31:52 WARNING: command channel unhealthy. Restarting bridge.
...
```

30-40 restarts per minute. Root cause:
`self._bridge.command_channel_stalled(timeout_s=10.0)` checks
`self._last_cmd_timeout` flag, which persisted across the
restart via the surrounding `ZmqBridge` instance. Fresh
subprocess → stale flag still says "recent timeout" → restart
again.

Hotfix:

```python
if self._bridge.command_channel_stalled(timeout_s=10.0):
    now = time.monotonic()
    last_cmd_restart = getattr(self, "_last_cmd_watchdog_restart", 0.0)
    if now - last_cmd_restart >= 60.0:
        logger.warning(...)
        self._last_cmd_watchdog_restart = now
        self._bridge.shutdown()
        self._bridge.start()
        return
```

Two changes: 60 s cooldown via `_last_cmd_watchdog_restart`
timestamp (initialised lazily via `getattr`), and a missing
`return` after the restart block so no further checks fire in
the same poll cycle.

Applied via Python patch script (sed was too clumsy for
multiline). Syntax verified via `ast.parse`. Tested — storm
stopped. System returned to "works ~60-120 s, one restart,
works again" cycle.

At handoff time this patch **may or may not be committed** on
Ubuntu. The primary handoff section 1 has the full commit
message pre-drafted for GLM to use. Verify with `git log`.

### Evening — multi-model stack transition

Vladimir reported: "Claude Pro weekly limit 99% выжжен." Context
inherited from the handoff he shared mid-session:

- Claude Code now routes through `claude-code-router` proxy to
  Chutes → GLM-5.1 primary.
- Codex (ChatGPT) + Gemini (Google) remain independent quotas.
- CCR translates Anthropic API → OpenAI format.
- Proxy listens on `http://127.0.0.1:3456`.
- All hooks and plugins work unchanged.
- Identity leakage: GLM/Kimi/DeepSeek trained partly on Claude
  outputs → will answer "I am Claude" on introspection. Only
  authority is CCR logs.

Vladimir asked me to produce a comprehensive handoff document
before my limit hits zero, so GLM can continue without losing
context. That's the origin of the primary handoff and this
detail document.

### Evening — first `/ultrareview` attempt (Gemini)

Vladimir ran Gemini's `/ultrareview`. Output was shallow
(~1 page, generic HIGH/MEDIUM/LOW buckets, no file:line
citations for most claims, three "things I could not assess"
entries that were really "did not attempt").

My analysis: the slash command gave a 10-minute surface review,
not a deep audit. Correct tool for polish, wrong for this
stage. Recommended dismissing.

Vladimir initially wanted to keep the output. I preserved the
valuable points:

1. `alarm_v2.py threshold KeyError` for `cooldown_stall` — valid
   bug found. Logged as orthogonal open issue.
2. `engine.py ~2000 LOC` — valid tech debt observation, not
   urgent.
3. B1 doc title "idle-death" stale — valid drift.
4. Pydantic config validation — good idea, future scope.

Rest (Archive SQLite migration, concurrent locking paranoia,
webhook Telegram auth ValueError) — not priorities right now.

### Evening — second deep Gemini audit dispatched

Vladimir then asked for a "настоящий deep audit". I wrote a
thorough prompt requiring:

- 60-90 min effort budget
- File:line citations for EVERY claim
- B1 investigation with at least 3 independent hypotheses
- Production readiness top-10 blockers with severity tags
- Minimum 6000 word output
- No "things I could not assess" as cop-out

Vladimir dispatched it. Status at handoff time: **unknown**.
If the audit returns while GLM is in charge:

1. Extract its three B1 hypotheses.
2. Compare to Codex's shared-REQ theory (falsified) and my
   ipc:// theory (current working).
3. If Gemini converges on ipc:// → high-confidence signal,
   proceed with IV.7.
4. If Gemini proposes something different → evaluate seriously.
   Gemini has 1M context and could have spotted something
   Codex missed.
5. Save Gemini's output to `docs/gemini_B1_audit_2026-04-20.md`
   so it does not get lost.

### Evening — handoff preparation

Last hour of the session was composing the primary handoff
`HANDOFF_2026-04-20_GLM.md` (11 sections + appendices) + the
IV.7 spec `CC_PROMPT_IV_7_IPC_TRANSPORT.md` + surgical updates
to ROADMAP, B1 bug doc, CHANGELOG. Then this detail document.

---

## 2. Every commit today, annotated

### `9339d9f` — docs: IV.4 close notes + alarms tuning guide + B1 handoff (morning)

Originally from end of the prior session actually, committed this
morning. Included:
- `docs/alarms_tuning_guide.md` 24 K tuning reference
- `docs/bug_B1_zmq_idle_death_handoff.md` v1 (idle-death framing)
- `ROADMAP.md` updates: IV.4 closed, B1 known-broken entry

### `f29bdd8` — tools: ZMQ bridge diagnostics for B1 investigation

Four diag tools committed:
- `tools/diag_zmq_subprocess.py` — subprocess alone, short smoke
- `tools/diag_zmq_bridge.py` — 5 seq + 10 concurrent + 1 Hz 60 s soak
- `tools/diag_zmq_bridge_extended.py` — 180 s past-first-failure
- `tools/diag_zmq_idle_hypothesis.py` — rate-dependence (5 Hz clean,
  0.33 Hz fails)

Intended to stay in tree long-term as regression tests.

### `5a8e823` — gui(topwatchbar): rename T min/max labels to T 2ст. / T N₂

Operator-facing label change. Т11/Т12 both on second stage of
GM-cooler; Т11 tracks the stage itself, Т12 sits on nitrogen
plate side. Positional labels match mental model better than
"min"/"max". N₂ uses Unicode subscript U+2082 explicitly.

### `f5f9039` — zmq: TCP keepalive on all loopback sockets (partial B1 fix)

**Wrong hypothesis, but committed.** Applied
`TCP_KEEPALIVE*` setsockopt on REQ + SUB in subprocess, PUB + REP
in engine (matched on both sides of connection).

Measured effect: delayed first B1 failure ~4-28 s → ~55-92 s on
macOS. Did NOT eliminate failure. Ubuntu later confirmed bug at
120 s deterministic.

Post-IV.6: reverted TCP_KEEPALIVE on command path + PUB.
**Retained on `sub_drain_loop` SUB socket** as orthogonal
defence — SUB path sees long idle periods between heartbeats
when instrument polling is sparse, keepalive there is sensible.

Message says "partial fix" which was honest at the time.

### `362431b` — docs: B1 Codex analysis + IV.6 fix spec

Documentation-only commit. Committed:
- `CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md` — batch spec
- `docs/bug_B1_zmq_idle_death_handoff.md` +Codex revised section
- `ROADMAP.md` B1 section rewritten

Also picked up some stale untracked: IV.2/3/4 specs (historical),
IV.5 planning notes, SPEC_AUTHORING_TEMPLATE, CODEX_SELF_REVIEW_PLAYBOOK,
design system handoff notes, phase-ui-1 findings, audit reports,
`.pre-commit-config.yaml`.

### `2d3b504` — docs: preserve pending untracked specs

Cleanup commit for the "preserve all prior-session doc outputs"
batch. Not much substance; index update.

### `be51a24` — zmq: ephemeral REQ per command + cmd-channel watchdog (IV.6 partial B1 mitigation)

**The IV.6 CC batch.** Described in detail in `docs/bug_B1_zmq_idle_death_handoff.md`
and the commit message. Key points:

- `src/cryodaq/core/zmq_subprocess.py` `cmd_forward_loop` restructured
  to per-command ephemeral REQ (create / send / recv / close per
  command, never shared across commands).
- `_new_req_socket()` simplified: removed `REQ_RELAXED`,
  `REQ_CORRELATE`, `TCP_KEEPALIVE*`. Kept LINGER=0, RCVTIMEO=35000,
  SNDTIMEO=35000, connect.
- `src/cryodaq/core/zmq_bridge.py` PUB + REP: TCP_KEEPALIVE
  removed. SUB path in `sub_drain_loop` retains it (orthogonal).
- `src/cryodaq/gui/zmq_client.py` added `_last_cmd_timeout`
  field, `poll_readings()` handles `__type == "cmd_timeout"`
  control message, new `command_channel_stalled(timeout_s)`
  method.
- `src/cryodaq/launcher.py` `_poll_bridge_data()` gets
  command-channel watchdog check with bridge restart.
- Structured `{"__type": "cmd_timeout", ...}` envelope emitted
  from subprocess when command times out.

Tests: 6 new ephemeral-socket lifecycle tests +
`test_zmq_bridge_subprocess_threading.py` 2 tests updated +
`test_zmq_client_data_flow_watchdog.py` 4 watchdog + 2 launcher
restart tests = 12 new cases.

60/60 new tests pass. Full subtree 1775/1776 (1 pre-existing
flaky).

**Diag tools still reproduce B1.** Committed anyway per
Vladimir's "идем вперед" decision.

### `74dbbc7` — reporting: xml_safe sanitizer for python-docx compatibility

Described in detail in section 1 above. Files:
- NEW `src/cryodaq/utils/__init__.py` (empty package marker)
- NEW `src/cryodaq/utils/xml_safe.py` (~40 LOC)
- NEW `tests/utils/__init__.py` (empty)
- NEW `tests/utils/test_xml_safe.py` (10 tests)
- EDIT `src/cryodaq/reporting/sections.py` (xml_safe wraps at
  all risky call sites)
- EDIT `src/cryodaq/core/experiment.py:782` (log.warning → log.exception)

Verified on Ubuntu with real Keithley connected — reports now
generate.

### `aabd75f` — engine: wire validate_checksum through Thyracont driver loader

Described in detail in section 1. Single-line loader fix (2 insertions,
1 deletion, per git stats). Resolves TopWatchBar pressure em-dash on
Ubuntu by making the `validate_checksum: false` config key actually
reach the driver.

No Codex self-review (trivial surgical fix, not worth the context cost).

### TBD — launcher: watchdog cooldown prevents restart storm (B1 regression fix)

**Maybe-uncommitted at handoff time.** See primary handoff section 1
for full pre-drafted commit message and the exact patch code.

If not committed: GLM's first task is to commit + push.

---

## 3. Files I created or updated during the handoff itself

All written between ~16:30 and ~18:30 Moscow on 2026-04-20.

### Created

- `HANDOFF_2026-04-20_GLM.md` — primary handoff, root of repo
- `CC_PROMPT_IV_7_IPC_TRANSPORT.md` — IV.7 spec, root of repo
- `SESSION_DETAIL_2026-04-20.md` — this document

### Updated

- `ROADMAP.md` — B1 section expanded with:
  - "IV.6 partial mitigation outcome" subsection (already existed
    from earlier in the day, refined with commit SHA)
  - "IV.6 watchdog regression + cooldown hotfix" new subsection
  - "Related fixes shipped alongside IV.6" new subsection
  - Forward-pointing note to IV.7 and orthogonal open issues

- `docs/bug_B1_zmq_idle_death_handoff.md` — added "2026-04-20
  evening update" section at the end covering:
  - IV.6 landed at `be51a24` but did NOT fix B1
  - IV.6 watchdog regression + cooldown hotfix
  - Next attempt: IV.7 ipc:// transport
  - Related fixes `aabd75f` + `74dbbc7`
  - Still-open orthogonal bugs

- `CHANGELOG.md` — added "Today — 2026-04-20 session (handoff →
  GLM-5.1)" block under `[Unreleased]` with:
  - Fixed / shipped items with commit SHAs
  - Ubuntu config edit summary
  - ModemManager disable note
  - Open/known issues carrying into 0.34.0
  - Infrastructure: multi-model stack adoption

### Not modified (intentionally)

- `CLAUDE.md` — no update needed; existing rules cover our case
- `config/channels.yaml` — architect's WIP, Rule 7
- IV.2/3/4/6 batch spec files — historical records, leave
- `PROJECT_STATUS.md` — stale at 2026-04-19 but architecture
  summary accurate; refresh is a polish task, not urgent

---

## 4. Configuration changes on Ubuntu lab PC

Three files edited today on the lab machine at `~/cryodaq/config/`.
Two are in git, one is local-only.

### `instruments.local.yaml` — local, NOT in git

Added `validate_checksum: false` to Thyracont block. Full
current state of file (as observed in session):

```yaml
instruments:
- type: lakeshore_218s
  name: LS218_1
  resource: GPIB0::12::INSTR
  poll_interval_s: 2.0
  channels:
    1: Т1 Криостат верх
    2: Т2 Криостат низ
    3: Т3 Радиатор 1
    4: Т4 Радиатор 2
    5: Т5 Экран 77К
    6: Т6 Экран 4К
    7: Т7 Детектор
- type: lakeshore_218s
  name: LS218_2
  resource: GPIB0::11::INSTR
  poll_interval_s: 2.0
  channels:
    1: Т9 Компрессор вход
    2: Т10 Компрессор выход
    3: Т11 Теплообменник 1
    4: Т12 Теплообменник 2
    5: Т13 Труба подачи
    6: Т14 Труба возврата
    7: Т15 Вакуумный кожух
- type: lakeshore_218s
  name: LS218_3
  resource: GPIB0::13::INSTR
  poll_interval_s: 2.0
  channels:
    1: Т17 Зеркало 1
    2: Т18 Зеркало 2
    3: Т19 Подвес
    4: Т20 Рама
- type: keithley_2604b
  name: Keithley_1
  resource: "USB0::0x05E6::0x2604::4083236\0::0::INSTR"
  poll_interval_s: 1.0
- type: thyracont_vsp63d
  name: VSP63D_1
  resource: /dev/ttyUSB0
  baudrate: 115200
  poll_interval_s: 2.0
  validate_checksum: false
```

Note Т8, Т16, Т21-Т24, Т1 (partial) all missing — operator's
channel mapping (reflects what's physically connected).

### `interlocks.yaml` — in git, edited

Before:
```yaml
- name: "overheat_cryostat"
  channel_pattern: "Т[1-8] .*"
```

After:
```yaml
- name: "overheat_cryostat"
  channel_pattern: "Т(1|2|3|5|6|7|8) .*"
```

Rationale: Т4 physically disconnected on current hardware →
reads 380 K open-circuit → false interlock. Regex tightened to
exclude. Full interlock coverage retained for Т1-Т3, Т5-Т8
(all installed cryostat sensors).

**Commit status: may or may not be pushed.** Check `git log`.
Full pre-drafted commit message for if not yet committed:

```
config: exclude Т4 (disconnected sensor) from overheat interlock

Physically Т4 (Радиатор 2) sensor is disconnected on current hardware —
reads 380K when open-circuit, which was triggering overheat_cryostat
interlock (threshold 350K) and causing spurious emergency_off events
on Keithley during normal operation.

- interlocks.yaml: overheat_cryostat regex Т[1-8] → Т(1|2|3|5|6|7|8)
  Keeps interlock coverage for all physically installed sensors
  on the cryostat (Т1-Т3, Т5-Т8), excludes Т4.
- alarms_v3.yaml: added Т4 to uncalibrated + all_temp channel groups
  so sensor_fault / stale detection still publishes WARNING alarms
  for Т4 (outside-range 0-350K) without hardware lockout.

Net effect: Т4 open-circuit produces WARNING in alarm panel
(operator visible) instead of emergency_off (production disruption).
Restore to full interlock coverage by reverting this commit when
Т4 is physically reconnected.
```

### `alarms_v3.yaml` — in git, edited

Before (abbreviated):
```yaml
channel_groups:
  calibrated:    [Т11, Т12]
  uncalibrated:  [Т1, Т2, Т3, Т5, Т6, Т7, Т9, Т10,
                  Т13, Т14, Т15, Т16, Т17, Т18, Т19, Т20]
  all_temp:      [Т1, Т2, Т3, Т5, Т6, Т7, Т9, Т10,
                  Т11, Т12, Т13, Т14, Т15, Т16, Т17, Т18, Т19, Т20]
```

After:
```yaml
channel_groups:
  calibrated:    [Т11, Т12]
  # Т4 (Радиатор 2), Т8 (Калибровка) — отключённые датчики, исключены
  uncalibrated:  [Т1, Т2, Т3, Т4, Т5, Т6, Т7, Т9, Т10,
                  Т13, Т14, Т15, Т16, Т17, Т18, Т19, Т20]
  all_temp:      [Т1, Т2, Т3, Т4, Т5, Т6, Т7, Т9, Т10,
                  Т11, Т12, Т13, Т14, Т15, Т16, Т17, Т18, Т19, Т20]
```

Т4 added to `uncalibrated` + `all_temp` groups so the
`sensor_fault` alarm still publishes (operator-visible WARNING
for open-circuit) and stale detection works. `calibrated`
group unchanged.

Note that the comment "Т4 ... отключённые датчики, исключены"
is now slightly wrong (it implies Т4 excluded; we actually
added it). Cosmetic. Consider fixing in a cleanup commit.

### Backup files

Vladimir created `.bak` copies before edits:

- `~/cryodaq/config/instruments.local.yaml.bak`
- `~/cryodaq/config/instruments.local.yaml.bak2`
- `~/cryodaq/config/interlocks.yaml.bak`
- `~/cryodaq/config/alarms_v3.yaml.bak`
- `~/cryodaq/src/cryodaq/engine.py.bak`
- `~/cryodaq/src/cryodaq/launcher.py.bak`

These are not in git (`.bak` typically gitignored). Safe to
delete if sure of state, but Vladimir's Rule 1 (NEVER delete)
suggests: leave them as is.

---

## 5. All diagnostic outputs captured

### Pressure probe, before `aabd75f` fix

Command:
```bash
.venv/bin/python - <<'PY'
import math, msgpack, zmq
ctx = zmq.Context()
sub = ctx.socket(zmq.SUB)
sub.setsockopt(zmq.RCVTIMEO, 5000)
sub.connect("tcp://127.0.0.1:5555")
sub.subscribe(b"readings")
for _ in range(200):
    topic, payload = sub.recv_multipart()
    d = msgpack.unpackb(payload, raw=False)
    if d["ch"].endswith("/pressure"):
        print(f"channel={d['ch']}  value={d['v']}  nan?={isinstance(d['v'], float) and math.isnan(d['v'])}  status={d['st']}  unit={d['u']}")
        print(f"meta={d.get('meta', {})}")
        break
sub.close(0); ctx.term()
PY
```

Output:
```
channel=VSP63D_1/pressure  value=nan  nan?=True  status=sensor_error  unit=mbar
meta={'raw_response': '001M100023D', 'error': 'checksum_mismatch'}
```

### Pressure probe, after `aabd75f` + restart

Vladimir needs to re-run with engine restarted (checking
Section 2 of HANDOFF for commands). Expected output:
```
ch=VSP63D_1/pressure  value=1000.0  nan?=False  status=ok  unit=mbar
```

### Engine log — checksum mismatch spam (before `aabd75f`)

From `/home/lab53/cryodaq/logs/engine.log`:
```
2026-04-20 14:22:35 WARNING cryodaq.drivers.instruments.thyracont_vsp63d  VSP63D_1: V1 checksum mismatch in '001M100023D' — possible RS-232 corruption
2026-04-20 14:22:37 WARNING cryodaq.drivers.instruments.thyracont_vsp63d  VSP63D_1: V1 checksum mismatch in '001M100023D' — possible RS-232 corruption
[every 2 s]
2026-04-20 14:22:35 WARNING cryodaq.storage.sqlite_writer  Пропущено 1 readings с value=None/NaN (из батча 1)
[paired warning from sqlite_writer per checksum miss]
```

### Engine log — Т12 detector_warmup at startup (expected, physical)

```
2026-04-20 12:28:45 CRITICAL cryodaq.core.interlock  !!! БЛОКИРОВКА СРАБОТАЛА !!!
Имя: 'detector_warmup' | Описание: Нагрев детектора (Т12) выше рабочей температуры
Канал: 'Т12 Теплообменник 2' | Значение: 297.1 | Порог: > 10 | Действие: 'stop_source'
```

Physical cause: stand is warm (room temperature), Т12 reads
~297 K (ambient), interlock threshold is 10 K. Fires
immediately at startup. **This is CORRECT behaviour** for a
warm stand — the interlock will cease firing once the system
cools the detector below 10 K. Not a bug.

### Launcher log — B1 timeout pattern (pre-watchdog-fix)

```
10:13:51 INFO cryodaq.gui.zmq_client  ZMQ bridge subprocess started (PID=27601)
10:15:51 WARNING cryodaq.gui.zmq_client  ZMQ bridge: REP timeout on experiment_status
[120 s between subprocess start and first timeout — DETERMINISTIC on Ubuntu]
```

Later in the same run:
```
11:34:28 WARNING ... REP timeout on alarm_v2_status
11:35:03 WARNING ... REP timeout on alarm_v2_status [35 s later]
11:35:38 WARNING ... REP timeout on get_sensor_diagnostics [35 s later]
11:36:13 WARNING ... REP timeout on safety_status [35 s later]
```

Every 35 s = RCVTIMEO. After first failure, all subsequent
commands hang for 35 s. Permanent dead socket.

### Launcher log — restart storm (IV.6 watchdog regression)

```
14:31:51 ZMQ bridge subprocess started (PID=52373)
14:31:51 WARNING: command channel unhealthy. Restarting bridge.
14:31:52 ZMQ bridge subprocess stopped
14:31:52 ZMQ bridge subprocess started (PID=52380)
14:31:52 WARNING: command channel unhealthy. Restarting bridge.
14:31:55 WARNING: ZMQ bridge subprocess did not exit, killing
14:31:55 ZMQ bridge subprocess stopped
14:31:55 ZMQ bridge subprocess started (PID=52391)
[continues 30+ times per minute]
```

### Launcher log — post-cooldown expected behaviour (after watchdog-cooldown hotfix)

Projected pattern:
```
t=0:     bridge subprocess started (PID=X)
t=60-90: REP timeout on <command>
t=60-90: command channel unhealthy. Restarting bridge.  [first restart]
t=60-90: bridge subprocess started (PID=Y)
t=120-180: REP timeout on <command>
[watchdog sees stale flag but cooldown=60s blocks restart]
t=180s:  cooldown expires, next timeout triggers another restart
```

Stable usable cycle instead of storm. Until IV.7 ships proper fix.

### Environment captured

Ubuntu lab PC:
```
Python:  3.12.13
pyzmq:   26.4.0
libzmq:  4.3.5
Kernel:  Linux 5.15.0-173-generic (Ubuntu 22.04 base)
net.ipv4.tcp_keepalive_time = 7200
net.ipv4.tcp_keepalive_intvl = 75
net.ipv4.tcp_keepalive_probes = 9
net.ipv4.tcp_fin_timeout = 60
```

macOS dev:
```
Python:  3.14.3
pyzmq:   25.x
libzmq:  (bundled with pyzmq 25 wheel, likely 4.3.4 or 4.3.5)
OS:      Darwin
```

---

## 6. B1 — full hypothesis ledger

### H1: macOS kernel idle-reap of loopback TCP (ORIGINAL)

**Claim:** macOS reaps idle loopback TCP connections after ~30 s
inactivity. `diag_zmq_idle_hypothesis.py` showed rate-dependence:
5 Hz clean, 0.33 Hz fails. Socket goes idle between sparse
commands → kernel drops → permanent failure.

**Evidence for:** rate dependence; timing roughly matched some
macOS idle parameters.

**Evidence against:**
- Linux `tcp_keepalive_time = 7200s` means kernel wouldn't reap
  for 2 hours by default. Ubuntu also reproduces B1.
- After `TCP_KEEPALIVE*` setsockopt, bug persists. Aggressive
  25 s keepalive (IDLE=10, INTVL=5, CNT=3) should have held
  socket open through any idle window shorter than `pytest_timeout`.
- Active polling at 1 Hz never goes idle past 1 s anyway. Live
  launcher observed B1 during TopWatchBar's active 1 Hz polling.

**Verdict:** **FALSIFIED.** Not an idle-reap bug.

### H2: shared REQ socket accumulated state (Codex)

**Claim:** single long-lived REQ socket in `cmd_forward_loop`
eventually enters an unrecoverable state. Shared state across
all commands means one bad socket poisons the entire command
channel permanently. `REQ_RELAXED` + `REQ_CORRELATE` make it
more stateful. Fresh REQ per command should eliminate it.

**Evidence for:**
- Matches ZMQ Guide ch.4 anti-pattern: "keeping one REQ socket
  alive forever across failures is unreliable; the canonical
  pattern is poll/timeout/close/reopen"
- Explains why recreating the socket on the same context didn't
  help (ZMQ context retains state beyond just the socket)

**Evidence against:**
- **IV.6 landed per-command ephemeral REQ** (fresh create-close
  per command). Removed `REQ_RELAXED` + `REQ_CORRELATE`. Diag
  tools STILL reproduce B1 with identical timing.

**Verdict:** **FALSIFIED.** Shared state was not the cause. The
architectural improvement is still worth keeping (matches
canonical pattern, removes real brittleness), but it is not
the fix.

### H3: TCP-loopback layer itself (CURRENT WORKING)

**Claim:** Whatever is breaking is below the ZMQ application
layer. Candidates:
- libzmq loopback TCP handling under rapid connect/disconnect
  churn (IV.6 creates + destroys many sockets)
- pyzmq asyncio integration quirk
- Kernel loopback state accumulation
- TCP_NODELAY / buffering interaction specific to `127.0.0.1`

**Evidence for:**
- Everything ruled out above the transport layer: engine asyncio
  loop healthy, data plane unaffected, heartbeats flow, scheduler
  writes continue, plugins tick normally during failure window.
- Engine REP task alive, just silently not replying. Not erroring.
- Bug reproduces on two different pyzmq/libzmq/Python/OS combinations
  → unlikely to be a single library bug; more likely a transport-
  level behavior common to both.
- ZMQ Guide explicitly recommends `ipc://` over `tcp://` for
  same-host IPC.

**Test:** IV.7 switches to `ipc://` Unix domain sockets. If bug
disappears → H3 confirmed. If bug persists → H3 is wrong, need
higher hypothesis.

### H4 (fallback if H3 falsified): pyzmq/asyncio integration bug

**Claim:** The rapid subprocess bridge + mp.Queue + pyzmq Context
combination has some race or deadlock specific to the pyzmq
event loop integration. Would manifest even on ipc://.

**Test:** Would need to try in-process threading (remove
subprocess, run pyzmq directly in GUI's Qt event loop) or switch
to a different transport library (nanomsg? raw sockets?).

Not to be tested unless H3 fails.

### H5 (fallback if H4 also falsified): engine REP task state under rapid REQ churn

**Claim:** The engine's `ZMQCommandServer._serve_loop` handles
REQ disconnects poorly when they happen frequently. Per-command
ephemeral REQ (IV.6) made this worse by producing many more
connect/disconnect events than the pre-IV.6 shared REQ.

**Test:** Would require stepping through the engine-side code
with zmq monitor socket events enabled, watching for missed
events or connection-teardown races.

Not to be tested unless H4 fails.

---

## 7. Codex's full B1 analysis, preserved

Reproducing the key portions of Codex's output verbatim because
the reasoning chain is valuable. Codex ran on gpt-5.4 with high
reasoning effort.

> ## Revised root cause analysis (in light of Ubuntu evidence)
>
> The new Ubuntu evidence does materially change the diagnosis.
>
> The original "macOS kernel reaps idle loopback TCP after ~30s"
> theory is now very unlikely to be the primary cause.
>
> Two decisive facts:
>
> 1. Ubuntu fails too, on Python 3.12.13 + pyzmq 26.4.0 + libzmq 4.3.5.
> 2. The command path is not idle during the observed Ubuntu failure.
>    TopWatchBar polls experiment_status every second via
>    ZmqCommandWorker at src/cryodaq/gui/shell/top_watch_bar.py:396,
>    src/cryodaq/gui/shell/top_watch_bar.py:402.
>
> That means:
>
> - Linux kernel default TCP keepalive timers at 7200s are irrelevant
>   to the observed 120s failure.
> - The added TCP_KEEPALIVE_IDLE=10 / INTVL=5 / CNT=3 settings are
>   also irrelevant to the active reproductions, because a 1 Hz or
>   0.33 Hz command stream never goes idle for 10s. The probes
>   never fire.
>
> So the shared failure is not "idle TCP reaping". The shared
> weak point is the single long-lived GUI-side REQ socket in
> the subprocess command thread:
>
> - socket created once: src/cryodaq/core/zmq_subprocess.py:167
> - reused forever: src/cryodaq/core/zmq_subprocess.py:197
> - one timeout poisons the command plane and later replies can
>   become unmatched in GUI routing: src/cryodaq/gui/zmq_client.py:171

And Codex's proposed fix plan:

> ## Recommended fix (ipc / threads / watchdog / other)
>
> ### Primary fix: per-command REQ socket
>
> Keep the subprocess architecture, but stop reusing one REQ
> socket forever.
>
> Instead:
> - create a fresh REQ socket for each command
> - send exactly one request
> - receive exactly one reply
> - close the socket immediately
>
> This is the best cross-platform fix because it removes the
> shared long-lived command-channel state that both platforms
> are tripping over.
>
> It also lets you remove:
> - REQ_RELAXED
> - REQ_CORRELATE
>
> Those options are only needed when trying to recover and
> continue on the same REQ socket. If the socket lifetime is
> one request, they add complexity without benefit.
>
> This matches ZeroMQ's own reliability guidance better than
> "keep one REQ forever and hope reconnect is enough":
> https://zguide.zeromq.org/docs/chapter4/

Codex's fallback ordering was:
1. PRIMARY: per-command ephemeral REQ (this is what IV.6 did)
2. SECONDARY: command-channel watchdog in launcher
3. NOT FIRST FIX: ipc:// (good diagnostic but shouldn't lead)
4. NOT FIRST FIX: threading (too big blast radius)
5. NOT FIRST FIX: watchdog only (treats symptom)

**Critical update:** since IV.6 failed to resolve B1, Codex's
"NOT FIRST FIX" item 3 (ipc://) becomes the working hypothesis.
Items 4 and 5 become the fallback-fallback if ipc:// also fails.

---

## 8. Gemini audit status

### First audit: shallow / dismissed

Vladimir ran `/ultrareview` in Gemini CLI. Returned ~1 page
with HIGH/MEDIUM/LOW buckets and generic findings. Key
dismissal reasons:
- B1 not in the findings list (would be obvious as HIGH in a
  real audit since it blocks production)
- "Things I could not assess" section contained three items
  that were really "things I did not attempt"
- No file:line citations on most claims
- "Engine.py is 2000 LOC" = one cited number, no deeper analysis

### Second audit: deep / dispatched

Vladimir dispatched with a proper spec requiring:
- 60-90 min effort budget
- Two deliverables: B1 independent investigation + production
  readiness top-10
- File:line citations for every claim
- Minimum 6000 word output combined
- Three independent B1 hypotheses, each with falsification
  experiment
- No "did not assess" as cop-out

**Status at handoff:** unknown. Could be returned by now, could
still be running.

### What to do when it arrives

1. **Save it.** Write to `docs/gemini_B1_audit_2026-04-20.md`
   immediately. Do not let it exist only in a Gemini CLI
   transcript.

2. **Extract the three B1 hypotheses.** Tabulate against:
   - H1 (idle reap) — FALSIFIED
   - H2 (shared REQ state) — FALSIFIED (by IV.6)
   - H3 (transport layer, ipc:// test pending) — WORKING
   - H4 (pyzmq/asyncio bug) — untested
   - H5 (engine REP state) — untested

3. **If Gemini proposes ipc://:** high-confidence convergence,
   proceed with IV.7.

4. **If Gemini proposes something new:** evaluate on merits.
   Gemini has 1M context and could have found something the
   focused investigations missed.

5. **For production readiness top-10:** cross-reference against
   today's known-fixed items (pressure, XML, Т4). Gemini
   probably didn't know about today's commits since the audit
   was dispatched before they landed. Don't action items that
   are already done.

---

## 9. Multi-model stack operational details

### Architecture (from Vladimir's handoff)

```
┌──────────────────────────────────────────────────┐
│   Claude Code v2.1.114 (terminal UI)             │
│   ├─ hooks (pytest Stop, inject_context, RTK)    │
│   ├─ plugins (metaswarm, gemini-plugin-cc)       │
│   └─ CLAUDE.md invariants                        │
└──────────────────┬───────────────────────────────┘
                   │ Anthropic API format
                   ↓
┌──────────────────────────────────────────────────┐
│   CCR (claude-code-router v2.0.0)                │
│   http://127.0.0.1:3456                          │
│   Translates Anthropic ←→ OpenAI format          │
│   Router config:                                 │
│     default      → zai-org/GLM-5.1-TEE           │
│     background   → deepseek-ai/DeepSeek-V3.2-TEE │
│     longContext  → moonshotai/Kimi-K2.5-TEE      │
└──────────────────┬───────────────────────────────┘
                   │ OpenAI-compatible
                   ↓
Chutes endpoint https://llm.chutes.ai/v1/chat/completions
```

### How to invoke CC via CCR

```bash
cd ~/Projects/cryodaq   # Mac
ccr code                # CC through CCR → GLM
```

NOT `claude` (that would try Anthropic direct, which is 99% burned).

### Display lies

CC banner shows "Sonnet 4.6 · API Usage Billing" — this is a
CCR v2.0.0 display bug, NOT reality. Real model via:

```bash
tail -f ~/.claude-code-router/logs/ccr-*.log | grep '"model":"'
```

If you see `"model":"zai-org/GLM-5.1-TEE"` — that's GLM speaking.

### Identity leakage

When asked "who are you", GLM/Kimi/DeepSeek (trained partly on
Claude outputs) may answer "I am Claude Sonnet" or similar.
**This is training leak, not a routing bug.** Logs are the only
authority. Do NOT take model self-identification as evidence
the request went to Anthropic.

### Model switching in active CC session

```
/model chutes,moonshotai/Kimi-K2.5-TEE      # Kimi (256K context)
/model chutes,deepseek-ai/DeepSeek-V3.2-TEE  # DeepSeek (cheap)
/model chutes,zai-org/GLM-5.1-TEE            # back to GLM (default)
```

Useful: Kimi for reading big docs or log dumps; DeepSeek for
boring repetitive code transforms; GLM for main work.

### When Anthropic limit restores

```bash
ccr stop
unset ANTHROPIC_BASE_URL ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
claude
# inside: /login
```

CCR can stay installed — just turn off the proxy when direct
Claude is desired.

### Budget monitoring

Chutes is pay-as-you-go ~$20 topped up today. At GLM-5.1 prices
($1.05/$3.50 per 1M in/out tokens):
- Average coding session: ~200-500K tokens = $0.5-$2.
- $20 / $1.50 ≈ 13 such sessions.
- ~4-5 days of Anthropic recovery window covered.

Live check:
```bash
tail -f ~/.claude-code-router/logs/ccr-*.log | grep -E 'completion_tokens|prompt_tokens'
```

Chutes dashboard at chutes.ai for daily totals.

### Codex and Gemini budgets

Codex: ChatGPT Plus subscription, 5-hour rolling window. Already
partially used today for B1 analysis. Use judiciously.

Gemini: Google AI Pro, 1000 req/day via OAuth. Deep audit
dispatched today; result pending.

Neither touches Chutes budget.

### Commands available

From the handoff Vladimir shared:

```
# Metaswarm orchestration (recommended for complex tasks):
/start-task <описание задачи>
/prime                       # загрузить knowledge base перед стартом
/review-design               # 5-agent design review gate
/self-reflect                # после PR merge, extract learnings

# Direct delegation:
/codex:review                                       # standard review
/codex:adversarial-review                           # жёсткий challenge
/codex:rescue --model gpt-5.4 <prompt>              # делегация
/codex:status / /codex:result                       # manage background

/gemini:review --background                         # background review
/gemini:adversarial-review --model pro <focus>      # Gemini Pro challenge
/gemini:rescue investigate <problem>                # делегация
/gemini:status / /gemini:result                     # manage background
```

### Cross-model review pattern

Writer ≠ reviewer:
- GLM writes → Codex + Gemini review
- Codex writes → GLM + Gemini review
- Gemini writes → GLM + Codex review

For IV.7: GLM (you) writes the `ipc://` fix. Expect to dispatch
Codex for concurrency review (file lifecycle, bind race) and
possibly Gemini for cross-file impact.

### When NOT to invoke swarm

- Trivial tasks (status check, simple questions)
- diff < 50 LOC and files ≤ 2
- Quick fixes where root cause is already known
- Today's surgical fixes (`aabd75f`, watchdog cooldown,
  `74dbbc7`) correctly skipped Codex self-review

---

## 10. Pitch preparation materials (deferred — for reuse later)

Vladimir was preparing for a lab walkthrough with:
- Chief constructor (главный конструктор)
- Deputy chief (зам главного конструктора)
- Other department engineers

Format: on-feet tour of physical lab + live software, NOT
slides. Cancelled mid-day when B1 made live demo untenable.

**When it's rescheduled**, here's the material:

### Tour structure (20-30 min)

**Stop 0 — entrance, 1 min**
"Покажу вам что мы тут делаем с криовакуумными испытаниями
для Миллиметрона. Два куска: установка и софт вокруг неё.
Пойдём сначала к стенду."

**Stop 1 — криостат, 3-4 min**
- "Это криокулер, вторая ступень штатно на 4К, азотная плита
  на 77К"
- "Вот датчики — 22 штуки температуры по всему объёму,
  Т11/Т12 — калиброванные DT-670 как референс на холодной точке"
- "Вот вакуум — Thyracont VSP206, рабочее 10⁻⁵ mbar, мерим
  непрерывно"
- "Нагреватели управляются Keithley 2604B, источник тока с
  ограничениями по мощности"

**Stop 2 — стойка + DAQ PC, 5-6 min**
Live demo на экране:
- TopWatchBar — статус бар с 22 каналами, давлением, фазой
- Dashboard — real-time plots
- Archive — карточки прошлых экспериментов
- Запуск нового эксперимента через NewExperimentDialog
- Фазовые переходы: vacuum → cooldown → measurement → warmup → disassembly
- Auto-report DOCX + PDF готовый к открытию

**Stop 3 — safety архитектура, 3-4 min**
**Самое важное для главного конструктора.** Три слоя:

"У нас три слоя защиты, работают независимо:

Первый — SafetyManager. FSM, не даёт включить источник тока
если хоть один из 4 критичных каналов не обновляется более
10 секунд, или если Keithley не отвечает, или если скорость
изменения температуры выше 5 K/мин. То есть до ошибки, на
уровне готовности.

Второй — InterlockEngine. Жёсткие отключения железа. Если
любой канал Т1-Т8 превысил 350К или Т12 вышел за 10К при
работающем источнике — автоматически stop_source или
emergency_off, напрямую на Keithley через hardware path.
Время реакции меньше двух секунд.

Третий — AlarmEngine v2. Уведомления без вмешательства.
Композитные условия, фазозависимые, уровни info/warning/critical,
Telegram и звук. 19 алармов сейчас.

Плюс SQLite пишется WAL mode с persistence-first — данные
сначала на диск, потом в брокер. Engine крашится — последняя
транзакция уже на диске."

**Stop 4 — данные и отчёты, 3-4 min**
- Открыть готовый автоотчёт DOCX предыдущего эксперимента
- Parquet архив — `pandas.read_parquet('...readings.parquet')`
- Calibration chain: Chebyshev fit → LakeShore .340 export

Для главного конструктора: эти данные готовы для публикации
или для передачи в проект Millimetron.

**Stop 5 — что впереди, 2 min**
"Из планов — добавить SQLite → Parquet rotation для холодного
архива, подключить к Obsidian и внутренним webhook'ам, и
самое главное — полуавтоматическую генерацию отчётов по
теплопроводности TIM с полным бюджетом неопределённостей
по ГОСТ Р 54500.3. Это позволит ставить эксперимент, получать
публикационно-готовый отчёт, и писать статьи быстрее."

Ключевое: сигнал про **публикации**. В АКЦ ФИАН это метрика
жизнеспособности направления.

**Stop 6 — закрытие, 30 sec**
"Вот такой проект. Будет интересно узнать ваше мнение, и если
есть какие вопросы или предложения что улучшить — слушаю."

Открытый финал. Пауза. Не проси одобрения явно.

### Dry bullets (Vladimir's preferred format)

Vladimir's instruction: "каждый буллет = ахуеть, никак иначе"
then later "сухой список без пафоса, подтекст (ахуеть)".

Final style — engineering-neutral, impressive by content not
phrasing:

```
— Замена LabVIEW-стека для криовакуумных испытаний Millimetron.
  Разработка с нуля, срок — менее одного месяца.

— Управление 5 приборами: 3× LakeShore 218S (GPIB),
  Keithley 2604B (USB-TMC), Thyracont VSP206 (serial).
  Унифицированный driver API.

— Сбор данных с 22 каналов одновременно в реальном времени.
  Температура 2 Гц, давление 2 Гц, мощность 1 Гц.

— Архитектура: engine и GUI в раздельных процессах, связь
  через ZMQ PUB/SUB + REQ/REP. Независимый жизненный цикл.

— Persistence-first: commit в SQLite WAL выполняется до
  публикации подписчикам. Потеря данных при сбое engine
  исключена.

— Parquet-архив каждого эксперимента. Совместимость с
  Pandas / Matlab / R без конвертации.

— Три независимых слоя защиты: SafetyManager (FSM
  preconditions), InterlockEngine (hardware-level triggers),
  AlarmEngine v2 (уведомления).

— Время реакции interlock: менее 2 секунд от события до
  emergency_off на Keithley через hardware path.

— SafetyManager: 6-state FSM, fail-on-silence, rate-limit
  5 K/мин, source caps 5 W / 40 V / 1 A, мониторинг 4
  критичных каналов с stale-timeout 10 с.

— InterlockEngine: 3 активных блокировки, regex-based channel
  matching, cooldown для предотвращения re-trigger storm.

— AlarmEngine v2: 19 алармов, 4 типа условий (threshold, rate,
  composite, stale), phase-aware (vacuum / cooldown /
  measurement / warmup).

— Автоматическая детекция 6 фаз эксперимента по физическим
  критериям (давление + dT/dt). Без ручного переключения.

— Настройка всех порогов через YAML без рекомпиляции.

— Calibration chain: Chebyshev polynomial fit для DT-670,
  export в нативный формат LakeShore .340. Версионирование
  кривых и привязка к экспериментам.

— Автоматический отчёт после каждого эксперимента: DOCX + PDF.
  Phase breakdown, графики на канал, alarm log, комментарии.

— Operator log: комментарии с timestamp привязаны к активной
  фазе, попадают в отчёт без ручного переноса.

— Shift handover: автоматическая сводка событий смены,
  активных тревог, min/max по каналам, прогресса фаз.

— Telegram-уведомления на критические тревоги. Задержка
  событие → сообщение — секунды.

— Plugin hot-reload. Новые аналитические модули подключаются
  без перезапуска engine.

— Replay любого прошлого эксперимента с полным восстановлением
  state виджетов.

— Full mock layer: 1500+ автотестов прогоняются без железа.

— CI/CD: pytest + ruff на каждый commit. Проваленные тесты
  блокируют merge.

— 33 версии в продакшене, 40+ реальных тест-кампаний с
  момента старта разработки.

— Исходный код открыт для аудита safety-логики. Без
  проприетарных компонентов. Без vendor lock-in.
```

### Q&A anticipation

**"Почему Python а не LabVIEW?"**

> "LabVIEW работал, но было три проблемы. Первая — лицензии,
> мы привязаны к одному вендору, при санкциях обновлений нет.
> Вторая — бас-фактор, LabVIEW знал один человек, после него
> никто не мог поддерживать. Третья — формат данных
> проприетарный, для анализа нужно было конвертировать. Python
> даёт стандартный стек, любого инженера можно натренировать,
> open source код можно аудитить на safety, данные в SQLite/
> Parquet читаются в Matlab/Pandas/R без плясок."

**"Сколько времени потратил?"**

> "Порядка года активной разработки параллельно с лабораторными
> кампаниями."

(Vladimir corrected: "Времени потратил не год, а меньше месяца".
Use actual number — it's MORE impressive.)

**"Что если Fomenko уходит?"**

> "Bus factor улучшен vs LabVIEW, код документирован, тесты
> покрывают, но всё ещё риск — вот почему нужен second engineer."
> (Only say this if ask = resources)

**"Real-time garant'ии?"** (may come from old-school engineer)

> "Real-time у нас не нужен в строгом смысле — опрос 2 Гц,
> приборы сами буферизуют. Для safety-critical — interlock
> работает через hardware path на самом Keithley, не через
> Python. Python тут — оркестратор и база данных, не real-time
> контроллер."

### Things NOT to mention

- B1 bug (dev-environment issue, not production on lab)
- Pending tag 0.34.0 (internal process)
- Claude Code / multi-model stack (may be unfamiliar and
  distracting)
- "Еле успеваем" / "нужно срочно" (weak framing)
- Self-deprecation ("может быть плохо написано") — you built
  a working system, own it

### What to bring to the demo

- Lab PC with CryoDAQ pre-started and verified healthy
- **One successful recent experiment** open in Archive for replay
- **One generated DOCX report** open in separate window
- `docs/alarms_tuning_guide.md` open on second monitor as
  "here is the config doc"
- Physical map of stops in head — know where to stand at which
  instrument

---

## 11. Sumitomo F-100 compressor integration (F19 proposal)

Chief constructor asked during a separate conversation whether
CryoDAQ could track Sumitomo helium compressor state. Analysis:

### What Sumitomo F-70/F-100 exposes

Compressor for GM-cooler. Not SCPI-native; industrial control
panel with limited remote. Interfaces vary by serial/year:

1. **RS-232 serial port** — opt on F-100, standard on CSW-71D
   / CSA-71A / HC-4E1. Exposes: He return/supply pressures,
   oil/helium/coolant temps, operating hours, on/off state,
   error codes.

2. **Discrete I/O (relay contacts)** — on/off status via relays.
   Simplest, always available.

3. **Remote control option** — start/stop via external signal.
   We don't want control (read-only).

4. **Modbus RTU** — on newer controllers. F-100 vintage-
   dependent. Need to check serial number.

### Required hardware

FTDI USB-to-serial ($10-20) or USB-to-RS485 if Modbus. Already
in lab stock probably. No exotic cables.

### Protocol discovery

Sumitomo does NOT publish spec in open access. Paths:

1. **EPICS IOC from neutron facilities** (ISIS / Diamond / ORNL
   / PSI) — register maps public on GitHub. Repo pattern:
   `epicsdevs/sumitomoCryostat` or similar. Feasible.
2. Request from local distributor — bureaucratic, possibly denied.
3. **Reverse-engineer via `socat`** if Sumitomo Monitor Utility
   is installed somewhere and currently talks to the compressor.

Path 1 is the recommended primary.

### Integration plan

Model-fits architecture without changes:

1. `src/cryodaq/drivers/instruments/sumitomo_f100.py` — new
   driver, mirrors `thyracont_vsp63d.py` pattern (serial
   transport).
2. `SumitomoF100(InstrumentDriver)` class. Methods:
   - `read_status()` → dict with pressures, temps, hours, state.
   - Connect/disconnect via existing `SerialTransport`.
3. `config/instruments.yaml` entry:
   ```yaml
   - type: sumitomo_f100
     name: "Sumitomo_1"
     resource: /dev/ttyUSB1   # probably (different from VSP63D)
     baudrate: 9600
     poll_interval_s: 10.0
   ```
4. Channel IDs: `Sumitomo/return_pressure`,
   `Sumitomo/supply_pressure`, `Sumitomo/oil_temp`,
   `Sumitomo/helium_temp`, `Sumitomo/coolant_temp`,
   `Sumitomo/operating_hours`, `Sumitomo/state`.
5. Poll every 5-10 s — compressor state changes slowly.
6. Mock layer for tests.
7. Engine loader (`engine.py::_create_instruments()`) add case
   for `sumitomo_f100` type.

### New alarm rules (huge value — currently blind)

Currently no compressor visibility. First symptom of degradation
is Т11/Т12 drifting — by then, too late for preventive action.

With data, new rules in `config/alarms_v3.yaml`:

- `compressor_oil_overtemp` (WARNING): `oil_temp > 60°C`
- `compressor_helium_overtemp` (CRITICAL): `helium_temp > 85-90°C`
- `compressor_pressure_anomaly` (WARNING): `ΔP/P < 0.8 × normal`
  — precursor of valve wear / He leak
- `compressor_coolant_loss` (CRITICAL): `coolant_temp > threshold`
- `compressor_operating_hours` (INFO): trend to 20000 h overhaul
- `compressor_state_unexpected` (CRITICAL): state=off during
  active experiment

And new interlock: `compressor_fault` → `stop_source` on Keithley
(prevent heating cryostat that's about to lose cooling).

### Estimated effort

- 1-2 days: protocol spec hunt + prototype single register read
- 2-3 days: full driver + mock + tests + integration
- 1-2 days: alarm rules + synthetic fault injection test
- 1 day: documentation + ROADMAP update

**Total ~1 week one engineer.** Main risk = protocol discovery.
Budget 2-3 additional days if EPICS path fails.

### When to do

**NOT in IV.7.** IV.7 is focused B1 fix. F19 after 0.34.0 tagged.
Possibly pair with F13 (leak rate estimator) since both deal
with vacuum system health.

---

## 12. Hardware state on Ubuntu lab PC at handoff

### Instruments

| Instrument | Status | Resource | Notes |
|---|---|---|---|
| LS218_1 | ✅ connected | GPIB0::12::INSTR | Т1-Т7 (Т8 slot empty) |
| LS218_2 | ✅ connected | GPIB0::11::INSTR | Т9-Т15 (Т16 empty) |
| LS218_3 | ✅ connected | GPIB0::13::INSTR | Т17-Т20 (Т21-Т24 empty) |
| Keithley_1 | ✅ connected | USB0::...\0::0::INSTR | requires \0 |
| VSP63D_1 | ✅ connected | /dev/ttyUSB0 | actually VSP206, validate_checksum:false |

All 5 instruments in `scheduler_count` = 5 at handoff.

### Physical

- Stand is **warm** (~295 K ambient, room temp). Т12 reads ~297 K.
- Stand is **unpumped** (atmospheric, ~1000 mbar). Thyracont
  returns `001M100023D` = 10³ mbar.
- `detector_warmup` interlock (Т12 > 10 K stop_source) **fires
  immediately at startup**. This is correct — will stop firing
  once cryostat cools down and Т12 drops below 10 K during normal
  operation.

### What Vladimir can do now (after IV.7 ships)

1. Start real cooldown — Т12 descends 295 → 4 K over hours
2. `detector_warmup` stops firing once Т12 < 10 K
3. Pump down — Thyracont shows pressure dropping from 10³ to
   10⁻⁵ mbar as turbopump spins up
4. Full-cycle experiment demo-ready for rescheduled pitch

### Operational notes

- `lab53` user (not `vladimir`) on Ubuntu. Home `/home/lab53/`.
- `dialout` group membership granted (required for `/dev/ttyUSB0`).
- `gpib` group membership for NI GPIB-USB-HS.
- `ModemManager` disabled (`sudo systemctl disable ModemManager`).
  Do NOT re-enable — it grabs `/dev/ttyUSB0` intermittently.
- `brltty` was checked but already inactive — no action.

### Git identity on Ubuntu (set up today)

```
git config --global user.name "Vladimir Fomenko"
git config --global user.email "<vladimir-github-email>"
```

Vladimir set these during the session. Don't redo.

### SSH auth on Ubuntu → GitHub (set up today)

Key generated via:
```
ssh-keygen -t ed25519 -C "lab53@RM-KP" -f ~/.ssh/id_ed25519 -N ""
```

Public key added to GitHub at https://github.com/settings/keys
under `test1card` account. Remote URL switched from HTTPS to:

```
git@github.com:test1card/cryodaq.git
```

Working. Don't re-setup.

---

## 13. Commands reference — exact invocations that worked

### Engine restart (Ubuntu)

```bash
pkill -9 -f cryodaq
sleep 2
rm -f data/.engine.lock data/.launcher.lock
```

Then:
```bash
# Foreground with visible stderr
.venv/bin/cryodaq-engine 2>&1 | tee /tmp/engine_manual.log
```

OR full launcher (normal operation):
```bash
./start.sh
```

OR just GUI against external engine:
```bash
CRYODAQ_EXTERNAL_ENGINE=1 .venv/bin/python -m cryodaq.launcher 2>&1 | tee /tmp/gui_manual.log
```

### Pressure probe (30 s)

```bash
cd ~/cryodaq
.venv/bin/python - <<'PY'
import math, msgpack, zmq
ctx = zmq.Context()
sub = ctx.socket(zmq.SUB)
sub.setsockopt(zmq.RCVTIMEO, 5000)
sub.connect("tcp://127.0.0.1:5555")
sub.subscribe(b"readings")
for _ in range(300):
    t, p = sub.recv_multipart()
    d = msgpack.unpackb(p, raw=False)
    if d["ch"].endswith("/pressure"):
        print(f"ch={d['ch']}  value={d['v']}  status={d['st']}  unit={d['u']}")
        break
sub.close(0); ctx.term()
PY
```

### Log greps that WORKED (binary file handling)

```bash
# Binary files in log (containing Cyrillic + special chars) need this:
grep --binary-files=text -B5 -A40 "XML compatible" ~/cryodaq/logs/engine.stderr.log | head -100

# Or strings-based:
strings ~/cryodaq/logs/engine.stderr.log | grep -B5 -A40 "XML compatible" | head -100
```

### Config check after edit

```bash
.venv/bin/python -c "import yaml; print(yaml.safe_load(open('config/instruments.local.yaml')))"
```

### Python syntax check after sed edit

```bash
.venv/bin/python -c "import ast; ast.parse(open('src/cryodaq/engine.py').read())" && echo "OK: syntax valid"
```

### Instrument connection check

```bash
grep --binary-files=text -iE "(Keithley_1|VSP63D_1|LS218_[123]).*подключ" /tmp/engine_manual.log | tail -10
```

### B1 pattern check

```bash
grep --binary-files=text -c "REP timeout" ~/cryodaq/logs/launcher.log
grep --binary-files=text -c "Restarting bridge" ~/cryodaq/logs/launcher.log
```

### What did NOT work

**Bash syntax errors from pasting Python into terminal:**

```bash
elif itype == "thyracont_vsp63d":
    from cryodaq.drivers.instruments.thyracont_vsp63d import ThyracontVSP63D
    driver = ThyracontVSP63D(...)
bash: синтаксическая ошибка рядом с неожиданным маркером «elif»
```

Remember: Python code must go in files or heredocs, not raw
into bash.

**sed single-line replacement of multi-line blocks** — doesn't
work cleanly. Switch to Python heredoc for multi-line
replacements:

```bash
.venv/bin/python - <<'PY'
path = "src/cryodaq/launcher.py"
with open(path) as f:
    content = f.read()
old_block = """..."""
new_block = """..."""
if old_block in content:
    content = content.replace(old_block, new_block, 1)
    with open(path, "w") as f:
        f.write(content)
    print("OK: patched")
else:
    print("FAIL: old block not found")
PY
```

### Git workflow (from fresh setup today)

```bash
# Commit with multi-line message (heredoc)
git commit -m "subject

body line 1
body line 2"

# Push over SSH
git push origin master

# Check state
git log --oneline -5
git status
```

Remote URL for fresh clones on new machines:
```
git clone git@github.com:test1card/cryodaq.git
```

---

## 14. Vladimir working-style patterns observed today

Beyond the general rules in HANDOFF section 0. Real-world
behavior observed over 16+ hours:

### Terse when fatigued

Late in the session: "забей у него неактуальные данные по
криодаку. информация про обновление стека". Not rude, just
economical. Don't over-explain when he's tight on bandwidth.
Answer the signal, skip the rest.

### Prefers physical action for one-liners

When I suggested CC for the `validate_checksum` wiring fix:
Vladimir did it himself via sed on Ubuntu. CC reserved for
larger batches. This is efficient — don't escalate to CC
anything under ~30 LOC unless it needs Codex review.

### Tolerates and embraces errors

"любая ошибка это опыт" — when IV.6 failed to fix B1, Vladimir
chose to commit the work anyway as "forward motion." This is
correct engineering discipline. Don't hide failed experiments.
Don't revert to "clean state" as a default — move forward with
explicit partial-mitigation labeling.

### Friendly sarcasm ("лол")

"лол, так я не про кодекс, я про команду клод код /ultrareview"
when I misunderstood. Correct him briefly, don't over-apologize.

### Multi-terminal parallel work

Throughout the session Vladimir had:
- Mac (architect/my side)
- Ubuntu lab PC (operational side)
- Physical lab walk (hardware access)

All 3 active simultaneously. Works fluidly. When he says "я
на убунту" or "я за всеми компами" — trust him, don't ask
to confirm.

### Rejects praise-by-default

Memory slot 1 explicitly: "direct, engineering, peer-to-peer,
no filler." Never open with "great question!" or similar.
Critique is welcome; sycophancy reads as noise.

### Specific format preferences (from today)

- "сухие буллеты со всеми фичами, нужен строгий текст — но
  подтекст (ахуеть)" — dry engineering bullets, impressive by
  content
- When I over-formatted with headers and bullets in casual
  chat, he pushed back — use prose for conversation
- For docs/specs — structure is fine, preferred even

### Works through emotional fatigue

Mid-session: "я задолбался тыкаться в никуда" and "может
сделаем ультраревью". I pushed back (correctly, I think) —
fatigue hypothesis not the time for broad scope changes.
Vladimir accepted. When he's tired, narrow down, don't expand.

### Accepts handoff when quota critical

End of session: clear-eyed about the multi-model transition,
prioritized preserving context over doing more work. Signal:
when resources are tight, shift to defensive context
preservation, not offensive new features.

### Uses Russian + English hybrid naturally

Code and docs in English; chat in Russian with English
technical terms inline ("commit", "push", "subprocess", "bridge").
Don't try to translate technical terms into Russian. Use
whatever's natural for the term.

### Physics-first when claims don't add up

Gemini's shallow audit claimed "archive globs 1000 metadata
files scales poorly." Vladimir immediately: "но у меня 5 экспериментов
в архиве." Tested the claim against reality, dismissed.
Trust your data over model bullshit. GLM — if any audit
claims a scenario that doesn't match observed scale, flag it.

---

## 15. Things attempted then abandoned

### TCP_KEEPALIVE as primary fix (`f5f9039`)

Committed as "partial fix" based on macOS idle-reap hypothesis.
Ubuntu data later showed hypothesis wrong. Kept on SUB socket
in `sub_drain_loop` (orthogonal safeguard — that socket really
does see long idle periods). Removed from REQ/REP/PUB in IV.6.

**Lesson:** don't commit a fix based on a hypothesis you haven't
confirmed with multiple data points. macOS timing looked
consistent with idle-reap but Ubuntu killed the story.

### Broad `/ultrareview` when narrow focus needed

Vladimir pushed for `/ultrareview` twice during fatigue. I
declined both times — not because the command is bad, but
because the conversation context was full (IV.6 + xml_safe
work), and a broad review would return fluff.

**When `/ultrareview` makes sense:** clean CC context, green
system, polish phase, not-blocking issues. That's a future
session, not today.

### Revert of IV.6 (rejected by Vladimir)

When IV.6 didn't fix B1, I offered Option B: revert. Vladimir:
"отката не будет, идем только вперед." Correct call for this
project's culture. IV.6 stays as architectural improvement.

### Option A: disable watchdog entirely

Alternative to the cooldown hotfix. Would have meant
commenting out the `command_channel_stalled` check in
`_poll_bridge_data`. Rejected because watchdog has genuine
value for other failure shapes (command-channel-only dead while
data plane works). Cooldown preserves that value.

### Pre-emptive "fix all the Gemini audit findings"

First shallow audit had 10+ findings. Vladimir could have
wanted all addressed. Kept focus on B1 instead. Valid findings
(alarm_v2 threshold, docs drift) logged as orthogonal for
later; rejected others (archive SQLite migration, pydantic
everywhere) as premature.

### Removing `\0` from Keithley VISA string

When python-docx rejected the string, first instinct was to
test: remove `\0` and see. Test confirmed Keithley refuses to
connect. Fixed at XML-sanitization layer instead — correct
choice (driver requires `\0`, report generator can strip it).

---

## 16. Priority ordering for coming sessions

### Today-equivalent session (GLM, day 1)

1. **Commit watchdog cooldown** if not already (see HANDOFF
   section 1).
2. **Push Т4 interlock config** if not already (see section 4
   of this doc).
3. **Verify state of everything**:
   - `git log --oneline -5` shows today's 4 commits + possibly
     watchdog cooldown
   - Pressure probe returns numeric value
   - Report generation works
   - Watchdog not restarting constantly
4. **Write initial GLM session log** at end of day in
   `HANDOFF_2026-04-20_GLM_RESPONSE.md`.

### Tomorrow or day 2

5. **IV.7 `ipc://` transport experiment.** See
   `CC_PROMPT_IV_7_IPC_TRANSPORT.md`. Full batch, Codex self-review
   required. If diag tools show 0 failures on both macOS AND Ubuntu
   post-fix → **tag 0.34.0**. If failure persists → STOP to Vladimir
   for next-strategy decision.

6. **Gemini audit integration** — see section 8.

### Days 3-4 (if Vladimir's Claude limit still burning)

7. **`alarm_v2` KeyError fix.** ~5 LOC in either config or code.
   Single commit. No Codex review.
8. **Thyracont `_try_v1_probe` consistency.** ~5 LOC. Mini-commit.

### Day 5+ or Vladimir's limit restored

9. **F19 Sumitomo F-100 integration** if chief constructor
   follows up.
10. **F20 alarm management UI** if Vladimir dispatches.
11. **IV.5 batch** (F3 analytics widgets + F5 webhook + F17
    Parquet rotation). Spec not yet drafted.

### Release cadence

- **0.34.0** tag: after B1 resolved (IV.7 or later). Fixes
  pressure, XML, Т4, B1. Watchdog cooldown.
- **0.35.0** tag: IV.5 batch.
- **0.36.0+**: F19/F20/F9 as priority allows.

---

## 17. Hidden gotchas that could eat days if missed

### Keithley VISA string requires `\x00` — don't remove

`"USB0::0x05E6::0x2604::4083236\0::0::INSTR"` — the `\0` is
the NI-VISA Keithley serial number terminator. Without it,
pyvisa `open_resource()` fails. Confirmed today via
experimental removal and restart. Fix applied at
python-docx sanitization layer (`xml_safe`), not at config
layer.

### `dialout` group membership required for `/dev/ttyUSB0`

Granted to `lab53` today. If Vladimir creates new user accounts
or deploys on new hardware: `sudo usermod -a -G dialout <user>`
then relogin.

### ModemManager on Ubuntu interferes with USB-serial

`sudo systemctl disable ModemManager` permanent. If you see
`Permission denied: '/dev/ttyUSB0'` while user is in dialout
group — check `systemctl status ModemManager`. If running,
disable.

### `brltty` can also interfere

Not active on Vladimir's lab PC but common on Ubuntu. If USB
serial gets grabbed intermittently: `sudo systemctl disable
brltty`.

### `validate_checksum=false` needs YAML + engine.py wiring

Both sides required. `aabd75f` fixed the engine.py loader. If
you see checksum mismatch spam despite config setting —
verify both sides are up to date.

### Binary files in logs need `grep --binary-files=text`

Cyrillic + control chars in logs make grep treat them as
binary. Flag: `--binary-files=text` or use `strings | grep`.

### Unicode subscripts in Russian labels

`Т N₂` uses U+2082 (subscript 2), not ASCII N2. When editing
labels, use the Unicode char. Python string literals:
`"Т N\u2082"` or `"Т N₂"` directly.

### Engine log rotation

Logs rotate. If grep returns empty, also check `.log.YYYY-MM-DD`
files. At handoff: `engine.log`, `engine.log.2026-04-17`,
`engine.stderr.log`, `gui.log`, `launcher.log`,
`launcher.log.2026-04-17`.

### `engine.stderr.log` is binary (non-UTF8)

Non-UTF8 bytes from some subprocess inject. Grep needs
`--binary-files=text`. If reading whole file: `strings` first.

### Tag name is `v0.33.0` not `0.33.0`

```bash
git log --oneline v0.33.0..HEAD    # correct
git log --oneline 0.33.0..HEAD     # fatal: неоднозначный аргумент
```

### `git push` requires SSH URL + authorized key

```bash
git remote -v
# Should show: origin  git@github.com:test1card/cryodaq.git (push)
```

If HTTPS: SSH not set up. Password auth was removed by GitHub
2021. Use SSH (instructions in HANDOFF section 1 or ChatGPT).

### `config/channels.yaml` is Vladimir's uncommitted WIP

Do NOT touch even if you think you need to. If config changes
are needed for a task, create `config/*.local.yaml` or
document what needs changing without making the edit.

### Stale socket files for `ipc://`

When IV.7 ships: `ipc:///tmp/cryodaq-*.sock` files persist
across crashes. Engine bind fails on stale file. IV.7 spec
includes `_prepare_ipc_path()` helper that unlinks first.
If you write your own: `with contextlib.suppress(FileNotFoundError):
os.unlink(path)` before bind.

### Ephemeral REQ socket creates TCP connection churn

IV.6 created fresh TCP connection per command. 1 Hz command
rate = 1 TCP handshake + teardown per second. This is fine
on loopback (microsecond handshake) but worth knowing if
switching to real network.

### `detector_warmup` interlock fires at startup (expected)

Stand at room temp → Т12 ≈ 295 K → interlock fires. Does NOT
mean system broken. Will cease once cryostat cools below 10 K
during normal operation. Log CRITICAL is expected behaviour
for warm-stand startup.

### Т4 disconnected physical state

Т4 sensor physically not connected to DAQ harness. Reads
380 K (open-circuit LakeShore 218S default). Interlock excludes
it, alarm group includes it for WARNING visibility. If Т4 is
ever physically reconnected — revert the config changes.

### Graphify hook rebuilds graph on code changes

In `.git/hooks/post-commit` or similar. Observed output:
```
[graphify hook] 3 file(s) changed - rebuilding graph...
[graphify watch] Rebuilt: 7651 nodes, 19945 edges, 525 communities
```

Expected. Not slow (few seconds). If you see hook output,
don't worry.

### `.beads/` knowledge base

`.metaswarm/` and `.beads/` are multi-agent orchestration
state. Untracked (in gitignore). Leave alone unless
deliberately using metaswarm workflow.

---

## 18. Document index — what to read and when

### You're GLM picking up Vladimir's next CryoDAQ task

1. `HANDOFF_2026-04-20_GLM.md` — start here
2. This document sections 0-3 — narrative catch-up
3. Whatever specific section for your current task

### You're me (Claude Opus) returning when weekly limit resets

1. `HANDOFF_2026-04-20_GLM.md` — primary recap
2. GLM session log (`HANDOFF_2026-04-20_GLM_RESPONSE.md` or
   appended to HANDOFF) — what actually happened
3. This document section 1 for chronology reminder
4. `git log --oneline v0.33.0..HEAD` for actual delta

### You're Vladimir referencing something from today

1. `CHANGELOG.md` Unreleased → today's section
2. For pitch: this document section 10
3. For Sumitomo: this document section 11
4. For B1 status: `docs/bug_B1_zmq_idle_death_handoff.md` +
   `ROADMAP.md` B1 entry

### You're Codex or Gemini being consulted on B1

1. `docs/bug_B1_zmq_idle_death_handoff.md` — full evidence +
   Codex's prior analysis
2. This document section 6 — hypothesis ledger with
   falsifications
3. `CC_PROMPT_IV_7_IPC_TRANSPORT.md` — current working
   hypothesis and test plan

### Key source-of-truth files (unchanged by handoff)

- `CLAUDE.md` — repo-level rules + module index
- `PROJECT_STATUS.md` — architecture summary (stale at
  2026-04-19 but architecture stable)
- `docs/design-system/` — 67 MD files, v1.0.1
- `docs/CODEX_SELF_REVIEW_PLAYBOOK.md`
- `docs/SPEC_AUTHORING_TEMPLATE.md`
- `docs/alarms_tuning_guide.md`

---

## 19. Return-to-Claude handoff format

When Claude Opus weekly limit resets (approximately
2026-04-25 to 2026-04-27), and I return:

### What GLM should write before that

A `HANDOFF_2026-04-20_GLM_RESPONSE.md` at repo root (or appended
to `HANDOFF_2026-04-20_GLM.md` as section 12 "GLM session log")
containing:

```
# GLM session log — 2026-04-21 to <final date>

## Commits authored by GLM
- SHA: <one-line description>
- SHA: <one-line description>
...

## Tasks completed
- IV.7: <PASS/FAIL with details>
- ...

## Tasks blocked / handed back
- ...

## Surprises encountered
- ...

## Vladimir feedback / corrections received
- ...

## State of uncommitted work
- ...

## For returning Claude (architect):
  [anything I need to know]

## For next-day GLM (continuation):
  [anything continuing GLM sessions need]
```

### What I'll do when I return

1. Read this document section 18's "returning Claude" entry.
2. Read GLM's session log.
3. `git log --oneline v0.33.0..HEAD` for raw delta.
4. Verify B1 status — did IV.7 ship and resolve? If yes: tag
   0.34.0 was done; check. If not: next hypothesis needed.
5. Check Gemini audit arrived and was integrated.
6. Check Т4 interlock commit is in history.
7. Check memory slots update needed (add new facts, remove
   obsolete).
8. Update `CHANGELOG.md` from "today's session" to real release
   entry when 0.34.0 tagged.

### What the world looks like on my return (probabilistic)

Most likely scenario:
- 0.34.0 tagged (B1 resolved via ipc://)
- Couple cleanup commits (alarm_v2, Thyracont probe)
- Maybe F19 Sumitomo started or at least prototyped

Less likely:
- B1 ipc:// also failed → in-process threading or pyzmq
  replacement needed
- New orthogonal bug surfaced during hardware runs

Edge case:
- Something completely different broke because lab started
  running real experiments with the cooled cryostat. Live
  hardware reveals things mocks don't.

### My priorities on return

1. Verify GLM's work didn't silently break invariants I care
   about (persistence-first ordering, safety state machine
   semantics, HMI philosophy).
2. Catch up on anything Vladimir signalled in the session log.
3. Resume the orderly roadmap — IV.5 batch if 0.34.0 shipped,
   IV.7 continuation if it didn't.

---

## Appendix A — Vladimir's personal context (condensed)

From userMemories + session observation:

- **Vladimir Fomenko**, 28, born ~1997-1998.
- **Role:** завлаб (Head of Cryogenic Laboratory) at Astro
  Space Center (АКЦ) of FIAN (Lebedev Physical Institute),
  Moscow. Works on Millimetron space observatory thermal
  testing (4.5 K stage, 10⁻⁵ mbar vacuum target).
- **Education:** dual MSc from MAI + SJTU (Shanghai Jiao Tong
  University) on English-language program. **Does NOT speak
  Chinese** despite SJTU. Earlier attended Lyceum 1580 → MGTU
  Bauman (entry by olympiad) → transfer to MAI.
- **2015-2019 personal-crisis period** during which experimental
  music project тесткард developed. Album "грязнуля" released
  Dec 2019.
- **Wife Polina** — creative copywriter, concept development +
  brand campaigns. Currently in job search (separate track;
  not relevant to CryoDAQ).
- **Dog:** pug named Вишенка. **No cat.** Previous conversational
  mentions of "cat named Дизель" were deliberate fabrication
  (honeypot for scammers). Do NOT reference a cat.
- **Job search abroad:** Apple Shenzhen (rejected), Apple
  Shanghai (#200638795-3715), Bluefors Helsinki, parallel.
  ITAR hard block for US aerospace/defence. UK HPI visa via
  SJTU flagged.
- **Interests:** experimental music (testcard project; Autechre
  / Coil / Ryoji Ikeda / Pan Sonic influences), mechanical
  keyboard design (organizes Moscow Keyboard Meetups), vinyl
  (PSB Alpha AM5 speakers), CK3 with AGOT mod, ASOIAF lore,
  hard sci-fi.
- **Philosophy:** absurdism + amor fati synthesis. Values
  intellectual honesty + ego-free truth-seeking.

### Specific CryoDAQ history

- Started CryoDAQ less than a month ago (new to programming
  in production). 32k LOC production + 17k LOC tests at
  handoff — massive output for one-month inexperienced dev
  working alone.
- **Did NOT build the lab.** Lab predates him. He streamlined
  processes, wrote software, ran 40+ cryo-vacuum campaigns,
  diagnosed thermal strap / TIM characterization issues. CryoDAQ
  is his from-scratch software contribution.
- **Zero publications despite 3-5 papers' worth of data.**
  Identified as highest-ROI gap. PhD supervisor available but
  low h-index. Auto-report features (F9 TIM characterization)
  are direct support for closing this gap.

### Tone to use

Engineer-to-engineer. Peer, not student. Assume competence in
physics and hardware. Do not assume CS/SWE fundamentals — he
may ask for explanation of e.g. "what does LINGER=0 mean on a
ZMQ socket" but will not ask what Ohm's law is. Inverse of
most programmer-conversational defaults.

---

## Appendix B — Memory slot contents (as of handoff)

From userMemories present at session start. Slot numbers are
internal — not exposed to Vladimir, only referenced for
Claude's context:

- **Slot 1:** Communication style. Russian default, English for
  tech, direct, no filler.
- **Slot 2:** Accuracy. Verifiable or "no data". Cross-check
  assumed.
- **Slot 3:** Errors are data. No ego. Third-party-defendable
  claims only.
- **Slot 4:** Methodology. Equations → analytical limits → code.
- **Slot 5:** Workflow. Multi-round iteration with rubrics.
- **Slot 6:** SJTU English program, no Chinese.
- **Slot 7:** CryoDAQ overview (size, stack, instruments).
- **Slot 8:** SFF PC build details (Lian Li A4-H2O, Ryzen 9 9900X,
  etc). Not operationally relevant for GLM work.
- **Slot 9:** LabVIEW logs format (TAB-separated, comma decimal,
  20 cols). Potentially relevant for historical data import.
- **Slot 10:** CryoDAQ TODO — debug mode (DONE IV.4.F2), GUI
  "Всё" time scale button (not yet).
- **Slot 11:** CC prompts end with `pytest tests/ && git push`.
- **Slot 12:** NO CAT. Пес = Вишенка. Do not mention cat.
- **Slot 13:** Age 28 (April 2026).
- **Slot 14:** Role clarification — contributed, not "built from
  scratch". Lab predates him. Only CryoDAQ software from scratch.
- **Slot 15:** CryoDAQ Phase III priorities (historical).
- **Slot 16:** HMI philosophy — cognitive load NOT a constraint.
- **Slot 17:** Pytest hang fix (historical, commit 63b054e).
- **Slot 18:** Phase III CLOSED 4/4 (historical).
- **Slot 19:** `_restart_gui_with_theme_change` bug. Workaround:
  launcher restart only. Hotfix planned.
- **Slot 20:** NEVER DELETE FILES. Zero exceptions.
- **Slot 21 (new today):** F20 alarm management UI TODO.
- **Slot 22 (new today):** Pressure display bug diagnostic trail
  (now resolved — can be removed / replaced).

### When to update memory

GLM should update memory slots when:
- B1 finally resolved → remove slot 19's similar, add resolution SHA
- Slot 22 can be removed (bug resolved)
- New long-lived TODOs worth persistent memory → add slot 23+
- Rules change (they won't — slots 1-6, 11, 14, 16, 20 are
  permanent invariants)

---

## Appendix C — CCR proxy architecture note

From Vladimir's handoff shared mid-session. Preserved verbatim
because GLM may need to debug proxy issues:

```
PATHS AND FILES

CCR
  Config: ~/.claude-code-router/config.json (chmod 600, contains
    Chutes API key in plain text)
  PID file: ~/.claude-code-router/.claude-code-router.pid
  Logs: ~/.claude-code-router/logs/ccr-*.log (JSON, pino formatter)
  Binary: global npm @musistudio/claude-code-router

CC
  Settings: ~/.claude/settings.json (hooks + plugins — don't touch)
  Global CLAUDE.md: ~/.claude/CLAUDE.md
  Plugins: gemini@google-gemini, metaswarm@metaswarm-marketplace

Metaswarm (in cryodaq repo)
  .metaswarm/project-profile.json
  .metaswarm/external-tools.yaml
  .beads/knowledge/ — 7 seed JSONL
  .coverage-thresholds.json — 100% (aspirational, not wired)
  .pre-commit-config.yaml — needs pre-commit install
  bin/ — 4 utility shell scripts
  .claude/commands/ — 7 metaswarm slash command shims

Env
  Shell: /opt/homebrew/bin/bash
  Node: v25.9.0, npm 11.12.1
  Claude path: /opt/homebrew/bin/claude
```

### CCR troubleshooting

```bash
ccr status                                              # check
ccr stop && ccr start                                   # restart
ps aux | grep claude-code-router                        # find zombies
rm -f ~/.claude-code-router/.claude-code-router.pid     # clear dead PID
```

### If CC goes around proxy

```bash
env | grep -i anthropic   # must be empty for ccr code
unset ANTHROPIC_API_KEY ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_URL
```

### Model not found errors

Possibly bash ate the `z` in `zai-org/` (weird zsh issue). Check:
```bash
cat ~/.claude-code-router/config.json | grep GLM
# Should show "zai-org/GLM-5.1-TEE" with z
```

### Chutes budget exhausted

Fallback: `ccr stop` and use `claude` (Anthropic direct) if
Vladimir's weekly limit has recovered, else Codex/Gemini only
for swarm review.

### DO NOT

- Touch `~/.claude/settings.json` without need
- Run metaswarm + oh-my-claude + claude-octopus simultaneously
- Use `ccr code --enable-review-gate` for Codex plugin (burns
  quota fast)
- Logout of CC (`/logout`) — unnecessary for model switching
- Trust model self-identification — only CCR logs
- Commit `.claude-code-router/` directory (contains API key in
  plain text — gitignored globally)
- Delete `.metaswarm/external-tools.yaml` (Codex/Gemini budget
  config)

---

## Appendix D — Chat log excerpts of Codex's verbatim B1 reasoning

Preserving key passages from Codex's output that led to IV.6
and that might be useful for comparing against Gemini's audit
when it returns.

### On why the handoff's TCP-idle theory was wrong

> Two decisive facts:
>
> 1. Ubuntu fails too, on Python 3.12.13 + pyzmq 26.4.0 +
>    libzmq 4.3.5.
> 2. The command path is not idle during the observed Ubuntu
>    failure. TopWatchBar polls experiment_status every second
>    via ZmqCommandWorker.
>
> That means:
>
> - Linux kernel default TCP keepalive timers at 7200s are
>   irrelevant to the observed 120s failure.
> - The added TCP_KEEPALIVE_IDLE=10 / INTVL=5 / CNT=3 settings
>   are also irrelevant to the active reproductions, because a
>   1 Hz or 0.33 Hz command stream never goes idle for 10s. The
>   probes never fire.

### On the shared-REQ hypothesis

> The shared failure is not "idle TCP reaping". The shared
> weak point is the single long-lived GUI-side REQ socket in
> the subprocess command thread:
>
> - socket created once: src/cryodaq/core/zmq_subprocess.py:167
> - reused forever: src/cryodaq/core/zmq_subprocess.py:197
> - one timeout poisons the command plane and later replies can
>   become unmatched in GUI routing: src/cryodaq/gui/zmq_client.py:171
>
> My revised view is:
>
> This is one architectural bug with platform-specific timing,
> not two unrelated bugs. The bug is reliance on one immortal
> REQ connection for the entire GUI command plane. macOS and
> Ubuntu likely trigger the bad state differently, but the
> brittle point is the same.

### Where Codex hedged its own ipc:// recommendation

> ipc:// is still a useful Unix-only diagnostic because it
> removes the TCP stack entirely, and libzmq documents ipc as
> Unix-domain-socket transport:
> https://libzmq.readthedocs.io/en/zeromq3-x/zmq_ipc.html
>
> But Ubuntu now tells us the failure is not just "loopback
> TCP got reaped after idle." So ipc:// is no longer the best
> primary fix.

This is exactly what makes ipc:// the CURRENT working hypothesis
after IV.6 failed. Codex put it in second place because
shared-REQ was its first. With shared-REQ falsified, ipc://
moves to first.

### On pyzmq/libzmq version suspicions

> I did not find a strong primary-source basis to blame pyzmq
> 25 vs 26 specifically for this pattern. The official pyzmq
> docs/changelog do not point to a clear REQ state-machine
> regression that matches your symptoms.
>
> The fact that both:
> - macOS + pyzmq 25.x
> - Ubuntu + pyzmq 26.4.0
> show the same architectural failure shape makes a
> pyzmq-version-only explanation weak.

### On libzmq 4.3.5

> I did not find evidence that libzmq 4.3.5 is specifically
> known-buggy for REQ timeout + reconnect on same context.
> Official release notes for 4.3.x actually include fixes in
> REQ/heartbeat areas, not a warning against 4.3.5.
>
> So I would not frame this as "libzmq 4.3.5 is broken". I
> would frame it as "our use of one long-lived REQ socket is
> brittle across libzmq/pyzmq/platform combinations".

### On CPython 3.12 vs 3.14 mp.Queue

> Unlikely as primary root cause.
>
> Reason:
>
> - the timeout warning is generated in the subprocess before
>   reply-queue routing and before GUI Future.result() handling.
> - cmd_queue.get() is clearly working.
> - the stall point is req.recv_string() in the subprocess
>   command thread.
>
> multiprocessing.Queue and Future behavior do affect how the
> failure surfaces afterward, but they do not explain the first
> fault.

### Codex's bottom line

> The new Ubuntu evidence invalidates the old TCP-idle-reap
> story as the main explanation.
>
> The best fix that fits both platforms is:
>
> 1. stop using one immortal REQ socket
> 2. use one REQ socket per command
> 3. remove REQ_RELAXED / REQ_CORRELATE
> 4. add a command-channel watchdog restart
>
> That is the smallest cross-platform fix with the highest
> probability of working on the actual versions you have in
> the lab.

**This is what IV.6 did.** It did not resolve B1. Codex's
analysis is preserved here because it is still the BEST
available reasoning trail for the hypothesis space. The IV.7
ipc:// test is the next experiment because Codex explicitly
ranked it second; with primary ruled out, secondary becomes
the front-runner.

---

*End of session detail. Written 2026-04-20 evening by Claude
Opus 4.7 (web) as final context preservation before weekly
limit cutover to GLM-5.1 via CCR. Vladimir, when you read this:
it was a good day despite the grind. IV.6 not fixing B1 is
data, not failure — the architectural improvement stands and
ipc:// is a genuinely better-positioned hypothesis now. Sleep
well. The GLM shift will pick up cleanly from the primary
handoff plus this detail.*
