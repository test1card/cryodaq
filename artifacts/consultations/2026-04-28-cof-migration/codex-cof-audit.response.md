Reading additional input from stdin...
OpenAI Codex v0.124.0 (research preview)
--------
workdir: /Users/vladimir/Projects/cryodaq
model: gpt-5.5
provider: openai
approval: never
sandbox: read-only
reasoning effort: high
reasoning summaries: none
session id: 019dd06e-c065-7600-84b4-59448a9a784b
--------
user
Model: gpt-5.5
Reasoning effort: high

# .cof migration audit — literal verifier

You are auditing branch `feat/cof-calibration-export` of the CryoDAQ repo at
~/Projects/cryodaq. Read the files directly. Do NOT summarize — find specific
bugs, gaps, or contradictions.

## Read these files

1. `src/cryodaq/analytics/calibration.py` — full file
2. `tests/analytics/test_calibration.py` — full file

## Verify each item — mark PASS or FAIL with file:line

### A. export_curve_cof() implementation
A1. Method exists on CalibrationStore and calls _write_cof_export(). PASS/FAIL:line
A2. Default path is `<curve_dir>/curve.cof` (not curve.330 or curve.340). PASS/FAIL:line
A3. Calls self._write_index() before returning. PASS/FAIL:line
A4. Returns the Path of the written file. PASS/FAIL:line

### B. _write_cof_export() format correctness
B1. Header contains: sensor_id, curve_id, raw_unit, fit_timestamp, format description, zone_count. List any missing.
B2. Each zone section has: raw_min, raw_max, order, coefficients. List any missing.
B3. Coefficients are formatted with sufficient precision (>=10 significant digits). PASS/FAIL:line
B4. Uses atomic_write_text (not open().write()). PASS/FAIL:line
B5. The Chebyshev domain description in the comment matches what CalibrationZone.evaluate() actually does (check line ~117). PASS/FAIL — quote both strings if mismatch.

### C. .330 removal completeness
C1. export_curve_330 method is absent from the class. PASS/FAIL
C2. import_curve_file: accepted suffixes do NOT include ".330". PASS/FAIL:line
C3. _import_curve_text: no branch for import_format == "330". PASS/FAIL:line
C4. get_curve_artifacts: dict key is "curve_cof_path", not "curve_330_path". PASS/FAIL:line
C5. _write_index: "curve_cof_path" key used, not "curve_330_path". PASS/FAIL:line

### D. .340 preservation
D1. export_curve_340 method still present and unchanged. PASS/FAIL
D2. import_curve_file still accepts ".340". PASS/FAIL:line

### E. Test coverage
E1. test_export_curve_cof_writes_file_with_expected_structure: asserts file exists, suffix, and header content. PASS/FAIL
E2. test_export_curve_cof_preserves_chebyshev_coefficients_round_trip: parses coefficients from .cof and compares to zone.coefficients. Does it verify ALL zones? PASS/FAIL
E3. test_export_curve_330_removed: checks hasattr, not call behavior. Is this adequate? PASS/FAIL + comment
E4. test_import_curve_file_rejects_330_suffix: passes a fake .330 file, expects ValueError. Does the written file have enough rows (>=4) to not fail on row-count check before the suffix check? PASS/FAIL — trace the code path.
E5. Existing test test_export_340_uses_200_breakpoints_and_roundtrips_via_import: still calls export_curve_330? PASS/FAIL

### F. Edge case
F1. export_curve_cof() when CalibrationStore has no base_dir (base_dir=None):
    _curve_directory() raises RuntimeError. Is this the right behavior?
    Trace the call: export_curve_cof -> _curve_directory -> ... PASS/FAIL + line

## Output format
For each item above: `<id>: PASS | FAIL | WARNING — <one line> [file:line]`
Then a findings table of all FAILs/WARNINGs with severity (CRITICAL/HIGH/MEDIUM/LOW).
Then: VERDICT: PASS / CONDITIONAL / FAIL

Write output to:
~/Projects/cryodaq/artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.response.md
codex
I’ll read the required verification skill first, then inspect the two target files with line numbers and produce the audit. The workspace is read-only in this session, so I’ll verify whether I can create the requested artifact before claiming it was written.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/b066e4a0/skills/using-superpowers/SKILL.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
---
name: using-superpowers
description: Use when starting any conversation - establishes how to find and use skills, requiring Skill tool invocation before ANY response including clarifying questions
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill.
</SUBAGENT-STOP>

<EXTREMELY-IMPORTANT>
If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill.

IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE. YOU MUST USE IT.

This is not negotiable. This is not optional. You cannot rationalize your way out of this.
</EXTREMELY-IMPORTANT>

## Instruction Priority

Superpowers skills override default system prompt behavior, but **user instructions always take precedence**:

1. **User's explicit instructions** (CLAUDE.md, GEMINI.md, AGENTS.md, direct requests) — highest priority
2. **Superpowers skills** — override default system behavior where they conflict
3. **Default system prompt** — lowest priority

If CLAUDE.md, GEMINI.md, or AGENTS.md says "don't use TDD" and a skill says "always use TDD," follow the user's instructions. The user is in control.

## How to Access Skills

**In Claude Code:** Use the `Skill` tool. When you invoke a skill, its content is loaded and presented to you—follow it directly. Never use the Read tool on skill files.

**In Copilot CLI:** Use the `skill` tool. Skills are auto-discovered from installed plugins. The `skill` tool works the same as Claude Code's `Skill` tool.

**In Gemini CLI:** Skills activate via the `activate_skill` tool. Gemini loads skill metadata at session start and activates the full content on demand.

**In other environments:** Check your platform's documentation for how skills are loaded.

## Platform Adaptation

Skills use Claude Code tool names. Non-CC platforms: see `references/copilot-tools.md` (Copilot CLI), `references/codex-tools.md` (Codex) for tool equivalents. Gemini CLI users get the tool mapping loaded automatically via GEMINI.md.

# Using Skills

## The Rule

**Invoke relevant or requested skills BEFORE any response or action.** Even a 1% chance a skill might apply means that you should invoke the skill to check. If an invoked skill turns out to be wrong for the situation, you don't need to use it.

```dot
digraph skill_flow {
    "User message received" [shape=doublecircle];
    "About to EnterPlanMode?" [shape=doublecircle];
    "Already brainstormed?" [shape=diamond];
    "Invoke brainstorming skill" [shape=box];
    "Might any skill apply?" [shape=diamond];
    "Invoke Skill tool" [shape=box];
    "Announce: 'Using [skill] to [purpose]'" [shape=box];
    "Has checklist?" [shape=diamond];
    "Create TodoWrite todo per item" [shape=box];
    "Follow skill exactly" [shape=box];
    "Respond (including clarifications)" [shape=doublecircle];

    "About to EnterPlanMode?" -> "Already brainstormed?";
    "Already brainstormed?" -> "Invoke brainstorming skill" [label="no"];
    "Already brainstormed?" -> "Might any skill apply?" [label="yes"];
    "Invoke brainstorming skill" -> "Might any skill apply?";

    "User message received" -> "Might any skill apply?";
    "Might any skill apply?" -> "Invoke Skill tool" [label="yes, even 1%"];
    "Might any skill apply?" -> "Respond (including clarifications)" [label="definitely not"];
    "Invoke Skill tool" -> "Announce: 'Using [skill] to [purpose]'";
    "Announce: 'Using [skill] to [purpose]'" -> "Has checklist?";
    "Has checklist?" -> "Create TodoWrite todo per item" [label="yes"];
    "Has checklist?" -> "Follow skill exactly" [label="no"];
    "Create TodoWrite todo per item" -> "Follow skill exactly";
}
```

## Red Flags

These thoughts mean STOP—you're rationalizing:

| Thought | Reality |
|---------|---------|
| "This is just a simple question" | Questions are tasks. Check for skills. |
| "I need more context first" | Skill check comes BEFORE clarifying questions. |
| "Let me explore the codebase first" | Skills tell you HOW to explore. Check first. |
| "I can check git/files quickly" | Files lack conversation context. Check for skills. |
| "Let me gather information first" | Skills tell you HOW to gather information. |
| "This doesn't need a formal skill" | If a skill exists, use it. |
| "I remember this skill" | Skills evolve. Read current version. |
| "This doesn't count as a task" | Action = task. Check for skills. |
| "The skill is overkill" | Simple things become complex. Use it. |
| "I'll just do this one thing first" | Check BEFORE doing anything. |
| "This feels productive" | Undisciplined action wastes time. Skills prevent this. |
| "I know what that means" | Knowing the concept ≠ using the skill. Invoke it. |

## Skill Priority

When multiple skills could apply, use this order:

1. **Process skills first** (brainstorming, debugging) - these determine HOW to approach the task
2. **Implementation skills second** (frontend-design, mcp-builder) - these guide execution

"Let's build X" → brainstorming first, then implementation skills.
"Fix this bug" → debugging first, then domain-specific skills.

## Skill Types

**Rigid** (TDD, debugging): Follow exactly. Don't adapt away discipline.

**Flexible** (patterns): Adapt principles to context.

The skill itself tells you which.

## User Instructions

Instructions say WHAT, not HOW. "Add X" or "Fix Y" doesn't mean skip workflows.

codex
Using `superpowers:using-superpowers` to follow the required skill workflow. Now I’m reading both target files with line numbers so each PASS/FAIL can be tied to the literal source.
exec
/opt/homebrew/bin/bash -lc 'nl -ba src/cryodaq/analytics/calibration.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Calibration backend: session storage, Chebyshev fits, and artifact IO."""
     2	
     3	from __future__ import annotations
     4	
     5	import csv
     6	import json
     7	import math
     8	import uuid
     9	import warnings
    10	from dataclasses import dataclass, field
    11	from datetime import UTC, datetime
    12	from pathlib import Path
    13	from typing import Any
    14	
    15	import numpy as np
    16	import yaml
    17	from numpy.polynomial import chebyshev as cheb
    18	
    19	
    20	def _utcnow() -> datetime:
    21	    return datetime.now(UTC)
    22	
    23	
    24	def _parse_time(raw: datetime | str | None) -> datetime | None:
    25	    if raw is None:
    26	        return None
    27	    if isinstance(raw, datetime):
    28	        if raw.tzinfo is None:
    29	            return raw.replace(tzinfo=UTC)
    30	        return raw.astimezone(UTC)
    31	    text = str(raw).strip()
    32	    if not text:
    33	        return None
    34	    if text.endswith("Z"):
    35	        text = f"{text[:-1]}+00:00"
    36	    parsed = datetime.fromisoformat(text)
    37	    if parsed.tzinfo is None:
    38	        return parsed.replace(tzinfo=UTC)
    39	    return parsed.astimezone(UTC)
    40	
    41	
    42	def _json_dict(raw: Any) -> dict[str, Any]:
    43	    if raw is None:
    44	        return {}
    45	    if isinstance(raw, dict):
    46	        return {str(key): value for key, value in raw.items()}
    47	    raise ValueError("Expected dictionary payload.")
    48	
    49	
    50	def _safe_path_fragment(value: str) -> str:
    51	    cleaned = "".join("_" if char in '<>:"/\\|?*' else char for char in str(value).strip())
    52	    return cleaned or "unnamed"
    53	
    54	
    55	@dataclass(frozen=True, slots=True)
    56	class CalibrationSample:
    57	    timestamp: datetime
    58	    reference_channel: str
    59	    reference_temperature: float
    60	    sensor_channel: str
    61	    sensor_raw_value: float
    62	    reference_instrument_id: str = ""
    63	    sensor_instrument_id: str = ""
    64	    experiment_id: str | None = None
    65	    metadata: dict[str, Any] = field(default_factory=dict)
    66	
    67	    def to_payload(self) -> dict[str, Any]:
    68	        return {
    69	            "timestamp": self.timestamp.isoformat(),
    70	            "reference_channel": self.reference_channel,
    71	            "reference_temperature": self.reference_temperature,
    72	            "sensor_channel": self.sensor_channel,
    73	            "sensor_raw_value": self.sensor_raw_value,
    74	            "reference_instrument_id": self.reference_instrument_id,
    75	            "sensor_instrument_id": self.sensor_instrument_id,
    76	            "experiment_id": self.experiment_id,
    77	            "metadata": dict(self.metadata),
    78	        }
    79	
    80	    @classmethod
    81	    def from_payload(cls, payload: dict[str, Any]) -> CalibrationSample:
    82	        return cls(
    83	            timestamp=_parse_time(payload.get("timestamp")) or _utcnow(),
    84	            reference_channel=str(payload.get("reference_channel", "")),
    85	            reference_temperature=float(payload.get("reference_temperature", 0.0)),
    86	            sensor_channel=str(payload.get("sensor_channel", "")),
    87	            sensor_raw_value=float(payload.get("sensor_raw_value", 0.0)),
    88	            reference_instrument_id=str(payload.get("reference_instrument_id", "")),
    89	            sensor_instrument_id=str(payload.get("sensor_instrument_id", "")),
    90	            experiment_id=(
    91	                str(payload.get("experiment_id"))
    92	                if payload.get("experiment_id") not in (None, "")
    93	                else None
    94	            ),
    95	            metadata=_json_dict(payload.get("metadata")),
    96	        )
    97	
    98	
    99	@dataclass(frozen=True, slots=True)
   100	class CalibrationZone:
   101	    raw_min: float
   102	    raw_max: float
   103	    order: int
   104	    coefficients: tuple[float, ...]
   105	    rmse_k: float
   106	    max_abs_error_k: float
   107	    point_count: int
   108	
   109	    def contains(self, raw_value: float) -> bool:
   110	        return self.raw_min <= raw_value <= self.raw_max
   111	
   112	    def evaluate(self, raw_value: float) -> float:
   113	        if self.raw_max <= self.raw_min:
   114	            raise ValueError("Calibration zone has invalid range.")
   115	        clipped = min(max(raw_value, self.raw_min), self.raw_max)
   116	        scaled = ((2.0 * (clipped - self.raw_min)) / (self.raw_max - self.raw_min)) - 1.0
   117	        return float(cheb.chebval(scaled, self.coefficients))
   118	
   119	    def to_payload(self) -> dict[str, Any]:
   120	        return {
   121	            "raw_min": self.raw_min,
   122	            "raw_max": self.raw_max,
   123	            "order": self.order,
   124	            "coefficients": list(self.coefficients),
   125	            "rmse_k": self.rmse_k,
   126	            "max_abs_error_k": self.max_abs_error_k,
   127	            "point_count": self.point_count,
   128	        }
   129	
   130	    @classmethod
   131	    def from_payload(cls, payload: dict[str, Any]) -> CalibrationZone:
   132	        return cls(
   133	            raw_min=float(payload.get("raw_min", 0.0)),
   134	            raw_max=float(payload.get("raw_max", 0.0)),
   135	            order=int(payload.get("order", 1)),
   136	            coefficients=tuple(float(value) for value in payload.get("coefficients", [])),
   137	            rmse_k=float(payload.get("rmse_k", 0.0)),
   138	            max_abs_error_k=float(payload.get("max_abs_error_k", 0.0)),
   139	            point_count=int(payload.get("point_count", 0)),
   140	        )
   141	
   142	
   143	@dataclass(frozen=True, slots=True)
   144	class CalibrationCurve:
   145	    curve_id: str
   146	    sensor_id: str
   147	    fit_timestamp: datetime
   148	    raw_unit: str
   149	    sensor_kind: str
   150	    source_session_ids: tuple[str, ...]
   151	    zones: tuple[CalibrationZone, ...]
   152	    metrics: dict[str, Any] = field(default_factory=dict)
   153	    metadata: dict[str, Any] = field(default_factory=dict)
   154	
   155	    def evaluate(self, raw_value: float) -> float:
   156	        if not self.zones:
   157	            raise ValueError("Calibration curve has no fitted zones.")
   158	        for zone in self.zones:
   159	            if zone.contains(raw_value):
   160	                return zone.evaluate(raw_value)
   161	        if raw_value < self.zones[0].raw_min:
   162	            return self.zones[0].evaluate(raw_value)
   163	        return self.zones[-1].evaluate(raw_value)
   164	
   165	    def to_payload(self) -> dict[str, Any]:
   166	        return {
   167	            "schema_version": 1,
   168	            "curve_id": self.curve_id,
   169	            "sensor_id": self.sensor_id,
   170	            "fit_timestamp": self.fit_timestamp.isoformat(),
   171	            "raw_unit": self.raw_unit,
   172	            "sensor_kind": self.sensor_kind,
   173	            "source_session_ids": list(self.source_session_ids),
   174	            "zones": [zone.to_payload() for zone in self.zones],
   175	            "metrics": dict(self.metrics),
   176	            "metadata": dict(self.metadata),
   177	        }
   178	
   179	    @classmethod
   180	    def from_payload(cls, payload: dict[str, Any]) -> CalibrationCurve:
   181	        return cls(
   182	            curve_id=str(payload.get("curve_id", "")),
   183	            sensor_id=str(payload.get("sensor_id", "")),
   184	            fit_timestamp=_parse_time(payload.get("fit_timestamp")) or _utcnow(),
   185	            raw_unit=str(payload.get("raw_unit", "sensor_unit")),
   186	            sensor_kind=str(payload.get("sensor_kind", "generic")),
   187	            source_session_ids=tuple(str(item) for item in payload.get("source_session_ids", [])),
   188	            zones=tuple(CalibrationZone.from_payload(item) for item in payload.get("zones", [])),
   189	            metrics=_json_dict(payload.get("metrics")),
   190	            metadata=_json_dict(payload.get("metadata")),
   191	        )
   192	
   193	
   194	class CalibrationStore:
   195	    """Calibration curve storage and multi-zone Chebyshev fitting."""
   196	
   197	    _TASK_CV_ORDER_RANGE = tuple(range(7, 13))
   198	    _TASK_DOWNSAMPLE_TARGET = 5000
   199	
   200	    def __init__(self, base_dir: Path | None = None) -> None:
   201	        self._base_dir = base_dir
   202	        self._curves_dir = base_dir / "curves" if base_dir is not None else None
   203	        self._exports_dir = base_dir / "exports" if base_dir is not None else None
   204	        self._index_path = base_dir / "index.yaml" if base_dir is not None else None
   205	        self._curves: dict[str, CalibrationCurve] = {}
   206	        self._assignments: dict[str, dict[str, Any]] = {}
   207	        self._runtime_settings: dict[str, Any] = {
   208	            "global_mode": "off",
   209	            "updated_at": "",
   210	        }
   211	        if self._index_path is not None:
   212	            self._load_index()
   213	
   214	    def fit_curve(
   215	        self,
   216	        sensor_id: str,
   217	        samples: list[CalibrationSample] | tuple[CalibrationSample, ...],
   218	        *,
   219	        raw_unit: str = "sensor_unit",
   220	        sensor_kind: str = "generic",
   221	        source_session_ids: list[str] | tuple[str, ...] | None = None,
   222	        max_zones: int = 3,
   223	        min_points_per_zone: int = 6,
   224	        max_order: int = 12,
   225	        target_rmse_k: float = 0.05,
   226	        metadata: dict[str, Any] | None = None,
   227	    ) -> CalibrationCurve:
   228	        if not sensor_id.strip():
   229	            raise ValueError("sensor_id is required for calibration fit.")
   230	        if len(samples) < max(4, min_points_per_zone):
   231	            raise ValueError("Not enough calibration samples for fitting.")
   232	        normalized_samples = self._preprocess_samples(
   233	            samples,
   234	            downsample_target=self._TASK_DOWNSAMPLE_TARGET,
   235	        )
   236	        if len(normalized_samples) < max(4, min_points_per_zone):
   237	            raise ValueError("Not enough calibration samples for fitting after preprocessing.")
   238	
   239	        temperatures = np.array(
   240	            [sample.reference_temperature for sample in normalized_samples], dtype=float
   241	        )
   242	        raw_values = np.array(
   243	            [sample.sensor_raw_value for sample in normalized_samples], dtype=float
   244	        )
   245	
   246	        if not np.all(np.isfinite(raw_values)) or not np.all(np.isfinite(temperatures)):
   247	            raise ValueError("Calibration samples must contain finite values only.")
   248	        if np.ptp(raw_values) <= 0 or np.ptp(temperatures) <= 0:
   249	            raise ValueError("Calibration raw values must span a non-zero range.")
   250	        zone_slices = self._detect_zone_slices(
   251	            temperatures,
   252	            raw_values,
   253	            max_zones=max(1, max_zones),
   254	            min_points_per_zone=max(3, min_points_per_zone),
   255	            max_order=max(1, max_order),
   256	        )
   257	        zones = self._fit_zone_slices(
   258	            temperatures,
   259	            raw_values,
   260	            zone_slices=zone_slices,
   261	            max_order=max(1, max_order),
   262	            target_rmse_k=max(float(target_rmse_k), 0.0),
   263	        )
   264	
   265	        all_predictions = np.array(
   266	            [self._evaluate_zones(zones, raw_value) for raw_value in raw_values],
   267	            dtype=float,
   268	        )
   269	        residuals = all_predictions - temperatures
   270	        sensitivity = np.gradient(raw_values, temperatures)
   271	        curve = CalibrationCurve(
   272	            curve_id=uuid.uuid4().hex[:12],
   273	            sensor_id=sensor_id.strip(),
   274	            fit_timestamp=_utcnow(),
   275	            raw_unit=raw_unit.strip() or "sensor_unit",
   276	            sensor_kind=sensor_kind.strip() or "generic",
   277	            source_session_ids=tuple(str(item) for item in (source_session_ids or ()) if str(item)),
   278	            zones=tuple(zones),
   279	            metrics={
   280	                "sample_count": int(len(normalized_samples)),
   281	                "input_sample_count": int(len(samples)),
   282	                "downsampled_sample_count": int(len(normalized_samples)),
   283	                "downsampling_applied": bool(len(normalized_samples) != len(samples)),
   284	                "zone_count": int(len(zones)),
   285	                "rmse_k": float(math.sqrt(np.mean(np.square(residuals)))),
   286	                "max_abs_error_k": float(np.max(np.abs(residuals))),
   287	                "raw_min": float(np.min(raw_values)),
   288	                "raw_max": float(np.max(raw_values)),
   289	                "temperature_min_k": float(np.min(temperatures)),
   290	                "temperature_max_k": float(np.max(temperatures)),
   291	                "zone_detection": "dV/dT",
   292	                "order_selection": "cross_validation",
   293	                "cv_order_candidates": list(self._TASK_CV_ORDER_RANGE),
   294	                "target_rmse_k": float(target_rmse_k),
   295	                "sensitivity_min": float(np.min(sensitivity)),
   296	                "sensitivity_max": float(np.max(sensitivity)),
   297	            },
   298	            metadata={
   299	                **_json_dict(metadata),
   300	                "preprocessing": {
   301	                    "downsample_target": self._TASK_DOWNSAMPLE_TARGET,
   302	                    "input_sample_count": len(samples),
   303	                    "output_sample_count": len(normalized_samples),
   304	                },
   305	            },
   306	        )
   307	        self._curves[curve.sensor_id] = curve
   308	        return curve
   309	
   310	    def evaluate(self, sensor_id: str, raw_value: float, *, magnetic_field_T: float = 0.0) -> float:
   311	        del magnetic_field_T
   312	        curve = self._require_curve(sensor_id)
   313	        return curve.evaluate(float(raw_value))
   314	
   315	    def voltage_to_temp(
   316	        self,
   317	        sensor_id: str,
   318	        voltage: float,
   319	        *,
   320	        magnetic_field_T: float = 0.0,
   321	    ) -> float:
   322	        return self.evaluate(sensor_id, voltage, magnetic_field_T=magnetic_field_T)
   323	
   324	    def T_from_V(
   325	        self,
   326	        sensor_id: str,
   327	        voltage: float,
   328	        *,
   329	        magnetic_field_T: float = 0.0,
   330	    ) -> float:
   331	        return self.voltage_to_temp(sensor_id, voltage, magnetic_field_T=magnetic_field_T)
   332	
   333	    def resistance_to_temp(
   334	        self,
   335	        sensor_id: str,
   336	        resistance: float,
   337	        *,
   338	        magnetic_field_T: float = 0.0,
   339	    ) -> float:
   340	        return self.evaluate(sensor_id, resistance, magnetic_field_T=magnetic_field_T)
   341	
   342	    def save_curve(self, curve: CalibrationCurve, path: Path | None = None) -> Path:
   343	        target = path or self._curve_path(curve.sensor_id, curve.curve_id)
   344	        target.parent.mkdir(parents=True, exist_ok=True)
   345	        from cryodaq.core.atomic_write import atomic_write_text
   346	
   347	        atomic_write_text(target, json.dumps(curve.to_payload(), ensure_ascii=False, indent=2))
   348	        self._curves[curve.sensor_id] = curve
   349	        self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
   350	        self._write_index()
   351	        return target
   352	
   353	    def load_curve(self, path: Path) -> CalibrationCurve:
   354	        curve = CalibrationCurve.from_payload(json.loads(path.read_text(encoding="utf-8")))
   355	        self._curves[curve.sensor_id] = curve
   356	        self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
   357	        return curve
   358	
   359	    def load_curves(self, curves_dir: Path) -> None:
   360	        for path in sorted(curves_dir.glob("**/*.json")):
   361	            self.load_curve(path)
   362	        self._write_index()
   363	
   364	    def import_curve_json(self, path: Path) -> CalibrationCurve:
   365	        return self.load_curve(path)
   366	
   367	    def import_curve_file(
   368	        self,
   369	        path: Path,
   370	        *,
   371	        sensor_id: str | None = None,
   372	        channel_key: str | None = None,
   373	        raw_unit: str = "sensor_unit",
   374	        sensor_kind: str = "generic",
   375	    ) -> CalibrationCurve:
   376	        suffix = path.suffix.lower()
   377	        if suffix == ".json":
   378	            curve = self.import_curve_json(path)
   379	        elif suffix == ".340":
   380	            curve = self._import_curve_text(
   381	                path,
   382	                sensor_id=sensor_id,
   383	                channel_key=channel_key,
   384	                raw_unit=raw_unit,
   385	                sensor_kind=sensor_kind,
   386	                import_format="340",
   387	            )
   388	        else:
   389	            raise ValueError(f"Unsupported calibration import format: {path.suffix}")
   390	        if channel_key:
   391	            self.assign_curve(
   392	                sensor_id=curve.sensor_id,
   393	                curve_id=curve.curve_id,
   394	                channel_key=channel_key,
   395	                runtime_apply_ready=False,
   396	            )
   397	        self._write_index()
   398	        return curve
   399	
   400	    def export_curve_json(self, sensor_id: str, path: Path | None = None) -> Path:
   401	        curve = self._require_curve(sensor_id)
   402	        return self.save_curve(curve, path)
   403	
   404	    def export_curve_table(
   405	        self,
   406	        sensor_id: str,
   407	        *,
   408	        path: Path | None = None,
   409	        points: int = 200,
   410	    ) -> Path:
   411	        curve = self._require_curve(sensor_id)
   412	        target = path or self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
   413	        target.parent.mkdir(parents=True, exist_ok=True)
   414	        raw_min = curve.zones[0].raw_min
   415	        raw_max = curve.zones[-1].raw_max
   416	        raw_grid = np.linspace(raw_min, raw_max, max(points, 2))
   417	        with target.open("w", encoding="utf-8", newline="") as handle:
   418	            writer = csv.writer(handle)
   419	            writer.writerow([f"raw_{curve.raw_unit}", "temperature_K"])
   420	            for raw_value in raw_grid:
   421	                writer.writerow([float(raw_value), curve.evaluate(float(raw_value))])
   422	        return target
   423	
   424	    def export_curve_cof(
   425	        self,
   426	        sensor_id: str,
   427	        *,
   428	        path: Path | None = None,
   429	    ) -> Path:
   430	        """Export calibration curve as .cof (Chebyshev coefficients) format.
   431	
   432	        Unlike .340 which exports sampled breakpoints, .cof preserves the
   433	        raw fit coefficients per zone. Portable: can be re-evaluated by
   434	        any code with numpy.polynomial.chebyshev, no CryoDAQ schema
   435	        dependency.
   436	        """
   437	        curve = self._require_curve(sensor_id)
   438	        target = path or (self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof")
   439	        target.parent.mkdir(parents=True, exist_ok=True)
   440	        self._write_cof_export(target, curve)
   441	        self._write_index()
   442	        return target
   443	
   444	    def export_curve_340(
   445	        self,
   446	        sensor_id: str,
   447	        *,
   448	        path: Path | None = None,
   449	        points: int = 200,
   450	    ) -> Path:
   451	        curve = self._require_curve(sensor_id)
   452	        if self._exports_dir is None:
   453	            raise RuntimeError("CalibrationStore base_dir is required for export.")
   454	        target = path or self._curve_340_path(curve.sensor_id, curve.curve_id)
   455	        target.parent.mkdir(parents=True, exist_ok=True)
   456	        rows = self._export_rows(curve, points=max(points, 2))
   457	        self._write_curve_text_export(target, curve, rows, format_name="340")
   458	        self._write_index()
   459	        return target
   460	
   461	    def get_curve_info(
   462	        self, sensor_id: str | None = None, curve_id: str | None = None
   463	    ) -> dict[str, Any]:
   464	        curve = self._resolve_curve(sensor_id=sensor_id, curve_id=curve_id)
   465	        return {
   466	            "sensor_id": curve.sensor_id,
   467	            "curve_id": curve.curve_id,
   468	            "fit_timestamp": curve.fit_timestamp.isoformat(),
   469	            "raw_unit": curve.raw_unit,
   470	            "sensor_kind": curve.sensor_kind,
   471	            "source_session_ids": list(curve.source_session_ids),
   472	            "zones": [zone.to_payload() for zone in curve.zones],
   473	            "metrics": dict(curve.metrics),
   474	            "metadata": dict(curve.metadata),
   475	            "artifacts": self.get_curve_artifacts(curve.sensor_id),
   476	            "assignment": dict(self._assignments.get(curve.sensor_id) or {}),
   477	        }
   478	
   479	    def get_curve_artifacts(self, sensor_id: str) -> dict[str, str]:
   480	        curve = self._require_curve(sensor_id)
   481	        return {
   482	            "curve_path": str(self._curve_path(curve.sensor_id, curve.curve_id)),
   483	            "table_path": str(
   484	                self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
   485	            ),
   486	            "curve_cof_path": str(
   487	                self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof"
   488	            ),
   489	            "curve_340_path": str(
   490	                self._curve_340_path(curve.sensor_id, curve.curve_id) if self._exports_dir else ""
   491	            ),
   492	            "index_path": str(self._index_path) if self._index_path else "",
   493	        }
   494	
   495	    def list_curves(self, *, sensor_id: str | None = None) -> list[dict[str, Any]]:
   496	        curves = list(self._curves.values())
   497	        if sensor_id:
   498	            curves = [curve for curve in curves if curve.sensor_id == sensor_id]
   499	        curves.sort(key=lambda item: item.fit_timestamp, reverse=True)
   500	        return [self.get_curve_info(curve_id=curve.curve_id) for curve in curves]
   501	
   502	    def list_assignments(self) -> list[dict[str, Any]]:
   503	        assignments = [dict(item) for item in self._assignments.values()]
   504	        assignments.sort(key=lambda item: str(item.get("sensor_id", "")))
   505	        return assignments
   506	
   507	    def get_runtime_settings(self) -> dict[str, Any]:
   508	        assignments = []
   509	        for item in self.list_assignments():
   510	            channel_key = str(item.get("channel_key", "")).strip()
   511	            resolution = self.resolve_runtime_policy(channel_key=channel_key) if channel_key else {}
   512	            assignments.append(
   513	                {
   514	                    **item,
   515	                    "resolution": resolution,
   516	                }
   517	            )
   518	        return {
   519	            "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
   520	            "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
   521	            "assignments": assignments,
   522	        }
   523	
   524	    def set_runtime_global_mode(self, mode: str) -> dict[str, Any]:
   525	        normalized = str(mode).strip().lower()
   526	        if normalized not in {"off", "on"}:
   527	            raise ValueError("Runtime calibration global_mode must be 'off' or 'on'.")
   528	        self._runtime_settings["global_mode"] = normalized
   529	        self._runtime_settings["updated_at"] = _utcnow().isoformat()
   530	        self._write_index()
   531	        return self.get_runtime_settings()
   532	
   533	    def set_runtime_channel_policy(
   534	        self,
   535	        *,
   536	        channel_key: str,
   537	        policy: str,
   538	        sensor_id: str | None = None,
   539	        curve_id: str | None = None,
   540	        runtime_apply_ready: bool | None = None,
   541	    ) -> dict[str, Any]:
   542	        normalized_channel_key = str(channel_key).strip()
   543	        if not normalized_channel_key:
   544	            raise ValueError("channel_key is required.")
   545	        normalized_policy = str(policy).strip().lower()
   546	        if normalized_policy not in {"inherit", "off", "on"}:
   547	            raise ValueError("Channel runtime policy must be 'inherit', 'off', or 'on'.")
   548	        curve = self._resolve_curve(
   549	            sensor_id=str(sensor_id or "").strip() or None,
   550	            curve_id=str(curve_id or "").strip() or None,
   551	        )
   552	        assignment = self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
   553	        assignment["channel_key"] = normalized_channel_key
   554	        assignment["reading_mode_policy"] = normalized_policy
   555	        if runtime_apply_ready is not None:
   556	            assignment["runtime_apply_ready"] = bool(runtime_apply_ready)
   557	        assignment["updated_at"] = _utcnow().isoformat()
   558	        self._write_index()
   559	        return {
   560	            "assignment": dict(assignment),
   561	            "resolution": self.resolve_runtime_policy(channel_key=normalized_channel_key),
   562	        }
   563	
   564	    def resolve_runtime_policy(
   565	        self,
   566	        *,
   567	        channel_key: str,
   568	    ) -> dict[str, Any]:
   569	        normalized_channel_key = str(channel_key).strip()
   570	        if not normalized_channel_key:
   571	            raise ValueError("channel_key is required.")
   572	        global_mode = str(self._runtime_settings.get("global_mode", "off") or "off")
   573	        assignment = next(
   574	            (
   575	                dict(item)
   576	                for item in self._assignments.values()
   577	                if str(item.get("channel_key", "")).strip() == normalized_channel_key
   578	            ),
   579	            None,
   580	        )
   581	        if global_mode == "off":
   582	            return {
   583	                "global_mode": global_mode,
   584	                "channel_key": normalized_channel_key,
   585	                "effective_mode": "off",
   586	                "reading_mode": "krdg",
   587	                "raw_source": "KRDG",
   588	                "reason": "global_off",
   589	                "assignment": assignment,
   590	            }
   591	        if assignment is None:
   592	            return {
   593	                "global_mode": global_mode,
   594	                "channel_key": normalized_channel_key,
   595	                "effective_mode": "off",
   596	                "reading_mode": "krdg",
   597	                "raw_source": "KRDG",
   598	                "reason": "missing_assignment",
   599	                "assignment": None,
   600	            }
   601	        policy = str(assignment.get("reading_mode_policy", "inherit") or "inherit").lower()
   602	        if policy == "off":
   603	            return {
   604	                "global_mode": global_mode,
   605	                "channel_key": normalized_channel_key,
   606	                "effective_mode": "off",
   607	                "reading_mode": "krdg",
   608	                "raw_source": "KRDG",
   609	                "reason": "channel_off",
   610	                "assignment": assignment,
   611	            }
   612	        if not bool(assignment.get("runtime_apply_ready", False)):
   613	            return {
   614	                "global_mode": global_mode,
   615	                "channel_key": normalized_channel_key,
   616	                "effective_mode": "off",
   617	                "reading_mode": "krdg",
   618	                "raw_source": "KRDG",
   619	                "reason": "not_runtime_ready",
   620	                "assignment": assignment,
   621	            }
   622	        sensor_id = str(assignment.get("sensor_id", "")).strip()
   623	        if not sensor_id or sensor_id not in self._curves:
   624	            return {
   625	                "global_mode": global_mode,
   626	                "channel_key": normalized_channel_key,
   627	                "effective_mode": "off",
   628	                "reading_mode": "krdg",
   629	                "raw_source": "KRDG",
   630	                "reason": "missing_curve",
   631	                "assignment": assignment,
   632	            }
   633	        curve = self._curves[sensor_id]
   634	        return {
   635	            "global_mode": global_mode,
   636	            "channel_key": normalized_channel_key,
   637	            "effective_mode": "on",
   638	            "reading_mode": "curve",
   639	            "raw_source": "SRDG",
   640	            "reason": "curve_applied",
   641	            "assignment": assignment,
   642	            "curve": self.get_curve_info(curve_id=curve.curve_id),
   643	        }
   644	
   645	    def assign_curve(
   646	        self,
   647	        *,
   648	        sensor_id: str,
   649	        curve_id: str | None = None,
   650	        channel_key: str | None = None,
   651	        runtime_apply_ready: bool = False,
   652	        reading_mode_policy: str = "inherit",
   653	    ) -> dict[str, Any]:
   654	        curve = self._resolve_curve(sensor_id=sensor_id, curve_id=curve_id)
   655	        normalized_policy = str(reading_mode_policy).strip().lower() or "inherit"
   656	        if normalized_policy not in {"inherit", "off", "on"}:
   657	            raise ValueError("reading_mode_policy must be 'inherit', 'off', or 'on'.")
   658	        assignment = {
   659	            "sensor_id": curve.sensor_id,
   660	            "curve_id": curve.curve_id,
   661	            "channel_key": str(channel_key).strip() if channel_key is not None else curve.sensor_id,
   662	            "updated_at": _utcnow().isoformat(),
   663	            "runtime_apply_ready": bool(runtime_apply_ready),
   664	            "reading_mode_policy": normalized_policy,
   665	        }
   666	        self._assignments[curve.sensor_id] = assignment
   667	        self._write_index()
   668	        return dict(assignment)
   669	
   670	    def lookup_curve(
   671	        self,
   672	        *,
   673	        sensor_id: str | None = None,
   674	        channel_key: str | None = None,
   675	    ) -> dict[str, Any]:
   676	        assignment: dict[str, Any] | None = None
   677	        if sensor_id:
   678	            assignment = dict(self._assignments.get(sensor_id) or {})
   679	        elif channel_key:
   680	            assignment = next(
   681	                (
   682	                    dict(item)
   683	                    for item in self._assignments.values()
   684	                    if str(item.get("channel_key", "")).strip() == channel_key
   685	                ),
   686	                None,
   687	            )
   688	        if assignment is None:
   689	            if sensor_id and sensor_id in self._curves:
   690	                curve = self._curves[sensor_id]
   691	                assignment = dict(
   692	                    self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
   693	                )
   694	            else:
   695	                raise KeyError("Calibration curve lookup did not match any sensor or channel.")
   696	        curve = self._resolve_curve(
   697	            sensor_id=str(assignment.get("sensor_id", "")),
   698	            curve_id=str(assignment.get("curve_id", "")),
   699	        )
   700	        return {
   701	            "assignment": assignment,
   702	            "curve": self.get_curve_info(curve_id=curve.curve_id),
   703	        }
   704	
   705	    def _require_curve(self, sensor_id: str) -> CalibrationCurve:
   706	        if sensor_id not in self._curves:
   707	            raise KeyError(f"Calibration curve for sensor '{sensor_id}' is not loaded.")
   708	        return self._curves[sensor_id]
   709	
   710	    def _resolve_curve(
   711	        self, *, sensor_id: str | None = None, curve_id: str | None = None
   712	    ) -> CalibrationCurve:
   713	        if sensor_id:
   714	            return self._require_curve(sensor_id)
   715	        if curve_id:
   716	            for curve in self._curves.values():
   717	                if curve.curve_id == curve_id:
   718	                    return curve
   719	        raise KeyError("Calibration curve could not be resolved.")
   720	
   721	    def _curve_directory(self, sensor_id: str, curve_id: str) -> Path:
   722	        if self._curves_dir is None:
   723	            raise RuntimeError("CalibrationStore base_dir is required for artifact export.")
   724	        return self._curves_dir / _safe_path_fragment(sensor_id) / _safe_path_fragment(curve_id)
   725	
   726	    def _curve_path(self, sensor_id: str, curve_id: str) -> Path:
   727	        return self._curve_directory(sensor_id, curve_id) / "curve.json"
   728	
   729	    def _curve_340_path(self, sensor_id: str, curve_id: str) -> Path:
   730	        if self._exports_dir is None:
   731	            raise RuntimeError("CalibrationStore base_dir is required for export.")
   732	        return (
   733	            self._exports_dir
   734	            / _safe_path_fragment(sensor_id)
   735	            / _safe_path_fragment(curve_id)
   736	            / "curve.340"
   737	        )
   738	
   739	    def _load_index(self) -> None:
   740	        if self._index_path is None or not self._index_path.exists():
   741	            return
   742	        payload = yaml.safe_load(self._index_path.read_text(encoding="utf-8")) or {}
   743	        runtime = payload.get("runtime", {})
   744	        if isinstance(runtime, dict):
   745	            global_mode = str(runtime.get("global_mode", "off") or "off").strip().lower()
   746	            if global_mode in {"off", "on"}:
   747	                self._runtime_settings["global_mode"] = global_mode
   748	            self._runtime_settings["updated_at"] = str(runtime.get("updated_at", "")).strip()
   749	        assignments = payload.get("assignments", [])
   750	        if isinstance(assignments, list):
   751	            for item in assignments:
   752	                if not isinstance(item, dict):
   753	                    continue
   754	                sensor_id = str(item.get("sensor_id", "")).strip()
   755	                if sensor_id:
   756	                    self._assignments[sensor_id] = {
   757	                        "sensor_id": sensor_id,
   758	                        "curve_id": str(item.get("curve_id", "")).strip(),
   759	                        "channel_key": str(item.get("channel_key", sensor_id)).strip() or sensor_id,
   760	                        "updated_at": str(item.get("updated_at", "")).strip(),
   761	                        "runtime_apply_ready": bool(item.get("runtime_apply_ready", False)),
   762	                        "reading_mode_policy": str(
   763	                            item.get("reading_mode_policy", "inherit") or "inherit"
   764	                        )
   765	                        .strip()
   766	                        .lower()
   767	                        or "inherit",
   768	                    }
   769	
   770	    def _write_index(self) -> None:
   771	        if self._index_path is None:
   772	            return
   773	        self._index_path.parent.mkdir(parents=True, exist_ok=True)
   774	        payload = {
   775	            "schema_version": 1,
   776	            "generated_at": _utcnow().isoformat(),
   777	            "runtime": {
   778	                "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
   779	                "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
   780	            },
   781	            "curves": [
   782	                {
   783	                    "sensor_id": curve.sensor_id,
   784	                    "curve_id": curve.curve_id,
   785	                    "fit_timestamp": curve.fit_timestamp.isoformat(),
   786	                    "raw_unit": curve.raw_unit,
   787	                    "sensor_kind": curve.sensor_kind,
   788	                    "curve_path": str(self._curve_path(curve.sensor_id, curve.curve_id)),
   789	                    "table_path": str(
   790	                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
   791	                    ),
   792	                    "curve_cof_path": str(
   793	                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof"
   794	                    ),
   795	                    "curve_340_path": str(
   796	                        self._curve_340_path(curve.sensor_id, curve.curve_id)
   797	                        if self._exports_dir
   798	                        else ""
   799	                    ),
   800	                    "source_session_ids": list(curve.source_session_ids),
   801	                }
   802	                for curve in sorted(
   803	                    self._curves.values(), key=lambda item: item.fit_timestamp, reverse=True
   804	                )
   805	            ],
   806	            "assignments": [dict(item) for item in self.list_assignments()],
   807	        }
   808	        from cryodaq.core.atomic_write import atomic_write_text
   809	
   810	        atomic_write_text(
   811	            self._index_path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
   812	        )
   813	
   814	    def _ensure_assignment(self, *, sensor_id: str, curve_id: str) -> dict[str, Any]:
   815	        existing = self._assignments.get(sensor_id)
   816	        if existing:
   817	            existing["curve_id"] = curve_id
   818	            existing["updated_at"] = _utcnow().isoformat()
   819	            return existing
   820	        assignment = {
   821	            "sensor_id": sensor_id,
   822	            "curve_id": curve_id,
   823	            "channel_key": sensor_id,
   824	            "updated_at": _utcnow().isoformat(),
   825	            "runtime_apply_ready": False,
   826	            "reading_mode_policy": "inherit",
   827	        }
   828	        self._assignments[sensor_id] = assignment
   829	        return assignment
   830	
   831	    def _export_rows(self, curve: CalibrationCurve, *, points: int) -> list[tuple[float, float]]:
   832	        dense_points = max(points * 24, 2000)
   833	        raw_min = curve.zones[0].raw_min
   834	        raw_max = curve.zones[-1].raw_max
   835	        raw_grid = np.linspace(raw_min, raw_max, dense_points, dtype=float)
   836	        temperatures = np.array(
   837	            [curve.evaluate(float(raw_value)) for raw_value in raw_grid], dtype=float
   838	        )
   839	        order = np.argsort(temperatures)
   840	        sorted_temperatures = temperatures[order]
   841	        sorted_raw = raw_grid[order]
   842	        sorted_temperatures, sorted_raw = self._collapse_duplicate_axis(
   843	            sorted_temperatures, sorted_raw
   844	        )
   845	        indices = self._adaptive_breakpoint_indices(sorted_temperatures, sorted_raw, max(points, 2))
   846	        rows = [(float(sorted_temperatures[index]), float(sorted_raw[index])) for index in indices]
   847	        deduped: list[tuple[float, float]] = []
   848	        seen: set[tuple[float, float]] = set()
   849	        for item in rows:
   850	            key = (round(item[0], 9), round(item[1], 9))
   851	            if key in seen:
   852	                continue
   853	            seen.add(key)
   854	            deduped.append(item)
   855	        return deduped[: max(points, 2)]
   856	
   857	    def _write_curve_text_export(
   858	        self,
   859	        path: Path,
   860	        curve: CalibrationCurve,
   861	        rows: list[tuple[float, float]],
   862	        *,
   863	        format_name: str,
   864	    ) -> None:
   865	        with path.open("w", encoding="utf-8", newline="") as handle:
   866	            handle.write(f"# CryoDAQ calibration curve export .{format_name}\n")
   867	            handle.write(f"# sensor_id: {curve.sensor_id}\n")
   868	            handle.write(f"# curve_id: {curve.curve_id}\n")
   869	            handle.write(f"# raw_unit: {curve.raw_unit}\n")
   870	            handle.write("# columns: temperature_K, sensor_raw\n")
   871	            writer = csv.writer(handle)
   872	            for temperature_k, raw_value in rows:
   873	                writer.writerow([f"{temperature_k:.9g}", f"{raw_value:.9g}"])
   874	
   875	    def _write_cof_export(self, path: Path, curve: CalibrationCurve) -> None:
   876	        """Write .cof format: header + per-zone raw Chebyshev coefficients."""
   877	        from cryodaq.core.atomic_write import atomic_write_text
   878	
   879	        lines: list[str] = []
   880	        lines.append("# CryoDAQ calibration curve export .cof")
   881	        lines.append(f"# sensor_id: {curve.sensor_id}")
   882	        lines.append(f"# curve_id: {curve.curve_id}")
   883	        lines.append(f"# raw_unit: {curve.raw_unit}")
   884	        lines.append(f"# fit_timestamp: {curve.fit_timestamp.isoformat()}")
   885	        lines.append(
   886	            "# format: Chebyshev T_n(x), x = 2*(raw - raw_min)/(raw_max - raw_min) - 1"
   887	        )
   888	        lines.append(f"# zone_count: {len(curve.zones)}")
   889	        lines.append("")
   890	        for index, zone in enumerate(curve.zones, start=1):
   891	            lines.append(f"[zone {index}]")
   892	            lines.append(f"raw_min: {zone.raw_min:.12g}")
   893	            lines.append(f"raw_max: {zone.raw_max:.12g}")
   894	            lines.append(f"order: {zone.order}")
   895	            coefficients = ", ".join(f"{value:.12g}" for value in zone.coefficients)
   896	            lines.append(f"coefficients: {coefficients}")
   897	            lines.append(f"# rmse_k: {zone.rmse_k:.6g}")
   898	            lines.append(f"# max_abs_error_k: {zone.max_abs_error_k:.6g}")
   899	            lines.append(f"# point_count: {zone.point_count}")
   900	            lines.append("")
   901	        atomic_write_text(path, "\n".join(lines))
   902	
   903	    def _import_curve_text(
   904	        self,
   905	        path: Path,
   906	        *,
   907	        sensor_id: str | None,
   908	        channel_key: str | None,
   909	        raw_unit: str,
   910	        sensor_kind: str,
   911	        import_format: str,
   912	    ) -> CalibrationCurve:
   913	        rows: list[tuple[float, float]] = []
   914	        for raw_line in path.read_text(encoding="utf-8").splitlines():
   915	            line = raw_line.strip()
   916	            if not line or line.startswith("#"):
   917	                continue
   918	            line = line.replace(",", " ")
   919	            parts = [item for item in line.split() if item]
   920	            if len(parts) < 2:
   921	                continue
   922	            try:
   923	                temperature_k = float(parts[0])
   924	                raw_value = float(parts[1])
   925	            except ValueError:
   926	                continue
   927	            rows.append((temperature_k, raw_value))
   928	        if len(rows) < 4:
   929	            raise ValueError(
   930	                f"Calibration file '{path.name}' does not contain enough numeric pairs."
   931	            )
   932	        resolved_sensor_id = (sensor_id or (channel_key or path.stem)).strip()
   933	        samples = [
   934	            CalibrationSample(
   935	                timestamp=_utcnow(),
   936	                reference_channel="import",
   937	                reference_temperature=temperature_k,
   938	                sensor_channel=channel_key or resolved_sensor_id,
   939	                sensor_raw_value=raw_value,
   940	                metadata={"import_format": import_format, "source_path": str(path)},
   941	            )
   942	            for temperature_k, raw_value in sorted(rows, key=lambda item: item[1])
   943	        ]
   944	        curve = self.fit_curve(
   945	            resolved_sensor_id,
   946	            samples,
   947	            raw_unit=raw_unit,
   948	            sensor_kind=sensor_kind,
   949	            source_session_ids=(),
   950	            max_zones=3,
   951	            min_points_per_zone=4,
   952	            max_order=12,
   953	            target_rmse_k=0.05,
   954	            metadata={
   955	                "import_format": import_format,
   956	                "import_source_path": str(path),
   957	                "channel_key": channel_key or resolved_sensor_id,
   958	            },
   959	        )
   960	        self.save_curve(curve)
   961	        if import_format == "340":
   962	            self.export_curve_340(curve.sensor_id)
   963	        return curve
   964	
   965	    def _preprocess_samples(
   966	        self,
   967	        samples: list[CalibrationSample] | tuple[CalibrationSample, ...],
   968	        *,
   969	        downsample_target: int,
   970	    ) -> tuple[CalibrationSample, ...]:
   971	        rows: list[tuple[float, float, CalibrationSample]] = []
   972	        for sample in samples:
   973	            temperature = float(sample.reference_temperature)
   974	            raw_value = float(sample.sensor_raw_value)
   975	            if not math.isfinite(temperature) or not math.isfinite(raw_value):
   976	                continue
   977	            rows.append((temperature, raw_value, sample))
   978	        if len(rows) < 4:
   979	            raise ValueError("Not enough finite calibration samples for fitting.")
   980	        rows.sort(key=lambda item: (item[0], item[1]))
   981	
   982	        aggregated: list[CalibrationSample] = []
   983	        index = 0
   984	        while index < len(rows):
   985	            temperature = rows[index][0]
   986	            bucket = [rows[index]]
   987	            index += 1
   988	            while index < len(rows) and math.isclose(
   989	                rows[index][0], temperature, rel_tol=0.0, abs_tol=1e-9
   990	            ):
   991	                bucket.append(rows[index])
   992	                index += 1
   993	            template = bucket[-1][2]
   994	            aggregated.append(
   995	                CalibrationSample(
   996	                    timestamp=template.timestamp,
   997	                    reference_channel=template.reference_channel,
   998	                    reference_temperature=float(np.mean([item[0] for item in bucket])),
   999	                    sensor_channel=template.sensor_channel,
  1000	                    sensor_raw_value=float(np.mean([item[1] for item in bucket])),
  1001	                    reference_instrument_id=template.reference_instrument_id,
  1002	                    sensor_instrument_id=template.sensor_instrument_id,
  1003	                    experiment_id=template.experiment_id,
  1004	                    metadata=dict(template.metadata),
  1005	                )
  1006	            )
  1007	        if len(aggregated) <= downsample_target:
  1008	            return tuple(aggregated)
  1009	        return tuple(
  1010	            self._downsample_uniform_temperature(aggregated, downsample_target=downsample_target)
  1011	        )
  1012	
  1013	    def _downsample_uniform_temperature(
  1014	        self,
  1015	        samples: list[CalibrationSample] | tuple[CalibrationSample, ...],
  1016	        *,
  1017	        downsample_target: int,
  1018	    ) -> list[CalibrationSample]:
  1019	        ordered = sorted(samples, key=lambda item: item.reference_temperature)
  1020	        temperatures = np.array([item.reference_temperature for item in ordered], dtype=float)
  1021	        if len(ordered) <= downsample_target or np.ptp(temperatures) <= 0:
  1022	            return list(ordered)
  1023	        edges = np.linspace(float(temperatures[0]), float(temperatures[-1]), downsample_target + 1)
  1024	        downsampled: list[CalibrationSample] = []
  1025	        start = 0
  1026	        for bin_index in range(downsample_target):
  1027	            lower = edges[bin_index]
  1028	            upper = edges[bin_index + 1]
  1029	            bucket: list[CalibrationSample] = []
  1030	            while start < len(ordered):
  1031	                current = ordered[start]
  1032	                value = current.reference_temperature
  1033	                if value < lower and bin_index > 0:
  1034	                    start += 1
  1035	                    continue
  1036	                if (value < upper) or (bin_index == downsample_target - 1 and value <= upper):
  1037	                    bucket.append(current)
  1038	                    start += 1
  1039	                    continue
  1040	                break
  1041	            if not bucket:
  1042	                nearest_index = int(np.searchsorted(temperatures, (lower + upper) / 2.0))
  1043	                nearest_index = max(0, min(nearest_index, len(ordered) - 1))
  1044	                bucket = [ordered[nearest_index]]
  1045	            template = bucket[len(bucket) // 2]
  1046	            downsampled.append(
  1047	                CalibrationSample(
  1048	                    timestamp=template.timestamp,
  1049	                    reference_channel=template.reference_channel,
  1050	                    reference_temperature=float(
  1051	                        np.mean([item.reference_temperature for item in bucket])
  1052	                    ),
  1053	                    sensor_channel=template.sensor_channel,
  1054	                    sensor_raw_value=float(np.mean([item.sensor_raw_value for item in bucket])),
  1055	                    reference_instrument_id=template.reference_instrument_id,
  1056	                    sensor_instrument_id=template.sensor_instrument_id,
  1057	                    experiment_id=template.experiment_id,
  1058	                    metadata=dict(template.metadata),
  1059	                )
  1060	            )
  1061	        downsampled.sort(key=lambda item: item.reference_temperature)
  1062	        return downsampled
  1063	
  1064	    def _detect_zone_slices(
  1065	        self,
  1066	        temperatures: np.ndarray,
  1067	        raw_values: np.ndarray,
  1068	        *,
  1069	        max_zones: int,
  1070	        min_points_per_zone: int,
  1071	        max_order: int,
  1072	    ) -> list[slice]:
  1073	        if len(raw_values) < (min_points_per_zone * 2) or max_zones <= 1:
  1074	            return [slice(0, len(raw_values))]
  1075	        dvdt = np.gradient(raw_values, temperatures)
  1076	        dvdt = self._smooth_series(dvdt)
  1077	        magnitude = np.log10(np.maximum(np.abs(dvdt), 1e-12))
  1078	        change_score = np.abs(np.gradient(magnitude, temperatures))
  1079	        curvature = np.abs(np.gradient(dvdt, temperatures))
  1080	        combined_score = change_score + (0.25 * curvature / max(float(np.max(curvature)), 1e-12))
  1081	        candidate_order = np.argsort(combined_score)[::-1]
  1082	        boundaries: list[int] = []
  1083	        for index in candidate_order:
  1084	            if index < min_points_per_zone or index > len(raw_values) - min_points_per_zone:
  1085	                continue
  1086	            if any(abs(index - boundary) < min_points_per_zone for boundary in boundaries):
  1087	                continue
  1088	            refined = self._refine_boundary_index(
  1089	                temperatures,
  1090	                raw_values,
  1091	                candidate_index=int(index),
  1092	                min_points_per_zone=min_points_per_zone,
  1093	                max_order=max_order,
  1094	            )
  1095	            if any(abs(refined - boundary) < min_points_per_zone for boundary in boundaries):
  1096	                continue
  1097	            boundaries.append(refined)
  1098	            if len(boundaries) >= max_zones - 1:
  1099	                break
  1100	        cuts = sorted(boundaries)
  1101	        if not cuts:
  1102	            return [slice(0, len(raw_values))]
  1103	        slices: list[slice] = []
  1104	        start = 0
  1105	        for stop in cuts:
  1106	            if stop - start < min_points_per_zone:
  1107	                continue
  1108	            slices.append(slice(start, stop))
  1109	            start = stop
  1110	        if len(raw_values) - start < min_points_per_zone and slices:
  1111	            last = slices.pop()
  1112	            slices.append(slice(last.start, len(raw_values)))
  1113	        else:
  1114	            slices.append(slice(start, len(raw_values)))
  1115	        return slices
  1116	
  1117	    def _fit_zone_slices(
  1118	        self,
  1119	        temperatures: np.ndarray,
  1120	        raw_values: np.ndarray,
  1121	        *,
  1122	        zone_slices: list[slice],
  1123	        max_order: int,
  1124	        target_rmse_k: float,
  1125	    ) -> list[CalibrationZone]:
  1126	        zones = [
  1127	            self._fit_zone_cv(
  1128	                raw_values[zone_slice],
  1129	                temperatures[zone_slice],
  1130	                max_order=max_order,
  1131	            )
  1132	            for zone_slice in zone_slices
  1133	        ]
  1134	        zones.sort(key=lambda item: item.raw_min)
  1135	        return zones
  1136	
  1137	    def _fit_zone_cv(
  1138	        self,
  1139	        raw_values: np.ndarray,
  1140	        temperatures: np.ndarray,
  1141	        *,
  1142	        max_order: int,
  1143	    ) -> CalibrationZone:
  1144	        ordered_indices = np.argsort(raw_values)
  1145	        ordered_raw = np.asarray(raw_values[ordered_indices], dtype=float)
  1146	        ordered_temperatures = np.asarray(temperatures[ordered_indices], dtype=float)
  1147	        ordered_raw, ordered_temperatures = self._collapse_duplicate_axis(
  1148	            ordered_raw, ordered_temperatures
  1149	        )
  1150	        if len(ordered_raw) < 2 or np.ptp(ordered_raw) <= 0:
  1151	            raise RuntimeError("Failed to fit calibration zone: degenerate input range.")
  1152	
  1153	        task_candidates = [
  1154	            order
  1155	            for order in self._TASK_CV_ORDER_RANGE
  1156	            if order <= max_order and order < len(ordered_raw)
  1157	        ]
  1158	        if task_candidates:
  1159	            candidate_orders = task_candidates
  1160	        else:
  1161	            fallback_max = min(max_order, max(1, len(ordered_raw) - 1))
  1162	            candidate_orders = list(range(1, fallback_max + 1))
  1163	
  1164	        best_cv_rmse: float | None = None
  1165	        best_zone: CalibrationZone | None = None
  1166	        for order in candidate_orders:
  1167	            try:
  1168	                cv_rmse = self._cross_validated_rmse(ordered_raw, ordered_temperatures, order=order)
  1169	                zone = self._build_zone(ordered_raw, ordered_temperatures, order=order)
  1170	            except RuntimeError:
  1171	                continue
  1172	            score = (cv_rmse, zone.rmse_k, order)
  1173	            if best_cv_rmse is None or score < (best_cv_rmse, best_zone.rmse_k, best_zone.order):  # type: ignore[union-attr]
  1174	                best_cv_rmse = cv_rmse
  1175	                best_zone = zone
  1176	        if best_zone is None:
  1177	            raise RuntimeError("Failed to fit calibration zone.")
  1178	        return best_zone
  1179	
  1180	    def _build_zone(
  1181	        self,
  1182	        raw_values: np.ndarray,
  1183	        temperatures: np.ndarray,
  1184	        *,
  1185	        order: int,
  1186	    ) -> CalibrationZone:
  1187	        domain = [float(np.min(raw_values)), float(np.max(raw_values))]
  1188	        with warnings.catch_warnings():
  1189	            warnings.simplefilter("error", np.exceptions.RankWarning)
  1190	            try:
  1191	                fit = cheb.Chebyshev.fit(raw_values, temperatures, deg=order, domain=domain)
  1192	            except np.exceptions.RankWarning as exc:
  1193	                raise RuntimeError("Calibration zone fit is numerically unstable.") from exc
  1194	        predictions = fit(raw_values)
  1195	        residuals = predictions - temperatures
  1196	        return CalibrationZone(
  1197	            raw_min=float(np.min(raw_values)),
  1198	            raw_max=float(np.max(raw_values)),
  1199	            order=order,
  1200	            coefficients=tuple(float(value) for value in fit.coef),
  1201	            rmse_k=float(math.sqrt(np.mean(np.square(residuals)))),
  1202	            max_abs_error_k=float(np.max(np.abs(residuals))),
  1203	            point_count=int(len(raw_values)),
  1204	        )
  1205	
  1206	    def _cross_validated_rmse(
  1207	        self,
  1208	        raw_values: np.ndarray,
  1209	        temperatures: np.ndarray,
  1210	        *,
  1211	        order: int,
  1212	    ) -> float:
  1213	        sample_count = len(raw_values)
  1214	        if sample_count <= order + 2:
  1215	            zone = self._build_zone(raw_values, temperatures, order=order)
  1216	            return zone.rmse_k
  1217	        folds = min(5, max(2, sample_count // max(order + 1, 4)))
  1218	        indices = np.arange(sample_count)
  1219	        fold_indices = [
  1220	            indices[offset::folds] for offset in range(folds) if len(indices[offset::folds]) > 0
  1221	        ]
  1222	        rmses: list[float] = []
  1223	        for fold in fold_indices:
  1224	            mask = np.ones(sample_count, dtype=bool)
  1225	            mask[fold] = False
  1226	            train_raw = raw_values[mask]
  1227	            train_temperatures = temperatures[mask]
  1228	            if len(train_raw) <= order:
  1229	                continue
  1230	            zone = self._build_zone(train_raw, train_temperatures, order=order)
  1231	            predictions = np.array(
  1232	                [zone.evaluate(float(value)) for value in raw_values[fold]], dtype=float
  1233	            )
  1234	            residuals = predictions - temperatures[fold]
  1235	            rmses.append(float(math.sqrt(np.mean(np.square(residuals)))))
  1236	        if not rmses:
  1237	            zone = self._build_zone(raw_values, temperatures, order=order)
  1238	            return zone.rmse_k
  1239	        return float(np.mean(rmses))
  1240	
  1241	    def _evaluate_zones(self, zones: list[CalibrationZone], raw_value: float) -> float:
  1242	        for zone in zones:
  1243	            if zone.contains(float(raw_value)):
  1244	                return zone.evaluate(float(raw_value))
  1245	        if raw_value < zones[0].raw_min:
  1246	            return zones[0].evaluate(float(raw_value))
  1247	        return zones[-1].evaluate(float(raw_value))
  1248	
  1249	    def _smooth_series(self, values: np.ndarray) -> np.ndarray:
  1250	        if len(values) < 5:
  1251	            return np.asarray(values, dtype=float)
  1252	        window = min(len(values) if len(values) % 2 == 1 else len(values) - 1, 11)
  1253	        if window < 3:
  1254	            return np.asarray(values, dtype=float)
  1255	        kernel = np.ones(window, dtype=float) / float(window)
  1256	        padded = np.pad(values, (window // 2, window // 2), mode="edge")
  1257	        return np.convolve(padded, kernel, mode="valid")
  1258	
  1259	    def _adaptive_breakpoint_indices(
  1260	        self,
  1261	        temperatures: np.ndarray,
  1262	        raw_values: np.ndarray,
  1263	        points: int,
  1264	    ) -> list[int]:
  1265	        if len(temperatures) <= points:
  1266	            return list(range(len(temperatures)))
  1267	        first = np.gradient(raw_values, temperatures)
  1268	        second = np.gradient(first, temperatures)
  1269	        weights = 1.0 + np.abs(second)
  1270	        cumulative = np.cumsum(weights)
  1271	        cumulative /= cumulative[-1]
  1272	        targets = np.linspace(0.0, 1.0, points)
  1273	        indices = np.searchsorted(cumulative, targets, side="left")
  1274	        indices = np.clip(indices, 0, len(temperatures) - 1)
  1275	        indices[0] = 0
  1276	        indices[-1] = len(temperatures) - 1
  1277	        deduped = sorted({int(index) for index in indices})
  1278	        while len(deduped) < points:
  1279	            for candidate in np.linspace(0, len(temperatures) - 1, points, dtype=int):
  1280	                deduped.append(int(candidate))
  1281	                deduped = sorted(set(deduped))
  1282	                if len(deduped) >= points:
  1283	                    break
  1284	        return deduped[:points]
  1285	
  1286	    def _refine_boundary_index(
  1287	        self,
  1288	        temperatures: np.ndarray,
  1289	        raw_values: np.ndarray,
  1290	        *,
  1291	        candidate_index: int,
  1292	        min_points_per_zone: int,
  1293	        max_order: int,
  1294	    ) -> int:
  1295	        search_radius = max(3, min_points_per_zone // 2)
  1296	        start = max(min_points_per_zone, candidate_index - search_radius)
  1297	        stop = min(len(raw_values) - min_points_per_zone, candidate_index + search_radius)
  1298	        best_index = candidate_index
  1299	        best_score: tuple[float, float] | None = None
  1300	        for index in range(start, stop + 1):
  1301	            try:
  1302	                left_zone = self._fit_zone_cv(
  1303	                    raw_values[:index], temperatures[:index], max_order=max_order
  1304	                )
  1305	                right_zone = self._fit_zone_cv(
  1306	                    raw_values[index:], temperatures[index:], max_order=max_order
  1307	                )
  1308	            except RuntimeError:
  1309	                continue
  1310	            weighted_rmse = math.sqrt(
  1311	                (
  1312	                    (left_zone.rmse_k**2) * left_zone.point_count
  1313	                    + (right_zone.rmse_k**2) * right_zone.point_count
  1314	                )
  1315	                / max(left_zone.point_count + right_zone.point_count, 1)
  1316	            )
  1317	            score = (weighted_rmse, max(left_zone.max_abs_error_k, right_zone.max_abs_error_k))
  1318	            if best_score is None or score < best_score:
  1319	                best_score = score
  1320	                best_index = index
  1321	        return best_index
  1322	
  1323	    def _collapse_duplicate_axis(
  1324	        self,
  1325	        primary: np.ndarray,
  1326	        secondary: np.ndarray,
  1327	    ) -> tuple[np.ndarray, np.ndarray]:
  1328	        if len(primary) < 2:
  1329	            return np.asarray(primary, dtype=float), np.asarray(secondary, dtype=float)
  1330	        rows = sorted(
  1331	            zip(primary.tolist(), secondary.tolist(), strict=False), key=lambda item: item[0]
  1332	        )
  1333	        unique_primary: list[float] = []
  1334	        unique_secondary: list[float] = []
  1335	        bucket_primary = [rows[0][0]]
  1336	        bucket_secondary = [rows[0][1]]
  1337	        for current_primary, current_secondary in rows[1:]:
  1338	            if math.isclose(current_primary, bucket_primary[-1], rel_tol=0.0, abs_tol=1e-12):
  1339	                bucket_primary.append(current_primary)
  1340	                bucket_secondary.append(current_secondary)
  1341	                continue
  1342	            unique_primary.append(float(np.mean(bucket_primary)))
  1343	            unique_secondary.append(float(np.mean(bucket_secondary)))
  1344	            bucket_primary = [current_primary]
  1345	            bucket_secondary = [current_secondary]
  1346	        unique_primary.append(float(np.mean(bucket_primary)))
  1347	        unique_secondary.append(float(np.mean(bucket_secondary)))
  1348	        return np.asarray(unique_primary, dtype=float), np.asarray(unique_secondary, dtype=float)

exec
/opt/homebrew/bin/bash -lc 'nl -ba tests/analytics/test_calibration.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	from __future__ import annotations
     2	
     3	from datetime import UTC, datetime
     4	from pathlib import Path
     5	
     6	import numpy as np
     7	import pytest
     8	
     9	from cryodaq.analytics.calibration import CalibrationSample, CalibrationStore
    10	
    11	
    12	def _sample_series() -> list[CalibrationSample]:
    13	    points: list[CalibrationSample] = []
    14	    for index, temp_k in enumerate([4.0, 6.0, 8.0, 12.0, 20.0, 35.0, 60.0, 90.0, 140.0, 220.0]):
    15	        raw_value = (1500.0 / (temp_k + 18.0)) + (0.002 * temp_k)
    16	        points.append(
    17	            CalibrationSample(
    18	                timestamp=datetime(2026, 3, 16, 12, index, tzinfo=UTC),
    19	                reference_channel="CH1",
    20	                reference_temperature=temp_k,
    21	                sensor_channel="CH2",
    22	                sensor_raw_value=raw_value,
    23	                reference_instrument_id="ls218s",
    24	                sensor_instrument_id="ls218s",
    25	                metadata={"index": index},
    26	            )
    27	        )
    28	    return points
    29	
    30	
    31	def _piecewise_raw(temp_k: float) -> float:
    32	    if temp_k <= 45.0:
    33	        return 1.72 - 0.060 * np.log1p(temp_k) - 0.00035 * temp_k
    34	    if temp_k <= 150.0:
    35	        dt = temp_k - 45.0
    36	        anchor = 1.72 - 0.060 * np.log1p(45.0) - 0.00035 * 45.0
    37	        return anchor - 0.0028 * dt - 0.000010 * dt * dt
    38	    dt = temp_k - 150.0
    39	    anchor = _piecewise_raw(150.0)
    40	    return anchor - 0.00105 * dt - 0.0000035 * dt * dt
    41	
    42	
    43	def _multi_zone_samples(count: int = 900, *, sensor_id: str = "CH2") -> list[CalibrationSample]:
    44	    temperatures = np.linspace(4.0, 290.0, count, dtype=float)
    45	    return [
    46	        CalibrationSample(
    47	            timestamp=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
    48	            reference_channel="REF",
    49	            reference_temperature=float(temp_k),
    50	            sensor_channel=sensor_id,
    51	            sensor_raw_value=float(_piecewise_raw(float(temp_k))),
    52	            reference_instrument_id="etalon",
    53	            sensor_instrument_id="ls218s",
    54	            metadata={"series": "multi-zone"},
    55	        )
    56	        for temp_k in temperatures
    57	    ]
    58	
    59	
    60	def _dense_nonuniform_samples(count: int = 9000) -> list[CalibrationSample]:
    61	    low = np.linspace(4.0, 80.0, int(count * 0.8), dtype=float)
    62	    high = np.linspace(80.0, 300.0, count - len(low), dtype=float)
    63	    temperatures = np.concatenate([low, high])
    64	    return [
    65	        CalibrationSample(
    66	            timestamp=datetime(2026, 3, 16, 14, 0, tzinfo=UTC),
    67	            reference_channel="REF",
    68	            reference_temperature=float(temp_k),
    69	            sensor_channel="CH3",
    70	            sensor_raw_value=float(_piecewise_raw(float(temp_k))),
    71	            metadata={"series": "dense"},
    72	        )
    73	        for temp_k in temperatures
    74	    ]
    75	
    76	
    77	def _data_lines(path: Path) -> list[str]:
    78	    return [
    79	        line.strip()
    80	        for line in path.read_text(encoding="utf-8").splitlines()
    81	        if line.strip() and not line.lstrip().startswith("#")
    82	    ]
    83	
    84	
    85	def test_calibration_store_fit_roundtrip_and_persistence(tmp_path: Path) -> None:
    86	    store = CalibrationStore(tmp_path)
    87	    samples = _sample_series()
    88	
    89	    curve = store.fit_curve(
    90	        "sensor-001",
    91	        samples,
    92	        raw_unit="ohm",
    93	        source_session_ids=["sess-001"],
    94	        max_zones=3,
    95	        min_points_per_zone=4,
    96	        target_rmse_k=0.03,
    97	    )
    98	    curve_path = store.save_curve(curve)
    99	    table_path = store.export_curve_table("sensor-001", points=32)
   100	
   101	    reloaded = CalibrationStore(tmp_path)
   102	    reloaded.load_curves(tmp_path / "curves")
   103	    estimated = reloaded.evaluate("sensor-001", samples[3].sensor_raw_value)
   104	
   105	    assert len(curve.zones) >= 1
   106	    assert curve.metrics["sample_count"] == len(samples)
   107	    assert curve_path.exists()
   108	    assert table_path.exists()
   109	    assert estimated == pytest.approx(samples[3].reference_temperature, abs=0.2)
   110	
   111	
   112	def test_fit_pipeline_uses_task_level_zone_detection_and_cv_order_selection(tmp_path: Path) -> None:
   113	    store = CalibrationStore(tmp_path)
   114	    samples = _multi_zone_samples()
   115	
   116	    curve = store.fit_curve(
   117	        "sensor-fit-task",
   118	        samples,
   119	        raw_unit="V",
   120	        max_zones=3,
   121	        min_points_per_zone=24,
   122	        target_rmse_k=0.05,
   123	    )
   124	
   125	    holdout_temps = np.linspace(6.0, 285.0, 60, dtype=float)
   126	    errors = [
   127	        abs(store.evaluate("sensor-fit-task", float(_piecewise_raw(float(temp_k)))) - float(temp_k))
   128	        for temp_k in holdout_temps
   129	    ]
   130	
   131	    assert curve.metrics["zone_detection"] == "dV/dT"
   132	    assert curve.metrics["order_selection"] == "cross_validation"
   133	    assert curve.metrics["rmse_k"] < 0.05
   134	    assert max(errors) < 0.05
   135	    assert len(curve.zones) >= 2
   136	    assert all(zone.order >= 7 for zone in curve.zones if zone.point_count >= 9)
   137	
   138	
   139	def test_downsampling_is_uniform_by_temperature_to_task_target(tmp_path: Path) -> None:
   140	    store = CalibrationStore(tmp_path)
   141	    samples = _dense_nonuniform_samples()
   142	
   143	    preprocessed = store._preprocess_samples(
   144	        samples, downsample_target=store._TASK_DOWNSAMPLE_TARGET
   145	    )
   146	    temperatures = np.array([sample.reference_temperature for sample in preprocessed], dtype=float)
   147	    histogram, _ = np.histogram(temperatures, bins=10)
   148	
   149	    assert len(preprocessed) == store._TASK_DOWNSAMPLE_TARGET
   150	    assert histogram.max() - histogram.min() <= 2
   151	
   152	
   153	def test_t_from_v_matches_evaluate_and_voltage_to_temp(tmp_path: Path) -> None:
   154	    store = CalibrationStore(tmp_path)
   155	    curve = store.fit_curve(
   156	        "sensor-api", _multi_zone_samples(), raw_unit="V", max_zones=3, min_points_per_zone=24
   157	    )
   158	    store.save_curve(curve)
   159	
   160	    raw_value = _piecewise_raw(123.0)
   161	
   162	    assert store.evaluate("sensor-api", raw_value) == pytest.approx(123.0, abs=0.05)
   163	    assert store.T_from_V("sensor-api", raw_value) == pytest.approx(
   164	        store.evaluate("sensor-api", raw_value), abs=1e-9
   165	    )
   166	    assert store.voltage_to_temp("sensor-api", raw_value) == pytest.approx(
   167	        store.evaluate("sensor-api", raw_value), abs=1e-9
   168	    )
   169	
   170	
   171	def test_calibration_store_import_export_json(tmp_path: Path) -> None:
   172	    store = CalibrationStore(tmp_path)
   173	    curve = store.fit_curve(
   174	        "sensor-002",
   175	        _sample_series(),
   176	        raw_unit="sensor_unit",
   177	        max_zones=2,
   178	        min_points_per_zone=4,
   179	    )
   180	    exported = store.export_curve_json("sensor-002")
   181	
   182	    imported_store = CalibrationStore(tmp_path / "imported")
   183	    imported_curve = imported_store.import_curve_json(exported)
   184	
   185	    assert imported_curve.sensor_id == "sensor-002"
   186	    assert imported_store.get_curve_info("sensor-002")["curve_id"] == curve.curve_id
   187	
   188	
   189	def test_export_340_uses_200_breakpoints_and_roundtrips_via_import(tmp_path: Path) -> None:
   190	    source_store = CalibrationStore(tmp_path / "source")
   191	    curve = source_store.fit_curve(
   192	        "sensor-003",
   193	        _multi_zone_samples(1200),
   194	        raw_unit="V",
   195	        max_zones=3,
   196	        min_points_per_zone=30,
   197	    )
   198	    source_store.save_curve(curve)
   199	
   200	    path_340 = source_store.export_curve_340("sensor-003", points=200)
   201	    imported_store = CalibrationStore(tmp_path / "imported")
   202	    imported_curve = imported_store.import_curve_file(
   203	        path_340, sensor_id="sensor-003B", channel_key="LS218:CH3", raw_unit="V"
   204	    )
   205	
   206	    exported_lines = _data_lines(path_340)
   207	    roundtrip_raw = _piecewise_raw(88.0)
   208	
   209	    assert len(exported_lines) == 200
   210	    assert imported_curve.sensor_id == "sensor-003B"
   211	    assert imported_store.T_from_V("sensor-003B", roundtrip_raw) == pytest.approx(88.0, abs=0.1)
   212	
   213	
   214	def test_calibration_store_imports_340_and_supports_lookup(tmp_path: Path) -> None:
   215	    source_store = CalibrationStore(tmp_path / "source")
   216	    curve = source_store.fit_curve(
   217	        "sensor-004",
   218	        _sample_series(),
   219	        raw_unit="V",
   220	        max_zones=2,
   221	        min_points_per_zone=4,
   222	    )
   223	    source_store.save_curve(curve)
   224	    exported_340 = source_store.export_curve_340("sensor-004", points=48)
   225	
   226	    imported_store = CalibrationStore(tmp_path / "imported")
   227	    imported_curve_340 = imported_store.import_curve_file(
   228	        exported_340, sensor_id="sensor-004B", channel_key="LS218:CH3"
   229	    )
   230	
   231	    lookup = imported_store.lookup_curve(channel_key="LS218:CH3")
   232	
   233	    assert imported_curve_340.sensor_id == "sensor-004B"
   234	    assert lookup["assignment"]["channel_key"] == "LS218:CH3"
   235	    assert lookup["curve"]["sensor_id"] == "sensor-004B"
   236	
   237	
   238	def test_calibration_store_backward_compatible_load_rebuilds_index(tmp_path: Path) -> None:
   239	    legacy_store = CalibrationStore(tmp_path / "legacy")
   240	    curve = legacy_store.fit_curve(
   241	        "sensor-005",
   242	        _sample_series(),
   243	        raw_unit="sensor_unit",
   244	        max_zones=2,
   245	        min_points_per_zone=4,
   246	    )
   247	    curve_path = legacy_store.save_curve(curve)
   248	    index_path = tmp_path / "legacy" / "index.yaml"
   249	    if index_path.exists():
   250	        index_path.unlink()
   251	
   252	    reloaded = CalibrationStore(tmp_path / "legacy")
   253	    reloaded.load_curves(tmp_path / "legacy" / "curves")
   254	
   255	    assert reloaded.get_curve_info("sensor-005")["curve_id"] == curve.curve_id
   256	    assert index_path.exists()
   257	    assert curve_path.exists()
   258	
   259	
   260	# ---------------------------------------------------------------------------
   261	# Phase 2d B-1: atomic write for calibration index
   262	# ---------------------------------------------------------------------------
   263	
   264	
   265	def test_calibration_index_uses_atomic_write():
   266	    """B-1.2: calibration.py index/curve writes must use atomic_write_text."""
   267	    source = Path("src/cryodaq/analytics/calibration.py").read_text(encoding="utf-8")
   268	    import re
   269	
   270	    raw_state_writes = re.findall(r"_index_path\.write_text|target\.write_text\(json", source)
   271	    assert len(raw_state_writes) == 0, (
   272	        f"Found {len(raw_state_writes)} raw write_text calls for state files — "
   273	        f"should all route through atomic_write_text"
   274	    )
   275	    assert "atomic_write_text" in source
   276	
   277	
   278	# ---------------------------------------------------------------------------
   279	# Phase D: .cof export + .330 removal
   280	# ---------------------------------------------------------------------------
   281	
   282	
   283	def test_export_curve_cof_writes_file_with_expected_structure(tmp_path: Path) -> None:
   284	    store = CalibrationStore(tmp_path)
   285	    curve = store.fit_curve(
   286	        "sensor-cof-01", _multi_zone_samples(300), raw_unit="V", max_zones=2, min_points_per_zone=24
   287	    )
   288	    store.save_curve(curve)
   289	
   290	    cof_path = store.export_curve_cof("sensor-cof-01")
   291	
   292	    assert cof_path.exists()
   293	    assert cof_path.suffix == ".cof"
   294	    text = cof_path.read_text(encoding="utf-8")
   295	    assert "# CryoDAQ calibration curve export .cof" in text
   296	    assert f"# sensor_id: {curve.sensor_id}" in text
   297	    assert f"# curve_id: {curve.curve_id}" in text
   298	    assert "[zone 1]" in text
   299	    assert "raw_min:" in text
   300	    assert "raw_max:" in text
   301	    assert "order:" in text
   302	    assert "coefficients:" in text
   303	
   304	
   305	def test_export_curve_cof_preserves_chebyshev_coefficients_round_trip(tmp_path: Path) -> None:
   306	    store = CalibrationStore(tmp_path)
   307	    curve = store.fit_curve(
   308	        "sensor-cof-02", _multi_zone_samples(600), raw_unit="V", max_zones=3, min_points_per_zone=24
   309	    )
   310	    store.save_curve(curve)
   311	
   312	    cof_path = store.export_curve_cof("sensor-cof-02")
   313	    text = cof_path.read_text(encoding="utf-8")
   314	
   315	    parsed_coefficients: list[tuple[float, ...]] = []
   316	    for line in text.splitlines():
   317	        line = line.strip()
   318	        if line.startswith("coefficients:"):
   319	            values = tuple(float(v) for v in line.split(":", 1)[1].split(","))
   320	            parsed_coefficients.append(values)
   321	
   322	    assert len(parsed_coefficients) == len(curve.zones)
   323	    for parsed, zone in zip(parsed_coefficients, curve.zones, strict=True):
   324	        assert len(parsed) == len(zone.coefficients)
   325	        for a, b in zip(parsed, zone.coefficients, strict=True):
   326	            assert a == pytest.approx(b, rel=1e-10)
   327	
   328	
   329	def test_export_curve_cof_includes_zone_count_header(tmp_path: Path) -> None:
   330	    store = CalibrationStore(tmp_path)
   331	    curve = store.fit_curve(
   332	        "sensor-cof-03", _multi_zone_samples(300), raw_unit="V", max_zones=3, min_points_per_zone=24
   333	    )
   334	    store.save_curve(curve)
   335	
   336	    cof_path = store.export_curve_cof("sensor-cof-03")
   337	    text = cof_path.read_text(encoding="utf-8")
   338	
   339	    assert f"# zone_count: {len(curve.zones)}" in text
   340	
   341	
   342	def test_export_curve_cof_metadata_comments_match_curve(tmp_path: Path) -> None:
   343	    store = CalibrationStore(tmp_path)
   344	    curve = store.fit_curve(
   345	        "sensor-cof-04", _sample_series(), raw_unit="ohm", max_zones=2, min_points_per_zone=4
   346	    )
   347	    store.save_curve(curve)
   348	
   349	    cof_path = store.export_curve_cof("sensor-cof-04")
   350	    text = cof_path.read_text(encoding="utf-8")
   351	
   352	    assert f"# raw_unit: {curve.raw_unit}" in text
   353	    assert f"# fit_timestamp: {curve.fit_timestamp.isoformat()}" in text
   354	    assert "# rmse_k:" in text
   355	    assert "# max_abs_error_k:" in text
   356	    assert "# point_count:" in text
   357	
   358	
   359	def test_export_curve_330_removed(tmp_path: Path) -> None:
   360	    store = CalibrationStore(tmp_path)
   361	    assert not hasattr(store, "export_curve_330"), (
   362	        "export_curve_330 must be removed — architect decision 2026-04-25"
   363	    )
   364	
   365	
   366	def test_import_curve_file_rejects_330_suffix(tmp_path: Path) -> None:
   367	    fake_330 = tmp_path / "curve.330"
   368	    fake_330.write_text("# header\n4.0 75.0\n6.0 60.0\n10.0 40.0\n20.0 22.0\n", encoding="utf-8")
   369	    store = CalibrationStore(tmp_path)
   370	    with pytest.raises(ValueError, match="Unsupported calibration import format"):
   371	        store.import_curve_file(fake_330)

exec
/opt/homebrew/bin/bash -lc 'git status --short --branch' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
## feat/cof-calibration-export
?? artifacts/consultations/2026-04-28-cof-migration/

codex
The first file output was truncated around the index helpers, so I’m pulling the missing section separately. The test file came through completely; the `.330` rejection test writes four numeric rows before calling the import path.
exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/analytics/calibration.py | sed -n '500,920p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   500	        return [self.get_curve_info(curve_id=curve.curve_id) for curve in curves]
   501	
   502	    def list_assignments(self) -> list[dict[str, Any]]:
   503	        assignments = [dict(item) for item in self._assignments.values()]
   504	        assignments.sort(key=lambda item: str(item.get("sensor_id", "")))
   505	        return assignments
   506	
   507	    def get_runtime_settings(self) -> dict[str, Any]:
   508	        assignments = []
   509	        for item in self.list_assignments():
   510	            channel_key = str(item.get("channel_key", "")).strip()
   511	            resolution = self.resolve_runtime_policy(channel_key=channel_key) if channel_key else {}
   512	            assignments.append(
   513	                {
   514	                    **item,
   515	                    "resolution": resolution,
   516	                }
   517	            )
   518	        return {
   519	            "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
   520	            "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
   521	            "assignments": assignments,
   522	        }
   523	
   524	    def set_runtime_global_mode(self, mode: str) -> dict[str, Any]:
   525	        normalized = str(mode).strip().lower()
   526	        if normalized not in {"off", "on"}:
   527	            raise ValueError("Runtime calibration global_mode must be 'off' or 'on'.")
   528	        self._runtime_settings["global_mode"] = normalized
   529	        self._runtime_settings["updated_at"] = _utcnow().isoformat()
   530	        self._write_index()
   531	        return self.get_runtime_settings()
   532	
   533	    def set_runtime_channel_policy(
   534	        self,
   535	        *,
   536	        channel_key: str,
   537	        policy: str,
   538	        sensor_id: str | None = None,
   539	        curve_id: str | None = None,
   540	        runtime_apply_ready: bool | None = None,
   541	    ) -> dict[str, Any]:
   542	        normalized_channel_key = str(channel_key).strip()
   543	        if not normalized_channel_key:
   544	            raise ValueError("channel_key is required.")
   545	        normalized_policy = str(policy).strip().lower()
   546	        if normalized_policy not in {"inherit", "off", "on"}:
   547	            raise ValueError("Channel runtime policy must be 'inherit', 'off', or 'on'.")
   548	        curve = self._resolve_curve(
   549	            sensor_id=str(sensor_id or "").strip() or None,
   550	            curve_id=str(curve_id or "").strip() or None,
   551	        )
   552	        assignment = self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
   553	        assignment["channel_key"] = normalized_channel_key
   554	        assignment["reading_mode_policy"] = normalized_policy
   555	        if runtime_apply_ready is not None:
   556	            assignment["runtime_apply_ready"] = bool(runtime_apply_ready)
   557	        assignment["updated_at"] = _utcnow().isoformat()
   558	        self._write_index()
   559	        return {
   560	            "assignment": dict(assignment),
   561	            "resolution": self.resolve_runtime_policy(channel_key=normalized_channel_key),
   562	        }
   563	
   564	    def resolve_runtime_policy(
   565	        self,
   566	        *,
   567	        channel_key: str,
   568	    ) -> dict[str, Any]:
   569	        normalized_channel_key = str(channel_key).strip()
   570	        if not normalized_channel_key:
   571	            raise ValueError("channel_key is required.")
   572	        global_mode = str(self._runtime_settings.get("global_mode", "off") or "off")
   573	        assignment = next(
   574	            (
   575	                dict(item)
   576	                for item in self._assignments.values()
   577	                if str(item.get("channel_key", "")).strip() == normalized_channel_key
   578	            ),
   579	            None,
   580	        )
   581	        if global_mode == "off":
   582	            return {
   583	                "global_mode": global_mode,
   584	                "channel_key": normalized_channel_key,
   585	                "effective_mode": "off",
   586	                "reading_mode": "krdg",
   587	                "raw_source": "KRDG",
   588	                "reason": "global_off",
   589	                "assignment": assignment,
   590	            }
   591	        if assignment is None:
   592	            return {
   593	                "global_mode": global_mode,
   594	                "channel_key": normalized_channel_key,
   595	                "effective_mode": "off",
   596	                "reading_mode": "krdg",
   597	                "raw_source": "KRDG",
   598	                "reason": "missing_assignment",
   599	                "assignment": None,
   600	            }
   601	        policy = str(assignment.get("reading_mode_policy", "inherit") or "inherit").lower()
   602	        if policy == "off":
   603	            return {
   604	                "global_mode": global_mode,
   605	                "channel_key": normalized_channel_key,
   606	                "effective_mode": "off",
   607	                "reading_mode": "krdg",
   608	                "raw_source": "KRDG",
   609	                "reason": "channel_off",
   610	                "assignment": assignment,
   611	            }
   612	        if not bool(assignment.get("runtime_apply_ready", False)):
   613	            return {
   614	                "global_mode": global_mode,
   615	                "channel_key": normalized_channel_key,
   616	                "effective_mode": "off",
   617	                "reading_mode": "krdg",
   618	                "raw_source": "KRDG",
   619	                "reason": "not_runtime_ready",
   620	                "assignment": assignment,
   621	            }
   622	        sensor_id = str(assignment.get("sensor_id", "")).strip()
   623	        if not sensor_id or sensor_id not in self._curves:
   624	            return {
   625	                "global_mode": global_mode,
   626	                "channel_key": normalized_channel_key,
   627	                "effective_mode": "off",
   628	                "reading_mode": "krdg",
   629	                "raw_source": "KRDG",
   630	                "reason": "missing_curve",
   631	                "assignment": assignment,
   632	            }
   633	        curve = self._curves[sensor_id]
   634	        return {
   635	            "global_mode": global_mode,
   636	            "channel_key": normalized_channel_key,
   637	            "effective_mode": "on",
   638	            "reading_mode": "curve",
   639	            "raw_source": "SRDG",
   640	            "reason": "curve_applied",
   641	            "assignment": assignment,
   642	            "curve": self.get_curve_info(curve_id=curve.curve_id),
   643	        }
   644	
   645	    def assign_curve(
   646	        self,
   647	        *,
   648	        sensor_id: str,
   649	        curve_id: str | None = None,
   650	        channel_key: str | None = None,
   651	        runtime_apply_ready: bool = False,
   652	        reading_mode_policy: str = "inherit",
   653	    ) -> dict[str, Any]:
   654	        curve = self._resolve_curve(sensor_id=sensor_id, curve_id=curve_id)
   655	        normalized_policy = str(reading_mode_policy).strip().lower() or "inherit"
   656	        if normalized_policy not in {"inherit", "off", "on"}:
   657	            raise ValueError("reading_mode_policy must be 'inherit', 'off', or 'on'.")
   658	        assignment = {
   659	            "sensor_id": curve.sensor_id,
   660	            "curve_id": curve.curve_id,
   661	            "channel_key": str(channel_key).strip() if channel_key is not None else curve.sensor_id,
   662	            "updated_at": _utcnow().isoformat(),
   663	            "runtime_apply_ready": bool(runtime_apply_ready),
   664	            "reading_mode_policy": normalized_policy,
   665	        }
   666	        self._assignments[curve.sensor_id] = assignment
   667	        self._write_index()
   668	        return dict(assignment)
   669	
   670	    def lookup_curve(
   671	        self,
   672	        *,
   673	        sensor_id: str | None = None,
   674	        channel_key: str | None = None,
   675	    ) -> dict[str, Any]:
   676	        assignment: dict[str, Any] | None = None
   677	        if sensor_id:
   678	            assignment = dict(self._assignments.get(sensor_id) or {})
   679	        elif channel_key:
   680	            assignment = next(
   681	                (
   682	                    dict(item)
   683	                    for item in self._assignments.values()
   684	                    if str(item.get("channel_key", "")).strip() == channel_key
   685	                ),
   686	                None,
   687	            )
   688	        if assignment is None:
   689	            if sensor_id and sensor_id in self._curves:
   690	                curve = self._curves[sensor_id]
   691	                assignment = dict(
   692	                    self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
   693	                )
   694	            else:
   695	                raise KeyError("Calibration curve lookup did not match any sensor or channel.")
   696	        curve = self._resolve_curve(
   697	            sensor_id=str(assignment.get("sensor_id", "")),
   698	            curve_id=str(assignment.get("curve_id", "")),
   699	        )
   700	        return {
   701	            "assignment": assignment,
   702	            "curve": self.get_curve_info(curve_id=curve.curve_id),
   703	        }
   704	
   705	    def _require_curve(self, sensor_id: str) -> CalibrationCurve:
   706	        if sensor_id not in self._curves:
   707	            raise KeyError(f"Calibration curve for sensor '{sensor_id}' is not loaded.")
   708	        return self._curves[sensor_id]
   709	
   710	    def _resolve_curve(
   711	        self, *, sensor_id: str | None = None, curve_id: str | None = None
   712	    ) -> CalibrationCurve:
   713	        if sensor_id:
   714	            return self._require_curve(sensor_id)
   715	        if curve_id:
   716	            for curve in self._curves.values():
   717	                if curve.curve_id == curve_id:
   718	                    return curve
   719	        raise KeyError("Calibration curve could not be resolved.")
   720	
   721	    def _curve_directory(self, sensor_id: str, curve_id: str) -> Path:
   722	        if self._curves_dir is None:
   723	            raise RuntimeError("CalibrationStore base_dir is required for artifact export.")
   724	        return self._curves_dir / _safe_path_fragment(sensor_id) / _safe_path_fragment(curve_id)
   725	
   726	    def _curve_path(self, sensor_id: str, curve_id: str) -> Path:
   727	        return self._curve_directory(sensor_id, curve_id) / "curve.json"
   728	
   729	    def _curve_340_path(self, sensor_id: str, curve_id: str) -> Path:
   730	        if self._exports_dir is None:
   731	            raise RuntimeError("CalibrationStore base_dir is required for export.")
   732	        return (
   733	            self._exports_dir
   734	            / _safe_path_fragment(sensor_id)
   735	            / _safe_path_fragment(curve_id)
   736	            / "curve.340"
   737	        )
   738	
   739	    def _load_index(self) -> None:
   740	        if self._index_path is None or not self._index_path.exists():
   741	            return
   742	        payload = yaml.safe_load(self._index_path.read_text(encoding="utf-8")) or {}
   743	        runtime = payload.get("runtime", {})
   744	        if isinstance(runtime, dict):
   745	            global_mode = str(runtime.get("global_mode", "off") or "off").strip().lower()
   746	            if global_mode in {"off", "on"}:
   747	                self._runtime_settings["global_mode"] = global_mode
   748	            self._runtime_settings["updated_at"] = str(runtime.get("updated_at", "")).strip()
   749	        assignments = payload.get("assignments", [])
   750	        if isinstance(assignments, list):
   751	            for item in assignments:
   752	                if not isinstance(item, dict):
   753	                    continue
   754	                sensor_id = str(item.get("sensor_id", "")).strip()
   755	                if sensor_id:
   756	                    self._assignments[sensor_id] = {
   757	                        "sensor_id": sensor_id,
   758	                        "curve_id": str(item.get("curve_id", "")).strip(),
   759	                        "channel_key": str(item.get("channel_key", sensor_id)).strip() or sensor_id,
   760	                        "updated_at": str(item.get("updated_at", "")).strip(),
   761	                        "runtime_apply_ready": bool(item.get("runtime_apply_ready", False)),
   762	                        "reading_mode_policy": str(
   763	                            item.get("reading_mode_policy", "inherit") or "inherit"
   764	                        )
   765	                        .strip()
   766	                        .lower()
   767	                        or "inherit",
   768	                    }
   769	
   770	    def _write_index(self) -> None:
   771	        if self._index_path is None:
   772	            return
   773	        self._index_path.parent.mkdir(parents=True, exist_ok=True)
   774	        payload = {
   775	            "schema_version": 1,
   776	            "generated_at": _utcnow().isoformat(),
   777	            "runtime": {
   778	                "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
   779	                "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
   780	            },
   781	            "curves": [
   782	                {
   783	                    "sensor_id": curve.sensor_id,
   784	                    "curve_id": curve.curve_id,
   785	                    "fit_timestamp": curve.fit_timestamp.isoformat(),
   786	                    "raw_unit": curve.raw_unit,
   787	                    "sensor_kind": curve.sensor_kind,
   788	                    "curve_path": str(self._curve_path(curve.sensor_id, curve.curve_id)),
   789	                    "table_path": str(
   790	                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
   791	                    ),
   792	                    "curve_cof_path": str(
   793	                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof"
   794	                    ),
   795	                    "curve_340_path": str(
   796	                        self._curve_340_path(curve.sensor_id, curve.curve_id)
   797	                        if self._exports_dir
   798	                        else ""
   799	                    ),
   800	                    "source_session_ids": list(curve.source_session_ids),
   801	                }
   802	                for curve in sorted(
   803	                    self._curves.values(), key=lambda item: item.fit_timestamp, reverse=True
   804	                )
   805	            ],
   806	            "assignments": [dict(item) for item in self.list_assignments()],
   807	        }
   808	        from cryodaq.core.atomic_write import atomic_write_text
   809	
   810	        atomic_write_text(
   811	            self._index_path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
   812	        )
   813	
   814	    def _ensure_assignment(self, *, sensor_id: str, curve_id: str) -> dict[str, Any]:
   815	        existing = self._assignments.get(sensor_id)
   816	        if existing:
   817	            existing["curve_id"] = curve_id
   818	            existing["updated_at"] = _utcnow().isoformat()
   819	            return existing
   820	        assignment = {
   821	            "sensor_id": sensor_id,
   822	            "curve_id": curve_id,
   823	            "channel_key": sensor_id,
   824	            "updated_at": _utcnow().isoformat(),
   825	            "runtime_apply_ready": False,
   826	            "reading_mode_policy": "inherit",
   827	        }
   828	        self._assignments[sensor_id] = assignment
   829	        return assignment
   830	
   831	    def _export_rows(self, curve: CalibrationCurve, *, points: int) -> list[tuple[float, float]]:
   832	        dense_points = max(points * 24, 2000)
   833	        raw_min = curve.zones[0].raw_min
   834	        raw_max = curve.zones[-1].raw_max
   835	        raw_grid = np.linspace(raw_min, raw_max, dense_points, dtype=float)
   836	        temperatures = np.array(
   837	            [curve.evaluate(float(raw_value)) for raw_value in raw_grid], dtype=float
   838	        )
   839	        order = np.argsort(temperatures)
   840	        sorted_temperatures = temperatures[order]
   841	        sorted_raw = raw_grid[order]
   842	        sorted_temperatures, sorted_raw = self._collapse_duplicate_axis(
   843	            sorted_temperatures, sorted_raw
   844	        )
   845	        indices = self._adaptive_breakpoint_indices(sorted_temperatures, sorted_raw, max(points, 2))
   846	        rows = [(float(sorted_temperatures[index]), float(sorted_raw[index])) for index in indices]
   847	        deduped: list[tuple[float, float]] = []
   848	        seen: set[tuple[float, float]] = set()
   849	        for item in rows:
   850	            key = (round(item[0], 9), round(item[1], 9))
   851	            if key in seen:
   852	                continue
   853	            seen.add(key)
   854	            deduped.append(item)
   855	        return deduped[: max(points, 2)]
   856	
   857	    def _write_curve_text_export(
   858	        self,
   859	        path: Path,
   860	        curve: CalibrationCurve,
   861	        rows: list[tuple[float, float]],
   862	        *,
   863	        format_name: str,
   864	    ) -> None:
   865	        with path.open("w", encoding="utf-8", newline="") as handle:
   866	            handle.write(f"# CryoDAQ calibration curve export .{format_name}\n")
   867	            handle.write(f"# sensor_id: {curve.sensor_id}\n")
   868	            handle.write(f"# curve_id: {curve.curve_id}\n")
   869	            handle.write(f"# raw_unit: {curve.raw_unit}\n")
   870	            handle.write("# columns: temperature_K, sensor_raw\n")
   871	            writer = csv.writer(handle)
   872	            for temperature_k, raw_value in rows:
   873	                writer.writerow([f"{temperature_k:.9g}", f"{raw_value:.9g}"])
   874	
   875	    def _write_cof_export(self, path: Path, curve: CalibrationCurve) -> None:
   876	        """Write .cof format: header + per-zone raw Chebyshev coefficients."""
   877	        from cryodaq.core.atomic_write import atomic_write_text
   878	
   879	        lines: list[str] = []
   880	        lines.append("# CryoDAQ calibration curve export .cof")
   881	        lines.append(f"# sensor_id: {curve.sensor_id}")
   882	        lines.append(f"# curve_id: {curve.curve_id}")
   883	        lines.append(f"# raw_unit: {curve.raw_unit}")
   884	        lines.append(f"# fit_timestamp: {curve.fit_timestamp.isoformat()}")
   885	        lines.append(
   886	            "# format: Chebyshev T_n(x), x = 2*(raw - raw_min)/(raw_max - raw_min) - 1"
   887	        )
   888	        lines.append(f"# zone_count: {len(curve.zones)}")
   889	        lines.append("")
   890	        for index, zone in enumerate(curve.zones, start=1):
   891	            lines.append(f"[zone {index}]")
   892	            lines.append(f"raw_min: {zone.raw_min:.12g}")
   893	            lines.append(f"raw_max: {zone.raw_max:.12g}")
   894	            lines.append(f"order: {zone.order}")
   895	            coefficients = ", ".join(f"{value:.12g}" for value in zone.coefficients)
   896	            lines.append(f"coefficients: {coefficients}")
   897	            lines.append(f"# rmse_k: {zone.rmse_k:.6g}")
   898	            lines.append(f"# max_abs_error_k: {zone.max_abs_error_k:.6g}")
   899	            lines.append(f"# point_count: {zone.point_count}")
   900	            lines.append("")
   901	        atomic_write_text(path, "\n".join(lines))
   902	
   903	    def _import_curve_text(
   904	        self,
   905	        path: Path,
   906	        *,
   907	        sensor_id: str | None,
   908	        channel_key: str | None,
   909	        raw_unit: str,
   910	        sensor_kind: str,
   911	        import_format: str,
   912	    ) -> CalibrationCurve:
   913	        rows: list[tuple[float, float]] = []
   914	        for raw_line in path.read_text(encoding="utf-8").splitlines():
   915	            line = raw_line.strip()
   916	            if not line or line.startswith("#"):
   917	                continue
   918	            line = line.replace(",", " ")
   919	            parts = [item for item in line.split() if item]
   920	            if len(parts) < 2:

exec
/opt/homebrew/bin/bash -lc 'find artifacts/consultations/2026-04-28-cof-migration -maxdepth 1 -type f -print' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.response.md
artifacts/consultations/2026-04-28-cof-migration/gemini-cof-audit.prompt.md
artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.prompt.md
artifacts/consultations/2026-04-28-cof-migration/gemini-cof-audit.response.md

exec
/opt/homebrew/bin/bash -lc "rg -n \"export_curve_330|curve_330_path|curve_cof_path|\\.330|import_format == \\\"330\\\"|export_curve_340|_write_index|_curve_directory|_write_cof_export|atomic_write_text|format: Chebyshev\" src/cryodaq/analytics/calibration.py tests/analytics/test_calibration.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
tests/analytics/test_calibration.py:200:    path_340 = source_store.export_curve_340("sensor-003", points=200)
tests/analytics/test_calibration.py:224:    exported_340 = source_store.export_curve_340("sensor-004", points=48)
tests/analytics/test_calibration.py:266:    """B-1.2: calibration.py index/curve writes must use atomic_write_text."""
tests/analytics/test_calibration.py:273:        f"should all route through atomic_write_text"
tests/analytics/test_calibration.py:275:    assert "atomic_write_text" in source
tests/analytics/test_calibration.py:279:# Phase D: .cof export + .330 removal
tests/analytics/test_calibration.py:359:def test_export_curve_330_removed(tmp_path: Path) -> None:
tests/analytics/test_calibration.py:361:    assert not hasattr(store, "export_curve_330"), (
tests/analytics/test_calibration.py:362:        "export_curve_330 must be removed — architect decision 2026-04-25"
tests/analytics/test_calibration.py:367:    fake_330 = tmp_path / "curve.330"
src/cryodaq/analytics/calibration.py:345:        from cryodaq.core.atomic_write import atomic_write_text
src/cryodaq/analytics/calibration.py:347:        atomic_write_text(target, json.dumps(curve.to_payload(), ensure_ascii=False, indent=2))
src/cryodaq/analytics/calibration.py:350:        self._write_index()
src/cryodaq/analytics/calibration.py:362:        self._write_index()
src/cryodaq/analytics/calibration.py:397:        self._write_index()
src/cryodaq/analytics/calibration.py:412:        target = path or self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
src/cryodaq/analytics/calibration.py:438:        target = path or (self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof")
src/cryodaq/analytics/calibration.py:440:        self._write_cof_export(target, curve)
src/cryodaq/analytics/calibration.py:441:        self._write_index()
src/cryodaq/analytics/calibration.py:444:    def export_curve_340(
src/cryodaq/analytics/calibration.py:458:        self._write_index()
src/cryodaq/analytics/calibration.py:484:                self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
src/cryodaq/analytics/calibration.py:486:            "curve_cof_path": str(
src/cryodaq/analytics/calibration.py:487:                self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof"
src/cryodaq/analytics/calibration.py:530:        self._write_index()
src/cryodaq/analytics/calibration.py:558:        self._write_index()
src/cryodaq/analytics/calibration.py:667:        self._write_index()
src/cryodaq/analytics/calibration.py:721:    def _curve_directory(self, sensor_id: str, curve_id: str) -> Path:
src/cryodaq/analytics/calibration.py:727:        return self._curve_directory(sensor_id, curve_id) / "curve.json"
src/cryodaq/analytics/calibration.py:770:    def _write_index(self) -> None:
src/cryodaq/analytics/calibration.py:790:                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
src/cryodaq/analytics/calibration.py:792:                    "curve_cof_path": str(
src/cryodaq/analytics/calibration.py:793:                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof"
src/cryodaq/analytics/calibration.py:808:        from cryodaq.core.atomic_write import atomic_write_text
src/cryodaq/analytics/calibration.py:810:        atomic_write_text(
src/cryodaq/analytics/calibration.py:875:    def _write_cof_export(self, path: Path, curve: CalibrationCurve) -> None:
src/cryodaq/analytics/calibration.py:877:        from cryodaq.core.atomic_write import atomic_write_text
src/cryodaq/analytics/calibration.py:886:            "# format: Chebyshev T_n(x), x = 2*(raw - raw_min)/(raw_max - raw_min) - 1"
src/cryodaq/analytics/calibration.py:901:        atomic_write_text(path, "\n".join(lines))
src/cryodaq/analytics/calibration.py:962:            self.export_curve_340(curve.sensor_id)

codex
The requested response path already exists as an untracked file. I’m reading it before deciding how to handle the requested write, because this environment does not permit filesystem writes.
exec
/opt/homebrew/bin/bash -lc 'nl -ba artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.response.md' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	Reading additional input from stdin...
     2	OpenAI Codex v0.124.0 (research preview)
     3	--------
     4	workdir: /Users/vladimir/Projects/cryodaq
     5	model: gpt-5.5
     6	provider: openai
     7	approval: never
     8	sandbox: read-only
     9	reasoning effort: high
    10	reasoning summaries: none
    11	session id: 019dd06e-c065-7600-84b4-59448a9a784b
    12	--------
    13	user
    14	Model: gpt-5.5
    15	Reasoning effort: high
    16	
    17	# .cof migration audit — literal verifier
    18	
    19	You are auditing branch `feat/cof-calibration-export` of the CryoDAQ repo at
    20	~/Projects/cryodaq. Read the files directly. Do NOT summarize — find specific
    21	bugs, gaps, or contradictions.
    22	
    23	## Read these files
    24	
    25	1. `src/cryodaq/analytics/calibration.py` — full file
    26	2. `tests/analytics/test_calibration.py` — full file
    27	
    28	## Verify each item — mark PASS or FAIL with file:line
    29	
    30	### A. export_curve_cof() implementation
    31	A1. Method exists on CalibrationStore and calls _write_cof_export(). PASS/FAIL:line
    32	A2. Default path is `<curve_dir>/curve.cof` (not curve.330 or curve.340). PASS/FAIL:line
    33	A3. Calls self._write_index() before returning. PASS/FAIL:line
    34	A4. Returns the Path of the written file. PASS/FAIL:line
    35	
    36	### B. _write_cof_export() format correctness
    37	B1. Header contains: sensor_id, curve_id, raw_unit, fit_timestamp, format description, zone_count. List any missing.
    38	B2. Each zone section has: raw_min, raw_max, order, coefficients. List any missing.
    39	B3. Coefficients are formatted with sufficient precision (>=10 significant digits). PASS/FAIL:line
    40	B4. Uses atomic_write_text (not open().write()). PASS/FAIL:line
    41	B5. The Chebyshev domain description in the comment matches what CalibrationZone.evaluate() actually does (check line ~117). PASS/FAIL — quote both strings if mismatch.
    42	
    43	### C. .330 removal completeness
    44	C1. export_curve_330 method is absent from the class. PASS/FAIL
    45	C2. import_curve_file: accepted suffixes do NOT include ".330". PASS/FAIL:line
    46	C3. _import_curve_text: no branch for import_format == "330". PASS/FAIL:line
    47	C4. get_curve_artifacts: dict key is "curve_cof_path", not "curve_330_path". PASS/FAIL:line
    48	C5. _write_index: "curve_cof_path" key used, not "curve_330_path". PASS/FAIL:line
    49	
    50	### D. .340 preservation
    51	D1. export_curve_340 method still present and unchanged. PASS/FAIL
    52	D2. import_curve_file still accepts ".340". PASS/FAIL:line
    53	
    54	### E. Test coverage
    55	E1. test_export_curve_cof_writes_file_with_expected_structure: asserts file exists, suffix, and header content. PASS/FAIL
    56	E2. test_export_curve_cof_preserves_chebyshev_coefficients_round_trip: parses coefficients from .cof and compares to zone.coefficients. Does it verify ALL zones? PASS/FAIL
    57	E3. test_export_curve_330_removed: checks hasattr, not call behavior. Is this adequate? PASS/FAIL + comment
    58	E4. test_import_curve_file_rejects_330_suffix: passes a fake .330 file, expects ValueError. Does the written file have enough rows (>=4) to not fail on row-count check before the suffix check? PASS/FAIL — trace the code path.
    59	E5. Existing test test_export_340_uses_200_breakpoints_and_roundtrips_via_import: still calls export_curve_330? PASS/FAIL
    60	
    61	### F. Edge case
    62	F1. export_curve_cof() when CalibrationStore has no base_dir (base_dir=None):
    63	    _curve_directory() raises RuntimeError. Is this the right behavior?
    64	    Trace the call: export_curve_cof -> _curve_directory -> ... PASS/FAIL + line
    65	
    66	## Output format
    67	For each item above: `<id>: PASS | FAIL | WARNING — <one line> [file:line]`
    68	Then a findings table of all FAILs/WARNINGs with severity (CRITICAL/HIGH/MEDIUM/LOW).
    69	Then: VERDICT: PASS / CONDITIONAL / FAIL
    70	
    71	Write output to:
    72	~/Projects/cryodaq/artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.response.md
    73	codex
    74	I’ll read the required verification skill first, then inspect the two target files with line numbers and produce the audit. The workspace is read-only in this session, so I’ll verify whether I can create the requested artifact before claiming it was written.
    75	exec
    76	/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/b066e4a0/skills/using-superpowers/SKILL.md" in /Users/vladimir/Projects/cryodaq
    77	 succeeded in 0ms:
    78	---
    79	name: using-superpowers
    80	description: Use when starting any conversation - establishes how to find and use skills, requiring Skill tool invocation before ANY response including clarifying questions
    81	---
    82	
    83	<SUBAGENT-STOP>
    84	If you were dispatched as a subagent to execute a specific task, skip this skill.
    85	</SUBAGENT-STOP>
    86	
    87	<EXTREMELY-IMPORTANT>
    88	If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill.
    89	
    90	IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE. YOU MUST USE IT.
    91	
    92	This is not negotiable. This is not optional. You cannot rationalize your way out of this.
    93	</EXTREMELY-IMPORTANT>
    94	
    95	## Instruction Priority
    96	
    97	Superpowers skills override default system prompt behavior, but **user instructions always take precedence**:
    98	
    99	1. **User's explicit instructions** (CLAUDE.md, GEMINI.md, AGENTS.md, direct requests) — highest priority
   100	2. **Superpowers skills** — override default system behavior where they conflict
   101	3. **Default system prompt** — lowest priority
   102	
   103	If CLAUDE.md, GEMINI.md, or AGENTS.md says "don't use TDD" and a skill says "always use TDD," follow the user's instructions. The user is in control.
   104	
   105	## How to Access Skills
   106	
   107	**In Claude Code:** Use the `Skill` tool. When you invoke a skill, its content is loaded and presented to you—follow it directly. Never use the Read tool on skill files.
   108	
   109	**In Copilot CLI:** Use the `skill` tool. Skills are auto-discovered from installed plugins. The `skill` tool works the same as Claude Code's `Skill` tool.
   110	
   111	**In Gemini CLI:** Skills activate via the `activate_skill` tool. Gemini loads skill metadata at session start and activates the full content on demand.
   112	
   113	**In other environments:** Check your platform's documentation for how skills are loaded.
   114	
   115	## Platform Adaptation
   116	
   117	Skills use Claude Code tool names. Non-CC platforms: see `references/copilot-tools.md` (Copilot CLI), `references/codex-tools.md` (Codex) for tool equivalents. Gemini CLI users get the tool mapping loaded automatically via GEMINI.md.
   118	
   119	# Using Skills
   120	
   121	## The Rule
   122	
   123	**Invoke relevant or requested skills BEFORE any response or action.** Even a 1% chance a skill might apply means that you should invoke the skill to check. If an invoked skill turns out to be wrong for the situation, you don't need to use it.
   124	
   125	```dot
   126	digraph skill_flow {
   127	    "User message received" [shape=doublecircle];
   128	    "About to EnterPlanMode?" [shape=doublecircle];
   129	    "Already brainstormed?" [shape=diamond];
   130	    "Invoke brainstorming skill" [shape=box];
   131	    "Might any skill apply?" [shape=diamond];
   132	    "Invoke Skill tool" [shape=box];
   133	    "Announce: 'Using [skill] to [purpose]'" [shape=box];
   134	    "Has checklist?" [shape=diamond];
   135	    "Create TodoWrite todo per item" [shape=box];
   136	    "Follow skill exactly" [shape=box];
   137	    "Respond (including clarifications)" [shape=doublecircle];
   138	
   139	    "About to EnterPlanMode?" -> "Already brainstormed?";
   140	    "Already brainstormed?" -> "Invoke brainstorming skill" [label="no"];
   141	    "Already brainstormed?" -> "Might any skill apply?" [label="yes"];
   142	    "Invoke brainstorming skill" -> "Might any skill apply?";
   143	
   144	    "User message received" -> "Might any skill apply?";
   145	    "Might any skill apply?" -> "Invoke Skill tool" [label="yes, even 1%"];
   146	    "Might any skill apply?" -> "Respond (including clarifications)" [label="definitely not"];
   147	    "Invoke Skill tool" -> "Announce: 'Using [skill] to [purpose]'";
   148	    "Announce: 'Using [skill] to [purpose]'" -> "Has checklist?";
   149	    "Has checklist?" -> "Create TodoWrite todo per item" [label="yes"];
   150	    "Has checklist?" -> "Follow skill exactly" [label="no"];
   151	    "Create TodoWrite todo per item" -> "Follow skill exactly";
   152	}
   153	```
   154	
   155	## Red Flags
   156	
   157	These thoughts mean STOP—you're rationalizing:
   158	
   159	| Thought | Reality |
   160	|---------|---------|
   161	| "This is just a simple question" | Questions are tasks. Check for skills. |
   162	| "I need more context first" | Skill check comes BEFORE clarifying questions. |
   163	| "Let me explore the codebase first" | Skills tell you HOW to explore. Check first. |
   164	| "I can check git/files quickly" | Files lack conversation context. Check for skills. |
   165	| "Let me gather information first" | Skills tell you HOW to gather information. |
   166	| "This doesn't need a formal skill" | If a skill exists, use it. |
   167	| "I remember this skill" | Skills evolve. Read current version. |
   168	| "This doesn't count as a task" | Action = task. Check for skills. |
   169	| "The skill is overkill" | Simple things become complex. Use it. |
   170	| "I'll just do this one thing first" | Check BEFORE doing anything. |
   171	| "This feels productive" | Undisciplined action wastes time. Skills prevent this. |
   172	| "I know what that means" | Knowing the concept ≠ using the skill. Invoke it. |
   173	
   174	## Skill Priority
   175	
   176	When multiple skills could apply, use this order:
   177	
   178	1. **Process skills first** (brainstorming, debugging) - these determine HOW to approach the task
   179	2. **Implementation skills second** (frontend-design, mcp-builder) - these guide execution
   180	
   181	"Let's build X" → brainstorming first, then implementation skills.
   182	"Fix this bug" → debugging first, then domain-specific skills.
   183	
   184	## Skill Types
   185	
   186	**Rigid** (TDD, debugging): Follow exactly. Don't adapt away discipline.
   187	
   188	**Flexible** (patterns): Adapt principles to context.
   189	
   190	The skill itself tells you which.
   191	
   192	## User Instructions
   193	
   194	Instructions say WHAT, not HOW. "Add X" or "Fix Y" doesn't mean skip workflows.
   195	
   196	codex
   197	Using `superpowers:using-superpowers` to follow the required skill workflow. Now I’m reading both target files with line numbers so each PASS/FAIL can be tied to the literal source.
   198	exec
   199	/opt/homebrew/bin/bash -lc 'nl -ba src/cryodaq/analytics/calibration.py' in /Users/vladimir/Projects/cryodaq
   200	 succeeded in 0ms:
   201	     1	"""Calibration backend: session storage, Chebyshev fits, and artifact IO."""
   202	     2	
   203	     3	from __future__ import annotations
   204	     4	
   205	     5	import csv
   206	     6	import json
   207	     7	import math
   208	     8	import uuid
   209	     9	import warnings
   210	    10	from dataclasses import dataclass, field
   211	    11	from datetime import UTC, datetime
   212	    12	from pathlib import Path
   213	    13	from typing import Any
   214	    14	
   215	    15	import numpy as np
   216	    16	import yaml
   217	    17	from numpy.polynomial import chebyshev as cheb
   218	    18	
   219	    19	
   220	    20	def _utcnow() -> datetime:
   221	    21	    return datetime.now(UTC)
   222	    22	
   223	    23	
   224	    24	def _parse_time(raw: datetime | str | None) -> datetime | None:
   225	    25	    if raw is None:
   226	    26	        return None
   227	    27	    if isinstance(raw, datetime):
   228	    28	        if raw.tzinfo is None:
   229	    29	            return raw.replace(tzinfo=UTC)
   230	    30	        return raw.astimezone(UTC)
   231	    31	    text = str(raw).strip()
   232	    32	    if not text:
   233	    33	        return None
   234	    34	    if text.endswith("Z"):
   235	    35	        text = f"{text[:-1]}+00:00"
   236	    36	    parsed = datetime.fromisoformat(text)
   237	    37	    if parsed.tzinfo is None:
   238	    38	        return parsed.replace(tzinfo=UTC)
   239	    39	    return parsed.astimezone(UTC)
   240	    40	
   241	    41	
   242	    42	def _json_dict(raw: Any) -> dict[str, Any]:
   243	    43	    if raw is None:
   244	    44	        return {}
   245	    45	    if isinstance(raw, dict):
   246	    46	        return {str(key): value for key, value in raw.items()}
   247	    47	    raise ValueError("Expected dictionary payload.")
   248	    48	
   249	    49	
   250	    50	def _safe_path_fragment(value: str) -> str:
   251	    51	    cleaned = "".join("_" if char in '<>:"/\\|?*' else char for char in str(value).strip())
   252	    52	    return cleaned or "unnamed"
   253	    53	
   254	    54	
   255	    55	@dataclass(frozen=True, slots=True)
   256	    56	class CalibrationSample:
   257	    57	    timestamp: datetime
   258	    58	    reference_channel: str
   259	    59	    reference_temperature: float
   260	    60	    sensor_channel: str
   261	    61	    sensor_raw_value: float
   262	    62	    reference_instrument_id: str = ""
   263	    63	    sensor_instrument_id: str = ""
   264	    64	    experiment_id: str | None = None
   265	    65	    metadata: dict[str, Any] = field(default_factory=dict)
   266	    66	
   267	    67	    def to_payload(self) -> dict[str, Any]:
   268	    68	        return {
   269	    69	            "timestamp": self.timestamp.isoformat(),
   270	    70	            "reference_channel": self.reference_channel,
   271	    71	            "reference_temperature": self.reference_temperature,
   272	    72	            "sensor_channel": self.sensor_channel,
   273	    73	            "sensor_raw_value": self.sensor_raw_value,
   274	    74	            "reference_instrument_id": self.reference_instrument_id,
   275	    75	            "sensor_instrument_id": self.sensor_instrument_id,
   276	    76	            "experiment_id": self.experiment_id,
   277	    77	            "metadata": dict(self.metadata),
   278	    78	        }
   279	    79	
   280	    80	    @classmethod
   281	    81	    def from_payload(cls, payload: dict[str, Any]) -> CalibrationSample:
   282	    82	        return cls(
   283	    83	            timestamp=_parse_time(payload.get("timestamp")) or _utcnow(),
   284	    84	            reference_channel=str(payload.get("reference_channel", "")),
   285	    85	            reference_temperature=float(payload.get("reference_temperature", 0.0)),
   286	    86	            sensor_channel=str(payload.get("sensor_channel", "")),
   287	    87	            sensor_raw_value=float(payload.get("sensor_raw_value", 0.0)),
   288	    88	            reference_instrument_id=str(payload.get("reference_instrument_id", "")),
   289	    89	            sensor_instrument_id=str(payload.get("sensor_instrument_id", "")),
   290	    90	            experiment_id=(
   291	    91	                str(payload.get("experiment_id"))
   292	    92	                if payload.get("experiment_id") not in (None, "")
   293	    93	                else None
   294	    94	            ),
   295	    95	            metadata=_json_dict(payload.get("metadata")),
   296	    96	        )
   297	    97	
   298	    98	
   299	    99	@dataclass(frozen=True, slots=True)
   300	   100	class CalibrationZone:
   301	   101	    raw_min: float
   302	   102	    raw_max: float
   303	   103	    order: int
   304	   104	    coefficients: tuple[float, ...]
   305	   105	    rmse_k: float
   306	   106	    max_abs_error_k: float
   307	   107	    point_count: int
   308	   108	
   309	   109	    def contains(self, raw_value: float) -> bool:
   310	   110	        return self.raw_min <= raw_value <= self.raw_max
   311	   111	
   312	   112	    def evaluate(self, raw_value: float) -> float:
   313	   113	        if self.raw_max <= self.raw_min:
   314	   114	            raise ValueError("Calibration zone has invalid range.")
   315	   115	        clipped = min(max(raw_value, self.raw_min), self.raw_max)
   316	   116	        scaled = ((2.0 * (clipped - self.raw_min)) / (self.raw_max - self.raw_min)) - 1.0
   317	   117	        return float(cheb.chebval(scaled, self.coefficients))
   318	   118	
   319	   119	    def to_payload(self) -> dict[str, Any]:
   320	   120	        return {
   321	   121	            "raw_min": self.raw_min,
   322	   122	            "raw_max": self.raw_max,
   323	   123	            "order": self.order,
   324	   124	            "coefficients": list(self.coefficients),
   325	   125	            "rmse_k": self.rmse_k,
   326	   126	            "max_abs_error_k": self.max_abs_error_k,
   327	   127	            "point_count": self.point_count,
   328	   128	        }
   329	   129	
   330	   130	    @classmethod
   331	   131	    def from_payload(cls, payload: dict[str, Any]) -> CalibrationZone:
   332	   132	        return cls(
   333	   133	            raw_min=float(payload.get("raw_min", 0.0)),
   334	   134	            raw_max=float(payload.get("raw_max", 0.0)),
   335	   135	            order=int(payload.get("order", 1)),
   336	   136	            coefficients=tuple(float(value) for value in payload.get("coefficients", [])),
   337	   137	            rmse_k=float(payload.get("rmse_k", 0.0)),
   338	   138	            max_abs_error_k=float(payload.get("max_abs_error_k", 0.0)),
   339	   139	            point_count=int(payload.get("point_count", 0)),
   340	   140	        )
   341	   141	
   342	   142	
   343	   143	@dataclass(frozen=True, slots=True)
   344	   144	class CalibrationCurve:
   345	   145	    curve_id: str
   346	   146	    sensor_id: str
   347	   147	    fit_timestamp: datetime
   348	   148	    raw_unit: str
   349	   149	    sensor_kind: str
   350	   150	    source_session_ids: tuple[str, ...]
   351	   151	    zones: tuple[CalibrationZone, ...]
   352	   152	    metrics: dict[str, Any] = field(default_factory=dict)
   353	   153	    metadata: dict[str, Any] = field(default_factory=dict)
   354	   154	
   355	   155	    def evaluate(self, raw_value: float) -> float:
   356	   156	        if not self.zones:
   357	   157	            raise ValueError("Calibration curve has no fitted zones.")
   358	   158	        for zone in self.zones:
   359	   159	            if zone.contains(raw_value):
   360	   160	                return zone.evaluate(raw_value)
   361	   161	        if raw_value < self.zones[0].raw_min:
   362	   162	            return self.zones[0].evaluate(raw_value)
   363	   163	        return self.zones[-1].evaluate(raw_value)
   364	   164	
   365	   165	    def to_payload(self) -> dict[str, Any]:
   366	   166	        return {
   367	   167	            "schema_version": 1,
   368	   168	            "curve_id": self.curve_id,
   369	   169	            "sensor_id": self.sensor_id,
   370	   170	            "fit_timestamp": self.fit_timestamp.isoformat(),
   371	   171	            "raw_unit": self.raw_unit,
   372	   172	            "sensor_kind": self.sensor_kind,
   373	   173	            "source_session_ids": list(self.source_session_ids),
   374	   174	            "zones": [zone.to_payload() for zone in self.zones],
   375	   175	            "metrics": dict(self.metrics),
   376	   176	            "metadata": dict(self.metadata),
   377	   177	        }
   378	   178	
   379	   179	    @classmethod
   380	   180	    def from_payload(cls, payload: dict[str, Any]) -> CalibrationCurve:
   381	   181	        return cls(
   382	   182	            curve_id=str(payload.get("curve_id", "")),
   383	   183	            sensor_id=str(payload.get("sensor_id", "")),
   384	   184	            fit_timestamp=_parse_time(payload.get("fit_timestamp")) or _utcnow(),
   385	   185	            raw_unit=str(payload.get("raw_unit", "sensor_unit")),
   386	   186	            sensor_kind=str(payload.get("sensor_kind", "generic")),
   387	   187	            source_session_ids=tuple(str(item) for item in payload.get("source_session_ids", [])),
   388	   188	            zones=tuple(CalibrationZone.from_payload(item) for item in payload.get("zones", [])),
   389	   189	            metrics=_json_dict(payload.get("metrics")),
   390	   190	            metadata=_json_dict(payload.get("metadata")),
   391	   191	        )
   392	   192	
   393	   193	
   394	   194	class CalibrationStore:
   395	   195	    """Calibration curve storage and multi-zone Chebyshev fitting."""
   396	   196	
   397	   197	    _TASK_CV_ORDER_RANGE = tuple(range(7, 13))
   398	   198	    _TASK_DOWNSAMPLE_TARGET = 5000
   399	   199	
   400	   200	    def __init__(self, base_dir: Path | None = None) -> None:
   401	   201	        self._base_dir = base_dir
   402	   202	        self._curves_dir = base_dir / "curves" if base_dir is not None else None
   403	   203	        self._exports_dir = base_dir / "exports" if base_dir is not None else None
   404	   204	        self._index_path = base_dir / "index.yaml" if base_dir is not None else None
   405	   205	        self._curves: dict[str, CalibrationCurve] = {}
   406	   206	        self._assignments: dict[str, dict[str, Any]] = {}
   407	   207	        self._runtime_settings: dict[str, Any] = {
   408	   208	            "global_mode": "off",
   409	   209	            "updated_at": "",
   410	   210	        }
   411	   211	        if self._index_path is not None:
   412	   212	            self._load_index()
   413	   213	
   414	   214	    def fit_curve(
   415	   215	        self,
   416	   216	        sensor_id: str,
   417	   217	        samples: list[CalibrationSample] | tuple[CalibrationSample, ...],
   418	   218	        *,
   419	   219	        raw_unit: str = "sensor_unit",
   420	   220	        sensor_kind: str = "generic",
   421	   221	        source_session_ids: list[str] | tuple[str, ...] | None = None,
   422	   222	        max_zones: int = 3,
   423	   223	        min_points_per_zone: int = 6,
   424	   224	        max_order: int = 12,
   425	   225	        target_rmse_k: float = 0.05,
   426	   226	        metadata: dict[str, Any] | None = None,
   427	   227	    ) -> CalibrationCurve:
   428	   228	        if not sensor_id.strip():
   429	   229	            raise ValueError("sensor_id is required for calibration fit.")
   430	   230	        if len(samples) < max(4, min_points_per_zone):
   431	   231	            raise ValueError("Not enough calibration samples for fitting.")
   432	   232	        normalized_samples = self._preprocess_samples(
   433	   233	            samples,
   434	   234	            downsample_target=self._TASK_DOWNSAMPLE_TARGET,
   435	   235	        )
   436	   236	        if len(normalized_samples) < max(4, min_points_per_zone):
   437	   237	            raise ValueError("Not enough calibration samples for fitting after preprocessing.")
   438	   238	
   439	   239	        temperatures = np.array(
   440	   240	            [sample.reference_temperature for sample in normalized_samples], dtype=float
   441	   241	        )
   442	   242	        raw_values = np.array(
   443	   243	            [sample.sensor_raw_value for sample in normalized_samples], dtype=float
   444	   244	        )
   445	   245	
   446	   246	        if not np.all(np.isfinite(raw_values)) or not np.all(np.isfinite(temperatures)):
   447	   247	            raise ValueError("Calibration samples must contain finite values only.")
   448	   248	        if np.ptp(raw_values) <= 0 or np.ptp(temperatures) <= 0:
   449	   249	            raise ValueError("Calibration raw values must span a non-zero range.")
   450	   250	        zone_slices = self._detect_zone_slices(
   451	   251	            temperatures,
   452	   252	            raw_values,
   453	   253	            max_zones=max(1, max_zones),
   454	   254	            min_points_per_zone=max(3, min_points_per_zone),
   455	   255	            max_order=max(1, max_order),
   456	   256	        )
   457	   257	        zones = self._fit_zone_slices(
   458	   258	            temperatures,
   459	   259	            raw_values,
   460	   260	            zone_slices=zone_slices,
   461	   261	            max_order=max(1, max_order),
   462	   262	            target_rmse_k=max(float(target_rmse_k), 0.0),
   463	   263	        )
   464	   264	
   465	   265	        all_predictions = np.array(
   466	   266	            [self._evaluate_zones(zones, raw_value) for raw_value in raw_values],
   467	   267	            dtype=float,
   468	   268	        )
   469	   269	        residuals = all_predictions - temperatures
   470	   270	        sensitivity = np.gradient(raw_values, temperatures)
   471	   271	        curve = CalibrationCurve(
   472	   272	            curve_id=uuid.uuid4().hex[:12],
   473	   273	            sensor_id=sensor_id.strip(),
   474	   274	            fit_timestamp=_utcnow(),
   475	   275	            raw_unit=raw_unit.strip() or "sensor_unit",
   476	   276	            sensor_kind=sensor_kind.strip() or "generic",
   477	   277	            source_session_ids=tuple(str(item) for item in (source_session_ids or ()) if str(item)),
   478	   278	            zones=tuple(zones),
   479	   279	            metrics={
   480	   280	                "sample_count": int(len(normalized_samples)),
   481	   281	                "input_sample_count": int(len(samples)),
   482	   282	                "downsampled_sample_count": int(len(normalized_samples)),
   483	   283	                "downsampling_applied": bool(len(normalized_samples) != len(samples)),
   484	   284	                "zone_count": int(len(zones)),
   485	   285	                "rmse_k": float(math.sqrt(np.mean(np.square(residuals)))),
   486	   286	                "max_abs_error_k": float(np.max(np.abs(residuals))),
   487	   287	                "raw_min": float(np.min(raw_values)),
   488	   288	                "raw_max": float(np.max(raw_values)),
   489	   289	                "temperature_min_k": float(np.min(temperatures)),
   490	   290	                "temperature_max_k": float(np.max(temperatures)),
   491	   291	                "zone_detection": "dV/dT",
   492	   292	                "order_selection": "cross_validation",
   493	   293	                "cv_order_candidates": list(self._TASK_CV_ORDER_RANGE),
   494	   294	                "target_rmse_k": float(target_rmse_k),
   495	   295	                "sensitivity_min": float(np.min(sensitivity)),
   496	   296	                "sensitivity_max": float(np.max(sensitivity)),
   497	   297	            },
   498	   298	            metadata={
   499	   299	                **_json_dict(metadata),
   500	   300	                "preprocessing": {
   501	   301	                    "downsample_target": self._TASK_DOWNSAMPLE_TARGET,
   502	   302	                    "input_sample_count": len(samples),
   503	   303	                    "output_sample_count": len(normalized_samples),
   504	   304	                },
   505	   305	            },
   506	   306	        )
   507	   307	        self._curves[curve.sensor_id] = curve
   508	   308	        return curve
   509	   309	
   510	   310	    def evaluate(self, sensor_id: str, raw_value: float, *, magnetic_field_T: float = 0.0) -> float:
   511	   311	        del magnetic_field_T
   512	   312	        curve = self._require_curve(sensor_id)
   513	   313	        return curve.evaluate(float(raw_value))
   514	   314	
   515	   315	    def voltage_to_temp(
   516	   316	        self,
   517	   317	        sensor_id: str,
   518	   318	        voltage: float,
   519	   319	        *,
   520	   320	        magnetic_field_T: float = 0.0,
   521	   321	    ) -> float:
   522	   322	        return self.evaluate(sensor_id, voltage, magnetic_field_T=magnetic_field_T)
   523	   323	
   524	   324	    def T_from_V(
   525	   325	        self,
   526	   326	        sensor_id: str,
   527	   327	        voltage: float,
   528	   328	        *,
   529	   329	        magnetic_field_T: float = 0.0,
   530	   330	    ) -> float:
   531	   331	        return self.voltage_to_temp(sensor_id, voltage, magnetic_field_T=magnetic_field_T)
   532	   332	
   533	   333	    def resistance_to_temp(
   534	   334	        self,
   535	   335	        sensor_id: str,
   536	   336	        resistance: float,
   537	   337	        *,
   538	   338	        magnetic_field_T: float = 0.0,
   539	   339	    ) -> float:
   540	   340	        return self.evaluate(sensor_id, resistance, magnetic_field_T=magnetic_field_T)
   541	   341	
   542	   342	    def save_curve(self, curve: CalibrationCurve, path: Path | None = None) -> Path:
   543	   343	        target = path or self._curve_path(curve.sensor_id, curve.curve_id)
   544	   344	        target.parent.mkdir(parents=True, exist_ok=True)
   545	   345	        from cryodaq.core.atomic_write import atomic_write_text
   546	   346	
   547	   347	        atomic_write_text(target, json.dumps(curve.to_payload(), ensure_ascii=False, indent=2))
   548	   348	        self._curves[curve.sensor_id] = curve
   549	   349	        self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
   550	   350	        self._write_index()
   551	   351	        return target
   552	   352	
   553	   353	    def load_curve(self, path: Path) -> CalibrationCurve:
   554	   354	        curve = CalibrationCurve.from_payload(json.loads(path.read_text(encoding="utf-8")))
   555	   355	        self._curves[curve.sensor_id] = curve
   556	   356	        self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
   557	   357	        return curve
   558	   358	
   559	   359	    def load_curves(self, curves_dir: Path) -> None:
   560	   360	        for path in sorted(curves_dir.glob("**/*.json")):
   561	   361	            self.load_curve(path)
   562	   362	        self._write_index()
   563	   363	
   564	   364	    def import_curve_json(self, path: Path) -> CalibrationCurve:
   565	   365	        return self.load_curve(path)
   566	   366	
   567	   367	    def import_curve_file(
   568	   368	        self,
   569	   369	        path: Path,
   570	   370	        *,
   571	   371	        sensor_id: str | None = None,
   572	   372	        channel_key: str | None = None,
   573	   373	        raw_unit: str = "sensor_unit",
   574	   374	        sensor_kind: str = "generic",
   575	   375	    ) -> CalibrationCurve:
   576	   376	        suffix = path.suffix.lower()
   577	   377	        if suffix == ".json":
   578	   378	            curve = self.import_curve_json(path)
   579	   379	        elif suffix == ".340":
   580	   380	            curve = self._import_curve_text(
   581	   381	                path,
   582	   382	                sensor_id=sensor_id,
   583	   383	                channel_key=channel_key,
   584	   384	                raw_unit=raw_unit,
   585	   385	                sensor_kind=sensor_kind,
   586	   386	                import_format="340",
   587	   387	            )
   588	   388	        else:
   589	   389	            raise ValueError(f"Unsupported calibration import format: {path.suffix}")
   590	   390	        if channel_key:
   591	   391	            self.assign_curve(
   592	   392	                sensor_id=curve.sensor_id,
   593	   393	                curve_id=curve.curve_id,
   594	   394	                channel_key=channel_key,
   595	   395	                runtime_apply_ready=False,
   596	   396	            )
   597	   397	        self._write_index()
   598	   398	        return curve
   599	   399	
   600	   400	    def export_curve_json(self, sensor_id: str, path: Path | None = None) -> Path:
   601	   401	        curve = self._require_curve(sensor_id)
   602	   402	        return self.save_curve(curve, path)
   603	   403	
   604	   404	    def export_curve_table(
   605	   405	        self,
   606	   406	        sensor_id: str,
   607	   407	        *,
   608	   408	        path: Path | None = None,
   609	   409	        points: int = 200,
   610	   410	    ) -> Path:
   611	   411	        curve = self._require_curve(sensor_id)
   612	   412	        target = path or self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
   613	   413	        target.parent.mkdir(parents=True, exist_ok=True)
   614	   414	        raw_min = curve.zones[0].raw_min
   615	   415	        raw_max = curve.zones[-1].raw_max
   616	   416	        raw_grid = np.linspace(raw_min, raw_max, max(points, 2))
   617	   417	        with target.open("w", encoding="utf-8", newline="") as handle:
   618	   418	            writer = csv.writer(handle)
   619	   419	            writer.writerow([f"raw_{curve.raw_unit}", "temperature_K"])
   620	   420	            for raw_value in raw_grid:
   621	   421	                writer.writerow([float(raw_value), curve.evaluate(float(raw_value))])
   622	   422	        return target
   623	   423	
   624	   424	    def export_curve_cof(
   625	   425	        self,
   626	   426	        sensor_id: str,
   627	   427	        *,
   628	   428	        path: Path | None = None,
   629	   429	    ) -> Path:
   630	   430	        """Export calibration curve as .cof (Chebyshev coefficients) format.
   631	   431	
   632	   432	        Unlike .340 which exports sampled breakpoints, .cof preserves the
   633	   433	        raw fit coefficients per zone. Portable: can be re-evaluated by
   634	   434	        any code with numpy.polynomial.chebyshev, no CryoDAQ schema
   635	   435	        dependency.
   636	   436	        """
   637	   437	        curve = self._require_curve(sensor_id)
   638	   438	        target = path or (self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof")
   639	   439	        target.parent.mkdir(parents=True, exist_ok=True)
   640	   440	        self._write_cof_export(target, curve)
   641	   441	        self._write_index()
   642	   442	        return target
   643	   443	
   644	   444	    def export_curve_340(
   645	   445	        self,
   646	   446	        sensor_id: str,
   647	   447	        *,
   648	   448	        path: Path | None = None,
   649	   449	        points: int = 200,
   650	   450	    ) -> Path:
   651	   451	        curve = self._require_curve(sensor_id)
   652	   452	        if self._exports_dir is None:
   653	   453	            raise RuntimeError("CalibrationStore base_dir is required for export.")
   654	   454	        target = path or self._curve_340_path(curve.sensor_id, curve.curve_id)
   655	   455	        target.parent.mkdir(parents=True, exist_ok=True)
   656	   456	        rows = self._export_rows(curve, points=max(points, 2))
   657	   457	        self._write_curve_text_export(target, curve, rows, format_name="340")
   658	   458	        self._write_index()
   659	   459	        return target
   660	   460	
   661	   461	    def get_curve_info(
   662	   462	        self, sensor_id: str | None = None, curve_id: str | None = None
   663	   463	    ) -> dict[str, Any]:
   664	   464	        curve = self._resolve_curve(sensor_id=sensor_id, curve_id=curve_id)
   665	   465	        return {
   666	   466	            "sensor_id": curve.sensor_id,
   667	   467	            "curve_id": curve.curve_id,
   668	   468	            "fit_timestamp": curve.fit_timestamp.isoformat(),
   669	   469	            "raw_unit": curve.raw_unit,
   670	   470	            "sensor_kind": curve.sensor_kind,
   671	   471	            "source_session_ids": list(curve.source_session_ids),
   672	   472	            "zones": [zone.to_payload() for zone in curve.zones],
   673	   473	            "metrics": dict(curve.metrics),
   674	   474	            "metadata": dict(curve.metadata),
   675	   475	            "artifacts": self.get_curve_artifacts(curve.sensor_id),
   676	   476	            "assignment": dict(self._assignments.get(curve.sensor_id) or {}),
   677	   477	        }
   678	   478	
   679	   479	    def get_curve_artifacts(self, sensor_id: str) -> dict[str, str]:
   680	   480	        curve = self._require_curve(sensor_id)
   681	   481	        return {
   682	   482	            "curve_path": str(self._curve_path(curve.sensor_id, curve.curve_id)),
   683	   483	            "table_path": str(
   684	   484	                self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
   685	   485	            ),
   686	   486	            "curve_cof_path": str(
   687	   487	                self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof"
   688	   488	            ),
   689	   489	            "curve_340_path": str(
   690	   490	                self._curve_340_path(curve.sensor_id, curve.curve_id) if self._exports_dir else ""
   691	   491	            ),
   692	   492	            "index_path": str(self._index_path) if self._index_path else "",
   693	   493	        }
   694	   494	
   695	   495	    def list_curves(self, *, sensor_id: str | None = None) -> list[dict[str, Any]]:
   696	   496	        curves = list(self._curves.values())
   697	   497	        if sensor_id:
   698	   498	            curves = [curve for curve in curves if curve.sensor_id == sensor_id]
   699	   499	        curves.sort(key=lambda item: item.fit_timestamp, reverse=True)
   700	   500	        return [self.get_curve_info(curve_id=curve.curve_id) for curve in curves]
   701	   501	
   702	   502	    def list_assignments(self) -> list[dict[str, Any]]:
   703	   503	        assignments = [dict(item) for item in self._assignments.values()]
   704	   504	        assignments.sort(key=lambda item: str(item.get("sensor_id", "")))
   705	   505	        return assignments
   706	   506	
   707	   507	    def get_runtime_settings(self) -> dict[str, Any]:
   708	   508	        assignments = []
   709	   509	        for item in self.list_assignments():
   710	   510	            channel_key = str(item.get("channel_key", "")).strip()
   711	   511	            resolution = self.resolve_runtime_policy(channel_key=channel_key) if channel_key else {}
   712	   512	            assignments.append(
   713	   513	                {
   714	   514	                    **item,
   715	   515	                    "resolution": resolution,
   716	   516	                }
   717	   517	            )
   718	   518	        return {
   719	   519	            "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
   720	   520	            "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
   721	   521	            "assignments": assignments,
   722	   522	        }
   723	   523	
   724	   524	    def set_runtime_global_mode(self, mode: str) -> dict[str, Any]:
   725	   525	        normalized = str(mode).strip().lower()
   726	   526	        if normalized not in {"off", "on"}:
   727	   527	            raise ValueError("Runtime calibration global_mode must be 'off' or 'on'.")
   728	   528	        self._runtime_settings["global_mode"] = normalized
   729	   529	        self._runtime_settings["updated_at"] = _utcnow().isoformat()
   730	   530	        self._write_index()
   731	   531	        return self.get_runtime_settings()
   732	   532	
   733	   533	    def set_runtime_channel_policy(
   734	   534	        self,
   735	   535	        *,
   736	   536	        channel_key: str,
   737	   537	        policy: str,
   738	   538	        sensor_id: str | None = None,
   739	   539	        curve_id: str | None = None,
   740	   540	        runtime_apply_ready: bool | None = None,
   741	   541	    ) -> dict[str, Any]:
   742	   542	        normalized_channel_key = str(channel_key).strip()
   743	   543	        if not normalized_channel_key:
   744	   544	            raise ValueError("channel_key is required.")
   745	   545	        normalized_policy = str(policy).strip().lower()
   746	   546	        if normalized_policy not in {"inherit", "off", "on"}:
   747	   547	            raise ValueError("Channel runtime policy must be 'inherit', 'off', or 'on'.")
   748	   548	        curve = self._resolve_curve(
   749	   549	            sensor_id=str(sensor_id or "").strip() or None,
   750	   550	            curve_id=str(curve_id or "").strip() or None,
   751	   551	        )
   752	   552	        assignment = self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
   753	   553	        assignment["channel_key"] = normalized_channel_key
   754	   554	        assignment["reading_mode_policy"] = normalized_policy
   755	   555	        if runtime_apply_ready is not None:
   756	   556	            assignment["runtime_apply_ready"] = bool(runtime_apply_ready)
   757	   557	        assignment["updated_at"] = _utcnow().isoformat()
   758	   558	        self._write_index()
   759	   559	        return {
   760	   560	            "assignment": dict(assignment),
   761	   561	            "resolution": self.resolve_runtime_policy(channel_key=normalized_channel_key),
   762	   562	        }
   763	   563	
   764	   564	    def resolve_runtime_policy(
   765	   565	        self,
   766	   566	        *,
   767	   567	        channel_key: str,
   768	   568	    ) -> dict[str, Any]:
   769	   569	        normalized_channel_key = str(channel_key).strip()
   770	   570	        if not normalized_channel_key:
   771	   571	            raise ValueError("channel_key is required.")
   772	   572	        global_mode = str(self._runtime_settings.get("global_mode", "off") or "off")
   773	   573	        assignment = next(
   774	   574	            (
   775	   575	                dict(item)
   776	   576	                for item in self._assignments.values()
   777	   577	                if str(item.get("channel_key", "")).strip() == normalized_channel_key
   778	   578	            ),
   779	   579	            None,
   780	   580	        )
   781	   581	        if global_mode == "off":
   782	   582	            return {
   783	   583	                "global_mode": global_mode,
   784	   584	                "channel_key": normalized_channel_key,
   785	   585	                "effective_mode": "off",
   786	   586	                "reading_mode": "krdg",
   787	   587	                "raw_source": "KRDG",
   788	   588	                "reason": "global_off",
   789	   589	                "assignment": assignment,
   790	   590	            }
   791	   591	        if assignment is None:
   792	   592	            return {
   793	   593	                "global_mode": global_mode,
   794	   594	                "channel_key": normalized_channel_key,
   795	   595	                "effective_mode": "off",
   796	   596	                "reading_mode": "krdg",
   797	   597	                "raw_source": "KRDG",
   798	   598	                "reason": "missing_assignment",
   799	   599	                "assignment": None,
   800	   600	            }
   801	   601	        policy = str(assignment.get("reading_mode_policy", "inherit") or "inherit").lower()
   802	   602	        if policy == "off":
   803	   603	            return {
   804	   604	                "global_mode": global_mode,
   805	   605	                "channel_key": normalized_channel_key,
   806	   606	                "effective_mode": "off",
   807	   607	                "reading_mode": "krdg",
   808	   608	                "raw_source": "KRDG",
   809	   609	                "reason": "channel_off",
   810	   610	                "assignment": assignment,
   811	   611	            }
   812	   612	        if not bool(assignment.get("runtime_apply_ready", False)):
   813	   613	            return {
   814	   614	                "global_mode": global_mode,
   815	   615	                "channel_key": normalized_channel_key,
   816	   616	                "effective_mode": "off",
   817	   617	                "reading_mode": "krdg",
   818	   618	                "raw_source": "KRDG",
   819	   619	                "reason": "not_runtime_ready",
   820	   620	                "assignment": assignment,
   821	   621	            }
   822	   622	        sensor_id = str(assignment.get("sensor_id", "")).strip()
   823	   623	        if not sensor_id or sensor_id not in self._curves:
   824	   624	            return {
   825	   625	                "global_mode": global_mode,
   826	   626	                "channel_key": normalized_channel_key,
   827	   627	                "effective_mode": "off",
   828	   628	                "reading_mode": "krdg",
   829	   629	                "raw_source": "KRDG",
   830	   630	                "reason": "missing_curve",
   831	   631	                "assignment": assignment,
   832	   632	            }
   833	   633	        curve = self._curves[sensor_id]
   834	   634	        return {
   835	   635	            "global_mode": global_mode,
   836	   636	            "channel_key": normalized_channel_key,
   837	   637	            "effective_mode": "on",
   838	   638	            "reading_mode": "curve",
   839	   639	            "raw_source": "SRDG",
   840	   640	            "reason": "curve_applied",
   841	   641	            "assignment": assignment,
   842	   642	            "curve": self.get_curve_info(curve_id=curve.curve_id),
   843	   643	        }
   844	   644	
   845	   645	    def assign_curve(
   846	   646	        self,
   847	   647	        *,
   848	   648	        sensor_id: str,
   849	   649	        curve_id: str | None = None,
   850	   650	        channel_key: str | None = None,
   851	   651	        runtime_apply_ready: bool = False,
   852	   652	        reading_mode_policy: str = "inherit",
   853	   653	    ) -> dict[str, Any]:
   854	   654	        curve = self._resolve_curve(sensor_id=sensor_id, curve_id=curve_id)
   855	   655	        normalized_policy = str(reading_mode_policy).strip().lower() or "inherit"
   856	   656	        if normalized_policy not in {"inherit", "off", "on"}:
   857	   657	            raise ValueError("reading_mode_policy must be 'inherit', 'off', or 'on'.")
   858	   658	        assignment = {
   859	   659	            "sensor_id": curve.sensor_id,
   860	   660	            "curve_id": curve.curve_id,
   861	   661	            "channel_key": str(channel_key).strip() if channel_key is not None else curve.sensor_id,
   862	   662	            "updated_at": _utcnow().isoformat(),
   863	   663	            "runtime_apply_ready": bool(runtime_apply_ready),
   864	   664	            "reading_mode_policy": normalized_policy,
   865	   665	        }
   866	   666	        self._assignments[curve.sensor_id] = assignment
   867	   667	        self._write_index()
   868	   668	        return dict(assignment)
   869	   669	
   870	   670	    def lookup_curve(
   871	   671	        self,
   872	   672	        *,
   873	   673	        sensor_id: str | None = None,
   874	   674	        channel_key: str | None = None,
   875	   675	    ) -> dict[str, Any]:
   876	   676	        assignment: dict[str, Any] | None = None
   877	   677	        if sensor_id:
   878	   678	            assignment = dict(self._assignments.get(sensor_id) or {})
   879	   679	        elif channel_key:
   880	   680	            assignment = next(
   881	   681	                (
   882	   682	                    dict(item)
   883	   683	                    for item in self._assignments.values()
   884	   684	                    if str(item.get("channel_key", "")).strip() == channel_key
   885	   685	                ),
   886	   686	                None,
   887	   687	            )
   888	   688	        if assignment is None:
   889	   689	            if sensor_id and sensor_id in self._curves:
   890	   690	                curve = self._curves[sensor_id]
   891	   691	                assignment = dict(
   892	   692	                    self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
   893	   693	                )
   894	   694	            else:
   895	   695	                raise KeyError("Calibration curve lookup did not match any sensor or channel.")
   896	   696	        curve = self._resolve_curve(
   897	   697	            sensor_id=str(assignment.get("sensor_id", "")),
   898	   698	            curve_id=str(assignment.get("curve_id", "")),
   899	   699	        )
   900	   700	        return {
   901	   701	            "assignment": assignment,
   902	   702	            "curve": self.get_curve_info(curve_id=curve.curve_id),
   903	   703	        }
   904	   704	
   905	   705	    def _require_curve(self, sensor_id: str) -> CalibrationCurve:
   906	   706	        if sensor_id not in self._curves:
   907	   707	            raise KeyError(f"Calibration curve for sensor '{sensor_id}' is not loaded.")
   908	   708	        return self._curves[sensor_id]
   909	   709	
   910	   710	    def _resolve_curve(
   911	   711	        self, *, sensor_id: str | None = None, curve_id: str | None = None
   912	   712	    ) -> CalibrationCurve:
   913	   713	        if sensor_id:
   914	   714	            return self._require_curve(sensor_id)
   915	   715	        if curve_id:
   916	   716	            for curve in self._curves.values():
   917	   717	                if curve.curve_id == curve_id:
   918	   718	                    return curve
   919	   719	        raise KeyError("Calibration curve could not be resolved.")
   920	   720	
   921	   721	    def _curve_directory(self, sensor_id: str, curve_id: str) -> Path:
   922	   722	        if self._curves_dir is None:
   923	   723	            raise RuntimeError("CalibrationStore base_dir is required for artifact export.")
   924	   724	        return self._curves_dir / _safe_path_fragment(sensor_id) / _safe_path_fragment(curve_id)
   925	   725	
   926	   726	    def _curve_path(self, sensor_id: str, curve_id: str) -> Path:
   927	   727	        return self._curve_directory(sensor_id, curve_id) / "curve.json"
   928	   728	
   929	   729	    def _curve_340_path(self, sensor_id: str, curve_id: str) -> Path:
   930	   730	        if self._exports_dir is None:
   931	   731	            raise RuntimeError("CalibrationStore base_dir is required for export.")
   932	   732	        return (
   933	   733	            self._exports_dir
   934	   734	            / _safe_path_fragment(sensor_id)
   935	   735	            / _safe_path_fragment(curve_id)
   936	   736	            / "curve.340"
   937	   737	        )
   938	   738	
   939	   739	    def _load_index(self) -> None:
   940	   740	        if self._index_path is None or not self._index_path.exists():
   941	   741	            return
   942	   742	        payload = yaml.safe_load(self._index_path.read_text(encoding="utf-8")) or {}
   943	   743	        runtime = payload.get("runtime", {})
   944	   744	        if isinstance(runtime, dict):
   945	   745	            global_mode = str(runtime.get("global_mode", "off") or "off").strip().lower()
   946	   746	            if global_mode in {"off", "on"}:
   947	   747	                self._runtime_settings["global_mode"] = global_mode
   948	   748	            self._runtime_settings["updated_at"] = str(runtime.get("updated_at", "")).strip()
   949	   749	        assignments = payload.get("assignments", [])
   950	   750	        if isinstance(assignments, list):
   951	   751	            for item in assignments:
   952	   752	                if not isinstance(item, dict):
   953	   753	                    continue
   954	   754	                sensor_id = str(item.get("sensor_id", "")).strip()
   955	   755	                if sensor_id:
   956	   756	                    self._assignments[sensor_id] = {
   957	   757	                        "sensor_id": sensor_id,
   958	   758	                        "curve_id": str(item.get("curve_id", "")).strip(),
   959	   759	                        "channel_key": str(item.get("channel_key", sensor_id)).strip() or sensor_id,
   960	   760	                        "updated_at": str(item.get("updated_at", "")).strip(),
   961	   761	                        "runtime_apply_ready": bool(item.get("runtime_apply_ready", False)),
   962	   762	                        "reading_mode_policy": str(
   963	   763	                            item.get("reading_mode_policy", "inherit") or "inherit"
   964	   764	                        )
   965	   765	                        .strip()
   966	   766	                        .lower()
   967	   767	                        or "inherit",
   968	   768	                    }
   969	   769	
   970	   770	    def _write_index(self) -> None:
   971	   771	        if self._index_path is None:
   972	   772	            return
   973	   773	        self._index_path.parent.mkdir(parents=True, exist_ok=True)
   974	   774	        payload = {
   975	   775	            "schema_version": 1,
   976	   776	            "generated_at": _utcnow().isoformat(),
   977	   777	            "runtime": {
   978	   778	                "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
   979	   779	                "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
   980	   780	            },
   981	   781	            "curves": [
   982	   782	                {
   983	   783	                    "sensor_id": curve.sensor_id,
   984	   784	                    "curve_id": curve.curve_id,
   985	   785	                    "fit_timestamp": curve.fit_timestamp.isoformat(),
   986	   786	                    "raw_unit": curve.raw_unit,
   987	   787	                    "sensor_kind": curve.sensor_kind,
   988	   788	                    "curve_path": str(self._curve_path(curve.sensor_id, curve.curve_id)),
   989	   789	                    "table_path": str(
   990	   790	                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
   991	   791	                    ),
   992	   792	                    "curve_cof_path": str(
   993	   793	                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof"
   994	   794	                    ),
   995	   795	                    "curve_340_path": str(
   996	   796	                        self._curve_340_path(curve.sensor_id, curve.curve_id)
   997	   797	                        if self._exports_dir
   998	   798	                        else ""
   999	   799	                    ),
  1000	   800	                    "source_session_ids": list(curve.source_session_ids),
  1001	   801	                }
  1002	   802	                for curve in sorted(
  1003	   803	                    self._curves.values(), key=lambda item: item.fit_timestamp, reverse=True
  1004	   804	                )
  1005	   805	            ],
  1006	   806	            "assignments": [dict(item) for item in self.list_assignments()],
  1007	   807	        }
  1008	   808	        from cryodaq.core.atomic_write import atomic_write_text
  1009	   809	
  1010	   810	        atomic_write_text(
  1011	   811	            self._index_path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
  1012	   812	        )
  1013	   813	
  1014	   814	    def _ensure_assignment(self, *, sensor_id: str, curve_id: str) -> dict[str, Any]:
  1015	   815	        existing = self._assignments.get(sensor_id)
  1016	   816	        if existing:
  1017	   817	            existing["curve_id"] = curve_id
  1018	   818	            existing["updated_at"] = _utcnow().isoformat()
  1019	   819	            return existing
  1020	   820	        assignment = {
  1021	   821	            "sensor_id": sensor_id,
  1022	   822	            "curve_id": curve_id,
  1023	   823	            "channel_key": sensor_id,
  1024	   824	            "updated_at": _utcnow().isoformat(),
  1025	   825	            "runtime_apply_ready": False,
  1026	   826	            "reading_mode_policy": "inherit",
  1027	   827	        }
  1028	   828	        self._assignments[sensor_id] = assignment
  1029	   829	        return assignment
  1030	   830	
  1031	   831	    def _export_rows(self, curve: CalibrationCurve, *, points: int) -> list[tuple[float, float]]:
  1032	   832	        dense_points = max(points * 24, 2000)
  1033	   833	        raw_min = curve.zones[0].raw_min
  1034	   834	        raw_max = curve.zones[-1].raw_max
  1035	   835	        raw_grid = np.linspace(raw_min, raw_max, dense_points, dtype=float)
  1036	   836	        temperatures = np.array(
  1037	   837	            [curve.evaluate(float(raw_value)) for raw_value in raw_grid], dtype=float
  1038	   838	        )
  1039	   839	        order = np.argsort(temperatures)
  1040	   840	        sorted_temperatures = temperatures[order]
  1041	   841	        sorted_raw = raw_grid[order]
  1042	   842	        sorted_temperatures, sorted_raw = self._collapse_duplicate_axis(
  1043	   843	            sorted_temperatures, sorted_raw
  1044	   844	        )
  1045	   845	        indices = self._adaptive_breakpoint_indices(sorted_temperatures, sorted_raw, max(points, 2))
  1046	   846	        rows = [(float(sorted_temperatures[index]), float(sorted_raw[index])) for index in indices]
  1047	   847	        deduped: list[tuple[float, float]] = []
  1048	   848	        seen: set[tuple[float, float]] = set()
  1049	   849	        for item in rows:
  1050	   850	            key = (round(item[0], 9), round(item[1], 9))
  1051	   851	            if key in seen:
  1052	   852	                continue
  1053	   853	            seen.add(key)
  1054	   854	            deduped.append(item)
  1055	   855	        return deduped[: max(points, 2)]
  1056	   856	
  1057	   857	    def _write_curve_text_export(
  1058	   858	        self,
  1059	   859	        path: Path,
  1060	   860	        curve: CalibrationCurve,
  1061	   861	        rows: list[tuple[float, float]],
  1062	   862	        *,
  1063	   863	        format_name: str,
  1064	   864	    ) -> None:
  1065	   865	        with path.open("w", encoding="utf-8", newline="") as handle:
  1066	   866	            handle.write(f"# CryoDAQ calibration curve export .{format_name}\n")
  1067	   867	            handle.write(f"# sensor_id: {curve.sensor_id}\n")
  1068	   868	            handle.write(f"# curve_id: {curve.curve_id}\n")
  1069	   869	            handle.write(f"# raw_unit: {curve.raw_unit}\n")
  1070	   870	            handle.write("# columns: temperature_K, sensor_raw\n")
  1071	   871	            writer = csv.writer(handle)
  1072	   872	            for temperature_k, raw_value in rows:
  1073	   873	                writer.writerow([f"{temperature_k:.9g}", f"{raw_value:.9g}"])
  1074	   874	
  1075	   875	    def _write_cof_export(self, path: Path, curve: CalibrationCurve) -> None:
  1076	   876	        """Write .cof format: header + per-zone raw Chebyshev coefficients."""
  1077	   877	        from cryodaq.core.atomic_write import atomic_write_text
  1078	   878	
  1079	   879	        lines: list[str] = []
  1080	   880	        lines.append("# CryoDAQ calibration curve export .cof")
  1081	   881	        lines.append(f"# sensor_id: {curve.sensor_id}")
  1082	   882	        lines.append(f"# curve_id: {curve.curve_id}")
  1083	   883	        lines.append(f"# raw_unit: {curve.raw_unit}")
  1084	   884	        lines.append(f"# fit_timestamp: {curve.fit_timestamp.isoformat()}")
  1085	   885	        lines.append(
  1086	   886	            "# format: Chebyshev T_n(x), x = 2*(raw - raw_min)/(raw_max - raw_min) - 1"
  1087	   887	        )
  1088	   888	        lines.append(f"# zone_count: {len(curve.zones)}")
  1089	   889	        lines.append("")
  1090	   890	        for index, zone in enumerate(curve.zones, start=1):
  1091	   891	            lines.append(f"[zone {index}]")
  1092	   892	            lines.append(f"raw_min: {zone.raw_min:.12g}")
  1093	   893	            lines.append(f"raw_max: {zone.raw_max:.12g}")
  1094	   894	            lines.append(f"order: {zone.order}")
  1095	   895	            coefficients = ", ".join(f"{value:.12g}" for value in zone.coefficients)
  1096	   896	            lines.append(f"coefficients: {coefficients}")
  1097	   897	            lines.append(f"# rmse_k: {zone.rmse_k:.6g}")
  1098	   898	            lines.append(f"# max_abs_error_k: {zone.max_abs_error_k:.6g}")
  1099	   899	            lines.append(f"# point_count: {zone.point_count}")
  1100	   900	            lines.append("")
  1101	   901	        atomic_write_text(path, "\n".join(lines))
  1102	   902	
  1103	   903	    def _import_curve_text(
  1104	   904	        self,
  1105	   905	        path: Path,
  1106	   906	        *,
  1107	   907	        sensor_id: str | None,
  1108	   908	        channel_key: str | None,
  1109	   909	        raw_unit: str,
  1110	   910	        sensor_kind: str,
  1111	   911	        import_format: str,
  1112	   912	    ) -> CalibrationCurve:
  1113	   913	        rows: list[tuple[float, float]] = []
  1114	   914	        for raw_line in path.read_text(encoding="utf-8").splitlines():
  1115	   915	            line = raw_line.strip()
  1116	   916	            if not line or line.startswith("#"):
  1117	   917	                continue
  1118	   918	            line = line.replace(",", " ")
  1119	   919	            parts = [item for item in line.split() if item]
  1120	   920	            if len(parts) < 2:
  1121	   921	                continue
  1122	   922	            try:
  1123	   923	                temperature_k = float(parts[0])
  1124	   924	                raw_value = float(parts[1])
  1125	   925	            except ValueError:
  1126	   926	                continue
  1127	   927	            rows.append((temperature_k, raw_value))
  1128	   928	        if len(rows) < 4:
  1129	   929	            raise ValueError(
  1130	   930	                f"Calibration file '{path.name}' does not contain enough numeric pairs."
  1131	   931	            )
  1132	   932	        resolved_sensor_id = (sensor_id or (channel_key or path.stem)).strip()
  1133	   933	        samples = [
  1134	   934	            CalibrationSample(
  1135	   935	                timestamp=_utcnow(),
  1136	   936	                reference_channel="import",
  1137	   937	                reference_temperature=temperature_k,
  1138	   938	                sensor_channel=channel_key or resolved_sensor_id,
  1139	   939	                sensor_raw_value=raw_value,
  1140	   940	                metadata={"import_format": import_format, "source_path": str(path)},
  1141	   941	            )
  1142	   942	            for temperature_k, raw_value in sorted(rows, key=lambda item: item[1])
  1143	   943	        ]
  1144	   944	        curve = self.fit_curve(
  1145	   945	            resolved_sensor_id,
  1146	   946	            samples,
  1147	   947	            raw_unit=raw_unit,
  1148	   948	            sensor_kind=sensor_kind,
  1149	   949	            source_session_ids=(),
  1150	   950	            max_zones=3,
  1151	   951	            min_points_per_zone=4,
  1152	   952	            max_order=12,
  1153	   953	            target_rmse_k=0.05,
  1154	   954	            metadata={
  1155	   955	                "import_format": import_format,
  1156	   956	                "import_source_path": str(path),
  1157	   957	                "channel_key": channel_key or resolved_sensor_id,
  1158	   958	            },
  1159	   959	        )
  1160	   960	        self.save_curve(curve)
  1161	   961	        if import_format == "340":
  1162	   962	            self.export_curve_340(curve.sensor_id)
  1163	   963	        return curve
  1164	   964	
  1165	   965	    def _preprocess_samples(
  1166	   966	        self,
  1167	   967	        samples: list[CalibrationSample] | tuple[CalibrationSample, ...],
  1168	   968	        *,
  1169	   969	        downsample_target: int,
  1170	   970	    ) -> tuple[CalibrationSample, ...]:
  1171	   971	        rows: list[tuple[float, float, CalibrationSample]] = []
  1172	   972	        for sample in samples:
  1173	   973	            temperature = float(sample.reference_temperature)
  1174	   974	            raw_value = float(sample.sensor_raw_value)
  1175	   975	            if not math.isfinite(temperature) or not math.isfinite(raw_value):
  1176	   976	                continue
  1177	   977	            rows.append((temperature, raw_value, sample))
  1178	   978	        if len(rows) < 4:
  1179	   979	            raise ValueError("Not enough finite calibration samples for fitting.")
  1180	   980	        rows.sort(key=lambda item: (item[0], item[1]))
  1181	   981	
  1182	   982	        aggregated: list[CalibrationSample] = []
  1183	   983	        index = 0
  1184	   984	        while index < len(rows):
  1185	   985	            temperature = rows[index][0]
  1186	   986	            bucket = [rows[index]]
  1187	   987	            index += 1
  1188	   988	            while index < len(rows) and math.isclose(
  1189	   989	                rows[index][0], temperature, rel_tol=0.0, abs_tol=1e-9
  1190	   990	            ):
  1191	   991	                bucket.append(rows[index])
  1192	   992	                index += 1
  1193	   993	            template = bucket[-1][2]
  1194	   994	            aggregated.append(
  1195	   995	                CalibrationSample(
  1196	   996	                    timestamp=template.timestamp,
  1197	   997	                    reference_channel=template.reference_channel,
  1198	   998	                    reference_temperature=float(np.mean([item[0] for item in bucket])),
  1199	   999	                    sensor_channel=template.sensor_channel,
  1200	  1000	                    sensor_raw_value=float(np.mean([item[1] for item in bucket])),
  1201	  1001	                    reference_instrument_id=template.reference_instrument_id,
  1202	  1002	                    sensor_instrument_id=template.sensor_instrument_id,
  1203	  1003	                    experiment_id=template.experiment_id,
  1204	  1004	                    metadata=dict(template.metadata),
  1205	  1005	                )
  1206	  1006	            )
  1207	  1007	        if len(aggregated) <= downsample_target:
  1208	  1008	            return tuple(aggregated)
  1209	  1009	        return tuple(
  1210	  1010	            self._downsample_uniform_temperature(aggregated, downsample_target=downsample_target)
  1211	  1011	        )
  1212	  1012	
  1213	  1013	    def _downsample_uniform_temperature(
  1214	  1014	        self,
  1215	  1015	        samples: list[CalibrationSample] | tuple[CalibrationSample, ...],
  1216	  1016	        *,
  1217	  1017	        downsample_target: int,
  1218	  1018	    ) -> list[CalibrationSample]:
  1219	  1019	        ordered = sorted(samples, key=lambda item: item.reference_temperature)
  1220	  1020	        temperatures = np.array([item.reference_temperature for item in ordered], dtype=float)
  1221	  1021	        if len(ordered) <= downsample_target or np.ptp(temperatures) <= 0:
  1222	  1022	            return list(ordered)
  1223	  1023	        edges = np.linspace(float(temperatures[0]), float(temperatures[-1]), downsample_target + 1)
  1224	  1024	        downsampled: list[CalibrationSample] = []
  1225	  1025	        start = 0
  1226	  1026	        for bin_index in range(downsample_target):
  1227	  1027	            lower = edges[bin_index]
  1228	  1028	            upper = edges[bin_index + 1]
  1229	  1029	            bucket: list[CalibrationSample] = []
  1230	  1030	            while start < len(ordered):
  1231	  1031	                current = ordered[start]
  1232	  1032	                value = current.reference_temperature
  1233	  1033	                if value < lower and bin_index > 0:
  1234	  1034	                    start += 1
  1235	  1035	                    continue
  1236	  1036	                if (value < upper) or (bin_index == downsample_target - 1 and value <= upper):
  1237	  1037	                    bucket.append(current)
  1238	  1038	                    start += 1
  1239	  1039	                    continue
  1240	  1040	                break
  1241	  1041	            if not bucket:
  1242	  1042	                nearest_index = int(np.searchsorted(temperatures, (lower + upper) / 2.0))
  1243	  1043	                nearest_index = max(0, min(nearest_index, len(ordered) - 1))
  1244	  1044	                bucket = [ordered[nearest_index]]
  1245	  1045	            template = bucket[len(bucket) // 2]
  1246	  1046	            downsampled.append(
  1247	  1047	                CalibrationSample(
  1248	  1048	                    timestamp=template.timestamp,
  1249	  1049	                    reference_channel=template.reference_channel,
  1250	  1050	                    reference_temperature=float(
  1251	  1051	                        np.mean([item.reference_temperature for item in bucket])
  1252	  1052	                    ),
  1253	  1053	                    sensor_channel=template.sensor_channel,
  1254	  1054	                    sensor_raw_value=float(np.mean([item.sensor_raw_value for item in bucket])),
  1255	  1055	                    reference_instrument_id=template.reference_instrument_id,
  1256	  1056	                    sensor_instrument_id=template.sensor_instrument_id,
  1257	  1057	                    experiment_id=template.experiment_id,
  1258	  1058	                    metadata=dict(template.metadata),
  1259	  1059	                )
  1260	  1060	            )
  1261	  1061	        downsampled.sort(key=lambda item: item.reference_temperature)
  1262	  1062	        return downsampled
  1263	  1063	
  1264	  1064	    def _detect_zone_slices(
  1265	  1065	        self,
  1266	  1066	        temperatures: np.ndarray,
  1267	  1067	        raw_values: np.ndarray,
  1268	  1068	        *,
  1269	  1069	        max_zones: int,
  1270	  1070	        min_points_per_zone: int,
  1271	  1071	        max_order: int,
  1272	  1072	    ) -> list[slice]:
  1273	  1073	        if len(raw_values) < (min_points_per_zone * 2) or max_zones <= 1:
  1274	  1074	            return [slice(0, len(raw_values))]
  1275	  1075	        dvdt = np.gradient(raw_values, temperatures)
  1276	  1076	        dvdt = self._smooth_series(dvdt)
  1277	  1077	        magnitude = np.log10(np.maximum(np.abs(dvdt), 1e-12))
  1278	  1078	        change_score = np.abs(np.gradient(magnitude, temperatures))
  1279	  1079	        curvature = np.abs(np.gradient(dvdt, temperatures))
  1280	  1080	        combined_score = change_score + (0.25 * curvature / max(float(np.max(curvature)), 1e-12))
  1281	  1081	        candidate_order = np.argsort(combined_score)[::-1]
  1282	  1082	        boundaries: list[int] = []
  1283	  1083	        for index in candidate_order:
  1284	  1084	            if index < min_points_per_zone or index > len(raw_values) - min_points_per_zone:
  1285	  1085	                continue
  1286	  1086	            if any(abs(index - boundary) < min_points_per_zone for boundary in boundaries):
  1287	  1087	                continue
  1288	  1088	            refined = self._refine_boundary_index(
  1289	  1089	                temperatures,
  1290	  1090	                raw_values,
  1291	  1091	                candidate_index=int(index),
  1292	  1092	                min_points_per_zone=min_points_per_zone,
  1293	  1093	                max_order=max_order,
  1294	  1094	            )
  1295	  1095	            if any(abs(refined - boundary) < min_points_per_zone for boundary in boundaries):
  1296	  1096	                continue
  1297	  1097	            boundaries.append(refined)
  1298	  1098	            if len(boundaries) >= max_zones - 1:
  1299	  1099	                break
  1300	  1100	        cuts = sorted(boundaries)
  1301	  1101	        if not cuts:
  1302	  1102	            return [slice(0, len(raw_values))]
  1303	  1103	        slices: list[slice] = []
  1304	  1104	        start = 0
  1305	  1105	        for stop in cuts:
  1306	  1106	            if stop - start < min_points_per_zone:
  1307	  1107	                continue
  1308	  1108	            slices.append(slice(start, stop))
  1309	  1109	            start = stop
  1310	  1110	        if len(raw_values) - start < min_points_per_zone and slices:
  1311	  1111	            last = slices.pop()
  1312	  1112	            slices.append(slice(last.start, len(raw_values)))
  1313	  1113	        else:
  1314	  1114	            slices.append(slice(start, len(raw_values)))
  1315	  1115	        return slices
  1316	  1116	
  1317	  1117	    def _fit_zone_slices(
  1318	  1118	        self,
  1319	  1119	        temperatures: np.ndarray,
  1320	  1120	        raw_values: np.ndarray,
  1321	  1121	        *,
  1322	  1122	        zone_slices: list[slice],
  1323	  1123	        max_order: int,
  1324	  1124	        target_rmse_k: float,
  1325	  1125	    ) -> list[CalibrationZone]:
  1326	  1126	        zones = [
  1327	  1127	            self._fit_zone_cv(
  1328	  1128	                raw_values[zone_slice],
  1329	  1129	                temperatures[zone_slice],
  1330	  1130	                max_order=max_order,
  1331	  1131	            )
  1332	  1132	            for zone_slice in zone_slices
  1333	  1133	        ]
  1334	  1134	        zones.sort(key=lambda item: item.raw_min)
  1335	  1135	        return zones
  1336	  1136	
  1337	  1137	    def _fit_zone_cv(
  1338	  1138	        self,
  1339	  1139	        raw_values: np.ndarray,
  1340	  1140	        temperatures: np.ndarray,
  1341	  1141	        *,
  1342	  1142	        max_order: int,
  1343	  1143	    ) -> CalibrationZone:
  1344	  1144	        ordered_indices = np.argsort(raw_values)
  1345	  1145	        ordered_raw = np.asarray(raw_values[ordered_indices], dtype=float)
  1346	  1146	        ordered_temperatures = np.asarray(temperatures[ordered_indices], dtype=float)
  1347	  1147	        ordered_raw, ordered_temperatures = self._collapse_duplicate_axis(
  1348	  1148	            ordered_raw, ordered_temperatures
  1349	  1149	        )
  1350	  1150	        if len(ordered_raw) < 2 or np.ptp(ordered_raw) <= 0:
  1351	  1151	            raise RuntimeError("Failed to fit calibration zone: degenerate input range.")
  1352	  1152	
  1353	  1153	        task_candidates = [
  1354	  1154	            order
  1355	  1155	            for order in self._TASK_CV_ORDER_RANGE
  1356	  1156	            if order <= max_order and order < len(ordered_raw)
  1357	  1157	        ]
  1358	  1158	        if task_candidates:
  1359	  1159	            candidate_orders = task_candidates
  1360	  1160	        else:
  1361	  1161	            fallback_max = min(max_order, max(1, len(ordered_raw) - 1))
  1362	  1162	            candidate_orders = list(range(1, fallback_max + 1))
  1363	  1163	
  1364	  1164	        best_cv_rmse: float | None = None
  1365	  1165	        best_zone: CalibrationZone | None = None
  1366	  1166	        for order in candidate_orders:
  1367	  1167	            try:
  1368	  1168	                cv_rmse = self._cross_validated_rmse(ordered_raw, ordered_temperatures, order=order)
  1369	  1169	                zone = self._build_zone(ordered_raw, ordered_temperatures, order=order)
  1370	  1170	            except RuntimeError:
  1371	  1171	                continue
  1372	  1172	            score = (cv_rmse, zone.rmse_k, order)
  1373	  1173	            if best_cv_rmse is None or score < (best_cv_rmse, best_zone.rmse_k, best_zone.order):  # type: ignore[union-attr]
  1374	  1174	                best_cv_rmse = cv_rmse
  1375	  1175	                best_zone = zone
  1376	  1176	        if best_zone is None:
  1377	  1177	            raise RuntimeError("Failed to fit calibration zone.")
  1378	  1178	        return best_zone
  1379	  1179	
  1380	  1180	    def _build_zone(
  1381	  1181	        self,
  1382	  1182	        raw_values: np.ndarray,
  1383	  1183	        temperatures: np.ndarray,
  1384	  1184	        *,
  1385	  1185	        order: int,
  1386	  1186	    ) -> CalibrationZone:
  1387	  1187	        domain = [float(np.min(raw_values)), float(np.max(raw_values))]
  1388	  1188	        with warnings.catch_warnings():
  1389	  1189	            warnings.simplefilter("error", np.exceptions.RankWarning)
  1390	  1190	            try:
  1391	  1191	                fit = cheb.Chebyshev.fit(raw_values, temperatures, deg=order, domain=domain)
  1392	  1192	            except np.exceptions.RankWarning as exc:
  1393	  1193	                raise RuntimeError("Calibration zone fit is numerically unstable.") from exc
  1394	  1194	        predictions = fit(raw_values)
  1395	  1195	        residuals = predictions - temperatures
  1396	  1196	        return CalibrationZone(
  1397	  1197	            raw_min=float(np.min(raw_values)),
  1398	  1198	            raw_max=float(np.max(raw_values)),
  1399	  1199	            order=order,
  1400	  1200	            coefficients=tuple(float(value) for value in fit.coef),
  1401	  1201	            rmse_k=float(math.sqrt(np.mean(np.square(residuals)))),
  1402	  1202	            max_abs_error_k=float(np.max(np.abs(residuals))),
  1403	  1203	            point_count=int(len(raw_values)),
  1404	  1204	        )
  1405	  1205	
  1406	  1206	    def _cross_validated_rmse(
  1407	  1207	        self,
  1408	  1208	        raw_values: np.ndarray,
  1409	  1209	        temperatures: np.ndarray,
  1410	  1210	        *,
  1411	  1211	        order: int,
  1412	  1212	    ) -> float:
  1413	  1213	        sample_count = len(raw_values)
  1414	  1214	        if sample_count <= order + 2:
  1415	  1215	            zone = self._build_zone(raw_values, temperatures, order=order)
  1416	  1216	            return zone.rmse_k
  1417	  1217	        folds = min(5, max(2, sample_count // max(order + 1, 4)))
  1418	  1218	        indices = np.arange(sample_count)
  1419	  1219	        fold_indices = [
  1420	  1220	            indices[offset::folds] for offset in range(folds) if len(indices[offset::folds]) > 0
  1421	  1221	        ]
  1422	  1222	        rmses: list[float] = []
  1423	  1223	        for fold in fold_indices:
  1424	  1224	            mask = np.ones(sample_count, dtype=bool)
  1425	  1225	            mask[fold] = False
  1426	  1226	            train_raw = raw_values[mask]
  1427	  1227	            train_temperatures = temperatures[mask]
  1428	  1228	            if len(train_raw) <= order:
  1429	  1229	                continue
  1430	  1230	            zone = self._build_zone(train_raw, train_temperatures, order=order)
  1431	  1231	            predictions = np.array(
  1432	  1232	                [zone.evaluate(float(value)) for value in raw_values[fold]], dtype=float
  1433	  1233	            )
  1434	  1234	            residuals = predictions - temperatures[fold]
  1435	  1235	            rmses.append(float(math.sqrt(np.mean(np.square(residuals)))))
  1436	  1236	        if not rmses:
  1437	  1237	            zone = self._build_zone(raw_values, temperatures, order=order)
  1438	  1238	            return zone.rmse_k
  1439	  1239	        return float(np.mean(rmses))
  1440	  1240	
  1441	  1241	    def _evaluate_zones(self, zones: list[CalibrationZone], raw_value: float) -> float:
  1442	  1242	        for zone in zones:
  1443	  1243	            if zone.contains(float(raw_value)):
  1444	  1244	                return zone.evaluate(float(raw_value))
  1445	  1245	        if raw_value < zones[0].raw_min:
  1446	  1246	            return zones[0].evaluate(float(raw_value))
  1447	  1247	        return zones[-1].evaluate(float(raw_value))
  1448	  1248	
  1449	  1249	    def _smooth_series(self, values: np.ndarray) -> np.ndarray:
  1450	  1250	        if len(values) < 5:
  1451	  1251	            return np.asarray(values, dtype=float)
  1452	  1252	        window = min(len(values) if len(values) % 2 == 1 else len(values) - 1, 11)
  1453	  1253	        if window < 3:
  1454	  1254	            return np.asarray(values, dtype=float)
  1455	  1255	        kernel = np.ones(window, dtype=float) / float(window)
  1456	  1256	        padded = np.pad(values, (window // 2, window // 2), mode="edge")
  1457	  1257	        return np.convolve(padded, kernel, mode="valid")
  1458	  1258	
  1459	  1259	    def _adaptive_breakpoint_indices(
  1460	  1260	        self,
  1461	  1261	        temperatures: np.ndarray,
  1462	  1262	        raw_values: np.ndarray,
  1463	  1263	        points: int,
  1464	  1264	    ) -> list[int]:
  1465	  1265	        if len(temperatures) <= points:
  1466	  1266	            return list(range(len(temperatures)))
  1467	  1267	        first = np.gradient(raw_values, temperatures)
  1468	  1268	        second = np.gradient(first, temperatures)
  1469	  1269	        weights = 1.0 + np.abs(second)
  1470	  1270	        cumulative = np.cumsum(weights)
  1471	  1271	        cumulative /= cumulative[-1]
  1472	  1272	        targets = np.linspace(0.0, 1.0, points)
  1473	  1273	        indices = np.searchsorted(cumulative, targets, side="left")
  1474	  1274	        indices = np.clip(indices, 0, len(temperatures) - 1)
  1475	  1275	        indices[0] = 0
  1476	  1276	        indices[-1] = len(temperatures) - 1
  1477	  1277	        deduped = sorted({int(index) for index in indices})
  1478	  1278	        while len(deduped) < points:
  1479	  1279	            for candidate in np.linspace(0, len(temperatures) - 1, points, dtype=int):
  1480	  1280	                deduped.append(int(candidate))
  1481	  1281	                deduped = sorted(set(deduped))
  1482	  1282	                if len(deduped) >= points:
  1483	  1283	                    break
  1484	  1284	        return deduped[:points]
  1485	  1285	
  1486	  1286	    def _refine_boundary_index(
  1487	  1287	        self,
  1488	  1288	        temperatures: np.ndarray,
  1489	  1289	        raw_values: np.ndarray,
  1490	  1290	        *,
  1491	  1291	        candidate_index: int,
  1492	  1292	        min_points_per_zone: int,
  1493	  1293	        max_order: int,
  1494	  1294	    ) -> int:
  1495	  1295	        search_radius = max(3, min_points_per_zone // 2)
  1496	  1296	        start = max(min_points_per_zone, candidate_index - search_radius)
  1497	  1297	        stop = min(len(raw_values) - min_points_per_zone, candidate_index + search_radius)
  1498	  1298	        best_index = candidate_index
  1499	  1299	        best_score: tuple[float, float] | None = None
  1500	  1300	        for index in range(start, stop + 1):
  1501	  1301	            try:
  1502	  1302	                left_zone = self._fit_zone_cv(
  1503	  1303	                    raw_values[:index], temperatures[:index], max_order=max_order
  1504	  1304	                )
  1505	  1305	                right_zone = self._fit_zone_cv(
  1506	  1306	                    raw_values[index:], temperatures[index:], max_order=max_order
  1507	  1307	                )
  1508	  1308	            except RuntimeError:
  1509	  1309	                continue
  1510	  1310	            weighted_rmse = math.sqrt(
  1511	  1311	                (
  1512	  1312	                    (left_zone.rmse_k**2) * left_zone.point_count
  1513	  1313	                    + (right_zone.rmse_k**2) * right_zone.point_count
  1514	  1314	                )
  1515	  1315	                / max(left_zone.point_count + right_zone.point_count, 1)
  1516	  1316	            )
  1517	  1317	            score = (weighted_rmse, max(left_zone.max_abs_error_k, right_zone.max_abs_error_k))
  1518	  1318	            if best_score is None or score < best_score:
  1519	  1319	                best_score = score
  1520	  1320	                best_index = index
  1521	  1321	        return best_index
  1522	  1322	
  1523	  1323	    def _collapse_duplicate_axis(
  1524	  1324	        self,
  1525	  1325	        primary: np.ndarray,
  1526	  1326	        secondary: np.ndarray,
  1527	  1327	    ) -> tuple[np.ndarray, np.ndarray]:
  1528	  1328	        if len(primary) < 2:
  1529	  1329	            return np.asarray(primary, dtype=float), np.asarray(secondary, dtype=float)
  1530	  1330	        rows = sorted(
  1531	  1331	            zip(primary.tolist(), secondary.tolist(), strict=False), key=lambda item: item[0]
  1532	  1332	        )
  1533	  1333	        unique_primary: list[float] = []
  1534	  1334	        unique_secondary: list[float] = []
  1535	  1335	        bucket_primary = [rows[0][0]]
  1536	  1336	        bucket_secondary = [rows[0][1]]
  1537	  1337	        for current_primary, current_secondary in rows[1:]:
  1538	  1338	            if math.isclose(current_primary, bucket_primary[-1], rel_tol=0.0, abs_tol=1e-12):
  1539	  1339	                bucket_primary.append(current_primary)
  1540	  1340	                bucket_secondary.append(current_secondary)
  1541	  1341	                continue
  1542	  1342	            unique_primary.append(float(np.mean(bucket_primary)))
  1543	  1343	            unique_secondary.append(float(np.mean(bucket_secondary)))
  1544	  1344	            bucket_primary = [current_primary]
  1545	  1345	            bucket_secondary = [current_secondary]
  1546	  1346	        unique_primary.append(float(np.mean(bucket_primary)))
  1547	  1347	        unique_secondary.append(float(np.mean(bucket_secondary)))
  1548	  1348	        return np.asarray(unique_primary, dtype=float), np.asarray(unique_secondary, dtype=float)
  1549	
  1550	exec
  1551	/opt/homebrew/bin/bash -lc 'nl -ba tests/analytics/test_calibration.py' in /Users/vladimir/Projects/cryodaq
  1552	 succeeded in 0ms:
  1553	     1	from __future__ import annotations
  1554	     2	
  1555	     3	from datetime import UTC, datetime
  1556	     4	from pathlib import Path
  1557	     5	
  1558	     6	import numpy as np
  1559	     7	import pytest
  1560	     8	
  1561	     9	from cryodaq.analytics.calibration import CalibrationSample, CalibrationStore
  1562	    10	
  1563	    11	
  1564	    12	def _sample_series() -> list[CalibrationSample]:
  1565	    13	    points: list[CalibrationSample] = []
  1566	    14	    for index, temp_k in enumerate([4.0, 6.0, 8.0, 12.0, 20.0, 35.0, 60.0, 90.0, 140.0, 220.0]):
  1567	    15	        raw_value = (1500.0 / (temp_k + 18.0)) + (0.002 * temp_k)
  1568	    16	        points.append(
  1569	    17	            CalibrationSample(
  1570	    18	                timestamp=datetime(2026, 3, 16, 12, index, tzinfo=UTC),
  1571	    19	                reference_channel="CH1",
  1572	    20	                reference_temperature=temp_k,
  1573	    21	                sensor_channel="CH2",
  1574	    22	                sensor_raw_value=raw_value,
  1575	    23	                reference_instrument_id="ls218s",
  1576	    24	                sensor_instrument_id="ls218s",
  1577	    25	                metadata={"index": index},
  1578	    26	            )
  1579	    27	        )
  1580	    28	    return points
  1581	    29	
  1582	    30	
  1583	    31	def _piecewise_raw(temp_k: float) -> float:
  1584	    32	    if temp_k <= 45.0:
  1585	    33	        return 1.72 - 0.060 * np.log1p(temp_k) - 0.00035 * temp_k
  1586	    34	    if temp_k <= 150.0:
  1587	    35	        dt = temp_k - 45.0
  1588	    36	        anchor = 1.72 - 0.060 * np.log1p(45.0) - 0.00035 * 45.0
  1589	    37	        return anchor - 0.0028 * dt - 0.000010 * dt * dt
  1590	    38	    dt = temp_k - 150.0
  1591	    39	    anchor = _piecewise_raw(150.0)
  1592	    40	    return anchor - 0.00105 * dt - 0.0000035 * dt * dt
  1593	    41	
  1594	    42	
  1595	    43	def _multi_zone_samples(count: int = 900, *, sensor_id: str = "CH2") -> list[CalibrationSample]:
  1596	    44	    temperatures = np.linspace(4.0, 290.0, count, dtype=float)
  1597	    45	    return [
  1598	    46	        CalibrationSample(
  1599	    47	            timestamp=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
  1600	    48	            reference_channel="REF",
  1601	    49	            reference_temperature=float(temp_k),
  1602	    50	            sensor_channel=sensor_id,
  1603	    51	            sensor_raw_value=float(_piecewise_raw(float(temp_k))),
  1604	    52	            reference_instrument_id="etalon",
  1605	    53	            sensor_instrument_id="ls218s",
  1606	    54	            metadata={"series": "multi-zone"},
  1607	    55	        )
  1608	    56	        for temp_k in temperatures
  1609	    57	    ]
  1610	    58	
  1611	    59	
  1612	    60	def _dense_nonuniform_samples(count: int = 9000) -> list[CalibrationSample]:
  1613	    61	    low = np.linspace(4.0, 80.0, int(count * 0.8), dtype=float)
  1614	    62	    high = np.linspace(80.0, 300.0, count - len(low), dtype=float)
  1615	    63	    temperatures = np.concatenate([low, high])
  1616	    64	    return [
  1617	    65	        CalibrationSample(
  1618	    66	            timestamp=datetime(2026, 3, 16, 14, 0, tzinfo=UTC),
  1619	    67	            reference_channel="REF",
  1620	    68	            reference_temperature=float(temp_k),
  1621	    69	            sensor_channel="CH3",
  1622	    70	            sensor_raw_value=float(_piecewise_raw(float(temp_k))),
  1623	    71	            metadata={"series": "dense"},
  1624	    72	        )
  1625	    73	        for temp_k in temperatures
  1626	    74	    ]
  1627	    75	
  1628	    76	
  1629	    77	def _data_lines(path: Path) -> list[str]:
  1630	    78	    return [
  1631	    79	        line.strip()
  1632	    80	        for line in path.read_text(encoding="utf-8").splitlines()
  1633	    81	        if line.strip() and not line.lstrip().startswith("#")
  1634	    82	    ]
  1635	    83	
  1636	    84	
  1637	    85	def test_calibration_store_fit_roundtrip_and_persistence(tmp_path: Path) -> None:
  1638	    86	    store = CalibrationStore(tmp_path)
  1639	    87	    samples = _sample_series()
  1640	    88	
  1641	    89	    curve = store.fit_curve(
  1642	    90	        "sensor-001",
  1643	    91	        samples,
  1644	    92	        raw_unit="ohm",
  1645	    93	        source_session_ids=["sess-001"],
  1646	    94	        max_zones=3,
  1647	    95	        min_points_per_zone=4,
  1648	    96	        target_rmse_k=0.03,
  1649	    97	    )
  1650	    98	    curve_path = store.save_curve(curve)
  1651	    99	    table_path = store.export_curve_table("sensor-001", points=32)
  1652	   100	
  1653	   101	    reloaded = CalibrationStore(tmp_path)
  1654	   102	    reloaded.load_curves(tmp_path / "curves")
  1655	   103	    estimated = reloaded.evaluate("sensor-001", samples[3].sensor_raw_value)
  1656	   104	
  1657	   105	    assert len(curve.zones) >= 1
  1658	   106	    assert curve.metrics["sample_count"] == len(samples)
  1659	   107	    assert curve_path.exists()
  1660	   108	    assert table_path.exists()
  1661	   109	    assert estimated == pytest.approx(samples[3].reference_temperature, abs=0.2)
  1662	   110	
  1663	   111	
  1664	   112	def test_fit_pipeline_uses_task_level_zone_detection_and_cv_order_selection(tmp_path: Path) -> None:
  1665	   113	    store = CalibrationStore(tmp_path)
  1666	   114	    samples = _multi_zone_samples()
  1667	   115	
  1668	   116	    curve = store.fit_curve(
  1669	   117	        "sensor-fit-task",
  1670	   118	        samples,
  1671	   119	        raw_unit="V",
  1672	   120	        max_zones=3,
  1673	   121	        min_points_per_zone=24,
  1674	   122	        target_rmse_k=0.05,
  1675	   123	    )
  1676	   124	
  1677	   125	    holdout_temps = np.linspace(6.0, 285.0, 60, dtype=float)
  1678	   126	    errors = [
  1679	   127	        abs(store.evaluate("sensor-fit-task", float(_piecewise_raw(float(temp_k)))) - float(temp_k))
  1680	   128	        for temp_k in holdout_temps
  1681	   129	    ]
  1682	   130	
  1683	   131	    assert curve.metrics["zone_detection"] == "dV/dT"
  1684	   132	    assert curve.metrics["order_selection"] == "cross_validation"
  1685	   133	    assert curve.metrics["rmse_k"] < 0.05
  1686	   134	    assert max(errors) < 0.05
  1687	   135	    assert len(curve.zones) >= 2
  1688	   136	    assert all(zone.order >= 7 for zone in curve.zones if zone.point_count >= 9)
  1689	   137	
  1690	   138	
  1691	   139	def test_downsampling_is_uniform_by_temperature_to_task_target(tmp_path: Path) -> None:
  1692	   140	    store = CalibrationStore(tmp_path)
  1693	   141	    samples = _dense_nonuniform_samples()
  1694	   142	
  1695	   143	    preprocessed = store._preprocess_samples(
  1696	   144	        samples, downsample_target=store._TASK_DOWNSAMPLE_TARGET
  1697	   145	    )
  1698	   146	    temperatures = np.array([sample.reference_temperature for sample in preprocessed], dtype=float)
  1699	   147	    histogram, _ = np.histogram(temperatures, bins=10)
  1700	   148	
  1701	   149	    assert len(preprocessed) == store._TASK_DOWNSAMPLE_TARGET
  1702	   150	    assert histogram.max() - histogram.min() <= 2
  1703	   151	
  1704	   152	
  1705	   153	def test_t_from_v_matches_evaluate_and_voltage_to_temp(tmp_path: Path) -> None:
  1706	   154	    store = CalibrationStore(tmp_path)
  1707	   155	    curve = store.fit_curve(
  1708	   156	        "sensor-api", _multi_zone_samples(), raw_unit="V", max_zones=3, min_points_per_zone=24
  1709	   157	    )
  1710	   158	    store.save_curve(curve)
  1711	   159	
  1712	   160	    raw_value = _piecewise_raw(123.0)
  1713	   161	
  1714	   162	    assert store.evaluate("sensor-api", raw_value) == pytest.approx(123.0, abs=0.05)
  1715	   163	    assert store.T_from_V("sensor-api", raw_value) == pytest.approx(
  1716	   164	        store.evaluate("sensor-api", raw_value), abs=1e-9
  1717	   165	    )
  1718	   166	    assert store.voltage_to_temp("sensor-api", raw_value) == pytest.approx(
  1719	   167	        store.evaluate("sensor-api", raw_value), abs=1e-9
  1720	   168	    )
  1721	   169	
  1722	   170	
  1723	   171	def test_calibration_store_import_export_json(tmp_path: Path) -> None:
  1724	   172	    store = CalibrationStore(tmp_path)
  1725	   173	    curve = store.fit_curve(
  1726	   174	        "sensor-002",
  1727	   175	        _sample_series(),
  1728	   176	        raw_unit="sensor_unit",
  1729	   177	        max_zones=2,
  1730	   178	        min_points_per_zone=4,
  1731	   179	    )
  1732	   180	    exported = store.export_curve_json("sensor-002")
  1733	   181	
  1734	   182	    imported_store = CalibrationStore(tmp_path / "imported")
  1735	   183	    imported_curve = imported_store.import_curve_json(exported)
  1736	   184	
  1737	   185	    assert imported_curve.sensor_id == "sensor-002"
  1738	   186	    assert imported_store.get_curve_info("sensor-002")["curve_id"] == curve.curve_id
  1739	   187	
  1740	   188	
  1741	   189	def test_export_340_uses_200_breakpoints_and_roundtrips_via_import(tmp_path: Path) -> None:
  1742	   190	    source_store = CalibrationStore(tmp_path / "source")
  1743	   191	    curve = source_store.fit_curve(
  1744	   192	        "sensor-003",
  1745	   193	        _multi_zone_samples(1200),
  1746	   194	        raw_unit="V",
  1747	   195	        max_zones=3,
  1748	   196	        min_points_per_zone=30,
  1749	   197	    )
  1750	   198	    source_store.save_curve(curve)
  1751	   199	
  1752	   200	    path_340 = source_store.export_curve_340("sensor-003", points=200)
  1753	   201	    imported_store = CalibrationStore(tmp_path / "imported")
  1754	   202	    imported_curve = imported_store.import_curve_file(
  1755	   203	        path_340, sensor_id="sensor-003B", channel_key="LS218:CH3", raw_unit="V"
  1756	   204	    )
  1757	   205	
  1758	   206	    exported_lines = _data_lines(path_340)
  1759	   207	    roundtrip_raw = _piecewise_raw(88.0)
  1760	   208	
  1761	   209	    assert len(exported_lines) == 200
  1762	   210	    assert imported_curve.sensor_id == "sensor-003B"
  1763	   211	    assert imported_store.T_from_V("sensor-003B", roundtrip_raw) == pytest.approx(88.0, abs=0.1)
  1764	   212	
  1765	   213	
  1766	   214	def test_calibration_store_imports_340_and_supports_lookup(tmp_path: Path) -> None:
  1767	   215	    source_store = CalibrationStore(tmp_path / "source")
  1768	   216	    curve = source_store.fit_curve(
  1769	   217	        "sensor-004",
  1770	   218	        _sample_series(),
  1771	   219	        raw_unit="V",
  1772	   220	        max_zones=2,
  1773	   221	        min_points_per_zone=4,
  1774	   222	    )
  1775	   223	    source_store.save_curve(curve)
  1776	   224	    exported_340 = source_store.export_curve_340("sensor-004", points=48)
  1777	   225	
  1778	   226	    imported_store = CalibrationStore(tmp_path / "imported")
  1779	   227	    imported_curve_340 = imported_store.import_curve_file(
  1780	   228	        exported_340, sensor_id="sensor-004B", channel_key="LS218:CH3"
  1781	   229	    )
  1782	   230	
  1783	   231	    lookup = imported_store.lookup_curve(channel_key="LS218:CH3")
  1784	   232	
  1785	   233	    assert imported_curve_340.sensor_id == "sensor-004B"
  1786	   234	    assert lookup["assignment"]["channel_key"] == "LS218:CH3"
  1787	   235	    assert lookup["curve"]["sensor_id"] == "sensor-004B"
  1788	   236	
  1789	   237	
  1790	   238	def test_calibration_store_backward_compatible_load_rebuilds_index(tmp_path: Path) -> None:
  1791	   239	    legacy_store = CalibrationStore(tmp_path / "legacy")
  1792	   240	    curve = legacy_store.fit_curve(
  1793	   241	        "sensor-005",
  1794	   242	        _sample_series(),
  1795	   243	        raw_unit="sensor_unit",
  1796	   244	        max_zones=2,
  1797	   245	        min_points_per_zone=4,
  1798	   246	    )
  1799	   247	    curve_path = legacy_store.save_curve(curve)
  1800	   248	    index_path = tmp_path / "legacy" / "index.yaml"
  1801	   249	    if index_path.exists():
  1802	   250	        index_path.unlink()
  1803	   251	
  1804	   252	    reloaded = CalibrationStore(tmp_path / "legacy")
  1805	   253	    reloaded.load_curves(tmp_path / "legacy" / "curves")
  1806	   254	
  1807	   255	    assert reloaded.get_curve_info("sensor-005")["curve_id"] == curve.curve_id
  1808	   256	    assert index_path.exists()
  1809	   257	    assert curve_path.exists()
  1810	   258	
  1811	   259	
  1812	   260	# ---------------------------------------------------------------------------
  1813	   261	# Phase 2d B-1: atomic write for calibration index
  1814	   262	# ---------------------------------------------------------------------------
  1815	   263	
  1816	   264	
  1817	   265	def test_calibration_index_uses_atomic_write():
  1818	   266	    """B-1.2: calibration.py index/curve writes must use atomic_write_text."""
  1819	   267	    source = Path("src/cryodaq/analytics/calibration.py").read_text(encoding="utf-8")
  1820	   268	    import re
  1821	   269	
  1822	   270	    raw_state_writes = re.findall(r"_index_path\.write_text|target\.write_text\(json", source)
  1823	   271	    assert len(raw_state_writes) == 0, (
  1824	   272	        f"Found {len(raw_state_writes)} raw write_text calls for state files — "
  1825	   273	        f"should all route through atomic_write_text"
  1826	   274	    )
  1827	   275	    assert "atomic_write_text" in source
  1828	   276	
  1829	   277	
  1830	   278	# ---------------------------------------------------------------------------
  1831	   279	# Phase D: .cof export + .330 removal
  1832	   280	# ---------------------------------------------------------------------------
  1833	   281	
  1834	   282	
  1835	   283	def test_export_curve_cof_writes_file_with_expected_structure(tmp_path: Path) -> None:
  1836	   284	    store = CalibrationStore(tmp_path)
  1837	   285	    curve = store.fit_curve(
  1838	   286	        "sensor-cof-01", _multi_zone_samples(300), raw_unit="V", max_zones=2, min_points_per_zone=24
  1839	   287	    )
  1840	   288	    store.save_curve(curve)
  1841	   289	
  1842	   290	    cof_path = store.export_curve_cof("sensor-cof-01")
  1843	   291	
  1844	   292	    assert cof_path.exists()
  1845	   293	    assert cof_path.suffix == ".cof"
  1846	   294	    text = cof_path.read_text(encoding="utf-8")
  1847	   295	    assert "# CryoDAQ calibration curve export .cof" in text
  1848	   296	    assert f"# sensor_id: {curve.sensor_id}" in text
  1849	   297	    assert f"# curve_id: {curve.curve_id}" in text
  1850	   298	    assert "[zone 1]" in text
  1851	   299	    assert "raw_min:" in text
  1852	   300	    assert "raw_max:" in text
  1853	   301	    assert "order:" in text
  1854	   302	    assert "coefficients:" in text
  1855	   303	
  1856	   304	
  1857	   305	def test_export_curve_cof_preserves_chebyshev_coefficients_round_trip(tmp_path: Path) -> None:
  1858	   306	    store = CalibrationStore(tmp_path)
  1859	   307	    curve = store.fit_curve(
  1860	   308	        "sensor-cof-02", _multi_zone_samples(600), raw_unit="V", max_zones=3, min_points_per_zone=24
  1861	   309	    )
  1862	   310	    store.save_curve(curve)
  1863	   311	
  1864	   312	    cof_path = store.export_curve_cof("sensor-cof-02")
  1865	   313	    text = cof_path.read_text(encoding="utf-8")
  1866	   314	
  1867	   315	    parsed_coefficients: list[tuple[float, ...]] = []
  1868	   316	    for line in text.splitlines():
  1869	   317	        line = line.strip()
  1870	   318	        if line.startswith("coefficients:"):
  1871	   319	            values = tuple(float(v) for v in line.split(":", 1)[1].split(","))
  1872	   320	            parsed_coefficients.append(values)
  1873	   321	
  1874	   322	    assert len(parsed_coefficients) == len(curve.zones)
  1875	   323	    for parsed, zone in zip(parsed_coefficients, curve.zones, strict=True):
  1876	   324	        assert len(parsed) == len(zone.coefficients)
  1877	   325	        for a, b in zip(parsed, zone.coefficients, strict=True):
  1878	   326	            assert a == pytest.approx(b, rel=1e-10)
  1879	   327	
  1880	   328	
  1881	   329	def test_export_curve_cof_includes_zone_count_header(tmp_path: Path) -> None:
  1882	   330	    store = CalibrationStore(tmp_path)
  1883	   331	    curve = store.fit_curve(
  1884	   332	        "sensor-cof-03", _multi_zone_samples(300), raw_unit="V", max_zones=3, min_points_per_zone=24
  1885	   333	    )
  1886	   334	    store.save_curve(curve)
  1887	   335	
  1888	   336	    cof_path = store.export_curve_cof("sensor-cof-03")
  1889	   337	    text = cof_path.read_text(encoding="utf-8")
  1890	   338	
  1891	   339	    assert f"# zone_count: {len(curve.zones)}" in text
  1892	   340	
  1893	   341	
  1894	   342	def test_export_curve_cof_metadata_comments_match_curve(tmp_path: Path) -> None:
  1895	   343	    store = CalibrationStore(tmp_path)
  1896	   344	    curve = store.fit_curve(
  1897	   345	        "sensor-cof-04", _sample_series(), raw_unit="ohm", max_zones=2, min_points_per_zone=4
  1898	   346	    )
  1899	   347	    store.save_curve(curve)
  1900	   348	
  1901	   349	    cof_path = store.export_curve_cof("sensor-cof-04")
  1902	   350	    text = cof_path.read_text(encoding="utf-8")
  1903	   351	
  1904	   352	    assert f"# raw_unit: {curve.raw_unit}" in text
  1905	   353	    assert f"# fit_timestamp: {curve.fit_timestamp.isoformat()}" in text
  1906	   354	    assert "# rmse_k:" in text
  1907	   355	    assert "# max_abs_error_k:" in text
  1908	   356	    assert "# point_count:" in text
  1909	   357	
  1910	   358	
  1911	   359	def test_export_curve_330_removed(tmp_path: Path) -> None:
  1912	   360	    store = CalibrationStore(tmp_path)
  1913	   361	    assert not hasattr(store, "export_curve_330"), (
  1914	   362	        "export_curve_330 must be removed — architect decision 2026-04-25"
  1915	   363	    )
  1916	   364	
  1917	   365	
  1918	   366	def test_import_curve_file_rejects_330_suffix(tmp_path: Path) -> None:
  1919	   367	    fake_330 = tmp_path / "curve.330"
  1920	   368	    fake_330.write_text("# header\n4.0 75.0\n6.0 60.0\n10.0 40.0\n20.0 22.0\n", encoding="utf-8")
  1921	   369	    store = CalibrationStore(tmp_path)
  1922	   370	    with pytest.raises(ValueError, match="Unsupported calibration import format"):
  1923	   371	        store.import_curve_file(fake_330)
  1924	
  1925	exec
  1926	/opt/homebrew/bin/bash -lc 'git status --short --branch' in /Users/vladimir/Projects/cryodaq
  1927	 succeeded in 0ms:
  1928	## feat/cof-calibration-export
  1929	?? artifacts/consultations/2026-04-28-cof-migration/
  1930	
  1931	codex
  1932	The first file output was truncated around the index helpers, so I’m pulling the missing section separately. The test file came through completely; the `.330` rejection test writes four numeric rows before calling the import path.
  1933	exec
  1934	/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/analytics/calibration.py | sed -n '500,920p'" in /Users/vladimir/Projects/cryodaq
  1935	 succeeded in 0ms:
  1936	   500	        return [self.get_curve_info(curve_id=curve.curve_id) for curve in curves]
  1937	   501	
  1938	   502	    def list_assignments(self) -> list[dict[str, Any]]:
  1939	   503	        assignments = [dict(item) for item in self._assignments.values()]
  1940	   504	        assignments.sort(key=lambda item: str(item.get("sensor_id", "")))
  1941	   505	        return assignments
  1942	   506	
  1943	   507	    def get_runtime_settings(self) -> dict[str, Any]:
  1944	   508	        assignments = []
  1945	   509	        for item in self.list_assignments():
  1946	   510	            channel_key = str(item.get("channel_key", "")).strip()
  1947	   511	            resolution = self.resolve_runtime_policy(channel_key=channel_key) if channel_key else {}
  1948	   512	            assignments.append(
  1949	   513	                {
  1950	   514	                    **item,
  1951	   515	                    "resolution": resolution,
  1952	   516	                }
  1953	   517	            )
  1954	   518	        return {
  1955	   519	            "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
  1956	   520	            "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
  1957	   521	            "assignments": assignments,
  1958	   522	        }
  1959	   523	
  1960	   524	    def set_runtime_global_mode(self, mode: str) -> dict[str, Any]:
  1961	   525	        normalized = str(mode).strip().lower()
  1962	   526	        if normalized not in {"off", "on"}:
  1963	   527	            raise ValueError("Runtime calibration global_mode must be 'off' or 'on'.")
  1964	   528	        self._runtime_settings["global_mode"] = normalized
  1965	   529	        self._runtime_settings["updated_at"] = _utcnow().isoformat()
  1966	   530	        self._write_index()
  1967	   531	        return self.get_runtime_settings()
  1968	   532	
  1969	   533	    def set_runtime_channel_policy(
  1970	   534	        self,
  1971	   535	        *,
  1972	   536	        channel_key: str,
  1973	   537	        policy: str,
  1974	   538	        sensor_id: str | None = None,
  1975	   539	        curve_id: str | None = None,
  1976	   540	        runtime_apply_ready: bool | None = None,
  1977	   541	    ) -> dict[str, Any]:
  1978	   542	        normalized_channel_key = str(channel_key).strip()
  1979	   543	        if not normalized_channel_key:
  1980	   544	            raise ValueError("channel_key is required.")
  1981	   545	        normalized_policy = str(policy).strip().lower()
  1982	   546	        if normalized_policy not in {"inherit", "off", "on"}:
  1983	   547	            raise ValueError("Channel runtime policy must be 'inherit', 'off', or 'on'.")
  1984	   548	        curve = self._resolve_curve(
  1985	   549	            sensor_id=str(sensor_id or "").strip() or None,
  1986	   550	            curve_id=str(curve_id or "").strip() or None,
  1987	   551	        )
  1988	   552	        assignment = self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
  1989	   553	        assignment["channel_key"] = normalized_channel_key
  1990	   554	        assignment["reading_mode_policy"] = normalized_policy
  1991	   555	        if runtime_apply_ready is not None:
  1992	   556	            assignment["runtime_apply_ready"] = bool(runtime_apply_ready)
  1993	   557	        assignment["updated_at"] = _utcnow().isoformat()
  1994	   558	        self._write_index()
  1995	   559	        return {
  1996	   560	            "assignment": dict(assignment),
  1997	   561	            "resolution": self.resolve_runtime_policy(channel_key=normalized_channel_key),
  1998	   562	        }
  1999	   563	
  2000	   564	    def resolve_runtime_policy(
  2001	   565	        self,
  2002	   566	        *,
  2003	   567	        channel_key: str,
  2004	   568	    ) -> dict[str, Any]:
  2005	   569	        normalized_channel_key = str(channel_key).strip()
  2006	   570	        if not normalized_channel_key:
  2007	   571	            raise ValueError("channel_key is required.")
  2008	   572	        global_mode = str(self._runtime_settings.get("global_mode", "off") or "off")
  2009	   573	        assignment = next(
  2010	   574	            (
  2011	   575	                dict(item)
  2012	   576	                for item in self._assignments.values()
  2013	   577	                if str(item.get("channel_key", "")).strip() == normalized_channel_key
  2014	   578	            ),
  2015	   579	            None,
  2016	   580	        )
  2017	   581	        if global_mode == "off":
  2018	   582	            return {
  2019	   583	                "global_mode": global_mode,
  2020	   584	                "channel_key": normalized_channel_key,
  2021	   585	                "effective_mode": "off",
  2022	   586	                "reading_mode": "krdg",
  2023	   587	                "raw_source": "KRDG",
  2024	   588	                "reason": "global_off",
  2025	   589	                "assignment": assignment,
  2026	   590	            }
  2027	   591	        if assignment is None:
  2028	   592	            return {
  2029	   593	                "global_mode": global_mode,
  2030	   594	                "channel_key": normalized_channel_key,
  2031	   595	                "effective_mode": "off",
  2032	   596	                "reading_mode": "krdg",
  2033	   597	                "raw_source": "KRDG",
  2034	   598	                "reason": "missing_assignment",
  2035	   599	                "assignment": None,
  2036	   600	            }
  2037	   601	        policy = str(assignment.get("reading_mode_policy", "inherit") or "inherit").lower()
  2038	   602	        if policy == "off":
  2039	   603	            return {
  2040	   604	                "global_mode": global_mode,
  2041	   605	                "channel_key": normalized_channel_key,
  2042	   606	                "effective_mode": "off",
  2043	   607	                "reading_mode": "krdg",
  2044	   608	                "raw_source": "KRDG",
  2045	   609	                "reason": "channel_off",
  2046	   610	                "assignment": assignment,
  2047	   611	            }
  2048	   612	        if not bool(assignment.get("runtime_apply_ready", False)):
  2049	   613	            return {
  2050	   614	                "global_mode": global_mode,
  2051	   615	                "channel_key": normalized_channel_key,
  2052	   616	                "effective_mode": "off",
  2053	   617	                "reading_mode": "krdg",
  2054	   618	                "raw_source": "KRDG",
  2055	   619	                "reason": "not_runtime_ready",
  2056	   620	                "assignment": assignment,
  2057	   621	            }
  2058	   622	        sensor_id = str(assignment.get("sensor_id", "")).strip()
  2059	   623	        if not sensor_id or sensor_id not in self._curves:
  2060	   624	            return {
  2061	   625	                "global_mode": global_mode,
  2062	   626	                "channel_key": normalized_channel_key,
  2063	   627	                "effective_mode": "off",
  2064	   628	                "reading_mode": "krdg",
  2065	   629	                "raw_source": "KRDG",
  2066	   630	                "reason": "missing_curve",
  2067	   631	                "assignment": assignment,
  2068	   632	            }
  2069	   633	        curve = self._curves[sensor_id]
  2070	   634	        return {
  2071	   635	            "global_mode": global_mode,
  2072	   636	            "channel_key": normalized_channel_key,
  2073	   637	            "effective_mode": "on",
  2074	   638	            "reading_mode": "curve",
  2075	   639	            "raw_source": "SRDG",
  2076	   640	            "reason": "curve_applied",
  2077	   641	            "assignment": assignment,
  2078	   642	            "curve": self.get_curve_info(curve_id=curve.curve_id),
  2079	   643	        }
  2080	   644	
  2081	   645	    def assign_curve(
  2082	   646	        self,
  2083	   647	        *,
  2084	   648	        sensor_id: str,
  2085	   649	        curve_id: str | None = None,
  2086	   650	        channel_key: str | None = None,
  2087	   651	        runtime_apply_ready: bool = False,
  2088	   652	        reading_mode_policy: str = "inherit",
  2089	   653	    ) -> dict[str, Any]:
  2090	   654	        curve = self._resolve_curve(sensor_id=sensor_id, curve_id=curve_id)
  2091	   655	        normalized_policy = str(reading_mode_policy).strip().lower() or "inherit"
  2092	   656	        if normalized_policy not in {"inherit", "off", "on"}:
  2093	   657	            raise ValueError("reading_mode_policy must be 'inherit', 'off', or 'on'.")
  2094	   658	        assignment = {
  2095	   659	            "sensor_id": curve.sensor_id,
  2096	   660	            "curve_id": curve.curve_id,
  2097	   661	            "channel_key": str(channel_key).strip() if channel_key is not None else curve.sensor_id,
  2098	   662	            "updated_at": _utcnow().isoformat(),
  2099	   663	            "runtime_apply_ready": bool(runtime_apply_ready),
  2100	   664	            "reading_mode_policy": normalized_policy,
  2101	   665	        }
  2102	   666	        self._assignments[curve.sensor_id] = assignment
  2103	   667	        self._write_index()
  2104	   668	        return dict(assignment)
  2105	   669	
  2106	   670	    def lookup_curve(
  2107	   671	        self,
  2108	   672	        *,
  2109	   673	        sensor_id: str | None = None,
  2110	   674	        channel_key: str | None = None,
  2111	   675	    ) -> dict[str, Any]:
  2112	   676	        assignment: dict[str, Any] | None = None
  2113	   677	        if sensor_id:
  2114	   678	            assignment = dict(self._assignments.get(sensor_id) or {})
  2115	   679	        elif channel_key:
  2116	   680	            assignment = next(
  2117	   681	                (
  2118	   682	                    dict(item)
  2119	   683	                    for item in self._assignments.values()
  2120	   684	                    if str(item.get("channel_key", "")).strip() == channel_key
  2121	   685	                ),
  2122	   686	                None,
  2123	   687	            )
  2124	   688	        if assignment is None:
  2125	   689	            if sensor_id and sensor_id in self._curves:
  2126	   690	                curve = self._curves[sensor_id]
  2127	   691	                assignment = dict(
  2128	   692	                    self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
  2129	   693	                )
  2130	   694	            else:
  2131	   695	                raise KeyError("Calibration curve lookup did not match any sensor or channel.")
  2132	   696	        curve = self._resolve_curve(
  2133	   697	            sensor_id=str(assignment.get("sensor_id", "")),
  2134	   698	            curve_id=str(assignment.get("curve_id", "")),
  2135	   699	        )
  2136	   700	        return {
  2137	   701	            "assignment": assignment,
  2138	   702	            "curve": self.get_curve_info(curve_id=curve.curve_id),
  2139	   703	        }
  2140	   704	
  2141	   705	    def _require_curve(self, sensor_id: str) -> CalibrationCurve:
  2142	   706	        if sensor_id not in self._curves:
  2143	   707	            raise KeyError(f"Calibration curve for sensor '{sensor_id}' is not loaded.")
  2144	   708	        return self._curves[sensor_id]
  2145	   709	
  2146	   710	    def _resolve_curve(
  2147	   711	        self, *, sensor_id: str | None = None, curve_id: str | None = None
  2148	   712	    ) -> CalibrationCurve:
  2149	   713	        if sensor_id:
  2150	   714	            return self._require_curve(sensor_id)
  2151	   715	        if curve_id:
  2152	   716	            for curve in self._curves.values():
  2153	   717	                if curve.curve_id == curve_id:
  2154	   718	                    return curve
  2155	   719	        raise KeyError("Calibration curve could not be resolved.")
  2156	   720	
  2157	   721	    def _curve_directory(self, sensor_id: str, curve_id: str) -> Path:
  2158	   722	        if self._curves_dir is None:
  2159	   723	            raise RuntimeError("CalibrationStore base_dir is required for artifact export.")
  2160	   724	        return self._curves_dir / _safe_path_fragment(sensor_id) / _safe_path_fragment(curve_id)
  2161	   725	
  2162	   726	    def _curve_path(self, sensor_id: str, curve_id: str) -> Path:
  2163	   727	        return self._curve_directory(sensor_id, curve_id) / "curve.json"
  2164	   728	
  2165	   729	    def _curve_340_path(self, sensor_id: str, curve_id: str) -> Path:
  2166	   730	        if self._exports_dir is None:
  2167	   731	            raise RuntimeError("CalibrationStore base_dir is required for export.")
  2168	   732	        return (
  2169	   733	            self._exports_dir
  2170	   734	            / _safe_path_fragment(sensor_id)
  2171	   735	            / _safe_path_fragment(curve_id)
  2172	   736	            / "curve.340"
  2173	   737	        )
  2174	   738	
  2175	   739	    def _load_index(self) -> None:
  2176	   740	        if self._index_path is None or not self._index_path.exists():
  2177	   741	            return
  2178	   742	        payload = yaml.safe_load(self._index_path.read_text(encoding="utf-8")) or {}
  2179	   743	        runtime = payload.get("runtime", {})
  2180	   744	        if isinstance(runtime, dict):
  2181	   745	            global_mode = str(runtime.get("global_mode", "off") or "off").strip().lower()
  2182	   746	            if global_mode in {"off", "on"}:
  2183	   747	                self._runtime_settings["global_mode"] = global_mode
  2184	   748	            self._runtime_settings["updated_at"] = str(runtime.get("updated_at", "")).strip()
  2185	   749	        assignments = payload.get("assignments", [])
  2186	   750	        if isinstance(assignments, list):
  2187	   751	            for item in assignments:
  2188	   752	                if not isinstance(item, dict):
  2189	   753	                    continue
  2190	   754	                sensor_id = str(item.get("sensor_id", "")).strip()
  2191	   755	                if sensor_id:
  2192	   756	                    self._assignments[sensor_id] = {
  2193	   757	                        "sensor_id": sensor_id,
  2194	   758	                        "curve_id": str(item.get("curve_id", "")).strip(),
  2195	   759	                        "channel_key": str(item.get("channel_key", sensor_id)).strip() or sensor_id,
  2196	   760	                        "updated_at": str(item.get("updated_at", "")).strip(),
  2197	   761	                        "runtime_apply_ready": bool(item.get("runtime_apply_ready", False)),
  2198	   762	                        "reading_mode_policy": str(
  2199	   763	                            item.get("reading_mode_policy", "inherit") or "inherit"
  2200	   764	                        )
  2201	   765	                        .strip()
  2202	   766	                        .lower()
  2203	   767	                        or "inherit",
  2204	   768	                    }
  2205	   769	
  2206	   770	    def _write_index(self) -> None:
  2207	   771	        if self._index_path is None:
  2208	   772	            return
  2209	   773	        self._index_path.parent.mkdir(parents=True, exist_ok=True)
  2210	   774	        payload = {
  2211	   775	            "schema_version": 1,
  2212	   776	            "generated_at": _utcnow().isoformat(),
  2213	   777	            "runtime": {
  2214	   778	                "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
  2215	   779	                "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
  2216	   780	            },
  2217	   781	            "curves": [
  2218	   782	                {
  2219	   783	                    "sensor_id": curve.sensor_id,
  2220	   784	                    "curve_id": curve.curve_id,
  2221	   785	                    "fit_timestamp": curve.fit_timestamp.isoformat(),
  2222	   786	                    "raw_unit": curve.raw_unit,
  2223	   787	                    "sensor_kind": curve.sensor_kind,
  2224	   788	                    "curve_path": str(self._curve_path(curve.sensor_id, curve.curve_id)),
  2225	   789	                    "table_path": str(
  2226	   790	                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
  2227	   791	                    ),
  2228	   792	                    "curve_cof_path": str(
  2229	   793	                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof"
  2230	   794	                    ),
  2231	   795	                    "curve_340_path": str(
  2232	   796	                        self._curve_340_path(curve.sensor_id, curve.curve_id)
  2233	   797	                        if self._exports_dir
  2234	   798	                        else ""
  2235	   799	                    ),
  2236	   800	                    "source_session_ids": list(curve.source_session_ids),
  2237	   801	                }
  2238	   802	                for curve in sorted(
  2239	   803	                    self._curves.values(), key=lambda item: item.fit_timestamp, reverse=True
  2240	   804	                )
  2241	   805	            ],
  2242	   806	            "assignments": [dict(item) for item in self.list_assignments()],
  2243	   807	        }
  2244	   808	        from cryodaq.core.atomic_write import atomic_write_text
  2245	   809	
  2246	   810	        atomic_write_text(
  2247	   811	            self._index_path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
  2248	   812	        )
  2249	   813	
  2250	   814	    def _ensure_assignment(self, *, sensor_id: str, curve_id: str) -> dict[str, Any]:
  2251	   815	        existing = self._assignments.get(sensor_id)
  2252	   816	        if existing:
  2253	   817	            existing["curve_id"] = curve_id
  2254	   818	            existing["updated_at"] = _utcnow().isoformat()
  2255	   819	            return existing
  2256	   820	        assignment = {
  2257	   821	            "sensor_id": sensor_id,
  2258	   822	            "curve_id": curve_id,
  2259	   823	            "channel_key": sensor_id,
  2260	   824	            "updated_at": _utcnow().isoformat(),
  2261	   825	            "runtime_apply_ready": False,
  2262	   826	            "reading_mode_policy": "inherit",
  2263	   827	        }
  2264	   828	        self._assignments[sensor_id] = assignment
  2265	   829	        return assignment
  2266	   830	
  2267	   831	    def _export_rows(self, curve: CalibrationCurve, *, points: int) -> list[tuple[float, float]]:
  2268	   832	        dense_points = max(points * 24, 2000)
  2269	   833	        raw_min = curve.zones[0].raw_min
  2270	   834	        raw_max = curve.zones[-1].raw_max
  2271	   835	        raw_grid = np.linspace(raw_min, raw_max, dense_points, dtype=float)
  2272	   836	        temperatures = np.array(
  2273	   837	            [curve.evaluate(float(raw_value)) for raw_value in raw_grid], dtype=float
  2274	   838	        )
  2275	   839	        order = np.argsort(temperatures)
  2276	   840	        sorted_temperatures = temperatures[order]
  2277	   841	        sorted_raw = raw_grid[order]
  2278	   842	        sorted_temperatures, sorted_raw = self._collapse_duplicate_axis(
  2279	   843	            sorted_temperatures, sorted_raw
  2280	   844	        )
  2281	   845	        indices = self._adaptive_breakpoint_indices(sorted_temperatures, sorted_raw, max(points, 2))
  2282	   846	        rows = [(float(sorted_temperatures[index]), float(sorted_raw[index])) for index in indices]
  2283	   847	        deduped: list[tuple[float, float]] = []
  2284	   848	        seen: set[tuple[float, float]] = set()
  2285	   849	        for item in rows:
  2286	   850	            key = (round(item[0], 9), round(item[1], 9))
  2287	   851	            if key in seen:
  2288	   852	                continue
  2289	   853	            seen.add(key)
  2290	   854	            deduped.append(item)
  2291	   855	        return deduped[: max(points, 2)]
  2292	   856	
  2293	   857	    def _write_curve_text_export(
  2294	   858	        self,
  2295	   859	        path: Path,
  2296	   860	        curve: CalibrationCurve,
  2297	   861	        rows: list[tuple[float, float]],
  2298	   862	        *,
  2299	   863	        format_name: str,
  2300	   864	    ) -> None:
  2301	   865	        with path.open("w", encoding="utf-8", newline="") as handle:
  2302	   866	            handle.write(f"# CryoDAQ calibration curve export .{format_name}\n")
  2303	   867	            handle.write(f"# sensor_id: {curve.sensor_id}\n")
  2304	   868	            handle.write(f"# curve_id: {curve.curve_id}\n")
  2305	   869	            handle.write(f"# raw_unit: {curve.raw_unit}\n")
  2306	   870	            handle.write("# columns: temperature_K, sensor_raw\n")
  2307	   871	            writer = csv.writer(handle)
  2308	   872	            for temperature_k, raw_value in rows:
  2309	   873	                writer.writerow([f"{temperature_k:.9g}", f"{raw_value:.9g}"])
  2310	   874	
  2311	   875	    def _write_cof_export(self, path: Path, curve: CalibrationCurve) -> None:
  2312	   876	        """Write .cof format: header + per-zone raw Chebyshev coefficients."""
  2313	   877	        from cryodaq.core.atomic_write import atomic_write_text
  2314	   878	
  2315	   879	        lines: list[str] = []
  2316	   880	        lines.append("# CryoDAQ calibration curve export .cof")
  2317	   881	        lines.append(f"# sensor_id: {curve.sensor_id}")
  2318	   882	        lines.append(f"# curve_id: {curve.curve_id}")
  2319	   883	        lines.append(f"# raw_unit: {curve.raw_unit}")
  2320	   884	        lines.append(f"# fit_timestamp: {curve.fit_timestamp.isoformat()}")
  2321	   885	        lines.append(
  2322	   886	            "# format: Chebyshev T_n(x), x = 2*(raw - raw_min)/(raw_max - raw_min) - 1"
  2323	   887	        )
  2324	   888	        lines.append(f"# zone_count: {len(curve.zones)}")
  2325	   889	        lines.append("")
  2326	   890	        for index, zone in enumerate(curve.zones, start=1):
  2327	   891	            lines.append(f"[zone {index}]")
  2328	   892	            lines.append(f"raw_min: {zone.raw_min:.12g}")
  2329	   893	            lines.append(f"raw_max: {zone.raw_max:.12g}")
  2330	   894	            lines.append(f"order: {zone.order}")
  2331	   895	            coefficients = ", ".join(f"{value:.12g}" for value in zone.coefficients)
  2332	   896	            lines.append(f"coefficients: {coefficients}")
  2333	   897	            lines.append(f"# rmse_k: {zone.rmse_k:.6g}")
  2334	   898	            lines.append(f"# max_abs_error_k: {zone.max_abs_error_k:.6g}")
  2335	   899	            lines.append(f"# point_count: {zone.point_count}")
  2336	   900	            lines.append("")
  2337	   901	        atomic_write_text(path, "\n".join(lines))
  2338	   902	
  2339	   903	    def _import_curve_text(
  2340	   904	        self,
  2341	   905	        path: Path,
  2342	   906	        *,
  2343	   907	        sensor_id: str | None,
  2344	   908	        channel_key: str | None,
  2345	   909	        raw_unit: str,
  2346	   910	        sensor_kind: str,
  2347	   911	        import_format: str,
  2348	   912	    ) -> CalibrationCurve:
  2349	   913	        rows: list[tuple[float, float]] = []
  2350	   914	        for raw_line in path.read_text(encoding="utf-8").splitlines():
  2351	   915	            line = raw_line.strip()
  2352	   916	            if not line or line.startswith("#"):
  2353	   917	                continue
  2354	   918	            line = line.replace(",", " ")
  2355	   919	            parts = [item for item in line.split() if item]
  2356	   920	            if len(parts) < 2:
  2357	
  2358	exec
  2359	/opt/homebrew/bin/bash -lc 'find artifacts/consultations/2026-04-28-cof-migration -maxdepth 1 -type f -print' in /Users/vladimir/Projects/cryodaq
  2360	 succeeded in 0ms:
  2361	artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.response.md
  2362	artifacts/consultations/2026-04-28-cof-migration/gemini-cof-audit.prompt.md
  2363	artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.prompt.md
  2364	artifacts/consultations/2026-04-28-cof-migration/gemini-cof-audit.response.md
  2365	
  2366	exec
  2367	/opt/homebrew/bin/bash -lc "rg -n \"export_curve_330|curve_330_path|curve_cof_path|\\.330|import_format == \\\"330\\\"|export_curve_340|_write_index|_curve_directory|_write_cof_export|atomic_write_text|format: Chebyshev\" src/cryodaq/analytics/calibration.py tests/analytics/test_calibration.py" in /Users/vladimir/Projects/cryodaq
  2368	 succeeded in 0ms:
  2369	tests/analytics/test_calibration.py:200:    path_340 = source_store.export_curve_340("sensor-003", points=200)
  2370	tests/analytics/test_calibration.py:224:    exported_340 = source_store.export_curve_340("sensor-004", points=48)
  2371	tests/analytics/test_calibration.py:266:    """B-1.2: calibration.py index/curve writes must use atomic_write_text."""
  2372	tests/analytics/test_calibration.py:273:        f"should all route through atomic_write_text"
  2373	tests/analytics/test_calibration.py:275:    assert "atomic_write_text" in source
  2374	tests/analytics/test_calibration.py:279:# Phase D: .cof export + .330 removal
  2375	tests/analytics/test_calibration.py:359:def test_export_curve_330_removed(tmp_path: Path) -> None:
  2376	tests/analytics/test_calibration.py:361:    assert not hasattr(store, "export_curve_330"), (
  2377	tests/analytics/test_calibration.py:362:        "export_curve_330 must be removed — architect decision 2026-04-25"
  2378	tests/analytics/test_calibration.py:367:    fake_330 = tmp_path / "curve.330"
  2379	src/cryodaq/analytics/calibration.py:345:        from cryodaq.core.atomic_write import atomic_write_text
  2380	src/cryodaq/analytics/calibration.py:347:        atomic_write_text(target, json.dumps(curve.to_payload(), ensure_ascii=False, indent=2))
  2381	src/cryodaq/analytics/calibration.py:350:        self._write_index()
  2382	src/cryodaq/analytics/calibration.py:362:        self._write_index()
  2383	src/cryodaq/analytics/calibration.py:397:        self._write_index()
  2384	src/cryodaq/analytics/calibration.py:412:        target = path or self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
  2385	src/cryodaq/analytics/calibration.py:438:        target = path or (self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof")
  2386	src/cryodaq/analytics/calibration.py:440:        self._write_cof_export(target, curve)
  2387	src/cryodaq/analytics/calibration.py:441:        self._write_index()
  2388	src/cryodaq/analytics/calibration.py:444:    def export_curve_340(
  2389	src/cryodaq/analytics/calibration.py:458:        self._write_index()
  2390	src/cryodaq/analytics/calibration.py:484:                self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
  2391	src/cryodaq/analytics/calibration.py:486:            "curve_cof_path": str(
  2392	src/cryodaq/analytics/calibration.py:487:                self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof"
  2393	src/cryodaq/analytics/calibration.py:530:        self._write_index()
  2394	src/cryodaq/analytics/calibration.py:558:        self._write_index()
  2395	src/cryodaq/analytics/calibration.py:667:        self._write_index()
  2396	src/cryodaq/analytics/calibration.py:721:    def _curve_directory(self, sensor_id: str, curve_id: str) -> Path:
  2397	src/cryodaq/analytics/calibration.py:727:        return self._curve_directory(sensor_id, curve_id) / "curve.json"
  2398	src/cryodaq/analytics/calibration.py:770:    def _write_index(self) -> None:
  2399	src/cryodaq/analytics/calibration.py:790:                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
  2400	src/cryodaq/analytics/calibration.py:792:                    "curve_cof_path": str(
  2401	src/cryodaq/analytics/calibration.py:793:                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof"
  2402	src/cryodaq/analytics/calibration.py:808:        from cryodaq.core.atomic_write import atomic_write_text
  2403	src/cryodaq/analytics/calibration.py:810:        atomic_write_text(
  2404	src/cryodaq/analytics/calibration.py:875:    def _write_cof_export(self, path: Path, curve: CalibrationCurve) -> None:
  2405	src/cryodaq/analytics/calibration.py:877:        from cryodaq.core.atomic_write import atomic_write_text
  2406	src/cryodaq/analytics/calibration.py:886:            "# format: Chebyshev T_n(x), x = 2*(raw - raw_min)/(raw_max - raw_min) - 1"
  2407	src/cryodaq/analytics/calibration.py:901:        atomic_write_text(path, "\n".join(lines))
  2408	src/cryodaq/analytics/calibration.py:962:            self.export_curve_340(curve.sensor_id)
  2409	
  2410	codex
  2411	The requested response path already exists as an untracked file. I’m reading it before deciding how to handle the requested write, because this environment does not permit filesystem writes.

exec
/opt/homebrew/bin/bash -lc 'wc -l src/cryodaq/analytics/calibration.py tests/analytics/test_calibration.py artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.response.md' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    1348 src/cryodaq/analytics/calibration.py
     371 tests/analytics/test_calibration.py
    2411 artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.response.md
    4130 total

exec
/opt/homebrew/bin/bash -lc 'git diff -- src/cryodaq/analytics/calibration.py tests/analytics/test_calibration.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
codex
I have enough source context for most checks. For D1’s “unchanged” wording, I’m checking local branch metadata/diffs if available; without a baseline ref, I can only verify the method’s current presence and behavior.
exec
/opt/homebrew/bin/bash -lc 'git branch --show-current' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
feat/cof-calibration-export

exec
/opt/homebrew/bin/bash -lc 'git branch --list --all "*main*" "*master*" "*feat/cof-calibration-export*"' in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc 'git diff --name-only main...HEAD -- src/cryodaq/analytics/calibration.py tests/analytics/test_calibration.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
* feat/cof-calibration-export
  master
  remotes/origin/feat/cof-calibration-export
  remotes/origin/master

 exited 128 in 0ms:
fatal: bad revision 'main...HEAD'

exec
/opt/homebrew/bin/bash -lc "git diff main...HEAD -- src/cryodaq/analytics/calibration.py | sed -n '1,240p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
fatal: bad revision 'main...HEAD'

exec
/opt/homebrew/bin/bash -lc 'git diff --name-only master...HEAD -- src/cryodaq/analytics/calibration.py tests/analytics/test_calibration.py' in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "git diff master...HEAD -- src/cryodaq/analytics/calibration.py | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "git show master:src/cryodaq/analytics/calibration.py | rg -n \"def export_curve_340|def export_curve_330|elif suffix == \\\"\\.340\\\"|elif suffix == \\\"\\.330\\\"|curve_330_path|curve_340_path\"" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/analytics/calibration.py
tests/analytics/test_calibration.py

 succeeded in 0ms:
424:    def export_curve_330(
439:    def export_curve_340(
449:        target = path or self._curve_340_path(curve.sensor_id, curve.curve_id)
481:            "curve_330_path": str(
484:            "curve_340_path": str(
485:                self._curve_340_path(curve.sensor_id, curve.curve_id) if self._exports_dir else ""
724:    def _curve_340_path(self, sensor_id: str, curve_id: str) -> Path:
787:                    "curve_330_path": str(
790:                    "curve_340_path": str(
791:                        self._curve_340_path(curve.sensor_id, curve.curve_id)

 succeeded in 0ms:
diff --git a/src/cryodaq/analytics/calibration.py b/src/cryodaq/analytics/calibration.py
index 39490ae..1f19c6e 100644
--- a/src/cryodaq/analytics/calibration.py
+++ b/src/cryodaq/analytics/calibration.py
@@ -376,14 +376,14 @@ class CalibrationStore:
         suffix = path.suffix.lower()
         if suffix == ".json":
             curve = self.import_curve_json(path)
-        elif suffix in {".330", ".340"}:
+        elif suffix == ".340":
             curve = self._import_curve_text(
                 path,
                 sensor_id=sensor_id,
                 channel_key=channel_key,
                 raw_unit=raw_unit,
                 sensor_kind=sensor_kind,
-                import_format=suffix.lstrip("."),
+                import_format="340",
             )
         else:
             raise ValueError(f"Unsupported calibration import format: {path.suffix}")
@@ -421,18 +421,23 @@ class CalibrationStore:
                 writer.writerow([float(raw_value), curve.evaluate(float(raw_value))])
         return target
 
-    def export_curve_330(
+    def export_curve_cof(
         self,
         sensor_id: str,
         *,
         path: Path | None = None,
-        points: int = 200,
     ) -> Path:
+        """Export calibration curve as .cof (Chebyshev coefficients) format.
+
+        Unlike .340 which exports sampled breakpoints, .cof preserves the
+        raw fit coefficients per zone. Portable: can be re-evaluated by
+        any code with numpy.polynomial.chebyshev, no CryoDAQ schema
+        dependency.
+        """
         curve = self._require_curve(sensor_id)
-        target = path or (self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.330")
+        target = path or (self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof")
         target.parent.mkdir(parents=True, exist_ok=True)
-        rows = self._export_rows(curve, points=max(points, 2))
-        self._write_curve_text_export(target, curve, rows, format_name="330")
+        self._write_cof_export(target, curve)
         self._write_index()
         return target
 
@@ -478,8 +483,8 @@ class CalibrationStore:
             "table_path": str(
                 self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
             ),
-            "curve_330_path": str(
-                self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.330"
+            "curve_cof_path": str(
+                self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof"
             ),
             "curve_340_path": str(
                 self._curve_340_path(curve.sensor_id, curve.curve_id) if self._exports_dir else ""
@@ -784,8 +789,8 @@ class CalibrationStore:
                     "table_path": str(
                         self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
                     ),
-                    "curve_330_path": str(
-                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.330"
+                    "curve_cof_path": str(
+                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof"
                     ),
                     "curve_340_path": str(
                         self._curve_340_path(curve.sensor_id, curve.curve_id)
@@ -867,6 +872,34 @@ class CalibrationStore:
             for temperature_k, raw_value in rows:
                 writer.writerow([f"{temperature_k:.9g}", f"{raw_value:.9g}"])
 
+    def _write_cof_export(self, path: Path, curve: CalibrationCurve) -> None:
+        """Write .cof format: header + per-zone raw Chebyshev coefficients."""
+        from cryodaq.core.atomic_write import atomic_write_text
+
+        lines: list[str] = []
+        lines.append("# CryoDAQ calibration curve export .cof")
+        lines.append(f"# sensor_id: {curve.sensor_id}")
+        lines.append(f"# curve_id: {curve.curve_id}")
+        lines.append(f"# raw_unit: {curve.raw_unit}")
+        lines.append(f"# fit_timestamp: {curve.fit_timestamp.isoformat()}")
+        lines.append(
+            "# format: Chebyshev T_n(x), x = 2*(raw - raw_min)/(raw_max - raw_min) - 1"
+        )
+        lines.append(f"# zone_count: {len(curve.zones)}")
+        lines.append("")
+        for index, zone in enumerate(curve.zones, start=1):
+            lines.append(f"[zone {index}]")
+            lines.append(f"raw_min: {zone.raw_min:.12g}")
+            lines.append(f"raw_max: {zone.raw_max:.12g}")
+            lines.append(f"order: {zone.order}")
+            coefficients = ", ".join(f"{value:.12g}" for value in zone.coefficients)
+            lines.append(f"coefficients: {coefficients}")
+            lines.append(f"# rmse_k: {zone.rmse_k:.6g}")
+            lines.append(f"# max_abs_error_k: {zone.max_abs_error_k:.6g}")
+            lines.append(f"# point_count: {zone.point_count}")
+            lines.append("")
+        atomic_write_text(path, "\n".join(lines))
+
     def _import_curve_text(
         self,
         path: Path,
@@ -925,8 +958,6 @@ class CalibrationStore:
             },
         )
         self.save_curve(curve)
-        if import_format == "330":
-            self.export_curve_330(curve.sensor_id)
         if import_format == "340":
             self.export_curve_340(curve.sensor_id)
         return curve

codex
The diff against local `master` confirms `export_curve_340`’s body did not change; the migration replaced `.330` and added `.cof` around it. I’m doing one final verification pass for the exact failure/warning list before preparing the artifact content.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/b066e4a0/skills/verification-before-completion/SKILL.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
---
name: verification-before-completion
description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success claims; evidence before assertions always
---

# Verification Before Completion

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in this message, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | Test command output: 0 failures | Previous run, "should pass" |
| Linter clean | Linter output: 0 errors | Partial check, extrapolation |
| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
| Regression test works | Red-green cycle verified | Test passes once |
| Agent completed | VCS diff shows changes | Agent reports "success" |
| Requirements met | Line-by-line checklist | Tests passing |

## Red Flags - STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!", etc.)
- About to commit/push/PR without verification
- Trusting agent success reports
- Relying on partial verification
- Thinking "just this once"
- Tired and wanting work over
- **ANY wording implying success without having run verification**

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification |
| "I'm confident" | Confidence ≠ evidence |
| "Just this once" | No exceptions |
| "Linter passed" | Linter ≠ compiler |
| "Agent said success" | Verify independently |
| "I'm tired" | Exhaustion ≠ excuse |
| "Partial check is enough" | Partial proves nothing |
| "Different words so rule doesn't apply" | Spirit over letter |

## Key Patterns

**Tests:**
```
✅ [Run test command] [See: 34/34 pass] "All tests pass"
❌ "Should pass now" / "Looks correct"
```

**Regression tests (TDD Red-Green):**
```
✅ Write → Run (pass) → Revert fix → Run (MUST FAIL) → Restore → Run (pass)
❌ "I've written a regression test" (without red-green verification)
```

**Build:**
```
✅ [Run build] [See: exit 0] "Build passes"
❌ "Linter passed" (linter doesn't check compilation)
```

**Requirements:**
```
✅ Re-read plan → Create checklist → Verify each → Report gaps or completion
❌ "Tests pass, phase complete"
```

**Agent delegation:**
```
✅ Agent reports success → Check VCS diff → Verify changes → Report actual state
❌ Trust agent report
```

## Why This Matters

From 24 failure memories:
- your human partner said "I don't believe you" - trust broken
- Undefined functions shipped - would crash
- Missing requirements shipped - incomplete features
- Time wasted on false completion → redirect → rework
- Violates: "Honesty is a core value. If you lie, you'll be replaced."

## When To Apply

**ALWAYS before:**
- ANY variation of success/completion claims
- ANY expression of satisfaction
- ANY positive statement about work state
- Committing, PR creation, task completion
- Moving to next task
- Delegating to agents

**Rule applies to:**
- Exact phrases
- Paraphrases and synonyms
- Implications of success
- ANY communication suggesting completion/correctness

## The Bottom Line

**No shortcuts for verification.**

Run the command. Read the output. THEN claim the result.

This is non-negotiable.

codex
I’m going to replace the requested response file with the audit content now. If the read-only sandbox blocks the write, I’ll return the exact content in the final response and state that the file could not be updated.
2026-04-27T19:35:47.551224Z ERROR codex_core::tools::router: error=patch rejected: writing is blocked by read-only sandbox; rejected by user approval settings
codex
I could not write the file because the session is in a read-only sandbox; the patch was rejected. Audit content:

```md
A1: PASS — `CalibrationStore.export_curve_cof()` exists and calls `_write_cof_export(target, curve)`. [src/cryodaq/analytics/calibration.py:424, src/cryodaq/analytics/calibration.py:440]
A2: PASS — default target is `_curve_directory(...)/"curve.cof"`. [src/cryodaq/analytics/calibration.py:438]
A3: PASS — calls `self._write_index()` before returning. [src/cryodaq/analytics/calibration.py:441]
A4: PASS — returns `target`, the written path. [src/cryodaq/analytics/calibration.py:442]

B1: PASS — header includes all required fields; missing: none. [src/cryodaq/analytics/calibration.py:880]
B2: PASS — each zone writes raw_min, raw_max, order, coefficients; missing: none. [src/cryodaq/analytics/calibration.py:891]
B3: PASS — coefficients use `.12g`, 12 significant digits. [src/cryodaq/analytics/calibration.py:895]
B4: PASS — uses `atomic_write_text`. [src/cryodaq/analytics/calibration.py:877, src/cryodaq/analytics/calibration.py:901]
B5: FAIL — comment says `x = 2*(raw - raw_min)/(raw_max - raw_min) - 1`; evaluate clips first: `clipped = min(max(raw_value, self.raw_min), self.raw_max)` then scales `clipped`. [src/cryodaq/analytics/calibration.py:886, src/cryodaq/analytics/calibration.py:115]

C1: PASS — `export_curve_330` absent from class. [src/cryodaq/analytics/calibration.py:424]
C2: PASS — accepted suffixes exclude `.330`. [src/cryodaq/analytics/calibration.py:376]
C3: PASS — no `import_format == "330"` branch; only `.340` branch remains. [src/cryodaq/analytics/calibration.py:961]
C4: PASS — uses `curve_cof_path`. [src/cryodaq/analytics/calibration.py:486]
C5: PASS — `_write_index()` uses `curve_cof_path`. [src/cryodaq/analytics/calibration.py:792]

D1: PASS — `export_curve_340()` still present; local diff vs `master` shows no body changes. [src/cryodaq/analytics/calibration.py:444]
D2: PASS — `.340` still accepted. [src/cryodaq/analytics/calibration.py:379]

E1: PASS — asserts exists, suffix, and header/structure content. [tests/analytics/test_calibration.py:292]
E2: PASS — verifies all zones via length equality and `zip(..., strict=True)`. [tests/analytics/test_calibration.py:322]
E3: PASS — adequate: removed API should be absent, so call behavior is not expected. [tests/analytics/test_calibration.py:359]
E4: PASS — file has 4 rows, but suffix rejection happens before row-count parsing. [tests/analytics/test_calibration.py:368, src/cryodaq/analytics/calibration.py:376]
E5: PASS — calls `export_curve_340`, not `export_curve_330`. [tests/analytics/test_calibration.py:200]

F1: PASS — default path calls `_curve_directory()`, which raises `RuntimeError` when `base_dir=None`; right behavior for no default artifact directory. [src/cryodaq/analytics/calibration.py:438, src/cryodaq/analytics/calibration.py:721]

| ID | Severity | Finding |
|---|---|---|
| B5 | LOW | `.cof` format comment omits the clipping step used by `CalibrationZone.evaluate()`, so out-of-zone raw values may be evaluated differently by consumers following the comment literally. |

VERDICT: CONDITIONAL
```
tokens used
56 137
I could not write the file because the session is in a read-only sandbox; the patch was rejected. Audit content:

```md
A1: PASS — `CalibrationStore.export_curve_cof()` exists and calls `_write_cof_export(target, curve)`. [src/cryodaq/analytics/calibration.py:424, src/cryodaq/analytics/calibration.py:440]
A2: PASS — default target is `_curve_directory(...)/"curve.cof"`. [src/cryodaq/analytics/calibration.py:438]
A3: PASS — calls `self._write_index()` before returning. [src/cryodaq/analytics/calibration.py:441]
A4: PASS — returns `target`, the written path. [src/cryodaq/analytics/calibration.py:442]

B1: PASS — header includes all required fields; missing: none. [src/cryodaq/analytics/calibration.py:880]
B2: PASS — each zone writes raw_min, raw_max, order, coefficients; missing: none. [src/cryodaq/analytics/calibration.py:891]
B3: PASS — coefficients use `.12g`, 12 significant digits. [src/cryodaq/analytics/calibration.py:895]
B4: PASS — uses `atomic_write_text`. [src/cryodaq/analytics/calibration.py:877, src/cryodaq/analytics/calibration.py:901]
B5: FAIL — comment says `x = 2*(raw - raw_min)/(raw_max - raw_min) - 1`; evaluate clips first: `clipped = min(max(raw_value, self.raw_min), self.raw_max)` then scales `clipped`. [src/cryodaq/analytics/calibration.py:886, src/cryodaq/analytics/calibration.py:115]

C1: PASS — `export_curve_330` absent from class. [src/cryodaq/analytics/calibration.py:424]
C2: PASS — accepted suffixes exclude `.330`. [src/cryodaq/analytics/calibration.py:376]
C3: PASS — no `import_format == "330"` branch; only `.340` branch remains. [src/cryodaq/analytics/calibration.py:961]
C4: PASS — uses `curve_cof_path`. [src/cryodaq/analytics/calibration.py:486]
C5: PASS — `_write_index()` uses `curve_cof_path`. [src/cryodaq/analytics/calibration.py:792]

D1: PASS — `export_curve_340()` still present; local diff vs `master` shows no body changes. [src/cryodaq/analytics/calibration.py:444]
D2: PASS — `.340` still accepted. [src/cryodaq/analytics/calibration.py:379]

E1: PASS — asserts exists, suffix, and header/structure content. [tests/analytics/test_calibration.py:292]
E2: PASS — verifies all zones via length equality and `zip(..., strict=True)`. [tests/analytics/test_calibration.py:322]
E3: PASS — adequate: removed API should be absent, so call behavior is not expected. [tests/analytics/test_calibration.py:359]
E4: PASS — file has 4 rows, but suffix rejection happens before row-count parsing. [tests/analytics/test_calibration.py:368, src/cryodaq/analytics/calibration.py:376]
E5: PASS — calls `export_curve_340`, not `export_curve_330`. [tests/analytics/test_calibration.py:200]

F1: PASS — default path calls `_curve_directory()`, which raises `RuntimeError` when `base_dir=None`; right behavior for no default artifact directory. [src/cryodaq/analytics/calibration.py:438, src/cryodaq/analytics/calibration.py:721]

| ID | Severity | Finding |
|---|---|---|
| B5 | LOW | `.cof` format comment omits the clipping step used by `CalibrationZone.evaluate()`, so out-of-zone raw values may be evaluated differently by consumers following the comment literally. |

VERDICT: CONDITIONAL
```
