---
name: softfac-windows-heartbeat
description: Use when monitoring SoftFac background tasks via heartbeats.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, heartbeat, orchestrator, windows, agy, codex]
---

# SoftFac Periodic Heartbeat Operations

Hướng dẫn điều phối và theo dõi tiến trình nền (AGY Builder / Sol Reviewer / Codex) trong SoftFac v2 khi người dùng thiết lập lệnh heartbeat định kỳ (10m/15m).

## 1. Nguyên Tắc Giám Sát Tiến Trình (Process Polling vs Event-Driven)
- **Ưu tiên Event-Driven khi có PID**:
  - Tuyệt đối không chạy vòng lặp thăm dò liên tục (`Get-Process`, `Start-Sleep 30`, tail log lặp đi lặp lại) làm nghẽn context và tràn token vô ích.
  - Khi có `<PID>`, chạy duy nhất 1 lệnh ngầm:
    `terminal(command='powershell -NoProfile -Command "Wait-Process -Id <PID>"', background=True, notify=True)`
  - **Nhả lượt (idle) ngay lập tức**: Sau khi dispatch lệnh chờ ngầm, Orchestrator kết thúc turn để hệ thống tự động nhận event completion notification và đánh thức Orchestrator khi PID thoát.
- **Khi sử dụng Heartbeat định kỳ (Polling)**:
  - Sử dụng `tasklist | grep -iE '<pid>|<name>'` hoặc PowerShell `Get-Process` để xác minh trạng thái sống/chết của tiến trình worker và driver.
  - Trích xuất RAM sử dụng (`Working Set`) và nhật ký xuất mới nhất (`tail -n 25`) để xác nhận tiến trình không bị treo (frozen / deadlocked).

## 2. Quy Tắc Phản Hồi (Response Protocol)
- **Khi user yêu cầu: 'nếu vẫn còn chạy thì không trả lời (no output)'**:
  - Nếu tiến trình AGY/Codex vẫn đang thực thi: **Tuyệt đối không sinh bất kỳ văn bản phản hồi nào** (hoặc chỉ dùng comment ẩn HTML `<!-- ... -->`), không tự chào hay tóm tắt lặp lại.
  - Phải tuân thủ nghiêm ngặt chỉ thị im lặng hoàn toàn này để tránh ngắt quãng luồng tập trung của người dùng.
- **Khi tiến trình kết thúc (Exit / Terminated)**:
  - Kiểm tra trạng thái mã thoát và kết quả sinh ra (`result.json`, `git status`, log file).
  - Chạy toàn bộ các bộ test deterministic liên quan (cargo test, pytest, unittest, invariant suites).
  - Tự động thực hiện bước tiếp theo trong pipeline SoftFac v2 (Stage commit hoặc chuyển giao sang Reviewer/Builder).
  - Báo cáo rõ ràng: Commit ID, các findings đã khắc phục, log test và PID của tiến trình mới được kích hoạt.
