---
name: softfac-windows-workflow-discipline
description: Enforce Builder exit, Orchestrator commit, and Sol audit.
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [coding, builder, agy, sol, softfac, orchestrator, windows]
---

# SoftFac v2 Windows Workflow & Role Discipline

### VAI TRÒ VÀ TRÌNH TỰ BẮT BUỘC

1. **AGY BUILDER (`agy.exe`, `gemini-3.8-flash-high`)**:
   - Nhận prompt chi tiết chứa 100% findings/yêu cầu từ Sol hoặc User.
   - **MỆNH LỆNH THI CÔNG TRỰC TIẾP**: Cấm ngồi lập kế hoạch hay chia lượt plan/code; code, test, patch ngay lập tức trong 1 lượt duy nhất.
   - Sửa đổi mã nguồn, cập nhật test suite và chạy test nội bộ.
   - **TUYỆT ĐỐI CẤM AGY CHẠY `git commit`**.
   - Phải thoát hoàn toàn tiến trình (`exit 0`, không còn xuất hiện trong `tasklist`) sau khi hoàn thành.

2. **HERMES ORCHESTRATOR**:
   - **KHÔNG code thay Builder**: Dù gặp lỗi cú pháp hay test fail nhỏ, luôn ném ngược lại cho AGY Builder sửa trong lượt kế tiếp.
   - **Chờ Builder kết thúc hoàn toàn**: Tuyệt đối không gọi Sol Reviewer khi AGY vẫn còn đang chạy trong `tasklist`. Phải kiểm tra tiến trình `agy.exe` đã thoát sạch sẽ.
   - **Giám sát Kernel & Quản lý tiến trình nền (BẮT BUỘC)**:
     * Mọi lệnh gọi AGY hoặc Sol chạy nền bắt buộc phải ở chế độ non-interactive (không chờ input phím).
     * Chạy tiến trình dài (AGY Builder / Sol Reviewer) qua terminal với `background=true, notify=true` hoặc python script bọc ngoài có logging ra file tạm.
     * **TUYỆT ĐỐI CẤM loop polling hoặc lặp Start-Sleep**: Không chạy vòng lặp thăm dò liên tục (`Get-Process`, `Start-Sleep`, kiểm tra log tail từng vài chục giây) làm nghẽn context và tràn lượt tool gọi vô ích.
     * **Quy tắc chờ ngầm chuẩn**: Sau khi spawn tiến trình dài hoặc khi cần theo dõi tiến trình `<PID>`, chạy duy nhất 1 lệnh ngầm:
       `powershell -NoProfile -Command "Wait-Process -Id <PID>"` với `background=true, notify=true`.
     * **Nhả lượt (idle) ngay lập tức**: Sau khi dispatch lệnh chờ ngầm, Orchestrator lập tức nhả lượt (kết thúc turn), để hệ thống tự động nhận event completion notification và đánh thức Orchestrator khi PID thoát.
     * **An toàn môi trường Host**: Cấm chạy các kịch bản kiểm thử trực tiếp có logic đóng ứng dụng diện rộng (`cleanup_all` / `taskkill`) trên máy host; các tác vụ reset/oracle kiểm thử phải được bypass hoặc cô lập trong sandbox.
   - **Chạy nghiệm thu độc lập**:
     * Unit test discovery: `python -m unittest discover -s ...`
     * Invariants / Oracle controls (nếu có).
     * Xác nhận Layer A (`crates/`) nguyên vẹn 100% (0 dòng diff).
   - **Chính tay Hermes thực hiện `git commit`**:
     * Commit mã nguồn trước.
     * Cập nhật đồng bộ các tài liệu provenance/manifest (`baseline-manifest.json`, `capability-matrix.md`, `baseline-report.md`) với SHA256 commit và tree hash vừa tạo.
     * Commit tài liệu đối soát.

3. **SOL REVIEWER (`codex.exe`, `gpt-6-sol`, reasoning=high)**:
   - Chỉ được kích hoạt sau khi Hermes Orchestrator đã commit hoàn tất mã nguồn và tài liệu đồng bộ.
   - Chạy nền qua subprocess độc lập với API pool localhost:13844/v1 (`codex.cmd exec --sandbox danger-full-access`).
   - Theo dõi Sol qua lệnh chờ ngầm `Wait-Process -Id <PID>` (`background=true, notify=true`), không loop poll.
   - **TUYỆT ĐỐI KHÔNG tự ý tắt hoặc kill tiến trình Sol Reviewer** khi đang chạy để tránh làm lãng phí quota thẩm định.

4. **NGHIỆM THU 100% APPROVE & TỰ ĐỘNG CHUYỂN TIẾP MILESTONE**:
   - Khi Sol thẩm định một Milestone mới: Sol chạy Full Milestone Review.
   - Khi Sol phát hiện findings (verdict REVISE): Orchestrator gom toàn bộ findings thành 1 prompt thi công trực tiếp cho AGY Builder batch-fix -> Sol re-review findings.
   - Lặp lại vòng lặp (loop) cho đến khi 100% findings được Sol APPROVE / RESOLVED.
   - **Tự động chuyển tiếp Milestone ($n \to n+1$)**: Khi Sol trả về `verdict: APPROVED` và `remaining_findings: []`: Orchestrator đối chiếu ngay với Astra Master Plan, trích xuất yêu cầu của Milestone tiếp theo ($n+1$), soạn prompt thi công trực tiếp và kích hoạt AGY Builder ngay lập tức; không dừng lại hỏi ý kiến hoặc yêu cầu người dùng xác nhận các bước đã có trong plan.
   - Khi báo cáo luôn trích xuất JSON verdict thực tế của Sol làm bằng chứng, không báo cáo suông.
