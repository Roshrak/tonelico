---
name: softfac-windows-milestone-review
description: Use when conducting SoftFac milestone reviews on Windows.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, review, sol, agy, milestone, windows]
---

# SoftFac v2 Windows Milestone Review & Remediation Protocol

### 1. PHÂN ĐỊNH RẠCH RÒI 2 CHẾ ĐỘ SOL REVIEW

Trong quy trình SoftFac v2 trên Windows, Sol Reviewer (`codex.exe`, `gpt-6-sol`, reasoning `high`) vận hành theo hai chế độ thẩm định độc lập:

#### A. Full Milestone Review (Round 01 - Khi bắt đầu Milestone mới)
- **Kích hoạt**: Bắt buộc khi chuyển giao từ milestone cũ ($M_{n-1}$) sang milestone mới ($M_n$) sau khi $M_{n-1}$ đã đạt 100% `APPROVE`.
- **Yêu cầu Prompt**: 
  - Khẳng định rõ đây là **FULL MILESTONE REVIEW (Round 01)** của Milestone $M_n$.
  - Yêu cầu Sol quét toàn diện và độc lập từ đầu toàn bộ phạm vi của milestone:
    * Architecture Invariants: Kiểm tra Layer A Rust (`crates/`) nguyên vẹn 0 dòng diff; Section 4 Identity Authority.
    * Core Logic: State machine, contract, fail-closed action blocking, model ambiguity override interception, equivalence bridge verification.
    * Evaluation Gates: Đánh giá chi tiết từng gate (từ Gate 1 đến Gate 7).
    * Schemas & Fixtures: Draft-2020-12 schema validation, kiểm tra tất cả fixture sets và negative tests.
    * Empirical Evidence: Thẩm định tính xác thực của benchmark (phải chạy live inference thực tế, cấm mock/sleep gán xác suất tĩnh).
    * Provenance: Cơ chế Git provenance phi đệ quy (`git_source_tree_and_base_commit`), tính nhất quán giữa candidate commit, source tree hash và working tree cleanliness.
    * Test Suites: Cargo test (`cargo test -p agent-desktop-core`) và full Python suite.
    * Diff Hygiene: `git diff --check` (0 trailing whitespace).
  - **CẤM TUYỆT ĐỐI**: Không bao giờ gửi prompt findings-only review của milestone cũ hoặc chỉ trích xuất vài finding lẻ khi mở đầu milestone mới.

#### B. Findings-Only Review (Round 02+ - Vòng lặp Remediation)
- **Kích hoạt**: Chỉ áp dụng khi Sol Reviewer đã ra báo cáo Full Milestone Review (hoặc vòng trước) với phán quyết `REVISE` và có danh sách findings tồn đọng (`remaining_findings`).
- **Yêu cầu Prompt**:
  - Đối soát tập trung vào các findings còn mở (reopened) mà AGY Builder vừa remediation.
  - Kiểm tra candidate commit mới mang commit hash và source tree hash cập nhật.
  - Rà soát tính triệt để của giải pháp khắc phục cho đến khi tất cả findings chuyển sang trạng thái `RESOLVED` / `APPROVED`.

---

### 2. MÔI TRƯỜNG VÀ CÔNG CỤ THỰC THI CHUẨN

#### A. Môi trường Python Test Runner & Harness
- Khi chạy unit test (`test_*.py`), test discovery (`python -m unittest discover ...`), hoặc empirical evaluation harness (`run_m*_empirical_trial.py`) trong `agent-desktop-win`:
  - **Bắt buộc dùng Python venv đầy đủ packages**:  
    `C:/Users/HH18/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe`
  - **Bắt buộc gán PYTHONPATH**:  
    `PYTHONPATH=tools/cu-amplifier`
  - *Lý do*: Python mặc định ngoài PATH có thể thiếu các thư viện phụ thuộc (`jsonschema`, `PIL`, `psutil`) hoặc gây lỗi crash/segfault không mong muốn.

#### B. Vận hành Codex Sol Reviewer qua API Pool
- Lệnh gọi: `C:/Users/HH18/AppData/Local/hermes/bin/codex.cmd exec --sandbox danger-full-access <prompt>`
- Provider: `codex_local_access` trỏ vào `http://localhost:13844/v1` (`gpt-6-sol`).
- Bắt buộc chạy non-interactive qua script runner ra file log tạm.

#### C. Giám sát tiến trình không polling
- Sau khi khởi chạy AGY hoặc Sol chạy nền, theo dõi bằng duy nhất 1 lệnh ngầm:
  `powershell -NoProfile -Command "Wait-Process -Id <PID>"` với `background=true, notify=true`.
- Orchestrator nhả lượt ngay lập tức để hệ thống tự đánh thức khi tiến trình kết thúc.

---

### 3. KỶ LUẬT PHÂN VAI VÀ CHUYỂN TIẾP MILESTONE

1. **Hermes Orchestrator**:
   - Không tự sửa code thay Builder dù gặp bất kỳ lỗi nhỏ nào.
   - Chờ AGY Builder thoát hoàn toàn (`exit 0`).
   - Tự tay chạy lại nghiệm thu độc lập và thực hiện `git commit`.
   - Báo cáo kết quả luôn trích dẫn đầy đủ JSON verdict thực tế của Sol, không báo cáo suông.
2. **Tự động chuyển tiếp Milestone**:
   - Khi Sol Reviewer xác nhận `verdict: "APPROVE"` và `remaining_findings: []`, Orchestrator lập tức chuyển sang Milestone tiếp theo theo Astra Master Plan, kích hoạt Full Milestone Review (Round 01) cho milestone mới.
