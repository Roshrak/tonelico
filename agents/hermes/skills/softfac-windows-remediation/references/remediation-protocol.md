# SoftFac v2 Single-Turn Batch Remediation Protocol

Quy chuẩn điều phối khắc phục lỗi (Remediation) khi Sol Reviewer trả về `REJECTED` trong pipeline SoftFac v2.

## 1. Nguyên Tắc Cốt Lõi: Single-Turn Remediation (Tuyệt đối không chia 2 lượt)
- **Cấm chia nhỏ quy trình thành Plan -> Execute**:
  - Khi Reviewer trả về danh sách findings, Orchestrator **tuyệt đối không** yêu cầu Builder lập kế hoạch phân tích rồi mới chạy lượt 2 để sửa code.
  - Phải gửi **đúng 1 prompt thi công trực tiếp duy nhất (Single-Turn Action)**.
- **Yêu cầu bắt buộc trong prompt của Builder**:
  1. Đọc và khắc phục toàn bộ 100% findings của Reviewer trong 1 lượt chạy.
  2. Sửa trực tiếp vào mã nguồn, cấm chỉ đưa ra phân tích lý thuyết.
  3. Tự động chạy toàn bộ các bộ kiểm thử hồi quy (unit tests, contract invariants, oracle controls).
  4. Tạo commit git chính thức với message chuẩn hóa mô tả chi tiết các findings đã sửa trước khi kết thúc tiến trình.

## 2. Bất Biến Kết Nối Antigravity Proxy Pool Cho AGY CLI
- `agy CLI` được cấu hình gắn chặt vào Antigravity proxy pool cục bộ (`http://127.0.0.1:8045`).
- File `~/.gemini/antigravity-cli/settings.json` phải luôn giữ:
  ```json
  {
    "model": "Gemini 3.8 Flash (High)",
    "modelProvider": "gemini",
    "trustedWorkspaces": ["C:\\Users\\HH18"]
  }
  ```
- Biến môi trường hệ thống: `GOOGLE_GEMINI_BASE_URL="http://127.0.0.1:8045"`.
- **TUYỆT ĐỐI CẤM SỬA, GỠ BỎ HOẶC QUAY LẠI OAUTH CÁ NHÂN**: Khi gặp 429 quota hoặc lỗi kết nối, không được tự ý đổi endpoint hay revert về OAuth cá nhân vì proxy pool chịu trách nhiệm tự động xoay tài khoản và model mapping.

## 3. Quy Trình Vận Hành Của Orchestrator
1. **Tổng hợp Findings**: Thu thập toàn bộ danh sách finding từ tệp JSON kết quả của Sol Reviewer.
2. **Khởi tạo Prompt Thi Công Trực Tiếp**: Trình bày rõ ràng từng finding, file bị ảnh hưởng và giải pháp kỹ thuật cụ thể (kèm cờ cấm plan/analyze).
3. **Kích hoạt Builder**: Khởi chạy `agy.exe` (hoặc `codex.exe`) trong chế độ background với prompt thi công trực tiếp.
4. **Giám sát Ngầm**: Theo dõi PID và log ngầm (im lặng, không xuất output khi tiến trình đang chạy bình thường theo quy tắc heartbeat).
5. **Kiểm Tra & Chuyển Giao**: Ngay khi Builder hoàn tất commit và kiểm thử pass 100%, Orchestrator xác minh workspace clean và khởi chạy ngay lượt Re-Review với Sol Reviewer.
