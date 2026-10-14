# Quy trình Thẩm định Nghiêm ngặt và Kết nối Endpoint Sol Reviewer

### 1. Nguyên tắc Thẩm định Đối soát (Adversarial Empirical Rigor)
- **Cấm rút ngắn prompt review hoặc bỏ qua số liệu thực nghiệm:** Prompt gửi Sol Reviewer (`gpt-6-sol`, reasoning: `high`) bắt buộc phải đính kèm đầy đủ:
  1. Toàn bộ đặc tả kỹ thuật và tiêu chí nghiệm thu của Milestone trích từ Astra Plan.
  2. Toàn bộ committed code changes (`git diff`), commit SHA chính xác từ `git rev-parse HEAD`.
  3. Raw artifact JSON chứa số liệu thực nghiệm thật: thời gian chạy thật (wall-clock latency, sum of sample latencies), p95 latency, các bài test A/B ablation thật với cùng budget.
  4. Log test suite độc lập (Rust core tests, Python amplifier tests, Invariants, Oracle controls).
- **Tránh review sơ sài 30-40s:** Nếu prompt bị cắt ngắn không có dữ liệu thực nghiệm, Sol sẽ không thể đối soát sâu, gây ra đánh giá thiếu căn cứ hoặc bị từ chối. Sol cần đủ dữ liệu để chạy reasoning sâu và trả về log chi tiết từng finding.

### 2. Cấu hình Endpoint & Xác minh Quota Thực tế
- Khi chuyển đổi proxy pool (ví dụ `Codex CLI () connected to API pool http://localhost:13844/v1` với model `gpt-6-sol` và token được chỉ định):
  - Gửi request trực tiếp qua chuẩn OpenAI-compatible (`/v1/chat/completions`) kèm `temperature` thấp (0.1 - 0.2) và timeout dài (1200s).
  - Bắt buộc ghi lại và kiểm tra `usage` tokens (`prompt_tokens`, `completion_tokens`, `reasoning_tokens`) vào file log độc lập để chứng minh tiến trình thực sự chạy và tiêu hao quota.
