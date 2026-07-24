# CryoDAQ — Replacement-Cost Estimate

**Purpose:** defensible estimate of what it would cost a traditional team (no AI) to
build CryoDAQ from scratch. Used to justify replacement value. Every figure traces to a
measured metric or a stated rate. Deliberately conservative.

Measured: 2026-06-17. Repo: `Projects/cryodaq`, HEAD on `main`.

---

## Part 1 — Objective code metrics

SLOC counted as **non-blank physical lines** (a `cloc`/`scc` substitute; comment lines
included, so ~10–15% above pure logical code — corrected below).

| Category | Non-blank lines | Files | Notes |
|---|---:|---:|---|
| **Production code** (`src/cryodaq/`, Python) | **59,425** | 218 | the deliverable |
| **Tests** (Python) | 49,774 | 329 | 3,158 test functions |
| Scripts / tools / build (Python) | 3,125 | 23 | |
| Config (hand-written: yaml/toml/json) | ~1,200 | ~10 | `channels.yaml`, `alarms_v3.yaml`, `pyproject.toml`… |
| Web (HTML/JS/CSS) | 706 | 1 | web dashboard |
| Docs (md/rst) authored | ~20,000 | (of 469) | see caveat |

**Caveats on the raw totals** (why the headline uses *production code*, not the gross count):
- "Config 190k lines / 70 files" in a naïve scan is **experimental data**, not code:
  `cooldown_v5/*.json` are ~20k-line measurement runs each. Excluded.
- "Docs 202k lines" is dominated by an auto-generated `CHANGELOG.md` (219 KB) and an
  Obsidian planning vault. Only ~20k lines are genuinely hand-authored prose. Excluded
  from the cost basis (treated as zero-effort by-product).

**Language:** 112,324 lines of Python total (prod + test + tooling); HTML 706; shell/batch ~190.

**Tests:** 3,158 `test_` functions across 329 files, 4 `conftest.py`. Test-to-prod ratio
≈ 0.84:1 by SLOC — a mature, well-covered codebase (a real team *must* fund this work).

**Version control / cadence:**
- **821 commits**, **76 tags/releases** (v0.x → v0.56.4).
- First commit 2026-03-14, last 2026-05-15 → **~2 months** wall-clock.
- **42 active commit-days** — sustained, near-daily intensity.
- Authors: Vladimir (human) + Claude (AI pair) — effectively **one engineer + AI**.

### Architecture map (production submodules, by SLOC)

| Module | SLOC | Subsystem |
|---|---:|---|
| `gui/` | 23,526 | PySide6 desktop UI: main window, live plots, analytics view, widgets |
| `core/` | 9,075 | **Safety FSM** (`interlock`, `safety_broker`, `safety_manager`), alarms, cooldown alarm |
| `agents/` | 5,926 | LLM assistant + **RAG** query engine over the system |
| `analytics/` | 4,545 | **ML cooldown predictor / forecasting service** |
| `engine.py` | 3,462 | acquisition / experiment engine (async core) |
| `drivers/` | 3,212 | **3 transport buses** (GPIB, USB-TMC, RS-232) + 3 instruments |
| `storage/` | 2,199 | persistence-first data layer |
| `notifications/` | 1,760 | alerting / sinks |
| `launcher.py` | 1,370 | process bootstrap / instance lock |
| `reporting/` | 1,178 | experiment reports |
| `replay_engine/`, `replay/` | 1,282 | lazy replay of recorded runs |
| `web/`, `sinks/`, `tools/`, misc | ~1,900 | ZMQ web bridge, CLI tools |

Hardware integration is **real**, not mocked-only: drivers for **Keithley 2604B**
(sourcemeter), **LakeShore 218S** (temperature monitor), **Thyracont VSP63D** (pressure),
each over its own bus. **70 source files use `asyncio`** → genuinely asynchronous core.

---

## Part 2 — Effort (three independent methods)

### Cost basis
Logical production SLOC = 59,425 × ~0.88 (comment discount) ≈ **52 KSLOC**.
This is the COCOMO input. Tests/docs are **not** added to the input (COCOMO effort
already includes the test phase) — they appear later as a sanity check.

### Method A — Basic COCOMO-81  (`Effort_PM = a · KSLOC^b`)

| Mode | a | b | Effort (PM) | Justification |
|---|---|---|---:|---|
| Semi-detached | 3.0 | 1.12 | **251** | mixed app + systems work |
| Embedded | 3.6 | 1.20 | **412** | hardware-in-loop, safety-critical, real-time |

`3.0 · 52^1.12 = 251 PM`; `3.6 · 52^1.20 = 412 PM`.

### Method B — COCOMO II Post-Architecture
`Effort = 2.94 · Size^E · Π(EM)`, `E = 0.91 + 0.01·ΣSF`.

- Scale factors (PREC 4.96 low-precedentedness, FLEX 2.03, RESL 2.83, TEAM 1.10 solo,
  PMAT 4.68) → ΣSF ≈ 15.6 → **E = 1.066**.
- Effort multipliers raised above nominal, each justified:
  **RELY = 1.26** (safety-critical), **CPLX = 1.34** (real-time device control + concurrency),
  **TIME = 1.11** (real-time execution constraint). Others nominal. → **Π EM ≈ 1.87**.
- `2.94 · 52^1.066 · 1.87 ≈ **371 PM**`.

### Method C — Empirical productivity (the defensible anchor)

COCOMO-81/II were calibrated on assembly and 3GL code; they **systematically
over-estimate** modern high-level-language work by ~3–6×. Taken literally, Methods A/B
imply 21–34 person-years for a 52 KSLOC Python codebase — a number a skeptic correctly
rejects. So the headline uses measured industry productivity instead.

Delivered engineering artifacts a replacement team must actually produce:
**52k prod + ~50k test SLOC ≈ 100k SLOC** of Python, plus hardware bring-up against
three real instruments and 821 commits of iteration.

Fully-burdened productivity for **instrumentation / safety / embedded-adjacent** software
(includes design, test, debug, integration, meetings) ≈ **15,000–20,000 delivered
SLOC per developer-year**:

| Scenario | SLOC counted | SLOC / dev-yr | Effort |
|---|---:|---:|---:|
| Conservative | 52k (prod only) | 15,000 | **3.5 PY ≈ 42 PM** |
| Realistic | 100k (prod + tests) | 18,000 | **5.5 PY ≈ 66 PM** |

**Reconciliation:** raw COCOMO 251–412 PM (upper bound, language-uncorrected);
empirical 42–66 PM. **Adopted effort: 42 PM (conservative) → 66 PM (realistic).**

### Team-equivalent
- Conservative 42 PM → e.g. **3 engineers × ~14 months**, or 4 × ~10.5 months.
- Realistic 66 PM → **4 engineers × ~16 months** (plus a fraction of a QA/safety reviewer).
A solo human (no AI) could not have produced this in 2 months — the effort is real; it is
the *AI leverage* that compressed it (Part 4).

### Why this project is dearer than its SLOC suggests
COCOMO on bare SLOC under-prices five things, all present here and all reflected in the
`RELY`/`CPLX`/`TIME` multipliers and the embedded mode:
1. **Real hardware over 3 buses** (GPIB / USB-TMC / RS-232) — timing, framing, device
   quirks, and bring-up that can only be debugged against the physical instrument.
2. **Safety-critical state machine** (interlock + broker + manager) — incorrect transitions
   risk equipment/people; demands defensive design, extra review, and exhaustive tests.
3. **Asynchronous architecture** (70 async files) — concurrency bugs are non-deterministic
   and expensive to find.
4. **ML cooldown prediction** — modelling, data plumbing, validation.
5. **Real-time acquisition** — latency/jitter constraints on the hot path.
The 0.84:1 test ratio is the cost of *proving* all of the above works.

---

## Part 3 — Money (Moscow, 2026)

**Rate assumption (stated, not derived):** fully-loaded cost of a senior
developer / АСУ ТП engineer in Moscow = **250,000–400,000 ₽ / month** (salary + taxes +
overhead + equipment). Per the user's brief; used as given.

### Internal-team rebuild

| Scenario | Effort | Rate | Cost |
|---|---:|---:|---:|
| Conservative | 42 PM | 250,000 ₽ | **10.5 M₽** |
| Conservative | 42 PM | 300,000 ₽ | 12.6 M₽ |
| Realistic | 66 PM | 300,000 ₽ | 19.8 M₽ |
| Realistic | 66 PM | 350,000 ₽ | **23.1 M₽** |

**Internal rebuild → ≈ 10–23 M₽.**

### Turnkey via system integrator
Integrators charge **×1.5–2.5** internal cost (margin, risk, warranty):

| | Low (×1.5) | High (×2.5) |
|---|---:|---:|
| on 10.5 M₽ | 15.8 M₽ | — |
| on 23.1 M₽ | — | 57.8 M₽ |

**Integrator turnkey → ≈ 16–58 M₽.**

---

## Final defensible range

| View | Range (₽) | Basis |
|---|---:|---|
| **Conservative replacement (internal)** | **10–13 M₽** | 42 PM × 250–300k |
| **Realistic replacement (internal)** | **18–23 M₽** | 66 PM × 300–350k |
| Turnkey via integrator | 16–58 M₽ | ×1.5–2.5 |

**Headline, skeptic-proof: rebuilding CryoDAQ with a conventional team costs ≈ 10–23 M₽
and takes 3.5–5.5 person-years (a 3–4 person team for 12–18 months).**

---

## Part 4 — Reality correction

- **Traditional estimate:** ~3.5–5.5 person-years of effort; **≈ 10–23 M₽** to rebuild
  internally (16–58 M₽ turnkey).
- **Actual:** delivered in **~2 months by one engineer with AI assistance** (821 commits,
  76 releases, 42 active days).

This is not a contradiction — it is the measurement of AI leverage:

- **Time-to-market:** ~2 months vs **12–18 months** traditional → **~6–9× faster**.
- **Effort/cost:** one engineer-quarter of human time stands in for **3.5–5.5
  person-years** of conventional labour → roughly a **15–25× cost compression**.

The conventional replacement value of the asset is **10–23 M₽**. The fact that it was
produced for a fraction of that, in a fraction of the time, is the value the AI-assisted
engineer delivered — and the basis for the compensation argument.

> Every number above traces to a measured metric (SLOC, commit count, test count,
> module sizes) or an explicitly stated rate/multiplier. The estimate leans
> conservative throughout: COCOMO's higher figures are shown but **not** adopted; the
> headline rests on empirical productivity and the lower end of the Moscow rate band.
