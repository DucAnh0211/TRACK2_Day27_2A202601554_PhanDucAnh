from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def _finite(values: Iterable[float]) -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    return np.sort(array[np.isfinite(array)])


def _ks_distance(left: np.ndarray, right: np.ndarray) -> float:
    """Compute the two-sample Kolmogorov-Smirnov distance without SciPy."""
    points = np.sort(np.unique(np.concatenate([left, right])))
    left_cdf = np.searchsorted(left, points, side="right") / left.size
    right_cdf = np.searchsorted(right, points, side="right") / right.size
    return float(np.max(np.abs(left_cdf - right_cdf)))


def detect_distribution_shift(
    current_values: Iterable[float],
    baseline_values: Iterable[float],
    *,
    ratio_threshold: float = 3.0,
) -> dict[str, Any]:
    """Detect location, spread, or shape drift using robust statistics and KS."""
    cur = _finite(current_values)
    base = _finite(baseline_values)
    if cur.size == 0 or base.size == 0:
        return {
            "is_anomaly": False,
            "score": 0.0,
            "method": "ks_robust",
            "reason": "empty_or_non_finite_input",
        }

    base_median = float(np.median(base))
    cur_median = float(np.median(cur))
    q1, q3 = np.quantile(base, [0.25, 0.75])
    cur_q1, cur_q3 = np.quantile(cur, [0.25, 0.75])
    base_iqr = float(q3 - q1)
    cur_iqr = float(cur_q3 - cur_q1)

    # Fall back to a magnitude-aware epsilon for constant baselines.
    scale = base_iqr if base_iqr > 0 else max(abs(base_median) * 0.01, 1e-9)
    location_score = abs(cur_median - base_median) / scale
    if base_iqr == 0:
        spread_ratio = 1.0 if cur_iqr == 0 else float("inf")
    elif cur_iqr == 0:
        spread_ratio = float("inf")
    else:
        spread_ratio = max(cur_iqr / base_iqr, base_iqr / cur_iqr)

    ks = _ks_distance(cur, base)
    # Approximate alpha=0.01 two-sample critical value. For tiny samples the
    # robust location/spread checks still catch large business-impacting shifts.
    ks_threshold = min(1.0, 1.63 * np.sqrt((cur.size + base.size) / (cur.size * base.size)))
    is_anomaly = bool(
        location_score >= ratio_threshold
        or spread_ratio >= ratio_threshold
        or (cur.size >= 5 and base.size >= 5 and ks > ks_threshold)
    )
    score = max(
        float(location_score),
        float(spread_ratio if np.isfinite(spread_ratio) else float("inf")),
        float(ks / ks_threshold) if ks_threshold else 0.0,
    )
    return {
        "is_anomaly": is_anomaly,
        "score": float(score),
        "method": "ks_robust",
        "reason": (
            f"baseline_median={base_median:.6g}, current_median={cur_median:.6g}, "
            f"location_score={location_score:.3f}, spread_ratio={spread_ratio:.3f}, "
            f"ks={ks:.3f}, ks_threshold={ks_threshold:.3f}"
        ),
        "location_score": float(location_score),
        "spread_ratio": float(spread_ratio),
        "ks_distance": float(ks),
    }
