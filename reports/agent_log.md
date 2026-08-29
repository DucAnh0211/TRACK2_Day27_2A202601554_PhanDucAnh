# AI Agent Decision Log

## Decision 1 — Contract types and freshness

- Hypothesis: `pd.to_numeric(..., errors="coerce")` có thể che giấu type drift; freshness cần processing clock rõ ràng để không làm fail historical replay.
- Prompt / request to agent: hoàn thiện type checking, freshness, severity và action nhưng giữ stable API.
- Agent proposal: strict numeric/string checks, parseable datetime, `df.attrs["validation_time"]` cho production/replay tests, và action `block/warn/observe`.
- Evidence/test: test numeric string trong `order_id`, stale timestamp với explicit clock, missing critical column; cả ba pass.
- Accept / reject / revise: revise rồi accept.
- Why: bản đầu so wall clock làm public historical fixture fail; thêm replay-safe clock contract để test và vận hành đều deterministic.

## Decision 2 — Robust anomaly detection

- Hypothesis: global Z-score báo sai cho weekend và dễ bị outlier kéo lệch.
- Prompt / request to agent: làm `method="auto"` context-aware, vẫn giữ explicit Z-score.
- Agent proposal: ưu tiên `same_segment_history`, dùng median/MAD, xử lý MAD=0 và fallback Z-score khi history ngắn.
- Evidence/test: legitimate Saturday 251 trên baseline 245–255 không alert; current 100 alert; public volume drop 600 xuống 150 cho MAD score 10.29.
- Accept / reject / revise: accept.
- Why: bắt failure thật mà không cần ML phức tạp và giảm false positive do seasonality.

## Decision 3 — SCD join revenue inflation

- Hypothesis: hai active customer versions nhân đôi order rows khi join.
- Prompt / request to agent: viết unit test nhỏ nhất để expose failure rồi sửa production model.
- Agent proposal: unit fixture có hai active rows cho cùng customer; deduplicate bằng `row_number()` trước join; thêm singular test phát hiện upstream violation.
- Evidence/test: dbt unit test kỳ vọng 2 orders và revenue 170 thay vì 4 rows/revenue 340; dbt build PASS=19.
- Accept / reject / revise: accept.
- Why: unit test bảo vệ transformation logic, singular test bảo vệ dữ liệu thực, model có defense-in-depth.

## Decision 4 — Multi-window burn rate

- Hypothesis: page chỉ theo short window tạo noise từ transient spike.
- Prompt / request to agent: phân biệt spike ngắn với sustained burn.
- Agent proposal: cả short và long windows phải cùng vượt 6x để page; cả hai vượt 14.4x thì critical.
- Evidence/test: `(20x, 1x)` không page; `(8x, 7x)` page; duplicate/stale-KB scenario page critical khi cả hai demo windows cùng cháy.
- Accept / reject / revise: accept.
- Why: giữ tính actionable của alert và thể hiện rõ threshold trong output.

## Decision 5 — GX severity action

- Hypothesis: expectation rời rạc chỉ cho biết pass/fail, chưa tạo operational response.
- Prompt / request to agent: đóng gói Suite, ValidationDefinition, Checkpoint và Actions.
- Agent proposal: 8-expectation suite, custom local audit Action, contract-driven block/quarantine cho critical failures.
- Evidence/test: healthy batch pass 8/8; duplicate fault fail uniqueness với 6 unexpected rows, exit non-zero và tạo `data/quarantine/orders.csv`.
- Accept / reject / revise: accept.
- Why: kết quả validation dẫn trực tiếp tới hành động có thể kiểm chứng, không chỉ in log.

## Decision 6 — Distribution and RAG drift

- Hypothesis: mean ratio bỏ sót shape drift có cùng mean; embedding norm drift đang luôn trả false.
- Prompt / request to agent: bổ sung signal không cần tải embedding model.
- Agent proposal: kết hợp KS distance, median/IQR location/spread; áp dụng detector cho precomputed embedding norms.
- Evidence/test: bimodal distribution có center gần baseline vẫn bị bắt; embedding norms dịch từ khoảng 1.0 lên khoảng 2.0 bị alert.
- Accept / reject / revise: accept.
- Why: tăng coverage hidden cases với dependency local và return shape ổn định.
