---
name: softfac-remediation-discipline
description: Protocol for zero-plan batch remediation in SoftFac v2.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, agy, remediation, builder, reviewer]
---

# SoftFac v2 Batch Remediation & Proxy Invariants

Quy tắc cốt lõi về kỷ luật điều phối sửa lỗi (Remediation Discipline) và bất biến cấu hình kết nối proxy cho AGY Builder trong SoftFac v2.

## 1. Zero-Plan Direct Remediation Protocol (Cấm Lập Kế Hoạch Khi Sửa Lỗi)

- **Nguyên tắc tối thượng**: Khi Sol Reviewer từ chối (REJECT) và trả về danh sách findings, Orchestrator giao nhiệm vụ cho Builder để **sửa mã nguồn trực tiếp và kiểm thử**, TUYỆT ĐỐI KHÔNG yêu cầu hoặc cho phép Builder lập kế hoạch (plan/analysis).
- **Cấm chia lượt (Single Run Enforcement)**:
  - Cấm mô hình 2 lượt: Lượt 1 phân tích/lên kế hoạch -> Lượt 2 mới thực thi sửa code.
  - Phải dùng đúng **1 prompt thi công duy nhất**: Yêu cầu Builder đọc findings, chỉnh sửa thẳng vào các tệp nguồn liên quan, chạy test suites, và hoàn tất trong một lần chạy.
- **Cấu trúc prompt remediation chuẩn**:
  1. **Chỉ thị dứt khoát**: `EDIT FILES DIRECTLY AND COMMIT/FINISH IN THIS SINGLE RUN. DO NOT PLAN. DO NOT ANALYZE.`
  2. **Danh sách findings từ Sol**: Trích xuất nguyên văn hoặc tóm tắt kỹ thuật các điểm Sol yêu cầu sửa.
  3. **Checklist hành động cụ thể**: Liệt kê rõ từng file cần sửa, hàm cần sửa, logic cần đổi (ví dụ: thay substring match bằng exact match, thêm replay guard, bổ sung test).
  4. **Tiêu chuẩn nghiệm thu**: Nêu rõ lệnh kiểm thử cần chạy trước khi hoàn thành (unit tests 100% pass, invariants pass, oracle controls pass).

## 2. Bất Biến Cấu Hình Proxy Pool Antigravity Cho AGY CLI

Để tránh lỗi cạn kiệt hạn ngạch cá nhân (`RESOURCE_EXHAUSTED (code 429)`) khi gọi `agy.exe`, kết nối proxy pool là bất biến hệ thống không được vi phạm:

- **Địa chỉ Proxy**: Bắt buộc trỏ vào proxy pool Antigravity local tại `http://127.0.0.1:8045`.
- **Cấu hình `~/.gemini/antigravity-cli/settings.json`**:
  ```json
  {
    "model": "Gemini 3.8 Flash (High)",
    "modelProvider": "gemini",
    "trustedWorkspaces": [
      "C:\\Users\\HH18"
    ]
  }
  ```
- **Biến môi trường**:
  ```bash
  export GOOGLE_GEMINI_BASE_URL="http://127.0.0.1:8045"
  export GEMINI_API_KEY="..."
  ```
- **Quy tắc bất biến**: TUYỆT ĐỐI CẤM gỡ bỏ hoặc thay đổi cấu hình proxy pool trên về mặc định của Google API nếu không có yêu cầu trực tiếp từ người dùng. Mọi lệnh chạy AGY Builder phải sử dụng cấu hình proxy này.
