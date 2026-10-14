---
name: antigravity-agy-proxy-ops
description: Use when connecting AGY CLI to Antigravity proxy pool.
version: 1.0.0
---

# AGY CLI & Antigravity Proxy Pool Operations

Hướng dẫn cấu hình, định tuyến model và xử lý lỗi quota khi kết nối `agy` CLI với proxy pool của Antigravity Manager (`antigravity-tools.exe`).

## 1. Kiến trúc kết nối & Cơ chế xác thực của AGY

AGY CLI (`agy.exe`) hỗ trợ 2 chế độ xác thực độc lập:
1. **OAuth cá nhân (Mặc định):** Đọc token từ `~/.gemini/oauth_creds.json` và gọi trực tiếp `cloudcode-pa.googleapis.com`. Ở chế độ này, AGY **bỏ qua hoàn toàn** `GEMINI_API_KEY` và `GOOGLE_GEMINI_BASE_URL`. Nếu tài khoản cá nhân hết quota, AGY sẽ bị lỗi:
   `RESOURCE_EXHAUSTED (code 429): Individual quota reached. Resets in ...`
2. **API Key & Custom Base URL (Kết nối Pool):** Để buộc AGY kết nối qua proxy pool nội bộ, **bắt buộc** phải cấu hình trong `~/.gemini/antigravity-cli/settings.json`:
   ```json
   {
     "model": "Gemini 3.8 Flash (High)",
     "modelProvider": "gemini",
     "trustedWorkspaces": [
       "C:\\Users\\HH18"
     ]
   }
   ```
   **Bắt buộc:** Phải có trường `"modelProvider": "gemini"`. Nếu thiếu trường này, CLI sẽ tự động fallback về OAuth cá nhân.

## 2. Biến môi trường kết nối Proxy Pool & Bất Biến Cấu Hình

Cần export 2 biến môi trường trước khi chạy AGY:
```bash
export GOOGLE_GEMINI_BASE_URL="http://127.0.0.1:8045"
export GEMINI_API_KEY="<proxy_api_key_from_gui_config>"
```
*Lưu ý: API Key của Antigravity Tools lấy tự động từ `~/.antigravity_tools/gui_config.json` tại trường `proxy.api_key`.*

### Bất biến nghiêm ngặt về Proxy Pool & Phân vai SoftFac:
1. **Cấm gỡ bỏ hoặc sửa đổi cấu hình proxy pool:**
   - Cấu hình `"modelProvider": "gemini"` trong `~/.gemini/antigravity-cli/settings.json` là bất biến khi người dùng đã kết nối pool. Tuyệt đối không xóa trường này để fallback về Google Auth nếu chưa có lệnh rõ ràng từ người dùng.
2. **Không tự sửa code thay Builder & Không tự gọi Sol liên tục:**
   - Trong pipeline SoftFac v2, Orchestrator tuyệt đối không tự code sửa lỗi thay AGY Builder. Khi Sol đưa ra findings, ném đúng 1 prompt chỉ thị sửa mã nguồn cho AGY thực thi trong một lượt (one-shot batch).
   - Tuyệt đối cấm tự ý gọi Sol review vòng lặp làm thất thoát quota. Mọi vướng mắc, lỗi timeout hoặc nghẽn quota của AGY phải báo cáo ngay lập tức cho người dùng.

## 3. Quy tắc đặt tên Model & Pitfalls

- **Yêu cầu Reasoning Effort cho Gemini Flash:**
  Khi sử dụng dòng Flash (như `gemini-3.8-flash`, `gemini-3.7-flash`), AGY CLI yêu cầu chỉ định rõ mức độ reasoning effort (`low`, `medium`, `high`). Nếu chỉ truyền `--model gemini-3.8-flash` mà không có `--effort`, CLI sẽ báo lỗi:
  `error: invalid model selection: --model gemini-3.8-flash requires --effort (available: low, medium, high)`
  
  **Cách gọi đúng:**
  - Dùng tên đầy đủ: `agy --model gemini-3.8-flash-high -p "..."`
  - Hoặc kèm flag effort: `agy --model gemini-3.8-flash --effort high -p "..."`
  - Hoặc cấu hình mặc định trong `settings.json`: `"model": "Gemini 3.8 Flash (High)"`

## 4. Phân biệt Short Probe vs Multi-Turn Execution Pool Quota (Pitfall quan trọng)

- **Cơ chế tải của AGY Multi-Turn:**
  - Khi chạy một lệnh test ngắn đơn lẻ (`1+1=?`), request chỉ gọi 1 lượt suy luận nhẹ, thường thành công ngay nếu còn ít nhất một account có quota ngắn hạn.
  - Khi khởi chạy `agy` trong phiên làm việc thực tế (`-p prompt`), AGY gửi đồng thời các request phụ ngầm (như `conversation_title` generation, schema validation, streaming chunks).
  - Nếu tất cả tài khoản trong proxy pool đã chạm trần hạn ngạch streaming (`streamGenerateContent`), AGY CLI sẽ nhận lỗi:
    `Error 429, Message: All accounts exhausted. Last error: HTTP 429: Resource has been exhausted (e.g. check quota)`
    và tiến trình sẽ tự động exit âm thầm ngay sau bước đọc file hoặc khởi tạo ngữ cảnh ban đầu.
- **Quy tắc điều phối khi gặp 429:**
  - Không nhầm lẫn giữa việc test probe ngắn (`1+1=?`) pass với việc pool đã sẵn sàng cho một phiên multi-turn dài.
  - Phải kiểm tra log chi tiết tại `~/.gemini/antigravity-cli/cli.log`. Nếu xuất hiện `All accounts exhausted`, dừng việc tái khởi chạy liên tục; báo cáo minh bạch cho người dùng bổ sung/xoay vòng account hoặc đợi quota reset.

## 5. Cấu hình Custom Mapping trong Antigravity Tools

Upstream Google Cloud Code PA (`cloudcode-pa.googleapis.com`) của các tài khoản trong pool không cấp quota cho model ID gốc dạng `gemini-3.8-flash` (gây lỗi 404 hoặc 429 *"All accounts exhausted"* và làm AGY CLI loading vô hạn).

Cần cấu hình `custom_mapping` trong `~/.antigravity_tools/gui_config.json` hoặc qua GUI (Settings -> Model Router):
```json
{
  "proxy": {
    "custom_mapping": {
      "gemini-3.8-flash": "gemini-3.8-flash-high",
      "gemini-3.7-flash": "gemini-3.7-flash-high",
      "gemini-3.6-flash": "gemini-3.6-flash-high"
    }
  }
}
```
Sau khi sửa cấu hình, khởi động lại tiến trình `antigravity-tools.exe` để proxy nạp bảng routing vào bộ nhớ.

## 5. Quy trình chẩn đoán nhanh khi AGY treo hoặc loading mãi

1. **Kiểm tra nhật ký proxy pool:**
   Truy vấn SQLite `~/.antigravity_tools/proxy_logs.db` bảng `request_logs` để xem request từ AGY có đến proxy không:
   - Nếu không có log nào: AGY đang chạy bằng OAuth cá nhân (thiếu `"modelProvider": "gemini"` trong `settings.json`).
   - Nếu có log trả về HTTP 429 / 404: Upstream không nhận diện model, cần thêm `custom_mapping` sang variant `-high` hoặc `-low`.
2. **Kiểm tra phản hồi upstream qua curl / script:**
   Gửi trực tiếp POST request tới `http://127.0.0.1:8045/v1beta/models/<model>:streamGenerateContent?alt=sse` để xác định chính xác tài khoản nào trong pool đang handle và mã lỗi upstream trả về.
