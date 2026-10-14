# Antigravity Proxy Pool Quirk & Streaming Exhaustion

Ghi chép chuyên sâu về cơ chế hoạt động của Antigravity Proxy Pool (`http://127.0.0.1:8045`) và sự phân tách hạn ngạch giữa các endpoint.

## 1. Hiện Tượng Phân Tách Endpoint (Endpoint vs CLI Discrepancy)

- **Endpoint tương thích OpenAI (`/v1/chat/completions`)**:
  - Các request ngắn hạn (như lệnh probe `1+1=?`, test ping) thường được proxy định tuyến đến một tài khoản bất kỳ còn một ít request quota.
  - Phản hồi trả về `HTTP 200 OK` ngay lập tức, dễ gây hiểu lầm là toàn bộ pool đã sẵn sàng.
- **Tiến trình tương tác CLI (`agy.exe`)**:
  - `agy.exe` là agent runtime thực thi nhiều lượt (multi-turn), đồng thời phát nhiều loại request song song:
    1. Endpoint Google GenAI: `v1beta/models/...:streamGenerateContent?alt=sse`.
    2. Endpoint tạo tiêu đề hội thoại ngầm: `conversation_title.go`.
    3. Endpoint xác nhận công cụ: `tool_confirmation_manager.go`.
  - Khi quota của model streaming trên các tài khoản Google bị cạn, CLI sẽ ghi nhận:
    `Error 429, Message: All accounts exhausted. Last error: HTTP 429: Resource has been exhausted.`
  - Hậu quả: `agy.exe` chỉ chạy được 2-4 tool steps (`ViewFile`) rồi tự động ngắt tiến trình mà chưa thực hiện được các thay đổi vào mã nguồn.

## 2. Quy Tắc Xác Minh Liveness Chuẩn Cho Orchestrator

1. **Không dùng probe đơn lẻ làm căn cứ duy nhất**:
   - Một lệnh `agy -p "1+1=?"` hoặc curl thành công không đồng nghĩa với việc phiên chạy dài của Builder sẽ không bị 429.
2. **Kiểm tra tiến trình tương tác sống thực tế**:
   - Sau khi khởi chạy `agy.exe` cho một task lớn, cần theo dõi `tasklist | grep -i agy` sau tối thiểu 15-30 giây.
   - Nếu tiến trình biến mất khỏi danh sách tiến trình, kiểm tra ngay đuôi `~/.gemini/antigravity-cli/cli.log` để xem lỗi 429 streaming hoặc title generation.
