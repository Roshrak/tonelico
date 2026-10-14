---
name: cu-benchmarking-rules
description: Use when building or auditing CU benchmark harnesses.
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [benchmark, computer-use, oracle, invariants, amplification, gemini, softfac]
---

# Computer-Use Amplification Benchmark & Harness Guidelines

Bộ quy tắc kỹ thuật và kinh nghiệm thực chiến khi xây dựng, chạy và thẩm định (Sol review) hệ thống Computer-Use Amplification (`benchmarks/windows-cu/`, `tools/cu-amplifier/`) theo chuẩn SoftFac v2.

## 1. Bản chất Kỹ thuật & Bẫy Thẩm định của Sol Reviewer (Findings CU-F001 đến CU-F011)

### Model Identity & Track A Execution (`CU-F002`)
- **Không Mock Fallback trong Track A**: Khi chạy benchmark đánh giá năng lực cơ sở (baseline) của model mục tiêu (ví dụ `gemini-3.8-flash-high`), adapter không được phép âm thầm fallback sang deterministic mock khi gặp lỗi kết nối hay timeout.
- **Fail-Closed Model Verification**: Adapter phải kiểm tra chính xác model identity trả về từ endpoint API bằng so khớp chuỗi tuyệt đối (`model_version == expected_model_name`), cấm dùng substring (`in`) vì sẽ lọt shadow model hoặc fallback model ngầm.
- **Exact Reviewed Commit Provenance**: Mọi artifact nghiệm thu (`baseline-manifest.json`, `capability-matrix.md`, `baseline-report.md`, `run.json`) phải mang chính xác HEAD commit SHA và tree SHA của candidate commit được đưa sang Sol review. Cấm ghi nhận commit tạm thời/sibling commit.

### Cấu trúc Snapshot & Tool Surface Mapping (`CU-F003`)
- **Duyệt cây `data.tree` thay vì danh sách phẳng**: Trong runtime contract v1, dữ liệu cấu trúc UI nằm trong `data.tree` (phân cấp). Việc đọc nhầm trường `data.elements` phẳng sẽ dẫn đến toàn bộ element ref bị `null` (null refs).
- **Qualified Refs**: Element ref phải giữ nguyên định dạng qualified `@snapshot_id:eN` để runtime phân giải chính xác thế hệ snapshot và session.
- **Tách biệt Lệnh Đọc/Quan sát**: Các lệnh quan sát thuần túy (`snapshot`, `screenshot`, `get`, `is`) không được phép bị từ chối chỉ vì element thiếu quyền mutation trong `available_actions`.
- **Đúng Cờ CLI & Tool Surface Đầy Đủ**: Đảm bảo cờ CLI chuẩn xác (ví dụ cờ `--property` thay vì `--prop`), hỗ trợ đầy đủ toàn bộ action set.

### Thiết kế Oracle Đối kháng & Strict Target Match (`CU-F004`)
- **Strict Normalized Target Match (`_strict_target_match`)**:
  - Chỉ chấp nhận so khớp chính xác tuyệt đối case-insensitive (`target.strip().lower() == observed.strip().lower()`).
  - Cấm tuyệt đối substring matching hai chiều (`target in observed` hoặc `observed in target`).
  - Cấm fallback sang non-unique UI identifiers: Khi một phần tử có cả `AutomationId` (hoặc `ref`/`id`) và `Name`, runner verifier chỉ được phép ghi nhận unique `automation_id` vào `mutated_controls`. Tuyệt đối không thêm `matching_element["name"]` vào mutation keys, vì sẽ gây false-positive target correlation khi nhiều control trên desktop chia sẻ cùng một tên hiển thị (`email`).
- **Pre-action Snapshotting & Delta Verification**: Oracle phải chụp toàn bộ trạng thái pre-action và chứng minh được sự biến đổi trạng thái thực tế.

### Kiểm tra Bất biến Hệ thống với Lỗi Tiêm kích Thực thụ (`CU-F005`)
- Bộ kiểm tra bất biến (`invariants.py`, `INV-01` đến `INV-06`) phải thực hiện active fault injection với mã lỗi trả về chính xác (`AMBIGUOUS_TARGET`, `STALE_REF`, `capability_unsupported`, `unsafe_replay_after_uncertain_delivery`).

### Fixtures & Quản lý Trạng thái Ứng dụng (`CU-F006`)
- Fixture runner (`_fixture_runner.py`) không được phép hardcode các cờ thành công từ ban đầu. Phải cô lập hoàn toàn browser profiles (`--user-data-dir`).

### Schema & Lưu Trữ Artifact (`CU-F007`, `CU-F011`)
- Lưu trữ file vật lý `artifacts/<id>.json` trên ổ đĩa và validate bằng `artifact.schema.json`. Ghi bền vững từng dòng (`flush()` + `os.fsync()`) cho `.jsonl`.

### Báo cáo Thực nghiệm & Tính Toàn vẹn Dữ liệu (`CU-F008`)
- Siết chặt gating trong `report_generator.py`: Bắt buộc số lượt repeats đồng đều tuyệt đối (`min_repeats == max_repeats == 3`), tỷ lệ held-out task $\ge 14/40$ ($\ge 35\%$), và bộ 6 invariants + 16 controls pass 100%.

### Quản lý Sandbox & Thu hồi Tiến trình Đệ Quy (`CU-F009`)
- **Explicit Launch Token Propagation**:
  - Khi khởi chạy bất kỳ tiến trình sandbox/fixture nào, truyền token:
    - Environment: `CU_LAUNCH_TOKEN = f"CU_TOKEN_{uuid.hex}"`.
    - Command line: `--cu-token <token>`. Fixture runner script bắt buộc khai báo `--cu-token` trong `argparse` để tránh exit code 1.
- **Ancestry Ledger & Win32_Process Reclamation**:
  - Lưu mọi launcher PID vào `self._ancestry_ledger`.
  - Khi dọn dẹp (`cleanup_all`), dùng PowerShell / CIM query `Win32_Process` để truy vết CommandLine chứa `CU_TOKEN_*`, hoặc ProcessId/ParentProcessId nằm trong ancestry ledger để diệt sạch tận gốc grandchildren / detached processes.

---

## 2. Quy Tắc Thẩm Định Task-Level Independent Verification (CU-M6)

### Polling Trạng Thái Trễ (Delayed-State Polling)
- **Bắt buộc chứng minh polling quan sát tươi mới (Fresh Reads)**: Khi kiểm thử postcondition xuất hiện sau độ trễ (ví dụ transition diễn ra ở t >= 250ms với timeout 500ms), test case phải chứng minh provider ghi nhận trạng thái chưa hoàn tất (premature/pending) ở các lần thăm dò ban đầu, thực hiện ít nhất >= 3 lần đọc mới, và chỉ xác nhận thành công khi trạng thái settled xuất hiện trước deadline. Cấm dùng test tĩnh chỉ kiểm tra ở t=0 hoặc chuyển đổi trạng thái quá sớm (dưới 100ms) khi kịch bản yêu cầu 250ms. Code, test assertion, artifact JSON và markdown report phải đồng bộ thời gian tuyệt đối.

### Chống Vòng Lặp Giả (Anti-Circularity) Trong Visual Semantic Verifier
- **Không Stub/Mock Theo Header**: Test vision adapter bắt buộc phải phụ thuộc vào nội dung pixel thực tế (ví dụ kiểm tra dominant color, phân tích histogram, độ tương phản, hoặc gọi multimodal endpoint thật). Cấm chỉ kiểm tra header PNG/JPEG rồi trả về chuỗi mô tả cố định chứa sẵn keyword.
- **Kịch Bản Đối Chứng Âm (Negative/Decoy Controls)**: Mọi benchmark đánh giá semantic verifier bắt buộc phải có cặp ảnh đối chứng dương (ví dụ: gear icon) và đối chứng âm (blank image hoặc decoy button). Cần chứng minh tráo đổi ảnh đối chứng âm sẽ làm thay đổi kết quả thẩm định từ SUCCESS thành FAILURE/UNKNOWN.
- **So Sánh Đồng Thời 3 Nhánh (3-Way Ablation)**: Bắt buộc đánh giá trên cùng một tập task trực quan giữa 3 chế độ:
  1. `deterministic-only` (chỉ kiểm tra UIA/MSAA text)
  2. `crop-only` (cắt vùng bounding box nhưng không có reasoning ngữ cảnh)
  3. `semantic-verifier` (multimodal vision reasoning)
  Chứng minh semantic verifier vượt trội về recall/precision mà không tăng false-positive rate. Mọi chỉ số phải được tính toán từ tập tác vụ trực quan chung này.

### Ưu Tiên File Oracle Tuyệt Đối Cho Tác Vụ Lưu/Xuất File (Save Tasks)
- **Không Tin Hộp Thoại Biến Mất**: Việc hộp thoại Save As biến mất hoặc nút Save không còn hiển thị không đủ để chứng minh file đã lưu thành công.
- **Enforced Task-Plan Policy**: Nếu tác vụ có file oracle (đường dẫn file đích), evaluator bắt buộc phải kiểm tra file trên ổ đĩa: file phải tồn tại, kích thước > 0 bytes, và nội dung/hash khớp. Nếu file oracle thất bại (file thiếu hoặc 0-byte), task outcome bị ép buộc là `FAILURE` bất kể trạng thái UI ra sao.

### Phân Tách Mẫu Số Báo Cáo & Tỷ Lệ Unknown
- **Công thức Coverage Rõ Ràng**: Verification Coverage phải có công thức và mẫu số minh bạch: Coverage = evaluated_tasks / total_applicable_tasks = 12 / 12 = 100%.
- **Tách Bạch Tỷ Lệ Unknown**:
  - Standard Scenarios Unknown (Deterministic) = 1 / 6 = 16.7% (do thiếu visual verifier trên tác vụ đồ họa).
  - Overall Evaluation Suite Unknown (Deterministic) = 1 / 12 = 8.3% (1 trên tổng số 12 kịch bản chuẩn và bẫy).
  - Với chế độ Full (kết hợp Semantic Verifier), cả 2 tỷ lệ trên đạt 0.0%.

---

## 3. Quy Tắc Thẩm Định Phục Hồi Không Replay & Intent Journaling (CU-M7)

### Tích Hợp Intent Journaling Vào Ranh Giới Điều Phối Đột Biến Thực Tế
- **Persist Ngay Trước Lệnh Mutation (Fail-Closed)**: Durable intent journaling bắt buộc phải được gắn trực tiếp vào ranh giới dispatch (`BaselineRunner._dispatch_command`). Trước mỗi lệnh gây đột biến hệ thống, phải ghi intent xuống đĩa (`record_intent_pre_dispatch()` kèm `flush()` và `os.fsync()`). Nếu việc ghi đĩa thất bại, hệ thống phải dừng ngay lập tức (fail-closed), tuyệt đối không gửi lệnh sang OS.
- **Cập Nhật Outcome Ngay Khi Nhận Phản Hồi**: Ngay sau khi lệnh CLI/OS trả về (hoặc timeout/exception), phải lập tức gọi `record_intent_outcome()` để cập nhật disposition (`DELIVERED`, `UNCERTAIN`, `UNKNOWN`, `NOT_DELIVERED`).

### Chống Replay Có Phạm Vi (Scoped Replay Protection vs Global Suppression)
- **Không Khóa Vĩnh Viễn Control Mục Tiêu**: Cấm chặn vĩnh viễn target ref trên toàn hệ thống sau một lần thất bại. Việc chặn lặp lại (suppression/quarantine) phải được định danh theo `(intent_id, idempotency_key, state_generation)`.
- **Cho Phép Hành Động Mới Hợp Lệ**: Một hành động mới trên cùng control (ví dụ gõ tiếp ký tự sau khi focus, hoặc nhấn Next sau khi form đã hợp lệ) phải được cho phép nếu đi kèm ý định logic mới và generation token mới từ snapshot tươi mới.

### Bằng Chứng Xác Thực Tươi Mới Cho NotDelivered Reconsideration
- **Bắt Buộc Bằng Chứng Hậu Thất Bại**: Khi một hành động bị veto ở trạng thái `NOT_DELIVERED`, hệ thống chỉ được xem xét đề xuất lại nếu có bằng chứng xác thực được sinh ra SAU thời điểm thất bại (fresh snapshot ID, higher generation token, policy check ID). Cấm dùng cờ boolean tự gán từ caller (`live_target_valid=True`).

### Tiêm Kích Lỗi & Kiểm Chứng Bằng Bộ Đếm Đột Biến Ngoại Vi
- **External Mutation Counter Tại 3 Ranh Giới**: Kiểm thử fault injection phải đo đạc trực tiếp trên bộ đếm ngoại vi (external mutation counter) tại 3 ranh giới lỗi:
  1. Lỗi trước khi dispatch (pre-dispatch write failure).
  2. Lỗi ngay sau khi dispatch (disconnect / crash sau khi effect đã phát sinh trên OS).
  3. Lỗi trước khi nhận/xử lý response (transport / trace write failure).
- **Khẳng Định Zero Duplicate Mutations**: Bộ đếm ngoại vi chứng minh không có bất kỳ lệnh nào bị thực thi lặp lại 2 lần đối với các trạng thái `uncertain`, `unknown`, hoặc `delivered`.

### Siết Chặt Schema Cho Trạng Thái Dừng (Terminal State Schema Invariant)
- **Bắt Buộc Bằng Chứng Hoặc Lý Do Chặn**: Trong `intent_journal.schema.json`, khi một entry đạt `dispatch_phase == "TERMINAL"`, schema phải bắt buộc có trường `terminal_evidence` hoặc trường `blocked_reason` không rỗng. Schema test phải có negative case từ chối terminal record thiếu cả hai trường này.

### Cô Lập Fixture & Hạch Toán Thống Kê Chuẩn Xác
- **Tách Biệt Rõ Ràng Các Fixture Lỗi**:
  - `lost_focus.json`: Kiểm thử riêng việc mất focus cửa sổ.
  - `unexpected_dialog.json`: Kiểm thử riêng việc xuất hiện modal/dialog bất ngờ che khuất thao tác.
  - `executor_crash_restart.json`: Kiểm thử riêng kịch bản crash executor và phục hồi qua nhật ký intent journal.
- **Hạch Toán Khớp 100%**: Mọi con số trong fixture, test assertion, artifact JSON và báo cáo thực nghiệm markdown phải đồng nhất hoàn toàn về số lượng recoverable faults và tỷ lệ recovery.

---

## 4. Quy Tắc Thẩm Định Multimodal Escalation & Paired Trial Gating (CU-M3)

### Bảo Toàn Không Gian Tọa Độ Qua Phép Chiếu (Coordinate Space Preservation)
- **Tường Minh Không Gian Tọa Độ**: Khi chiếu tọa độ từ crop/vùng con (`projection.py`), kết quả phải gắn nhãn tường minh `coordinate_space="desktop"`.
- **Cấm Suy Diễn Mơ Hồ**: Tuyệt đối không phỏng đoán tọa độ desktop từ `window_id` khi thiếu chuỗi offset hình học rõ ràng. Toàn bộ chuỗi từ projector đến runner caller phải kiểm chứng tính bất biến của không gian tọa độ.

### Xác Minh Hash Ảnh Chụp Màn Hình Thất Bại-Đóng (Fail-Closed Screenshot Hash)
- **Kiểm Tra Bắt Buộc Trước Khi Cắt (Preflight Verification)**: Mọi thao tác crop action phải kiểm tra hash của observation screenshot. Nếu hash bị thiếu, rỗng, hoặc không khớp với screenshot hiện hành, hệ thống phải từ chối ngay lập tức (fail-closed).
- **Cập Nhật Hash Sau Thành Công**: `self.current_screenshot_hash` chỉ được cập nhật sau khi hành động thực thi thành công hoàn toàn.

### Định Danh Cam Kết Thử Nghiệm & Phạm Vi Mô Phỏng Ngoại Tuyến (Simulation Gating)
- **Gắn Nhãn Rõ Phạm Vi Mô Phỏng**: Các bài đo đạc sử dụng harness mô phỏng tất định (deterministic simulation) phải khai báo tường minh giao thức (ví dụ: `validated under offline deterministic simulation harness protocol`). Không được đánh tráo kết quả mô phỏng thành bằng chứng hoàn thành tác vụ sản xuất thực tế.
- **Linh Hoạt Trong Nghiệm Thu Attestation Commit**: Runner nghiệm thu (`run_m3_paired_trial.py`) phải hỗ trợ kiểm tra `candidate_commit` đối chiếu với git HEAD, commit cha trực tiếp (parent commit), hoặc cờ CLI `--candidate-commit <SHA>` để việc tạo commit báo cáo không làm vô hiệu hóa artifact đối soát.

### Bảo Toàn Lỗi Thực Tế Khi Đánh Giá Multimodal (No Cached Semantic Fallback)
- **Không Lấy Đáp Án Lưu Sẵn Khi Rớt Mạng**: Khi đánh giá mô hình thị giác (multimodal) đối chiếu với OCR cục bộ, nếu gateway API ngoại vi không khả dụng hoặc trả về rỗng, evaluator (`ocr_evaluator.py`) phải bảo toàn nguyên vẹn lỗi (`engine_available=False`, trích xuất rỗng). Tuyệt đối không lấy mô tả ngữ nghĩa lưu sẵn trong corpus đắp vào để tạo điểm số giả lập 100%.
- **Phán Quyết Phụ Thuộc Dữ Liệu Đo Đạc Thật**: Chỉ phát hành phán quyết `NO-GO` khi gateway thực sự khả dụng và dữ liệu đo đạc trực tiếp chứng minh tính ưu việt. Khi gateway mất kết nối, phán quyết bắt buộc phải là `INCONCLUSIVE_GATEWAY_UNAVAILABLE` hoặc `EVALUATION_DEGRADED`.

