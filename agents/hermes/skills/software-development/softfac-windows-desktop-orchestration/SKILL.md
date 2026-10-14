---
name: softfac-windows-desktop-orchestration
description: Run SoftFac v2 loops on Windows with AGY and Codex.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [coding, builder, agy, codex, sol, softfac, orchestrator, windows]
---

# SoftFac v2 Windows Desktop Orchestration

### QUY TẮC BẤT BIẾN TUYỆT ĐỐI CỦA HERMES ORCHESTRATOR:
0. **CẤM PROMPT BUILDER LẬP KẾ HOẠCH / PHÂN TÍCH 2 BƯỚC**:
   - Mọi prompt gửi cho AGY Builder PHẢI LÀ MỆNH LỆNH THI CÔNG TRỰC TIẾP (code, test, patch ngay lập tức trong 1 lượt duy nhất).
   - Tuyệt đối cấm Builder chia 2 lượt plan/code hay ngồi thảo luận kế hoạch rườm rà.
1. **TUYỆT ĐỐI KHÔNG TỰ SỬA CODE THAY BUILDER**:
   - Dù test fail, nôn nóng, hay gặp lỗi nhỏ, MỌI finding và lỗi test BẮT BUỘC PHẢI chuyển giao cho AGY Builder tự sửa 100%.
2. **PHÂN ĐỊNH VAI TRÒ BUILDER & ORCHESTRATOR**:
   - **AGY Builder**: Chỉ viết code, sửa lỗi và chạy test cục bộ; **TUYỆT ĐỐI CẤM AGY GIT COMMIT**.
   - **Hermes Orchestrator**: Giám sát tiến trình, tự chạy test suite nghiệm thu độc lập sau khi Builder thoát sạch, và **Hermes là bên duy nhất thực hiện Git commit**.
   - Tuyệt đối không gọi Sol Reviewer khi AGY chưa build xong và chưa clean exit khỏi `tasklist`.
3. **TUYỆT ĐỐI KHÔNG TỰ Ý TẮT HOẶC HỦY TIẾN TRÌNH SOL REVIEWER**:
   - Khi `codex.exe` đang thẩm định, cấm ngắt giữa chừng để bảo toàn quota và kết quả đánh giá.
4. **NGUYÊN TẮC GHI BẰNG CHỨNG THỰC TẾ**:
   - Chỉ cho qua step mới khi review finding được Sol APPROVE 100%.
   - Khi báo cáo phải trích xuất trực tiếp log JSON approve thực tế của Sol làm bằng chứng, cấm nói suông.
5. **ĐIỀU PHỐI TIẾN TRÌNH NỀN & GIÁM SÁT DESKTOP (BẮT BUỘC NOTIFY=TRUE)**:
   - Mỗi khi kích hoạt AGY Builder hoặc Codex Reviewer chạy ngầm, BẮT BUỘC gọi tool `terminal` với cả hai cờ: `background=True` VÀ `notify=True`.
   - Nếu tiến trình được chạy ngoài hoặc đã có PID cụ thể: chạy ngay lệnh giám sát Kernel:
     `terminal(command='powershell -NoProfile -Command "Wait-Process -Id <PID>"', background=True, notify=True)`
   - Sau khi bật tiến trình, chỉ báo ngắn gọn PID và **YIELD TURN NGAY LẬP TỨC** để desktop ở trạng thái IDLE sẵn sàng nhận sự kiện đánh thức.

---

### QUY TRÌNH ĐIỀU PHỐI TỰ ĐỘNG 2 PHA:

#### Pha A — Khi AGY Builder kết thúc (Process finished):
1. Xác nhận sạch tiến trình: Chạy `tasklist | grep -i agy` đảm bảo AGY đã thoát hoàn toàn.
2. Tự tay Orchestrator chạy test suites độc lập (`python -m unittest discover ...`, invariants, oracle controls).
3. Nếu test fail: Không tự sửa code, tổng hợp lỗi tạo batch prompt thi công trực tiếp cho AGY chạy lại.
4. Nếu test PASS 100%: Kiểm tra `git status` / `git diff` và chính tay Hermes thực hiện Git commit.
5. Kích hoạt Sol Reviewer chạy ngầm (`background=True, notify=True`), báo PID và DỪNG LƯỢT chờ kết quả.

#### Pha B — Khi Codex Reviewer kết thúc (Process finished):
1. Kiểm tra sạch tiến trình: Chạy `tasklist | grep -i codex`.
2. Đọc file kết quả JSON (`sol_result.json`):
   - Nếu Sol APPROVE 100%: Xác nhận hoàn thành milestone, xuất trình log JSON gốc làm bằng chứng, sẵn sàng cho milestone tiếp theo.
   - Nếu Sol trả về REVISE / còn findings: Tổng hợp surviving findings thành mệnh lệnh thi công 1-shot trực tiếp ném lại cho AGY Builder sửa vòng tiếp theo (`background=True, notify=True`), báo PID và tiếp tục DỪNG LƯỢT.

---

### BẤT BIẾN MÔ HÌNH PROVENANCE & HARNESS EVALUATION:
1. **Phân tách 3 tầng Commit**:
   - `Historical execution commit`: SHA dữ liệu chạy quá khứ (bất biến).
   - `Fixed-runner / remediation commit`: SHA sửa code cố định.
   - `Review / attestation commit`: Commit nghiệm thu tài liệu trên nhánh main.
2. **Không để commit tài liệu tự tham chiếu vòng lặp**: Không bắt buộc file tài liệu phải chứa chính SHA của commit sinh ra nó.
3. **Fail-Closed Manifest Comparability**:
   - Trong các bộ harness so sánh A/B (như `paired_ab_harness.py`), so sánh cam kết phải bắt buộc field `runner_commit` rõ ràng; cấm fallback sang `runtime_commit` hay `head_commit`.
