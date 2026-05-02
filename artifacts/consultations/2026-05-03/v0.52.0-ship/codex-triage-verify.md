OpenAI Codex v0.124.0 (research preview)
--------
workdir: /Users/vladimir/Projects/cryodaq
model: gpt-5.5
provider: openai
approval: never
sandbox: read-only
reasoning effort: medium
reasoning summaries: none
session id: 019dea73-3541-7b73-b5bd-4c4e71c1fc2a
--------
user
CryoDAQ analytics tab empty plots — independent diagnostic verification.

Context: User reports Analytics tab shows empty plots on "Отладочная проверка-001"
(debug experiment, currently in cooldown phase, system physically at base temperature
T_cold≈4K). Engine is running. Header shows live values. Question: bug or expected?

CC's triage diagnosis: Expected behavior (A) for 3 of 4 plots. Transient for 1.

Verify CC's diagnosis by examining the following files and recon findings:

## Recon findings (CC ran these)

1. Branch: master at 3890dcc (v0.52.0 merged). Clean.
2. Experiment cc35331d8c89, current_phase="cooldown", status=RUNNING.
   Physical temps: T_cold≈3.89K, T_warm≈4.5K (BASE TEMPERATURE).
3. analytics_layout.yaml: cooldown phase → main=cooldown_prediction,
   top_right=temperature_overview, bottom_right=r_thermal_placeholder.
   "vacuum_prediction" widget NOT in cooldown phase layout.
4. SQLite: 0 readings in last 60s BUT max_ts=161s ago → engine running, writing normally.
5. ZMQ: engine writing to SQLite → broker presumed publishing. Header shows live values.
6. Widget wiring: main_window_v2:414 routes K-unit readings to analytics_view.set_temperature_readings().
   main_window_v2:448-484 routes analytics channels to set_cooldown().
   main_window_v2:662 calls analytics_view.set_phase().
7. F-P diff: zero changes to existing widget class bodies. No regression possible.
8. Integration tests: 9/9 PASS including temperature forwarding and r_thermal_placeholder.

## Verify the following specific code paths

1. CooldownService._do_predict() — what happens when T_cold≈4K (base temp)?
   Does it set cooldown_active=False? Does it publish? Does CooldownPredictionWidget
   receive valid data or nothing?
   File: src/cryodaq/analytics/cooldown_service.py

2. TemperatureOverviewWidget._fetch_history() — what ZMQ command does it issue?
   Can the result be empty persistently (not just on first open)?
   What is the `from_ts` range? Does it filter by experiment_id?
   File: src/cryodaq/gui/shell/views/analytics_widgets.py ~line 326

3. The readings_history ZMQ command handler in the engine — does it filter by
   experiment? Does it query only the current daily DB or all DBs in range?
   File: src/cryodaq/engine.py (grep for "readings_history")

4. Does TemperatureOverviewWidget show an empty-state label when no data, or is it
   truly blank (no visual feedback)?
   File: src/cryodaq/gui/shell/views/analytics_widgets.py ~line 396-400

## Questions for verifier

A. Is CC's diagnosis correct: cooldown_active=False at base temp → CooldownPredictionWidget
   empty = expected? Or is there a code path that should still show something?

B. Is TemperatureOverviewWidget PERSISTENTLY empty possible (not just transient)?
   Specifically: if readings_history returns 0 results AND no live readings arrive
   within the time window — can this happen in normal ops?

C. Did F-P changes introduce any regression in TemperatureOverviewWidget or
   CooldownPredictionWidget? (diff: analytics_widgets.py v0.51.0..v0.52.0)

D. Is there any operator-visible indicator in the empty CooldownPredictionWidget
   that explains WHY it's empty (e.g. "Ожидание охлаждения...")? Or is it blank?

Severity: P0 (if persistent bug), P1 (if UX gap), P2 (if expected behavior only).
Report findings. Do not echo this prompt.
exec
/opt/homebrew/bin/bash -lc 'cat /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/3c46336323290cda7c90d78e7a0134f47cc73713/skills/using-superpowers/SKILL.md && cat /Users/vladimir/.agents/skills/omc-reference/SKILL.md | head -80' in /Users/vladimir/Projects/cryodaq
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
---
name: omc-reference
description: OMC agent catalog, available tools, team pipeline routing, commit protocol, and skills registry. Auto-loads when delegating to agents, using OMC tools, orchestrating teams, making commits, or invoking skills.
user-invocable: false
---

# OMC Reference

Use this built-in reference when you need detailed OMC catalog information that does not need to live in every `AGENTS.md` session.

## Agent Catalog

Prefix: `oh-my-Codex:`. See `agents/*.md` for full prompts.

- `explore` (haiku) — fast codebase search and mapping
- `analyst` (opus) — requirements clarity and hidden constraints
- `planner` (opus) — sequencing and execution plans
- `architect` (opus) — system design, boundaries, and long-horizon tradeoffs
- `debugger` (sonnet) — root-cause analysis and failure diagnosis
- `executor` (sonnet) — implementation and refactoring
- `verifier` (sonnet) — completion evidence and validation
- `tracer` (sonnet) — trace gathering and evidence capture
- `security-reviewer` (sonnet) — trust boundaries and vulnerabilities
- `code-reviewer` (opus) — comprehensive code review
- `test-engineer` (sonnet) — testing strategy and regression coverage
- `designer` (sonnet) — UX and interaction design
- `writer` (haiku) — documentation and concise content work
- `qa-tester` (sonnet) — runtime/manual validation
- `scientist` (sonnet) — data analysis and statistical reasoning
- `document-specialist` (sonnet) — SDK/API/framework documentation lookup
- `git-master` (sonnet) — commit strategy and history hygiene
- `code-simplifier` (opus) — behavior-preserving simplification
- `critic` (opus) — plan/design challenge and review

## Model Routing

- `haiku` — quick lookups, lightweight inspection, narrow docs work
- `sonnet` — standard implementation, debugging, and review
- `opus` — architecture, deep analysis, consensus planning, and high-risk review

## Tools Reference

### External AI / orchestration
- `/team N:executor "task"`
- `omc team N:codex|gemini "..."`
- `omc ask <Codex|codex|gemini>`
- `/ccg`

### OMC state
- `state_read`, `state_write`, `state_clear`, `state_list_active`, `state_get_status`

### Team runtime
- `TeamCreate`, `TeamDelete`, `SendMessage`, `TaskCreate`, `TaskList`, `TaskGet`, `TaskUpdate`

### Notepad
- `notepad_read`, `notepad_write_priority`, `notepad_write_working`, `notepad_write_manual`

### Project memory
- `project_memory_read`, `project_memory_write`, `project_memory_add_note`, `project_memory_add_directive`

### Code intelligence
- LSP: `lsp_hover`, `lsp_goto_definition`, `lsp_find_references`, `lsp_diagnostics`, and related helpers
- AST: `ast_grep_search`, `ast_grep_replace`
- Utility: `python_repl`

## Skills Registry

Invoke built-in workflows via `/oh-my-Codex:<name>`.

### Workflow skills
- `autopilot` — full autonomous execution from idea to working code
- `ralph` — persistence loop until completion with verification
- `ultrawork` — high-throughput parallel execution
- `visual-verdict` — structured visual QA verdicts
- `team` — coordinated team orchestration
- `ccg` — Codex + Gemini + Codex synthesis lane
- `ultraqa` — QA cycle: test, verify, fix, repeat
- `omc-plan` — planning workflow and `/plan`-safe alias
- `ralplan` — consensus planning workflow
- `sciomc` — science/research workflow

exec
/opt/homebrew/bin/bash -lc "git status --short && git rev-parse HEAD && sed -n '1,260p' src/cryodaq/analytics/cooldown_service.py && sed -n '300,430p' src/cryodaq/gui/shell/views/analytics_widgets.py && grep -R \"readings_history\" -n src/cryodaq/engine.py src/cryodaq | head -20" in /Users/vladimir/Projects/cryodaq
 succeeded in 231ms:
3890dcc1e5df2346c3b92d9748ee6717eafde9d1
"""Сервис прогнозирования охлаждения для CryoDAQ Engine.

Интегрирует cooldown_predictor с DataBroker:
- CooldownDetector: определяет начало/конец цикла охлаждения
- CooldownService: asyncio-сервис, подписывается на брокер,
  периодически вызывает predict(), публикует DerivedMetric
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from cryodaq.analytics.base_plugin import DerivedMetric
from cryodaq.analytics.cooldown_predictor import (
    EnsembleModel,
    compute_rate_from_history,
    ingest_from_raw_arrays,
    load_model,
    predict,
)
from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)


# ============================================================================
# Cooldown detector: state machine for cycle detection
# ============================================================================


class CooldownPhase(Enum):
    """Фаза цикла охлаждения."""

    IDLE = "idle"
    COOLING = "cooling"
    STABILIZING = "stabilizing"
    COMPLETE = "complete"


class CooldownDetector:
    """Определяет начало/конец цикла охлаждения по потоку данных.

    Переходы состояний:
        IDLE -> COOLING: dT_cold/dt < start_rate_threshold в течение confirm_minutes
        COOLING -> STABILIZING: T_cold < end_T_threshold
        STABILIZING -> COMPLETE: |dT/dt| < end_rate_threshold в течение confirm_minutes
        COMPLETE -> IDLE: после вызова reset() (auto-ingest завершён)
    """

    def __init__(
        self,
        start_rate_threshold: float = -5.0,
        start_confirm_minutes: float = 10.0,
        end_T_cold_threshold: float = 6.0,
        end_rate_threshold: float = 0.1,
        end_confirm_minutes: float = 30.0,
    ) -> None:
        self._start_rate_thr = start_rate_threshold
        self._start_confirm_s = start_confirm_minutes * 60.0
        self._end_T_thr = end_T_cold_threshold
        self._end_rate_thr = end_rate_threshold
        self._end_confirm_s = end_confirm_minutes * 60.0

        self._phase = CooldownPhase.IDLE
        self._confirm_start_ts: float | None = None
        self._confirm_end_ts: float | None = None
        self._cooldown_start_ts: float | None = None

        # Sliding window for dT/dt estimation (last 5 min)
        self._recent: deque[tuple[float, float]] = deque(maxlen=60)

    @property
    def phase(self) -> CooldownPhase:
        return self._phase

    @property
    def cooldown_start_ts(self) -> float | None:
        return self._cooldown_start_ts

    def reset(self) -> None:
        """Сброс в IDLE (после auto-ingest)."""
        self._phase = CooldownPhase.IDLE
        self._confirm_start_ts = None
        self._confirm_end_ts = None
        self._cooldown_start_ts = None
        self._recent.clear()

    def update(self, ts: float, T_cold: float) -> CooldownPhase:
        """Обновить состояние детектора по новому показанию.

        Args:
            ts: монотонное время (time.monotonic()) в секундах
            T_cold: текущая температура холодной ступени, K

        Returns:
            Текущая фаза после обновления.
        """
        self._recent.append((ts, T_cold))

        # Estimate dT/dt from recent window
        dT_dt = self._estimate_rate()

        if self._phase == CooldownPhase.IDLE:
            if dT_dt is not None and dT_dt < self._start_rate_thr:
                if self._confirm_start_ts is None:
                    self._confirm_start_ts = ts
                elif ts - self._confirm_start_ts >= self._start_confirm_s:
                    self._phase = CooldownPhase.COOLING
                    self._cooldown_start_ts = self._confirm_start_ts
                    self._confirm_start_ts = None
                    logger.info(
                        "Обнаружено начало охлаждения: dT/dt=%.1f K/ч, T_cold=%.1f K",
                        dT_dt,
                        T_cold,
                    )
            else:
                self._confirm_start_ts = None

        elif self._phase == CooldownPhase.COOLING:
            if T_cold < self._end_T_thr:
                self._phase = CooldownPhase.STABILIZING
                logger.info(
                    "Охлаждение -> стабилизация: T_cold=%.2f K < %.1f K",
                    T_cold,
                    self._end_T_thr,
                )

        elif self._phase == CooldownPhase.STABILIZING:
            if dT_dt is not None and abs(dT_dt) < self._end_rate_thr:
                if self._confirm_end_ts is None:
                    self._confirm_end_ts = ts
                elif ts - self._confirm_end_ts >= self._end_confirm_s:
                    self._phase = CooldownPhase.COMPLETE
                    self._confirm_end_ts = None
                    logger.info(
                        "Охлаждение завершено: T_cold=%.2f K, |dT/dt|=%.3f K/ч",
                        T_cold,
                        abs(dT_dt) if dT_dt else 0.0,
                    )
            else:
                self._confirm_end_ts = None

        return self._phase

    def _estimate_rate(self) -> float | None:
        """Оценить dT/dt [K/ч] по скользящему окну."""
        if len(self._recent) < 5:
            return None
        ts_arr = [p[0] for p in self._recent]
        T_arr = [p[1] for p in self._recent]
        dt_s = ts_arr[-1] - ts_arr[0]
        if dt_s < 30.0:
            return None
        dT = T_arr[-1] - T_arr[0]
        # Convert to K/h
        return dT / (dt_s / 3600.0)


# ============================================================================
# CooldownService: asyncio integration with DataBroker
# ============================================================================


class CooldownService:
    """Асинхронный сервис прогнозирования охлаждения.

    Подписывается на DataBroker, собирает данные каналов cold/warm
    в кольцевой буфер, периодически вызывает predict() и публикует
    DerivedMetric через ZMQ.
    """

    def __init__(
        self,
        broker: DataBroker,
        config: dict[str, Any],
        model_dir: Path,
    ) -> None:
        self._broker = broker
        self._config = config
        self._model_dir = model_dir

        self._channel_cold: str = config.get("channel_cold", "")
        self._channel_warm: str = config.get("channel_warm", "")
        self._predict_interval_s: float = float(config.get("predict_interval_s", 30))
        self._rate_window_h: float = float(config.get("rate_window_h", 1.5))
        self._auto_ingest: bool = bool(config.get("auto_ingest", True))
        self._min_cooldown_hours: float = float(config.get("min_cooldown_hours", 10.0))

        # Detector config
        det_cfg = config.get("detect", {})
        self._detector = CooldownDetector(
            start_rate_threshold=float(det_cfg.get("start_rate_threshold", -5.0)),
            start_confirm_minutes=float(det_cfg.get("start_confirm_minutes", 10)),
            end_T_cold_threshold=float(det_cfg.get("end_T_cold_threshold", 6.0)),
            end_rate_threshold=float(det_cfg.get("end_rate_threshold", 0.1)),
            end_confirm_minutes=float(det_cfg.get("end_confirm_minutes", 30)),
        )

        # Ring buffer: (t_hours_from_start, T_cold, T_warm)
        self._buffer: deque[tuple[float, float, float]] = deque(maxlen=100_000)
        self._cooldown_wall_start: float | None = None

        # Model
        self._model: EnsembleModel | None = None

        # Queue & tasks
        self._queue: asyncio.Queue | None = None
        self._consume_task: asyncio.Task | None = None
        self._predict_task: asyncio.Task | None = None
        self._running = False

        # Latest T values for detector
        self._last_T_cold: float | None = None
        self._last_T_warm: float | None = None

        # Cached prediction for query agent (F30)
        self._last_prediction: dict[str, Any] | None = None

    @property
    def phase(self) -> CooldownPhase:
        return self._detector.phase

    def last_prediction(self) -> dict[str, Any] | None:
        """Return last computed prediction metadata, or None if not yet predicted."""
        return self._last_prediction

    async def start(self) -> None:
        """Запустить сервис: подписка на брокер, загрузка модели, запуск задач."""
        if self._running:
            return

        channels = {self._channel_cold, self._channel_warm}

        def _filter(reading: Reading) -> bool:
            return reading.channel in channels

        self._queue = await self._broker.subscribe(
            "cooldown_service",
            maxsize=5000,
            filter_fn=_filter,
        )

        # Load model (in executor, may be slow)
        loop = asyncio.get_running_loop()
        try:
            model_file = self._model_dir / "predictor_model.json"
            if model_file.exists():
                self._model = await loop.run_in_executor(None, load_model, self._model_dir)
                logger.info(
                    "Модель охлаждения загружена: %d кривых, %.1f +/- %.1f ч",
                    self._model.n_curves,
        self._graphics.setBackground(theme.PLOT_BG)
        self._empty_label = _muted_label("Ожидание данных…")
        lay.addWidget(self._empty_label)
        lay.addWidget(self._graphics, stretch=1)
        self._graphics.setVisible(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    def _get_or_create_group_plot(self, group: str) -> pg.PlotItem:
        """Return the PlotItem for *group*, creating it if needed."""
        if group in self._group_plots:
            return self._group_plots[group]
        pi = self._graphics.addPlot(row=self._next_row, col=0)
        pi.showGrid(x=True, y=True, alpha=0.3)
        label = group if group else "Температура"
        pi.setLabel("left", label, units="K", color=theme.PLOT_LABEL_COLOR)
        pi.getAxis("left").enableAutoSIPrefix(False)
        date_axis = pg.DateAxisItem(orientation="bottom")
        pi.setAxisItems({"bottom": date_axis})
        pi.addLegend(offset=(10, 10))
        # Link x-axis so all groups scroll / zoom together.
        if self._group_plots:
            pi.setXLink(next(iter(self._group_plots.values())))
        self._group_plots[group] = pi
        self._next_row += 1
        return pi

    def _fetch_history(self) -> None:
        """Issue a readings_history ZMQ command for all cold channels (spec §4.1)."""
        import time

        from cryodaq.gui.zmq_client import ZmqCommandWorker

        channels = self._channel_mgr.get_cold_channels() or None
        cmd = {
            "cmd": "readings_history",
            "from_ts": time.time() - 7 * 24 * 3600,
            "to_ts": time.time(),
            "channels": channels,
            "limit_per_channel": 5000,
        }
        self._history_worker = ZmqCommandWorker(cmd, parent=self)
        self._history_worker.finished.connect(self._on_history_loaded)
        self._history_worker.start()

    @Slot(dict)
    def _on_history_loaded(self, result: dict) -> None:
        """Merge engine history response; sort each series by timestamp."""
        if not result.get("ok"):
            return
        data: dict[str, list] = result.get("data", {})
        for channel, points in data.items():
            if not points:
                continue
            series = self._series.setdefault(channel, _ChannelSeries())
            for entry in points:
                series.xs.append(float(entry[0]))
                series.ys.append(float(entry[1]))
        # Sort by timestamp: history may arrive after F4 live-stream replay,
        # producing out-of-order points if not sorted.
        for series in self._series.values():
            if len(series.xs) > 1:
                pairs = sorted(zip(series.xs, series.ys))
                series.xs[:] = [p[0] for p in pairs]
                series.ys[:] = [p[1] for p in pairs]
        self._refresh_all_curves()
        self._update_empty_state()

    def set_temperature_readings(self, readings: dict[str, Reading]) -> None:
        """Append live broker readings (spec §4.1 live stream)."""
        for ch_id, reading in readings.items():
            series = self._series.setdefault(ch_id, _ChannelSeries())
            series.xs.append(reading.timestamp.timestamp())
            series.ys.append(float(reading.value))
            max_pts = 5000
            if len(series.xs) > max_pts:
                del series.xs[: len(series.xs) - max_pts]
                del series.ys[: len(series.ys) - max_pts]
            self._update_curve(ch_id)
        self._update_empty_state()

    def _update_curve(self, ch_id: str) -> None:
        series = self._series.get(ch_id)
        if series is None:
            return
        group = self._channel_mgr.get_group(ch_id)
        pi = self._get_or_create_group_plot(group)
        if ch_id not in self._curves:
            pen = series_pen(len(self._curves))
            name = self._channel_mgr.get_name(ch_id) or ch_id
            curve = pi.plot([], [], pen=pen, name=name)
            self._curves[ch_id] = curve
        self._curves[ch_id].setData(x=series.xs, y=series.ys)

    def _refresh_all_curves(self) -> None:
        for ch_id in self._series:
            self._update_curve(ch_id)

    def _update_empty_state(self) -> None:
        has_data = any(s.xs for s in self._series.values())
        self._empty_label.setHidden(has_data)
        self._graphics.setHidden(not has_data)


class VacuumPredictionWidget(QWidget):
    """Log-Y prediction widget for vacuum pressure forecast (F-P2).

    Self-contained: accumulates raw pressure readings via
    :meth:`set_pressure_reading` and polls the engine every 10 s via
    ``get_vacuum_trend`` to obtain the extrapolated P(t) projection.
    Converts relative-time extrapolation arrays to absolute unix
    timestamps so the inner :class:`PredictionWidget` date axis works
    correctly.  Confidence band = ±1σ from ``residual_std`` (log₁₀
    units), converted to mbar.
    """

    _MAX_RAW_PTS: int = 5000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._inner = PredictionWidget(
            title="Прогноз вакуума",
            y_label="Давление",
            y_unit="мбар",
            log_y=True,
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._inner)
src/cryodaq/engine.py:507:            t_hist = await writer.read_readings_history(
src/cryodaq/engine.py:1789:            if action == "readings_history":
src/cryodaq/engine.py:1795:                data = await writer.read_readings_history(
src/cryodaq/agents/assistant/live/context_builder.py:216:        if not channels or not hasattr(self._reader, "read_readings_history"):
src/cryodaq/agents/assistant/live/context_builder.py:221:                await self._reader.read_readings_history(
src/cryodaq/agents/assistant/live/context_builder.py:241:        if not hasattr(self._reader, "read_readings_history"):
src/cryodaq/agents/assistant/live/context_builder.py:246:                await self._reader.read_readings_history(
Binary file src/cryodaq/agents/assistant/live/__pycache__/context_builder.cpython-314.pyc matches
src/cryodaq/agents/assistant/query/adapters/sqlite_adapter.py:26:        if not hasattr(self._reader, "read_readings_history"):
src/cryodaq/agents/assistant/query/adapters/sqlite_adapter.py:32:                await self._reader.read_readings_history(
Binary file src/cryodaq/agents/assistant/query/adapters/__pycache__/sqlite_adapter.cpython-314.pyc matches
Binary file src/cryodaq/agents/__pycache__/context_builder.cpython-314.pyc matches
Binary file src/cryodaq/__pycache__/engine.cpython-314.pyc matches
Binary file src/cryodaq/storage/__pycache__/sqlite_writer.cpython-314.pyc matches
src/cryodaq/storage/sqlite_writer.py:691:    def _read_readings_history(
src/cryodaq/storage/sqlite_writer.py:766:    async def read_readings_history(
src/cryodaq/storage/sqlite_writer.py:774:        """Async wrapper for _read_readings_history."""
src/cryodaq/storage/sqlite_writer.py:777:            self._read_readings_history,
src/cryodaq/engine.py:507:            t_hist = await writer.read_readings_history(
src/cryodaq/engine.py:1789:            if action == "readings_history":

exec
/opt/homebrew/bin/bash -lc "grep -n \"def _do_predict\\|def _consume\\|DerivedMetric\\|cooldown_active\\|set_cooldown\\|class CooldownPredictionWidget\\|class TemperatureOverviewWidget\" -n src/cryodaq/analytics/cooldown_service.py src/cryodaq/gui/shell/views/analytics_widgets.py && sed -n '250,430p' src/cryodaq/analytics/cooldown_service.py && sed -n '1,180p' src/cryodaq/gui/shell/views/analytics_widgets.py && sed -n '1780,1810p' src/cryodaq/engine.py && sed -n '660,745p' src/cryodaq/storage/sqlite_writer.py && sed -n '745,790p' src/cryodaq/storage/sqlite_writer.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/analytics/cooldown_service.py:6:  периодически вызывает predict(), публикует DerivedMetric
src/cryodaq/analytics/cooldown_service.py:21:from cryodaq.analytics.base_plugin import DerivedMetric
src/cryodaq/analytics/cooldown_service.py:178:    DerivedMetric через ZMQ.
src/cryodaq/analytics/cooldown_service.py:300:    async def _consume_loop(self) -> None:
src/cryodaq/analytics/cooldown_service.py:345:        """Периодически вызывать predict() и публиковать DerivedMetric."""
src/cryodaq/analytics/cooldown_service.py:353:    async def _do_predict(self) -> None:
src/cryodaq/analytics/cooldown_service.py:359:        cooldown_active = phase in (CooldownPhase.COOLING, CooldownPhase.STABILIZING)
src/cryodaq/analytics/cooldown_service.py:367:        if self._cooldown_wall_start is not None and cooldown_active:
src/cryodaq/analytics/cooldown_service.py:413:            "cooldown_active": cooldown_active,
src/cryodaq/analytics/cooldown_service.py:426:        # Publish DerivedMetric
src/cryodaq/analytics/cooldown_service.py:427:        DerivedMetric.now(
src/cryodaq/gui/shell/views/analytics_widgets.py:203:class TemperatureOverviewWidget(QWidget):
src/cryodaq/gui/shell/views/analytics_widgets.py:515:class CooldownPredictionWidget(QWidget):
src/cryodaq/gui/shell/views/analytics_widgets.py:530:    def set_cooldown_data(self, data) -> None:
        )

        # Load model (in executor, may be slow)
        loop = asyncio.get_running_loop()
        try:
            model_file = self._model_dir / "predictor_model.json"
            if model_file.exists():
                self._model = await loop.run_in_executor(None, load_model, self._model_dir)
                logger.info(
                    "Модель охлаждения загружена: %d кривых, %.1f +/- %.1f ч",
                    self._model.n_curves,
                    self._model.duration_mean,
                    self._model.duration_std,
                )
            else:
                logger.warning(
                    "Файл модели не найден: %s — прогнозирование недоступно",
                    model_file,
                )
        except Exception as exc:
            logger.error("Ошибка загрузки модели охлаждения: %s", exc)

        self._running = True
        self._consume_task = asyncio.create_task(
            self._consume_loop(),
            name="cooldown_consume",
        )
        self._predict_task = asyncio.create_task(
            self._predict_loop(),
            name="cooldown_predict",
        )
        logger.info("CooldownService запущен")

    async def stop(self) -> None:
        """Остановить сервис: отмена задач, отписка от брокера."""
        if not self._running:
            return
        self._running = False

        for task in (self._consume_task, self._predict_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await self._broker.unsubscribe("cooldown_service")
        logger.info("CooldownService остановлен")

    async def _consume_loop(self) -> None:
        """Читать показания из очереди брокера и обновлять буфер/детектор."""
        try:
            while self._running:
                try:
                    reading: Reading = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=5.0,
                    )
                except TimeoutError:
                    continue

                reading_ts = reading.timestamp.timestamp()

                if reading.channel == self._channel_cold:
                    self._last_T_cold = reading.value
                    # Update detector (use reading timestamp for correct dT/dt)
                    self._detector.update(reading_ts, reading.value)
                elif reading.channel == self._channel_warm:
                    self._last_T_warm = reading.value

                # Buffer data during cooldown
                phase = self._detector.phase
                if phase in (CooldownPhase.COOLING, CooldownPhase.STABILIZING):
                    if self._cooldown_wall_start is None:
                        self._cooldown_wall_start = reading_ts

                    t_hours = (reading_ts - self._cooldown_wall_start) / 3600.0
                    T_cold = self._last_T_cold if self._last_T_cold is not None else float("nan")
                    T_warm = self._last_T_warm if self._last_T_warm is not None else float("nan")
                    self._buffer.append((t_hours, T_cold, T_warm))

                elif phase == CooldownPhase.COMPLETE:
                    await self._on_cooldown_end()

                elif phase == CooldownPhase.IDLE:
                    # Clear buffer if we're idle
                    if self._buffer:
                        self._buffer.clear()
                        self._cooldown_wall_start = None

        except asyncio.CancelledError:
            return

    async def _predict_loop(self) -> None:
        """Периодически вызывать predict() и публиковать DerivedMetric."""
        try:
            while self._running:
                await asyncio.sleep(self._predict_interval_s)
                await self._do_predict()
        except asyncio.CancelledError:
            return

    async def _do_predict(self) -> None:
        """Выполнить прогнозирование и опубликовать результат."""
        if self._model is None:
            return

        phase = self._detector.phase
        cooldown_active = phase in (CooldownPhase.COOLING, CooldownPhase.STABILIZING)

        T_cold = self._last_T_cold
        T_warm = self._last_T_warm
        if T_cold is None or T_warm is None:
            return

        # Compute elapsed time
        if self._cooldown_wall_start is not None and cooldown_active:
            t_elapsed = (time.time() - self._cooldown_wall_start) / 3600.0
        else:
            t_elapsed = 0.0

        # Compute observed rates from buffer
        rate_cold: float | None = None
        rate_warm: float | None = None
        if len(self._buffer) >= 20:
            buf_arr = np.array(list(self._buffer))
            t_h = buf_arr[:, 0]
            Tc = buf_arr[:, 1]
            Tw = buf_arr[:, 2]
            rate_cold, rate_warm = compute_rate_from_history(
                t_h,
                Tc,
                Tw,
                window_h=self._rate_window_h,
            )

        # Run predict in executor (scipy is CPU-heavy)
        loop = asyncio.get_running_loop()
        try:
            pred = await loop.run_in_executor(
                None,
                lambda: predict(
                    self._model,
                    T_cold,
                    T_warm,
                    t_elapsed=t_elapsed,
                    generate_trajectory=True,
                    observed_rate_cold=rate_cold,
                    observed_rate_warm=rate_warm,
                ),
            )
        except Exception as exc:
            logger.error("Ошибка прогнозирования охлаждения: %s", exc)
            return

        # Build metadata
        metadata: dict[str, Any] = {
            "t_remaining_hours": pred.t_remaining_hours,
            "t_remaining_ci68": (pred.t_remaining_low_68, pred.t_remaining_high_68),
            "progress": pred.progress,
            "phase": pred.phase,
            "n_references": pred.n_references,
            "cooldown_active": cooldown_active,
            "cooldown_start_ts": self._detector.cooldown_start_ts or 0,
            "T_cold": T_cold,
            "T_warm": T_warm,
        }
        self._last_prediction = metadata  # cache for F30 query agent

        if pred.future_t is not None:
            metadata["future_t"] = pred.future_t.tolist()
            metadata["future_T_cold_mean"] = pred.future_T_cold_mean.tolist()
            metadata["future_T_cold_upper"] = pred.future_T_cold_upper.tolist()
            metadata["future_T_cold_lower"] = pred.future_T_cold_lower.tolist()

        # Publish DerivedMetric
        DerivedMetric.now(
            plugin_id="cooldown_predictor",
            metric="cooldown_eta",
            value=pred.t_remaining_hours,
"""Analytics widget registry — keyed by YAML config ID.

Each widget is a self-contained QWidget with setter methods for its
specific data type(s). :class:`AnalyticsView` composes widgets per
``config/analytics_layout.yaml``.

Widgets without live data pipelines yet render a placeholder card —
layout stays coherent while data wiring catches up.

Phase III.C contract:
- Widget IDs in this module map 1:1 to YAML ``phases[<phase>].main``,
  ``top_right``, ``bottom_right`` values.
- Widgets declare setter methods whose names :class:`AnalyticsView`
  uses via duck-typing to forward shell data pushes. Unimplemented
  setters are simply skipped.
- All widgets use DS v1.0.1 tokens only. Interactive chrome (buttons,
  focus rings) uses Phase III.A ``ACCENT`` / ``SELECTION_BG`` /
  ``FOCUS_RING`` — never the status tier.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from cryodaq.analytics.steady_state import SteadyStatePredictor
from cryodaq.core.channel_manager import get_channel_manager
from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui._plot_style import apply_plot_style, series_pen
from cryodaq.gui.shell.overlays.alarm_panel import SeverityChip
from cryodaq.gui.state.time_window import (
    TimeWindow,
    get_time_window_controller,
)
from cryodaq.gui.widgets.shared.prediction_widget import PredictionWidget
from cryodaq.gui.widgets.shared.pressure_plot import PressurePlot

# ---------------------------------------------------------------------------
# Widget IDs — must match YAML
# ---------------------------------------------------------------------------

WIDGET_TEMPERATURE_OVERVIEW = "temperature_overview"
WIDGET_VACUUM_PREDICTION = "vacuum_prediction"
WIDGET_COOLDOWN_PREDICTION = "cooldown_prediction"
WIDGET_R_THERMAL_LIVE = "r_thermal_live"
WIDGET_PRESSURE_CURRENT = "pressure_current"
WIDGET_SENSOR_HEALTH_SUMMARY = "sensor_health_summary"
WIDGET_KEITHLEY_POWER = "keithley_power"
WIDGET_R_THERMAL_PLACEHOLDER = "r_thermal_placeholder"
WIDGET_TEMPERATURE_TRAJECTORY = "temperature_trajectory"
WIDGET_COOLDOWN_HISTORY = "cooldown_history"
WIDGET_EXPERIMENT_SUMMARY = "experiment_summary"

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_registry: dict[str, Callable[[], QWidget]] = {}


def register(widget_id: str, factory: Callable[[], QWidget]) -> None:
    _registry[widget_id] = factory


def create(widget_id: str | None) -> QWidget | None:
    if widget_id is None:
        return None
    factory = _registry.get(widget_id)
    if factory is None:
        raise KeyError(f"Analytics widget not registered: {widget_id}")
    widget = factory()
    # Tag the instance with its registry ID so AnalyticsView can
    # decide whether a re-layout should keep or replace an existing
    # widget.
    widget.setProperty("analytics_widget_id", widget_id)
    return widget


def id_of(widget: QWidget | None) -> str | None:
    if widget is None:
        return None
    val = widget.property("analytics_widget_id")
    return str(val) if val else None


def available_ids() -> list[str]:
    return sorted(_registry.keys())


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _card(object_name: str) -> QFrame:
    card = QFrame()
    card.setObjectName(object_name)
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    card.setStyleSheet(
        f"#{object_name} {{"
        f" background-color: {theme.SURFACE_CARD};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f" border-radius: {theme.RADIUS_MD}px;"
        f"}}"
    )
    return card


def _title_label(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_SIZE_LG)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    label.setFont(font)
    label.setStyleSheet(
        f"color: {theme.FOREGROUND}; background: transparent; border: none; letter-spacing: 0.5px;"
    )
    return label


def _muted_label(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_BODY_SIZE)
    label.setFont(font)
    label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    return label


def _mono_value_label(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont(theme.FONT_MONO)
    font.setPixelSize(theme.FONT_SIZE_XL)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    label.setFont(font)
    label.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
    return label


# ---------------------------------------------------------------------------
# Placeholder widget — «данные появятся при переходе фазы»
# ---------------------------------------------------------------------------


class PlaceholderCard(QWidget):
    """Placeholder card for widgets whose data pipeline is not yet wired."""

    def __init__(
        self,
        title: str,
        subtitle: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        card = _card("analyticsPlaceholder")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        layout.setSpacing(theme.SPACE_2)
                "calibration_v2_fit",
                "calibration_v2_coverage",
            }:
                return await asyncio.to_thread(
                    _run_calibration_v2_command,
                    action,
                    cmd,
                    calibration_store,
                )
            if action == "readings_history":
                channels_raw = cmd.get("channels")
                channels = list(channels_raw) if channels_raw else None
                from_ts = cmd.get("from_ts")
                to_ts = cmd.get("to_ts")
                limit = int(cmd.get("limit_per_channel", 3600))
                data = await writer.read_readings_history(
                    channels=channels,
                    from_ts=float(from_ts) if from_ts is not None else None,
                    to_ts=float(to_ts) if to_ts is not None else None,
                    limit_per_channel=limit,
                )
                # Serialize: {channel: [[ts, value], ...]}
                return {
                    "ok": True,
                    "data": {ch: pts for ch, pts in data.items()},
                }
            if action == "cooldown_history_get":
                return await _run_cooldown_history_command(
                    cmd, experiment_manager, writer
                )
            if action in {"log_entry", "log_get"}:
        self._running = True
        self._task = asyncio.create_task(self._consume_loop(queue), name="sqlite_writer")
        logger.info(
            "SQLiteWriter запущен (flush=%.1fs, batch=%d)", self._flush_interval_s, self._batch_size
        )

    async def stop(self) -> None:
        """Остановить цикл, дождаться завершения, закрыть БД."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Shutdown executor FIRST — waits for any in-flight write_batch to finish.
        # Then close connection — no race with executor thread.
        if self._executor is not None:
            self._executor.shutdown(wait=True)
        if self._read_executor is not None:
            self._read_executor.shutdown(wait=True)
        if self._conn:
            self._conn.close()
            self._conn = None
        logger.info("SQLiteWriter остановлен (записано: %d)", self._total_written)

    # ------------------------------------------------------------------
    # Readings history query (for GUI reconnect / full-range view)
    # ------------------------------------------------------------------

    def _read_readings_history(
        self,
        *,
        channels: list[str] | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit_per_channel: int = 3600,
    ) -> dict[str, list[tuple[float, float]]]:
        """Read historical readings from SQLite.

        Returns {channel: [(unix_ts, value), ...]} sorted by time ASC.
        Scans all daily DB files that overlap [from_ts, to_ts].
        """
        result: dict[str, list[tuple[float, float]]] = {}
        db_files = sorted(self._data_dir.glob("data_????-??-??.db"))
        if not db_files:
            return result

        # Filter DB files by date range if possible
        if from_ts is not None:
            from_day = datetime.fromtimestamp(from_ts, tz=UTC).date()
        else:
            from_day = None
        if to_ts is not None:
            to_day = datetime.fromtimestamp(to_ts, tz=UTC).date()
        else:
            to_day = None

        selected_dbs: list[Path] = []
        for db_path in db_files:
            try:
                day = date.fromisoformat(db_path.stem.removeprefix("data_"))
            except ValueError:
                continue
            if from_day is not None and day < from_day:
                continue
            if to_day is not None and day > to_day:
                continue
            selected_dbs.append(db_path)

        for db_path in selected_dbs:
            try:
                conn = sqlite3.connect(str(db_path), timeout=5)
                conn.row_factory = sqlite3.Row
                try:
                    query = "SELECT timestamp, channel, value FROM readings WHERE 1=1"
                    params: list[Any] = []
                    if from_ts is not None:
                        query += " AND timestamp >= ?"
                        params.append(from_ts)
                    if to_ts is not None:
                        query += " AND timestamp <= ?"
                        params.append(to_ts)
                    if channels:
                        placeholders = ",".join("?" for _ in channels)
                        placeholders = ",".join("?" for _ in channels)
                        query += f" AND channel IN ({placeholders})"
                        params.extend(channels)
                    query += " ORDER BY timestamp ASC"
                    for row in conn.execute(query, params).fetchall():
                        ch = row["channel"]
                        if ch not in result:
                            result[ch] = []
                        result[ch].append((float(row["timestamp"]), float(row["value"])))
                finally:
                    conn.close()
            except Exception:
                logger.warning("Ошибка чтения истории из %s", db_path)

        # Truncate to limit_per_channel (keep latest)
        for ch in result:
            if len(result[ch]) > limit_per_channel:
                result[ch] = result[ch][-limit_per_channel:]

        return result

    async def read_readings_history(
        self,
        *,
        channels: list[str] | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit_per_channel: int = 3600,
    ) -> dict[str, list[tuple[float, float]]]:
        """Async wrapper for _read_readings_history."""
        loop = asyncio.get_running_loop()
        task = partial(
            self._read_readings_history,
            channels=channels,
            from_ts=from_ts,
            to_ts=to_ts,
            limit_per_channel=limit_per_channel,
        )
        return await loop.run_in_executor(self._read_executor, task)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_written": self._total_written,
            "current_db": str(self._db_path(self._current_date)) if self._current_date else None,
        }

exec
/opt/homebrew/bin/bash -lc "sed -n '420,455p' src/cryodaq/analytics/cooldown_service.py && sed -n '200,330p' src/cryodaq/gui/shell/views/analytics_widgets.py && sed -n '515,570p' src/cryodaq/gui/shell/views/analytics_widgets.py && git diff v0.51.0..v0.52.0 -- src/cryodaq/gui/shell/views/analytics_widgets.py | sed -n '1,240p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
        if pred.future_t is not None:
            metadata["future_t"] = pred.future_t.tolist()
            metadata["future_T_cold_mean"] = pred.future_T_cold_mean.tolist()
            metadata["future_T_cold_upper"] = pred.future_T_cold_upper.tolist()
            metadata["future_T_cold_lower"] = pred.future_T_cold_lower.tolist()

        # Publish DerivedMetric
        DerivedMetric.now(
            plugin_id="cooldown_predictor",
            metric="cooldown_eta",
            value=pred.t_remaining_hours,
            unit="h",
            metadata=metadata,
        )

        # Publish via broker to all subscribers
        reading = Reading.now(
            channel="analytics/cooldown_predictor/cooldown_eta",
            value=pred.t_remaining_hours,
            unit="h",
            instrument_id="cooldown_predictor",
            metadata=metadata | {"plugin_id": "cooldown_predictor"},
        )
        await self._broker.publish(reading)

        logger.debug(
            "Прогноз охлаждения: p=%.1f%%, осталось %.1f ч, фаза=%s",
            pred.progress * 100,
            pred.t_remaining_hours,
            pred.phase,
        )

    async def _on_cooldown_end(self) -> None:
        """Обработка завершения цикла охлаждения: auto-ingest."""
        if not self._buffer:
            logger.warning("Цикл охлаждения завершён, но буфер пуст")
    ys: list[float] = field(default_factory=list)


class TemperatureOverviewWidget(QWidget):
    """Compact multi-channel temperature plot following the global
    time window. Subscribes to ``GlobalTimeWindowController``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._series: dict[str, _ChannelSeries] = {}
        self._build_ui()
        controller = get_time_window_controller()
        self._apply_window(controller.get_window())
        controller.window_changed.connect(self._apply_window)

    def _build_ui(self) -> None:
        card = _card("analyticsTemperatureOverview")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("Температурные каналы"))
        self._plot = pg.PlotWidget()
        apply_plot_style(self._plot)
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "Температура", units="K", color=theme.PLOT_LABEL_COLOR)
        pi.getAxis("left").enableAutoSIPrefix(False)
        date_axis = pg.DateAxisItem(orientation="bottom")
        self._plot.setAxisItems({"bottom": date_axis})
        pi.addLegend(offset=(10, 10))
        lay.addWidget(self._plot, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    # ------------------------------------------------------------------
    # Data ingestion — shell pushes via set_temperature_readings.
    # ------------------------------------------------------------------

    def set_temperature_readings(self, readings: dict[str, Reading]) -> None:
        for ch_id, reading in readings.items():
            ts = reading.timestamp.timestamp()
            series = self._series.setdefault(ch_id, _ChannelSeries())
            series.xs.append(ts)
            series.ys.append(float(reading.value))
            # Trim to avoid unbounded memory growth (24h ×1Hz ≈ 86k).
            max_pts = 5000
            if len(series.xs) > max_pts:
                del series.xs[: len(series.xs) - max_pts]
                del series.ys[: len(series.ys) - max_pts]
            if ch_id not in self._curves:
                curve = self._plot.plot([], [], pen=series_pen(len(self._curves)), name=ch_id)
                self._curves[ch_id] = curve
            self._curves[ch_id].setData(x=series.xs, y=series.ys)

    # ------------------------------------------------------------------
    # Window control
    # ------------------------------------------------------------------

    def _apply_window(self, window: TimeWindow) -> None:
        import math
        import time

        pi = self._plot.getPlotItem()
        if not math.isfinite(window.seconds):
            pi.enableAutoRange(axis=pg.ViewBox.XAxis, enable=True)
            pi.autoRange()
            return
        now = time.time()
        pi.setXRange(now - window.seconds, now, padding=0)


class TemperatureTrajectoryWidget(QWidget):
    """Full-experiment temperature history — per-group Y-axis scaling (W1, warmup/main, F3-Cycle2).

    Initial data: ``readings_history`` ZMQ fetch (7-day window, cold channels) on construction.
    Live updates: :meth:`set_temperature_readings` — append-only per spec §4.1.
    Y-axis: one :class:`pg.PlotItem` per channel group (cryostat / compressor / detector)
    for independent auto-scaling (spec §4.1 criterion 3).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channel_mgr = get_channel_manager()
        self._series: dict[str, _ChannelSeries] = {}
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._group_plots: dict[str, pg.PlotItem] = {}
        self._next_row: int = 0
        self._history_worker = None
        self._build_ui()
        self._fetch_history()

    def _build_ui(self) -> None:
        card = _card("analyticsTemperatureTrajectory")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("Траектория температуры"))
        self._graphics = pg.GraphicsLayoutWidget()
        self._graphics.setBackground(theme.PLOT_BG)
        self._empty_label = _muted_label("Ожидание данных…")
        lay.addWidget(self._empty_label)
        lay.addWidget(self._graphics, stretch=1)
        self._graphics.setVisible(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    def _get_or_create_group_plot(self, group: str) -> pg.PlotItem:
        """Return the PlotItem for *group*, creating it if needed."""
        if group in self._group_plots:
            return self._group_plots[group]
        pi = self._graphics.addPlot(row=self._next_row, col=0)
        pi.showGrid(x=True, y=True, alpha=0.3)
        label = group if group else "Температура"
        pi.setLabel("left", label, units="K", color=theme.PLOT_LABEL_COLOR)
        pi.getAxis("left").enableAutoSIPrefix(False)
        date_axis = pg.DateAxisItem(orientation="bottom")
        pi.setAxisItems({"bottom": date_axis})
        pi.addLegend(offset=(10, 10))
        # Link x-axis so all groups scroll / zoom together.
        if self._group_plots:
            pi.setXLink(next(iter(self._group_plots.values())))
        self._group_plots[group] = pi
        self._next_row += 1
        return pi

    def _fetch_history(self) -> None:
        """Issue a readings_history ZMQ command for all cold channels (spec §4.1)."""
class CooldownPredictionWidget(QWidget):
    """Linear-Y prediction widget wrapped for cooldown forecast."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._inner = PredictionWidget(
            title="Прогноз охлаждения",
            y_label="Температура",
            y_unit="K",
            log_y=False,
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._inner)

    def set_cooldown_data(self, data) -> None:
        if data is None:
            return
        # CooldownData from analytics_view has actual_trajectory,
        # predicted_trajectory, ci_trajectory (t, lo, hi triples).
        actual = getattr(data, "actual_trajectory", []) or []
        predicted = getattr(data, "predicted_trajectory", []) or []
        ci = getattr(data, "ci_trajectory", []) or []
        self._inner.set_history([(t, v) for (t, v) in actual])
        if predicted and ci:
            lower = [(t, lo) for (t, lo, _hi) in ci]
            upper = [(t, hi) for (t, _lo, hi) in ci]
            self._inner.set_prediction(
                [(t, v) for (t, v) in predicted],
                lower,
                upper,
                ci_level_pct=67.0,
            )


class RThermalLiveWidget(QWidget):
    """Live R_thermal readout + delta/min + compact history plot (F-P3).

    Adds a horizontal asymptote overlay via :class:`SteadyStatePredictor`
    applied to the R_thermal history.  The overlay (dashed line + ±σ band)
    appears once the predictor has settled ≥30% and reports a valid fit.

    Visual tokens follow the canonical PredictionWidget convention:
    - Asymptote line: STATUS_INFO, PLOT_LINE_WIDTH, Qt.DashLine
    - Confidence band: STATUS_INFO at alpha=64 (~25% opacity)
    """

    # Predictor convergence threshold: show overlay when ≥30% settled.
    _SETTLE_THRESHOLD: float = 30.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ss_predictor = SteadyStatePredictor(window_s=600.0, update_interval_s=30.0)
        self._last_r_ts: float = 0.0
        self._build_ui()

diff --git a/src/cryodaq/gui/shell/views/analytics_widgets.py b/src/cryodaq/gui/shell/views/analytics_widgets.py
index 0949466..756b5c1 100644
--- a/src/cryodaq/gui/shell/views/analytics_widgets.py
+++ b/src/cryodaq/gui/shell/views/analytics_widgets.py
@@ -20,12 +20,14 @@ Phase III.C contract:
 
 from __future__ import annotations
 
+import math
+import time
 from collections.abc import Callable
 from dataclasses import dataclass, field
 
 import pyqtgraph as pg
-from PySide6.QtCore import Qt, QUrl, Slot
-from PySide6.QtGui import QDesktopServices, QFont
+from PySide6.QtCore import Qt, QTimer, QUrl, Slot
+from PySide6.QtGui import QColor, QDesktopServices, QFont
 from PySide6.QtWidgets import (
     QFrame,
     QGridLayout,
@@ -35,6 +37,7 @@ from PySide6.QtWidgets import (
     QWidget,
 )
 
+from cryodaq.analytics.steady_state import SteadyStatePredictor
 from cryodaq.core.channel_manager import get_channel_manager
 from cryodaq.drivers.base import Reading
 from cryodaq.gui import theme
@@ -401,7 +404,18 @@ class TemperatureTrajectoryWidget(QWidget):
 
 
 class VacuumPredictionWidget(QWidget):
-    """Log-Y prediction widget wrapped for vacuum forecast."""
+    """Log-Y prediction widget for vacuum pressure forecast (F-P2).
+
+    Self-contained: accumulates raw pressure readings via
+    :meth:`set_pressure_reading` and polls the engine every 10 s via
+    ``get_vacuum_trend`` to obtain the extrapolated P(t) projection.
+    Converts relative-time extrapolation arrays to absolute unix
+    timestamps so the inner :class:`PredictionWidget` date axis works
+    correctly.  Confidence band = ±1σ from ``residual_std`` (log₁₀
+    units), converted to mbar.
+    """
+
+    _MAX_RAW_PTS: int = 5000
 
     def __init__(self, parent: QWidget | None = None) -> None:
         super().__init__(parent)
@@ -415,7 +429,26 @@ class VacuumPredictionWidget(QWidget):
         root.setContentsMargins(0, 0, 0, 0)
         root.addWidget(self._inner)
 
+        # Raw pressure history: (unix_ts, pressure_mbar)
+        self._raw_buffer: list[tuple[float, float]] = []
+
+        self._poll_timer = QTimer(self)
+        self._poll_timer.setInterval(10_000)
+        self._poll_timer.timeout.connect(self._poll_trend)
+        self._poll_timer.start()
+        QTimer.singleShot(500, self._poll_trend)
+
+    def set_pressure_reading(self, reading: Reading) -> None:
+        if reading is None:
+            return
+        ts = reading.timestamp.timestamp()
+        self._raw_buffer.append((ts, float(reading.value)))
+        if len(self._raw_buffer) > self._MAX_RAW_PTS:
+            del self._raw_buffer[: len(self._raw_buffer) - self._MAX_RAW_PTS]
+        self._inner.set_history(list(self._raw_buffer))
+
     def set_vacuum_prediction(self, data: dict | None) -> None:
+        """Accept externally-pushed prediction dict (legacy path)."""
         if data is None:
             return
         history = data.get("history") or []
@@ -427,6 +460,57 @@ class VacuumPredictionWidget(QWidget):
         if central and lower and upper:
             self._inner.set_prediction(list(central), list(lower), list(upper), ci_level_pct=ci_pct)
 
+    @Slot()
+    def _poll_trend(self) -> None:
+        from cryodaq.gui.zmq_client import ZmqCommandWorker
+
+        worker = ZmqCommandWorker({"cmd": "get_vacuum_trend"}, parent=self)
+        worker.finished.connect(self._on_trend_result)
+        worker.start()
+
+    @Slot(dict)
+    def _on_trend_result(self, result: dict) -> None:
+        if not result.get("ok") or result.get("status") == "no_data":
+            # Clear any previously-rendered forecast so no stale overlay persists
+            # after a bridge restart, disabled predictor, or empty buffer.
+            self._inner.set_prediction([], [], [], ci_level_pct=68.0)
+            return
+        extrap_t = result.get("extrapolation_t") or []
+        extrap_logP = result.get("extrapolation_logP") or []
+        residual_std = float(result.get("residual_std") or 0.0)
+        if not extrap_t or not extrap_logP or len(extrap_t) != len(extrap_logP):
+            return
+
+        # extrap_t is seconds from engine buffer t0; extrap_t[0] ≈ buffer duration.
+        # Setting t0 = now - extrap_t[0] maps relative times to absolute unix
+        # timestamps with the prediction starting at "now".
+        now = time.time()
+        t0 = now - extrap_t[0]
+
+        central = [
+            (t0 + t, 10.0**lp)
+            for t, lp in zip(extrap_t, extrap_logP)
+            if math.isfinite(lp)
+        ]
+        if not central:
+            return
+
+        if residual_std > 0:
+            lower = [
+                (t0 + t, 10.0 ** (lp - residual_std))
+                for t, lp in zip(extrap_t, extrap_logP)
+                if math.isfinite(lp)
+            ]
+            upper = [
+                (t0 + t, 10.0 ** (lp + residual_std))
+                for t, lp in zip(extrap_t, extrap_logP)
+                if math.isfinite(lp)
+            ]
+        else:
+            lower = central
+            upper = central
+        self._inner.set_prediction(central, lower, upper, ci_level_pct=68.0)
+
 
 class CooldownPredictionWidget(QWidget):
     """Linear-Y prediction widget wrapped for cooldown forecast."""
@@ -464,10 +548,24 @@ class CooldownPredictionWidget(QWidget):
 
 
 class RThermalLiveWidget(QWidget):
-    """Live R_thermal readout + delta/min + compact history plot."""
+    """Live R_thermal readout + delta/min + compact history plot (F-P3).
+
+    Adds a horizontal asymptote overlay via :class:`SteadyStatePredictor`
+    applied to the R_thermal history.  The overlay (dashed line + ±σ band)
+    appears once the predictor has settled ≥30% and reports a valid fit.
+
+    Visual tokens follow the canonical PredictionWidget convention:
+    - Asymptote line: STATUS_INFO, PLOT_LINE_WIDTH, Qt.DashLine
+    - Confidence band: STATUS_INFO at alpha=64 (~25% opacity)
+    """
+
+    # Predictor convergence threshold: show overlay when ≥30% settled.
+    _SETTLE_THRESHOLD: float = 30.0
 
     def __init__(self, parent: QWidget | None = None) -> None:
         super().__init__(parent)
+        self._ss_predictor = SteadyStatePredictor(window_s=600.0, update_interval_s=30.0)
+        self._last_r_ts: float = 0.0
         self._build_ui()
 
     def _build_ui(self) -> None:
@@ -490,7 +588,38 @@ class RThermalLiveWidget(QWidget):
         pi.getAxis("left").enableAutoSIPrefix(False)
         date_axis = pg.DateAxisItem(orientation="bottom")
         self._plot.setAxisItems({"bottom": date_axis})
+
+        # F-P3: CI band added first so it renders behind the data curve.
+        # Color: STATUS_INFO at alpha=64 — matches PredictionWidget convention.
+        band_color = QColor(theme.STATUS_INFO)
+        band_color.setAlpha(64)
+        self._asym_band = pg.LinearRegionItem(
+            values=[0.0, 0.0],
+            orientation="horizontal",
+            brush=pg.mkBrush(band_color),
+            movable=False,
+        )
+        self._asym_band.setVisible(False)
+        self._plot.addItem(self._asym_band)
+
+        # Data curve renders above the band.
         self._curve = self._plot.plot([], [], pen=series_pen(0))
+
+        # F-P3: Asymptote dashed line added last — renders above data curve.
+        # Pen: STATUS_INFO, PLOT_LINE_WIDTH, DashLine — matches PredictionWidget.
+        self._asym_line = pg.InfiniteLine(
+            angle=0,
+            pen=pg.mkPen(
+                color=QColor(theme.STATUS_INFO),
+                width=theme.PLOT_LINE_WIDTH,
+                style=Qt.DashLine,
+            ),
+            label="R∞",
+            labelOpts={"color": theme.STATUS_INFO, "position": 0.95},
+        )
+        self._asym_line.setVisible(False)
+        self._plot.addItem(self._asym_line)
+
         lay.addWidget(self._plot, stretch=1)
 
         root = QVBoxLayout(self)
@@ -502,6 +631,8 @@ class RThermalLiveWidget(QWidget):
             self._value_label.setText("—")
             self._delta_label.setText("ΔR / мин: —")
             self._curve.setData([], [])
+            self._asym_line.setVisible(False)
+            self._asym_band.setVisible(False)
             return
         current = getattr(data, "current_value", None)
         delta = getattr(data, "delta_per_minute", None)
@@ -519,6 +650,29 @@ class RThermalLiveWidget(QWidget):
             ys = [v for _, v in history]
             self._curve.setData(x=xs, y=ys)
 
+            # Feed only new history points into the predictor.
+            for ts, val in history:
+                if ts > self._last_r_ts:
+                    self._ss_predictor.add_point("R_thermal", ts, val)
+                    self._last_r_ts = ts
+
+            self._ss_predictor.update(time.time())
+            pred = self._ss_predictor.get_prediction("R_thermal")
+            if pred is not None and pred.valid and pred.percent_settled >= self._SETTLE_THRESHOLD:
+                r_inf = pred.t_predicted
+                sigma = abs(pred.amplitude) * max(0.0, 1.0 - pred.confidence)
+                self._asym_line.setPos(r_inf)
+                self._asym_band.setRegion([r_inf - sigma, r_inf + sigma])
+                self._asym_line.setVisible(True)
+                self._asym_band.setVisible(True)
+            else:
+                self._asym_line.setVisible(False)
+                self._asym_band.setVisible(False)
+        else:
+            # Empty history on non-None push — hide stale overlay if present.
+            self._asym_line.setVisible(False)
+            self._asym_band.setVisible(False)
+
 
 class PressureCurrentWidget(QWidget):
     """Wraps the shared :class:`PressurePlot` for the analytics view."""

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/gui/shell/views/analytics_widgets.py | sed -n '203,285p;326,405p;515,545p' && nl -ba src/cryodaq/analytics/cooldown_service.py | sed -n '353,438p' && nl -ba src/cryodaq/engine.py | sed -n '1789,1805p' && nl -ba src/cryodaq/storage/sqlite_writer.py | sed -n '691,763p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   203	class TemperatureOverviewWidget(QWidget):
   204	    """Compact multi-channel temperature plot following the global
   205	    time window. Subscribes to ``GlobalTimeWindowController``."""
   206	
   207	    def __init__(self, parent: QWidget | None = None) -> None:
   208	        super().__init__(parent)
   209	        self._curves: dict[str, pg.PlotDataItem] = {}
   210	        self._series: dict[str, _ChannelSeries] = {}
   211	        self._build_ui()
   212	        controller = get_time_window_controller()
   213	        self._apply_window(controller.get_window())
   214	        controller.window_changed.connect(self._apply_window)
   215	
   216	    def _build_ui(self) -> None:
   217	        card = _card("analyticsTemperatureOverview")
   218	        lay = QVBoxLayout(card)
   219	        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
   220	        lay.setSpacing(theme.SPACE_2)
   221	        lay.addWidget(_title_label("Температурные каналы"))
   222	        self._plot = pg.PlotWidget()
   223	        apply_plot_style(self._plot)
   224	        pi = self._plot.getPlotItem()
   225	        pi.setLabel("left", "Температура", units="K", color=theme.PLOT_LABEL_COLOR)
   226	        pi.getAxis("left").enableAutoSIPrefix(False)
   227	        date_axis = pg.DateAxisItem(orientation="bottom")
   228	        self._plot.setAxisItems({"bottom": date_axis})
   229	        pi.addLegend(offset=(10, 10))
   230	        lay.addWidget(self._plot, stretch=1)
   231	
   232	        root = QVBoxLayout(self)
   233	        root.setContentsMargins(0, 0, 0, 0)
   234	        root.addWidget(card)
   235	
   236	    # ------------------------------------------------------------------
   237	    # Data ingestion — shell pushes via set_temperature_readings.
   238	    # ------------------------------------------------------------------
   239	
   240	    def set_temperature_readings(self, readings: dict[str, Reading]) -> None:
   241	        for ch_id, reading in readings.items():
   242	            ts = reading.timestamp.timestamp()
   243	            series = self._series.setdefault(ch_id, _ChannelSeries())
   244	            series.xs.append(ts)
   245	            series.ys.append(float(reading.value))
   246	            # Trim to avoid unbounded memory growth (24h ×1Hz ≈ 86k).
   247	            max_pts = 5000
   248	            if len(series.xs) > max_pts:
   249	                del series.xs[: len(series.xs) - max_pts]
   250	                del series.ys[: len(series.ys) - max_pts]
   251	            if ch_id not in self._curves:
   252	                curve = self._plot.plot([], [], pen=series_pen(len(self._curves)), name=ch_id)
   253	                self._curves[ch_id] = curve
   254	            self._curves[ch_id].setData(x=series.xs, y=series.ys)
   255	
   256	    # ------------------------------------------------------------------
   257	    # Window control
   258	    # ------------------------------------------------------------------
   259	
   260	    def _apply_window(self, window: TimeWindow) -> None:
   261	        import math
   262	        import time
   263	
   264	        pi = self._plot.getPlotItem()
   265	        if not math.isfinite(window.seconds):
   266	            pi.enableAutoRange(axis=pg.ViewBox.XAxis, enable=True)
   267	            pi.autoRange()
   268	            return
   269	        now = time.time()
   270	        pi.setXRange(now - window.seconds, now, padding=0)
   271	
   272	
   273	class TemperatureTrajectoryWidget(QWidget):
   274	    """Full-experiment temperature history — per-group Y-axis scaling (W1, warmup/main, F3-Cycle2).
   275	
   276	    Initial data: ``readings_history`` ZMQ fetch (7-day window, cold channels) on construction.
   277	    Live updates: :meth:`set_temperature_readings` — append-only per spec §4.1.
   278	    Y-axis: one :class:`pg.PlotItem` per channel group (cryostat / compressor / detector)
   279	    for independent auto-scaling (spec §4.1 criterion 3).
   280	    """
   281	
   282	    def __init__(self, parent: QWidget | None = None) -> None:
   283	        super().__init__(parent)
   284	        self._channel_mgr = get_channel_manager()
   285	        self._series: dict[str, _ChannelSeries] = {}
   326	        self._next_row += 1
   327	        return pi
   328	
   329	    def _fetch_history(self) -> None:
   330	        """Issue a readings_history ZMQ command for all cold channels (spec §4.1)."""
   331	        import time
   332	
   333	        from cryodaq.gui.zmq_client import ZmqCommandWorker
   334	
   335	        channels = self._channel_mgr.get_cold_channels() or None
   336	        cmd = {
   337	            "cmd": "readings_history",
   338	            "from_ts": time.time() - 7 * 24 * 3600,
   339	            "to_ts": time.time(),
   340	            "channels": channels,
   341	            "limit_per_channel": 5000,
   342	        }
   343	        self._history_worker = ZmqCommandWorker(cmd, parent=self)
   344	        self._history_worker.finished.connect(self._on_history_loaded)
   345	        self._history_worker.start()
   346	
   347	    @Slot(dict)
   348	    def _on_history_loaded(self, result: dict) -> None:
   349	        """Merge engine history response; sort each series by timestamp."""
   350	        if not result.get("ok"):
   351	            return
   352	        data: dict[str, list] = result.get("data", {})
   353	        for channel, points in data.items():
   354	            if not points:
   355	                continue
   356	            series = self._series.setdefault(channel, _ChannelSeries())
   357	            for entry in points:
   358	                series.xs.append(float(entry[0]))
   359	                series.ys.append(float(entry[1]))
   360	        # Sort by timestamp: history may arrive after F4 live-stream replay,
   361	        # producing out-of-order points if not sorted.
   362	        for series in self._series.values():
   363	            if len(series.xs) > 1:
   364	                pairs = sorted(zip(series.xs, series.ys))
   365	                series.xs[:] = [p[0] for p in pairs]
   366	                series.ys[:] = [p[1] for p in pairs]
   367	        self._refresh_all_curves()
   368	        self._update_empty_state()
   369	
   370	    def set_temperature_readings(self, readings: dict[str, Reading]) -> None:
   371	        """Append live broker readings (spec §4.1 live stream)."""
   372	        for ch_id, reading in readings.items():
   373	            series = self._series.setdefault(ch_id, _ChannelSeries())
   374	            series.xs.append(reading.timestamp.timestamp())
   375	            series.ys.append(float(reading.value))
   376	            max_pts = 5000
   377	            if len(series.xs) > max_pts:
   378	                del series.xs[: len(series.xs) - max_pts]
   379	                del series.ys[: len(series.ys) - max_pts]
   380	            self._update_curve(ch_id)
   381	        self._update_empty_state()
   382	
   383	    def _update_curve(self, ch_id: str) -> None:
   384	        series = self._series.get(ch_id)
   385	        if series is None:
   386	            return
   387	        group = self._channel_mgr.get_group(ch_id)
   388	        pi = self._get_or_create_group_plot(group)
   389	        if ch_id not in self._curves:
   390	            pen = series_pen(len(self._curves))
   391	            name = self._channel_mgr.get_name(ch_id) or ch_id
   392	            curve = pi.plot([], [], pen=pen, name=name)
   393	            self._curves[ch_id] = curve
   394	        self._curves[ch_id].setData(x=series.xs, y=series.ys)
   395	
   396	    def _refresh_all_curves(self) -> None:
   397	        for ch_id in self._series:
   398	            self._update_curve(ch_id)
   399	
   400	    def _update_empty_state(self) -> None:
   401	        has_data = any(s.xs for s in self._series.values())
   402	        self._empty_label.setHidden(has_data)
   403	        self._graphics.setHidden(not has_data)
   404	
   405	
   515	class CooldownPredictionWidget(QWidget):
   516	    """Linear-Y prediction widget wrapped for cooldown forecast."""
   517	
   518	    def __init__(self, parent: QWidget | None = None) -> None:
   519	        super().__init__(parent)
   520	        self._inner = PredictionWidget(
   521	            title="Прогноз охлаждения",
   522	            y_label="Температура",
   523	            y_unit="K",
   524	            log_y=False,
   525	        )
   526	        root = QVBoxLayout(self)
   527	        root.setContentsMargins(0, 0, 0, 0)
   528	        root.addWidget(self._inner)
   529	
   530	    def set_cooldown_data(self, data) -> None:
   531	        if data is None:
   532	            return
   533	        # CooldownData from analytics_view has actual_trajectory,
   534	        # predicted_trajectory, ci_trajectory (t, lo, hi triples).
   535	        actual = getattr(data, "actual_trajectory", []) or []
   536	        predicted = getattr(data, "predicted_trajectory", []) or []
   537	        ci = getattr(data, "ci_trajectory", []) or []
   538	        self._inner.set_history([(t, v) for (t, v) in actual])
   539	        if predicted and ci:
   540	            lower = [(t, lo) for (t, lo, _hi) in ci]
   541	            upper = [(t, hi) for (t, _lo, hi) in ci]
   542	            self._inner.set_prediction(
   543	                [(t, v) for (t, v) in predicted],
   544	                lower,
   545	                upper,
   353	    async def _do_predict(self) -> None:
   354	        """Выполнить прогнозирование и опубликовать результат."""
   355	        if self._model is None:
   356	            return
   357	
   358	        phase = self._detector.phase
   359	        cooldown_active = phase in (CooldownPhase.COOLING, CooldownPhase.STABILIZING)
   360	
   361	        T_cold = self._last_T_cold
   362	        T_warm = self._last_T_warm
   363	        if T_cold is None or T_warm is None:
   364	            return
   365	
   366	        # Compute elapsed time
   367	        if self._cooldown_wall_start is not None and cooldown_active:
   368	            t_elapsed = (time.time() - self._cooldown_wall_start) / 3600.0
   369	        else:
   370	            t_elapsed = 0.0
   371	
   372	        # Compute observed rates from buffer
   373	        rate_cold: float | None = None
   374	        rate_warm: float | None = None
   375	        if len(self._buffer) >= 20:
   376	            buf_arr = np.array(list(self._buffer))
   377	            t_h = buf_arr[:, 0]
   378	            Tc = buf_arr[:, 1]
   379	            Tw = buf_arr[:, 2]
   380	            rate_cold, rate_warm = compute_rate_from_history(
   381	                t_h,
   382	                Tc,
   383	                Tw,
   384	                window_h=self._rate_window_h,
   385	            )
   386	
   387	        # Run predict in executor (scipy is CPU-heavy)
   388	        loop = asyncio.get_running_loop()
   389	        try:
   390	            pred = await loop.run_in_executor(
   391	                None,
   392	                lambda: predict(
   393	                    self._model,
   394	                    T_cold,
   395	                    T_warm,
   396	                    t_elapsed=t_elapsed,
   397	                    generate_trajectory=True,
   398	                    observed_rate_cold=rate_cold,
   399	                    observed_rate_warm=rate_warm,
   400	                ),
   401	            )
   402	        except Exception as exc:
   403	            logger.error("Ошибка прогнозирования охлаждения: %s", exc)
   404	            return
   405	
   406	        # Build metadata
   407	        metadata: dict[str, Any] = {
   408	            "t_remaining_hours": pred.t_remaining_hours,
   409	            "t_remaining_ci68": (pred.t_remaining_low_68, pred.t_remaining_high_68),
   410	            "progress": pred.progress,
   411	            "phase": pred.phase,
   412	            "n_references": pred.n_references,
   413	            "cooldown_active": cooldown_active,
   414	            "cooldown_start_ts": self._detector.cooldown_start_ts or 0,
   415	            "T_cold": T_cold,
   416	            "T_warm": T_warm,
   417	        }
   418	        self._last_prediction = metadata  # cache for F30 query agent
   419	
   420	        if pred.future_t is not None:
   421	            metadata["future_t"] = pred.future_t.tolist()
   422	            metadata["future_T_cold_mean"] = pred.future_T_cold_mean.tolist()
   423	            metadata["future_T_cold_upper"] = pred.future_T_cold_upper.tolist()
   424	            metadata["future_T_cold_lower"] = pred.future_T_cold_lower.tolist()
   425	
   426	        # Publish DerivedMetric
   427	        DerivedMetric.now(
   428	            plugin_id="cooldown_predictor",
   429	            metric="cooldown_eta",
   430	            value=pred.t_remaining_hours,
   431	            unit="h",
   432	            metadata=metadata,
   433	        )
   434	
   435	        # Publish via broker to all subscribers
   436	        reading = Reading.now(
   437	            channel="analytics/cooldown_predictor/cooldown_eta",
   438	            value=pred.t_remaining_hours,
  1789	            if action == "readings_history":
  1790	                channels_raw = cmd.get("channels")
  1791	                channels = list(channels_raw) if channels_raw else None
  1792	                from_ts = cmd.get("from_ts")
  1793	                to_ts = cmd.get("to_ts")
  1794	                limit = int(cmd.get("limit_per_channel", 3600))
  1795	                data = await writer.read_readings_history(
  1796	                    channels=channels,
  1797	                    from_ts=float(from_ts) if from_ts is not None else None,
  1798	                    to_ts=float(to_ts) if to_ts is not None else None,
  1799	                    limit_per_channel=limit,
  1800	                )
  1801	                # Serialize: {channel: [[ts, value], ...]}
  1802	                return {
  1803	                    "ok": True,
  1804	                    "data": {ch: pts for ch, pts in data.items()},
  1805	                }
   691	    def _read_readings_history(
   692	        self,
   693	        *,
   694	        channels: list[str] | None = None,
   695	        from_ts: float | None = None,
   696	        to_ts: float | None = None,
   697	        limit_per_channel: int = 3600,
   698	    ) -> dict[str, list[tuple[float, float]]]:
   699	        """Read historical readings from SQLite.
   700	
   701	        Returns {channel: [(unix_ts, value), ...]} sorted by time ASC.
   702	        Scans all daily DB files that overlap [from_ts, to_ts].
   703	        """
   704	        result: dict[str, list[tuple[float, float]]] = {}
   705	        db_files = sorted(self._data_dir.glob("data_????-??-??.db"))
   706	        if not db_files:
   707	            return result
   708	
   709	        # Filter DB files by date range if possible
   710	        if from_ts is not None:
   711	            from_day = datetime.fromtimestamp(from_ts, tz=UTC).date()
   712	        else:
   713	            from_day = None
   714	        if to_ts is not None:
   715	            to_day = datetime.fromtimestamp(to_ts, tz=UTC).date()
   716	        else:
   717	            to_day = None
   718	
   719	        selected_dbs: list[Path] = []
   720	        for db_path in db_files:
   721	            try:
   722	                day = date.fromisoformat(db_path.stem.removeprefix("data_"))
   723	            except ValueError:
   724	                continue
   725	            if from_day is not None and day < from_day:
   726	                continue
   727	            if to_day is not None and day > to_day:
   728	                continue
   729	            selected_dbs.append(db_path)
   730	
   731	        for db_path in selected_dbs:
   732	            try:
   733	                conn = sqlite3.connect(str(db_path), timeout=5)
   734	                conn.row_factory = sqlite3.Row
   735	                try:
   736	                    query = "SELECT timestamp, channel, value FROM readings WHERE 1=1"
   737	                    params: list[Any] = []
   738	                    if from_ts is not None:
   739	                        query += " AND timestamp >= ?"
   740	                        params.append(from_ts)
   741	                    if to_ts is not None:
   742	                        query += " AND timestamp <= ?"
   743	                        params.append(to_ts)
   744	                    if channels:
   745	                        placeholders = ",".join("?" for _ in channels)
   746	                        query += f" AND channel IN ({placeholders})"
   747	                        params.extend(channels)
   748	                    query += " ORDER BY timestamp ASC"
   749	                    for row in conn.execute(query, params).fetchall():
   750	                        ch = row["channel"]
   751	                        if ch not in result:
   752	                            result[ch] = []
   753	                        result[ch].append((float(row["timestamp"]), float(row["value"])))
   754	                finally:
   755	                    conn.close()
   756	            except Exception:
   757	                logger.warning("Ошибка чтения истории из %s", db_path)
   758	
   759	        # Truncate to limit_per_channel (keep latest)
   760	        for ch in result:
   761	            if len(result[ch]) > limit_per_channel:
   762	                result[ch] = result[ch][-limit_per_channel:]
   763	

exec
/opt/homebrew/bin/bash -lc "grep -R \"class AnalyticsView\\|set_cooldown\\|actual_trajectory\\|future_t\\|cooldown_active\\|set_temperature_readings\\|analytics/cooldown\" -n src/cryodaq/gui/shell/views src/cryodaq/gui/shell/main_window_v2.py | head -100 && sed -n '400,500p' src/cryodaq/gui/shell/main_window_v2.py && sed -n '430,510p' src/cryodaq/gui/shell/views/analytics_view.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/gui/shell/views/analytics_widgets.py:237:    # Data ingestion — shell pushes via set_temperature_readings.
src/cryodaq/gui/shell/views/analytics_widgets.py:240:    def set_temperature_readings(self, readings: dict[str, Reading]) -> None:
src/cryodaq/gui/shell/views/analytics_widgets.py:277:    Live updates: :meth:`set_temperature_readings` — append-only per spec §4.1.
src/cryodaq/gui/shell/views/analytics_widgets.py:370:    def set_temperature_readings(self, readings: dict[str, Reading]) -> None:
src/cryodaq/gui/shell/views/analytics_widgets.py:530:    def set_cooldown_data(self, data) -> None:
src/cryodaq/gui/shell/views/analytics_widgets.py:533:        # CooldownData from analytics_view has actual_trajectory,
src/cryodaq/gui/shell/views/analytics_widgets.py:535:        actual = getattr(data, "actual_trajectory", []) or []
Binary file src/cryodaq/gui/shell/views/__pycache__/analytics_view.cpython-314.pyc matches
Binary file src/cryodaq/gui/shell/views/__pycache__/analytics_widgets.cpython-314.pyc matches
src/cryodaq/gui/shell/views/analytics_view.py:17:  contract (:meth:`set_cooldown`, :meth:`set_r_thermal`,
src/cryodaq/gui/shell/views/analytics_view.py:19:  (:meth:`set_temperature_readings`, :meth:`set_pressure_reading`,
src/cryodaq/gui/shell/views/analytics_view.py:67:    ``analytics/cooldown_predictor/cooldown_eta`` broker channel.
src/cryodaq/gui/shell/views/analytics_view.py:75:    actual_trajectory: list[tuple[float, float]] = field(default_factory=list)
src/cryodaq/gui/shell/views/analytics_view.py:127:class AnalyticsView(QWidget):
src/cryodaq/gui/shell/views/analytics_view.py:179:    def set_cooldown(self, data: CooldownData | None) -> None:
src/cryodaq/gui/shell/views/analytics_view.py:181:        self._forward("set_cooldown_data", data)
src/cryodaq/gui/shell/views/analytics_view.py:191:    def set_temperature_readings(self, readings: dict[str, Reading]) -> None:
src/cryodaq/gui/shell/views/analytics_view.py:194:        self._forward("set_temperature_readings", readings)
src/cryodaq/gui/shell/views/analytics_view.py:296:            self._forward_to(widgets, "set_cooldown_data", self._last_cooldown)
src/cryodaq/gui/shell/views/analytics_view.py:303:                widgets, "set_temperature_readings", self._last_temperature_readings
src/cryodaq/gui/shell/main_window_v2.py:353:                widget.set_temperature_readings(dict(self._analytics_temperature_snapshot))
src/cryodaq/gui/shell/main_window_v2.py:414:                self._analytics_view.set_temperature_readings({channel: reading})
src/cryodaq/gui/shell/main_window_v2.py:442:            # B.8: the v2 AnalyticsView exposes set_cooldown /
src/cryodaq/gui/shell/main_window_v2.py:481:        if channel == "analytics/cooldown_predictor/cooldown_eta":
src/cryodaq/gui/shell/main_window_v2.py:484:                self._push_analytics("set_cooldown", data)
src/cryodaq/gui/shell/main_window_v2.py:496:          - metadata["future_t"]            optional list[float], hours
src/cryodaq/gui/shell/main_window_v2.py:539:        future_t = meta.get("future_t")
src/cryodaq/gui/shell/main_window_v2.py:544:            isinstance(future_t, list)
src/cryodaq/gui/shell/main_window_v2.py:546:            and len(future_t) == len(future_mean)
src/cryodaq/gui/shell/main_window_v2.py:548:            predicted = list(zip(future_t, future_mean, strict=False))
src/cryodaq/gui/shell/main_window_v2.py:550:            isinstance(future_t, list)
src/cryodaq/gui/shell/main_window_v2.py:553:            and len(future_t) == len(future_upper) == len(future_lower)
src/cryodaq/gui/shell/main_window_v2.py:555:            ci_traj = list(zip(future_t, future_lower, future_upper, strict=False))
src/cryodaq/gui/shell/main_window_v2.py:562:            actual_trajectory=[],
src/cryodaq/gui/shell/main_window_v2.py:638:            self._analytics_snapshot.pop("set_cooldown", None)
            self._calibration_panel.on_reading(reading)
        if (
            channel.startswith("\u0422")
            and reading.unit == "K"
            and self._conductivity_panel is not None
        ):
            self._conductivity_panel.on_reading(reading)
        # F3-Cycle2: route temperature readings to analytics view + shell cache.
        # This is intentional parallel routing — calibration_panel and analytics_view
        # are independent consumers: calibration uses readings for curve fitting;
        # analytics uses them for TemperatureTrajectoryWidget live stream.
        if reading.unit == "K":
            self._analytics_temperature_snapshot[channel] = reading
            if self._analytics_view is not None:
                self._analytics_view.set_temperature_readings({channel: reading})
        if (
            "/smua/" in channel
            or "/smub/" in channel
            or channel.startswith("analytics/keithley_channel_state/")
        ):
            if self._keithley_panel is not None:
                self._keithley_panel.on_reading(reading)
            if channel.endswith("/power") and self._conductivity_panel is not None:
                self._conductivity_panel.on_reading(reading)
            # F4: accumulate Keithley power readings into analytics snapshot.
            # Must guard on SMU sub-path explicitly — the outer condition also
            # matches analytics/keithley_channel_state/* channels which lack
            # the smua/smub segment KeithleyPowerWidget expects at parts[-2].
            if (
                ("/smua/" in channel or "/smub/" in channel)
                and channel.split("/")[-1] in ("voltage", "current", "power")
            ):
                self._analytics_keithley_snapshot[channel] = reading
                if self._analytics_view is not None:
                    self._analytics_view.set_keithley_readings({channel: reading})
        # F4: route pressure gauge readings to analytics view + shell cache.
        # VSP63D publishes on channels ending with /pressure, unit мбар.
        if reading.unit == "мбар" and channel.endswith("/pressure"):
            self._push_analytics("set_pressure_reading", reading)
        if channel.startswith("analytics/"):
            # Note: _overview_panel.on_reading already called above in
            # eager sinks — no need to call again here (Codex B.5.5 F3)
            # B.8: the v2 AnalyticsView exposes set_cooldown /
            # set_r_thermal / set_fault setters instead of a generic
            # on_reading sink. The shell adapts specific analytics
            # channels into the typed snapshots below.
            # F4: _adapt_reading_to_analytics now handles None view internally
            # via _push_analytics — remove the prior None guard.
            self._adapt_reading_to_analytics(reading)
            if self._operator_log_panel is not None:
                self._operator_log_panel.on_reading(reading)
            if channel == "analytics/safety_state":
                state_name = reading.metadata.get("state")
                reason = reading.metadata.get("reason", "") or ""
                self._last_safety_state = str(state_name) if state_name is not None else None
                self._last_safety_reason = str(reason) if reason else ""
                self._bottom_bar.set_safety_state(self._last_safety_state)
                if self._keithley_panel is not None:
                    ready, reason_text = _map_safety_state(
                        self._last_safety_state, self._last_safety_reason
                    )
                    self._keithley_panel.set_safety_ready(ready, reason_text)
        if self._instrument_panel is not None:
            self._instrument_panel.on_reading(reading)

    # ------------------------------------------------------------------
    # Analytics channel adapter (B.8 follow-up)
    # ------------------------------------------------------------------

    def _adapt_reading_to_analytics(self, reading: Reading) -> None:
        """Translate broker ``analytics/*`` readings into AnalyticsView setter calls.

        Routes known analytics channels through :meth:`_push_analytics` so that
        the shell-level snapshot cache is updated regardless of whether
        AnalyticsView is currently open (F4 lazy-open replay, spec §4.5).

        Any unrecognised ``analytics/*`` channel is silently dropped — the v2
        panel has no generic ``on_reading`` sink, so unknown channels are
        intentional no-ops.
        """
        channel = reading.channel
        if channel == "analytics/cooldown_predictor/cooldown_eta":
            data = self._cooldown_reading_to_data(reading)
            if data is not None:
                self._push_analytics("set_cooldown", data)

    @staticmethod
    def _cooldown_reading_to_data(reading: Reading):
        """Build a `CooldownData` snapshot from a cooldown_predictor reading.

        Plugin output shape (see cooldown_service.py:400-433):
          - value              = t_remaining_hours (also in metadata)
          - metadata["t_remaining_hours"]   float, hours
          - metadata["t_remaining_ci68"]    (low, high) asymmetric
          - metadata["progress"]            float in [0, 1]  (fraction, NOT %)
          - metadata["phase"]               "phase1" | "transition" | "phase2" | "steady"
          - metadata["future_t"]            optional list[float], hours
          - metadata["future_T_cold_mean"]  optional list[float], K
          - metadata["future_T_cold_upper"] optional list[float], K
          - metadata["future_T_cold_lower"] optional list[float], K
        """

exec
/opt/homebrew/bin/bash -lc "sed -n '55,95p' src/cryodaq/gui/shell/views/analytics_view.py && sed -n '127,210p' src/cryodaq/gui/shell/views/analytics_view.py && sed -n '288,307p' src/cryodaq/gui/shell/views/analytics_view.py && sed -n '490,570p' src/cryodaq/gui/shell/main_window_v2.py && grep -R \"cooldown_active\" -n src tests | head -50" in /Users/vladimir/Projects/cryodaq
 succeeded in 222ms:
Binary file src/cryodaq/agents/assistant/query/__pycache__/schemas.cpython-314.pyc matches
Binary file src/cryodaq/agents/assistant/query/__pycache__/agent.cpython-314.pyc matches
Binary file src/cryodaq/agents/assistant/query/__pycache__/prompts.cpython-314.pyc matches
src/cryodaq/agents/assistant/query/prompts.py:108:- Захолаживание активно: {cooldown_active}
Binary file src/cryodaq/agents/assistant/query/adapters/__pycache__/cooldown_adapter.cpython-314.pyc matches
src/cryodaq/agents/assistant/query/adapters/cooldown_adapter.py:40:                cooldown_active=bool(pred.get("cooldown_active", False)),
src/cryodaq/agents/assistant/query/schemas.py:49:    cooldown_active: bool
src/cryodaq/agents/assistant/query/agent.py:302:                cooldown_active=ru_bool(False),
src/cryodaq/agents/assistant/query/agent.py:318:            cooldown_active=ru_bool(eta.cooldown_active),
src/cryodaq/gui/widgets/overview_panel.py:1482:        active = meta.get("cooldown_active", False)
Binary file src/cryodaq/gui/widgets/__pycache__/analytics_panel.cpython-314.pyc matches
Binary file src/cryodaq/gui/widgets/__pycache__/overview_panel.cpython-314.pyc matches
src/cryodaq/gui/widgets/analytics_panel.py:70:        self._cooldown_active: bool = False
src/cryodaq/gui/widgets/analytics_panel.py:333:            active = meta.get("cooldown_active", False)
src/cryodaq/gui/widgets/analytics_panel.py:336:            if active and not self._cooldown_active:
src/cryodaq/gui/widgets/analytics_panel.py:340:            self._cooldown_active = active
src/cryodaq/gui/widgets/analytics_panel.py:347:            if not self._cooldown_active:
src/cryodaq/gui/widgets/analytics_panel.py:362:            if self._cooldown_active and self._cooldown_start_time > 0:
src/cryodaq/gui/widgets/analytics_panel.py:368:        active = meta.get("cooldown_active", False)
src/cryodaq/gui/widgets/analytics_panel.py:427:        if self._cooldown_active:
Binary file src/cryodaq/analytics/__pycache__/cooldown_service.cpython-314.pyc matches
src/cryodaq/analytics/cooldown_service.py:359:        cooldown_active = phase in (CooldownPhase.COOLING, CooldownPhase.STABILIZING)
src/cryodaq/analytics/cooldown_service.py:367:        if self._cooldown_wall_start is not None and cooldown_active:
src/cryodaq/analytics/cooldown_service.py:413:            "cooldown_active": cooldown_active,
tests/agents/assistant/test_query_adapters.py:126:        "cooldown_active": True,
tests/agents/assistant/test_query_adapters.py:138:    assert result.cooldown_active is True
Binary file tests/agents/assistant/__pycache__/test_intent_classifier.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/agents/assistant/__pycache__/test_query_adapters.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/agents/assistant/__pycache__/test_hf_v0472_tone.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/agents/assistant/__pycache__/test_query_agent.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/agents/assistant/__pycache__/test_query_agent.cpython-314.pyc matches
tests/agents/assistant/test_query_agent.py:137:        cooldown_active=True,
tests/agents/assistant/test_intent_classifier.py:246:        cooldown_active=True,
tests/analytics/test_cooldown_service.py:404:        assert "cooldown_active" in meta
tests/analytics/test_cooldown_service.py:405:        assert meta["cooldown_active"] is True
Binary file tests/analytics/__pycache__/test_cooldown_service.cpython-314.pyc matches
Binary file tests/analytics/__pycache__/test_cooldown_service.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/analytics/__pycache__/test_cooldown_service.cpython-314-pytest-9.0.2.pyc matches

exec
/opt/homebrew/bin/bash -lc "grep -n \"def predict\\|class PredictionResult\\|future_t\\|progress\\|steady\\|T_cold\" src/cryodaq/analytics/cooldown_predictor.py | head -80 && sed -n '320,470p' src/cryodaq/analytics/cooldown_predictor.py && grep -R \"cooldown_prediction\" -n config src tests | head -60" in /Users/vladimir/Projects/cryodaq
 succeeded in 126ms:
config/analytics_layout.yaml:24:    main: cooldown_prediction
src/cryodaq/gui/shell/views/analytics_widgets.py:59:WIDGET_COOLDOWN_PREDICTION = "cooldown_prediction"
Binary file src/cryodaq/gui/shell/views/__pycache__/analytics_widgets.cpython-314.pyc matches
src/cryodaq/gui/widgets/overview_panel.py:1423:            self._update_cooldown_prediction(reading)
src/cryodaq/gui/widgets/overview_panel.py:1479:    def _update_cooldown_prediction(self, reading: Reading) -> None:
Binary file src/cryodaq/gui/widgets/__pycache__/overview_panel.cpython-314.pyc matches
Binary file tests/tools/__pycache__/test_mock_scenario.cpython-314-pytest-9.0.3.pyc matches
tests/tools/test_mock_scenario.py:67:    preds = [r for r in readings if r.channel == "analytics/cooldown_prediction"]
tests/tools/test_mock_scenario.py:70:        assert r.metadata.get("kind") == "cooldown_prediction"
tests/integration/test_analytics_view_lifecycle.py:85:        "cooldown": "cooldown_prediction",
Binary file tests/integration/__pycache__/test_analytics_view_lifecycle.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/gui/shell/views/__pycache__/test_analytics_widgets.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/gui/shell/views/__pycache__/test_analytics_view_phase_aware.cpython-314-pytest-9.0.3.pyc matches
tests/gui/shell/views/test_analytics_view_phase_aware.py:66:def test_cooldown_layout_main_is_cooldown_prediction(app):
tests/gui/shell/views/test_analytics_view_phase_aware.py:70:    assert analytics_widgets.id_of(slots["main"]) == "cooldown_prediction"
tests/gui/shell/views/test_analytics_view_phase_aware.py:157:def test_set_cooldown_forwards_to_cooldown_prediction_widget(app):
tests/gui/shell/views/test_analytics_widgets.py:40:        "cooldown_prediction",
tests/gui/shell/views/test_analytics_widgets.py:102:def test_cooldown_prediction_is_linear_y(app):

exec
/opt/homebrew/bin/bash -lc "sed -n '470,570p' src/cryodaq/analytics/cooldown_predictor.py && cat config/analytics_layout.yaml && sed -n '1470,1505p' src/cryodaq/gui/widgets/overview_panel.py && sed -n '320,370p' src/cryodaq/gui/widgets/analytics_panel.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
            dr = observed_rate_cold - rc.initial_rate_cold
            w_rate *= np.exp(-0.5 * (dr / sigma_rc) ** 2)

        if use_rate_warm and rc.initial_rate_warm != 0.0:
            # Warm rate is often more discriminating (e.g., illuminator)
            sigma_rw = max(rate_warm_std * 0.4, 1.0)
            dr_w = observed_rate_warm - rc.initial_rate_warm
            w_rate *= np.exp(-0.5 * (dr_w / sigma_rw) ** 2)

        w_total = w_prog * w_rate
        estimates.append((rc.name, t_rem, rc.duration_hours, w_total, w_prog, w_rate))

    if not estimates:
        return PredictionResult(
            t_remaining_hours=0,
            t_remaining_low_68=0,
            t_remaining_high_68=0,
            t_remaining_low_95=0,
            t_remaining_high_95=0,
            t_total_hours=0,
            progress=p_now,
            phase="unknown",
            T_cold_predicted_final=4.0,
            T_warm_predicted_final=85.0,
            n_references=0,
            individual_estimates=[],
        )

    # --- Fallback: if rate weighting killed all references, disable it ---
    rate_weights = np.array([e[5] for e in estimates])
    if (use_rate_cold or use_rate_warm) and np.max(rate_weights) < 0.01:
        estimates = [(n, r, d, wp, wp, 1.0) for n, r, d, _, wp, _ in estimates]

    t_rems = np.array([e[1] for e in estimates])
    t_tots = np.array([e[2] for e in estimates])
    weights = np.array([e[3] for e in estimates])
    weights /= weights.sum()

    t_rem_mean = float(np.average(t_rems, weights=weights))
    t_tot_mean = float(np.average(t_tots, weights=weights))
    t_rem_var = float(np.average((t_rems - t_rem_mean) ** 2, weights=weights))
    t_rem_std = max(np.sqrt(t_rem_var), 0.1)

    n_eff = len(estimates)
    t_68 = 1.0 + 0.5 / max(n_eff, 1)
    t_95 = 2.0 + 3.0 / max(n_eff, 1)

    if p_now >= 0.98:
        phase = "steady"
    elif T_cold_now > T_PHASE_BOUNDARY:
        phase = "phase1"
    elif T_cold_now > 15:
        phase = "transition"
    else:
        phase = "phase2"

    Tc_finals = [rc.T_cold_final for rc in model.curves]
    Tw_finals = [rc.T_warm_final for rc in model.curves if rc.T_warm_final > 0]

    result = PredictionResult(
        t_remaining_hours=t_rem_mean,
        t_remaining_low_68=max(0, t_rem_mean - t_68 * t_rem_std),
        t_remaining_high_68=t_rem_mean + t_68 * t_rem_std,
        t_remaining_low_95=max(0, t_rem_mean - t_95 * t_rem_std),
        t_remaining_high_95=t_rem_mean + t_95 * t_rem_std,
        t_total_hours=t_tot_mean,
        progress=p_now,
        phase=phase,
        T_cold_predicted_final=float(np.mean(Tc_finals)) if Tc_finals else 4.0,
        T_warm_predicted_final=float(np.mean(Tw_finals)) if Tw_finals else 85.0,
        n_references=n_eff,
        individual_estimates=[(n, round(r, 2)) for n, r, *_ in estimates],
    )

    if generate_trajectory and p_now < 0.98:
        p_future = np.linspace(p_now, 1.0, 200)
        t_fut = np.full((n_eff, 200), np.nan)
        Tc_fut = np.full((n_eff, 200), np.nan)
        Tw_fut = np.full((n_eff, 200), np.nan)

        for i, rc in enumerate(model.curves):
            if rc._t_of_p is not None:
                t_c = rc._t_of_p(p_future)
                t_c = t_c - float(rc._t_of_p(p_now)) + t_elapsed
                t_fut[i] = t_c
            if rc._Tc_of_p is not None:
                Tc_fut[i] = rc._Tc_of_p(p_future)
            if rc._Tw_of_p is not None:
                Tw_fut[i] = rc._Tw_of_p(p_future)

        result.future_t = np.nanmean(t_fut, axis=0)
        result.future_T_cold_mean = np.nanmean(Tc_fut, axis=0)
        result.future_T_warm_mean = np.nanmean(Tw_fut, axis=0)
        result.future_T_cold_upper = result.future_T_cold_mean + np.nanstd(Tc_fut, axis=0)
        result.future_T_cold_lower = result.future_T_cold_mean - np.nanstd(Tc_fut, axis=0)
        result.future_T_warm_upper = result.future_T_warm_mean + np.nanstd(Tw_fut, axis=0)
        result.future_T_warm_lower = result.future_T_warm_mean - np.nanstd(Tw_fut, axis=0)

    return result


# Phase → analytics layout mapping (Phase III.C).
#
# Each phase defines which widget occupies the large (1/2 screen) slot
# and which two fill the right column (1/4 each). Widget IDs map to
# factories registered in src/cryodaq/gui/shell/views/analytics_widgets.py.
#
# Changes to this file do NOT require code changes — new phases can be
# added by extending the mapping (assuming the widget IDs already exist
# in the registry). Hot-reload is NOT supported; a GUI restart is
# required after editing.

phases:
  preparation:
    main: temperature_overview
    top_right: pressure_current
    bottom_right: sensor_health_summary

  vacuum:
    main: vacuum_prediction
    top_right: temperature_overview
    bottom_right: pressure_current

  cooldown:
    main: cooldown_prediction
    top_right: temperature_overview
    bottom_right: r_thermal_placeholder

  measurement:
    main: r_thermal_live
    top_right: temperature_overview
    bottom_right: keithley_power

  warmup:
    main: temperature_trajectory
    top_right: pressure_current
    bottom_right: cooldown_history

  disassembly:
    main: experiment_summary
    top_right: null
    bottom_right: null

# Fallback when phase unknown or before an experiment starts.
fallback:
  main: temperature_overview
  top_right: pressure_current
  bottom_right: sensor_health_summary
            state_name = reading.metadata.get("state", "")
            if state_name:
                self._status_strip.set_safety_state(state_name)
                self._keithley_strip.set_safety_state(state_name)

        # Alarm count
        if channel == "analytics/alarm_count":
            self._status_strip.set_alarm_count(int(reading.value))

    def _update_cooldown_prediction(self, reading: Reading) -> None:
        """Draw ML prediction curve on temperature chart."""
        meta = reading.metadata or {}
        active = meta.get("cooldown_active", False)

        if not active:
            self._pred_curve.setVisible(False)
            self._ci_band.setVisible(False)
            self._eta_overlay.setVisible(False)
            return

        future_t = meta.get("future_t", [])
        future_mean = meta.get("future_T_cold_mean", [])
        future_upper = meta.get("future_T_cold_upper", [])
        future_lower = meta.get("future_T_cold_lower", [])
        cooldown_start = meta.get("cooldown_start_ts", 0)

        if cooldown_start and future_t and future_mean:
            abs_ts = [cooldown_start + h * 3600 for h in future_t]
            self._pred_curve.setData(abs_ts, future_mean)
            self._pred_curve.setVisible(True)

            if future_upper and future_lower and len(future_upper) == len(future_t):
                self._ci_upper_curve.setData(abs_ts, future_upper)
                self._ci_lower_curve.setData(abs_ts, future_lower)
                self._ci_band.setVisible(True)
            else:
            self._empty_overlay.setVisible(False)

        ch = reading.channel
        ts = reading.timestamp.timestamp()

        if ch.endswith("/R_thermal"):
            self._r_thermal_buf.append((ts, reading.value))
            self._current_r = reading.value
            self._r_value.setText(f"{reading.value:.4g}")

        elif ch.endswith("/cooldown_eta"):
            meta = reading.metadata or {}
            self._prediction_meta = meta
            active = meta.get("cooldown_active", False)

            # При активации cooldown — запомнить время старта (один раз)
            if active and not self._cooldown_active:
                self._cooldown_start_time = ts
                self._t_cold_buf.clear()

            self._cooldown_active = active
            t_rem = meta.get("t_remaining_hours", 0.0)
            ci = meta.get("t_remaining_ci68", 0.0)
            self._update_eta_display(t_rem, ci, meta)

        elif ch.endswith("/cooldown_eta_s"):
            # Совместимость со старым плагином cooldown_estimator
            if not self._cooldown_active:
                eta = reading.value
                if eta < 60:
                    self._eta_value.setText(f"{eta:.0f} сек")
                elif eta < 3600:
                    self._eta_value.setText(f"{eta / 60:.1f} мин")
                else:
                    self._eta_value.setText(f"{eta / 3600:.1f} ч")
                self._eta_subtitle.setVisible(False)
                self._progress_bar.setVisible(False)
                self._phase_label.setVisible(False)
                self._model_label.setVisible(False)

        elif reading.unit == "K" and "Детектор" in ch:
            # Живая линия T_cold — накапливать только во время cooldown
            if self._cooldown_active and self._cooldown_start_time > 0:
                rel_hours = (ts - self._cooldown_start_time) / 3600.0
                self._t_cold_buf.append((rel_hours, reading.value))

    def _update_eta_display(self, t_hours: float, ci_hours: float, meta: dict) -> None:
        """Обновить карточку ETA по данным cooldown_predictor."""
        active = meta.get("cooldown_active", False)

        if not active:

exec
/opt/homebrew/bin/bash -lc "sed -n '1,180p' src/cryodaq/gui/state/time_window.py && grep -R \"set_temperature_readings\\|temperature_overview\" -n tests/gui tests/integration | head -80 && grep -R \"readings_history\" -n tests | head -80" in /Users/vladimir/Projects/cryodaq
 succeeded in 113ms:
Binary file tests/core/__pycache__/test_readings_history.cpython-314.pyc matches
Binary file tests/core/__pycache__/test_readings_history.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/core/__pycache__/test_readings_history.cpython-314-pytest-9.0.2.pyc matches
tests/core/test_readings_history.py:1:"""Tests for readings_history engine command and SQLiteWriter.read_readings_history."""
tests/core/test_readings_history.py:55:def test_read_readings_history_all(writer_with_data) -> None:
tests/core/test_readings_history.py:58:    data = writer._read_readings_history()
tests/core/test_readings_history.py:65:def test_read_readings_history_time_filter(writer_with_data) -> None:
tests/core/test_readings_history.py:69:    data = writer._read_readings_history(from_ts=from_ts)
tests/core/test_readings_history.py:74:def test_read_readings_history_channel_filter(writer_with_data) -> None:
tests/core/test_readings_history.py:77:    data = writer._read_readings_history(channels=["Т1 Камера"])
tests/core/test_readings_history.py:83:def test_read_readings_history_limit(writer_with_data) -> None:
tests/core/test_readings_history.py:86:    data = writer._read_readings_history(limit_per_channel=10)
tests/core/test_readings_history.py:92:def test_read_readings_history_sorted_asc(writer_with_data) -> None:
tests/core/test_readings_history.py:95:    data = writer._read_readings_history()
tests/core/test_readings_history.py:102:async def test_async_read_readings_history(writer_with_data) -> None:
tests/core/test_readings_history.py:105:    data = await writer.read_readings_history(channels=["Т1 Камера"], limit_per_channel=5)
tests/test_engine_cooldown_history.py:82:    writer.read_readings_history = AsyncMock(return_value=t_hist or {})
tests/agents/assistant/test_query_adapters.py:188:    """Correctly computes min/max/mean/std from read_readings_history."""
tests/agents/assistant/test_query_adapters.py:200:    reader.read_readings_history = AsyncMock(return_value=readings_data)
tests/agents/assistant/test_query_adapters.py:216:    reader.read_readings_history = AsyncMock(return_value={"T_cold": []})
tests/agents/assistant/test_diagnostic.py:91:        reader.read_readings_history = AsyncMock(return_value={})
tests/agents/assistant/test_diagnostic.py:191:    failing_reader.read_readings_history = AsyncMock(side_effect=Exception("DB error"))
Binary file tests/agents/assistant/__pycache__/test_query_adapters.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/agents/assistant/__pycache__/test_diagnostic.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/agents/assistant/__pycache__/test_hf_v0472_tone.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/agents/__pycache__/test_gemma_diagnostic.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/__pycache__/test_engine_cooldown_history.cpython-314-pytest-9.0.3.pyc matches
tests/storage/test_sqlite_writer_executor_separation.py:4:read_readings_history, ...) must run on the dedicated _read_executor,
tests/storage/test_sqlite_writer_executor_separation.py:36:def test_read_readings_history_uses_read_executor():
tests/storage/test_sqlite_writer_executor_separation.py:37:    """read_readings_history has been on _read_executor for a while;
tests/storage/test_sqlite_writer_executor_separation.py:39:    source = inspect.getsource(SQLiteWriter.read_readings_history)
Binary file tests/storage/__pycache__/test_sqlite_writer_executor_separation.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/storage/__pycache__/test_sqlite_writer_executor_separation.cpython-314.pyc matches
tests/gui/shell/views/test_analytics_widget_experiment_summary.py:207:    F19: now also issues readings_history (2 ZMQ workers total); test verifies
tests/gui/shell/views/test_analytics_widget_experiment_summary.py:215:    # First call is alarm_v2_history, second is readings_history (F19 sub-item 1)
tests/gui/shell/views/test_analytics_widget_experiment_summary.py:408:    """ok=False from readings_history must render '—' in stats label."""
tests/gui/shell/views/test_analytics_widget_experiment_summary.py:415:    """set_experiment_status must trigger two ZMQ workers: alarm_history + readings_history."""
tests/gui/shell/views/test_analytics_widget_experiment_summary.py:429:    assert "readings_history" in call_cmds
Binary file tests/gui/shell/views/__pycache__/test_analytics_widget_experiment_summary.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/gui/shell/views/__pycache__/test_analytics_widget_temperature_trajectory.cpython-314-pytest-9.0.3.pyc matches
tests/gui/shell/views/test_analytics_widget_temperature_trajectory.py:93:    """TemperatureTrajectoryWidget must issue a readings_history ZMQ command
tests/gui/shell/views/test_analytics_widget_temperature_trajectory.py:102:    assert cmd["cmd"] == "readings_history"
Binary file tests/gui/__pycache__/test_shift_handover.cpython-314-pytest-9.0.3.pyc matches
tests/gui/test_shift_handover.py:199:    readings_history / experiment_status to populate sections."""
tests/gui/test_shift_handover.py:217:        "readings_history",

codex
Verdict: CC’s diagnosis is mostly correct.

A. CooldownPredictionWidget empty at base temp: expected by current code.
- `CooldownService._do_predict()` sets `cooldown_active = phase in (COOLING, STABILIZING)`.
- At physical base temp around 4 K, detector is not necessarily in `COOLING/STABILIZING`; if it is `IDLE` or complete-like, `cooldown_active=False`.
- The service still publishes a cooldown ETA reading if model + latest cold/warm temps exist.
- But `predict()` only generates `future_t` / trajectory when `p_now < 0.98`. At ~4 K, progress is effectively steady/base, so no future trajectory is produced.
- `CooldownPredictionWidget` receives `CooldownData`, but with empty `actual_trajectory`, empty `predicted_trajectory`, and empty `ci_trajectory`, so the plot remains blank.

B. TemperatureOverviewWidget persistently empty: possible, but not through `readings_history`.
- Important correction: `TemperatureOverviewWidget` does not call `_fetch_history()` at all. The `_fetch_history()` around line ~329 belongs to `TemperatureTrajectoryWidget`.
- `TemperatureOverviewWidget` is live-only: it displays data only after `set_temperature_readings()` receives K-unit readings.
- Therefore it can remain empty if no live K readings are forwarded while the widget is open / cached snapshot is empty.
- If header shows live K values and the AnalyticsView is open, new K readings should normally populate it. If DB has last write 161s ago and no fresh live readings arrive, an empty/unchanged overview is plausible.

C. F-P regression: not supported.
- Diff `v0.51.0..v0.52.0` does not modify `TemperatureOverviewWidget` or `CooldownPredictionWidget` bodies.
- The F-P changes touched vacuum prediction and R-thermal live behavior, not the two suspect widgets.
- No regression from F-P found for these paths.

D. Operator-visible empty explanation:
- `TemperatureTrajectoryWidget` has an empty-state label: `Ожидание данных…`.
- `TemperatureOverviewWidget` does not have an empty-state label; it shows an empty plot area.
- `CooldownPredictionWidget` also has no explicit explanation such as “Охлаждение завершено / базовая температура достигнута”; it delegates to `PredictionWidget` with empty data, so the operator gets no clear reason.

Severity:
- Not P0.
- Functional behavior at base temperature is expected.
- There is a P1/P2 UX gap: cooldown prediction can be blank with no explanation, especially during a cooldown phase label while the system is already at base temperature.
Verdict: CC’s diagnosis is mostly correct.

A. CooldownPredictionWidget empty at base temp: expected by current code.
- `CooldownService._do_predict()` sets `cooldown_active = phase in (COOLING, STABILIZING)`.
- At physical base temp around 4 K, detector is not necessarily in `COOLING/STABILIZING`; if it is `IDLE` or complete-like, `cooldown_active=False`.
- The service still publishes a cooldown ETA reading if model + latest cold/warm temps exist.
- But `predict()` only generates `future_t` / trajectory when `p_now < 0.98`. At ~4 K, progress is effectively steady/base, so no future trajectory is produced.
- `CooldownPredictionWidget` receives `CooldownData`, but with empty `actual_trajectory`, empty `predicted_trajectory`, and empty `ci_trajectory`, so the plot remains blank.

B. TemperatureOverviewWidget persistently empty: possible, but not through `readings_history`.
- Important correction: `TemperatureOverviewWidget` does not call `_fetch_history()` at all. The `_fetch_history()` around line ~329 belongs to `TemperatureTrajectoryWidget`.
- `TemperatureOverviewWidget` is live-only: it displays data only after `set_temperature_readings()` receives K-unit readings.
- Therefore it can remain empty if no live K readings are forwarded while the widget is open / cached snapshot is empty.
- If header shows live K values and the AnalyticsView is open, new K readings should normally populate it. If DB has last write 161s ago and no fresh live readings arrive, an empty/unchanged overview is plausible.

C. F-P regression: not supported.
- Diff `v0.51.0..v0.52.0` does not modify `TemperatureOverviewWidget` or `CooldownPredictionWidget` bodies.
- The F-P changes touched vacuum prediction and R-thermal live behavior, not the two suspect widgets.
- No regression from F-P found for these paths.

D. Operator-visible empty explanation:
- `TemperatureTrajectoryWidget` has an empty-state label: `Ожидание данных…`.
- `TemperatureOverviewWidget` does not have an empty-state label; it shows an empty plot area.
- `CooldownPredictionWidget` also has no explicit explanation such as “Охлаждение завершено / базовая температура достигнута”; it delegates to `PredictionWidget` with empty data, so the operator gets no clear reason.

Severity:
- Not P0.
- Functional behavior at base temperature is expected.
- There is a P1/P2 UX gap: cooldown prediction can be blank with no explanation, especially during a cooldown phase label while the system is already at base temperature.
