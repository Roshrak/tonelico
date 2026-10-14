---
name: softfac-windows-operations-runtime
description: Use when running SoftFac v2 Windows drivers.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [coding, builder, agy, astra, sol, softfac, windows, runtime]
---

# SoftFac v2 Windows Runtime & Driver Invariants

### 1. Quy Chuẩn Khởi Chạy Sol Reviewer & Kiểm Tra Tiến Trình Thật
- **Driver Script Invocation**: Sử dụng `f.CodexRoleClient().call(role='reviewer', model='gpt-6-sol', reasoning_effort='high')`. Tuyệt đối không gọi `f.run_reviewer()` vì hàm này không tồn tại trong thư viện `hermes_factory_v2`.
- **Phân Biệt Codex CLI vs Codex App Daemon**:
  - `codex.exe` thường có tiến trình chạy nền của ứng dụng desktop (`app-server`).
  - Để kiểm tra Sol thật đang review hay không, phải kiểm tra CommandLine qua PowerShell:
    ```powershell
    Get-CimInstance Win32_Process -Filter 'Name = "codex.exe"' | Select-Object ProcessId, CommandLine
    ```
  - Tiến trình thật phải chứa cờ `exec --ephemeral -m gpt-6-sol -c model_reasoning_effort="high"`.

### 2. Quy Chuẩn Khởi Chạy AGY Builder Qua Antigravity Proxy Pool
- **Đường Dẫn Binary**: `C:\Users\HH18\AppData\Local\agy\bin\agy.exe`.
- **Cờ Thực Thi Non-Interactive**: Dùng `--model gemini-3.8-flash-high --dangerously-skip-permissions -p "<prompt>"`. Không truyền cờ `-y` vì CLI Go không hỗ trợ cờ `-y` độc lập.
- **Biến Môi Trường Kết Nối Proxy Pool**:
  - `GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:8045`
  - `GEMINI_API_KEY=<key lấy từ gui_config.json>`
  - `GEMINI_MODEL=gemini-3.8-flash-high`

### 3. Nguyên Tắc Thẩm Định Thực Nghiệm Của Sol (Zero Mock / Zero Hash Simulation)
- Khi Sol Reviewer yêu cầu kiểm thử paired empirical trial:
  - CẤM dùng hàm băm (hash) hoặc random để tạo số liệu giả/mô phỏng kết quả.
  - Bắt buộc phải gắn với code thực thi thật (`BaselineRunner`, `ModelAdapter`, `EscalationDecisionTable`).
  - Đo đạc thời gian p50/p95 thật trên các task mẫu và tính toán khoảng tin cậy (Wilson / bootstrap CI) theo đúng chuẩn Section 8.
- Khi làm kiểm thử OCR ablation:
  - Chạy live engine trên host (ví dụ WinRT `Windows.Media.Ocr`).
  - Các engine không có sẵn phải minh bạch ghi rõ trạng thái `UNAVAILABLE`, không giả lập kết quả.
