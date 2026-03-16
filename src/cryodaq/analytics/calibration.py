"""Calibration backend: session storage, Chebyshev fits, and artifact IO."""

from __future__ import annotations

import csv
import json
import math
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from numpy.polynomial import chebyshev as cheb


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(raw: datetime | str | None) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw.astimezone(timezone.utc)
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_dict(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    raise ValueError("Expected dictionary payload.")


@dataclass(frozen=True, slots=True)
class CalibrationSample:
    timestamp: datetime
    reference_channel: str
    reference_temperature: float
    sensor_channel: str
    sensor_raw_value: float
    reference_instrument_id: str = ""
    sensor_instrument_id: str = ""
    experiment_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "reference_channel": self.reference_channel,
            "reference_temperature": self.reference_temperature,
            "sensor_channel": self.sensor_channel,
            "sensor_raw_value": self.sensor_raw_value,
            "reference_instrument_id": self.reference_instrument_id,
            "sensor_instrument_id": self.sensor_instrument_id,
            "experiment_id": self.experiment_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CalibrationSample:
        return cls(
            timestamp=_parse_time(payload.get("timestamp")) or _utcnow(),
            reference_channel=str(payload.get("reference_channel", "")),
            reference_temperature=float(payload.get("reference_temperature", 0.0)),
            sensor_channel=str(payload.get("sensor_channel", "")),
            sensor_raw_value=float(payload.get("sensor_raw_value", 0.0)),
            reference_instrument_id=str(payload.get("reference_instrument_id", "")),
            sensor_instrument_id=str(payload.get("sensor_instrument_id", "")),
            experiment_id=(
                str(payload.get("experiment_id"))
                if payload.get("experiment_id") not in (None, "")
                else None
            ),
            metadata=_json_dict(payload.get("metadata")),
        )


@dataclass(frozen=True, slots=True)
class CalibrationSession:
    session_id: str
    sensor_id: str
    reference_channel: str
    sensor_channel: str
    raw_unit: str
    started_at: datetime
    finished_at: datetime | None = None
    reference_instrument_id: str = ""
    sensor_instrument_id: str = ""
    experiment_id: str | None = None
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    samples: tuple[CalibrationSample, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "sensor_id": self.sensor_id,
            "reference_channel": self.reference_channel,
            "sensor_channel": self.sensor_channel,
            "raw_unit": self.raw_unit,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "reference_instrument_id": self.reference_instrument_id,
            "sensor_instrument_id": self.sensor_instrument_id,
            "experiment_id": self.experiment_id,
            "notes": self.notes,
            "metadata": dict(self.metadata),
            "samples": [sample.to_payload() for sample in self.samples],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CalibrationSession:
        return cls(
            session_id=str(payload.get("session_id", "")),
            sensor_id=str(payload.get("sensor_id", "")),
            reference_channel=str(payload.get("reference_channel", "")),
            sensor_channel=str(payload.get("sensor_channel", "")),
            raw_unit=str(payload.get("raw_unit", "sensor_unit")),
            started_at=_parse_time(payload.get("started_at")) or _utcnow(),
            finished_at=_parse_time(payload.get("finished_at")),
            reference_instrument_id=str(payload.get("reference_instrument_id", "")),
            sensor_instrument_id=str(payload.get("sensor_instrument_id", "")),
            experiment_id=(
                str(payload.get("experiment_id"))
                if payload.get("experiment_id") not in (None, "")
                else None
            ),
            notes=str(payload.get("notes", "")),
            metadata=_json_dict(payload.get("metadata")),
            samples=tuple(
                CalibrationSample.from_payload(item) for item in payload.get("samples", [])
            ),
        )


@dataclass(frozen=True, slots=True)
class CalibrationZone:
    raw_min: float
    raw_max: float
    order: int
    coefficients: tuple[float, ...]
    rmse_k: float
    max_abs_error_k: float
    point_count: int

    def contains(self, raw_value: float) -> bool:
        return self.raw_min <= raw_value <= self.raw_max

    def evaluate(self, raw_value: float) -> float:
        if self.raw_max <= self.raw_min:
            raise ValueError("Calibration zone has invalid range.")
        clipped = min(max(raw_value, self.raw_min), self.raw_max)
        scaled = ((2.0 * (clipped - self.raw_min)) / (self.raw_max - self.raw_min)) - 1.0
        return float(cheb.chebval(scaled, self.coefficients))

    def to_payload(self) -> dict[str, Any]:
        return {
            "raw_min": self.raw_min,
            "raw_max": self.raw_max,
            "order": self.order,
            "coefficients": list(self.coefficients),
            "rmse_k": self.rmse_k,
            "max_abs_error_k": self.max_abs_error_k,
            "point_count": self.point_count,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CalibrationZone:
        return cls(
            raw_min=float(payload.get("raw_min", 0.0)),
            raw_max=float(payload.get("raw_max", 0.0)),
            order=int(payload.get("order", 1)),
            coefficients=tuple(float(value) for value in payload.get("coefficients", [])),
            rmse_k=float(payload.get("rmse_k", 0.0)),
            max_abs_error_k=float(payload.get("max_abs_error_k", 0.0)),
            point_count=int(payload.get("point_count", 0)),
        )


@dataclass(frozen=True, slots=True)
class CalibrationCurve:
    curve_id: str
    sensor_id: str
    fit_timestamp: datetime
    raw_unit: str
    sensor_kind: str
    source_session_ids: tuple[str, ...]
    zones: tuple[CalibrationZone, ...]
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def evaluate(self, raw_value: float) -> float:
        if not self.zones:
            raise ValueError("Calibration curve has no fitted zones.")
        for zone in self.zones:
            if zone.contains(raw_value):
                return zone.evaluate(raw_value)
        if raw_value < self.zones[0].raw_min:
            return self.zones[0].evaluate(raw_value)
        return self.zones[-1].evaluate(raw_value)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "curve_id": self.curve_id,
            "sensor_id": self.sensor_id,
            "fit_timestamp": self.fit_timestamp.isoformat(),
            "raw_unit": self.raw_unit,
            "sensor_kind": self.sensor_kind,
            "source_session_ids": list(self.source_session_ids),
            "zones": [zone.to_payload() for zone in self.zones],
            "metrics": dict(self.metrics),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CalibrationCurve:
        return cls(
            curve_id=str(payload.get("curve_id", "")),
            sensor_id=str(payload.get("sensor_id", "")),
            fit_timestamp=_parse_time(payload.get("fit_timestamp")) or _utcnow(),
            raw_unit=str(payload.get("raw_unit", "sensor_unit")),
            sensor_kind=str(payload.get("sensor_kind", "generic")),
            source_session_ids=tuple(str(item) for item in payload.get("source_session_ids", [])),
            zones=tuple(CalibrationZone.from_payload(item) for item in payload.get("zones", [])),
            metrics=_json_dict(payload.get("metrics")),
            metadata=_json_dict(payload.get("metadata")),
        )


class CalibrationSessionStore:
    """Durable session artifacts for calibration sample capture."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._sessions_dir = self._base_dir / "sessions"

    def start_session(
        self,
        *,
        sensor_id: str,
        reference_channel: str,
        sensor_channel: str,
        raw_unit: str = "sensor_unit",
        reference_instrument_id: str = "",
        sensor_instrument_id: str = "",
        experiment_id: str | None = None,
        notes: str = "",
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        started_at: datetime | None = None,
    ) -> CalibrationSession:
        if not sensor_id.strip():
            raise ValueError("sensor_id is required for calibration session.")
        if not reference_channel.strip() or not sensor_channel.strip():
            raise ValueError("reference_channel and sensor_channel are required.")
        session = CalibrationSession(
            session_id=session_id or uuid.uuid4().hex[:12],
            sensor_id=sensor_id.strip(),
            reference_channel=reference_channel.strip(),
            sensor_channel=sensor_channel.strip(),
            raw_unit=raw_unit.strip() or "sensor_unit",
            started_at=started_at or _utcnow(),
            reference_instrument_id=reference_instrument_id.strip(),
            sensor_instrument_id=sensor_instrument_id.strip(),
            experiment_id=experiment_id,
            notes=notes,
            metadata=_json_dict(metadata),
            samples=(),
        )
        self._write_session(session)
        return session

    def append_sample(
        self,
        session_id: str,
        *,
        reference_temperature: float,
        sensor_raw_value: float,
        timestamp: datetime | None = None,
        experiment_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CalibrationSession:
        session = self.get_session(session_id)
        sample = CalibrationSample(
            timestamp=timestamp or _utcnow(),
            reference_channel=session.reference_channel,
            reference_temperature=float(reference_temperature),
            sensor_channel=session.sensor_channel,
            sensor_raw_value=float(sensor_raw_value),
            reference_instrument_id=session.reference_instrument_id,
            sensor_instrument_id=session.sensor_instrument_id,
            experiment_id=experiment_id if experiment_id is not None else session.experiment_id,
            metadata=_json_dict(metadata),
        )
        updated = CalibrationSession(
            session_id=session.session_id,
            sensor_id=session.sensor_id,
            reference_channel=session.reference_channel,
            sensor_channel=session.sensor_channel,
            raw_unit=session.raw_unit,
            started_at=session.started_at,
            finished_at=session.finished_at,
            reference_instrument_id=session.reference_instrument_id,
            sensor_instrument_id=session.sensor_instrument_id,
            experiment_id=sample.experiment_id,
            notes=session.notes,
            metadata=session.metadata,
            samples=(*session.samples, sample),
        )
        self._write_session(updated)
        return updated

    def finalize_session(
        self,
        session_id: str,
        *,
        finished_at: datetime | None = None,
        notes: str | None = None,
    ) -> CalibrationSession:
        session = self.get_session(session_id)
        updated = CalibrationSession(
            session_id=session.session_id,
            sensor_id=session.sensor_id,
            reference_channel=session.reference_channel,
            sensor_channel=session.sensor_channel,
            raw_unit=session.raw_unit,
            started_at=session.started_at,
            finished_at=finished_at or _utcnow(),
            reference_instrument_id=session.reference_instrument_id,
            sensor_instrument_id=session.sensor_instrument_id,
            experiment_id=session.experiment_id,
            notes=session.notes if notes is None else notes,
            metadata=session.metadata,
            samples=session.samples,
        )
        self._write_session(updated)
        return updated

    def get_session(self, session_id: str) -> CalibrationSession:
        path = self._session_metadata_path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Calibration session '{session_id}' not found.")
        return CalibrationSession.from_payload(json.loads(path.read_text(encoding="utf-8")))

    def list_sessions(self, *, sensor_id: str | None = None) -> list[CalibrationSession]:
        sessions: list[CalibrationSession] = []
        for path in sorted(self._sessions_dir.glob("*/session.json")):
            session = CalibrationSession.from_payload(json.loads(path.read_text(encoding="utf-8")))
            if sensor_id and session.sensor_id != sensor_id:
                continue
            sessions.append(session)
        sessions.sort(key=lambda item: item.started_at, reverse=True)
        return sessions

    def export_session_csv(self, session_id: str, path: Path | None = None) -> Path:
        session = self.get_session(session_id)
        target = path or (self._session_dir(session_id) / "samples.csv")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "timestamp",
                    "reference_temperature_K",
                    f"sensor_raw_{session.raw_unit}",
                    "reference_channel",
                    "sensor_channel",
                ]
            )
            for sample in session.samples:
                writer.writerow(
                    [
                        sample.timestamp.isoformat(),
                        sample.reference_temperature,
                        sample.sensor_raw_value,
                        sample.reference_channel,
                        sample.sensor_channel,
                    ]
                )
        return target

    def _session_dir(self, session_id: str) -> Path:
        return self._sessions_dir / session_id

    def _session_metadata_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "session.json"

    def _write_session(self, session: CalibrationSession) -> None:
        session_dir = self._session_dir(session.session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        path = self._session_metadata_path(session.session_id)
        path.write_text(json.dumps(session.to_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.export_session_csv(session.session_id)


class CalibrationStore:
    """Calibration curve storage and multi-zone Chebyshev fitting."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir
        self._curves_dir = base_dir / "curves" if base_dir is not None else None
        self._curves: dict[str, CalibrationCurve] = {}

    def fit_curve(
        self,
        sensor_id: str,
        samples: list[CalibrationSample] | tuple[CalibrationSample, ...],
        *,
        raw_unit: str = "sensor_unit",
        sensor_kind: str = "generic",
        source_session_ids: list[str] | tuple[str, ...] | None = None,
        max_zones: int = 3,
        min_points_per_zone: int = 6,
        max_order: int = 8,
        target_rmse_k: float = 0.05,
        metadata: dict[str, Any] | None = None,
    ) -> CalibrationCurve:
        if not sensor_id.strip():
            raise ValueError("sensor_id is required for calibration fit.")
        ordered = sorted(samples, key=lambda item: item.sensor_raw_value)
        if len(ordered) < max(4, min_points_per_zone):
            raise ValueError("Not enough calibration samples for fitting.")

        raw_values = np.array([sample.sensor_raw_value for sample in ordered], dtype=float)
        temperatures = np.array([sample.reference_temperature for sample in ordered], dtype=float)

        if not np.all(np.isfinite(raw_values)) or not np.all(np.isfinite(temperatures)):
            raise ValueError("Calibration samples must contain finite values only.")
        if np.ptp(raw_values) <= 0:
            raise ValueError("Calibration raw values must span a non-zero range.")

        diffs = np.diff(raw_values)
        if np.any(diffs < 0):
            raise ValueError("Calibration raw values must be monotonic after sorting.")

        zones = self._fit_recursive(
            raw_values,
            temperatures,
            zones_left=max(1, max_zones),
            min_points_per_zone=max(3, min_points_per_zone),
            max_order=max(1, max_order),
            target_rmse_k=max(float(target_rmse_k), 0.0),
        )

        all_predictions = np.array(
            [self._evaluate_zones(zones, raw_value) for raw_value in raw_values],
            dtype=float,
        )
        residuals = all_predictions - temperatures
        curve = CalibrationCurve(
            curve_id=uuid.uuid4().hex[:12],
            sensor_id=sensor_id.strip(),
            fit_timestamp=_utcnow(),
            raw_unit=raw_unit.strip() or "sensor_unit",
            sensor_kind=sensor_kind.strip() or "generic",
            source_session_ids=tuple(str(item) for item in (source_session_ids or ()) if str(item)),
            zones=tuple(zones),
            metrics={
                "sample_count": int(len(ordered)),
                "zone_count": int(len(zones)),
                "rmse_k": float(math.sqrt(np.mean(np.square(residuals)))),
                "max_abs_error_k": float(np.max(np.abs(residuals))),
                "raw_min": float(np.min(raw_values)),
                "raw_max": float(np.max(raw_values)),
                "temperature_min_k": float(np.min(temperatures)),
                "temperature_max_k": float(np.max(temperatures)),
            },
            metadata=_json_dict(metadata),
        )
        self._curves[curve.sensor_id] = curve
        return curve

    def evaluate(self, sensor_id: str, raw_value: float, *, magnetic_field_T: float = 0.0) -> float:
        del magnetic_field_T
        curve = self._require_curve(sensor_id)
        return curve.evaluate(float(raw_value))

    def voltage_to_temp(
        self,
        sensor_id: str,
        voltage: float,
        *,
        magnetic_field_T: float = 0.0,
    ) -> float:
        return self.evaluate(sensor_id, voltage, magnetic_field_T=magnetic_field_T)

    def resistance_to_temp(
        self,
        sensor_id: str,
        resistance: float,
        *,
        magnetic_field_T: float = 0.0,
    ) -> float:
        return self.evaluate(sensor_id, resistance, magnetic_field_T=magnetic_field_T)

    def save_curve(self, curve: CalibrationCurve, path: Path | None = None) -> Path:
        target = path or self._curve_path(curve.sensor_id, curve.curve_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(curve.to_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._curves[curve.sensor_id] = curve
        return target

    def load_curve(self, path: Path) -> CalibrationCurve:
        curve = CalibrationCurve.from_payload(json.loads(path.read_text(encoding="utf-8")))
        self._curves[curve.sensor_id] = curve
        return curve

    def load_curves(self, curves_dir: Path) -> None:
        for path in sorted(curves_dir.glob("**/*.json")):
            self.load_curve(path)

    def import_curve_json(self, path: Path) -> CalibrationCurve:
        return self.load_curve(path)

    def export_curve_json(self, sensor_id: str, path: Path | None = None) -> Path:
        curve = self._require_curve(sensor_id)
        return self.save_curve(curve, path)

    def export_curve_table(
        self,
        sensor_id: str,
        *,
        path: Path | None = None,
        points: int = 200,
    ) -> Path:
        curve = self._require_curve(sensor_id)
        target = path or self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        raw_min = curve.zones[0].raw_min
        raw_max = curve.zones[-1].raw_max
        raw_grid = np.linspace(raw_min, raw_max, max(points, 2))
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([f"raw_{curve.raw_unit}", "temperature_K"])
            for raw_value in raw_grid:
                writer.writerow([float(raw_value), curve.evaluate(float(raw_value))])
        return target

    def get_curve_info(self, sensor_id: str) -> dict[str, Any]:
        curve = self._require_curve(sensor_id)
        return {
            "sensor_id": curve.sensor_id,
            "curve_id": curve.curve_id,
            "fit_timestamp": curve.fit_timestamp.isoformat(),
            "raw_unit": curve.raw_unit,
            "sensor_kind": curve.sensor_kind,
            "source_session_ids": list(curve.source_session_ids),
            "zones": [zone.to_payload() for zone in curve.zones],
            "metrics": dict(curve.metrics),
            "metadata": dict(curve.metadata),
        }

    def _require_curve(self, sensor_id: str) -> CalibrationCurve:
        if sensor_id not in self._curves:
            raise KeyError(f"Calibration curve for sensor '{sensor_id}' is not loaded.")
        return self._curves[sensor_id]

    def _curve_directory(self, sensor_id: str, curve_id: str) -> Path:
        if self._curves_dir is None:
            raise RuntimeError("CalibrationStore base_dir is required for artifact export.")
        return self._curves_dir / sensor_id / curve_id

    def _curve_path(self, sensor_id: str, curve_id: str) -> Path:
        return self._curve_directory(sensor_id, curve_id) / "curve.json"

    def _fit_recursive(
        self,
        raw_values: np.ndarray,
        temperatures: np.ndarray,
        *,
        zones_left: int,
        min_points_per_zone: int,
        max_order: int,
        target_rmse_k: float,
    ) -> list[CalibrationZone]:
        zone, residuals = self._fit_zone(raw_values, temperatures, max_order=max_order)
        if (
            zones_left <= 1
            or len(raw_values) < (min_points_per_zone * 2)
            or zone.rmse_k <= target_rmse_k
        ):
            return [zone]

        split_idx = self._best_split_index(
            raw_values,
            temperatures,
            min_points_per_zone=min_points_per_zone,
            max_order=max_order,
        )
        if split_idx is None:
            return [zone]

        left_raw = raw_values[:split_idx]
        left_temp = temperatures[:split_idx]
        right_raw = raw_values[split_idx:]
        right_temp = temperatures[split_idx:]

        left_zone, _ = self._fit_zone(left_raw, left_temp, max_order=max_order)
        right_zone, _ = self._fit_zone(right_raw, right_temp, max_order=max_order)
        weighted_rmse = math.sqrt(
            (
                (left_zone.rmse_k ** 2) * len(left_raw)
                + (right_zone.rmse_k ** 2) * len(right_raw)
            )
            / len(raw_values)
        )
        if weighted_rmse >= zone.rmse_k * 0.95:
            return [zone]

        worse_left = left_zone.rmse_k >= right_zone.rmse_k
        left_budget = max(1, zones_left - 1) if worse_left else 1
        right_budget = max(1, zones_left - 1) if not worse_left else 1
        left_zones = self._fit_recursive(
            left_raw,
            left_temp,
            zones_left=left_budget,
            min_points_per_zone=min_points_per_zone,
            max_order=max_order,
            target_rmse_k=target_rmse_k,
        )
        right_zones = self._fit_recursive(
            right_raw,
            right_temp,
            zones_left=right_budget,
            min_points_per_zone=min_points_per_zone,
            max_order=max_order,
            target_rmse_k=target_rmse_k,
        )
        combined = [*left_zones, *right_zones]
        combined.sort(key=lambda item: item.raw_min)
        return combined[:zones_left]

    def _fit_zone(
        self,
        raw_values: np.ndarray,
        temperatures: np.ndarray,
        *,
        max_order: int,
    ) -> tuple[CalibrationZone, np.ndarray]:
        best_zone: CalibrationZone | None = None
        best_residuals: np.ndarray | None = None
        max_candidate_order = min(max_order, max(1, len(raw_values) - 1))
        for order in range(1, max_candidate_order + 1):
            domain = [float(raw_values[0]), float(raw_values[-1])]
            with warnings.catch_warnings():
                warnings.simplefilter("error", np.exceptions.RankWarning)
                try:
                    fit = cheb.Chebyshev.fit(raw_values, temperatures, deg=order, domain=domain)
                except np.exceptions.RankWarning:
                    continue
            predictions = fit(raw_values)
            residuals = predictions - temperatures
            rmse = float(math.sqrt(np.mean(np.square(residuals))))
            max_abs_error = float(np.max(np.abs(residuals)))
            zone = CalibrationZone(
                raw_min=float(raw_values[0]),
                raw_max=float(raw_values[-1]),
                order=order,
                coefficients=tuple(float(value) for value in fit.coef),
                rmse_k=rmse,
                max_abs_error_k=max_abs_error,
                point_count=int(len(raw_values)),
            )
            if best_zone is None or (rmse, order) < (best_zone.rmse_k, best_zone.order):
                best_zone = zone
                best_residuals = np.asarray(residuals, dtype=float)
        if best_zone is None or best_residuals is None:
            raise RuntimeError("Failed to fit calibration zone.")
        return best_zone, best_residuals

    def _best_split_index(
        self,
        raw_values: np.ndarray,
        temperatures: np.ndarray,
        *,
        min_points_per_zone: int,
        max_order: int,
    ) -> int | None:
        best_score: float | None = None
        best_index: int | None = None
        for idx in range(min_points_per_zone, len(raw_values) - min_points_per_zone + 1):
            left_zone, _ = self._fit_zone(raw_values[:idx], temperatures[:idx], max_order=max_order)
            right_zone, _ = self._fit_zone(raw_values[idx:], temperatures[idx:], max_order=max_order)
            score = max(left_zone.rmse_k, right_zone.rmse_k) + 0.001 * (
                left_zone.order + right_zone.order
            )
            if best_score is None or score < best_score:
                best_score = score
                best_index = idx
        return best_index

    def _evaluate_zones(self, zones: list[CalibrationZone], raw_value: float) -> float:
        for zone in zones:
            if zone.contains(float(raw_value)):
                return zone.evaluate(float(raw_value))
        if raw_value < zones[0].raw_min:
            return zones[0].evaluate(float(raw_value))
        return zones[-1].evaluate(float(raw_value))
