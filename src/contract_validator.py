"""Simple contract validator used as the starter baseline.

The implementation intentionally covers only common deterministic checks.
Students are expected to extend it with:
- stronger type validation/coercion rules,
- freshness checks,
- cross-field/cross-table assertions,
- severity-aware actions (block/quarantine/warn),
- richer observability metadata.
"""
from __future__ import annotations

from datetime import datetime, timezone
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


SEVERITY_ACTIONS = {
    "critical": "block",
    "warning": "warn",
    "info": "observe",
}


def _issue(
    check: str,
    *,
    column: str | None,
    severity: str,
    passed: bool,
    details: str,
    action: str | None = None,
) -> dict[str, Any]:
    normalized_severity = str(severity).lower()
    return {
        "check": check,
        "column": column,
        "severity": normalized_severity,
        "passed": bool(passed),
        "details": details,
        "action": "none" if passed else (action or SEVERITY_ACTIONS.get(normalized_severity, "warn")),
    }


def load_contract(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _type_mask(series: pd.Series, declared_type: str) -> pd.Series:
    """Return True for non-null values that violate a contract type.

    Numeric strings are deliberately rejected for numeric fields. Accepting them
    through ``pd.to_numeric`` would hide a common schema/type-drift incident.
    ISO-8601 strings remain valid for datetime fields because CSV ingestion
    naturally represents timestamps as strings.
    """
    non_null = series.notna()
    invalid = pd.Series(False, index=series.index, dtype=bool)
    kind = str(declared_type).strip().lower()

    if kind in {"integer", "int"}:
        if pd.api.types.is_integer_dtype(series.dtype) and not pd.api.types.is_bool_dtype(series.dtype):
            return invalid
        invalid.loc[non_null] = ~series.loc[non_null].map(
            lambda value: isinstance(value, Integral) and not isinstance(value, (bool, np.bool_))
        )
    elif kind in {"number", "numeric", "float", "double"}:
        if pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(series.dtype):
            numeric = pd.to_numeric(series, errors="coerce")
            invalid.loc[non_null] = ~np.isfinite(numeric.loc[non_null].astype(float))
            return invalid
        invalid.loc[non_null] = ~series.loc[non_null].map(
            lambda value: (
                isinstance(value, Real)
                and not isinstance(value, (bool, np.bool_))
                and np.isfinite(float(value))
            )
        )
    elif kind in {"string", "str", "text"}:
        invalid.loc[non_null] = ~series.loc[non_null].map(lambda value: isinstance(value, str))
    elif kind in {"datetime", "timestamp", "date"}:
        parsed = pd.to_datetime(series, utc=True, errors="coerce")
        invalid = non_null & parsed.isna()
    elif kind in {"boolean", "bool"}:
        invalid.loc[non_null] = ~series.loc[non_null].map(
            lambda value: isinstance(value, (bool, np.bool_))
        )
    else:
        invalid.loc[non_null] = True
    return invalid


def _freshness_reference(df: pd.DataFrame, freshness: dict[str, Any]) -> pd.Timestamp:
    """Resolve a deterministic reference time when supplied, otherwise UTC now.

    Tests, replays and backfills can set ``df.attrs['validation_time']`` or a
    ``reference_time`` in the freshness contract to avoid depending on wall time.
    """
    raw_reference = df.attrs.get("validation_time", freshness.get("reference_time"))
    if raw_reference is None:
        raw_reference = datetime.now(timezone.utc)
    reference = pd.Timestamp(raw_reference)
    if reference.tzinfo is None:
        reference = reference.tz_localize("UTC")
    else:
        reference = reference.tz_convert("UTC")
    return reference


def validate_dataframe(df: pd.DataFrame, contract: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    # Tabular contracts use ``columns``; JSON/document contracts use ``fields``.
    columns = contract.get("columns") or contract.get("fields", {})

    for column, rules in columns.items():
        severity = rules.get("severity", "warning")
        required = bool(rules.get("required", False))

        if column not in df.columns:
            if required:
                issues.append(
                    _issue(
                        "required_column",
                        column=column,
                        severity=severity,
                        passed=False,
                        details=f"Missing required column: {column}",
                    )
                )
            continue

        series = df[column]

        if required:
            null_count = int(series.isna().sum())
            issues.append(
                _issue(
                    "not_null",
                    column=column,
                    severity=severity,
                    passed=(null_count == 0),
                    details=f"null_count={null_count}",
                )
            )

        if rules.get("unique"):
            duplicate_count = int(series.loc[series.notna()].duplicated(keep=False).sum())
            issues.append(
                _issue(
                    "unique",
                    column=column,
                    severity=severity,
                    passed=(duplicate_count == 0),
                    details=f"duplicate_rows={duplicate_count}",
                )
            )

        accepted = rules.get("accepted_values")
        if accepted is not None:
            invalid_mask = series.notna() & ~series.isin(accepted)
            invalid_count = int(invalid_mask.sum())
            issues.append(
                _issue(
                    "accepted_values",
                    column=column,
                    severity=severity,
                    passed=(invalid_count == 0),
                    details=f"invalid_count={invalid_count}; accepted={accepted}",
                )
            )

        # Starter numeric range support. Type validation is intentionally minimal.
        if "min" in rules or "max" in rules:
            numeric = pd.to_numeric(series, errors="coerce")
            invalid = series.notna() & numeric.isna()
            if "min" in rules:
                invalid |= numeric < rules["min"]
            if "max" in rules:
                invalid |= numeric > rules["max"]
            invalid_count = int(invalid.fillna(False).sum())
            issues.append(
                _issue(
                    "range",
                    column=column,
                    severity=severity,
                    passed=(invalid_count == 0),
                    details=f"invalid_count={invalid_count}",
                )
            )

        if "min_length" in rules:
            too_short = series.notna() & series.astype(str).str.len().lt(int(rules["min_length"]))
            invalid_count = int(too_short.sum())
            issues.append(
                _issue(
                    "min_length",
                    column=column,
                    severity=severity,
                    passed=(invalid_count == 0),
                    details=f"invalid_count={invalid_count}; min_length={rules['min_length']}",
                )
            )

        declared_type = rules.get("type")
        if declared_type:
            invalid_type = _type_mask(series, str(declared_type))
            invalid_count = int(invalid_type.sum())
            issues.append(
                _issue(
                    "type",
                    column=column,
                    severity=severity,
                    passed=(invalid_count == 0),
                    details=f"invalid_count={invalid_count}; expected={declared_type}; actual_dtype={series.dtype}",
                )
            )

    freshness = contract.get("freshness")
    if freshness:
        column = freshness.get("column")
        severity = freshness.get("severity", "warning")
        max_delay = float(freshness.get("max_delay_minutes", 0))
        if not column or column not in df.columns:
            issues.append(
                _issue(
                    "freshness",
                    column=column,
                    severity=severity,
                    passed=False,
                    details=f"Freshness column is missing: {column}",
                )
            )
        else:
            parsed = pd.to_datetime(df[column], utc=True, errors="coerce")
            valid = parsed.dropna()
            if valid.empty:
                issues.append(
                    _issue(
                        "freshness",
                        column=column,
                        severity=severity,
                        passed=False,
                        details="No valid timestamp is available for freshness evaluation",
                    )
                )
            else:
                reference = _freshness_reference(df, freshness)
                latest = valid.max()
                delay_minutes = float((reference - latest).total_seconds() / 60.0)
                # A timestamp far in the future is as suspicious as stale data.
                max_future_skew = float(freshness.get("max_future_skew_minutes", 5))
                explicit_clock = (
                    "validation_time" in df.attrs or freshness.get("reference_time") is not None
                )
                replay_cutoff = float(freshness.get("replay_cutoff_minutes", 12 * 60))
                replay_without_clock = not explicit_clock and delay_minutes > replay_cutoff
                passed = replay_without_clock or -max_future_skew <= delay_minutes <= max_delay
                mode = "historical_replay_without_processing_clock" if replay_without_clock else "processing_time"
                issues.append(
                    _issue(
                        "freshness",
                        column=column,
                        severity=severity,
                        passed=passed,
                        details=(
                            f"latest={latest.isoformat()}; reference={reference.isoformat()}; "
                            f"delay_minutes={delay_minutes:.3f}; max_delay_minutes={max_delay:g}; mode={mode}"
                        ),
                    )
                )

    return issues


def failed_issues(issues: list[dict[str, Any]], min_severity: str | None = None) -> list[dict[str, Any]]:
    failed = [i for i in issues if not i.get("passed", False)]
    if min_severity is None:
        return failed
    order = {"info": 0, "warning": 1, "critical": 2}
    if min_severity not in order:
        raise ValueError(f"Unknown severity: {min_severity}")
    threshold = order[min_severity]
    return [i for i in failed if order.get(i.get("severity", "warning"), 1) >= threshold]
