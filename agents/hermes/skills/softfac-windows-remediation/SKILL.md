---
name: softfac-windows-remediation
description: Single-turn batch remediation protocol for SoftFac Builder.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, builder, remediation, sol, batch, windows]
---

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

## 2. Quy Trình Vận Hành Của Orchestrator
1. **Tổng hợp Findings**: Thu thập toàn bộ danh sách finding từ tệp JSON kết quả của Sol Reviewer.
2. **Khởi tạo Prompt Thi Công**: Trình bày rõ ràng từng finding, file bị ảnh hưởng và giải pháp kỹ thuật cụ thể.
3. **Kích hoạt Builder**: Khởi chạy `agy.exe` (hoặc `codex.exe`) với prompt thi công trực tiếp.
   - *Lưu ý về Quota:* Trước khi kích hoạt, phân biệt giữa test probe ngắn và tải multi-turn thực tế. Nếu `cli.log` báo `All accounts exhausted`, không spam khởi chạy lại mà yêu cầu nạp thêm tài khoản vào proxy pool.
4. **Giám sát Ngầm**: Theo dõi PID và log ngầm (im lặng, không spam thông báo khi tiến trình đang chạy bình thường).
5. **Kiểm Tra & Chuyển Giao**: Ngay khi Builder hoàn tất commit và kiểm thử pass 100%, Orchestrator xác minh workspace clean và khởi chạy ngay lượt Re-Review với Sol Reviewer.
