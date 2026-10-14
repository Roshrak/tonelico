---
name: softfac-autonomous-loop
description: Run SoftFac loops and Windows process tree containment.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, automation, orchestration, windows, process-management, job-object]
---

# SoftFac Autonomous Loop & Windows Process Containment

Quy chuẩn vận hành tự động hoá vòng lặp SoftFac v2 (Orchestrator) và cơ chế thu hồi tiến trình triệt để trên Windows.

## 1. Zero-Friction Autonomous Remediation Loop

- **Tự động chuyển giao (Zero Asking)**: Khi Sol Reviewer trả về `verdict: REVISE` kèm danh sách findings, Orchestrator **tuyệt đối không hỏi người dùng** ("bạn có muốn...", "có cần tôi làm tiếp không..."). Phải lập tức:
  1. Phân tích nguyên nhân gốc của các surviving findings.
  2. Tạo prompt 1-shot trực tiếp (batch remediation) cho Builder hoặc tự patch theo thẩm quyền nếu Builder gặp trục trặc quota.
  3. Chạy toàn bộ test suites, kiểm tra invariant và false-positive controls.
  4. Đồng bộ chính xác Git commit hash và tree hash lên manifest/report.
  5. Kích hoạt Sol Re-Review vòng kế tiếp ngay lập tức.
- **Heartbeat Directive**: Tuân thủ triệt để chỉ thị im lặng (`no output`) khi tiến trình nền (`agy.exe`, `codex.exe`) đang chạy để không gây nhiễu cho người dùng.

## 2. Event-Driven Orchestrator Awakening (PID Exit Triggers)

Thay vì polling thụ động theo chu kỳ (gây trễ và tốn turns), kích hoạt Orchestrator thức dậy ngay khi Worker (AGY/Codex) kết thúc theo các nguyên tắc bắt buộc sau:

### Quy Tắc Bắt Buộc Khi Khởi Động Background (`terminal`):
1. **BẮT BUỘC cờ `notify=True`**: Trong schema của tool `terminal`, tham số `notify` mặc định là `False`. Nếu chỉ truyền `background=True`, Hermes sẽ phân loại tiến trình vào chế độ **Silent Background Process** và **hoàn toàn không phát sinh sự kiện hoàn tất (`ProcessCompletionEvent`) khi tiến trình thoát**. Bắt buộc phải truyền `notify=True` (hoặc `notify_on_complete=True`) để Gateway/TUI/Desktop nhận được sự kiện thức dậy.
2. **Chế độ Non-Interactive / Auto-Approve**: Lệnh khởi chạy Builder trên Windows (`agy`, `codex`) bắt buộc phải có cờ không tương tác (ví dụ `-y`, `--yes` hoặc prompt thi công 1-shot trực tiếp), tuyệt đối không để Builder dừng chờ người dùng nhấn phím xác nhận trong terminal nền (gây deadlock treo ngầm).
3. **Bắt buộc Nhả Lượt Ngay Lập Tức (Yield Turn)**: Sau khi gọi `terminal(background=True, notify=True)` và nhận được `session_id`/`pid`:
   - Orchestrator chỉ báo cáo ngắn gọn PID và mục tiêu thi công.
   - **KẾT THÚC LƯỢT NGAY LẬP TỨC**. Tuyệt đối không gọi thêm bất kỳ tool nào, không in thêm câu hỏi. Session (Desktop Electron, TUI, CLI) cần trở về trạng thái `idle` thì bộ điều phối (`tui_gateway` / CLI idle poller) mới có thể claim lượt tự động khi tiến trình thoát.

### Mô hình A: In-Session Background Execution & PID Wait
*Khuyên dùng hàng đầu — áp dụng cho cả phiên Desktop (Electron), TUI, CLI và Telegram:*
- **Trường hợp 1 - Hermes tự khởi chạy Builder**:
  ```python
  terminal(
      command="agy --prompt 'Thi công Milestone 1 ngay lập tức...'",
      background=True,
      notify=True
  )
  ```
- **Trường hợp 2 - Giám sát PID có sẵn (Builder chạy từ ngoài hoặc có PID cụ thể)**:
  Hermes gọi lệnh chờ mức Windows NT Kernel (tiêu thụ 0% CPU):
  ```powershell
  powershell -NoProfile -Command "Wait-Process -Id <PID>"
  ```
  *(hoặc Win32 ctypes `WaitForSingleObject(hProcess, INFINITE)`).*
  Chạy với `background=True, notify=True`, sau đó nhả lượt ngay.
- **Cơ chế thức dậy tự động:**
  - **Trên Hermes Desktop (Electron) & TUI (`hermes --tui`)**: Daemon thread trong `tui_gateway` (`_notification_poller_scoped_loop`) bốc sự kiện từ `completion_queue`, gọi `_notif_submit` phát tín hiệu `message.start` qua WebSocket tới giao diện Electron, tự động tạo lượt chat mới và LLM lập tức nhảy vào làm Orchestrator.
  - **Trên CLI REPL (`hermes`, `hermes --cli`)**: Luồng `_tui_idle_tick()` (quét mỗi 100ms) gọi `_drain_process_notifications("cli-idle")`, nhét sự kiện vào `_pending_input` và tự động gọi `self.chat(...)`.
  - **Trên Gateway (Telegram/Discord)**: Gateway watcher phát hiện `session.exited` và tự động inject synthetic turn vào đúng phiên chat.

### Mô hình B: External Script Trigger (Khi Builder chạy từ script/batch riêng)
- **Bằng GUI Automation / WScript SendKeys**: Nếu Builder chạy từ file `.bat` ngoài và Hermes Desktop/CLI đang mở, cuối script Builder tự "đá" Hermes dậy:
  ```powershell
  $ws = New-Object -ComObject WScript.Shell
  if ($ws.AppActivate("Hermes")) {
      Start-Sleep -Milliseconds 400
      $ws.SendKeys("Builder PID đã chạy xong. Tiến hành vai trò Orchestrator ngay.~")
  }
  ```
- **Bằng HTTP Webhook (`hermes webhook`)**: Nếu Gateway đang chạy, cuối script bắn POST tới webhook route (`hermes webhook subscribe softfac-builder-done ...`), Hermes sẽ tự động spawn agent run xử lý Orchestrator.

### Mô hình C: Hermes CLI Slash Command `/loop`
- Nếu cần fallback kiểm tra định kỳ trong CLI:
  ```text
  /loop 15s Kiểm tra tasklist xem PID <PID> còn chạy không. Nếu còn thì im lặng. Nếu đã thoát thì /loop stop và bắt đầu khâu Orchestrator.
  ```

## 3. Kernel-Level Windows Job Object Containment (CU-F009 Pattern)

Khi quản lý vòng đời ứng dụng thử nghiệm, fixtures, hoặc các tiến trình tạo cây con/cháu tách rời (detached grandchildren):

- **Hạn chế của User-Space Polling**: Quét `psutil` hoặc `Win32_Process` theo chu kỳ (ví dụ 50ms) sẽ **thất bại 100%** khi tiến trình cha và tiến trình trung gian (intermediate launcher) thoát nhanh trước chu kỳ thăm dò. Tiến trình cháu bị mồ côi (orphaned) sẽ sống sót.
- **Giải pháp chuẩn Windows NT**: Sử dụng **Windows Kernel Job Object** với cờ `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)`:
  1. **Khởi tạo**: Tạo Job Object qua `kernel32.CreateJobObjectW` và thiết lập `SetInformationJobObject` với `JobObjectExtendedLimitInformation`.
  2. **Suspended-at-Creation Assignment**: Khi khởi chạy bất kỳ tiến trình nào (`subprocess.Popen`), truyền cờ `creationflags=CREATE_SUSPENDED (0x00000004)`.
  3. **Gán Job Object trước khi chạy**: Gọi `AssignProcessToJobObject(h_job, proc.handle)` và kiểm tra `IsProcessInJob`.
  4. **Resume Threads**: Sau khi đã gán vào Job Object thành công, giải phóng luồng chính qua `ResumeThread` (sử dụng `CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD)`).
  5. **Dọn dẹp triệt để**: Trong `cleanup_all()`, đóng handle Job Object (`CloseHandle(h_job)`). Windows NT kernel tự động quét sạch 100% tiến trình con, cháu, chắt mà không bỏ sót bất kỳ tiến trình nào.

## 4. Strict Provenance & Hash Synchronization (CU-F002 Pattern)

- **Tránh lỗi Sibling Commit**: Tuyệt đối không hardcode hash commit trước khi tạo commit hoặc commit sửa hash vào một commit riêng (tạo sibling commit).
- **Quy trình chuẩn**:
  1. Thực hiện mọi sửa đổi code và tài liệu phụ trợ.
  2. Chạy test suite xác nhận đạt 100%.
  3. Commit các thay đổi.
  4. Lấy hash commit (`git rev-parse HEAD`) và tree hash (`git rev-parse HEAD^{tree}`).
  5. Cập nhật mã hash chính xác vào `manifest.json`, `capability-matrix.md`, `baseline-report.md`, `run.json`.
  6. Dùng `git commit --amend --no-edit` để gộp việc cập nhật hash vào đúng commit duy nhất được review.
