# POLISH_FIXES_2_web — WEB + REPORTING fixes (2026-06-24)

Source assessment: `artifacts/test-sweep/POLISH_ASSESSMENT_2_web.md`.
Scope: WEB-H1, WEB-H2, WEB-M1, WEB-M2. Not committed.

Test invocation note: `tests/reporting/test_report_generator.py` requires
`CRYODAQ_ALLOW_BROKEN_SQLITE=1` on this machine (local SQLite 3.50.4 is in the
refused WAL-corruption range). The two new reporting tests set the env per-test
(mirroring existing tests at lines 183/287), and were also run with the env
exported. `tests/web` needs no env.

---

## WEB-H1 (HIGH) — docs hand operators a public-bind command  [DOC-ONLY]

**Prod change:**
- `docs/deployment.md:136` — `--host 0.0.0.0` → `--host 127.0.0.1`; added a
  two-line Russian note: dashboard has no auth, bind loopback only, public
  access requires a reverse proxy with auth (or SSH tunnel).
- `README.md:176` — same host change + inline `# опциональный web (loopback)`
  + two-line Russian note.
- `docs/operator_manual.md:38` — same host change + inline parenthetical note.

`CLAUDE.md:81` was left untouched — it is NOT in the assessment's 3-site list and
the guardrails forbid out-of-scope edits. (Flagged below as a residual gap.)

**Test:** none (doc-only, per task). Verified via grep that all three cited
lines now read `--host 127.0.0.1` and no `0.0.0.0` remains in the three docs
(the surviving `0.0.0.0` at `operator_manual.md:550` is an unrelated
engine-binding-check sentence).

**Result:** PASS (manual grep verification).

---

## WEB-H2 (HIGH) — LibreOffice subprocess has no timeout

**Prod change:** `src/cryodaq/reporting/generator.py`
- Added module constant `_SOFFICE_TIMEOUT_S = 120` (with rationale comment).
- `_try_convert_pdf`: wrapped `subprocess.run([... soffice ...])` with
  `timeout=_SOFFICE_TIMEOUT_S` and a `try/except subprocess.TimeoutExpired`
  that logs an ERROR and `return None` — degrading to docx-only, exactly the
  same fallback as the missing-soffice / failed-conversion path.
  (`subprocess.run` kills the child on TimeoutExpired itself.) Blocking nature
  unchanged (grandfathered per CLAUDE.md:369).

**Test:** `tests/reporting/test_report_generator.py::
test_report_generation_graceful_on_soffice_timeout` — patches `shutil.which`
to report soffice present, patches `subprocess.run` to raise `TimeoutExpired`,
asserts `generate()` returns with `pdf_path is None` and the editable docx
still exists, no exception bubbles.

**Result:** PASS (`2 passed in 85s` with the WEB-M2 test).

---

## WEB-M1 (MED) — unbounded reads (`/history?minutes=`, `/api/log?limit=`)

**Prod change:** `src/cryodaq/web/server.py`
- Added constants `_HISTORY_MAX_MINUTES = 1440` (24 h, covers the dashboard's
  longest window) and `_LOG_MAX_LIMIT = 2000`.
- `_query_history`: clamp `minutes = max(1, min(minutes, _HISTORY_MAX_MINUTES))`
  at the top, before computing the cutoff (bounds the executor path regardless
  of caller).
- `api_log`: clamp `limit = max(1, min(limit, _LOG_MAX_LIMIT))` before
  forwarding to the engine.

**Test:** `tests/web/test_read_bounds.py` (new, 2 tests)
- `test_query_history_clamps_oversized_minutes` — patches the data dir + a fake
  sqlite connection, calls `_query_history(99999999)`, asserts the effective
  `cutoff_epoch` passed to the SQL query is no older than
  `now - (_HISTORY_MAX_MINUTES + 1) min` (i.e. clamped, not the raw value).
- `test_api_log_clamps_oversized_limit` — patches `_send_engine_command`,
  invokes the `/api/log` route handler with `limit=10_000_000`, asserts the
  forwarded command's `limit == _LOG_MAX_LIMIT`.

**Result:** PASS (`6 passed` in `tests/web`).

---

## WEB-M2 (MED) — Gemma intro skips xml_safe

**Prod change:** `src/cryodaq/reporting/generator.py:_render_gemma_annotation`
- Import `xml_safe` and wrap each intro paragraph:
  `document.add_paragraph(xml_safe(para.strip()))` — matching the sibling
  fields in `sections.py`.

**Test:** `tests/reporting/test_report_generator.py::
test_gemma_intro_with_control_char_renders_without_raising` — calls
`_render_gemma_annotation` with an intro containing a bell char (`\x07`, illegal
in XML 1.0), asserts the heading + both paragraphs render and `\x07` is stripped
(no exception).

**Result:** PASS.

---

## Verification summary

- `pytest tests/web -p no:cacheprovider -q` → **6 passed**.
- `CRYODAQ_ALLOW_BROKEN_SQLITE=1 pytest <2 new reporting tests>` → **2 passed**.
- `ruff check --line-length 120` on all 4 touched files → **All checks passed**.
- LSP (`ty`) unavailable in this environment; relied on ruff + green tests.

## Residual gap found

- `CLAUDE.md:81` still shows `uvicorn ... --host 0.0.0.0 --port 8080`. It is the
  same public-bind footgun as WEB-H1 but was OUT OF the assessment's named
  3-site scope, so left untouched per guardrails. Recommend a follow-up doc fix
  to align it with the loopback default.
