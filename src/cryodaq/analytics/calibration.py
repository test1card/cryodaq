"""Calibration backend: session storage, Chebyshev fits, and artifact IO."""

from __future__ import annotations

import csv
import json
import math
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from numpy.polynomial import chebyshev as cheb


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_time(raw: datetime | str | None) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=UTC)
        return raw.astimezone(UTC)
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _json_dict(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    raise ValueError("Expected dictionary payload.")


def _safe_path_fragment(value: str) -> str:
    cleaned = "".join("_" if char in '<>:"/\\|?*' else char for char in str(value).strip())
    return cleaned or "unnamed"


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



class CalibrationStore:
    """Calibration curve storage and multi-zone Chebyshev fitting."""

    _TASK_CV_ORDER_RANGE = tuple(range(7, 13))
    _TASK_DOWNSAMPLE_TARGET = 5000

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir
        self._curves_dir = base_dir / "curves" if base_dir is not None else None
        self._exports_dir = base_dir / "exports" if base_dir is not None else None
        self._index_path = base_dir / "index.yaml" if base_dir is not None else None
        self._curves: dict[str, CalibrationCurve] = {}
        self._assignments: dict[str, dict[str, Any]] = {}
        self._runtime_settings: dict[str, Any] = {
            "global_mode": "off",
            "updated_at": "",
        }
        if self._index_path is not None:
            self._load_index()

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
        max_order: int = 12,
        target_rmse_k: float = 0.05,
        metadata: dict[str, Any] | None = None,
    ) -> CalibrationCurve:
        if not sensor_id.strip():
            raise ValueError("sensor_id is required for calibration fit.")
        if len(samples) < max(4, min_points_per_zone):
            raise ValueError("Not enough calibration samples for fitting.")
        normalized_samples = self._preprocess_samples(
            samples,
            downsample_target=self._TASK_DOWNSAMPLE_TARGET,
        )
        if len(normalized_samples) < max(4, min_points_per_zone):
            raise ValueError("Not enough calibration samples for fitting after preprocessing.")

        temperatures = np.array([sample.reference_temperature for sample in normalized_samples], dtype=float)
        raw_values = np.array([sample.sensor_raw_value for sample in normalized_samples], dtype=float)

        if not np.all(np.isfinite(raw_values)) or not np.all(np.isfinite(temperatures)):
            raise ValueError("Calibration samples must contain finite values only.")
        if np.ptp(raw_values) <= 0 or np.ptp(temperatures) <= 0:
            raise ValueError("Calibration raw values must span a non-zero range.")
        zone_slices = self._detect_zone_slices(
            temperatures,
            raw_values,
            max_zones=max(1, max_zones),
            min_points_per_zone=max(3, min_points_per_zone),
            max_order=max(1, max_order),
        )
        zones = self._fit_zone_slices(
            temperatures,
            raw_values,
            zone_slices=zone_slices,
            max_order=max(1, max_order),
            target_rmse_k=max(float(target_rmse_k), 0.0),
        )

        all_predictions = np.array(
            [self._evaluate_zones(zones, raw_value) for raw_value in raw_values],
            dtype=float,
        )
        residuals = all_predictions - temperatures
        sensitivity = np.gradient(raw_values, temperatures)
        curve = CalibrationCurve(
            curve_id=uuid.uuid4().hex[:12],
            sensor_id=sensor_id.strip(),
            fit_timestamp=_utcnow(),
            raw_unit=raw_unit.strip() or "sensor_unit",
            sensor_kind=sensor_kind.strip() or "generic",
            source_session_ids=tuple(str(item) for item in (source_session_ids or ()) if str(item)),
            zones=tuple(zones),
            metrics={
                "sample_count": int(len(normalized_samples)),
                "input_sample_count": int(len(samples)),
                "downsampled_sample_count": int(len(normalized_samples)),
                "downsampling_applied": bool(len(normalized_samples) != len(samples)),
                "zone_count": int(len(zones)),
                "rmse_k": float(math.sqrt(np.mean(np.square(residuals)))),
                "max_abs_error_k": float(np.max(np.abs(residuals))),
                "raw_min": float(np.min(raw_values)),
                "raw_max": float(np.max(raw_values)),
                "temperature_min_k": float(np.min(temperatures)),
                "temperature_max_k": float(np.max(temperatures)),
                "zone_detection": "dV/dT",
                "order_selection": "cross_validation",
                "cv_order_candidates": list(self._TASK_CV_ORDER_RANGE),
                "target_rmse_k": float(target_rmse_k),
                "sensitivity_min": float(np.min(sensitivity)),
                "sensitivity_max": float(np.max(sensitivity)),
            },
            metadata={
                **_json_dict(metadata),
                "preprocessing": {
                    "downsample_target": self._TASK_DOWNSAMPLE_TARGET,
                    "input_sample_count": len(samples),
                    "output_sample_count": len(normalized_samples),
                },
            },
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

    def T_from_V(
        self,
        sensor_id: str,
        voltage: float,
        *,
        magnetic_field_T: float = 0.0,
    ) -> float:
        return self.voltage_to_temp(sensor_id, voltage, magnetic_field_T=magnetic_field_T)

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
        from cryodaq.core.atomic_write import atomic_write_text

        atomic_write_text(target, json.dumps(curve.to_payload(), ensure_ascii=False, indent=2))
        self._curves[curve.sensor_id] = curve
        self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
        self._write_index()
        return target

    def load_curve(self, path: Path) -> CalibrationCurve:
        curve = CalibrationCurve.from_payload(json.loads(path.read_text(encoding="utf-8")))
        self._curves[curve.sensor_id] = curve
        self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
        return curve

    def load_curves(self, curves_dir: Path) -> None:
        for path in sorted(curves_dir.glob("**/*.json")):
            self.load_curve(path)
        self._write_index()

    def import_curve_json(self, path: Path) -> CalibrationCurve:
        return self.load_curve(path)

    def import_curve_file(
        self,
        path: Path,
        *,
        sensor_id: str | None = None,
        channel_key: str | None = None,
        raw_unit: str = "sensor_unit",
        sensor_kind: str = "generic",
    ) -> CalibrationCurve:
        suffix = path.suffix.lower()
        if suffix == ".json":
            curve = self.import_curve_json(path)
        elif suffix in {".330", ".340"}:
            curve = self._import_curve_text(
                path,
                sensor_id=sensor_id,
                channel_key=channel_key,
                raw_unit=raw_unit,
                sensor_kind=sensor_kind,
                import_format=suffix.lstrip("."),
            )
        else:
            raise ValueError(f"Unsupported calibration import format: {path.suffix}")
        if channel_key:
            self.assign_curve(
                sensor_id=curve.sensor_id,
                curve_id=curve.curve_id,
                channel_key=channel_key,
                runtime_apply_ready=False,
            )
        self._write_index()
        return curve

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

    def export_curve_330(
        self,
        sensor_id: str,
        *,
        path: Path | None = None,
        points: int = 200,
    ) -> Path:
        curve = self._require_curve(sensor_id)
        target = path or (self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.330")
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = self._export_rows(curve, points=max(points, 2))
        self._write_curve_text_export(target, curve, rows, format_name="330")
        self._write_index()
        return target

    def export_curve_340(
        self,
        sensor_id: str,
        *,
        path: Path | None = None,
        points: int = 200,
    ) -> Path:
        curve = self._require_curve(sensor_id)
        if self._exports_dir is None:
            raise RuntimeError("CalibrationStore base_dir is required for export.")
        target = path or self._curve_340_path(curve.sensor_id, curve.curve_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = self._export_rows(curve, points=max(points, 2))
        self._write_curve_text_export(target, curve, rows, format_name="340")
        self._write_index()
        return target

    def get_curve_info(self, sensor_id: str | None = None, curve_id: str | None = None) -> dict[str, Any]:
        curve = self._resolve_curve(sensor_id=sensor_id, curve_id=curve_id)
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
            "artifacts": self.get_curve_artifacts(curve.sensor_id),
            "assignment": dict(self._assignments.get(curve.sensor_id) or {}),
        }

    def get_curve_artifacts(self, sensor_id: str) -> dict[str, str]:
        curve = self._require_curve(sensor_id)
        return {
            "curve_path": str(self._curve_path(curve.sensor_id, curve.curve_id)),
            "table_path": str(self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"),
            "curve_330_path": str(self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.330"),
            "curve_340_path": str(self._curve_340_path(curve.sensor_id, curve.curve_id) if self._exports_dir else ""),
            "index_path": str(self._index_path) if self._index_path else "",
        }

    def list_curves(self, *, sensor_id: str | None = None) -> list[dict[str, Any]]:
        curves = list(self._curves.values())
        if sensor_id:
            curves = [curve for curve in curves if curve.sensor_id == sensor_id]
        curves.sort(key=lambda item: item.fit_timestamp, reverse=True)
        return [self.get_curve_info(curve_id=curve.curve_id) for curve in curves]

    def list_assignments(self) -> list[dict[str, Any]]:
        assignments = [dict(item) for item in self._assignments.values()]
        assignments.sort(key=lambda item: str(item.get("sensor_id", "")))
        return assignments

    def get_runtime_settings(self) -> dict[str, Any]:
        assignments = []
        for item in self.list_assignments():
            channel_key = str(item.get("channel_key", "")).strip()
            resolution = self.resolve_runtime_policy(channel_key=channel_key) if channel_key else {}
            assignments.append(
                {
                    **item,
                    "resolution": resolution,
                }
            )
        return {
            "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
            "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
            "assignments": assignments,
        }

    def set_runtime_global_mode(self, mode: str) -> dict[str, Any]:
        normalized = str(mode).strip().lower()
        if normalized not in {"off", "on"}:
            raise ValueError("Runtime calibration global_mode must be 'off' or 'on'.")
        self._runtime_settings["global_mode"] = normalized
        self._runtime_settings["updated_at"] = _utcnow().isoformat()
        self._write_index()
        return self.get_runtime_settings()

    def set_runtime_channel_policy(
        self,
        *,
        channel_key: str,
        policy: str,
        sensor_id: str | None = None,
        curve_id: str | None = None,
        runtime_apply_ready: bool | None = None,
    ) -> dict[str, Any]:
        normalized_channel_key = str(channel_key).strip()
        if not normalized_channel_key:
            raise ValueError("channel_key is required.")
        normalized_policy = str(policy).strip().lower()
        if normalized_policy not in {"inherit", "off", "on"}:
            raise ValueError("Channel runtime policy must be 'inherit', 'off', or 'on'.")
        curve = self._resolve_curve(
            sensor_id=str(sensor_id or "").strip() or None,
            curve_id=str(curve_id or "").strip() or None,
        )
        assignment = self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
        assignment["channel_key"] = normalized_channel_key
        assignment["reading_mode_policy"] = normalized_policy
        if runtime_apply_ready is not None:
            assignment["runtime_apply_ready"] = bool(runtime_apply_ready)
        assignment["updated_at"] = _utcnow().isoformat()
        self._write_index()
        return {
            "assignment": dict(assignment),
            "resolution": self.resolve_runtime_policy(channel_key=normalized_channel_key),
        }

    def resolve_runtime_policy(
        self,
        *,
        channel_key: str,
    ) -> dict[str, Any]:
        normalized_channel_key = str(channel_key).strip()
        if not normalized_channel_key:
            raise ValueError("channel_key is required.")
        global_mode = str(self._runtime_settings.get("global_mode", "off") or "off")
        assignment = next(
            (
                dict(item)
                for item in self._assignments.values()
                if str(item.get("channel_key", "")).strip() == normalized_channel_key
            ),
            None,
        )
        if global_mode == "off":
            return {
                "global_mode": global_mode,
                "channel_key": normalized_channel_key,
                "effective_mode": "off",
                "reading_mode": "krdg",
                "raw_source": "KRDG",
                "reason": "global_off",
                "assignment": assignment,
            }
        if assignment is None:
            return {
                "global_mode": global_mode,
                "channel_key": normalized_channel_key,
                "effective_mode": "off",
                "reading_mode": "krdg",
                "raw_source": "KRDG",
                "reason": "missing_assignment",
                "assignment": None,
            }
        policy = str(assignment.get("reading_mode_policy", "inherit") or "inherit").lower()
        if policy == "off":
            return {
                "global_mode": global_mode,
                "channel_key": normalized_channel_key,
                "effective_mode": "off",
                "reading_mode": "krdg",
                "raw_source": "KRDG",
                "reason": "channel_off",
                "assignment": assignment,
            }
        if not bool(assignment.get("runtime_apply_ready", False)):
            return {
                "global_mode": global_mode,
                "channel_key": normalized_channel_key,
                "effective_mode": "off",
                "reading_mode": "krdg",
                "raw_source": "KRDG",
                "reason": "not_runtime_ready",
                "assignment": assignment,
            }
        sensor_id = str(assignment.get("sensor_id", "")).strip()
        if not sensor_id or sensor_id not in self._curves:
            return {
                "global_mode": global_mode,
                "channel_key": normalized_channel_key,
                "effective_mode": "off",
                "reading_mode": "krdg",
                "raw_source": "KRDG",
                "reason": "missing_curve",
                "assignment": assignment,
            }
        curve = self._curves[sensor_id]
        return {
            "global_mode": global_mode,
            "channel_key": normalized_channel_key,
            "effective_mode": "on",
            "reading_mode": "curve",
            "raw_source": "SRDG",
            "reason": "curve_applied",
            "assignment": assignment,
            "curve": self.get_curve_info(curve_id=curve.curve_id),
        }

    def assign_curve(
        self,
        *,
        sensor_id: str,
        curve_id: str | None = None,
        channel_key: str | None = None,
        runtime_apply_ready: bool = False,
        reading_mode_policy: str = "inherit",
    ) -> dict[str, Any]:
        curve = self._resolve_curve(sensor_id=sensor_id, curve_id=curve_id)
        normalized_policy = str(reading_mode_policy).strip().lower() or "inherit"
        if normalized_policy not in {"inherit", "off", "on"}:
            raise ValueError("reading_mode_policy must be 'inherit', 'off', or 'on'.")
        assignment = {
            "sensor_id": curve.sensor_id,
            "curve_id": curve.curve_id,
            "channel_key": str(channel_key).strip() if channel_key is not None else curve.sensor_id,
            "updated_at": _utcnow().isoformat(),
            "runtime_apply_ready": bool(runtime_apply_ready),
            "reading_mode_policy": normalized_policy,
        }
        self._assignments[curve.sensor_id] = assignment
        self._write_index()
        return dict(assignment)

    def lookup_curve(
        self,
        *,
        sensor_id: str | None = None,
        channel_key: str | None = None,
    ) -> dict[str, Any]:
        assignment: dict[str, Any] | None = None
        if sensor_id:
            assignment = dict(self._assignments.get(sensor_id) or {})
        elif channel_key:
            assignment = next(
                (dict(item) for item in self._assignments.values() if str(item.get("channel_key", "")).strip() == channel_key),
                None,
            )
        if assignment is None:
            if sensor_id and sensor_id in self._curves:
                curve = self._curves[sensor_id]
                assignment = dict(self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id))
            else:
                raise KeyError("Calibration curve lookup did not match any sensor or channel.")
        curve = self._resolve_curve(sensor_id=str(assignment.get("sensor_id", "")), curve_id=str(assignment.get("curve_id", "")))
        return {
            "assignment": assignment,
            "curve": self.get_curve_info(curve_id=curve.curve_id),
        }

    def _require_curve(self, sensor_id: str) -> CalibrationCurve:
        if sensor_id not in self._curves:
            raise KeyError(f"Calibration curve for sensor '{sensor_id}' is not loaded.")
        return self._curves[sensor_id]

    def _resolve_curve(self, *, sensor_id: str | None = None, curve_id: str | None = None) -> CalibrationCurve:
        if sensor_id:
            return self._require_curve(sensor_id)
        if curve_id:
            for curve in self._curves.values():
                if curve.curve_id == curve_id:
                    return curve
        raise KeyError("Calibration curve could not be resolved.")

    def _curve_directory(self, sensor_id: str, curve_id: str) -> Path:
        if self._curves_dir is None:
            raise RuntimeError("CalibrationStore base_dir is required for artifact export.")
        return self._curves_dir / _safe_path_fragment(sensor_id) / _safe_path_fragment(curve_id)

    def _curve_path(self, sensor_id: str, curve_id: str) -> Path:
        return self._curve_directory(sensor_id, curve_id) / "curve.json"

    def _curve_340_path(self, sensor_id: str, curve_id: str) -> Path:
        if self._exports_dir is None:
            raise RuntimeError("CalibrationStore base_dir is required for export.")
        return self._exports_dir / _safe_path_fragment(sensor_id) / _safe_path_fragment(curve_id) / "curve.340"

    def _load_index(self) -> None:
        if self._index_path is None or not self._index_path.exists():
            return
        payload = yaml.safe_load(self._index_path.read_text(encoding="utf-8")) or {}
        runtime = payload.get("runtime", {})
        if isinstance(runtime, dict):
            global_mode = str(runtime.get("global_mode", "off") or "off").strip().lower()
            if global_mode in {"off", "on"}:
                self._runtime_settings["global_mode"] = global_mode
            self._runtime_settings["updated_at"] = str(runtime.get("updated_at", "")).strip()
        assignments = payload.get("assignments", [])
        if isinstance(assignments, list):
            for item in assignments:
                if not isinstance(item, dict):
                    continue
                sensor_id = str(item.get("sensor_id", "")).strip()
                if sensor_id:
                    self._assignments[sensor_id] = {
                        "sensor_id": sensor_id,
                        "curve_id": str(item.get("curve_id", "")).strip(),
                        "channel_key": str(item.get("channel_key", sensor_id)).strip() or sensor_id,
                        "updated_at": str(item.get("updated_at", "")).strip(),
                        "runtime_apply_ready": bool(item.get("runtime_apply_ready", False)),
                        "reading_mode_policy": str(item.get("reading_mode_policy", "inherit") or "inherit").strip().lower() or "inherit",
                    }

    def _write_index(self) -> None:
        if self._index_path is None:
            return
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "generated_at": _utcnow().isoformat(),
            "runtime": {
                "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
                "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
            },
            "curves": [
                {
                    "sensor_id": curve.sensor_id,
                    "curve_id": curve.curve_id,
                    "fit_timestamp": curve.fit_timestamp.isoformat(),
                    "raw_unit": curve.raw_unit,
                    "sensor_kind": curve.sensor_kind,
                    "curve_path": str(self._curve_path(curve.sensor_id, curve.curve_id)),
                    "table_path": str(self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"),
                    "curve_330_path": str(self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.330"),
                    "curve_340_path": str(self._curve_340_path(curve.sensor_id, curve.curve_id) if self._exports_dir else ""),
                    "source_session_ids": list(curve.source_session_ids),
                }
                for curve in sorted(self._curves.values(), key=lambda item: item.fit_timestamp, reverse=True)
            ],
            "assignments": [dict(item) for item in self.list_assignments()],
        }
        from cryodaq.core.atomic_write import atomic_write_text

        atomic_write_text(self._index_path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))

    def _ensure_assignment(self, *, sensor_id: str, curve_id: str) -> dict[str, Any]:
        existing = self._assignments.get(sensor_id)
        if existing:
            existing["curve_id"] = curve_id
            existing["updated_at"] = _utcnow().isoformat()
            return existing
        assignment = {
            "sensor_id": sensor_id,
            "curve_id": curve_id,
            "channel_key": sensor_id,
            "updated_at": _utcnow().isoformat(),
            "runtime_apply_ready": False,
            "reading_mode_policy": "inherit",
        }
        self._assignments[sensor_id] = assignment
        return assignment

    def _export_rows(self, curve: CalibrationCurve, *, points: int) -> list[tuple[float, float]]:
        dense_points = max(points * 24, 2000)
        raw_min = curve.zones[0].raw_min
        raw_max = curve.zones[-1].raw_max
        raw_grid = np.linspace(raw_min, raw_max, dense_points, dtype=float)
        temperatures = np.array([curve.evaluate(float(raw_value)) for raw_value in raw_grid], dtype=float)
        order = np.argsort(temperatures)
        sorted_temperatures = temperatures[order]
        sorted_raw = raw_grid[order]
        sorted_temperatures, sorted_raw = self._collapse_duplicate_axis(sorted_temperatures, sorted_raw)
        indices = self._adaptive_breakpoint_indices(sorted_temperatures, sorted_raw, max(points, 2))
        rows = [(float(sorted_temperatures[index]), float(sorted_raw[index])) for index in indices]
        deduped: list[tuple[float, float]] = []
        seen: set[tuple[float, float]] = set()
        for item in rows:
            key = (round(item[0], 9), round(item[1], 9))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[: max(points, 2)]

    def _write_curve_text_export(
        self,
        path: Path,
        curve: CalibrationCurve,
        rows: list[tuple[float, float]],
        *,
        format_name: str,
    ) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(f"# CryoDAQ calibration curve export .{format_name}\n")
            handle.write(f"# sensor_id: {curve.sensor_id}\n")
            handle.write(f"# curve_id: {curve.curve_id}\n")
            handle.write(f"# raw_unit: {curve.raw_unit}\n")
            handle.write("# columns: temperature_K, sensor_raw\n")
            writer = csv.writer(handle)
            for temperature_k, raw_value in rows:
                writer.writerow([f"{temperature_k:.9g}", f"{raw_value:.9g}"])

    def _import_curve_text(
        self,
        path: Path,
        *,
        sensor_id: str | None,
        channel_key: str | None,
        raw_unit: str,
        sensor_kind: str,
        import_format: str,
    ) -> CalibrationCurve:
        rows: list[tuple[float, float]] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            line = line.replace(",", " ")
            parts = [item for item in line.split() if item]
            if len(parts) < 2:
                continue
            try:
                temperature_k = float(parts[0])
                raw_value = float(parts[1])
            except ValueError:
                continue
            rows.append((temperature_k, raw_value))
        if len(rows) < 4:
            raise ValueError(f"Calibration file '{path.name}' does not contain enough numeric pairs.")
        resolved_sensor_id = (sensor_id or (channel_key or path.stem)).strip()
        samples = [
            CalibrationSample(
                timestamp=_utcnow(),
                reference_channel="import",
                reference_temperature=temperature_k,
                sensor_channel=channel_key or resolved_sensor_id,
                sensor_raw_value=raw_value,
                metadata={"import_format": import_format, "source_path": str(path)},
            )
            for temperature_k, raw_value in sorted(rows, key=lambda item: item[1])
        ]
        curve = self.fit_curve(
            resolved_sensor_id,
            samples,
            raw_unit=raw_unit,
            sensor_kind=sensor_kind,
            source_session_ids=(),
            max_zones=3,
            min_points_per_zone=4,
            max_order=12,
            target_rmse_k=0.05,
            metadata={
                "import_format": import_format,
                "import_source_path": str(path),
                "channel_key": channel_key or resolved_sensor_id,
            },
        )
        self.save_curve(curve)
        if import_format == "330":
            self.export_curve_330(curve.sensor_id)
        if import_format == "340":
            self.export_curve_340(curve.sensor_id)
        return curve

    def _preprocess_samples(
        self,
        samples: list[CalibrationSample] | tuple[CalibrationSample, ...],
        *,
        downsample_target: int,
    ) -> tuple[CalibrationSample, ...]:
        rows: list[tuple[float, float, CalibrationSample]] = []
        for sample in samples:
            temperature = float(sample.reference_temperature)
            raw_value = float(sample.sensor_raw_value)
            if not math.isfinite(temperature) or not math.isfinite(raw_value):
                continue
            rows.append((temperature, raw_value, sample))
        if len(rows) < 4:
            raise ValueError("Not enough finite calibration samples for fitting.")
        rows.sort(key=lambda item: (item[0], item[1]))

        aggregated: list[CalibrationSample] = []
        index = 0
        while index < len(rows):
            temperature = rows[index][0]
            bucket = [rows[index]]
            index += 1
            while index < len(rows) and math.isclose(rows[index][0], temperature, rel_tol=0.0, abs_tol=1e-9):
                bucket.append(rows[index])
                index += 1
            template = bucket[-1][2]
            aggregated.append(
                CalibrationSample(
                    timestamp=template.timestamp,
                    reference_channel=template.reference_channel,
                    reference_temperature=float(np.mean([item[0] for item in bucket])),
                    sensor_channel=template.sensor_channel,
                    sensor_raw_value=float(np.mean([item[1] for item in bucket])),
                    reference_instrument_id=template.reference_instrument_id,
                    sensor_instrument_id=template.sensor_instrument_id,
                    experiment_id=template.experiment_id,
                    metadata=dict(template.metadata),
                )
            )
        if len(aggregated) <= downsample_target:
            return tuple(aggregated)
        return tuple(self._downsample_uniform_temperature(aggregated, downsample_target=downsample_target))

    def _downsample_uniform_temperature(
        self,
        samples: list[CalibrationSample] | tuple[CalibrationSample, ...],
        *,
        downsample_target: int,
    ) -> list[CalibrationSample]:
        ordered = sorted(samples, key=lambda item: item.reference_temperature)
        temperatures = np.array([item.reference_temperature for item in ordered], dtype=float)
        if len(ordered) <= downsample_target or np.ptp(temperatures) <= 0:
            return list(ordered)
        edges = np.linspace(float(temperatures[0]), float(temperatures[-1]), downsample_target + 1)
        downsampled: list[CalibrationSample] = []
        start = 0
        for bin_index in range(downsample_target):
            lower = edges[bin_index]
            upper = edges[bin_index + 1]
            bucket: list[CalibrationSample] = []
            while start < len(ordered):
                current = ordered[start]
                value = current.reference_temperature
                if value < lower and bin_index > 0:
                    start += 1
                    continue
                if (value < upper) or (bin_index == downsample_target - 1 and value <= upper):
                    bucket.append(current)
                    start += 1
                    continue
                break
            if not bucket:
                nearest_index = int(np.searchsorted(temperatures, (lower + upper) / 2.0))
                nearest_index = max(0, min(nearest_index, len(ordered) - 1))
                bucket = [ordered[nearest_index]]
            template = bucket[len(bucket) // 2]
            downsampled.append(
                CalibrationSample(
                    timestamp=template.timestamp,
                    reference_channel=template.reference_channel,
                    reference_temperature=float(np.mean([item.reference_temperature for item in bucket])),
                    sensor_channel=template.sensor_channel,
                    sensor_raw_value=float(np.mean([item.sensor_raw_value for item in bucket])),
                    reference_instrument_id=template.reference_instrument_id,
                    sensor_instrument_id=template.sensor_instrument_id,
                    experiment_id=template.experiment_id,
                    metadata=dict(template.metadata),
                )
            )
        downsampled.sort(key=lambda item: item.reference_temperature)
        return downsampled

    def _detect_zone_slices(
        self,
        temperatures: np.ndarray,
        raw_values: np.ndarray,
        *,
        max_zones: int,
        min_points_per_zone: int,
        max_order: int,
    ) -> list[slice]:
        if len(raw_values) < (min_points_per_zone * 2) or max_zones <= 1:
            return [slice(0, len(raw_values))]
        dvdt = np.gradient(raw_values, temperatures)
        dvdt = self._smooth_series(dvdt)
        magnitude = np.log10(np.maximum(np.abs(dvdt), 1e-12))
        change_score = np.abs(np.gradient(magnitude, temperatures))
        curvature = np.abs(np.gradient(dvdt, temperatures))
        combined_score = change_score + (0.25 * curvature / max(float(np.max(curvature)), 1e-12))
        candidate_order = np.argsort(combined_score)[::-1]
        boundaries: list[int] = []
        for index in candidate_order:
            if index < min_points_per_zone or index > len(raw_values) - min_points_per_zone:
                continue
            if any(abs(index - boundary) < min_points_per_zone for boundary in boundaries):
                continue
            refined = self._refine_boundary_index(
                temperatures,
                raw_values,
                candidate_index=int(index),
                min_points_per_zone=min_points_per_zone,
                max_order=max_order,
            )
            if any(abs(refined - boundary) < min_points_per_zone for boundary in boundaries):
                continue
            boundaries.append(refined)
            if len(boundaries) >= max_zones - 1:
                break
        cuts = sorted(boundaries)
        if not cuts:
            return [slice(0, len(raw_values))]
        slices: list[slice] = []
        start = 0
        for stop in cuts:
            if stop - start < min_points_per_zone:
                continue
            slices.append(slice(start, stop))
            start = stop
        if len(raw_values) - start < min_points_per_zone and slices:
            last = slices.pop()
            slices.append(slice(last.start, len(raw_values)))
        else:
            slices.append(slice(start, len(raw_values)))
        return slices

    def _fit_zone_slices(
        self,
        temperatures: np.ndarray,
        raw_values: np.ndarray,
        *,
        zone_slices: list[slice],
        max_order: int,
        target_rmse_k: float,
    ) -> list[CalibrationZone]:
        zones = [
            self._fit_zone_cv(
                raw_values[zone_slice],
                temperatures[zone_slice],
                max_order=max_order,
            )
            for zone_slice in zone_slices
        ]
        zones.sort(key=lambda item: item.raw_min)
        return zones

    def _fit_zone_cv(
        self,
        raw_values: np.ndarray,
        temperatures: np.ndarray,
        *,
        max_order: int,
    ) -> CalibrationZone:
        ordered_indices = np.argsort(raw_values)
        ordered_raw = np.asarray(raw_values[ordered_indices], dtype=float)
        ordered_temperatures = np.asarray(temperatures[ordered_indices], dtype=float)
        ordered_raw, ordered_temperatures = self._collapse_duplicate_axis(ordered_raw, ordered_temperatures)
        if len(ordered_raw) < 2 or np.ptp(ordered_raw) <= 0:
            raise RuntimeError("Failed to fit calibration zone: degenerate input range.")

        task_candidates = [
            order
            for order in self._TASK_CV_ORDER_RANGE
            if order <= max_order and order < len(ordered_raw)
        ]
        if task_candidates:
            candidate_orders = task_candidates
        else:
            fallback_max = min(max_order, max(1, len(ordered_raw) - 1))
            candidate_orders = list(range(1, fallback_max + 1))

        best_cv_rmse: float | None = None
        best_zone: CalibrationZone | None = None
        for order in candidate_orders:
            try:
                cv_rmse = self._cross_validated_rmse(ordered_raw, ordered_temperatures, order=order)
                zone = self._build_zone(ordered_raw, ordered_temperatures, order=order)
            except RuntimeError:
                continue
            score = (cv_rmse, zone.rmse_k, order)
            if best_cv_rmse is None or score < (best_cv_rmse, best_zone.rmse_k, best_zone.order):  # type: ignore[union-attr]
                best_cv_rmse = cv_rmse
                best_zone = zone
        if best_zone is None:
            raise RuntimeError("Failed to fit calibration zone.")
        return best_zone

    def _build_zone(
        self,
        raw_values: np.ndarray,
        temperatures: np.ndarray,
        *,
        order: int,
    ) -> CalibrationZone:
        domain = [float(np.min(raw_values)), float(np.max(raw_values))]
        with warnings.catch_warnings():
            warnings.simplefilter("error", np.exceptions.RankWarning)
            try:
                fit = cheb.Chebyshev.fit(raw_values, temperatures, deg=order, domain=domain)
            except np.exceptions.RankWarning as exc:
                raise RuntimeError("Calibration zone fit is numerically unstable.") from exc
        predictions = fit(raw_values)
        residuals = predictions - temperatures
        return CalibrationZone(
            raw_min=float(np.min(raw_values)),
            raw_max=float(np.max(raw_values)),
            order=order,
            coefficients=tuple(float(value) for value in fit.coef),
            rmse_k=float(math.sqrt(np.mean(np.square(residuals)))),
            max_abs_error_k=float(np.max(np.abs(residuals))),
            point_count=int(len(raw_values)),
        )

    def _cross_validated_rmse(
        self,
        raw_values: np.ndarray,
        temperatures: np.ndarray,
        *,
        order: int,
    ) -> float:
        sample_count = len(raw_values)
        if sample_count <= order + 2:
            zone = self._build_zone(raw_values, temperatures, order=order)
            return zone.rmse_k
        folds = min(5, max(2, sample_count // max(order + 1, 4)))
        indices = np.arange(sample_count)
        fold_indices = [indices[offset::folds] for offset in range(folds) if len(indices[offset::folds]) > 0]
        rmses: list[float] = []
        for fold in fold_indices:
            mask = np.ones(sample_count, dtype=bool)
            mask[fold] = False
            train_raw = raw_values[mask]
            train_temperatures = temperatures[mask]
            if len(train_raw) <= order:
                continue
            zone = self._build_zone(train_raw, train_temperatures, order=order)
            predictions = np.array([zone.evaluate(float(value)) for value in raw_values[fold]], dtype=float)
            residuals = predictions - temperatures[fold]
            rmses.append(float(math.sqrt(np.mean(np.square(residuals)))))
        if not rmses:
            zone = self._build_zone(raw_values, temperatures, order=order)
            return zone.rmse_k
        return float(np.mean(rmses))

    def _evaluate_zones(self, zones: list[CalibrationZone], raw_value: float) -> float:
        for zone in zones:
            if zone.contains(float(raw_value)):
                return zone.evaluate(float(raw_value))
        if raw_value < zones[0].raw_min:
            return zones[0].evaluate(float(raw_value))
        return zones[-1].evaluate(float(raw_value))

    def _smooth_series(self, values: np.ndarray) -> np.ndarray:
        if len(values) < 5:
            return np.asarray(values, dtype=float)
        window = min(len(values) if len(values) % 2 == 1 else len(values) - 1, 11)
        if window < 3:
            return np.asarray(values, dtype=float)
        kernel = np.ones(window, dtype=float) / float(window)
        padded = np.pad(values, (window // 2, window // 2), mode="edge")
        return np.convolve(padded, kernel, mode="valid")

    def _adaptive_breakpoint_indices(
        self,
        temperatures: np.ndarray,
        raw_values: np.ndarray,
        points: int,
    ) -> list[int]:
        if len(temperatures) <= points:
            return list(range(len(temperatures)))
        first = np.gradient(raw_values, temperatures)
        second = np.gradient(first, temperatures)
        weights = 1.0 + np.abs(second)
        cumulative = np.cumsum(weights)
        cumulative /= cumulative[-1]
        targets = np.linspace(0.0, 1.0, points)
        indices = np.searchsorted(cumulative, targets, side="left")
        indices = np.clip(indices, 0, len(temperatures) - 1)
        indices[0] = 0
        indices[-1] = len(temperatures) - 1
        deduped = sorted({int(index) for index in indices})
        while len(deduped) < points:
            for candidate in np.linspace(0, len(temperatures) - 1, points, dtype=int):
                deduped.append(int(candidate))
                deduped = sorted(set(deduped))
                if len(deduped) >= points:
                    break
        return deduped[:points]

    def _refine_boundary_index(
        self,
        temperatures: np.ndarray,
        raw_values: np.ndarray,
        *,
        candidate_index: int,
        min_points_per_zone: int,
        max_order: int,
    ) -> int:
        search_radius = max(3, min_points_per_zone // 2)
        start = max(min_points_per_zone, candidate_index - search_radius)
        stop = min(len(raw_values) - min_points_per_zone, candidate_index + search_radius)
        best_index = candidate_index
        best_score: tuple[float, float] | None = None
        for index in range(start, stop + 1):
            try:
                left_zone = self._fit_zone_cv(raw_values[:index], temperatures[:index], max_order=max_order)
                right_zone = self._fit_zone_cv(raw_values[index:], temperatures[index:], max_order=max_order)
            except RuntimeError:
                continue
            weighted_rmse = math.sqrt(
                (
                    (left_zone.rmse_k ** 2) * left_zone.point_count
                    + (right_zone.rmse_k ** 2) * right_zone.point_count
                )
                / max(left_zone.point_count + right_zone.point_count, 1)
            )
            score = (weighted_rmse, max(left_zone.max_abs_error_k, right_zone.max_abs_error_k))
            if best_score is None or score < best_score:
                best_score = score
                best_index = index
        return best_index

    def _collapse_duplicate_axis(
        self,
        primary: np.ndarray,
        secondary: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        if len(primary) < 2:
            return np.asarray(primary, dtype=float), np.asarray(secondary, dtype=float)
        rows = sorted(zip(primary.tolist(), secondary.tolist(), strict=False), key=lambda item: item[0])
        unique_primary: list[float] = []
        unique_secondary: list[float] = []
        bucket_primary = [rows[0][0]]
        bucket_secondary = [rows[0][1]]
        for current_primary, current_secondary in rows[1:]:
            if math.isclose(current_primary, bucket_primary[-1], rel_tol=0.0, abs_tol=1e-12):
                bucket_primary.append(current_primary)
                bucket_secondary.append(current_secondary)
                continue
            unique_primary.append(float(np.mean(bucket_primary)))
            unique_secondary.append(float(np.mean(bucket_secondary)))
            bucket_primary = [current_primary]
            bucket_secondary = [current_secondary]
        unique_primary.append(float(np.mean(bucket_primary)))
        unique_secondary.append(float(np.mean(bucket_secondary)))
        return np.asarray(unique_primary, dtype=float), np.asarray(unique_secondary, dtype=float)
