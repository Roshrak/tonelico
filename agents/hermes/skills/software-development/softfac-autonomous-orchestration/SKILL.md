---
name: softfac-autonomous-orchestration
description: Run SoftFac v2 pipelines autonomously without hesitating.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, automation, orchestration, reviewer, builder]
---

# SoftFac v2 Autonomous Orchestration & Zero-Hesitation Rules

Hướng dẫn vận hành tự động cho Orchestrator (Hermes) trong SoftFac v2 pipeline.

## 1. Core Mandate: Full Autonomous Flow (Zero Hesitation)
- **Tự động hóa hoàn toàn**: SoftFac v2 là dây chuyền công nghiệp tự động (Software Factory).
- Khi Sol Reviewer đưa ra phán quyết `REVISE` hoặc `REJECTED`:
  - Orchestrator **BẮT BUỘC TỰ ĐỘNG** phân tích findings, tạo 1-shot prompt, chuyển giao trực tiếp cho Builder sửa code, chạy test xác minh và kích hoạt vòng review tiếp theo.
  - **CẤM HỎI Ý KIẾN NGƯỜI DÙNG**: Tuyệt đối không dừng lại giữa chừng để hỏi "Bạn có muốn tôi chuyển giao cho builder không?" hay "Tôi có nên tiếp tục không?". Người dùng giao phó toàn quyền điều phối cho Orchestrator.
  - **Chỉ dừng khi gặp Hard Blocker**: Chỉ tạm dừng và báo cáo khi gặp lỗi vật lý ngoại vi không thể tự giải quyết: mất điện, rớt mạng, proxy pool/account cạn kiệt hoàn toàn, hoặc yêu cầu 2FA/login từ con người.

## 2. One-Shot Batch Remediation Discipline
- Khi chuyển giao cho Builder (AGY):
  - **Gửi ĐÚNG 1 PROMPT THI CÔNG**: Yêu cầu sửa trực tiếp vào mã nguồn, chạy unit tests, invariants, oracle-controls và git commit ngay trong 1 lượt.
  - **Cấm Builder lập plan 2 lượt**: Không cho phép Builder tách thành turn lập kế hoạch rồi mới thi công.

## 3. Provenance & Forensic Containment Rules
- **Exact Commit Provenance**:
  - Không bao giờ để tài liệu (`baseline-manifest.json`, `capability-matrix.md`, `baseline-report.md`) hoặc run bundle (`run.json`, `initial_run.json`) mang hash của commit cũ hoặc working tree chưa commit. Luôn bảo đảm đồng bộ 100% mã commit và tree hash với commit được Sol review.
- **Detached-Descendant Containment**:
  - Tránh so khớp chuỗi script chung chung (như `_fixture_runner.py`) trong command line.
  - Khi dọn dẹp tiến trình con/cháu trong Windows, duy trì luồng giám sát phả hệ thời gian thực (`_monitor_ancestry_loop`) để bắt kịp các tiến trình con ngay cả khi tiến trình cha trung gian thoát sớm.
