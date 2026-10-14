---
name: softfac-quota-management
description: Use when handling quota exhaustion or 429 in SoftFac v2.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, quota, 429, agy, gemini, resource_exhausted, orchestrator]
---

# SoftFac v2 Quota Exhaustion & Resource Management

Hướng dẫn quy chuẩn xử lý tình huống tiến trình Builder (`agy.exe` / `gemini-3.8-flash-high`) hoặc Reviewer (`codex.exe` / `gpt-6-sol`) bị dừng đột ngột do cạn kiệt quota API (`RESOURCE_EXHAUSTED` / HTTP 429).

## 1. Cơ Chế Phát Hiện Quota Exhaustion
Khi tiến trình `agy.exe` hoặc `codex.exe` exit đột ngột với mã lỗi hoặc không sinh code mới:
- Kiểm tra ngay cuối log file chạy của tiến trình (`tail -n 35 <proc_log>`) và log của CLI daemon (`~/.gemini/antigravity-cli/cli.log`).
- Các dấu hiệu đặc trưng:
  - `RESOURCE_EXHAUSTED (code 429): Individual quota reached.`
  - `Please upgrade your subscription to increase your limits. Resets in <duration>.`
  - Chuỗi retry backoff thất bại liên tục (attempt 1 -> attempt 8 failed).

## 2. Quy Trình Ứng Phó Chuẩn Của Orchestrator
1. **Bảo tồn trạng thái Workspace:**
   - Kiểm tra `git status -s` để xác nhận thư mục làm việc không bị bẩn do quá trình sửa dở dang.
   - Nếu có file dở dang chưa hoàn thiện, dọn dẹp hoặc stash để đưa HEAD về commit hoàn chỉnh gần nhất đã được kiểm thử.
2. **Lưu trữ prompt và ngữ cảnh:**
   - Lưu trữ toàn bộ prompt remediation/task chưa hoàn thành vào tệp tạm (`prepare_agy_rX_prompt.txt`) để sẵn sàng nạp lại khi quota hồi phục.
3. **Bảo toàn nguyên tắc SoftFac v2 (Tuyệt đối không code thay Builder):**
   - Orchestrator tuyệt đối không được tự ý viết code sửa lỗi thay cho Builder khi Builder hết quota.
   - Không chuyển giao sang Sol Reviewer khi Builder chưa hoàn thành batch remediation và chưa tạo commit mới.
4. **Báo cáo và lập kế hoạch khôi phục:**
   - Trích xuất chính xác thời gian reset hạn ngạch (`Resets in XhYm`) từ log để báo cáo cho người dùng.
   - Đề xuất tạo hẹn giờ / lịch tự động tiếp tục khi quota sẵn sàng.
