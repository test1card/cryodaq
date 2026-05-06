# HF v0.47.2 — Гемма conversational tone + ChannelManager + chart wiring

> Real-world testing surfaced multiple UX issues, plus discovered
> that infrastructure for half of them ALREADY EXISTS but is not
> wired. This HF connects existing systems и iterates prompts.
>
> ARCHITECT REQUESTs source: parallel real-world testing session
> (2026-05-01 telegram-bot-realworld), conversation logged inline.
>
> Severity: HIGH UX. Bot non-blocking but feels like robot, not
> assistant. Charts already work but agent doesn't use them.
>
> Effort: M (~150 LOC code + ~80 LOC tests = ~230 LOC total).
> Mostly wiring + prompt iteration; minimal new code.

---

## 0. Context

### 0.1 Conversation that triggered this

```
Vladimir: привет

Гемма: Привет! Извини, я не могу обработать этот запрос. Я могу
       отвечать только на запросы, связанные с данными лаборатории.
       Попробуй спросить что-нибудь вроде "что сейчас?", "ETA
       вакуума" или "в какой фазе?".

Vladimir: привет! как дела? что у нас сейчас, какой этап?

Гемма: Привет! У нас сейчас эксперимент cc35331d8c89 находится в
       фазе cooldown. На данный момент нет активных тревог. Ключевые
       температуры, такие как T_cold, T_4K и другие, отсутствуют в
       данных. Давление составляет 1.38e-06 mbar, а прогнозы по ETA
       охлаждения и вакуума не определены.
```

### 0.2 Issues identified

**I1 — Greeting refused.** "привет" classified as `unknown`,
robotic refusal. Should respond friendly + brief offer.

**I2 — UUID exposed.** `cc35331d8c89` shown to operator. Adapter
must read existing `name`/`title` schema fields. Plus mock mode
needs synthetic name auto-injection.

**I3 — Channel display names not used.** `T_cold, T_4K` are not
even real channel names — actual lab uses `Т1`, `Т2`, etc with
display names ("Криостат верх", "Криостат низ", "Детектор", ...)
defined in `channels.yaml` AND in `_DEFAULT_CHANNELS` fallback in
`ChannelManager`.

**The infrastructure exists** (`ChannelManager.get_display_name()`
returns `"Т7 Детектор"` form). The query adapters (`BrokerSnapshot`,
`CompositeAdapter`) don't use it. Pure wiring fix.

**I4 — "Не определены" framing.** ETA values unavailable because
service hasn't accumulated history. Current: clinical "не
определены". Should be: conversational "охлаждение только началось,
появится через несколько минут".

**I5 — No chart in query response.** Vladimir wants: when operator
asks "что сейчас?", attach a PNG chart with current temperature
trends. Bot already builds charts via `PeriodicReporter` (matplotlib
+ Telegram `sendPhoto`). Query agent doesn't use this capability.

Pure wiring fix: extract chart-rendering logic from
`PeriodicReporter`, expose as utility, query agent calls it for
relevant intent categories.

---

## 1. Architect decisions baked in

| Decision | Verdict | Rationale |
|---|---|---|
| Greeting category | NEW `greeting` enum value | Friendly response, no LLM call |
| UUID handling | Read `title`→`name`→omit | Schema already supports both fields |
| Mock mode synthetic name | Auto-inject `mock_YYYY-MM-DD_HHMM` if no GUI provides one | Engine startup fix |
| Channel labels | Wire `BrokerSnapshot` and adapters to `ChannelManager` | Infrastructure exists, just disconnected |
| Display name format | `"Т7 Детектор"` (existing format from `get_display_name`) | Don't reinvent — use what exists |
| Chart rendering | Extract `PeriodicReporter._build_chart` to utility module, call from query agent | Existing function, just expose it |
| Chart trigger categories | `composite_status`, `range_stats`, optionally `current_value` for temperature/pressure channels | Categories where time-series visualization adds info |
| Chart latency | Async render in background, send chart AFTER text response | Don't block text reply on PNG render |
| Chart on/off control | `agent.query.charts.enabled` config (default true) | Operator may want text-only some days |
| Chart window | Default 2h (matches PeriodicReporter default) | Familiar to operator |
| LLM model unchanged | gemma4:e2b | Smoke quality acceptable |
| Backward compat | Old query flow without charts must still work if `charts.enabled=false` | Don't break existing tests |

---

## 2. Implementation phases

### 2.1 Phase A — Greeting intent + handler (~30 LOC + 10 tests)

[Same as previous spec version]

#### 2.1.1 Schema extension

`src/cryodaq/agents/assistant/query/schemas.py`:

```python
class QueryCategory(str, Enum):
    CURRENT_VALUE = "current_value"
    ETA_COOLDOWN = "eta_cooldown"
    ETA_VACUUM = "eta_vacuum"
    RANGE_STATS = "range_stats"
    PHASE_INFO = "phase_info"
    ALARM_STATUS = "alarm_status"
    COMPOSITE_STATUS = "composite_status"
    GREETING = "greeting"  # NEW
    OUT_OF_SCOPE_HISTORICAL = "out_of_scope_historical"
    OUT_OF_SCOPE_GENERAL = "out_of_scope_general"
    UNKNOWN = "unknown"
```

#### 2.1.2 Classifier prompt update

`prompts.py` INTENT_CLASSIFIER_SYSTEM — add greeting rule before
composite_status rule:

```
- "привет", "здравствуй", "hi", "hello", "доброе утро", "добрый день",
  "добрый вечер", "доброй ночи" → greeting (БЕЗ engine query)

- "привет, что сейчас?" → composite_status (greeting + actionable;
  actionable wins)
- "доброе утро, как дела?" → greeting (no engine query implied)
```

#### 2.1.3 Static greeting handler

`agent.py` — new method:

```python
def _greeting_response(self, query: str) -> str:
    """Static templated greeting. No LLM call, no fetch."""
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    hour = now.hour
    if 5 <= hour < 12:
        prefix = "Доброе утро"
    elif 12 <= hour < 18:
        prefix = "Добрый день"
    elif 18 <= hour < 23:
        prefix = "Добрый вечер"
    else:
        prefix = "Доброй ночи"
    return (
        f"{prefix}! Я {self._config.brand_name}, могу рассказать что "
        f"сейчас в системе. Попробуй: «что сейчас?», «ETA вакуума?», "
        f"«в какой фазе?», «есть ли тревоги?»."
    )
```

Audit log entry recorded даже без LLM call (для consistency).

#### 2.1.4 Tests

```python
def test_classifier_categorizes_simple_greeting():
def test_classifier_categorizes_morning_greeting():
def test_classifier_greeting_with_question_goes_composite():
def test_greeting_response_morning_time():
def test_greeting_response_night_time():
def test_greeting_response_no_llm_call():
def test_greeting_response_includes_brand_name():
def test_greeting_response_offers_examples():
def test_router_dispatches_greeting_to_static_handler():
```

### 2.2 Phase B — ChannelManager wiring (~40 LOC + 15 tests)

**Critical insight: don't add `display_label` field.** `ChannelManager`
ALREADY has `get_display_name(channel)` returning `"Т7 Детектор"`
form. Just wire it to query agent.

#### 2.2.1 BrokerSnapshot accepts ChannelManager

`src/cryodaq/agents/assistant/query/adapters/broker_snapshot.py`:

```python
class BrokerSnapshot:
    def __init__(
        self,
        broker: DataBroker,
        channel_manager: ChannelManager | None = None,
    ) -> None:
        self._broker = broker
        self._channel_manager = channel_manager
        # ... existing init ...
    
    def display_name(self, channel_id: str) -> str:
        """Operator-facing channel label.
        
        Returns ChannelManager.get_display_name() if available,
        otherwise channel_id passthrough.
        """
        if self._channel_manager is None:
            return channel_id
        try:
            return self._channel_manager.get_display_name(channel_id)
        except Exception:
            return channel_id
    
    async def latest_with_labels(self) -> dict[str, dict]:
        """Returns dict[channel_id, {value, unit, display_name, timestamp}]."""
        async with self._lock:
            return {
                ch_id: {
                    "value": r.value,
                    "unit": r.unit,
                    "display_name": self.display_name(ch_id),
                    "timestamp": r.timestamp,
                }
                for ch_id, r in self._latest.items()
            }
```

#### 2.2.2 Engine wiring

`engine.py` — pass existing `channel_manager` instance to
`BrokerSnapshot` constructor. ChannelManager already singleton-loaded
via `get_channel_manager()` (see existing engine startup).

```python
# Existing line:
channel_manager = get_channel_manager()

# In query agent setup:
broker_snapshot = BrokerSnapshot(broker, channel_manager=channel_manager)
```

#### 2.2.3 CompositeAdapter and CurrentValueAdapter use labels

These adapters currently format raw channel IDs into prompt context.
Update to use `latest_with_labels()` instead of `latest_all()`.

Format temperatures section like:
```
- Т1 Криостат верх: 78.2 K
- Т6 Экран 4К: 4.5 K
- Т7 Детектор: 2.1 K
```

Not:
```
- Т1: 78.2 K
- Т6: 4.5 K
```

#### 2.2.4 Format prompts updated

`FORMAT_COMPOSITE_STATUS_USER` and `FORMAT_CURRENT_VALUE_USER`:
note that `temps_text` already includes display names — prompt
just instructs LLM to use them as-is (don't strip down to ID).

Add to FORMAT_RESPONSE_SYSTEM:
```
- Каналы упоминай с display name (например "Т7 Детектор" а не
  голое "Т7"). Display name приходит готовым в данных ниже.
```

#### 2.2.5 Tests

```python
def test_broker_snapshot_uses_channel_manager_display_name():
    """Т7 → 'Т7 Детектор' when ChannelManager has standard config."""

def test_broker_snapshot_fallback_passthrough_when_no_manager():
    """ChannelManager=None → returns channel_id as-is."""

def test_broker_snapshot_handles_unknown_channel():
    """Unknown channel → ChannelManager fallback to ID."""

def test_latest_with_labels_includes_display_name_field():
    """Result dict includes display_name key per channel."""

def test_composite_text_uses_display_names():
    """Composite status text contains 'Т7 Детектор', not bare 'Т7'."""

def test_current_value_text_uses_display_names():
    """Current value response uses display name."""

def test_engine_wires_channel_manager_to_broker_snapshot():
    """engine.py constructs BrokerSnapshot with channel_manager arg."""
```

### 2.3 Phase C — Conversational tone + UUID handling (~30 LOC + 15 tests)

#### 2.3.1 FORMAT_RESPONSE_SYSTEM rewrite

```
Тон: коллега в lab chat, не database query interface.

Принципы тона:
- Если оператор поздоровался — поздоровайся в ответ перед сутью.
- Каналы упоминай с display name (например "Т7 Детектор" а не
  голое "Т7"). Display name приходит готовым в данных ниже.
- Не пиши UUID и внутренние идентификаторы. Используй человеческое
  название эксперимента из поля "Эксперимент:" если оно задано.
  Если нет — просто скажи "идёт эксперимент" без ID.
- "Не определено", "отсутствует", "null" — clinical/robotic.
  Используй conversational: "пока не считается", "только начало,
  появится через несколько минут", "поток ещё прогревается",
  "сервис не запущен в этой конфигурации".
- Объясняй почему данных нет если знаешь причину.
- 1-3 предложения для простого вопроса, 3-5 для composite_status.
- Не перечисляй ВСЕ поля сводки — выбери самое важное.
- Если вопрос содержал greeting — начни с greeting back перед сутью.
```

#### 2.3.2 ExperimentAdapter — read name/title

Schema `ExperimentInfo` already has `name` (NOT NULL '') and `title`
(NOT NULL ''). Adapter must read them.

```python
async def status(self) -> ExperimentStatus | None:
    if not self._em.active_experiment_id:
        return None
    active = self._em.active_experiment
    full_id = active.experiment_id
    
    # Read existing schema fields
    title = (getattr(active, "title", "") or "").strip()
    name = (getattr(active, "name", "") or "").strip()
    
    # Pick best human label
    if title:
        display_name = title
    elif name:
        display_name = name
    else:
        display_name = None  # No human label — UUID-only experiment
    
    return ExperimentStatus(
        experiment_id=full_id,
        display_name=display_name,
        # ... existing fields ...
    )
```

CompositeAdapter formats `experiment_text`:
- `display_name` set: `f"«{display_name}»"` (e.g. "«Cooldown TIM stack 2026-05-15»")
- `display_name` None: just say `"эксперимент"` без ID

NEVER output full UUID к operator under any condition.

#### 2.3.3 Mock mode synthetic name (engine-side)

Recon during Phase C: find where `cryodaq-engine --mock` triggers
experiment auto-start. Likely in `engine.py` startup or
`ExperimentManager` lazy creation path.

If experiment is created without explicit name argument, inject
synthetic:

```python
from datetime import datetime
synthetic_name = f"mock_{datetime.now().strftime('%Y-%m-%d_%H%M')}"
synthetic_title = f"Мок-режим от {datetime.now().strftime('%d.%m.%Y %H:%M')}"
# Pass to ExperimentManager.start_experiment(name=synthetic_name, title=synthetic_title, ...)
```

If mock mode doesn't auto-start experiment, defer this part to
ARCHITECT DECISION NEEDED — may not be necessary because real lab
usage always sets name via GUI.

#### 2.3.4 Cooldown/Vacuum ETA degradation messages

Add reason field for None states:

```python
@dataclass
class CooldownETA:
    t_remaining_hours: float | None
    cooldown_active: bool
    n_history_points: int
    reason: str | None  # "warming_up" | "model_not_converged" | "not_active" | None
    # ... rest ...
```

CooldownAdapter populates reason based on service state:
- service is None → reason="service_unavailable"
- service.last_prediction() is None and history < 60 points → reason="warming_up"
- service.last_prediction() is None and history >= 60 → reason="model_not_converged"
- service.cooldown_active() is False → reason="not_active"
- prediction available → reason=None, full data

If `CooldownService.cooldown_active()` and `.history_size()` don't
exist, add ~10 LOC service extension methods.

Format prompt for ETA cooldown:
- reason=warming_up → "Engine только запустился, ETA появится через несколько минут когда наберётся история показаний."
- reason=model_not_converged → "Модель пока не сошлась — обычно после 10-15 минут активного охлаждения становится понятно."
- reason=not_active → "Сейчас охлаждения нет, модель не активна."
- reason=service_unavailable → "Сервис прогноза охлаждения не настроен в этой конфигурации."

Same pattern для VacuumAdapter (warming_up / not_converged / not_pumping).

#### 2.3.5 Tests

```python
def test_composite_avoids_uuid_when_both_name_title_empty():
def test_composite_uses_title_when_set():
def test_composite_uses_name_when_only_name_set():
def test_composite_prefers_title_over_name():
def test_eta_cooldown_warming_up_friendly_message():
def test_eta_cooldown_not_active_friendly_message():
def test_eta_vacuum_no_pumping_friendly_message():
def test_response_starts_with_greeting_when_query_has_greeting():
def test_no_robotic_phrases_in_composite():
    """Verify 'не определены' / 'null' / 'отсутствует' don't appear."""
def test_mock_engine_assigns_synthetic_name_if_no_explicit():
    """If implemented per §2.3.3."""
```

### 2.4 Phase D — Chart rendering wiring (~50 LOC + 25 tests)

**The critical wiring task.** PeriodicReporter has matplotlib chart
rendering AND Telegram `sendPhoto` integration. Extract to shared
utility, call from query agent.

#### 2.4.1 Extract chart utility

`src/cryodaq/notifications/charts.py` — NEW module:

```python
"""Chart rendering for Гемма query agent.

Extracted from PeriodicReporter._build_chart for reuse by query
agent (composite_status, range_stats categories).
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryodaq.core.broker import DataBroker
    from cryodaq.core.channel_manager import ChannelManager
    from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)


async def render_temperature_chart(
    *,
    readings_by_channel: dict[str, list[tuple[float, float]]],
    units: dict[str, str],
    channel_manager: ChannelManager | None = None,
    chart_hours: float = 2.0,
    title: str = "Температуры",
) -> bytes | None:
    """Render PNG chart of temperature/pressure series.
    
    Parameters
    ----------
    readings_by_channel: {channel_id: [(unix_ts, value), ...]}
    units: {channel_id: unit_str}
    channel_manager: for display names (Т7 → "Т7 Детектор")
    chart_hours: window depth
    title: chart title
    
    Returns
    -------
    bytes: PNG-encoded chart, or None if no data to render.
    """
    if not readings_by_channel:
        return None
    
    # Lazy import matplotlib to avoid startup cost when charts disabled
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    
    fig, ax = plt.subplots(figsize=(10, 6), dpi=100)
    
    now_unix = datetime.now(UTC).timestamp()
    cutoff_unix = now_unix - chart_hours * 3600
    
    for ch_id, points in sorted(readings_by_channel.items()):
        if not points:
            continue
        # Filter by window
        recent = [(t, v) for t, v in points if t >= cutoff_unix]
        if not recent:
            continue
        ts, vals = zip(*recent, strict=False)
        # Display name
        if channel_manager:
            try:
                label = channel_manager.get_display_name(ch_id)
            except Exception:
                label = ch_id
        else:
            label = ch_id
        # Unit annotation
        unit = units.get(ch_id, "")
        full_label = f"{label} [{unit}]" if unit else label
        # X axis as relative minutes
        x = [(t - cutoff_unix) / 60 for t in ts]
        ax.plot(x, vals, label=full_label, linewidth=1.2)
    
    ax.set_xlabel("Время, мин (относительно)")
    ax.set_ylabel("Значение")
    ax.set_title(title)
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)
    
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
```

NOTE: This is independent from PeriodicReporter — it doesn't share
state. PeriodicReporter has its own ring buffers. Query agent
needs to either (a) maintain its own chart-feeding cache, OR (b)
read from SQLite for chart data.

#### 2.4.2 Chart data source

Recommend **(b) SQLite read.** Reasons:
- BrokerSnapshot only has latest value per channel, no history
- PeriodicReporter has ring buffer но running independently —
  shared state would couple two unrelated services
- SQLiteAdapter already implements `range_stats(channel, window)`
  — extend with `get_readings_for_chart(channels, window_hours)`
  returning (ts, value) tuples per channel

`SQLiteAdapter` extension:

```python
async def get_readings_for_chart(
    self,
    *,
    channels: list[str],
    window_hours: float = 2.0,
    max_points_per_channel: int = 1500,
) -> tuple[dict[str, list[tuple[float, float]]], dict[str, str]]:
    """Read recent readings for chart rendering.
    
    Returns:
        readings_by_channel: {ch: [(unix_ts, value), ...]}
        units: {ch: unit_str}
    """
    end_ts = datetime.now(UTC).timestamp()
    start_ts = end_ts - window_hours * 3600
    
    readings_by_channel: dict[str, list[tuple[float, float]]] = {}
    units: dict[str, str] = {}
    
    for ch in channels:
        recs = await self._reader.get_readings(
            channel=ch,
            start_ts=start_ts,
            end_ts=end_ts,
            limit=max_points_per_channel,
        )
        if recs:
            readings_by_channel[ch] = [(r.timestamp.timestamp(), r.value) for r in recs]
            units[ch] = recs[0].unit
    
    return readings_by_channel, units
```

#### 2.4.3 ChartDispatcher

`src/cryodaq/agents/assistant/query/chart_dispatcher.py`:

```python
"""Chart attachment for query agent responses."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from cryodaq.notifications.charts import render_temperature_chart

logger = logging.getLogger(__name__)


class ChartDispatcher:
    """Attach charts to query responses for relevant categories."""
    
    def __init__(
        self,
        *,
        sqlite_adapter,
        channel_manager,
        telegram_send_photo: Any,  # Callable: async fn(chat_id, png_bytes, caption=None)
        enabled: bool = True,
        default_window_hours: float = 2.0,
        visible_channels_only: bool = True,
    ) -> None:
        self._sqlite = sqlite_adapter
        self._channel_manager = channel_manager
        self._send_photo = telegram_send_photo
        self._enabled = enabled
        self._default_window = default_window_hours
        self._visible_only = visible_channels_only
    
    async def maybe_dispatch(
        self,
        *,
        intent_category: str,
        chat_id: int | str,
        target_channels: list[str] | None = None,
    ) -> bool:
        """Dispatch chart if intent category warrants it."""
        if not self._enabled:
            return False
        
        # Determine if this category gets a chart
        chart_categories = {"composite_status", "range_stats"}
        if intent_category not in chart_categories:
            return False
        
        # Determine channels to plot
        if target_channels:
            channels = target_channels
        elif self._channel_manager:
            # All visible temperature channels
            channels = [
                ch for ch in self._channel_manager.list_channels()
                if self._channel_manager.is_visible(ch)
            ]
        else:
            channels = []
        
        if not channels:
            return False
        
        try:
            readings, units = await self._sqlite.get_readings_for_chart(
                channels=channels,
                window_hours=self._default_window,
            )
            if not readings:
                logger.debug("ChartDispatcher: no data for chart")
                return False
            
            png = await render_temperature_chart(
                readings_by_channel=readings,
                units=units,
                channel_manager=self._channel_manager,
                chart_hours=self._default_window,
                title=f"Температуры за последние {self._default_window:.0f} ч",
            )
            if png is None:
                return False
            
            await self._send_photo(chat_id, png)
            return True
        except Exception as exc:
            logger.warning("Chart dispatch failed: %s", exc)
            return False
```

NOTE: `_send_photo` is callable injected from outside. TelegramCommandBot
exposes `send_photo()` method (or wrapper extracted from PeriodicReporter
which has the implementation). Phase D recon: find existing send_photo
implementation, expose as standalone callable.

#### 2.4.4 Query agent calls chart dispatcher

`AssistantQueryAgent.handle_query`:

```python
async def handle_query(self, query: str, *, chat_id: int | str) -> str:
    # ... existing intent classify + fetch + format flow ...
    
    response_text = await self._format_response(intent, fetched_data, query)
    
    # Async chart dispatch (don't block text reply)
    if self._chart_dispatcher:
        asyncio.create_task(
            self._chart_dispatcher.maybe_dispatch(
                intent_category=intent.category,
                chat_id=chat_id,
                target_channels=intent.target_channels,
            ),
            name=f"chart_dispatch_{int(time.time() * 1000)}",
        )
    
    return response_text
```

Chart dispatched as fire-and-forget — text reply returns immediately.
Chart arrives ~1-3s later (matplotlib render time).

#### 2.4.5 Engine wiring

```python
# In engine.py query agent setup
chart_dispatcher = ChartDispatcher(
    sqlite_adapter=sqlite_adapter,
    channel_manager=channel_manager,
    telegram_send_photo=telegram_bot.send_photo,  # method on TelegramCommandBot
    enabled=agent_config.query_charts_enabled,  # default True
    default_window_hours=agent_config.query_charts_window_hours,  # default 2.0
)

query_agent = AssistantQueryAgent(
    # ... existing args ...
    chart_dispatcher=chart_dispatcher,
)
```

If TelegramCommandBot doesn't have `send_photo()` method exposed,
add ~30 LOC method wrapping `aiohttp` POST к Telegram `sendPhoto`
endpoint (PeriodicReporter has the pattern — copy structure).

#### 2.4.6 Configuration

`config/agent.yaml`:

```yaml
agent:
  query:
    # ... existing fields ...
    charts:
      enabled: true
      window_hours: 2.0
      visible_channels_only: true
      send_for_categories:
        - composite_status
        - range_stats
```

#### 2.4.7 Tests

```python
def test_chart_dispatcher_skips_when_disabled():
def test_chart_dispatcher_skips_for_non_chart_categories():
def test_chart_dispatcher_renders_for_composite_status():
def test_chart_dispatcher_renders_for_range_stats():
def test_chart_dispatcher_uses_target_channels_when_specified():
def test_chart_dispatcher_uses_visible_channels_default():
def test_chart_dispatcher_handles_no_data_gracefully():
def test_render_temperature_chart_returns_png_bytes():
def test_render_temperature_chart_uses_display_names():
def test_render_temperature_chart_handles_empty_input():
def test_sqlite_adapter_get_readings_for_chart_window():
def test_query_agent_dispatches_chart_async():
    """Verify chart dispatch doesn't block text response."""
def test_query_agent_text_response_unchanged_when_chart_fails():
    """Chart failure shouldn't fail query."""
```

### 2.5 Phase E — Smoke test (manual, with real Telegram)

Setup:
1. Engine restart с обновлённой v0.47.2 codebase
2. mock mode: `cryodaq-engine --mock`
3. Telegram bot connected through Amnezia (assuming v0.47.1 SSL fix shipped)

Scenarios:

**Greeting:**
- "привет" → friendly greeting back, time-aware, examples offered, NO chart
- "доброе утро" → "Доброе утро! ..."
- "привет, что сейчас?" → composite status (NOT greeting refusal) WITH chart

**Composite status:**
- "что сейчас?" → 
  - Russian text: friendly, includes display name (Т7 Детектор not Т7), human experiment label or "идёт эксперимент"
  - Followed by PNG chart of temperatures last 2h, channel labels readable
  - Latency: text ~10s, chart ~1-3s after

**Specific channel:**
- "какая Т7?" → text response с display name "Т7 Детектор: 4.5K"
- No chart for single-value queries (current_value не в chart categories)

**Range stats:**
- "в каком диапазоне Т7 за час?" → text + chart of just Т7 last hour

**ETA degradation:**
- "ETA охлаждения" before predictor accumulates → "Engine только запустился..."
- After 15+ min cooldown → real ETA with CI

**No UUID:**
- After mock startup, "что сейчас?" should NOT show UUID even if mock
  experiment has empty title/name. If §2.3.3 implemented, should
  show "Мок-режим от ...". Otherwise just "идёт эксперимент".

Document в `artifacts/handoffs/2026-05-XX-hf-v0.47.2-tone-smoke.md`
с before/after sample screenshots from phone:
- Before: robotic UUID composite, no chart
- After: friendly composite with display names + chart attached

### 2.6 Phase F — Audit + ratify

Per ORCHESTRATION v1.4 §16.3 — UX/wiring scope, 1-model audit
(Codex sufficient). Focus auditor on:
- Backward compat: existing F30 tests stay green
- ChannelManager wiring completeness
- Chart rendering correctness (PNG valid, labels right)
- No regression в Russian quality
- Async chart dispatch doesn't leak tasks
- Error handling: chart failure doesn't fail query

### 2.7 Phase G — Release v0.47.2

After audit + smoke PASS:
1. Bump pyproject 0.47.1 → 0.47.2
2. CHANGELOG entry
3. Tag, push

CHANGELOG:
```markdown
## [0.47.2] — 2026-05-XX — HF: Гемма conversational tone + ChannelManager + charts

### Added
- `GREETING` intent category with time-aware static handler (no LLM call)
- `ChannelManager` wired to `BrokerSnapshot` and query adapters — display
  names ("Т7 Детектор") used throughout instead of bare channel IDs
- `ChartDispatcher` — query agent attaches PNG charts for composite_status
  and range_stats categories. Charts render last N hours from SQLite.
- `notifications.charts.render_temperature_chart` — extracted utility
  shared by PeriodicReporter and query agent
- `SQLiteAdapter.get_readings_for_chart` for time-series data extraction
- ETA degradation reasons (`warming_up` / `model_not_converged` /
  `not_active` / `service_unavailable`) with conversational framing
- Mock mode synthetic experiment name (`mock_YYYY-MM-DD_HHMM`) when GUI
  doesn't provide explicit name

### Changed
- AssistantQueryAgent prompts emphasize conversational tone
- Composite status uses display names from ChannelManager not raw IDs
- ETA degradation framed conversationally instead of "не определены"
- Experiment text uses `title`/`name` from ExperimentInfo schema
  (already supported, just wasn't wired to query agent)

### Fixed
- "привет" no longer refused — friendly greeting back instead
- UUIDs no longer exposed to operator (read existing name/title fields)
- Channel internal IDs no longer leaked — display names used throughout
- Operator now sees temperature charts on "что сейчас?" requests

### Reference
- ARCHITECT REQUEST from realworld testing 2026-05-01
- Sample bad output: see HF spec §0.1
- HF spec: CC_PROMPT_HF_V0.47.2_TONE_ITERATION.md
```

---

## 3. Acceptance criteria

After all phases:

1. ✅ "привет" returns time-aware greeting, no refusal
2. ✅ Composite status uses display names ("Т7 Детектор") not bare IDs
3. ✅ Composite status doesn't expose UUID even when no name/title set
4. ✅ Composite status uses experiment title/name when set
5. ✅ Mock mode auto-assigns synthetic experiment name
6. ✅ ETA degradation conversationally framed (warming_up, etc.)
7. ✅ Charts rendered for composite_status и range_stats categories
8. ✅ Chart dispatch async — text reply not blocked
9. ✅ Chart failure doesn't fail query (graceful degradation)
10. ✅ Chart uses display names in legend
11. ✅ All existing F30 tests still pass (backward compat)
12. ✅ ≥45 new tests across phases A-D
13. ✅ Smoke confirms friendlier feel + chart visible from phone

---

## 4. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Chart rendering blocks query event loop | MEDIUM | Async fire-and-forget dispatch; matplotlib in run_in_executor if needed |
| matplotlib import slow at startup | LOW | Lazy import inside render function |
| ChartDispatcher race with TelegramCommandBot send_photo | LOW | TelegramCommandBot.send_photo already async-safe |
| Display names inconsistent (yaml vs defaults) | MEDIUM | ChannelManager.get_display_name handles both; tests verify both paths |
| Chart fires on every query — Telegram rate limit | MEDIUM | Chart only for composite_status + range_stats; explicit category filter |
| Mock synthetic name collision if engine restarts within minute | LOW | Include seconds in name format if collision observed |
| Existing PeriodicReporter charts diverge from query charts | LOW | Same render utility used eventually; PeriodicReporter migration to shared utility deferred to next cycle |

---

## 5. Hard stops

- Phase B ChannelManager wiring breaks existing tests → STOP
- Phase D chart rendering errors crash engine → STOP, root cause
- Phase E smoke chart not arriving → STOP, debug send_photo path
- Phase E chart arrives but with bare channel IDs → STOP, ChannelManager
  not threaded through render
- Backward compat — F30 tests fail unexpectedly → STOP
- Greeting handler accidentally bypasses safety/scope → STOP

---

## 6. Architect comm-out discipline

Surface immediately:

- Phase B: `ChannelManager.list_channels()` and `is_visible()` API
  exists? If not, what's the equivalent? (Fallback: read channels.yaml directly)
- Phase D recon: `TelegramCommandBot.send_photo()` exposed? PeriodicReporter
  has the pattern (`_send_telegram_photo`). Need to expose as
  reusable method on bot.
- Phase D recon: SQLite reader API — does `get_readings(channel, start_ts, end_ts)`
  exist? If only batch query, may need to extend reader.
- Phase 2.3.3 mock mode: where does engine auto-start experiment in
  `--mock` path? Surface for architect review of fix scope.
- Phase 2.3.4 CooldownService API additions (`cooldown_active`,
  `history_size`): exist already or new?

Continue with safest interpretation per ORCHESTRATION v1.4 §13.2,
document in handoff.

---

## 7. Begin

1. Phase A — greeting category + handler + tests
2. Phase B — ChannelManager wiring (recon API first)
3. Phase C — tone prompts + experiment name + ETA reasons + tests
4. Phase D — chart utility extraction + ChartDispatcher + wiring
5. Phase E — manual smoke (Vladimir tests с phone)
6. Phase F — Codex audit
7. Phase G — release v0.47.2

Estimated 3-4 hours total including audit + smoke.

GO.
