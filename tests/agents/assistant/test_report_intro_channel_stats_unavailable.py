"""_format_channel_stats must not put "nan" into the Гемма prompt.

The per-channel min/max/mean ran over raw reading values. A single
unavailable sample produced ``- ls218s/CH1: мин 4.2 K / макс 4.2 K / ср nan K``
in the campaign-report prompt — from which the model writes a confident
annotation about a value that was never measured.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryodaq.agents.assistant.shared.report_intro import _format_channel_stats

NAN = float("nan")


@dataclass(frozen=True)
class _Reading:
    channel: str
    value: float
    unit: str


class _Dataset:
    def __init__(self, readings: list[_Reading]) -> None:
        self.readings = readings


def test_non_finite_sample_does_not_poison_channel_stats() -> None:
    out = _format_channel_stats(
        _Dataset(
            [
                _Reading("ls218s/CH1", 4.2, "K"),
                _Reading("ls218s/CH1", NAN, "K"),
                _Reading("ls218s/CH1", 4.4, "K"),
            ]
        )
    )

    assert "nan" not in out.lower(), f"prompt context contains a non-finite aggregate:\n{out}"
    assert out == "- ls218s/CH1: мин 4.2 K / макс 4.4 K / ср 4.3 K"


def test_channel_with_only_unavailable_samples_is_marked() -> None:
    out = _format_channel_stats(_Dataset([_Reading("ls218s/CH9", NAN, "K")]))

    assert "nan" not in out.lower(), f"prompt context contains a non-finite aggregate:\n{out}"
    # The channel is still listed — its absence would be indistinguishable from
    # a channel that was never configured.
    assert out == "- ls218s/CH9: нет данных"


def test_all_finite_readings_unchanged() -> None:
    out = _format_channel_stats(_Dataset([_Reading("ls218s/CH1", 4.0, "K"), _Reading("ls218s/CH1", 6.0, "K")]))

    assert out == "- ls218s/CH1: мин 4 K / макс 6 K / ср 5 K"


def test_no_readings_still_reports_no_data() -> None:
    assert _format_channel_stats(_Dataset([])) == "нет данных"
