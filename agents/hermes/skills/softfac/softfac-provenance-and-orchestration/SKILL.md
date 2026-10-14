---
name: softfac-provenance-and-orchestration
description: Use when orchestrating SoftFac v2 loops with AGY and Sol.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [coding, builder, agy, astra, sol, softfac, windows, provenance]
---

# SoftFac v2 Provenance & Advanced Orchestration Rules

Sổ tay kiến trúc và quy chế điều phối chuẩn mực cho Hermes Orchestrator khi dẫn dắt AGY Builder (`gemini-3.8-flash-high`) và Sol Reviewer (`gpt-6-sol`, reasoning: `high`).

---

## 1. Mô Hình Tham Chiếu Provenance Bất Biến (Chống Vòng LẶp Tự Tham Chiếu)
- **Bản chất vấn đề**: Một Git commit **không thể chứa chính SHA của bản thân nó trong nội dung file** (vì sửa file sẽ đổi hash tree → đổi SHA commit).
- **Quy tắc 3 cấp độ commit bắt buộc phân định rạch ròi**:
  1. `Historical Execution Provenance`: Commit gốc chạy benchmark thực tế trong quá khứ (ví dụ: `2bc166e2...`).
  2. `Remediation / Fixed-Runner Code Commit`: Commit sửa code cố định (ví dụ: `47974ad...`). Cả header và các đoạn trích dẫn phải dùng chung 1 SHA đồng nhất, không được lệch dòng.
  3. `Attestation / Review Commit`: Commit chứa tài liệu nghiệm thu / review candidate trên nhánh git.
- **Kiểm tra SHA target trong test**: Phải đóng băng chuỗi 40-hex SHA bất biến (`git cat-file -p <full-sha>:<path>`), cấm dùng tham chiếu mutable như `'HEAD'` hay `'main'` để tránh pass giả mạo trên working tree bẩn.

---

## 2. Thiết Kế Prompt Cho Builder (Chống Reactive Chắp Vá)
- **CẤM** ra lệnh kiểu hẹp: `"Fix the exact findings raised by Sol Reviewer below in ONE turn directly"`. Lệnh này khiến Builder chỉ chắp vá câu chữ hoặc làm literal test.
- **BẮT BUỘC** yêu cầu Builder:
  1. Lập Finding Matrix: mapping root cause → affected code path → required invariant → adversarial negative tests.
  2. Rà soát toàn diện các trường hợp lân cận (adjacent cases) trong cùng họ invariant (ví dụ: nếu cấm đoán mò `activate`, phải rà soát tất cả `focus`, `scroll`, `drag`, `set_value`, arguments defaults).
  3. Validate raw input trước khi normalize; fail-closed trước khi chạm tới dispatch.
  4. Giữ nguyên trạng thái bằng chứng thực nghiệm: cấm tự ý sửa số liệu thống kê hoặc ghi `RETAIN & PROMOTE` khi chưa chạy xong thực nghiệm paired A/B hợp lệ. Trạng thái đúng là `IMPLEMENTED — PROMOTION EVIDENCE PENDING FRESH PAIRED TRIAL`.

---

## 3. Phân Định Vai Trò & Chu Kỳ Điều Phối (Orchestration Cycle)
- **AGY Builder**: Viết/sửa code, cập nhật schema, viết test. **CẤM AGY commit**.
- **Hermes Orchestrator**:
  - Không viết code thay Builder.
  - Chờ AGY thoát hoàn toàn (`tasklist` sạch bóng `agy.exe`).
  - Chạy độc lập toàn bộ test suite (`python -m unittest discover`, `invariants`, `oracle-controls`).
  - Tạo Subject Code Commit độc quyền.
  - (Nếu cần A/B): Chạy Arm A (baseline) & Arm B (projected) từ cùng Subject Commit để sinh metrics thô.
  - Kích hoạt Sol Reviewer và chờ kết quả.
  - Không commit các file tạm hay thư mục log `evidence_rounds_*/`.

---

## 4. Quản Lý Tiến Trình & Timeout Windows
- Khi quét tiến trình trên Windows bằng `psutil.process_iter`, số lượng process lớn (400+) có thể mất 3-5 giây.
- Vòng lặp monitor ancestry bắt buộc phải kiểm tra cờ ngắt sớm:
  ```python
  if self._stop_event.is_set():
      break
  ```
  bên trong vòng lặp `for proc in psutil.process_iter(...)`.
- Đặt thread join timeout tối thiểu `5.0s` thay vì `2.0s` để tránh văng lỗi fail-closed giả mạo trên hệ thống bận.
