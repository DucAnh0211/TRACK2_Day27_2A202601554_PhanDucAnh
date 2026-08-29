from __future__ import annotations

import math
from typing import Any


def calculate_slo(target: float, bad_events: int, total_events: int) -> dict[str, Any]:
    if not 0 < target < 1:
        raise ValueError("target must be between 0 and 1 (exclusive)")
    if bad_events < 0 or total_events < 0 or bad_events > total_events:
        raise ValueError("invalid event counts")
    allowed_bad_rate = 1.0 - target
    if total_events == 0:
        return {
            "target": target,
            "actual_bad_rate": 0.0,
            "allowed_bad_rate": allowed_bad_rate,
            "burn_rate": 0.0,
            "remaining_error_budget_fraction": 1.0,
            "breached": False,
        }
    actual_bad_rate = bad_events / total_events
    burn_rate = actual_bad_rate / allowed_bad_rate
    consumed_fraction = min(1.0, actual_bad_rate / allowed_bad_rate)
    return {
        "target": target,
        "actual_bad_rate": actual_bad_rate,
        "allowed_bad_rate": allowed_bad_rate,
        "burn_rate": burn_rate,
        "remaining_error_budget_fraction": max(0.0, 1.0 - consumed_fraction),
        "breached": bool(actual_bad_rate > allowed_bad_rate),
    }


def evaluate_multiwindow_burn(
    *,
    short_window_burn: float,
    long_window_burn: float,
    policy: str = "standard",
) -> dict[str, Any]:
    """Evaluate paired burn windows and suppress isolated transient spikes.

    Both windows must exceed a threshold. This implements the key SRE property
    of multi-window alerting: a fast short-window burn alone is insufficient to
    page when the longer window shows that the event was transient.
    """
    short = float(short_window_burn)
    long = float(long_window_burn)
    if not math.isfinite(short) or not math.isfinite(long) or short < 0 or long < 0:
        raise ValueError("burn rates must be finite and non-negative")

    # A 14.4x pair represents a very fast error-budget burn. A 6x pair catches
    # a sustained slower burn. Thresholds are intentionally explicit in output
    # so an operator can defend why an alert fired.
    if short >= 14.4 and long >= 14.4:
        page = True
        severity = "critical"
        reason = "sustained_fast_burn: both windows are at least 14.4x"
        threshold = 14.4
    elif short >= 6.0 and long >= 6.0:
        page = True
        severity = "warning"
        reason = "sustained_burn: both windows are at least 6x"
        threshold = 6.0
    elif short >= 6.0 and long < 6.0:
        page = False
        severity = "info"
        reason = "transient_spike: short window is high but long window is below 6x"
        threshold = 6.0
    else:
        page = False
        severity = "info"
        reason = "within_multiwindow_policy"
        threshold = 6.0
    return {
        "page": page,
        "severity": severity,
        "reason": reason,
        "short_window_burn": short,
        "long_window_burn": long,
        "threshold": threshold,
        "policy": policy,
    }
