"""Кросс-экспериментная аналитика по архиву Parquet (roadmap D3).

Сканирует уже завершённые (архивные) эксперименты — ``<data_dir>/experiments/
<experiment_id>/{metadata.json, readings.parquet}`` — и извлекает по каждому
запуску компактный набор признаков, чтобы отслеживать дрейф во времени:

    (a) "отпечаток" цикла охлаждения — время до 77 K (LN2) и от 77 K до 4.2 K
        (LHe), максимальная скорость охлаждения по каждому из двух каналов
        ступеней GM-охладителя;
    (b) прокси здоровья тепловой развязки (TIM) — ΔT между Т11/Т12 на
        терминальном (квази-стационарном) участке каждого запуска;
    (c) прокси здоровья компрессора — начальная скорость охлаждения
        (dT/dt за первые ``initial_window_h``), трендуемая по месяцам:
        замедление со временем — сигнал деградации компрессора/утечки тепла.

Источник данных — ТОЛЬКО Parquet-архив + ``metadata.json``, читаемые через
существующий ``storage.parquet_archive.read_experiment_parquet()`` (модуль
не пишет и не импортирует внутренности ``storage`` сверх этой функции).
Отдельное хранилище ``analytics/cooldown_fingerprint.py`` (``data/
cooldown_history/*.json``) сюда осознанно не подключается: это артефакт
онлайн-сервиса охлаждения с собственным жизненным циклом, не гарантированно
соответствующий 1:1 архивным экспериментам, которые сканирует этот модуль.

Что НЕ выводится (честность вместо псевдонауки)
------------------------------------------------
* "Сопоставимая тепловая нагрузка" в буквальном смысле роадмапа недостижима:
  схема Parquet — это ``(timestamp, instrument_id, channel, value, unit,
  status, experiment_id)``, без универсально размеченного канала
  тепловыделения/нагревателя. Прокси (b) поэтому сравнивает терминальный
  квази-стационарный участок КАЖДОГО запуска (когда система вышла на свою
  базовую точку) — это относительно честное приближение "сопоставимых
  условий" (fond отсутствия активной нагрузки), но не строго контролируемая
  нагрузка.
* t(300K→77K) считается от начала ЗАПИСАННОГО ряда, а не от физических 300 K:
  если архив начинается не с комнатной температуры (частичный/ретроактивный
  запуск), эта метрика — недооценка полного времени охлаждения. Значение
  ``duration_h`` в ``ExperimentSummary`` показывает фактическую длину ряда.
* Скорость охлаждения (max/initial) считается по данным, ресемплированным на
  грубую равномерную сетку (``resample_bin_min`` мин.) — точечная разница
  между соседними сырыми отсчётами доминируется шумом датчика, поэтому
  "мгновенный" dT/dt здесь не публикуется.
* Здоровье компрессора — это прокси через скорость охлаждения, а не прямое
  измерение (давление гелия, наработка часов и т.п. в архиве не пишутся).
"""

from __future__ import annotations

import csv
import json
import logging
import math
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from cryodaq.analytics.cooldown_predictor import RATE_WINDOW_H
from cryodaq.storage.parquet_archive import read_experiment_parquet

logger = logging.getLogger(__name__)

# Landmark temperatures roadmap item D3 names explicitly: LN2 and LHe boiling
# points. Not hardcoded into the feature functions below — callers may pass
# other thresholds; these are just the module's sensible defaults.
T_LN2_K = 77.0
T_LHE_K = 4.2

# GM-cooler stage channels — hardware-pinned per config/physical_alarms.yaml
# `landmarks:` block (Cyrillic Т, matches the actual channel names on the
# broker). Overridable — this module hardcodes no config, only defaults.
DEFAULT_COLD_CHANNEL = "Т12"  # 2-я ступень, холодная точка (~2.9K)
DEFAULT_WARM_CHANNEL = "Т11"  # 1-я ступень (~40K)

_EXPERIMENTS_SUBDIR = "experiments"
_PARQUET_NAME = "readings.parquet"
_METADATA_GLOB = "*/metadata.json"


# ============================================================================
# Data structures
# ============================================================================


@dataclass
class ExperimentSummary:
    """Один архивный эксперимент: сводка признаков D3 для трендов."""

    experiment_id: str
    start_time: datetime
    status: str
    n_points_cold: int = 0
    n_points_warm: int = 0
    duration_h: float | None = None
    # (a) cooldown fingerprint
    t_to_77K_h: float | None = None
    t_77K_to_4K_h: float | None = None
    max_cooling_rate_cold_k_per_h: float | None = None
    max_cooling_rate_warm_k_per_h: float | None = None
    # (c) compressor-health proxy
    initial_cooldown_rate_k_per_h: float | None = None
    # (b) TIM / thermal-path health proxy
    steady_state_t_cold_k: float | None = None
    steady_state_t_warm_k: float | None = None
    steady_state_dT_k: float | None = None
    steady_state_pair_count: int = 0
    steady_state_max_skew_s: float | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start_time"] = self.start_time.isoformat()
        return payload


@dataclass
class ScanResult:
    summaries: list[ExperimentSummary]
    # (experiment_id, reason) — experiments found but not summarized.
    skipped: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class TrendPoint:
    experiment_id: str
    start_time: datetime
    value: float


@dataclass
class TrendResult:
    metric: str
    threshold: float
    points: list[TrendPoint]
    baseline_mean: float | None
    recent_mean: float | None
    drift: float | None  # recent_mean - baseline_mean
    drift_detected: bool
    slope_per_month: float | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "threshold": self.threshold,
            "points": [
                {
                    "experiment_id": p.experiment_id,
                    "start_time": p.start_time.isoformat(),
                    "value": p.value,
                }
                for p in self.points
            ],
            "baseline_mean": self.baseline_mean,
            "recent_mean": self.recent_mean,
            "drift": self.drift,
            "drift_detected": self.drift_detected,
            "slope_per_month": self.slope_per_month,
        }


# ============================================================================
# Archive scanner
# ============================================================================


def scan_archive(
    data_dir: Path,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    cold_channel: str = DEFAULT_COLD_CHANNEL,
    warm_channel: str = DEFAULT_WARM_CHANNEL,
    initial_window_h: float = RATE_WINDOW_H,
    steady_window_h: float = 1.0,
    resample_bin_min: float = 5.0,
    max_cross_channel_skew_s: float = 5.0,
) -> ScanResult:
    """Пройти ``<data_dir>/experiments/*/`` и извлечь сводку по каждому запуску.

    Аргументы:
        data_dir: корень данных (тот же, что у ``ExperimentArchive``).
        start/end: включающий диапазон по ``start_time`` эксперимента; None —
            без ограничения с этой стороны.
        cold_channel/warm_channel: имена каналов холодной/тёплой ступени.
        initial_window_h: окно для начальной скорости охлаждения (прокси
            компрессора) — по умолчанию совпадает с окном
            ``cooldown_predictor.RATE_WINDOW_H``, чтобы использовать тот же
            физический смысл "начальной скорости".
        steady_window_h: длина терминального окна для ΔT (прокси TIM).
        resample_bin_min: шаг ресемплинга для оценки max|dT/dt|.

    Возвращает ``ScanResult`` с summaries (может быть меньше, чем архивных
    директорий — RUNNING-эксперименты и те, где нет readings.parquet или
    целевых каналов, попадают в ``skipped`` с причиной).
    """
    data_dir = Path(data_dir)
    _require_positive_finite("initial_window_h", initial_window_h)
    _require_positive_finite("steady_window_h", steady_window_h)
    _require_positive_finite("resample_bin_min", resample_bin_min)
    _require_positive_finite("max_cross_channel_skew_s", max_cross_channel_skew_s)
    start = _normalize_bound(start)
    end = _normalize_bound(end)
    if start is not None and end is not None and end < start:
        raise ValueError("end must not precede start")
    experiments_dir = data_dir / _EXPERIMENTS_SUBDIR
    summaries: list[ExperimentSummary] = []
    skipped: list[tuple[str, str]] = []

    if not experiments_dir.exists():
        return ScanResult(summaries=summaries, skipped=skipped)

    for metadata_path in sorted(experiments_dir.glob(_METADATA_GLOB)):
        exp_dir = metadata_path.parent
        exp_id = exp_dir.name

        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            skipped.append((exp_id, f"metadata read failed: {exc}"))
            continue

        experiment = payload.get("experiment", {}) or {}
        metadata_experiment_id = str(experiment.get("experiment_id", ""))
        if metadata_experiment_id != exp_id:
            skipped.append((exp_id, "metadata experiment_id does not match archive directory"))
            continue
        status = str(experiment.get("status", ""))
        if status == "RUNNING":
            continue
        if status not in {"COMPLETED", "ABORTED"}:
            skipped.append((exp_id, f"unknown terminal status: {status or '<missing>'}"))
            continue

        start_time = _parse_iso(experiment.get("start_time"))
        if start_time is None:
            skipped.append((exp_id, "no start_time in metadata"))
            continue
        end_time = _parse_iso(experiment.get("end_time"))
        if end_time is None or end_time < start_time:
            skipped.append((exp_id, "invalid terminal end_time in metadata"))
            continue
        if start is not None and start_time < start:
            continue
        if end is not None and start_time > end:
            continue

        parquet_path = exp_dir / _PARQUET_NAME
        if not parquet_path.exists():
            skipped.append((exp_id, "no readings.parquet"))
            continue

        channels = read_experiment_parquet(
            parquet_path,
            channels=[cold_channel, warm_channel],
            expected_experiment_id=exp_id,
        )
        if not channels:
            skipped.append((exp_id, "parquet unreadable or empty (pyarrow missing?)"))
            continue
        if not _timestamps_within_experiment(channels, start_time, end_time):
            skipped.append((exp_id, "parquet timestamps outside experiment bounds"))
            continue

        summary = _build_summary(
            exp_id,
            start_time,
            status,
            channels.get(cold_channel, []),
            channels.get(warm_channel, []),
            initial_window_h=initial_window_h,
            steady_window_h=steady_window_h,
            resample_bin_min=resample_bin_min,
            max_cross_channel_skew_s=max_cross_channel_skew_s,
        )
        summaries.append(summary)

    return ScanResult(summaries=summaries, skipped=skipped)


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _normalize_bound(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_positive_finite(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")


def _timestamps_within_experiment(
    channels: dict[str, list[tuple[float, float]]],
    start_time: datetime,
    end_time: datetime,
) -> bool:
    lower = start_time.timestamp()
    upper = end_time.timestamp()
    return all(
        math.isfinite(float(timestamp)) and lower <= float(timestamp) <= upper
        for rows in channels.values()
        for timestamp, _value in rows
    )


# ============================================================================
# Per-experiment feature extraction
# ============================================================================


def _build_summary(
    experiment_id: str,
    start_time: datetime,
    status: str,
    cold_rows: list[tuple[float, float]],
    warm_rows: list[tuple[float, float]],
    *,
    initial_window_h: float,
    steady_window_h: float,
    resample_bin_min: float,
    max_cross_channel_skew_s: float,
) -> ExperimentSummary:
    cold = _to_hours_series(cold_rows)
    warm = _to_hours_series(warm_rows)

    summary = ExperimentSummary(
        experiment_id=experiment_id,
        start_time=start_time,
        status=status,
        n_points_cold=0 if cold is None else len(cold[0]),
        n_points_warm=0 if warm is None else len(warm[0]),
    )

    if cold is not None:
        t_cold, T_cold = cold
        summary.duration_h = float(t_cold[-1])
        summary.t_to_77K_h = _first_crossing_h(t_cold, T_cold, T_LN2_K)
        t_4k = _first_crossing_h(t_cold, T_cold, T_LHE_K)
        if summary.t_to_77K_h is not None and t_4k is not None and t_4k >= summary.t_to_77K_h:
            summary.t_77K_to_4K_h = t_4k - summary.t_to_77K_h
        summary.max_cooling_rate_cold_k_per_h = _max_abs_rate(t_cold, T_cold, resample_bin_min)
        summary.initial_cooldown_rate_k_per_h = _initial_rate(t_cold, T_cold, initial_window_h)
        summary.steady_state_t_cold_k = _tail_mean(t_cold, T_cold, steady_window_h)

    if warm is not None:
        t_warm, T_warm = warm
        if summary.duration_h is None:
            summary.duration_h = float(t_warm[-1])
        summary.max_cooling_rate_warm_k_per_h = _max_abs_rate(t_warm, T_warm, resample_bin_min)
        summary.steady_state_t_warm_k = _tail_mean(t_warm, T_warm, steady_window_h)

    if cold is not None and warm is not None:
        paired_dT, pair_count, max_skew = _paired_tail_delta(
            cold_rows,
            warm_rows,
            window_h=steady_window_h,
            max_skew_s=max_cross_channel_skew_s,
        )
        summary.steady_state_dT_k = paired_dT
        summary.steady_state_pair_count = pair_count
        summary.steady_state_max_skew_s = max_skew

    return summary


def _to_hours_series(
    rows: list[tuple[float, float]],
) -> tuple[np.ndarray, np.ndarray] | None:
    """Sort by timestamp, drop NaN, rebase to hours-since-first-sample.

    Returns None when there are fewer than 2 usable points (nothing
    meaningful to derive a rate or crossing time from).
    """
    if not rows:
        return None
    ordered = _finite_last_writer_rows(rows)
    ts = np.array([r[0] for r in ordered], dtype=float)
    val = np.array([r[1] for r in ordered], dtype=float)
    if len(ts) < 2:
        return None
    t_hours = (ts - ts[0]) / 3600.0
    return t_hours, val


def _finite_last_writer_rows(rows: list[tuple[float, float]]) -> list[tuple[float, float]]:
    by_timestamp: dict[float, float] = {}
    for raw_timestamp, raw_value in rows:
        try:
            timestamp = float(raw_timestamp)
            value = float(raw_value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(timestamp) and math.isfinite(value):
            by_timestamp[timestamp] = value
    return sorted(by_timestamp.items())


def _paired_tail_delta(
    cold_rows: list[tuple[float, float]],
    warm_rows: list[tuple[float, float]],
    *,
    window_h: float,
    max_skew_s: float,
) -> tuple[float | None, int, float | None]:
    """Pair terminal samples one-to-one without hiding cross-channel skew."""

    cold = _finite_last_writer_rows(cold_rows)
    warm = _finite_last_writer_rows(warm_rows)
    if not cold or not warm:
        return None, 0, None
    common_end = min(cold[-1][0], warm[-1][0])
    common_start = max(cold[0][0], warm[0][0], common_end - window_h * 3600.0)
    cold = [row for row in cold if common_start <= row[0] <= common_end]
    warm = [row for row in warm if common_start <= row[0] <= common_end]
    pairs: list[tuple[float, float, float]] = []
    cold_index = warm_index = 0
    while cold_index < len(cold) and warm_index < len(warm):
        cold_ts, cold_value = cold[cold_index]
        warm_ts, warm_value = warm[warm_index]
        skew = warm_ts - cold_ts
        if abs(skew) <= max_skew_s:
            pairs.append((warm_value - cold_value, abs(skew), cold_ts))
            cold_index += 1
            warm_index += 1
        elif skew < 0:
            warm_index += 1
        else:
            cold_index += 1
    if not pairs:
        return None, 0, None
    max_skew = max(pair[1] for pair in pairs)
    if len(pairs) < 3:
        return None, len(pairs), max_skew
    return float(np.mean([pair[0] for pair in pairs])), len(pairs), max_skew


def _first_crossing_h(t_hours: np.ndarray, T: np.ndarray, threshold: float) -> float | None:
    """First t_hours where T <= threshold, else None (never reached)."""
    idx = np.where(T <= threshold)[0]
    return float(t_hours[idx[0]]) if len(idx) else None


def _max_abs_rate(t_hours: np.ndarray, T: np.ndarray, bin_min: float) -> float | None:
    """Peak |dT/dt| [K/h] over the run.

    Resampled onto a coarse uniform grid (``bin_min`` minutes) before
    differencing — point-to-point diffs on raw sensor data are noise-
    dominated (same reason cooldown_predictor Savitzky-Golay-smooths before
    computing rates); a fixed-bin resample is a simpler, dependency-free
    stand-in that needs only numpy.
    """
    duration_h = float(t_hours[-1])
    bin_h = bin_min / 60.0
    if duration_h < bin_h * 2:
        return None
    grid = np.arange(0.0, duration_h, bin_h)
    if len(grid) < 3:
        return None
    T_grid = np.interp(grid, t_hours, T)
    dT_dt = np.diff(T_grid) / bin_h
    return float(np.max(np.abs(dT_dt)))


def _initial_rate(t_hours: np.ndarray, T: np.ndarray, window_h: float) -> float | None:
    """Average dT/dt [K/h] over the first ``window_h`` (linear fit).

    Same convention as cooldown_predictor's initial-rate feature; recomputed
    locally (not imported) to avoid depending on that module's private
    ``_compute_initial_rate`` helper.
    """
    mask = t_hours <= window_h
    if int(np.sum(mask)) < 5:
        return None
    t_w, T_w = t_hours[mask], T[mask]
    if t_w[-1] - t_w[0] < 0.1:
        return None
    return float(np.polyfit(t_w, T_w, 1)[0])


def _tail_mean(t_hours: np.ndarray, T: np.ndarray, window_h: float) -> float:
    """Mean T over the last ``window_h`` of the run — terminal/quiescent
    proxy for "comparable conditions" (see module docstring honesty note).
    """
    duration_h = float(t_hours[-1])
    mask = t_hours >= duration_h - window_h
    if int(np.sum(mask)) < 3:
        return float(T[-1])
    return float(np.mean(T[mask]))


# ============================================================================
# Trend / drift
# ============================================================================


def compute_trend(
    summaries: list[ExperimentSummary],
    metric: str,
    *,
    threshold: float,
    baseline_n: int = 5,
    recent_n: int = 5,
) -> TrendResult:
    """Хронологический тренд одного числового поля ``ExperimentSummary``.

    Дрейф отмечается, когда ``|recent_mean - baseline_mean| > threshold``:
    сравниваются среднее по первым ``baseline_n`` запускам и среднее по
    последним ``recent_n`` (по времени начала). ``threshold`` — обязательный
    аргумент вызывающей стороны: "нормальный" дрейф зависит от метрики,
    оборудования, площадки — здесь нет и не должно быть жёстко зашитого
    научного порога.

    ``slope_per_month`` — линейная регрессия значения по времени (в месяцах
    от первой точки), информационная величина в дополнение к baseline/recent
    сравнению.
    """
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("threshold must be non-negative and finite")
    if baseline_n < 1 or recent_n < 1:
        raise ValueError("baseline_n and recent_n must be positive")
    ordered = sorted(summaries, key=lambda s: _normalize_bound(s.start_time))
    points: list[TrendPoint] = []
    for s in ordered:
        value = getattr(s, metric, None)
        if value is not None and math.isfinite(float(value)):
            points.append(TrendPoint(s.experiment_id, s.start_time, float(value)))

    if not points:
        return TrendResult(
            metric=metric,
            threshold=threshold,
            points=[],
            baseline_mean=None,
            recent_mean=None,
            drift=None,
            drift_detected=False,
            slope_per_month=None,
        )

    baseline_mean = float(np.mean([p.value for p in points[:baseline_n]]))
    recent_mean = float(np.mean([p.value for p in points[-recent_n:]]))
    drift = recent_mean - baseline_mean
    drift_detected = abs(drift) > threshold

    slope_per_month: float | None = None
    if len(points) >= 2:
        t0 = points[0].start_time
        months = np.array([(p.start_time - t0).total_seconds() / (86400.0 * 30.44) for p in points])
        vals = np.array([p.value for p in points])
        if float(months[-1]) > 0:
            slope_per_month = float(np.polyfit(months, vals, 1)[0])

    return TrendResult(
        metric=metric,
        threshold=threshold,
        points=points,
        baseline_mean=baseline_mean,
        recent_mean=recent_mean,
        drift=drift,
        drift_detected=drift_detected,
        slope_per_month=slope_per_month,
    )


# ============================================================================
# Export / formatting
# ============================================================================

_SUMMARY_FIELDS = [f.name for f in fields(ExperimentSummary)]


def export_summaries_csv(summaries: list[ExperimentSummary], path: Path) -> None:
    """Write one row per experiment. Missing (None) features → empty cell."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_SUMMARY_FIELDS)
        writer.writeheader()
        for s in summaries:
            writer.writerow(s.to_payload())


def export_summaries_json(summaries: list[ExperimentSummary], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([s.to_payload() for s in summaries], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def export_trend_json(trend: TrendResult, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trend.to_payload(), indent=2, ensure_ascii=False), encoding="utf-8")


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f}"


def format_summary_table(summaries: list[ExperimentSummary]) -> str:
    """Плоская текстовая таблица для вывода в консоль."""
    if not summaries:
        return "(нет архивных экспериментов в диапазоне)"

    headers = [
        "experiment_id",
        "start",
        "dur_h",
        "t→77K_h",
        "77→4K_h",
        "rate0_K/h",
        "max|dT/dt|_K/h",
        "dT_steady_K",
    ]
    rows = []
    for s in summaries:
        rows.append(
            [
                s.experiment_id[:16],
                s.start_time.strftime("%Y-%m-%d"),
                _fmt(s.duration_h),
                _fmt(s.t_to_77K_h),
                _fmt(s.t_77K_to_4K_h),
                _fmt(s.initial_cooldown_rate_k_per_h),
                _fmt(s.max_cooling_rate_cold_k_per_h),
                _fmt(s.steady_state_dT_k),
            ]
        )

    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths))]
    lines.append("  ".join("-" * w for w in widths))
    for r in rows:
        lines.append("  ".join(c.ljust(w) for c, w in zip(r, widths)))
    return "\n".join(lines)


def format_trend_report(trend: TrendResult) -> str:
    """Короткая сводка тренда для консоли."""
    lines = [f"Метрика: {trend.metric}  (порог дрейфа: {trend.threshold})"]
    if not trend.points:
        lines.append("  Нет данных по этой метрике в выбранном диапазоне.")
        return "\n".join(lines)
    lines.append(f"  Точек: {len(trend.points)}")
    lines.append(f"  Базовое среднее (первые запуски): {_fmt(trend.baseline_mean)}")
    lines.append(f"  Текущее среднее (последние запуски): {_fmt(trend.recent_mean)}")
    lines.append(f"  Дрейф: {_fmt(trend.drift)}")
    lines.append(f"  Наклон: {_fmt(trend.slope_per_month)} / месяц")
    verdict = "ДРЕЙФ ОБНАРУЖЕН" if trend.drift_detected else "в пределах порога"
    lines.append(f"  Вывод: {verdict}")
    return "\n".join(lines)
