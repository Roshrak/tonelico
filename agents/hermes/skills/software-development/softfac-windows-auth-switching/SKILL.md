---
name: softfac-windows-auth-switching
description: Switch AGY and Codex CLI between proxy and direct OAuth.
version: 1.1.0
---

# Switching AGY & Codex CLI Between Proxy Pool & Direct OAuth

Quy trình chuẩn hóa chuyển đổi cơ chế xác thực và môi trường chạy cho cả hai agent trong pipeline SoftFac v2 trên Windows (`agy.exe` cho Builder, `codex.exe` cho Sol Reviewer), tránh xung đột định tuyến hoặc rò rỉ cấu hình proxy.

## 1. Cơ chế hoạt động & Nguyên nhân xung đột

### AGY CLI (Builder - Gemini)
1. Nếu `settings.json` (`~/.gemini/antigravity-cli/settings.json`) có `"modelProvider": "gemini"` VÀ môi trường có `GOOGLE_GEMINI_BASE_URL`:
   - AGY định tuyến qua proxy cục bộ (`http://127.0.0.1:8045`).
2. Nếu KHÔNG có `"modelProvider": "gemini"`:
   - AGY tự động dùng Google Auth / OAuth trực tiếp (`cloudcode-pa.googleapis.com`), đọc token từ `~/.gemini/oauth_creds.json`.
   - **Pitfall:** Nếu biến môi trường `GOOGLE_GEMINI_BASE_URL` hoặc `GEMINI_API_KEY` vẫn tồn tại trong process cha/subshell, SDK nội bộ vẫn cố kết nối vào proxy pool dẫn đến lỗi 429 hoặc mismatch quota.

### Codex CLI (Sol Reviewer - GPT-6 Sol / GPT-5.6 Sol)
1. Nếu `~/.codex/config.toml` có `model_provider = "codex_local_access"` (hoặc block `[model_providers.codex_local_access]` trỏ tới `http://localhost:13844/v1`):
   - Codex CLI định tuyến mọi request tới API pool cục bộ trên cổng 13844 qua token API key trong `~/.codex/auth.json`.
2. Nếu gỡ bỏ `model_provider = "sol-proxy"`:
   - Codex CLI tự động chuyển về provider chuẩn `openai`, kết nối trực tiếp WebSocket tới `wss://chatgpt.com/backend-api/` thông qua phiên OAuth ChatGPT lưu trong `~/.codex/auth.json`.

## 2. Quy trình chuyển Codex CLI sang Direct OpenAI OAuth (ChatGPT)

Khi người dùng muốn đăng nhập trực tiếp tài khoản ChatGPT cá nhân để dùng `gpt-6-sol` hoặc `gpt-5.6-sol`:

1. **Làm sạch `~/.codex/config.toml`**:
   - Xóa dòng `model_provider = "sol-proxy"`.
   - Xóa toàn bộ block `[model_providers.sol-proxy]` trỏ tới `localhost:13844`.
   - Cấu hình model mặc định: `model = "gpt-6-sol"` (hoặc `gpt-5.6-sol`), `model_reasoning_effort = "high"`.
2. **Xác thực hoặc chuyển đổi tài khoản ChatGPT**:
   - Kiểm tra trạng thái hiện tại: `codex login status`.
   - Nếu cần đăng nhập tài khoản khác:
     ```bash
     codex logout
     codex login
     ```
     Lệnh sẽ khởi tạo server callback tại `http://localhost:1455` và mở trình duyệt để xác thực OAuth.
3. **Xác minh môi trường bằng `codex doctor`**:
   - `default model provider`: hiển thị `openai`.
   - `stored auth mode`: hiển thị `chatgpt`.
   - `websocket`: hiển thị `connected (HTTP 101 Switching Protocols)`.
4. **Kiểm tra probe thực tế**:
   Codex yêu cầu Git repository, chạy probe ngắn trong thư mục tạm:
   ```bash
   cd $(mktemp -d) && git init && codex exec 'echo 1'
   ```
   Đảm bảo output ghi nhận `provider: openai` và `model: gpt-6-sol`.

## 3. Quy trình cấu hình Codex CLI với API Pool (Cockpit / Sol Proxy)

1. Cập nhật `~/.codex/config.toml`:
   ```toml
   model = "gpt-6-sol"
   model_provider = "codex_local_access"

   [model_providers.codex_local_access]
   name = "Codex API Service"
   base_url = "http://localhost:13844/v1"
   wire_api = "responses"
   requires_openai_auth = false
   supports_websockets = false
   experimental_bearer_token = "agt_codex_N0ogpcmP85D728nGpWbVU5YRbdLpCtrA"
   ```
2. Cập nhật `~/.codex/auth.json`:
   ```json
   {
     "OPENAI_API_KEY": "agt_codex_N0ogpcmP85D728nGpWbVU5YRbdLpCtrA",
     "auth_mode": "apikey"
   }
   ```
3. Xác nhận trạng thái đăng nhập:
   `codex login status` hiển thị: `Logged in using an API key - agt_code***pCtrA`.

## 4. Quy trình chuyển sang Direct Google Auth (Không dùng Pool)

Khi người dùng chuyển sang Google Auth trực tiếp:
1. **Làm sạch `settings.json` (`~/.gemini/antigravity-cli/settings.json`)**:
   Xóa trường `"modelProvider": "gemini"`:
   ```json
   {
     "model": "Gemini 3.8 Flash (High)",
     "trustedWorkspaces": [
       "C:\\Users\\HH18"
     ]
   }
   ```
2. **Làm sạch môi trường khi spawn subprocess**:
   Trước khi gọi `subprocess.Popen` hoặc chạy script khởi chạy `agy.exe`, bắt buộc sanitize biến môi trường:
   ```python
   env = os.environ.copy()
   env.pop("GOOGLE_GEMINI_BASE_URL", None)
   env.pop("GEMINI_API_KEY", None)
   ```
3. **Phân biệt lệnh probe ngắn vs multi-turn session**:
   - `agy --model gemini-3.8-flash-high -p "1+1=?"` kiểm tra tính hợp lệ của token/auth.
   - Khi chạy multi-turn prompt sửa code, `agy` kích hoạt thêm background tasks (title generation, schema check). Đảm bảo tài khoản Google Auth đã sẵn sàng quota stream để không bị ngắt quãng giữa phiên.

## 5. Quy trình chuyển lại Proxy Pool

1. Cập nhật `settings.json` bổ sung `"modelProvider": "gemini"`.
2. Truyền lại biến môi trường `GOOGLE_GEMINI_BASE_URL="http://127.0.0.1:8045"` và `GEMINI_API_KEY`.
3. Kiểm tra nhật ký SQLite `~/.antigravity_tools/proxy_logs.db` để bảo đảm proxy đang phục vụ request bình thường.
