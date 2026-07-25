from __future__ import annotations

import html
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from cryodaq.periodic_state import latest_completed_slot
from cryodaq.reporting.periodic_input import (
    MAX_CAPTION_BYTES,
    MAX_CAPTION_CODEPOINTS,
    PeriodicInputError,
    serialize_periodic_input,
    validate_caption_html,
)
from cryodaq.reporting.periodic_renderer import render_periodic_png


def _payload(
    readings: list[dict[str, object]],
    *,
    alarms: list[dict[str, object]] | None = None,
    history_complete: bool = True,
    alarm_state_complete: bool = True,
    dropped: int = 0,
    bad: int = 0,
) -> dict[str, object]:
    slot = latest_completed_slot(7_200.0, 1_800)
    return {
        "schema": 1,
        "generation_id": "a" * 32,
        "owner_token": "b" * 32,
        "slot": {
            "slot_id": slot.slot_id,
            "slot_start": slot.slot_start,
            "slot_end": slot.slot_end,
            "window_start": 0,
            "window_end": slot.slot_end,
            "config_fingerprint": "sha256:" + "f" * 64,
        },
        "render": {
            "display_time": "10.07.2026 04:05",
            "include_channels": None,
            "max_points_per_channel": 20_000,
            "max_total_points": 100_000,
            "max_input_bytes": 65_536,
            "history_complete": history_complete,
            "alarm_state_complete": alarm_state_complete,
            "dropped_points": dropped,
            "bad_points": bad,
            "source_errors": ["deadline:2026-07-10:sqlite"] if not history_complete else [],
        },
        "readings": readings,
        "alarms": alarms or [],
    }


def _validated(payload: dict[str, object]):
    return serialize_periodic_input(payload, expected_max_input_bytes=65_536)[1]


@contextmanager
def _capture_render(monkeypatch: pytest.MonkeyPatch, snapshot, output: Path):
    import cryodaq.reporting.periodic_renderer as module

    real_subplots = module.plt.subplots
    real_close = module.plt.close
    captured: dict[str, Any] = {}

    def subplots(*args: object, **kwargs: object):
        result = real_subplots(*args, **kwargs)
        captured["args"] = args
        captured["kwargs"] = kwargs
        captured["figure"] = result[0]
        return result

    monkeypatch.setattr(module.plt, "subplots", subplots)
    monkeypatch.setattr(module.plt, "close", lambda *_args, **_kwargs: None)
    try:
        result = render_periodic_png(snapshot, output, deadline_monotonic=module.time.monotonic() + 10)
        yield result, captured
    finally:
        if "figure" in captured:
            real_close(captured["figure"])


def _row(ts: float, iid: str, channel: str, value: float | None, unit: str) -> dict[str, object]:
    return {"ts": ts, "iid": iid, "ch": channel, "v": value, "u": unit, "st": "ok"}


def test_temperature_only_matches_legacy_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _validated(
        _payload(
            [
                _row(7_000, "ls", "Т10", 10.04, "K"),
                _row(7_001, "ls", "Т10", 9.876, "K"),
                _row(7_002, "ls", "Т2", 19.95, "K"),
                _row(7_003, "ls", "Т1", 3.9996, "K"),
                _row(7_004, "ls", "rack/cold_finger", 8.25, "K"),
            ]
        )
    )
    with _capture_render(monkeypatch, snapshot, tmp_path) as (result, capture):
        assert capture["args"] == (1, 1)
        assert capture["kwargs"] == {"figsize": (12, 6)}
        axes = capture["figure"].axes[0]
        assert axes.get_ylabel() == "Температура, К"
        assert axes.xaxis.get_major_formatter().fmt == "%H:%M"
        assert [line.get_label() for line in axes.lines] == ["Т1", "Т2", "Т10", "cold_finger"]
        assert [text.get_text() for text in axes.texts] == ["4", "19.95", "9.876", "8.25"]
        assert result.png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert result.width >= 100 and result.height >= 100


def test_temperature_pressure_layout_and_log_filter_match_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _validated(
        _payload(
            [
                _row(7_000, "ls", "T", 4.0, "K"),
                _row(7_001, "vac", "P", None, "mbar"),
                _row(7_002, "vac", "P", -1.0, "mbar"),
                _row(7_003, "vac", "P", 0.0, "mbar"),
                _row(7_004, "vac", "P", 1e-6, "mbar"),
                _row(7_005, "vac", "P", 1e-4, "mbar"),
            ]
        )
    )
    with _capture_render(monkeypatch, snapshot, tmp_path) as (_result, capture):
        assert capture["args"] == (2, 1)
        assert capture["kwargs"]["gridspec_kw"] == {"height_ratios": [2, 1]}
        pressure = capture["figure"].axes[1]
        assert pressure.get_yscale() == "log"
        assert list(pressure.lines[0].get_ydata()) == [1e-6, 1e-4]


def test_channel_order_labels_alarm_styles_and_legend_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readings = [
        _row(7_000 + index, "ls", channel, float(index + 1), "K")
        for index, channel in enumerate(["Т10", "Т2", "Т1", "a/same", "b/same"])
    ]
    readings.sort(key=lambda item: (item["ts"], item["iid"], item["ch"]))
    alarms = [
        {
            "id": "exact",
            "level": "CRITICAL",
            "channels": ["Т1"],
            "triggered_at": 6_900.0,
            "acknowledged": False,
        }
    ]
    snapshot = _validated(_payload(readings, alarms=alarms))
    with _capture_render(monkeypatch, snapshot, tmp_path) as (_result, capture):
        lines = capture["figure"].axes[0].lines
        assert [line.get_label() for line in lines] == ["Т1", "Т2", "Т10", "same", "same"]
        assert lines[0].get_color() == "red"
        assert lines[0].get_linewidth() == 1.8
        assert lines[1].get_linewidth() == 1.2


def test_caption_short_exact_contract(tmp_path: Path) -> None:
    readings = [
        _row(7_000, "ls", "Т1", 4.0, "K"),
        _row(7_001, "vac", "P", 1e-5, "mbar"),
        _row(7_002, "smu", "smua/voltage", 0.0123456, "V"),
    ]
    alarms = [
        {
            "id": "T1_LOW",
            "level": "WARNING",
            "channels": ["Т1"],
            "triggered_at": 6_900.0,
            "acknowledged": False,
        }
    ]
    result = render_periodic_png(
        _validated(_payload(readings, alarms=alarms)),
        tmp_path,
        deadline_monotonic=__import__("time").monotonic() + 10,
    )
    assert result.caption == (
        "<b>CryoDAQ | Периодический отчёт</b>\n"
        "Время: 10.07.2026 04:05\n\n"
        "<b>Температуры:</b>\n  Т1: 4 К\n\n"
        "<b>Давление:</b>\n  P: 1e-05 мбар\n\n"
        "<b>Прочие каналы:</b>\n  voltage: 0.01235 V\n\n"
        "<b>Активные тревоги (1):</b>\n  ⚠ T1_LOW"
    )


def test_caption_completeness_truth_is_mandatory(tmp_path: Path) -> None:
    snapshot = _validated(
        _payload([], history_complete=False, alarm_state_complete=False, dropped=4, bad=2)
    )
    result = render_periodic_png(
        snapshot, tmp_path, deadline_monotonic=__import__("time").monotonic() + 10
    )
    for line in (
        "⚠ История данных неполна",
        "⚠ Пропущено точек: 4",
        "⚠ Некорректных точек: 2",
        "⚠ Состояние тревог недоступно",
    ):
        assert line in result.caption
    assert "Тревог нет ✓" not in result.caption
    assert "deadline:" not in result.caption


def test_caption_aggregate_64_channel_128_alarm_overflow(tmp_path: Path) -> None:
    readings = [
        _row(7_000 + index, "ls", f"rack/{index:02d}-{'<&' * 40}", float(index), "K")
        for index in range(64)
    ]
    alarms = [
        {
            "id": f"alarm-{index:03d}-{'<&' * 40}",
            "level": "WARNING",
            "channels": [],
            "triggered_at": 6_000.0 + index,
            "acknowledged": False,
        }
        for index in range(128)
    ]
    result = render_periodic_png(
        _validated(
            _payload(
                readings,
                alarms=alarms,
                history_complete=False,
                alarm_state_complete=False,
                dropped=123,
                bad=45,
            )
        ),
        tmp_path,
        deadline_monotonic=__import__("time").monotonic() + 10,
    )
    assert len(result.caption) <= MAX_CAPTION_CODEPOINTS
    assert len(result.caption.encode("utf-8")) <= MAX_CAPTION_BYTES
    assert "<b>Активные тревоги (128):</b>" in result.caption
    assert "… (+" in result.caption
    assert "каналов)" in result.caption
    assert "⚠ Состояние тревог недоступно" in result.caption
    validate_caption_html(result.caption)


def test_caption_single_dynamic_token_shortening_escapes_before_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.reporting.periodic_renderer as module

    hostile = ("safe<&>😀e\u0301<b>&amp;" * 12)[:180]
    snapshot = _validated(_payload([_row(7_000, "ls", f"rack/{hostile}", 4.0, "K")]))
    monkeypatch.setattr(module, "MAX_CAPTION_CODEPOINTS", 190)
    series = module._series(snapshot)

    caption = module._build_caption(snapshot, series)

    assert len(caption) <= 190
    assert "каналов)" not in caption
    assert "…: 4 К" in caption
    escaped_prefix = caption.split("\n  ", 1)[1].split("…: 4 К", 1)[0]
    assert escaped_prefix == module._escape(hostile[: len(html.unescape(escaped_prefix))])
    validate_caption_html(caption)


def test_caption_alarm_id_shortening_preserves_alarm_count_truth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.reporting.periodic_renderer as module

    hostile = ("alarm<&>😀e\u0301<b>&amp;" * 10)[:170]
    snapshot = _validated(
        _payload(
            [],
            alarms=[
                {
                    "id": hostile,
                    "level": "CRITICAL",
                    "channels": [],
                    "triggered_at": 6_900.0,
                    "acknowledged": False,
                }
            ],
        )
    )
    monkeypatch.setattr(module, "MAX_CAPTION_CODEPOINTS", 190)

    caption = module._build_caption(snapshot, module._series(snapshot))

    assert "<b>Активные тревоги (1):</b>" in caption
    assert "  ⚠ alarm" in caption
    assert "…" in caption
    assert "(+" not in caption
    validate_caption_html(caption)


def test_caption_budget_boundaries_are_inclusive() -> None:
    assert validate_caption_html("x" * 1_024) == "x" * 1_024
    assert validate_caption_html("😀" * 1_024) == "😀" * 1_024
    with pytest.raises(PeriodicInputError, match="bounds"):
        validate_caption_html("x" * 1_025)
    with pytest.raises(PeriodicInputError, match="bounds"):
        validate_caption_html("😀" * 1_025)


def test_png_dimensions_reads_only_bounded_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.reporting.periodic_renderer as module

    png = tmp_path / "header.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + b"\x00\x00\x02\x80\x00\x00\x01\xe0"
        + b"x" * 1_000_000
    )
    monkeypatch.setattr(Path, "read_bytes", lambda _self: pytest.fail("unbounded read"))

    assert module._png_dimensions(png) == (640, 480)


def test_empty_other_only_and_all_invalid_pressure_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _validated(
        _payload(
            [
                _row(7_000, "smu", "V", 1.0, "V"),
                _row(7_001, "vac", "P", 0.0, "mbar"),
                _row(7_002, "vac", "P", None, "mbar"),
            ]
        )
    )
    with _capture_render(monkeypatch, snapshot, tmp_path) as (result, capture):
        assert len(capture["figure"].axes) == 2
        assert [text.get_text() for text in capture["figure"].axes[0].texts] == ["Нет данных"]
        assert [text.get_text() for text in capture["figure"].axes[1].texts] == ["Нет данных"]
        assert "<b>Прочие каналы:</b>\n  V: 1 V" in result.caption


def test_newest_unit_null_row_omits_older_unit_from_chart_and_caption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _validated(
        _payload(
            [
                _row(7_000, "ls", "mixed", 4.0, "K"),
                _row(7_001, "ls", "mixed", None, "V"),
                _row(7_002, "ls", "stable", 5.0, "K"),
            ]
        )
    )
    with _capture_render(monkeypatch, snapshot, tmp_path) as (result, capture):
        assert [line.get_label() for line in capture["figure"].axes[0].lines] == [
            "stable"
        ]
        assert "mixed" not in result.caption
        assert "stable: 5 К" in result.caption


def test_post_freeze_source_mutation_cannot_split_chart_and_caption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _payload([_row(7_000, "ls", "frozen", 4.0, "K")])
    snapshot = _validated(payload)
    payload["readings"][0]["v"] = 999.0
    payload["readings"][0]["u"] = "V"
    with pytest.raises(FrozenInstanceError):
        snapshot.readings[0].value = 999.0  # type: ignore[misc]

    with _capture_render(monkeypatch, snapshot, tmp_path) as (result, capture):
        line = capture["figure"].axes[0].lines[0]
        assert list(line.get_ydata()) == [4.0]
        assert "frozen: 4 К" in result.caption


def test_figure_cleanup_on_success(tmp_path: Path) -> None:
    import cryodaq.reporting.periodic_renderer as module

    snapshot = _validated(_payload([_row(7_000, "ls", "T", 4.0, "K")]))
    before = module.plt.get_fignums()
    render_periodic_png(
        snapshot, tmp_path, deadline_monotonic=module.time.monotonic() + 10
    )
    assert module.plt.get_fignums() == before


def test_figure_cleanup_on_success_and_save_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from matplotlib.figure import Figure

    import cryodaq.reporting.periodic_renderer as module

    snapshot = _validated(_payload([_row(7_000, "ls", "T", 4.0, "K")]))
    before = module.plt.get_fignums()
    output = tmp_path / "fail"
    output.mkdir()

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected save failure")

    monkeypatch.setattr(Figure, "savefig", fail_save)
    with pytest.raises(RuntimeError, match="injected"):
        render_periodic_png(snapshot, output, deadline_monotonic=module.time.monotonic() + 10)
    assert module.plt.get_fignums() == before


def test_renderer_uses_auto_date_locator_and_monotonic_deadline_checkpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.reporting.periodic_renderer as module

    snapshot = _validated(_payload([_row(7_000, "ls", "T", 4.0, "K")]))
    checks: list[float] = []
    real_check = module._check_deadline

    def tracked(deadline: float) -> None:
        checks.append(deadline)
        real_check(deadline)

    monkeypatch.setattr(module, "_check_deadline", tracked)
    with _capture_render(monkeypatch, snapshot, tmp_path) as (_result, capture):
        locator = capture["figure"].axes[0].xaxis.get_major_locator()
        assert isinstance(locator, module.mdates.AutoDateLocator)

    assert len(checks) >= 5
    assert len(set(checks)) == 1
