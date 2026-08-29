"""Anomaly detection starter.

Z-score is deliberately the default baseline. Students should improve `auto`
mode for seasonality/outliers rather than deleting the simple implementation.
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def _finite_values(values: Iterable[float]) -> np.ndarray:
    finite: list[float] = []
    for raw in values:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if np.isfinite(value):
            finite.append(value)
    return np.asarray(finite, dtype=float)


def _invalid_current(current: float, method: str) -> dict[str, Any] | None:
    try:
        value = float(current)
    except (TypeError, ValueError):
        return {"is_anomaly": True, "score": float("inf"), "method": method, "reason": "current_not_numeric"}
    if not np.isfinite(value):
        return {"is_anomaly": True, "score": float("inf"), "method": method, "reason": "current_not_finite"}
    return None


def zscore_detector(current: float, history: Iterable[float], threshold: float = 3.0) -> dict[str, Any]:
    invalid = _invalid_current(current, "zscore")
    if invalid:
        return invalid
    values = _finite_values(history)
    if values.size < 3:
        return {"is_anomaly": False, "score": 0.0, "method": "zscore", "reason": "insufficient_history"}
    mean = float(np.mean(values))
    std = float(np.std(values))
    if std == 0:
        score = float("inf") if float(current) != mean else 0.0
    else:
        score = abs(float(current) - mean) / std
    return {
        "is_anomaly": bool(score > threshold),
        "score": float(score),
        "method": "zscore",
        "reason": f"mean={mean:.3f}, std={std:.3f}, threshold={threshold}",
    }


def mad_detector(current: float, history: Iterable[float], threshold: float = 3.5) -> dict[str, Any]:
    """Robust modified Z-score detector with deterministic zero-MAD behavior."""
    invalid = _invalid_current(current, "mad")
    if invalid:
        return invalid
    values = _finite_values(history)
    if values.size < 5:
        return {"is_anomaly": False, "score": 0.0, "method": "mad", "reason": "insufficient_history"}
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad == 0:
        deviation = abs(float(current) - median)
        # When most history is identical, any material deviation is actionable.
        tolerance = max(abs(median) * 0.01, 1e-9)
        score = 0.0 if deviation <= tolerance else float("inf")
        return {
            "is_anomaly": bool(deviation > tolerance),
            "score": score,
            "method": "mad",
            "reason": f"median={median:.3f}, mad=0, tolerance={tolerance:.6g}",
        }
    modified_z = 0.6745 * abs(float(current) - median) / mad
    return {
        "is_anomaly": bool(modified_z > threshold),
        "score": float(modified_z),
        "method": "mad",
        "reason": f"median={median:.3f}, mad={mad:.3f}, threshold={threshold}",
    }


def detect_anomaly(
    current: float,
    history: Iterable[float],
    *,
    method: str = "auto",
    threshold: float = 3.0,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect a metric anomaly while preserving explicit baseline methods.

    ``auto`` prefers a same-segment baseline (for example, the same weekday),
    then a robust MAD baseline, and falls back to Z-score for short histories.
    """
    if method == "mad":
        return mad_detector(current, history)
    if method == "zscore":
        return zscore_detector(current, history, threshold=threshold)
    if method == "auto":
        context = context or {}
        raw_segment = context.get("same_segment_history")
        segment = _finite_values(raw_segment) if raw_segment is not None else np.asarray([], dtype=float)
        full_history = _finite_values(history)

        if segment.size >= 5:
            result = mad_detector(current, segment, threshold=max(3.5, threshold))
            result["method"] = "auto:same_segment_mad"
            result["reason"] += f"; segment_size={segment.size}"
        elif segment.size >= 3:
            result = zscore_detector(current, segment, threshold=threshold)
            result["method"] = "auto:same_segment_zscore"
            result["reason"] += f"; segment_size={segment.size}"
        elif full_history.size >= 5:
            result = mad_detector(current, full_history, threshold=max(3.5, threshold))
            result["method"] = "auto:mad"
        else:
            result = zscore_detector(current, full_history, threshold=threshold)
            result["method"] = "auto:zscore"

        metric_name = context.get("metric_name")
        if metric_name:
            result["metric"] = str(metric_name)
        if context.get("day_of_week") is not None:
            result["segment"] = f"day_of_week={context['day_of_week']}"
        if context.get("known_event"):
            # Do not silently hide real failures; expose the event for triage.
            result["reason"] += f"; known_event={context['known_event']}"
            result["known_event"] = context["known_event"]
        return result
    raise ValueError(f"Unsupported method: {method}")
