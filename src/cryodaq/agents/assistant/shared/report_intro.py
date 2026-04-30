"""Synchronous Гемма report intro generator for the DOCX pipeline.

Called from ReportGenerator.generate() which runs in a thread — must be
fully synchronous. Uses urllib.request for blocking HTTP; no asyncio.

Slice C: generates formal scientific annotation paragraph for experiment
reports. Graceful degradation: returns None on any failure so report
generation continues without an intro rather than crashing.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_OLLAMA_PATH = "/api/generate"


@dataclass
class IntroConfig:
    """Configuration for synchronous assistant report intro generation."""

    enabled: bool = False  # explicitly opted in via agent.yaml c_campaign_report: true
    base_url: str = "http://localhost:11434"
    model: str = "gemma4:e4b"
    timeout_s: float = 180.0  # campaign report is long — gemma4:e4b needs 60-120s
    max_tokens: int = 2048
    temperature: float = 0.2  # lower → more formal, less creative
    brand_name: str = "Гемма"


def load_intro_config() -> IntroConfig:
    """Load config from agent.yaml; returns disabled defaults on any error."""
    try:
        import yaml

        from cryodaq.paths import get_config_dir

        agent_yaml = get_config_dir() / "agent.yaml"
        with agent_yaml.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        # Try agent.* namespace (v0.45.0+), fall back to gemma.* (legacy)
        if "agent" in raw:
            section = raw["agent"]
        elif "gemma" in raw:
            logger.warning(
                "report_intro: legacy gemma.* config namespace detected; "
                "migrate to agent.*. Backward compatibility removed in v0.46.0."
            )
            section = raw["gemma"]
        else:
            section = {}
        gemma = section
        ollama = gemma.get("ollama", {})
        slices = gemma.get("slices", {})
        # Both agent.enabled AND c_campaign_report must be true
        gemma_enabled = bool(gemma.get("enabled", True))
        slice_enabled = bool(slices.get("c_campaign_report", False))
        base_timeout = float(ollama.get("timeout_s", 60.0))
        return IntroConfig(
            enabled=gemma_enabled and slice_enabled,
            base_url=str(ollama.get("base_url", "http://localhost:11434")),
            model=str(ollama.get("default_model", "gemma4:e4b")),
            # Campaign reports generate 200-400 words — use at least 180s
            timeout_s=max(base_timeout, 180.0),
            brand_name=str(gemma.get("brand_name", "Гемма")),
        )
    except Exception:
        logger.debug("report_intro: failed to load agent.yaml — using defaults", exc_info=True)
        return IntroConfig()  # enabled=False by default


def generate_report_intro(dataset: Any, config: IntroConfig | None = None) -> str | None:
    """Generate formal experiment annotation synchronously.

    Returns the generated text (plain Russian, no Markdown), or None if
    Гемма is disabled, unavailable, or returns an empty/truncated response.
    """
    if config is None:
        config = load_intro_config()
    if not config.enabled:
        logger.debug("report_intro: slice_c disabled — skipping")
        return None
    try:
        from cryodaq.agents.assistant.live.prompts import (
            CAMPAIGN_REPORT_INTRO_SYSTEM,
            CAMPAIGN_REPORT_INTRO_USER,
            format_with_brand,
        )

        ctx = _build_context(dataset)
        user_prompt = CAMPAIGN_REPORT_INTRO_USER.format(**ctx)
        system_prompt = format_with_brand(CAMPAIGN_REPORT_INTRO_SYSTEM, config.brand_name)
        t0 = time.monotonic()
        text = _call_ollama_sync(user_prompt, system_prompt, config)
        latency = time.monotonic() - t0
        if not text or not text.strip():
            logger.warning("report_intro: empty response from Гемма (%.1fs)", latency)
            return None
        logger.info(
            "report_intro: intro generated (%.1fs, %d chars)",
            latency,
            len(text),
        )
        return text.strip()
    except Exception:
        logger.warning("report_intro: generation failed — skipping intro", exc_info=True)
        return None


def _call_ollama_sync(prompt: str, system: str, config: IntroConfig) -> str:
    """Blocking HTTP POST to Ollama /api/generate. Raises on error."""
    url = config.base_url.rstrip("/") + _OLLAMA_PATH
    payload: dict[str, Any] = {
        "model": config.model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {
            "num_predict": config.max_tokens,
            "temperature": config.temperature,
        },
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=config.timeout_s) as resp:
        result: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
    if "error" in result:
        raise RuntimeError(f"Ollama error: {result['error']}")
    return str(result.get("response", ""))


def _build_context(dataset: Any) -> dict[str, str]:
    """Extract context fields from ReportDataset for the campaign report prompt."""
    exp: dict[str, Any] = dataset.metadata.get("experiment", {})

    experiment_id = str(exp.get("experiment_id") or exp.get("id") or "—")
    name = str(exp.get("title") or exp.get("name") or "—")
    operator = str(exp.get("operator") or "—")
    sample = str(exp.get("sample") or "—")
    start_time = _fmt_dt(exp.get("start_time"))
    end_time = _fmt_dt(exp.get("end_time"))
    duration = _compute_duration(exp.get("start_time"), exp.get("end_time"))
    status = _status_ru(str(exp.get("status") or ""))
    phases_text = _format_phases(exp)
    channel_stats = _format_channel_stats(dataset)
    alarms_summary = _format_alarms(dataset)
    operator_notes = _format_operator_notes(dataset)

    return {
        "experiment_id": experiment_id,
        "name": name,
        "operator": operator,
        "sample": sample,
        "start_time": start_time,
        "end_time": end_time,
        "duration": duration,
        "status": status,
        "phases_text": phases_text,
        "channel_stats": channel_stats,
        "alarms_summary": alarms_summary,
        "operator_notes": operator_notes,
    }


def _fmt_dt(val: Any) -> str:
    if not val:
        return "—"
    try:
        if isinstance(val, str):
            dt = datetime.fromisoformat(val)
        elif isinstance(val, datetime):
            dt = val
        else:
            return str(val)
        return dt.astimezone().strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(val)


def _compute_duration(start: Any, end: Any) -> str:
    try:
        s = datetime.fromisoformat(str(start)).astimezone(UTC) if start else None
        e = datetime.fromisoformat(str(end)).astimezone(UTC) if end else datetime.now(UTC)
        if s is None:
            return "—"
        total_s = int((e - s).total_seconds())
        h, rem = divmod(total_s, 3600)
        m, _ = divmod(rem, 60)
        if h > 0:
            return f"{h} ч {m} мин"
        return f"{m} мин"
    except Exception:
        return "—"


def _status_ru(status: str) -> str:
    _MAP = {
        "completed": "Завершён штатно",
        "finalized": "Завершён штатно",
        "stopped": "Остановлен",
        "aborted": "Прерван",
        "running": "В процессе",
    }
    return _MAP.get(status.lower(), status or "—")


def _format_phases(exp: dict[str, Any]) -> str:
    phases = exp.get("phases") or exp.get("phase_history") or []
    if not phases:
        return "нет данных"
    lines: list[str] = []
    for i, p in enumerate(phases):
        name = p.get("phase") or p.get("name") or f"Фаза {i+1}"
        started = _fmt_dt(p.get("started_at") or p.get("start_time"))
        ended = _fmt_dt(p.get("ended_at") or p.get("end_time"))
        if ended != "—":
            lines.append(f"- {name}: {started} — {ended}")
        else:
            lines.append(f"- {name}: {started}")
    return "\n".join(lines) if lines else "нет данных"


def _format_channel_stats(dataset: Any) -> str:
    readings = getattr(dataset, "readings", [])
    if not readings:
        return "нет данных"
    by_channel: dict[str, list[float]] = defaultdict(list)
    for r in readings:
        by_channel[r.channel].append(r.value)
    lines: list[str] = []
    for ch, vals in sorted(by_channel.items()):
        if not vals:
            continue
        mn, mx, avg = min(vals), max(vals), sum(vals) / len(vals)
        unit = next((r.unit for r in readings if r.channel == ch), "")
        unit_str = f" {unit}" if unit else ""
        lines.append(
            f"- {ch}: мин {mn:.4g}{unit_str} / макс {mx:.4g}{unit_str} / ср {avg:.4g}{unit_str}"
        )
    return "\n".join(lines[:12]) if lines else "нет данных"


def _format_alarms(dataset: Any) -> str:
    alarm_readings = getattr(dataset, "alarm_readings", [])
    if not alarm_readings:
        return "алармов не зафиксировано"
    channels = sorted({r.channel for r in alarm_readings})
    return f"Затронутые каналы ({len(channels)}): {', '.join(channels[:8])}"


def _format_operator_notes(dataset: Any) -> str:
    operator_log = getattr(dataset, "operator_log", [])
    gemma_entries = [
        e for e in operator_log
        if "gemma" not in (getattr(e, "tags", None) or ())
        and "ai" not in (getattr(e, "tags", None) or ())
        and e.message.strip()
    ]
    if not gemma_entries:
        return "нет записей"
    notes = [e.message.strip()[:200] for e in gemma_entries[:4]]
    return "\n".join(f"- {n}" for n in notes)
