---
name: cu-amplification-benchmark
description: Use when building or auditing CU benchmark harnesses.
version: 1.0.0
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
- **Fail-Closed on Empty/Unsupported Actions**: Khi `available_actions` rỗng hoặc không hỗ trợ mutation yêu cầu, adapter phải fail-closed; không nuốt ngoại lệ model thành hành động synthetic `wait`.

### Cấu trúc Snapshot & Tool Surface Mapping (`CU-F003`)
- **Duyệt cây `data.tree` thay vì danh sách phẳng**: Trong runtime contract v1, dữ liệu cấu trúc UI nằm trong `data.tree` (phân cấp). Việc đọc nhầm trường `data.elements` phẳng sẽ dẫn đến toàn bộ element ref bị `null` (null refs).
- **Qualified Refs**: Element ref phải giữ nguyên định dạng qualified `@snapshot_id:eN` để runtime phân giải chính xác thế hệ snapshot và session.
- **Kiểm tra `available_actions` động**: Trước khi phát mutation action (click, set-value, scroll), đối chiếu với `available_actions` thực tế của node trong snapshot.
- **Tách biệt Lệnh Đọc/Quan sát**: Các lệnh quan sát thuần túy (`snapshot`, `screenshot`, `get`, `is`) không được phép bị từ chối chỉ vì element thiếu quyền mutation trong `available_actions`.
- **Đúng Cờ CLI & Tool Surface Đầy Đủ**: Đảm bảo cờ CLI chuẩn xác (ví dụ cờ `--property` thay vì `--prop`), hỗ trợ đầy đủ các thao tác: `click`, `double-click`, `triple-click`, `right-click`, `hover`, `drag`, `key-down`, `key-up`, `focus`, `clear`, `check`, `uncheck`, `toggle`, `expand`, `collapse`, `scroll-to`, `snapshot`, `screenshot`.

### Thiết kế Oracle Đối kháng & Xác Thực Đột Biến Thực Tế (Delta) (`CU-F004`)
- **Pre-action Snapshotting & Delta Verification**: Oracle phải chụp toàn bộ trạng thái pre-action (`capture_initial_state`) bao gồm file tồn tại sẵn, active window handles, và browser DOM/URL. Oracle phải chứng minh được **sự thay đổi thực tế (Delta)**: nếu trạng thái mục tiêu vốn đã thỏa mãn từ trước hành động, bước kiểm tra tuyệt đối không được pass vì một hành động đột biến không liên quan.
- **Fail-Closed khi Thiếu Dữ liệu Kiểm Tra**: Nếu không thể trích xuất DOM, cửa sổ hoặc state do lỗi hạ tầng (ví dụ Chrome đóng, mất kết nối CDP), oracle phải fail-closed lập tức và nâng episode lên trạng thái `INVALID_INFRASTRUCTURE` thay vì bỏ qua hay trả về pass giả mạo.
- **Conjunctive Criteria**: Mọi điều kiện kiểm tra đa mục tiêu (file match VÀ tab closed) phải thỏa mãn đồng thời (`all()`). Bất kỳ predicate nào lạ hoặc không nhận dạng được phải lập tức từ chối.

### Kiểm tra Bất biến Hệ thống với Lỗi Tiêm kích Thực thụ (`CU-F005`)
- **Kiểm tra Mã thoát & Tính Hợp lệ của Lệnh**: Bộ kiểm tra bất biến (`invariants.py`, `INV-01` đến `INV-06`) không được coi là pass nếu runtime command trả về exit code khác 0 hoặc dữ liệu rác.
- **Active Fault Injection**:
  - `INV-01 (Duplicate Mutation)`: Đo lường số lần đột biến vật lý thực sự và xác nhận từ chối dứt điểm khi gặp lệnh trùng lặp.
  - `INV-03 (Ambiguous Target Rejection)`: Lấy đúng candidate refs của các nút live duplicate thực tế từ cây snapshot và phát lệnh để kiểm chứng runtime từ chối dứt điểm với `AMBIGUOUS_TARGET`.
  - `INV-04 (Cross-Session Stale Ref)`: Thử nghiệm tái sử dụng ref từ snapshot thuộc session đã đóng để bảo đảm runtime từ chối `STALE_REF`.
  - `INV-05 (Unsupported Capability)`: Thực thi các phép thử thực tế với cờ capability không được hỗ trợ để đảm bảo nhận về mã lỗi `not_delivered` hoặc `capability_unsupported`.
  - `INV-06 (Uncertain Delivery & Replay Prevention)`: Truyền trạng thái `delivery_uncertain` thật vào quy trình điều phối và xác nhận từ chối lặp lại hành động nguy hiểm.

### Fixtures & Quản lý Trạng thái Ứng dụng (`CU-F006`)
- **Không Gán Cứng Trạng Thái Ban Đầu**: Fixture runner (`_fixture_runner.py`) không được phép hardcode các cờ thành công từ ban đầu (như `bounds_match=True` hoặc `collision_count=0`). Mọi giá trị kiểm tra phải được đo đạc động khi có tương tác vật lý.
- **Cô Lập Profile Trình Duyệt**: Mỗi lượt chạy hoặc lặp lại benchmark trình duyệt (Chrome/Edge) phải được cấp một `--user-data-dir` hoàn toàn riêng biệt để tránh rò rỉ cookie, cache, hoặc xung đột session lock.

### Schema & Lưu Trữ Artifact (`CU-F007`, `CU-F011`)
- **Atomic Record Output**: Khởi tạo nguyên tử và ghi bền vững từng dòng (`flush()` + `os.fsync()`) cho `episodes.jsonl`, `steps.jsonl`, và `artifacts.jsonl`.
- **Artifact Validation**: Các artifact sinh ra (`tree_snapshot`, `screenshot`, `oracle_evidence`) phải được validate nghiêm ngặt bằng `artifact.schema.json`.

### Báo cáo Thực nghiệm & Tính Toàn vẹn Dữ liệu (`CU-F008`)
- **Đồng Bộ Dữ Liệu Thực Tế**: Chạy baseline census sạch sẽ trên commit mới nhất để `baseline-report.md` và `run.json` ghi nhận đúng mã hash commit, hash nhị phân, và mẫu số cơ hội thực tế theo từng họ lỗi.

### Quản lý Sandbox & Thu hồi Tiến trình Đệ Quy (`CU-F009`)
- **Recursive Process Tree Cleanup**: Trên Windows, việc terminate PID cha thường để lại các tiến trình con detached (Chrome, cmd, powershell). Bắt buộc truy vấn và terminate đệ quy toàn bộ cây tiến trình con qua WMI/CIM (`ParentProcessId == PID`).
- **Giới Hạn Sandbox Tuyệt Đối**: Mọi thao tác dọn dẹp hoặc khởi tạo file trong `ResetHarness` phải được giới hạn chặt chẽ bên trong thư mục sandbox (`benchmarks/windows-cu/sandbox/`), chuẩn hóa đường dẫn và chặn 100% path traversal (`..`).
