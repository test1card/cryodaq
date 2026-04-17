"""Calibration v2 post-run pipeline: extract pairs, downsample, breakpoints, fit."""

from __future__ import annotations

import logging
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from cryodaq.analytics.calibration import CalibrationCurve, CalibrationSample, CalibrationStore

logger = logging.getLogger(__name__)


@dataclass
class CalibrationFitResult:
    sensor_id: str
    reference_channel: str
    raw_pairs_count: int
    downsampled_count: int
    breakpoint_count: int
    curve: CalibrationCurve
    metrics: dict[str, Any]
    raw_pairs: list[tuple[float, float]]
    downsampled: list[tuple[float, float]]
    breakpoints: list[tuple[float, float]]


class CalibrationFitter:
    """Post-run calibration pipeline: extract → downsample → breakpoints → fit."""

    # ------------------------------------------------------------------
    # Extract
    # ------------------------------------------------------------------

    @staticmethod
    def extract_pairs(
        data_dir: Path,
        start_ts: float,
        end_ts: float,
        reference_channel: str,
        target_channel: str,
        *,
        max_time_delta_s: float = 2.0,
    ) -> list[tuple[float, float]]:
        """Extract time-aligned (SRDG, KRDG) pairs from SQLite data files.

        Returns list of ``(sensor_raw_value, reference_temperature_K)`` tuples.
        """
        srdg_channel = f"{target_channel}_raw"

        # Collect readings from all day-partitioned DB files
        krdg_data: list[tuple[float, float]] = []  # (timestamp, value)
        srdg_data: list[tuple[float, float]] = []

        for db_path in sorted(data_dir.glob("data_????-??-??.db")):
            try:
                conn = sqlite3.connect(str(db_path), timeout=5)
                conn.execute("PRAGMA journal_mode=WAL")
                cursor = conn.execute(
                    "SELECT timestamp, value FROM readings "
                    "WHERE channel = ? AND timestamp >= ? AND timestamp <= ? "
                    "ORDER BY timestamp",
                    (reference_channel, start_ts, end_ts),
                )
                krdg_data.extend(cursor.fetchall())

                cursor = conn.execute(
                    "SELECT timestamp, value FROM readings "
                    "WHERE channel = ? AND timestamp >= ? AND timestamp <= ? "
                    "ORDER BY timestamp",
                    (srdg_channel, start_ts, end_ts),
                )
                srdg_data.extend(cursor.fetchall())
                conn.close()
            except Exception:
                logger.warning("Failed to read %s", db_path, exc_info=True)

        if not krdg_data or not srdg_data:
            return []

        # Time-align: for each SRDG point, find nearest KRDG
        krdg_ts = np.array([t for t, _ in krdg_data])
        krdg_vals = np.array([v for _, v in krdg_data])

        pairs: list[tuple[float, float]] = []
        for ts, srdg_val in srdg_data:
            # Filter bad SRDG
            if not math.isfinite(srdg_val) or srdg_val <= 0:
                continue

            # Find nearest KRDG
            idx = int(np.searchsorted(krdg_ts, ts))
            best_idx = idx
            best_delta = float("inf")
            for candidate in (idx - 1, idx, idx + 1):
                if 0 <= candidate < len(krdg_ts):
                    delta = abs(krdg_ts[candidate] - ts)
                    if delta < best_delta:
                        best_delta = delta
                        best_idx = candidate

            if best_delta > max_time_delta_s:
                continue

            krdg_val = float(krdg_vals[best_idx])
            if not math.isfinite(krdg_val) or krdg_val < 1.5 or krdg_val > 1e6:
                continue

            pairs.append((srdg_val, krdg_val))

        return pairs

    # ------------------------------------------------------------------
    # Downsample
    # ------------------------------------------------------------------

    @staticmethod
    def adaptive_downsample(
        raw_pairs: list[tuple[float, float]],
        target_count: int = 500,
        min_per_bin: int = 3,
    ) -> list[tuple[float, float]]:
        """Downsample preserving high-curvature regions."""
        if len(raw_pairs) <= target_count:
            return list(raw_pairs)

        # Sort by SRDG value
        sorted_pairs = sorted(raw_pairs, key=lambda p: p[0])
        n = len(sorted_pairs)

        # Compute curvature (second derivative magnitude)
        srdg = np.array([p[0] for p in sorted_pairs])
        krdg = np.array([p[1] for p in sorted_pairs])

        # Smooth second derivative
        curvature = np.zeros(n)
        for i in range(1, n - 1):
            ds = srdg[i + 1] - srdg[i - 1]
            if ds > 0:
                d2t = abs(krdg[i + 1] - 2 * krdg[i] + krdg[i - 1])
                curvature[i] = d2t / (ds * ds + 1e-12)

        # Divide into bins
        n_bins = max(4, target_count // min_per_bin)
        bin_edges = np.linspace(srdg[0], srdg[-1], n_bins + 1)

        # Compute per-bin curvature weight
        bin_weights = np.ones(n_bins)
        for b in range(n_bins):
            mask = (srdg >= bin_edges[b]) & (srdg < bin_edges[b + 1])
            if b == n_bins - 1:
                mask = (srdg >= bin_edges[b]) & (srdg <= bin_edges[b + 1])
            if mask.any():
                bin_weights[b] = max(1.0, float(np.mean(curvature[mask])))

        # Allocate points proportional to curvature
        total_weight = bin_weights.sum()
        bin_alloc = np.maximum(
            min_per_bin,
            np.round(bin_weights / total_weight * target_count).astype(int),
        )

        # Sample from each bin
        result: list[tuple[float, float]] = []
        for b in range(n_bins):
            mask = (srdg >= bin_edges[b]) & (srdg < bin_edges[b + 1])
            if b == n_bins - 1:
                mask = (srdg >= bin_edges[b]) & (srdg <= bin_edges[b + 1])
            indices = np.where(mask)[0]
            if len(indices) == 0:
                continue
            count = min(int(bin_alloc[b]), len(indices))
            chosen = np.linspace(0, len(indices) - 1, count, dtype=int)
            for idx in chosen:
                result.append(sorted_pairs[int(indices[idx])])

        # Ensure boundary points included
        result.append(sorted_pairs[0])
        result.append(sorted_pairs[-1])

        # Deduplicate and sort
        result = sorted(set(result), key=lambda p: p[0])
        return result

    # ------------------------------------------------------------------
    # Breakpoints (Douglas-Peucker)
    # ------------------------------------------------------------------

    @staticmethod
    def generate_breakpoints(
        pairs: list[tuple[float, float]],
        max_breakpoints: int = 200,
        tolerance_mk: float = 50.0,
    ) -> list[tuple[float, float]]:
        """Douglas-Peucker breakpoint selection for .330 export."""
        if len(pairs) <= 2:
            return list(pairs)

        sorted_pairs = sorted(pairs, key=lambda p: p[0])
        tolerance_k = tolerance_mk / 1000.0

        # Iterative Douglas-Peucker
        n = len(sorted_pairs)
        include = [False] * n
        include[0] = True
        include[n - 1] = True

        # Stack-based DP
        stack: list[tuple[int, int]] = [(0, n - 1)]
        while stack:
            if sum(include) >= max_breakpoints:
                break
            start, end = stack.pop()
            if end - start <= 1:
                continue

            # Find point with max perpendicular distance
            s_start = sorted_pairs[start][0]
            t_start = sorted_pairs[start][1]
            s_end = sorted_pairs[end][0]
            t_end = sorted_pairs[end][1]

            max_dist = 0.0
            max_idx = start
            ds = s_end - s_start
            dt = t_end - t_start
            seg_len = math.sqrt(ds * ds + dt * dt) or 1e-12

            for i in range(start + 1, end):
                # Perpendicular distance from point to line segment
                s_i = sorted_pairs[i][0]
                t_i = sorted_pairs[i][1]
                dist = abs(dt * (s_start - s_i) - ds * (t_start - t_i)) / seg_len
                if dist > max_dist:
                    max_dist = dist
                    max_idx = i

            if max_dist > tolerance_k:
                include[max_idx] = True
                stack.append((start, max_idx))
                stack.append((max_idx, end))

        return [sorted_pairs[i] for i in range(n) if include[i]]

    # ------------------------------------------------------------------
    # Coverage
    # ------------------------------------------------------------------

    @staticmethod
    def compute_coverage(
        raw_pairs: list[tuple[float, float]],
        n_bins: int = 20,
    ) -> list[dict[str, Any]]:
        """Coverage statistics by temperature range."""
        if not raw_pairs:
            return []

        temps = [t for _, t in raw_pairs]
        t_min, t_max = min(temps), max(temps)
        if t_max - t_min < 0.1:
            return [
                {
                    "temp_min": t_min,
                    "temp_max": t_max,
                    "point_count": len(raw_pairs),
                    "density": float(len(raw_pairs)),
                    "status": "dense",
                }
            ]

        bin_edges = np.linspace(t_min, t_max, n_bins + 1)
        bins: list[dict[str, Any]] = []

        for i in range(n_bins):
            lo, hi = float(bin_edges[i]), float(bin_edges[i + 1])
            count = sum(1 for _, t in raw_pairs if lo <= t < hi or (i == n_bins - 1 and t == hi))
            width = hi - lo
            density = count / width if width > 0 else 0.0

            if count == 0:
                status = "empty"
            elif density < 1.0:
                status = "sparse"
            elif density < 10.0:
                status = "medium"
            else:
                status = "dense"

            bins.append(
                {
                    "temp_min": round(lo, 3),
                    "temp_max": round(hi, 3),
                    "point_count": count,
                    "density": round(density, 2),
                    "status": status,
                }
            )

        return bins

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def fit(
        self,
        data_dir: Path,
        start_ts: float,
        end_ts: float,
        reference_channel: str,
        target_channel: str,
        calibration_store: CalibrationStore,
        *,
        target_count: int = 500,
        max_breakpoints: int = 200,
        tolerance_mk: float = 50.0,
        min_points_per_zone: int = 6,
        target_rmse_k: float = 0.05,
    ) -> CalibrationFitResult:
        """Full pipeline: extract → downsample → breakpoints → Chebyshev fit."""
        sensor_id = f"{target_channel}_cal"

        # 1. Extract
        raw_pairs = self.extract_pairs(
            data_dir,
            start_ts,
            end_ts,
            reference_channel,
            target_channel,
        )
        if len(raw_pairs) < max(4, min_points_per_zone):
            raise ValueError(
                f"Not enough calibration pairs: {len(raw_pairs)} "
                f"(need at least {max(4, min_points_per_zone)})"
            )

        # 2. Downsample
        downsampled = self.adaptive_downsample(raw_pairs, target_count)

        # 3. Breakpoints
        breakpoints = self.generate_breakpoints(
            downsampled,
            max_breakpoints,
            tolerance_mk,
        )

        # 4. Chebyshev fit via CalibrationStore
        now = datetime.now(UTC)
        samples = [
            CalibrationSample(
                timestamp=now,
                reference_channel=reference_channel,
                reference_temperature=krdg_val,
                sensor_channel=target_channel,
                sensor_raw_value=srdg_val,
            )
            for srdg_val, krdg_val in downsampled
        ]

        curve = calibration_store.fit_curve(
            sensor_id,
            samples,
            raw_unit="sensor_unit",
            min_points_per_zone=min_points_per_zone,
            target_rmse_k=target_rmse_k,
        )
        calibration_store.save_curve(curve)

        # 5. Compute metrics on downsampled set
        errors: list[float] = []
        for srdg_val, krdg_val in downsampled:
            try:
                predicted = calibration_store.evaluate(sensor_id, srdg_val)
                errors.append(predicted - krdg_val)
            except Exception:
                pass

        rmse = float(np.sqrt(np.mean(np.array(errors) ** 2))) if errors else float("nan")
        max_err = float(np.max(np.abs(errors))) if errors else float("nan")

        metrics = {
            "rmse_k": round(rmse, 6),
            "max_abs_error_k": round(max_err, 6),
            "zone_count": len(curve.zones),
            "pair_count": len(raw_pairs),
        }

        return CalibrationFitResult(
            sensor_id=sensor_id,
            reference_channel=reference_channel,
            raw_pairs_count=len(raw_pairs),
            downsampled_count=len(downsampled),
            breakpoint_count=len(breakpoints),
            curve=curve,
            metrics=metrics,
            raw_pairs=raw_pairs,
            downsampled=downsampled,
            breakpoints=breakpoints,
        )
