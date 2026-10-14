---
name: softfac-sol-review-packet
description: Soạn Review Packet trung lập cho Sol trong SoftFac v2.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, sol, review, packet, audit, provenance]
---

# Quy Chuẩn Soạn Packet Review Cho Sol (SoftFac v2)

Mỗi khi chuẩn bị packet thẩm định cho Sol Reviewer, Hermes Orchestrator BẮT BUỘC tuân thủ các nguyên tắc trung lập và đối soát khách quan:

1. **Tính trung lập tuyệt đối (Neutral & Adversarial)**:
   - CẤM mớm kết quả, cấm gợi ý verdict (như "verdict MUST BE APPROVED", "passed all gates").
   - Sol là thẩm định độc lập duy nhất quyết định `APPROVED` hoặc `REVISE`.
   - Phải cung cấp JSON schema cho phép cả `APPROVED` lẫn `REVISE`.

2. **Phân loại nhãn bằng chứng minh bạch (Evidence Classification)**:
   - Mỗi mục bằng chứng dẫn chứng phải được gán nhãn rõ ràng:
     * `requirement`: Yêu cầu từ Master Plan.
     * `builder claim`: Lời tự khai của AGY (chưa được kiểm chứng).
     * `simulation / fixture evidence`: Dữ liệu mock/giả lập/fixture.
     * `independently observed evidence`: Kết quả Orchestrator tự chạy kiểm thử thật.
     * `missing evidence`: Bằng chứng còn thiếu hoặc chưa đủ.
   - Tuyệt đối không biến lời tuyên bố của Builder (PASS, PROMOTABLE) thành kết quả xác thực.

3. **Tính nguyên vẹn của Git Provenance (Non-Self-Referential)**:
   - Xác định rõ commit SHA, tree SHA, và trạng thái working tree (`working_tree_clean`).
   - Phân định rõ candidate commit đã kiểm thử với attestation commit.
   - Tuyệt đối không để xảy ra mâu thuẫn commit-hash recursion.

4. **Kiểm tra thực nghiệm (Empirical & Anti-Mock Discipline)**:
   - Phải chỉ rõ kết quả đo đạc đến từ quan sát provider thật (live UIA, CDP, MSAA, visual) hay từ dữ liệu giả lập/fixture.
   - Nêu rõ các negative controls (same-name/same-bounds decoys, stale generation, PID mismatch, expired deadline).
   - Kiểm tra đầy đủ các kịch bản biên: CDP unavailable, multi-target ambiguity.

5. **Trạng thái Packet**:
   - Nếu bằng chứng chưa đủ hoặc chưa chạy test thật: Đánh dấu `DRAFT — NOT SUBMITTABLE` và liệt kê blocker.
   - Nếu đầy đủ bằng chứng đối soát độc lập: Đánh dấu `READY FOR INDEPENDENT REVIEW` (nghĩa là packet đã đầy đủ để Sol duyệt, không mang hàm ý đã PASS).
