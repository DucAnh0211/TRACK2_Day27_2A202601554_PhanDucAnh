#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from observability.anomaly import detect_anomaly
from observability.lineage import get_downstream_assets
from observability.rag_metrics import detect_text_length_shift
from observability.slo import calculate_slo, evaluate_multiwindow_burn
from src.contract_validator import failed_issues, load_contract, validate_dataframe
from src.io_utils import load_jsonl


def main() -> None:
    orders = pd.read_csv(ROOT / "data" / "incoming" / "orders.csv")
    validation_time = datetime.now(timezone.utc)
    orders.attrs["validation_time"] = validation_time
    history = pd.read_csv(ROOT / "data" / "history" / "metrics_history.csv")
    contract = load_contract(ROOT / "contracts" / "orders_contract.yaml")
    issues = validate_dataframe(orders, contract)
    failed = failed_issues(issues)
    critical_failed = failed_issues(issues, min_severity="critical")

    # The reset fixture always contains 600 rows, independent of the wall-clock
    # weekday. Use the full robust history here; same-weekday behavior is tested
    # through detect_metric(..., context={"same_segment_history": ...}).
    current_dow = datetime.now().weekday()
    row_history = history["row_count"].tail(28).tolist()
    row_result = detect_anomaly(
        len(orders),
        row_history,
        method="auto",
        context={"metric_name": "row_count", "day_of_week": current_dow},
    )

    updated = pd.to_datetime(orders["updated_at"], utc=True, errors="coerce")
    freshness_minutes = (
        pd.Timestamp(datetime.now(timezone.utc)) - updated.max()
    ).total_seconds() / 60.0

    docs = load_jsonl(ROOT / "data" / "incoming" / "kb_documents.jsonl")
    kb_contract = load_contract(ROOT / "contracts" / "kb_contract.yaml")
    kb_df = pd.DataFrame(docs)
    kb_df.attrs["validation_time"] = validation_time
    kb_issues = validate_dataframe(kb_df, kb_contract)
    kb_failed = failed_issues(kb_issues)
    kb_freshness_issue = next((i for i in kb_issues if i["check"] == "freshness"), None)
    published = pd.to_datetime([d.get("published_at") for d in docs], utc=True, errors="coerce")
    kb_freshness_minutes = (
        (pd.Timestamp(datetime.now(timezone.utc)) - published.max()).total_seconds() / 60.0
        if len(published) and not pd.isna(published.max())
        else float("inf")
    )
    text_result = detect_text_length_shift(
        [d["content"] for d in docs], history["mean_text_length"].tail(14).tolist()
    )

    # Demo SLO: one check event for this run.
    bad = 1 if critical_failed else 0
    contract_slo = calculate_slo(0.999, bad_events=bad, total_events=1)
    kb_slo = calculate_slo(0.99, bad_events=1 if kb_failed else 0, total_events=1)
    combined_burn = evaluate_multiwindow_burn(
        short_window_burn=max(contract_slo["burn_rate"], kb_slo["burn_rate"]),
        long_window_burn=max(contract_slo["burn_rate"], kb_slo["burn_rate"]),
    )

    with open(ROOT / "data" / "baseline" / "lineage_graph.json", "r", encoding="utf-8") as f:
        lineage = json.load(f)["dataset_lineage"]
    blast_radius = get_downstream_assets(lineage, "stg_orders")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "orders_rows": int(len(orders)),
        "failed_contract_checks": len(failed),
        "critical_contract_failures": len(critical_failed),
        "row_count_anomaly": row_result,
        "freshness_minutes": freshness_minutes,
        "kb_freshness_minutes": kb_freshness_minutes,
        "kb_contract_failures": len(kb_failed),
        "kb_freshness_signal": kb_freshness_issue,
        "kb_text_length_signal": text_result,
        "contract_slo": contract_slo,
        "kb_freshness_slo": kb_slo,
        "multiwindow_burn": combined_burn,
        "sample_blast_radius_from_stg_orders": blast_radius,
    }
    out = ROOT / "reports" / "latest_metrics.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("=== DATA RELIABILITY BASELINE ===")
    print(f"orders rows              : {len(orders)}")
    print(f"contract failed checks   : {len(failed)}")
    print(f"critical contract fails  : {len(critical_failed)}")
    print(f"row-count anomaly        : {row_result['is_anomaly']} ({row_result['method']}, score={row_result['score']:.2f})")
    print(f"freshness minutes        : {freshness_minutes:.1f}")
    print(f"KB freshness minutes     : {kb_freshness_minutes:.1f}")
    print(f"KB contract fails        : {len(kb_failed)}")
    print(f"KB length anomaly        : {text_result['is_anomaly']}")
    print(f"multi-window page        : {combined_burn['page']} ({combined_burn['severity']})")
    print(f"sample blast radius      : {', '.join(blast_radius)}")
    print(f"report                    : {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
