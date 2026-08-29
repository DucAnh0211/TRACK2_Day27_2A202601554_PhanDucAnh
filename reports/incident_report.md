# Incident Report — Duplicate Order Replay

## Severity

P1 — dữ liệu có khả năng làm phình revenue trên CEO dashboard; critical contract đã block trước khi publish.

## Summary

Trong game-day run, batch `orders` tăng từ 600 lên 603 dòng do ba `order_id` đầu tiên xuất hiện lần thứ hai. Pipeline kỹ thuật vẫn có thể chạy, nhưng data contract và Great Expectations xác định đây là vi phạm uniqueness mức `critical`. Batch bị block và được sao chép vào khu vực quarantine, vì vậy dữ liệu lỗi không được coi là an toàn để publish.

## Detection

- Signal đầu tiên: `unique(order_id)` thất bại.
- First observed time: lần chạy public scenario `duplicate_pk` ngày 2026-08-29.
- Contract evidence: 1 critical failure, 603 rows thay vì 600.
- GX evidence: 7/8 expectations pass; uniqueness trả 6 unexpected rows tương ứng ba ID bị lặp hai lần.
- SLO evidence: critical-contract SLO 99.9%, 1 bad check/1 check, burn rate 1000x; multi-window demo page mức `critical`.
- Anomaly evidence: row-count score 0.24, không đủ để alert. Điều này chứng minh deterministic contract là lớp phát hiện phù hợp cho duplicate nhỏ.

## Root Cause

Batch ingestion đã replay một phần dữ liệu mà không thực thi idempotency/upsert theo `order_id`. Ba record hợp lệ bị append lại; schema, accepted values và amount range vẫn đúng nên chỉ uniqueness bắt được lỗi.

## Evidence

1. Healthy baseline: 600 rows, 0 contract failures, row-count anomaly `false` với MAD score 0.17.
2. Fault run: 603 rows, 1 critical contract failure; GX báo các ID `100000`, `100001`, `100002` mỗi ID có count 2.
3. dbt build trên dữ liệu khỏe: PASS=19, gồm 12 data tests và 2 unit tests; unit test xác nhận duplicate active SCD customer không làm nhân revenue.

## Blast Radius

```text
raw_orders
-> stg_orders
-> fct_daily_revenue
-> ceo_revenue_dashboard
```

Nếu không block, các completed duplicate có thể làm tăng `completed_order_rows` và `daily_revenue`. KB/RAG pipeline không nằm trong blast radius của incident này.

## Mitigation

1. Block batch vì failure có severity `critical`.
2. Quarantine batch tại `data/quarantine/orders.csv` để điều tra, không publish downstream.
3. Khôi phục incoming data từ healthy baseline.
4. Giữ dbt defense-in-depth: uniqueness test trên `stg_orders.order_id`, singular business tests và model chống SCD join multiplication.

## Recovery

Sau `make reset`, batch trở về 600 dòng. Baseline không còn contract failure; row-count signal trở lại expected range. GX Checkpoint pass 8/8 expectations và dbt build pass toàn bộ 19 resources.

## Verification

- [x] Contract healthy — 0 failed checks.
- [x] dbt tests healthy — PASS=19, WARN=0, ERROR=0.
- [x] Anomaly returned to expected range — MAD score 0.17, `is_anomaly=false`.
- [x] SLO healthy / budget understood — no bad contract or KB freshness event after reset.
- [x] Downstream output verified — `fct_daily_revenue` build và tests pass.

## Prevention / Action Items

| Action | Owner | Deadline | Why |
|---|---|---|---|
| Enforce idempotent merge/upsert by `order_id` at ingestion | commerce-data | 2026-09-02 | Ngăn retry append lại record |
| Keep critical uniqueness contract before dbt publish | data-reliability | Done | Fail fast và quarantine batch |
| Alert on repeated critical-contract burn in paired windows | SRE | 2026-09-03 | Giảm alert noise nhưng page lỗi kéo dài |
| Preserve dbt unit test for duplicate active SCD versions | analytics-engineering | Done | Ngăn revenue inflation do join |
| Add incident runbook link to dashboard | data-reliability | Done | Rút ngắn thời gian triage |
