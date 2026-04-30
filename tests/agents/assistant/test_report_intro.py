"""Tests for Slice C: Гемма campaign report intro generator."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from cryodaq.agents.assistant.shared.report_intro import (
    IntroConfig,
    _build_context,
    _format_channel_stats,
    _format_phases,
    generate_report_intro,
)

# ---------------------------------------------------------------------------
# Minimal ReportDataset stub
# ---------------------------------------------------------------------------


@dataclass
class _FakeReading:
    channel: str
    value: float
    unit: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    instrument_id: str = "test"
    status: str = "ok"


@dataclass
class _FakeLogRecord:
    message: str
    tags: tuple[str, ...] = ()
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    experiment_id: str | None = None
    author: str = ""
    source: str = "test"


@dataclass
class _FakeDataset:
    metadata: dict[str, Any] = field(default_factory=dict)
    readings: list[_FakeReading] = field(default_factory=list)
    operator_log: list[_FakeLogRecord] = field(default_factory=list)
    alarm_readings: list[_FakeReading] = field(default_factory=list)


def _make_dataset(
    experiment_id: str = "exp-smoke-001",
    name: str = "Тест охлаждения",
    status: str = "completed",
    phases: list[dict[str, Any]] | None = None,
    readings: list[_FakeReading] | None = None,
    operator_log: list[_FakeLogRecord] | None = None,
    alarm_readings: list[_FakeReading] | None = None,
) -> _FakeDataset:
    if phases is None:
        phases = [
            {"phase": "PREP", "started_at": "2026-05-01T10:00:00+00:00",
             "ended_at": "2026-05-01T10:15:00+00:00"},
            {"phase": "COOL", "started_at": "2026-05-01T10:15:00+00:00",
             "ended_at": "2026-05-01T12:00:00+00:00"},
        ]
    return _FakeDataset(
        metadata={
            "experiment": {
                "experiment_id": experiment_id,
                "title": name,
                "operator": "Иванов А.В.",
                "sample": "Cu-2024-001",
                "start_time": "2026-05-01T10:00:00+00:00",
                "end_time": "2026-05-01T12:00:00+00:00",
                "status": status,
                "phases": phases,
            }
        },
        readings=readings or [
            _FakeReading("T1", 4.2, "K"),
            _FakeReading("T1", 4.5, "K"),
            _FakeReading("T2", 4.3, "K"),
        ],
        operator_log=operator_log or [
            _FakeLogRecord("Начало охлаждения. Все параметры в норме."),
            _FakeLogRecord("Целевая температура достигнута."),
        ],
        alarm_readings=alarm_readings or [],
    )


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


def test_build_context_includes_experiment_id() -> None:
    dataset = _make_dataset(experiment_id="exp-123")
    ctx = _build_context(dataset)
    assert ctx["experiment_id"] == "exp-123"


def test_build_context_includes_duration() -> None:
    dataset = _make_dataset()
    ctx = _build_context(dataset)
    assert ctx["duration"] != "—"
    assert "ч" in ctx["duration"] or "мин" in ctx["duration"]


def test_format_phases_lists_all_phases() -> None:
    exp = {
        "phases": [
            {"phase": "PREP", "started_at": "2026-05-01T10:00:00+00:00",
             "ended_at": "2026-05-01T10:15:00+00:00"},
            {"phase": "COOL", "started_at": "2026-05-01T10:15:00+00:00",
             "ended_at": "2026-05-01T12:00:00+00:00"},
        ]
    }
    result = _format_phases(exp)
    assert "PREP" in result
    assert "COOL" in result


def test_format_channel_stats_computes_min_max_mean() -> None:
    readings = [
        _FakeReading("T1", 4.0, "K"),
        _FakeReading("T1", 5.0, "K"),
        _FakeReading("T1", 6.0, "K"),
    ]
    dataset = _make_dataset(readings=readings)
    result = _format_channel_stats(dataset)
    assert "T1" in result
    assert "4" in result  # min
    assert "6" in result  # max


def test_generate_report_intro_disabled_returns_none() -> None:
    dataset = _make_dataset()
    config = IntroConfig(enabled=False)
    result = generate_report_intro(dataset, config)
    assert result is None


def test_generate_report_intro_ollama_unavailable_returns_none() -> None:
    """Connection error (URLError) → graceful None, no exception raised."""
    import urllib.error

    dataset = _make_dataset()
    config = IntroConfig(enabled=True)
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        result = generate_report_intro(dataset, config)
    assert result is None


def test_generate_report_intro_calls_ollama_and_returns_text() -> None:
    """Mock successful Ollama response → returns non-empty Russian text."""
    dataset = _make_dataset()
    config = IntroConfig(enabled=True)
    mock_response_body = json.dumps({"response": "Настоящий отчёт посвящён эксперименту."})

    class _MockResp:
        def read(self):
            return mock_response_body.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    with patch("urllib.request.urlopen", return_value=_MockResp()):
        result = generate_report_intro(dataset, config)

    assert result == "Настоящий отчёт посвящён эксперименту."


def test_generate_report_intro_empty_ollama_response_returns_none() -> None:
    """Empty response text → None (not an empty string dispatched to DOCX)."""
    dataset = _make_dataset()
    config = IntroConfig(enabled=True)
    mock_body = json.dumps({"response": "   "})

    class _MockResp:
        def read(self):
            return mock_body.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    with patch("urllib.request.urlopen", return_value=_MockResp()):
        result = generate_report_intro(dataset, config)

    assert result is None


def test_operator_notes_excludes_gemma_tagged_entries() -> None:
    """Гемма-tagged entries must not appear in operator notes context."""
    dataset = _make_dataset(
        operator_log=[
            _FakeLogRecord("Человек: температура достигнута.", tags=()),
            _FakeLogRecord("🤖 Гемма: аларм summary text", tags=("gemma", "ai")),
        ]
    )
    ctx = _build_context(dataset)
    assert "Гемма" not in ctx["operator_notes"] or "Человек" in ctx["operator_notes"]
    assert "аларм summary" not in ctx["operator_notes"]
