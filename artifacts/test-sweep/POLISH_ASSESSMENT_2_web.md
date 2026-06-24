# CryoDAQ Polish Assessment 2 — WEB + REPORTING + DATA-EXPORT (read-only architect pass, 2026-06-24)

**Scope:** `web/server.py`, `reporting/{generator,sections,data}.py`,
`storage/{csv_export,hdf5_export,xlsx_export,parquet_archive,replay}.py`.
**Method:** read all 9 target files end-to-end + `utils/xml_safe.py`,
`storage/sqlite_writer.py` (non-finite gate), and both report-generation call
sites (`engine.py:1573`, `core/experiment.py:881`) to establish the async/thread
context. Every finding below was verified at the cited line. Findings that did
not survive a source read are in REJECTED. The prior pass
(`POLISH_ASSESSMENT.md`: safety/engine/driver/storage-writer/alarm/interlock) is
NOT re-reported.

**Headline:** the export/replay/report code is careful and the worst command-path
NaN gap lives in the *already-covered* safety/engine slice, not here. The genuine
new defects are operational, not algorithmic: (1) the operator-facing docs still
tell operators to bind `--host 0.0.0.0` on a fully unauthenticated dashboard that
also serves an **unbounded** `/history` read — the code default was fixed
(`eb84e44`) but the copy-pasted docs were not; (2) the LibreOffice `subprocess.run`
has **no `timeout=`**, and the report path is dispatched via `asyncio.to_thread`
*without* the `wait_for` envelope that `experiment_status` gets, so a hung
`soffice` permanently leaks a worker-thread with no recovery. Everything else is
MED/LOW hardening.

---

## DO FIRST (ranked)

1. **[HIGH] Operator docs still instruct `--host 0.0.0.0` on an unauthenticated
   dashboard.** `docs/deployment.md:136`, `README.md:176`, `docs/operator_manual.md:38`
   all say `uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080`. The code
   default was moved to loopback (`server.py:11,13`; commit `eb84e44`) and the
   module docstring says "never bind 0.0.0.0 directly" — but the three docs an
   operator actually copies from were never updated. Dashboard has zero auth
   (no `Depends`, no token, no CORS restriction). This is prior audit G.1
   (`docs/audits/2026-04-09/DEEP_AUDIT_CODEX_POST_2C.md:418`) only HALF-fixed, and
   matches the still-open memory note "Public bind 0.0.0.0 exposed in web server
   user-facing command" (May 7). **Fix:** change all three docs to `--host 127.0.0.1`
   + an explicit "SSH-tunnel for LAN; do not expose" note, matching the docstring.

2. **[HIGH] LibreOffice subprocess has no timeout → permanent worker-thread leak.**
   `reporting/generator.py:267-279` `subprocess.run([soffice, --headless, --convert-to,
   pdf, ...], check=False, capture_output=True)` has **no `timeout=`**. `generate()`
   is reached via `engine.py:2591` `asyncio.to_thread(_run_experiment_command, ...)`
   for `experiment_generate_report`, and via `core/experiment.py:881` on
   `finalize_experiment` (also a to_thread action). Critically, only
   `experiment_status` is wrapped in `asyncio.wait_for` (`engine.py:2597-2614`);
   the report action falls through to `result = await experiment_call`
   (`engine.py:2616`) with **no await timeout**. A hung `soffice` (stale
   `.~lock.report_raw.docx#`, headless-profile contention, a second soffice
   instance) blocks the worker thread forever — and as `engine.py:2598-2605` itself
   documents, a Python thread cannot be killed mid-call. Repeated finalizations then
   exhaust the default thread-pool. CLAUDE.md:369 grandfathers the *sync/blocking*
   nature of this call (DEEP_AUDIT E.2) but says nothing about the missing timeout;
   the timeout is a distinct, unmitigated defect. **Fix:** add `timeout=120`
   (or config) to `subprocess.run`; on `subprocess.TimeoutExpired` log WARNING and
   `return None` (report degrades to docx-only, the already-supported path).

3. **[MED] `/history?minutes=` is an unbounded read.** `server.py:385,398,257`
   `history(minutes: int = 60)` → `_query_history(minutes)` computes
   `cutoff = now - timedelta(minutes=minutes)` with no clamp, then
   `SELECT ... WHERE timestamp >= ? ORDER BY timestamp ASC` `.fetchall()`
   (`server.py:270-274`) across **every** `data_*.db` file and materializes all
   rows into a dict in memory. `?minutes=99999999` scans the entire archive and can
   OOM the web process. Prior audit flagged this (`DEEP_AUDIT_CC_POST_2C.md:802`);
   still unbounded. **Fix:** clamp `minutes` to a sane max (e.g. `min(minutes, 1440)`)
   and/or add a `LIMIT` + per-channel downsample. Same applies to `/api/log?limit=`
   (`server.py:374,377`) — `limit` is forwarded raw to the engine; bound it.

4. **[MED] Гемма/LLM annotation text bypasses `xml_safe`.** `generator.py:148-156`
   `_render_gemma_annotation` writes model output via `document.add_paragraph(para.strip())`
   with NO `xml_safe()`, while every operator/runtime string in `sections.py`
   (e.g. notes at `sections.py:404`, all table cells) is wrapped. The intro is
   produced by a local LLM (`gemma4:e4b`); if it ever emits a C0 control char or
   `\x00`, python-docx raises inside `_build_document` — which is OUTSIDE the
   `try/except` at `generator.py:79-92` (that guard only covers *producing* the
   intro, not *rendering* it). One bad model token then fails BOTH the raw and
   editable report builds. **Fix:** wrap with `xml_safe(...)` at `generator.py:149,151,154`
   exactly like sections.py does.

5. **[MED] `_query_history` cross-midnight comment overstates correctness.**
   `server.py:250-253` docstring claims it scans "all DB files whose date-suffix may
   intersect the window … to correctly handle cross-midnight queries." It actually
   globs **every** `data_????-??-??.db` (`server.py:265`) and filters only by the
   row `timestamp >= cutoff` — so it is correct for cross-midnight, but at the cost
   of opening every historical DB on every request (ties into finding 3). The comment
   implies a date-suffix prefilter that does not exist; `data.py:_db_paths`
   (`data.py:122-131`) DOES do the proper day-range prefilter and is the pattern to
   copy here. **Fix:** prefilter the glob to the `[cutoff.date() .. today]` day range
   like `data.py` does, then the unbounded-scan risk in finding 3 also shrinks.

6. **[LOW] `data.py` archived-CSV value coercion fabricates 0.0 on empty cell.**
   `data.py:99` `value=float(row.get("value") or 0.0)`. An empty/missing `value`
   cell (`""`) is falsy → silently becomes `0.0` (a plausible-looking real reading)
   instead of being skipped or flagged. A genuine `0.0` is safe (CSV yields `"0.0"`,
   truthy). **Fix:** coerce explicitly: skip the row or use a sentinel when the cell
   is empty, rather than `or 0.0`.

7. **[LOW] XLSX export emits NaN/Inf cells unguarded.** `xlsx_export.py:144`
   `value=round(v, 3)` runs whenever `v is not None`; a NaN/Inf reading (these can
   reach the readings table only as ±inf per `sqlite_writer.py:337-340`, NaN is
   dropped) becomes an Excel cell of `1E+308`-ish or a `#NUM`-displaying value with
   no marker. **Fix:** `if v is not None and math.isfinite(v)` (parallels
   `sections.py:661` which already does `math.isfinite(p.value)` for pressure).

8. **[LOW] CSV export does not BOM-validate but DOES write BOM — confirm intent.**
   `csv_export.py:79` opens with `encoding="utf-8-sig"` (BOM) which is the
   *intended* per-usecase behavior per CLAUDE.md:401 (Excel-on-Russian-Windows).
   This is CORRECT — flagged only to record that the BOM here is deliberate and must
   NOT be "fixed" by a future pass. (See SOUND.)

---

## Theme A — Web exposure + unbounded reads

The dashboard (`web/server.py`) is a monitoring surface with no authentication of
any kind: `/`, `/status`, `/api/status`, `/api/log`, `/history`, `/ws` are all open.
The code now defaults to `127.0.0.1` (`server.py:11`) and the docstring warns against
`0.0.0.0` (`server.py:13`), so the in-code posture is correct. The residual risk is
entirely in the **operator-facing docs** (finding 1) which still hand operators the
`0.0.0.0` command, plus the **unbounded `/history` / `/api/log`** reads (findings 3,
5). These three compound: an operator follows the doc, binds `0.0.0.0`, and now any
LAN host can issue `?minutes=99999999` and OOM the process. Bounding the reads and
fixing the docs closes the practical exposure without adding an auth layer (which is
an architect/product decision, out of scope for a polish pass).

`_send_engine_command` (`server.py:58-72`) is sound: REQ socket with
RCVTIMEO/SNDTIMEO=5000, LINGER=0, closed in `finally`, wrapped via
`asyncio.to_thread` (`server.py:75-77`) so it never blocks the loop. The broadcast
pump (`server.py:182-233`) is the good single-task-with-bounded-queue pattern and
drops on `QueueFull` rather than exploding tasks. No defect there.

## Theme B — Report generation (subprocess + sanitization)

- **HIGH — `generator.py:267-279`** — no `subprocess.run(timeout=...)`. See DO-FIRST #2.
  This is the one finding here with real operational teeth: it leaks an
  unkillable worker thread on a hung soffice, and the report action specifically
  lacks the `wait_for` envelope that protects `experiment_status`.
- **MED — `generator.py:148-156`** — LLM intro not `xml_safe`-wrapped. See DO-FIRST #4.
- Note `generator.py:283-286`: `target_pdf_path.unlink()` then `produced.replace(...)`
  — there's a small window where the old PDF is deleted before the new one lands, but
  `replace` is atomic and the unlink only runs when a stale target exists; on
  conversion failure `produced` won't exist and the function already returned None at
  `:281`. Acceptable.

## Theme C — Data export numeric/encoding correctness

- **LOW — `xlsx_export.py:144`** — NaN/Inf cell, finding 7.
- **LOW — `data.py:99`** — `or 0.0` fabrication, finding 6.
- `hdf5_export.py:187-190` deliberately substitutes `float("nan")` for NULL
  voltage/current/resistance/power — CORRECT for HDF5 (float64 datasets represent
  missing as NaN; this is the idiomatic choice and round-trips). Leave alone.
- `parquet_archive.py:119,132` casts `value` via `float(row["value"])` and writes
  `timestamp` as `pa.timestamp("us", tz="UTC")` from `datetime.fromtimestamp(ts, UTC)`
  — sound; chunked via `fetchmany` (`:105`) so no unbounded read. `read_experiment_parquet`
  divides int64 µs by 1e6 (`:201`) — correct, no off-by-one.

## Theme D — Replay + time-window slicing

- `replay.py:104-108` pause logic: `delta = ts_posix - prev_ts; if delta > 0: sleep(delta/speed)`.
  Correct — non-monotonic/equal timestamps don't sleep, negative deltas (clock
  skew) are skipped rather than producing a negative sleep. Sound.
- `replay.py:202-206` silently `continue`s on a timestamp parse error (matches memory
  note "Replay engine silently continues on timestamp parse errors", May 7). For
  replay (analytics-only, non-safety) this is acceptable; a DEBUG/WARNING count would
  aid triage but is not load-bearing. LOW/NIT.
- Window slicing across exporters is consistent: CSV/XLSX use `timestamp < end`
  (half-open, `csv_export.py:159`, `xlsx_export.py:243`); `data.py`/`parquet_archive`
  use `timestamp <= end` (closed, `data.py:141`, `parquet_archive.py:99`). The
  closed-interval in the report/parquet path is intentional (it wants the final
  reading at end_time inclusive) and the half-open in ad-hoc export is the
  conventional choice. Not a bug, but worth one comment noting the deliberate
  difference so a future "consistency" pass doesn't "fix" one into the other.
- `_db_paths` day iteration (`data.py:122-131`) and `parquet_archive.py:81-91`
  day loop are both inclusive `current_day <= last_day` and skip missing files —
  correct cross-midnight handling, no off-by-one.

## Theme E — Items reviewed and found SOUND (do NOT touch)

- `server.py:58-72` `_send_engine_command` — timeouts + LINGER=0 + finally-close. Correct.
- `server.py:167-233` broadcast: single pump task, bounded `Queue(maxsize=200)`,
  drop-on-full, dead-client reaping. Correct task-explosion mitigation.
- `server.py:466-468` JS `escapeHtml` is applied to every interpolated dynamic value
  in the dashboard (`ch`, `author`, `source`, `message`); numeric `.toFixed`/`.toExponential`
  outputs are numbers. No XSS sink found in `_DASHBOARD_HTML`.
- `server.py:265-279` history query is parameterized (`?` binding), connection
  closed in `finally`, per-file `except: continue`. No SQL injection; only the
  unbounded-range concern (finding 3) applies.
- `csv_export.py:79` `utf-8-sig` BOM — DELIBERATE per CLAUDE.md:401 (Excel/Russian
  Windows). Correct; do not remove.
- `sections.py` — every operator/config/runtime string is `xml_safe`-wrapped
  (`_add_kv_table:151,154`, table cells, captions); `xml_safe` (`utils/xml_safe.py:21-44`)
  correctly strips C0/DEL while preserving TAB/LF/CR. The Keithley `\x00` VISA-string
  case (`sections.py:758-762`) is handled. Correct.
- `sections.py:661` pressure stats already guard `math.isfinite(p.value) and p.value > 0`. Correct.
- All exporter SQLite queries are parameterized; `channels`/`instrument_ids` use
  `IN (?,?...)` placeholder expansion (`csv_export.py:162-167`, `xlsx_export.py:247-249`,
  `replay.py:189-191`). No injection.
- `parquet_archive.py:104-140` chunked streaming via `fetchmany(chunk_size)` +
  `ParquetWriter.write_table` per batch; writer closed in `finally`. No unbounded
  load, no handle leak.
- `hdf5_export.py:81` `h5py.File(..., "w")` in a `with`, conn closed in `finally`
  (`:100-101`). `_sanitize_name` (`:270-273`) replaces `/`, space, `:` so channel
  names can't escape the HDF5 group path. Sound.
- `data.py:_db_paths` + closed-interval query — correct cross-midnight. Conn closed
  in `finally` (`data.py:159-160,196-197`).

## REJECTED (verified false — do not re-litigate)

- "Web `recv_json` accepts NaN/Infinity → command injection of non-finite setpoint."
  CHECKED `server.py:68` `sock.recv_json()`: the web server is the **REQ sender**,
  not the engine REP **receiver**. `json.loads` does accept `NaN`/`Infinity`
  (verified at runtime), but the non-finite-command-setpoint defect lives at the
  engine's `zmq_bridge` decode + `request_run` guards — that is the SAFETY/ENGINE
  slice already covered by POLISH_ASSESSMENT.md (CRIT #1 / DO-FIRST #1-3 there).
  Not re-reported here.
- "`_query_history` cross-midnight is broken / drops rows." FALSE — it globs all DBs
  and filters by row timestamp, so it is cross-midnight-correct. The real issue is
  the unbounded scan + a docstring that implies a prefilter that isn't there
  (findings 3, 5), not data loss.
- "XLSX `by_time` keyed on timestamp string collides across instruments." FALSE in
  practice — the key is the raw REAL epoch from the row; same-channel same-epoch
  collisions are vanishingly rare and would also collide in any wide-format pivot.
  Not a correctness defect for the intended single-rate readings table.
- "CSV `utf-8-sig` BOM is an encoding bug." FALSE — deliberate per CLAUDE.md:401.
- "`replay.py` negative sleep on out-of-order timestamps." FALSE — `if delta > 0`
  guard at `replay.py:106` prevents it.
- "`hdf5_export` NaN-for-NULL is data corruption." FALSE — idiomatic HDF5 float64
  missing-value representation, round-trips cleanly.

## Worst-findings summary (for parent)

- No CRIT in this slice (the only CRIT, non-finite command setpoint, belongs to the
  already-covered engine/safety slice).
- 2× HIGH: (1) operator docs still say `--host 0.0.0.0` on an unauthenticated
  dashboard — code default fixed, docs not (`deployment.md:136`, `README.md:176`,
  `operator_manual.md:38`); (2) `soffice` `subprocess.run` has no `timeout=`
  (`generator.py:267`) and the report action lacks the `wait_for` envelope
  (`engine.py:2616`), so a hung LibreOffice permanently leaks an unkillable worker
  thread.
- 3× MED: unbounded `/history?minutes=` + `/api/log?limit=` read (`server.py:257,374`);
  Гемма LLM intro skips `xml_safe` (`generator.py:148-156`); misleading
  cross-midnight docstring vs whole-archive glob (`server.py:250-265`).
