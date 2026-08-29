from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "latest_metrics.json"
HISTORY = ROOT / "data" / "history" / "metrics_history.csv"

st.set_page_config(page_title="Data Reliability Lab", layout="wide")
st.title("Data Reliability Game Day")
st.caption("Contract, anomaly, lineage and SLO signals for incident decisions.")

if not REPORT.exists():
    st.warning("Run `make baseline` first to generate reports/latest_metrics.json")
    st.stop()

report = json.loads(REPORT.read_text(encoding="utf-8"))

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Orders rows", report["orders_rows"])
c2.metric("Freshness (min)", f"{report['freshness_minutes']:.1f}")
c3.metric("KB freshness (min)", f"{report.get('kb_freshness_minutes', 0):.1f}")
c4.metric("Contract failures", report["failed_contract_checks"])
c5.metric("Critical failures", report["critical_contract_failures"])

burn = report.get("multiwindow_burn", {})
if burn.get("page"):
    st.error(f"Incident status: PAGE ({burn.get('severity')}) — {burn.get('reason')}")
else:
    st.success(f"Incident status: no page — {burn.get('reason', 'healthy')}")

st.subheader("Current signals")
st.json({
    "row_count_anomaly": report["row_count_anomaly"],
    "kb_text_length_signal": report["kb_text_length_signal"],
    "kb_freshness_signal": report.get("kb_freshness_signal"),
    "contract_slo": report["contract_slo"],
    "kb_freshness_slo": report.get("kb_freshness_slo"),
    "multiwindow_burn": burn,
})

history = pd.read_csv(HISTORY)
st.subheader("Historical row count")
st.line_chart(history.set_index("date")[["row_count"]])

st.subheader("Example blast radius")
st.write("stg_orders -> " + " -> ".join(report["sample_blast_radius_from_stg_orders"]))

st.info("Owners: commerce-data (orders), support-ai (KB). Runbook: reports/incident_report.md")
