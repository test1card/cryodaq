# Reporting / Analytics / Plugins Deep Dive

**Date:** 2026-04-09  
**Branch:** `master`  
**Scope:** `reporting/`, `analytics/`, root `plugins/`  
**Files read completely:** 17  
**Note:** `sensor_diagnostics.py` exists in `src/cryodaq/core/`, not `src/cryodaq/analytics/`; that core file was read because the requested analytics file does not exist.

## Summary

- Numerical issues: 5
- Reporting robustness gaps: 4
- Calibration integrity gaps: 2
- Plugin trust / hot-reload issues: 3
- Severity totals: 3 HIGH, 8 MEDIUM, 1 LOW

## Files covered

- `src/cryodaq/reporting/data.py`
- `src/cryodaq/reporting/sections.py`
- `src/cryodaq/reporting/generator.py`
- `src/cryodaq/analytics/calibration.py`
- `src/cryodaq/analytics/calibration_fitter.py`
- `src/cryodaq/analytics/cooldown_predictor.py`
- `src/cryodaq/analytics/cooldown_service.py`
- `src/cryodaq/core/rate_estimator.py`
- `src/cryodaq/analytics/vacuum_trend.py`
- `src/cryodaq/analytics/plugin_loader.py`
- `src/cryodaq/core/sensor_diagnostics.py`
- `plugins/cooldown_estimator.py`
- `plugins/cooldown_estimator.yaml`
- `plugins/phase_detector.py`
- `plugins/phase_detector.yaml`
- `plugins/thermal_calculator.py`
- `plugins/thermal_calculator.yaml`

## Analysis 1: Numerical correctness in analytics

### A1. [MEDIUM] `cooldown_predictor.predict()` can normalize an all-zero weight vector into NaNs

**Location:** `src/cryodaq/analytics/cooldown_predictor.py:417-468`

**Why it matters:** if `t_elapsed` is badly skewed relative to all reference curves, every Gaussian progress weight can underflow to `0.0`. The code then divides by `weights.sum()` without checking for zero. That produces `NaN` ensemble weights, and the ETA / confidence values become `NaN` as well.

```python
for rc in model.curves:
    if rc._t_of_p is None:
        continue
    t_at_p = float(rc._t_of_p(p_now))
    t_rem = max(0, rc.duration_hours - t_at_p)

    if t_elapsed > 0:
        sigma_t = max(1.0, model.duration_std)
        w_prog = np.exp(-0.5 * ((t_at_p - t_elapsed) / sigma_t) ** 2)
    else:
        w_prog = 1.0

    w_rate = 1.0
    ...
    w_total = w_prog * w_rate
    estimates.append((rc.name, t_rem, rc.duration_hours, w_total, w_prog, w_rate))

...
weights = np.array([e[3] for e in estimates])
weights /= weights.sum()

t_rem_mean = float(np.average(t_rems, weights=weights))
```

**Minimal failing scenario:**

1. A caller supplies `t_elapsed` that is orders of magnitude larger than all reference `t_at_p` values.
2. Each `w_prog` becomes numerically `0.0`.
3. `weights.sum()` is `0.0`.
4. `weights /= weights.sum()` yields all-`NaN`.
5. `np.average(..., weights=weights)` returns `NaN` ETA values that get published downstream.

**Severity rationale:** not hardware-damaging, but a real numerical failure in a live analytics path.

### A2. [MEDIUM] `CooldownService` and the shipped `cooldown_estimator` plugin mix reading timestamps with current wall clock

**Locations:**

- `src/cryodaq/analytics/cooldown_service.py:297-315`
- `src/cryodaq/analytics/cooldown_service.py:351-367`
- `plugins/cooldown_estimator.py:165-175`
- `plugins/cooldown_estimator.py:288-290`

**Why it matters:** both code paths ingest historical/readout timestamps from `Reading.timestamp`, but then compute elapsed time or trim windows against `time.time()` / `datetime.now()`. A backward NTP correction, replayed historical data, or stale timestamps after reconnect will skew ETA and rate logic.

```python
reading_ts = reading.timestamp.timestamp()
...
if phase in (CooldownPhase.COOLING, CooldownPhase.STABILIZING):
    if self._cooldown_wall_start is None:
        self._cooldown_wall_start = reading_ts

    t_hours = (reading_ts - self._cooldown_wall_start) / 3600.0
    ...

# Compute elapsed time
if self._cooldown_wall_start is not None and cooldown_active:
    t_elapsed = (time.time() - self._cooldown_wall_start) / 3600.0
```

```python
for reading in relevant:
    t_s = reading.timestamp.timestamp()
    self._buffer.append((t_s, reading.value))

t_now = datetime.now(timezone.utc).timestamp()
t_cutoff = t_now - self._fit_window_s
...
t_target_from_t0 = -tau * math.log(ratio)
t_now_from_t0 = t_now - t0
t_remaining = t_target_from_t0 - t_now_from_t0
```

**Minimal failing scenario:**

1. Readings carry a timestamp stream anchored before an NTP backward jump or after replay/restart.
2. Buffer history uses reading timestamps, but ETA uses current wall clock.
3. `t_elapsed` or `t_now_from_t0` becomes too large, too small, or even negative relative to the data.
4. Predictor weight selection or plugin ETA shifts sharply or drops to empty/NaN.

**Severity rationale:** operationally important because the user explicitly cares about rare-data-loss / long-run edge cases, and these cooldown analytics are long-lived.

### A3. [MEDIUM] `VacuumTrendPredictor.push()` accepts `NaN` pressures and stores `NaN` in the fit buffer

**Location:** `src/cryodaq/analytics/vacuum_trend.py:125-134`

**Why it matters:** the only guard is `pressure_mbar <= 0`. For `NaN`, that comparison is false, so `math.log10(pressure_mbar)` runs and appends `NaN` to the internal buffer. The fitter later feeds those arrays into SciPy/numpy logic.

```python
def push(self, timestamp: float, pressure_mbar: float) -> None:
    """Add a pressure reading. Rejects P <= 0 (log₁₀ undefined)."""
    if pressure_mbar <= 0:
        return
    log_p = math.log10(pressure_mbar)
    self._buffer.append((timestamp, log_p))
    cutoff = timestamp - self.window_s
    while self._buffer and self._buffer[0][0] < cutoff:
        self._buffer.popleft()
```

**Minimal failing scenario:**

1. Upstream publishes `pressure_mbar = float("nan")`.
2. `pressure_mbar <= 0` is false.
3. `math.log10(nan)` returns `nan`.
4. Buffer now contains `NaN`; model fitting may fail or silently degrade to “insufficient_data”.

**Severity rationale:** the predictor degrades rather than corrupting hardware state, but this is avoidable NaN propagation.

### A4. [MEDIUM] `VacuumTrendPredictor` assumes every configured target pressure is strictly positive

**Location:** `src/cryodaq/analytics/vacuum_trend.py:330-356`

**Why it matters:** `targets_mbar` comes from config, but `update()` computes `math.log10(target)` with no validation. A zero or negative target crashes ETA generation with a math-domain error.

```python
for target in self.targets:
    log_target = math.log10(target)
    key = str(target)

    if logP_now <= log_target:
        result[key] = 0.0
        continue

    if log_p_ult > log_target:
        result[key] = None
        continue

    eta = self._binary_search_eta(fit, t_current, log_target)
    result[key] = eta
```

**Minimal failing scenario:**

1. Operator sets `targets_mbar: [1e-5, 0]` or `[-1e-6]`.
2. `update()` reaches `_compute_eta()`.
3. `math.log10(target)` raises `ValueError`.
4. No local guard catches it at this layer.

### A5. [MEDIUM] `cooldown_estimator` root plugin is numerically stable on paper, but its ETA depends on wall-clock trim rather than data-window trim

**Location:** `plugins/cooldown_estimator.py:165-175`, `plugins/cooldown_estimator.py:288-290`

**Why it matters:** the regression itself guards logarithm domain and slope sign well, but the buffer window is trimmed by `datetime.now()` instead of the newest reading timestamp. If the lab PC clock jumps or analytics is fed delayed readings, the effective fit window becomes unrelated to the actual measurement window.

```python
for reading in relevant:
    t_s = reading.timestamp.timestamp()
    self._buffer.append((t_s, reading.value))

...
t_now = datetime.now(timezone.utc).timestamp()
t_cutoff = t_now - self._fit_window_s
while self._buffer and self._buffer[0][0] < t_cutoff:
    self._buffer.popleft()
```

```python
t_target_from_t0 = -tau * math.log(ratio)
t_now_from_t0 = t_now - t0
t_remaining = t_target_from_t0 - t_now_from_t0
```

**Minimal failing scenario:** a stale packet burst after reconnect can be immediately trimmed away or interpreted as “already elapsed”, producing an empty result or a negative ETA.

## Analysis 2: Reporting pipeline robustness

### R1. [HIGH] A single section exception aborts the entire report build and can leave only partial artifacts behind

**Location:** `src/cryodaq/reporting/generator.py:71-109`

**Why it matters:** the generator builds a raw DOCX, optionally converts it to PDF, then builds an editable DOCX. There is no per-section isolation and no transaction/cleanup. Any exception inside one renderer stops the whole report generation after some files may already exist.

```python
reports_dir.mkdir(parents=True, exist_ok=True)
assets_dir.mkdir(parents=True, exist_ok=True)

raw_sections = self._resolve_raw_sections(dataset.metadata)
editable_sections = tuple(list(raw_sections) + list(self._EDITABLE_ONLY_SECTIONS))

raw_document = self._build_document(dataset, assets_dir, raw_sections)
raw_document.save(str(raw_source_docx_path))
pdf_path = self._try_convert_pdf(raw_source_docx_path, raw_pdf_path)

editable_document = self._build_document(dataset, assets_dir, editable_sections)
editable_document.save(str(editable_docx_path))
...
for index, section_name in enumerate(sections):
    ...
    renderer = SECTION_REGISTRY[section_name]
    renderer(document, dataset, assets_dir)
```

**Minimal failing scenario:**

1. Raw sections start rendering successfully.
2. `render_conductivity_section()` or another section raises `ValueError`, `KeyError`, `PermissionError`, or a matplotlib error.
3. `generate()` aborts immediately.
4. `report_raw.docx` may exist, while editable DOCX and/or PDF do not.

**Severity rationale:** full report generation fails on a single bad subsection, which is an operational blocker for post-run artifact generation.

### R2. [MEDIUM] LibreOffice PDF conversion failures are silent

**Location:** `src/cryodaq/reporting/generator.py:207-224`

**Why it matters:** `subprocess.run(..., check=False, capture_output=True)` discards both the return code and stderr/stdout. The only observable behavior is “PDF missing”, with no structured log about why conversion failed.

```python
def _try_convert_pdf(self, source_docx_path: Path, target_pdf_path: Path) -> Path | None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    output_dir = source_docx_path.parent
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", str(source_docx_path), "--outdir", str(output_dir)],
        check=False,
        capture_output=True,
    )
    produced = output_dir / f"{source_docx_path.stem}.pdf"
    if not produced.exists():
        return None
```

**Minimal failing scenario:** `soffice` returns non-zero because of a corrupt DOCX, missing fonts, read-only output directory, or disk-full condition; the code just returns `None`.

### R3. [MEDIUM] `ReportDataExtractor` crashes on blank or malformed experiment timestamps

**Location:** `src/cryodaq/reporting/data.py:56-67`, `src/cryodaq/reporting/data.py:192-200`

**Why it matters:** `load_dataset()` assumes `experiment.start_time` and `experiment.end_time` are always parseable ISO strings. `_parse_time()` does not handle blank strings and raises immediately.

```python
def load_dataset(self, metadata_path: Path) -> ReportDataset:
    metadata = self.load_metadata(metadata_path)
    experiment = metadata.get("experiment", {})
    start_time = self._parse_time(experiment.get("start_time"))
    end_time = self._parse_time(experiment.get("end_time")) or datetime.now(timezone.utc)
    experiment_id = experiment.get("experiment_id")
    ...

@staticmethod
def _parse_time(raw: Any) -> datetime:
    text = str(raw or "").strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
```

**Minimal failing scenario:** `metadata.json` contains `""` or omits `end_time`; `datetime.fromisoformat("")` raises `ValueError` before any fallback can run.

### R4. [MEDIUM] `render_conductivity_section()` trusts CSV schema and numeric cells, so one bad row aborts report generation

**Location:** `src/cryodaq/reporting/sections.py:446-482`

**Why it matters:** there is no per-row validation or exception handling around `float(item["temperature_k"])` / `float(item["conductance_wk"])`. If the archive table has a missing column, a non-numeric cell, or `NaN`/`inf` combinations that break rendering, the whole report path fails because generator-level section isolation is absent.

```python
path = _find_table_path(dataset, "conductivity_vs_temperature")
if path is None:
    document.add_paragraph("График теплопроводности для этой карточки отсутствует.")
    return
with path.open(encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    rows = list(reader)
if not rows:
    document.add_paragraph("График теплопроводности не удалось построить: таблица пуста.")
    return
temps = [float(item["temperature_k"]) for item in rows]
conds = [float(item["conductance_wk"]) for item in rows]
plt.figure(figsize=(6, 4))
plt.plot(temps, conds, marker="o")
```

**Minimal failing scenario:** one row has `conductance_wk=""` or the CSV header changed; `float(...)` or `item[...]` raises, and the entire report build aborts.

## Analysis 3: Calibration store integrity

### C1. [HIGH] Calibration curve and index writes are non-atomic and unlocked; concurrent writers can clobber each other

**Locations:**

- `src/cryodaq/analytics/calibration.py:201-213`
- `src/cryodaq/analytics/calibration.py:339-345`
- `src/cryodaq/analytics/calibration.py:731-759`

**Why it matters:** `CalibrationStore` keeps `_curves` and `_assignments` in memory, loads the index only at initialization, and rewrites the full `index.yaml` on each change. There is no file lock, no temp-file-and-rename sequence, and no reload-before-write merge.

```python
def __init__(self, base_dir: Path | None = None) -> None:
    self._base_dir = base_dir
    self._curves_dir = base_dir / "curves" if base_dir is not None else None
    self._exports_dir = base_dir / "exports" if base_dir is not None else None
    self._index_path = base_dir / "index.yaml" if base_dir is not None else None
    self._curves: dict[str, CalibrationCurve] = {}
    self._assignments: dict[str, dict[str, Any]] = {}
    ...
    if self._index_path is not None:
        self._load_index()
```

```python
def save_curve(self, curve: CalibrationCurve, path: Path | None = None) -> Path:
    target = path or self._curve_path(curve.sensor_id, curve.curve_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(curve.to_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
    self._curves[curve.sensor_id] = curve
    self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
    self._write_index()
```

```python
def _write_index(self) -> None:
    if self._index_path is None:
        return
    self._index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        ...
        "assignments": [dict(item) for item in self.list_assignments()],
    }
    self._index_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
```

**Minimal failing scenarios:**

1. Process A and process B both instantiate `CalibrationStore`.
2. Each loads its own in-memory `_assignments`.
3. A writes a new curve; B writes a channel policy later from stale memory.
4. B’s `_write_index()` rewrites the full YAML and can drop A’s newly added assignment/curve metadata.

Second scenario:

1. `write_text()` is interrupted by disk-full or crash.
2. `curve.json` or `index.yaml` is left truncated.
3. Next startup hits malformed JSON/YAML.

**Severity rationale:** this is an integrity problem in calibration metadata, not just a cosmetic export issue.

### C2. [MEDIUM] A corrupted `index.yaml` crashes `CalibrationStore` initialization

**Location:** `src/cryodaq/analytics/calibration.py:705-709`

**Why it matters:** `_load_index()` has no `try/except` around file read or `yaml.safe_load()`. Any YAML truncation, malformed syntax, or filesystem error propagates out of `__init__`.

```python
def _load_index(self) -> None:
    if self._index_path is None or not self._index_path.exists():
        return
    payload = yaml.safe_load(self._index_path.read_text(encoding="utf-8")) or {}
    runtime = payload.get("runtime", {})
```

**Minimal failing scenario:** interrupted `_write_index()` leaves half a YAML document; the next `CalibrationStore(base_dir)` raises during startup.

## Analysis 4: Plugin pipeline and shipped root plugins

### Plugin inventory

| Plugin file | Input channels | Published metrics | Notes |
|---|---|---|---|
| `plugins/cooldown_estimator.py` | one configured temperature channel | `analytics/cooldown_estimator/cooldown_eta_s` | exponential ETA fit, read-only |
| `plugins/phase_detector.py` | one temperature channel, optional pressure channel | `detected_phase`, `dT_dt_K_per_min`, `phase_confidence`, `stable_at_target_s` | phase inference, read-only |
| `plugins/thermal_calculator.py` | hot sensor, cold sensor, heater power | `analytics/thermal_calculator/R_thermal` | steady-state thermal resistance |

All three shipped plugins are pure in-process compute plugins. They do not spawn subprocesses or write files themselves.

### P1. [HIGH] Plugin pipeline is unsandboxed and has no per-plugin timeout; one hung plugin blocks the whole analytics chain

**Locations:**

- `src/cryodaq/analytics/plugin_loader.py:145-156`
- `src/cryodaq/analytics/plugin_loader.py:263-287`

**Why it matters:** plugin files are imported as arbitrary Python modules into the main process, and `plugin.process(batch)` is awaited serially with no timeout. An infinite loop or a stuck await inside one plugin blocks all later plugins and all analytics publication.

```python
spec = importlib.util.spec_from_file_location(
    f"cryodaq_plugin_{plugin_id}", path
)
...
module: types.ModuleType = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
```

```python
for plugin in list(self._plugins.values()):
    plugin_id = plugin.plugin_id
    try:
        metrics: list[DerivedMetric] = await plugin.process(batch)
    except Exception as exc:
        logger.error(
            "Плагин '%s' выбросил исключение при обработке пакета: %s",
            plugin_id,
            exc,
        )
        continue

    for metric in metrics:
        reading = Reading.now(...)
        await self._broker.publish(reading)
```

**Minimal failing scenario:**

1. A plugin hot-reload introduces `while True: pass` or an awaited operation that never returns.
2. `_process_loop()` awaits that plugin forever.
3. Later plugins never run.
4. No analytics-derived metrics are published until restart.

**Severity rationale:** one bad plugin stalls all analytics, and the trust model is fully in-process.

### P2. [MEDIUM] Hot reload unloads the old plugin before proving the new plugin/config can load

**Location:** `src/cryodaq/analytics/plugin_loader.py:312-321`

**Why it matters:** a changed file triggers `_unload_plugin()` first and `_load_plugin()` second. If the new Python file imports a missing dependency, or the new YAML breaks `configure()`, there is an immediate availability gap.

```python
for filename, mtime in current_files.items():
    if filename not in known_files:
        ...
    elif known_files[filename] != mtime:
        logger.info(
            "Файл плагина изменён, перезагрузка: %s", filename
        )
        self._unload_plugin(Path(filename).stem)
        self._load_plugin(self._plugins_dir / filename)
```

**Minimal failing scenario:**

1. `phase_detector.py` is edited and saved.
2. Watch loop unloads the current plugin.
3. New version fails import or YAML configure.
4. The plugin remains absent until the next good save/restart.

### P3. [LOW] Malformed plugin YAML still leaves the plugin registered with default/partial state

**Location:** `src/cryodaq/analytics/plugin_loader.py:186-201`

**Why it matters:** configuration errors are logged, but `_plugins[plugin_id] = plugin` still runs. For the current shipped plugins this usually means “quiet no-op” or warning spam rather than incorrect math, but it is still surprising behavior.

```python
config_path = path.with_suffix(".yaml")
if config_path.exists():
    try:
        with config_path.open("r", encoding="utf-8") as fh:
            config: dict[str, Any] = yaml.safe_load(fh) or {}
        plugin.configure(config)
        logger.debug("Конфиг '%s' применён к плагину '%s'", config_path, plugin_id)
    except Exception as cfg_exc:
        logger.error(
            "Ошибка загрузки конфига '%s' для плагина '%s': %s",
            config_path,
            plugin_id,
            cfg_exc,
        )

self._plugins[plugin_id] = plugin
```

**Minimal failing scenario:** `phase_detector.yaml` is malformed; loader logs the error, but the plugin remains active with empty channel config and silently publishes nothing.

## Additional numerical / robustness notes

### OK1. Reporting mostly handles zero-reading experiments gracefully

I did not find a crash path for “experiment has zero readings” in the common sections. Multiple renderers explicitly short-circuit to placeholder text:

```python
if not readings:
    document.add_paragraph(f"{title}: данные за интервал эксперимента отсутствуют.")
    return
```

```python
if not dataset.run_records:
    document.add_paragraph("Прогоны не выполнялись.")
    return
```

This means the pipeline is not fundamentally allergic to empty datasets; the more realistic failures are malformed metadata and malformed artifact tables.

### OK2. `VacuumTrendPredictor` does catch SciPy fit failures and degrades to “no fit” rather than crashing

All three fit methods wrap `curve_fit()` in exception handling and return `None` on failure:

```python
try:
    popt, _ = curve_fit(...)
    ...
    return FitResult(...)
except (RuntimeError, ValueError, TypeError):
    return None
```

That containment is good. The remaining problem is pre-fit input validation, not unhandled SciPy exceptions.

### OK3. `SensorDiagnosticsEngine` is conservative around degenerate statistics

I did not find divide-by-zero bugs in its core helpers. Examples:

```python
if len(values) < 2:
    return float("nan")
...
if sx == 0.0 or sy == 0.0:
    return None
...
if sigma == 0.0 or not math.isfinite(sigma):
    return 0
```

So the diagnostics path is much better defended against empty/constant inputs than the cooldown/vacuum predictors.

### OK4. Current shipped root plugins are read-only computation plugins

`cooldown_estimator.py`, `phase_detector.py`, and `thermal_calculator.py` only consume readings and emit derived metrics. I did not find filesystem writes, subprocess launches, or direct broker/socket manipulation in the shipped plugin files themselves. The trust risk sits in the loader architecture, not in these three specific plugins.

## Most important conclusions

1. The reporting pipeline is brittle at the section boundary. One malformed artifact table or plotting failure can abort the whole report build.
2. Calibration storage still lacks atomic file replacement and inter-process coordination. If two writers touch it, last-writer-wins clobbering is possible.
3. The plugin system is intentionally powerful but operationally fragile: no sandbox, no timeout, and unload-before-load hot reload.
4. The most serious numerical issue in this pass is the all-zero weight normalization in `cooldown_predictor`.
5. Timebase mixing is repeated in both `cooldown_service` and the shipped `cooldown_estimator` plugin; it is not an isolated bug.
