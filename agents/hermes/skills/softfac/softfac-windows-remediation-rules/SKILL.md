---
name: softfac-windows-remediation-rules
description: Use when orchestrating SoftFac v2 remediation loops.
version: 1.0.0
---

# SoftFac v2 Remediation Discipline & Invariants

Quy chuẩn bất biến khi điều phối khắc phục lỗi (Remediation) giữa Sol Reviewer, AGY Builder và Hermes Orchestrator trên Windows.

## 1. Phân Định Quyền Hạn Nghiêm Ngặt
1. **Orchestrator tuyệt đối không được code thay Builder:**
   - Khi Sol Reviewer trả về finding `REJECTED`, Orchestrator tuyệt đối không tự sửa code, không vá missing imports, không can thiệp logic hay test file thay Builder dù gặp bất kỳ lý do gì.
   - MỌI finding, MỌI lỗi test BẮT BUỘC PHẢI đóng gói và chuyển giao bằng prompt cho AGY Builder tự sửa 100%.
   - Nếu tiến trình Builder gặp sự cố (timeout, lỗi CLI, nghẽn quota, crash), Orchestrator **bắt buộc phải báo cáo ngay lập tức cho người dùng**, không được âm thầm tự can thiệp mã nguồn.
2. **Orchestrator là bên duy nhất commit:**
   - Builder (`agy` / `codex`) chỉ thực hiện chỉnh sửa source code và chạy test trong workspace, CẤM AGY commit.
   - Sau khi AGY thoát sạch sẽ, Orchestrator độc lập chạy lại toàn bộ test suite (unittest, invariants, oracle-controls), xác nhận git status, thực hiện `git commit` chuẩn hóa (`fix(...)`) và bảo đảm đồng bộ sổ cái provenance (tree hash / manifest).
3. **Bảo tồn Quota & Quản lý Tiến Trình Sol Reviewer:**
   - TUYỆT ĐỐI KHÔNG tự ý tắt, hủy (`kill`), hay ngắt tiến trình Sol Reviewer (`codex.exe`) khi đang chạy thẩm định, tránh lãng phí context và quota.
   - TUYỆT ĐỐI KHÔNG gọi Sol Reviewer liên tục ("spam review") khi chưa có commit mới sinh ra từ lượt thi công thực tế của Builder.
   - Chỉ kích hoạt Sol sau khi AGY đã hoàn tất và test suite độc lập pass 100%.

## 2. Bất Biến Cấu Hình Antigravity Proxy Pool
- AGY CLI gắn chặt với proxy pool cục bộ (`http://127.0.0.1:8045`).
- File `~/.gemini/antigravity-cli/settings.json` phải luôn giữ:
  ```json
  {
    "model": "Gemini 3.8 Flash (High)",
    "modelProvider": "gemini",
    "trustedWorkspaces": ["C:\\Users\\HH18"]
  }
  ```
- Biến môi trường: `GOOGLE_GEMINI_BASE_URL="http://127.0.0.1:8045"`, `GEMINI_API_KEY` lấy từ `~/.antigravity_tools/gui_config.json`.
- **CẤM TỰ Ý SỬA HOẶC XÓA CẤU HÌNH POOL**: Tuyệt đối không tự xóa `modelProvider` để fallback về Google Auth nếu chưa có lệnh của người dùng.

## 3. Quy Trình Chuyển Giao 1-Shot Cho Builder
- Khi nhận findings từ Sol Reviewer:
  - Gửi **đúng 1 prompt thi công trực tiếp duy nhất (Single-Turn)**.
  - Cấm cho Builder lập kế hoạch phân tích rồi mới chạy lượt 2.
  - Yêu cầu Builder sửa trực tiếp vào mã nguồn và tự chạy kiểm thử hồi quy trước khi kết thúc.
