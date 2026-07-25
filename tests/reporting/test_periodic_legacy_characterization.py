"""Semantic characterization of the legacy periodic Telegram PNG product.

These tests deliberately inspect matplotlib objects rather than pixels.  Two
tests freeze known legacy defects only so H3 can prove that it removes them;
they are not requirements for the replacement renderer.
"""

# pyplot must be imported only after the non-interactive backend is selected.
# ruff: noqa: E402, I001

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import matplotlib
import pytest

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from cryodaq.notifications import periodic_report
from cryodaq.notifications.periodic_report import PeriodicReporter


BASE = datetime(2026, 7, 10, 1, 0, tzinfo=UTC).timestamp()
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class AlarmStub:
    channels: tuple[str, ...]


class AlarmSnapshotFake:
    def __init__(self, snapshots: list[dict[str, AlarmStub]]) -> None:
        self.snapshots = deque(snapshots)
        self.calls = 0

    def get_active(self) -> dict[str, AlarmStub]:
        self.calls += 1
        if len(self.snapshots) > 1:
            return self.snapshots.popleft()
        return self.snapshots[0]


class NoIOBroker:
    async def subscribe(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("legacy characterization must not subscribe")

    async def unsubscribe(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("legacy characterization must not unsubscribe")


@pytest.fixture
def recorded_periodic_window() -> tuple[dict[str, str], dict[str, deque[tuple[float, float]]]]:
    units = {
        "Т10": "K",
        "Т2": "K",
        "Т1": "K",
        "rack/cold_finger": "K",
        "VSP63D_1/pressure": "mbar",
        "aux/pressure_2": "mbar",
        "Keithley/smua/voltage": "V",
    }
    buffers = {
        "Т10": deque([(BASE, 10.04), (BASE + 60, 9.876)]),
        "Т2": deque([(BASE, 20.0), (BASE + 60, 19.95)]),
        "Т1": deque([(BASE, 4.0), (BASE + 60, 3.9996)]),
        "rack/cold_finger": deque([(BASE, 8.5), (BASE + 60, 8.25)]),
        "VSP63D_1/pressure": deque(
            [
                (BASE, -1.0),
                (BASE + 10, 0.0),
                (BASE + 20, float("nan")),
                (BASE + 30, float("inf")),
                (BASE + 40, 1e-6),
                (BASE + 50, 1e-5),
                (BASE + 60, 1e-4),
            ]
        ),
        "aux/pressure_2": deque([(BASE, 2e-5), (BASE + 60, 3e-5)]),
        "Keithley/smua/voltage": deque([(BASE, 0.0123456)]),
    }
    return units, buffers


@pytest.fixture
def fixed_display_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            del tz
            return cls(2026, 7, 10, 4, 5)

    monkeypatch.setattr(periodic_report, "datetime", FixedDateTime)


def _reporter(
    units: dict[str, str],
    buffers: dict[str, deque[tuple[float, float]]],
    alarm_engine: AlarmSnapshotFake,
) -> PeriodicReporter:
    reporter = PeriodicReporter(
        broker=NoIOBroker(),
        alarm_engine=alarm_engine,
        bot_token="TEST_TOKEN_NOT_SECRET",
        chat_id=123456,
    )
    reporter._units = dict(units)
    reporter._buffers = {channel: deque(points) for channel, points in buffers.items()}
    return reporter


@dataclass
class ChartCapture:
    png: bytes
    figure: Figure
    subplots_args: tuple[Any, ...]
    subplots_kwargs: dict[str, Any]
    savefig_kwargs: dict[str, Any]
    legend_kwargs: list[dict[str, Any]]


@contextmanager
def _captured_chart(monkeypatch: pytest.MonkeyPatch, reporter: PeriodicReporter):
    real_subplots = plt.subplots
    real_close = plt.close
    real_savefig = Figure.savefig
    real_legend = Axes.legend
    capture: dict[str, Any] = {"legend_kwargs": []}

    def recording_subplots(*args: Any, **kwargs: Any):
        result = real_subplots(*args, **kwargs)
        capture["subplots_args"] = args
        capture["subplots_kwargs"] = kwargs
        capture["figure"] = result[0]
        return result

    def recording_savefig(self: Figure, *args: Any, **kwargs: Any) -> Any:
        capture["savefig_kwargs"] = kwargs
        return real_savefig(self, *args, **kwargs)

    def recording_legend(self: Axes, *args: Any, **kwargs: Any) -> Any:
        capture["legend_kwargs"].append(kwargs)
        return real_legend(self, *args, **kwargs)

    monkeypatch.setattr(plt, "subplots", recording_subplots)
    monkeypatch.setattr(plt, "close", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(Figure, "savefig", recording_savefig)
    monkeypatch.setattr(Axes, "legend", recording_legend)

    try:
        png = reporter._generate_chart()
        result = ChartCapture(
            png=png,
            figure=capture["figure"],
            subplots_args=capture["subplots_args"],
            subplots_kwargs=capture["subplots_kwargs"],
            savefig_kwargs=capture["savefig_kwargs"],
            legend_kwargs=capture["legend_kwargs"],
        )
        yield result
    finally:
        figure = capture.get("figure")
        if figure is not None:
            real_close(figure)


def _subset(
    window: tuple[dict[str, str], dict[str, deque[tuple[float, float]]]],
    units: set[str],
) -> tuple[dict[str, str], dict[str, deque[tuple[float, float]]]]:
    all_units, all_buffers = window
    selected = {channel: unit for channel, unit in all_units.items() if unit in units}
    return selected, {channel: all_buffers[channel] for channel in selected}


def test_legacy_temperature_only_semantic_layout(
    monkeypatch: pytest.MonkeyPatch,
    fixed_display_clock: None,
    recorded_periodic_window: tuple[dict[str, str], dict[str, deque[tuple[float, float]]]],
) -> None:
    del fixed_display_clock
    units, buffers = _subset(recorded_periodic_window, {"K"})
    reporter = _reporter(units, buffers, AlarmSnapshotFake([{}]))

    with _captured_chart(monkeypatch, reporter) as chart:
        assert chart.subplots_args == (1, 1)
        assert chart.subplots_kwargs == {"figsize": (12, 6)}
        assert tuple(chart.figure.get_size_inches()) == (12.0, 6.0)
        assert chart.savefig_kwargs == {"format": "png", "dpi": 100, "bbox_inches": "tight"}
        assert len(chart.figure.axes) == 1

        axes = chart.figure.axes[0]
        assert axes.get_ylabel() == "Температура, К"
        assert axes.xaxis.get_major_formatter().fmt == "%H:%M"
        assert [line.get_label() for line in axes.lines] == ["Т1", "Т2", "Т10", "cold_finger"]
        assert [text.get_text() for text in axes.texts] == ["4", "19.95", "9.876", "8.25"]
        assert [text.xy[1] for text in axes.texts] == [3.9996, 19.95, 9.876, 8.25]
        assert [text.xy[0].timestamp() for text in axes.texts] == [BASE + 60] * 4
        assert chart.figure._suptitle is not None
        assert chart.figure._suptitle.get_text() == "CryoDAQ | 10.07.2026 04:05"
        assert chart.png.startswith(PNG_SIGNATURE)
        assert len(chart.png) > len(PNG_SIGNATURE)


def test_chart_capture_closes_figure_when_legacy_render_raises(
    monkeypatch: pytest.MonkeyPatch,
    recorded_periodic_window: tuple[dict[str, str], dict[str, deque[tuple[float, float]]]],
) -> None:
    units, buffers = _subset(recorded_periodic_window, {"K"})
    reporter = _reporter(units, buffers, AlarmSnapshotFake([{}]))
    before = plt.get_fignums()

    def fail_savefig(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("injected save failure")

    monkeypatch.setattr(Figure, "savefig", fail_savefig)
    with pytest.raises(RuntimeError, match="injected save failure"):
        with _captured_chart(monkeypatch, reporter):
            raise AssertionError("unreachable")

    assert plt.get_fignums() == before


def test_legacy_temperature_pressure_layout_and_log_filter(
    monkeypatch: pytest.MonkeyPatch,
    recorded_periodic_window: tuple[dict[str, str], dict[str, deque[tuple[float, float]]]],
) -> None:
    units, buffers = _subset(recorded_periodic_window, {"K", "mbar"})
    reporter = _reporter(units, buffers, AlarmSnapshotFake([{}]))

    with _captured_chart(monkeypatch, reporter) as chart:
        assert chart.subplots_args == (2, 1)
        assert chart.subplots_kwargs == {
            "figsize": (12, 8),
            "sharex": False,
            "gridspec_kw": {"height_ratios": [2, 1]},
        }
        temp_axes, pressure_axes = chart.figure.axes
        assert temp_axes.get_ylabel() == "Температура, К"
        assert pressure_axes.get_ylabel() == "Давление, мбар"
        assert pressure_axes.get_yscale() == "log"
        pressure_line = next(line for line in pressure_axes.lines if line.get_label() == "pressure")
        assert list(pressure_line.get_ydata()) == [1e-6, 1e-5, 1e-4]
        lower, upper = pressure_axes.get_ylim()
        assert 0 < lower < upper
        assert chart.png.startswith(PNG_SIGNATURE)


def test_legacy_channel_order_labels_and_exact_alarm_highlight(
    monkeypatch: pytest.MonkeyPatch,
    recorded_periodic_window: tuple[dict[str, str], dict[str, deque[tuple[float, float]]]],
) -> None:
    units, buffers = recorded_periodic_window
    units = dict(units)
    buffers = dict(buffers)
    for index in range(24):
        channel = f"rack/sensor_{index:02d}"
        units[channel] = "K"
        buffers[channel] = deque([(BASE, float(index))])
    alarms = {
        "T1_LOW": AlarmStub(("Т1",)),
        "VACUUM_WARN": AlarmStub(("VSP63D_1/pressure",)),
        "NONMATCHING": AlarmStub(("Т",)),
    }
    reporter = _reporter(units, buffers, AlarmSnapshotFake([alarms]))

    with _captured_chart(monkeypatch, reporter) as chart:
        temp_axes, pressure_axes = chart.figure.axes
        temp_lines = temp_axes.lines
        assert [line.get_label() for line in temp_lines[:4]] == ["Т1", "Т2", "Т10", "cold_finger"]
        assert [line.get_label() for line in pressure_axes.lines] == ["pressure", "pressure_2"]

        by_label = {line.get_label(): line for axes in chart.figure.axes for line in axes.lines}
        for alarmed in ("Т1", "pressure"):
            assert by_label[alarmed].get_color() == "red"
            assert by_label[alarmed].get_linewidth() == 1.8
            assert by_label[alarmed].get_zorder() == 3
        for normal in ("Т2", "Т10", "cold_finger", "pressure_2"):
            assert by_label[normal].get_linewidth() == 1.2
            assert by_label[normal].get_zorder() == 2
        assert all(kwargs["loc"] == "upper left" for kwargs in chart.legend_kwargs)
        assert max(kwargs["ncol"] for kwargs in chart.legend_kwargs) == 4


@pytest.mark.parametrize(
    ("active", "expected_tail"),
    [
        (
            {
                "T1_LOW": AlarmStub(("Т1",)),
                "VACUUM_WARN": AlarmStub(("VSP63D_1/pressure",)),
            },
            "<b>Активные тревоги (2):</b>\n  ⚠ T1_LOW\n  ⚠ VACUUM_WARN",
        ),
        ({}, "Тревог нет ✓"),
    ],
)
def test_legacy_caption_groups_values_units_and_alarm_order(
    fixed_display_clock: None,
    recorded_periodic_window: tuple[dict[str, str], dict[str, deque[tuple[float, float]]]],
    active: dict[str, AlarmStub],
    expected_tail: str,
) -> None:
    del fixed_display_clock
    units, buffers = recorded_periodic_window
    reporter = _reporter(units, buffers, AlarmSnapshotFake([active]))

    expected = (
        "<b>CryoDAQ | Периодический отчёт</b>\n"
        "Время: 10.07.2026 04:05\n\n"
        "<b>Температуры:</b>\n"
        "  Т1: 4 К\n"
        "  Т2: 19.95 К\n"
        "  Т10: 9.876 К\n"
        "  cold_finger: 8.25 К\n\n"
        "<b>Давление:</b>\n"
        "  pressure: 0.0001 мбар\n"
        "  pressure_2: 3e-05 мбар\n\n"
        "<b>Прочие каналы:</b>\n"
        "  voltage: 0.01235 V\n\n"
        f"{expected_tail}"
    )
    assert reporter._generate_summary() == expected


def test_legacy_other_only_chart_is_empty_but_caption_keeps_other(
    monkeypatch: pytest.MonkeyPatch,
    fixed_display_clock: None,
    recorded_periodic_window: tuple[dict[str, str], dict[str, deque[tuple[float, float]]]],
) -> None:
    del fixed_display_clock
    units, buffers = _subset(recorded_periodic_window, {"V"})
    reporter = _reporter(units, buffers, AlarmSnapshotFake([{}]))

    with _captured_chart(monkeypatch, reporter) as chart:
        axes = chart.figure.axes[0]
        assert axes.get_ylabel() == "Температура, К"
        assert not axes.lines
        assert [text.get_text() for text in axes.texts] == ["Нет данных"]

    caption = reporter._generate_summary()
    assert "<b>Температуры:</b>" not in caption
    assert "<b>Давление:</b>" not in caption
    assert "<b>Прочие каналы:</b>\n  voltage: 0.01235 V" in caption
    assert caption.endswith("Тревог нет ✓")


class MultipartCapture:
    def __init__(self) -> None:
        self.fields: list[tuple[str, object, dict[str, object]]] = []

    def add_field(self, name: str, value: object, **kwargs: object) -> None:
        self.fields.append((name, value, kwargs))


class ResponseCapture:
    status = 200

    async def __aenter__(self) -> ResponseCapture:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class SessionCapture:
    def __init__(self) -> None:
        self.sent_to_photo_endpoint = False
        self.form: MultipartCapture | None = None

    def post(self, url: str, *, data: MultipartCapture) -> ResponseCapture:
        self.sent_to_photo_endpoint = url.endswith("/sendPhoto")
        self.form = data
        return ResponseCapture()


@pytest.mark.asyncio
async def test_legacy_wire_caption_is_blindly_sliced_at_1024(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Freeze a known defect: legacy slicing can split an HTML tag."""
    multipart = MultipartCapture()
    session = SessionCapture()
    reporter = _reporter({}, {}, AlarmSnapshotFake([{}]))
    source = "x" * 1023 + "<b>unsafe</b>"

    monkeypatch.setattr(periodic_report.aiohttp, "FormData", lambda: multipart)

    async def get_session() -> SessionCapture:
        return session

    monkeypatch.setattr(reporter, "_get_session", get_session)
    await reporter._send_photo(b"png", source)

    fields = {name: (value, kwargs) for name, value, kwargs in multipart.fields}
    assert fields["chat_id"] == ("123456", {})
    assert fields["photo"] == (b"png", {"filename": "report.png", "content_type": "image/png"})
    assert fields["caption"] == (source[:1024], {})
    assert fields["caption"][0].endswith("<")
    assert fields["parse_mode"] == ("HTML", {})
    assert session.sent_to_photo_endpoint is True
    assert session.form is multipart


def test_legacy_chart_and_caption_can_observe_different_alarm_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    fixed_display_clock: None,
    recorded_periodic_window: tuple[dict[str, str], dict[str, deque[tuple[float, float]]]],
) -> None:
    """Freeze a known defect: chart and caption query alarms separately."""
    del fixed_display_clock
    units, buffers = _subset(recorded_periodic_window, {"K"})
    alarms = AlarmSnapshotFake([{"T1_LOW": AlarmStub(("Т1",))}, {}])
    reporter = _reporter(units, buffers, alarms)

    with _captured_chart(monkeypatch, reporter) as chart:
        by_label = {line.get_label(): line for line in chart.figure.axes[0].lines}
        assert by_label["Т1"].get_color() == "red"

    caption = reporter._generate_summary()
    assert alarms.calls == 2
    assert "Тревог нет ✓" in caption
    assert "T1_LOW" not in caption
