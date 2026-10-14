---
name: softfac-empirical-benchmarking
description: Use when building paired empirical benchmarks in SoftFac.
version: 1.1.0
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
  3. `working_tree_clean`: Bắt buộc là `True` (phản ánh trung thực trạng thái Git thực tế).
  4. `evaluated_at`: Timestamp UTC sau thời điểm tạo commit candidate, chứng minh bài đo được thực hiện trên mã nguồn đã cam kết.

## 3. Quản Lý Timestamp Động Trong Các Hợp Đồng Ngắt & Tươi Mới (Dynamic Freshness Timestamps)
- **Cấm Tuyệt Đối Hardcode Timestamp Tĩnh Trong Unit Tests**:
  Trong các test suite kiểm thử máy trạng thái (state machine), resume guards, hoặc audit ledgers yêu cầu quan sát tươi mới (`fresh_observation.timestamp > interrupt.timestamp`):
  - Tuyệt đối không hardcode chuỗi thời gian tĩnh (ví dụ: `2026-09-23T12:00:00Z`). Khi thời gian thực tế của máy host vượt qua mốc tĩnh, các lệnh kiểm tra ngắt thời gian thực sẽ sinh lỗi `InvalidFreshObservationError` làm gãy test suite hồi quy.
  - Luôn sinh timestamp quan sát động dựa trên mốc thời gian của sự kiện ngắt hoặc đồng hồ hệ thống:
    ```python
    (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    ```

## 4. Bảo Toàn Tính Trung Thực Của Lỗi & Loại Bỏ Cache Fallback
- **Không Đắp Dữ Liệu Lịch Sử Làm Giả Kết Quả**:
  Khi API foundation model hoặc vision gateway không thể kết nối, evaluator phải ghi nhận lỗi trung thực (`engine_available=False`, chuỗi trích xuất rỗng). Tuyệt đối không thay thế bằng `extracted_semantic` được lưu sẵn trong corpus từ các lần chạy trước, vì điều này biến sự cố mất mạng thành điểm số chính xác 100% giả tạo.
- **Phân Định Rõ Ràng Protocol Mô Phỏng Ngoại Tuyến (Offline Simulation Scope)**:
  Kết quả thu được từ các harness mô phỏng tất định (deterministic simulation) phải được định danh chính xác (ví dụ: `GATE-M3-08 validated under offline deterministic simulation harness protocol`), tách bạch hoàn toàn với năng lực hoàn thành tác vụ trực tiếp trên môi trường production.

## 5. Chống Sửa Nhãn Thủ Công & Đảm Bảo Tính Toàn Vẹn Thực Thi Thật (No Relabeling Without Execution)
- **Sol Reviewer Đối Soát Thời Lượng Và Epoch ID**:
  Sol Reviewer luôn tính toán đối chiếu mốc thời gian:
  1. Epoch timestamp trong `trial_id` hoặc `run_id` phải khớp với thời điểm khởi động bài đo.
  2. Thời điểm `evaluated_at` trừ thời điểm bắt đầu phải tương thích với tổng thời lượng thực tế (`duration_seconds` hoặc tổng độ trễ các cuộc gọi inference). Nếu bài đo ghi nhận thời lượng 540s mà kết thúc trùng khít từng giây với lúc bắt đầu, Sol sẽ lập tức bắt lỗi sửa nhãn thủ công (relabeling).
  3. Mã băm ngẫu nhiên trong ID (ví dụ UUID suffix 8 ký tự) phải được sinh mới theo từng lần chạy thật.
- **Không Nhầm Lẫn Giữa Lệnh Kiểm Tra Cấu Trúc Và Lệnh Chạy Thực Nghiệm**:
  Các cờ như `--verify` chỉ kiểm tra tính toàn vẹn của tệp ảnh/fixture mà không thực thi so sánh OCR hay chạy harness. Bắt buộc phải chạy câu lệnh thực thi đầy đủ (full evaluation invocation) để cập nhật artifact.

## 6. Bảo Toàn Tính Đồng Bộ Giữa Các Khối Dữ Liệu Trong Artifact (Cross-Section Coherence)
- **Đồng Bộ Dữ Liệu Mẫu Giữa Benchmark Samples Và Paired Samples**:
  Khi bộ đánh giá (evaluator) ghi kết quả ra file JSON:
  - Khối `benchmark_samples[*].results` và khối `detailed_paired_samples[*]` phải khớp nhau từng chữ về chuỗi ngữ nghĩa trích xuất (`extracted_semantic`), độ tin cậy (`confidence`), độ trễ đo được (`latency_ms`), và kết quả nhận diện.
  - Cấm logic sao chép một phần (ví dụ: cập nhật nhánh ghép cặp nhưng cố tình giữ nguyên khối mẫu đơn từ template tĩnh cũ).
- **Ghi Nhận Đầy Đủ Run Identity**:
  `run_id` sinh ra trong phiên chạy phải được lưu lại ở cấp cao nhất của file artifact để bên thẩm định có thể liên kết trực tiếp bài đo với nhật ký thực thi.

## 7. Toàn Vẹn Của Cờ Trạng Thái Sạch (Clean-Flag Integrity)
- **Cấm Ghi Đè Trạng Thái Sạch Của Cây Thư Mục**:
  Biến `working_tree_clean` trong code evaluator phải được gán trực tiếp từ lệnh kiểm tra Git (`self.working_tree_clean = self._get_working_tree_clean()`). Tuyệt đối không thêm biểu thức `or (not require_clean_tree and ...)` để ngụy tạo trạng thái sạch khi cây thư mục đang có file chỉnh sửa dở dang.

## 8. Kỷ Luật Phân Định Mốc (Milestone Gating) & Trung Thực Tuyệt Đối
- **Không Làm Nhảy Cóc Hoặc Gom Góp Công Việc Của Milestone Sau**:
  Chỉ tập trung xử lý dứt điểm các finding của milestone hiện tại cho đến khi Sol Reviewer phát hành `verdict: APPROVE` 100%. Tuyệt đối không tự ý chuyển sang code milestone tiếp theo khi milestone hiện tại chưa được đóng.
- **Báo Cáo Minh Bạch Mọi Bất Thường**:
  Nếu gặp lỗi kiểm thử ở module khác do trôi thời gian hệ thống hoặc phụ thuộc chéo, phải báo cáo trung thực cho người dùng, không giấu diếm, không sửa tắt số liệu thực nghiệm.
