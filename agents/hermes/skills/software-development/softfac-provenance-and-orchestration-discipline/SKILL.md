---
name: softfac-provenance-and-orchestration-discipline
description: Use when managing SoftFac v2 provenance and audit evidence.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, orchestration, provenance, evidence, git, reviewer, builder]
---

# SoftFac v2 Provenance & Orchestration Discipline

Sổ tay quy chuẩn điều phối Orchestrator, kiến trúc phân định Git Provenance và thu thập chứng cứ audit trong SoftFac v2.

---

### 1. Kiến Trúc Phân Định Git Provenance (Tránh Lỗi Tự Tham Chiếu Vòng Lặp)

Trong các pipeline có kiểm soát chặt chẽ bằng hash/provenance (như Sol Reviewer audit `CU-F002`), **một Git commit không bao giờ có thể ghi chính SHA của bản thân nó vào file nội dung** (vì sửa file sẽ đổi git tree và tạo ra một SHA commit mới).

Do đó, Orchestrator phải luôn phân định rõ 3 tầng định danh độc lập:

1. **Historical Execution Provenance (Commit chạy benchmark/test gốc)**:
   - SHA của commit mà bộ dữ liệu gốc (run bundle, artifacts, episodes) được thực thi trong quá khứ.
   - Giữ nguyên trung thực, không được sửa đè thành commit hiện tại.
2. **Fixed-Runner / Remediation Code Commit (Commit sửa mã nguồn / runner)**:
   - SHA của commit chứa code sửa đổi, schema sửa đổi, logic fail-closed đã pass test suite.
   - Được trích dẫn thống nhất và đồng bộ 100% trong báo cáo (ví dụ: dòng header và dòng chi tiết trong `baseline-report.md` phải khớp tuyệt đối cùng 1 SHA).
3. **Attestation / Review Subject Commit**:
   - Commit sau cùng trên nhánh làm việc được chuyển giao cho Sol Reviewer thẩm định.
   - Thẩm định tính toàn vẹn thông qua các đối tượng Git raw blobs bất biến (`git cat-file -p <target_commit>:<path>`), cấm đọc mutable working tree files.

---

### 2. Kỷ Luật Thu Thập & Lưu Trữ Evidence (Logs, JSON Verdicts)

- Khi người dùng yêu cầu thu gom evidence hoặc qua các round thẩm định kéo dài, **toàn bộ log thật** (prompt, log raw của AGY CLI, driver log, token usage, và JSON verdict của Sol) phải được gom vào một thư mục bằng chứng riêng (ví dụ: `evidence_rounds_XX_YY/`).
- **Bất biến Git**: Thư mục bằng chứng audit phải được **giữ nguyên ở trạng thái untracked** (`.gitignore` hoặc không `git add`). TUYỆT ĐỐI KHÔNG commit cả thư mục log/evidence vào git tree của repository để tránh làm sai lệch git tree hash và vi phạm quy chuẩn release của dự án.
- Luôn tạo file mục lục tra cứu nhanh `INDEX_EVIDENCE.md` liệt kê rõ ràng tên file, kích thước, round và vai trò tương ứng để người dùng kiểm chứng ngay lập tức khi cần.

---

### 3. Quy Trình Orchestration Fail-Closed Trước Khi Chuyển Sang Sol Review

Không được chuyển sang Sol Review chỉ dựa trên việc Builder "sửa đúng literal theo câu chữ của Sol" mà Orchestrator phải tự kiểm tra các điều kiện tiên quyết:

1. **Kiểm tra tiến trình Builder**: Đảm bảo `agy.exe` đã thoát hoàn toàn (clean exit, không còn PID trong `tasklist`).
2. **Nghiệm thu độc lập**:
   - Chạy full unittest discovery (`python -m unittest discover -s ...`).
   - Chạy bộ invariants suite (INV-01 .. INV-06) phải 0 vi phạm.
   - Chạy adversarial false-positive controls (CTRL-01 .. CTRL-16) phải từ chối 100%.
3. **Kiểm tra tính bất biến của tham chiếu**:
   - Mọi hàm kiểm tra Git blob phải sử dụng full-SHA 40 ký tự đóng băng (`frozen 40-hex SHA`), cấm fallback về mutable ref như `'HEAD'`, `'main'`, short-SHA.
4. **Commit chính thức**: Chỉ Orchestrator mới được `git add` các file mã nguồn/tài liệu được chỉ định và thực hiện `git commit`. Builder tuyệt đối không được commit.
