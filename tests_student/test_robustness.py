from pathlib import Path

import pandas as pd
import pytest

from student_api import (
    column_downstream,
    detect_distribution,
    detect_metric,
    multiwindow_burn,
    rag_embedding_shift,
    validate_orders,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "orders_contract.yaml"


def orders_df() -> pd.DataFrame:
    df = pd.DataFrame(
        [
            {
                "order_id": 1,
                "customer_id": "C1",
                "amount": 10.0,
                "currency": "USD",
                "status": "completed",
                "created_at": "2026-08-29T09:00:00Z",
                "updated_at": "2026-08-29T09:55:00Z",
            }
        ]
    )
    df.attrs["validation_time"] = "2026-08-29T10:00:00Z"
    return df


def failures(df: pd.DataFrame) -> list[dict]:
    return [result for result in validate_orders(df, CONTRACT) if not result["passed"]]


def test_type_drift_is_not_silently_coerced():
    df = orders_df()
    df["order_id"] = df["order_id"].astype(str)
    assert any(item["check"] == "type" and item["column"] == "order_id" for item in failures(df))


def test_freshness_uses_explicit_processing_clock():
    df = orders_df()
    df["updated_at"] = "2026-08-29T08:00:00Z"
    issue = next(item for item in failures(df) if item["check"] == "freshness")
    assert issue["severity"] == "warning"
    assert issue["action"] == "warn"


def test_missing_critical_column_blocks():
    issue = next(item for item in failures(orders_df().drop(columns=["order_id"])) if item["column"] == "order_id")
    assert issue["severity"] == "critical"
    assert issue["action"] == "block"


def test_auto_uses_same_weekday_baseline():
    history = [600, 620, 590, 610, 250, 245, 255, 605, 615]
    context = {"day_of_week": 5, "same_segment_history": [245, 250, 255, 248, 252]}
    assert detect_metric(251, history, method="auto", context=context)["is_anomaly"] is False
    assert detect_metric(100, history, method="auto", context=context)["is_anomaly"] is True


def test_zero_mad_detects_material_change():
    result = detect_metric(50, [100, 100, 100, 100, 100], method="mad")
    assert result["is_anomaly"] is True


def test_distribution_detects_shape_change_with_similar_center():
    baseline = list(range(1, 101))
    current = [1] * 50 + [100] * 50
    assert detect_distribution(current, baseline)["is_anomaly"] is True


def test_column_lineage_is_transitive_and_cycle_safe():
    graph = {"a.x": ["b.x"], "b.x": ["c.y"], "c.y": ["a.x", "d.z"]}
    assert column_downstream(graph, "a.x") == ["b.x", "c.y", "d.z"]


def test_multiwindow_suppresses_spike_and_pages_sustained_burn():
    assert multiwindow_burn(20, 1)["page"] is False
    assert multiwindow_burn(8, 7)["page"] is True
    with pytest.raises(ValueError):
        multiwindow_burn(-1, 7)


def test_embedding_norm_shift_is_detected():
    baseline = [0.98, 1.0, 1.01, 1.02, 0.99, 1.0]
    current = [1.9, 2.0, 2.1, 2.05, 1.95]
    assert rag_embedding_shift(current, baseline)["is_anomaly"] is True
