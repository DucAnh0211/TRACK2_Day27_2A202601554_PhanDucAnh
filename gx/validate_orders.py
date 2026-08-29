#!/usr/bin/env python3
"""Great Expectations 1.21 Suite -> ValidationDefinition -> Checkpoint flow."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import great_expectations as gx
    from great_expectations.checkpoint import ActionContext, CheckpointResult, ValidationAction
except ImportError as exc:
    raise SystemExit("great_expectations is not installed. Run: uv pip install -r requirements.txt") from exc

from src.contract_validator import failed_issues, load_contract, validate_dataframe


class WriteReliabilityAuditAction(ValidationAction):
    """Persist a local, credential-free audit artifact after every Checkpoint."""

    type: Literal["write_reliability_audit"] = "write_reliability_audit"
    output_path: str

    def run(
        self,
        checkpoint_result: CheckpointResult,
        action_context: ActionContext | None = None,
    ) -> dict:
        del action_context
        summary = checkpoint_result.describe()
        path = Path(self.output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        return {"audit_path": str(path), "checkpoint_success": bool(checkpoint_result.success)}


def _expectations() -> list:
    return [
        gx.expectations.ExpectColumnValuesToNotBeNull(column="order_id", severity="critical"),
        gx.expectations.ExpectColumnValuesToBeUnique(column="order_id", severity="critical"),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="customer_id", severity="critical"),
        gx.expectations.ExpectColumnValuesToBeBetween(column="amount", min_value=0, severity="critical"),
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="currency", value_set=["USD", "VND"], severity="critical"
        ),
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="status",
            value_set=["pending", "completed", "refunded", "cancelled"],
            severity="warning",
        ),
        gx.expectations.ExpectColumnValuesToMatchStrftimeFormat(
            column="created_at", strftime_format="%Y-%m-%dT%H:%M:%S%z", severity="critical"
        ),
        gx.expectations.ExpectColumnValuesToMatchStrftimeFormat(
            column="updated_at", strftime_format="%Y-%m-%dT%H:%M:%S%z", severity="critical"
        ),
    ]


def run_checkpoint(df: pd.DataFrame) -> tuple[CheckpointResult, str, list[dict]]:
    context = gx.get_context(mode="ephemeral")
    data_source = context.data_sources.add_pandas("orders_pandas")
    asset = data_source.add_dataframe_asset(name="orders_dataframe")
    batch_definition = asset.add_batch_definition_whole_dataframe("whole_orders")

    suite = gx.ExpectationSuite(name="orders_reliability_suite")
    for expectation in _expectations():
        suite.add_expectation(expectation)
    suite = context.suites.add(suite)

    validation_definition = context.validation_definitions.add(
        gx.ValidationDefinition(
            name="orders_validation_definition",
            data=batch_definition,
            suite=suite,
        )
    )
    checkpoint = context.checkpoints.add(
        gx.Checkpoint(
            name="orders_reliability_checkpoint",
            validation_definitions=[validation_definition],
            actions=[
                WriteReliabilityAuditAction(
                    name="write_local_audit",
                    output_path=str(ROOT / "reports" / "gx_checkpoint_result.json"),
                )
            ],
            result_format={"result_format": "COMPLETE"},
        )
    )
    result = checkpoint.run(batch_parameters={"dataframe": df})

    contract_issues = validate_dataframe(
        df,
        load_contract(ROOT / "contracts" / "orders_contract.yaml"),
    )
    critical = failed_issues(contract_issues, min_severity="critical")
    failed = failed_issues(contract_issues)
    if critical:
        quarantine = ROOT / "data" / "quarantine" / "orders.csv"
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(quarantine, index=False)
        action = f"block_and_quarantine:{quarantine.relative_to(ROOT)}"
    elif failed:
        action = "warn"
    else:
        action = "accept"
    return result, action, contract_issues


def main() -> None:
    df = pd.read_csv(ROOT / "data" / "incoming" / "orders.csv")
    result, action, issues = run_checkpoint(df)
    failed = failed_issues(issues)
    print(result.describe())
    print(f"Contract failures: {len(failed)}")
    print(f"Severity action: {action}")
    print("GX checkpoint result:", "PASS" if bool(result.success) else "FAIL")
    if not bool(result.success):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
