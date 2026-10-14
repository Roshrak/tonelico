---
name: softfac-empirical-benchmarking
description: Use when building paired empirical benchmarks in SoftFac.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [softfac, benchmark, provenance, paired-trial, audit, sol, invariants]
---

# SoftFac Empirical Benchmarking & Paired Trial Rigor

Quy chuẩn kỹ thuật và các bẫy thẩm định đối kháng (adversarial audit pitfalls) của Sol Reviewer khi xây dựng, chạy và nghiệm thu các bộ đo đạc thực nghiệm (empirical benchmarks), paired trials, và ablation studies trong pipeline SoftFac v2 trên Windows.

## 1. Nguyên Tắc Both-Arms-Live Trong Đánh Giá Đối Soát Ghép Cặp (Paired Trials)
- **Không Kết Luận Khi Có Sự Cố Hạ Tầng Ngoại Vi**:
  Khi đánh giá so sánh hai nhánh (ví dụ: Pipeline A - Bounded Crop Multimodal vs. Pipeline B - Crop + Local OCR + Multimodal):
  - Phán quyết kiến trúc dứt khoát (`NO-GO` hoặc `RECONSIDER`) BẮT BUỘC đòi hỏi cả hai nhánh đều thực thi trực tiếp (live calls) thành công trên 100% mẫu khảo sát (`gemini_available and pipeline_b_available`).
  - Nếu bất kỳ nhánh nào gặp sự cố mạng, timeout hoặc gateway không khả dụng (`is_live_call=False`), sự cố đó không được phép dùng để tính delta âm (-100 pp) nhằm tuyên bố nhánh kia vô giá trị.
- **Đồng Bộ Tính Hợp Lệ Trên Mọi Trường Đầu Ra (All Output Fields)**:
  Quy tắc Both-Arms-Live phải được áp dụng nhất quán trên toàn bộ các cấu trúc JSON đầu ra (cả trường tổng quát cấp cao `verdict.decision` lẫn trường so sánh chi tiết lồng nhau `comparative_delta.definitive_verdict`). Tuyệt đối không để trường lồng nhau phát hành `NO-GO` trong khi trường cấp cao ghi nhận `INCONCLUSIVE_GATEWAY_UNAVAILABLE`.
- **Kiểm Thử Hai Chiều Mất Kết Nối (Bilateral Outage Tests)**:
  Test suite bắt buộc phải có test cases kiểm chứng cho cả hai kịch bản phân tách (split outage):
  1. Pipeline A live + Pipeline B down $\to$ cả hai trường phán quyết đều chuyển thành `INCONCLUSIVE` hoặc `EVALUATION_DEGRADED` (CẤM `NO-GO`).
  2. Pipeline A down + Pipeline B live $\to$ cả hai trường phán quyết đều chuyển thành `INCONCLUSIVE` hoặc `EVALUATION_DEGRADED` (CẤM `NO-GO`).

## 2. Ràng Buộc Mã Nguồn & Bất Biến Cây Thư Mục Làm Việc (Fail-Closed Worktree Binding)
- **Không Bỏ Qua Thư Mục Bẩn Dựa Trên Commit Tree Hash**:
  Khi xác minh một candidate commit revision (`target^{tree} == HEAD^{tree}`), runner đối soát không được phép trả về thành công ngay lập tức nếu working tree đang có tệp tin bị chỉnh sửa chưa commit (`git status --porcelain`).
- **Fail-Closed Tránh Thực Thi Code Bẩn Chưa Commit**:
  Nếu các module Python được đánh giá (hoặc các tệp fixture, harness) chứa uncommitted edits hoặc untracked files, runner bắt buộc phải từ chối chạy ngay lập tức (`raise ValueError`), tránh tình trạng mã nguồn bị sửa đổi ngoài luồng chạy thử nghiệm nhưng artifact lại gắn nhãn của một commit sạch trong lịch sử.
- **Hạch Toán Ba Thành Phần Bắt Buộc Trong Artifact**:
  Mọi artifact đối soát phải lưu đồng thời:
  1. `candidate_commit`: SHA commit mục tiêu được thẩm định.
  2. `source_tree_hash`: Hash cây mã nguồn sạch (`git rev-parse HEAD^{tree}`).
  3. `working_tree_clean`: Bắt buộc là `True`.
  4. `evaluated_at`: Timestamp UTC sau thời điểm tạo commit candidate, chứng minh bài đo được thực hiện trên mã nguồn đã cam kết.

## 3. Quản Lý Timestamp Động Trong Các Hợp Đồng Ngắt & Tươi Mới (Dynamic Freshness Timestamps)
- **Cấm Tuyệt Đối Hardcode Timestamp Tĩnh Trong Unit Tests**:
  Trong các test suite kiểm thử máy trạng thái (state machine), resume guards, hoặc audit ledgers yêu cầu quan sát tươi mới (`fresh_observation.timestamp > interrupt.timestamp`):
  - Tuyệt đối không hardcode chuỗi thời gian tĩnh (ví dụ: `2026-09-23T08:00:00Z`). Khi thời gian thực tế của máy host vượt qua mốc tĩnh, các lệnh kiểm tra ngắt thời gian thực sẽ sinh lỗi `InvalidFreshObservationError` làm gãy test suite hồi quy.
  - Luôn sinh timestamp quan sát động dựa trên mốc thời gian của sự kiện ngắt hoặc đồng hồ hệ thống:
    ```python
    (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    ```

## 4. Bảo Toàn Tính Trung Thực Của Lỗi & Loại Bỏ Cache Fallback
- **Không Đắp Dữ Liệu Lịch Sử Làm Giả Kết Quả**:
  Khi API foundation model hoặc vision gateway không thể kết nối, evaluator phải ghi nhận lỗi trung thực (`engine_available=False`, chuỗi trích xuất rỗng). Tuyệt đối không thay thế bằng `extracted_semantic` được lưu sẵn trong corpus từ các lần chạy trước, vì điều này biến sự cố mất mạng thành điểm số chính xác 100% giả tạo.
- **Phân Định Rõ Ràng Protocol Mô Phỏng Ngoại Tuyến (Offline Simulation Scope)**:
  Kết quả thu được từ các harness mô phỏng tất định (deterministic simulation) phải được định danh chính xác (ví dụ: `GATE-M3-08 validated under offline deterministic simulation harness protocol`), tách bạch hoàn toàn với năng lực hoàn thành tác vụ trực tiếp trên môi trường production.
