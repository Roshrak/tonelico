# Windows Computer-Use Amplification Protocol & Remediation Patterns

Hướng dẫn và bài học kỹ thuật chuyên sâu về giai đoạn Computer-Use Amplification (CU-M0 đến CU-M10) và quy chuẩn kiểm soát của Sol Reviewer.

## 1. Adversarial Oracle & Baseline Verification Patterns
- **Fail-Closed Oracle Semantics**:
  - Không bao giờ mặc định trả về `True` khi gặp predicate/criteria không hỗ trợ hoặc không nhận diện được.
  - Phải kiểm tra và bắt buộc tất cả recognized criteria cùng pass đồng thời (`all(...)`).
  - **Pre-existing State Invalidation**: Phải capture snapshot trạng thái trước khi action được dispatch (pre-action state) để loại trừ trường hợp file hoặc UI state mong muốn đã tồn tại sẵn từ trước.
  - **Import Integrity**: Luôn kiểm tra đầy đủ các import phụ thuộc trong runtime harness (ví dụ `import uuid`) để tránh các lỗi runtime đột ngột như `NameError: name 'uuid' is not defined` khi khởi tạo fixture hoặc state tracker.
- **Fail-Closed Model Identity Validation**:
  - Khi adapter kết nối trực tiếp với model inference qua API (như Gemini 3.8 Flash High), bắt buộc so sánh chuỗi danh tính tuyệt đối (`model_version == self.model_name`).
  - Tuyệt đối cấm kiểm tra lỏng lẻo bằng substring (`in self.model_name`) để tránh trường hợp shadow model hoặc mock model vượt qua kiểm duyệt.
  - Loại bỏ hoàn toàn mock fallback trong các track đánh giá năng lực thực tế của model.
- **Strict Invariant Fault Injection (`INV-01` .. `INV-06`)**:
  - Các bài test invariant không được dựa vào mock hời hợt; phải tiêm kích lỗi thực sự:
    - `INV-01`: Kiểm tra số lượt dispatch thực tế có bị đột biến (mutation spike) hay không.
    - `INV-03`: Tạo 2 control trùng thuộc tính để kiểm chứng lỗi `AMBIGUOUS_TARGET`.
    - `INV-04`: Thử giải quyết element ref từ một session khác để kiểm tra tính cô lập session.
    - `INV-05`: Gửi action không được hỗ trợ để đảm bảo nhận về `not_delivered`.
    - `INV-06`: Tiêm kích uncertain delivery và kiểm tra cơ chế chặn replay.
  - Test phải fail ngay lập tức nếu runtime command bị lỗi, không được pass âm thầm.

## 2. Windows Fixture Management & Sandbox Safety
- **Sandbox Boundary & Traversal Defense**:
  - Mọi thao tác ghi/đọc file trong benchmark phải được cô lập tuyệt đối trong thư mục sandbox (ví dụ `benchmarks/windows-cu/sandbox/`).
  - Kiểm tra và chặn đứng mọi nỗ lực path traversal chứa `..` ra ngoài sandbox root.
- **Clean Fixture Lifecycle & Process Reclamation**:
  - Bổ sung launcher và runner thật cho toàn bộ các surface (Notepad, Explorer, Calculator, Settings, Dialogs, Chrome).
  - Với các trình duyệt (Chrome/Edge): phải quản lý profile cô lập (`--user-data-dir`) theo từng lượt chạy và dọn dẹp sạch sẽ sau khi kết thúc.
  - **Process Tree Reclamation**: Chỉ terminate các tiến trình con do chính test harness spawn (dựa trên PID tree). Tuyệt đối không dùng `taskkill /F /IM <process>.exe` diện rộng làm ảnh hưởng đến môi trường của người dùng.
  - Bọc dọn dẹp tài nguyên và tiến trình trong khối `finally` và xử lý cả `BaseException` (KeyboardInterrupt, SystemExit) để run manifest luôn được ghi trạng thái kết thúc hợp lệ.

## 3. Tool Surface Mapping & Delivery Contracts
- **Element Actionability**:
  - Kiểm tra danh sách `available_actions` của từng phần tử UI trước khi dispatch. Không tự ý gán action tĩnh khi element không hỗ trợ.
  - **CLI Flag Precision**: Khi ánh xạ action từ benchmark runner sang core CLI, phải đảm bảo cờ dòng lệnh chính xác 100% với định nghĩa của clap parser (ví dụ lệnh `get` và `is` dùng `--property`, không dùng `--prop` hay `--state`).
  - **Read/Inspect Action Permissiveness**: Các lệnh quan sát và kiểm tra trạng thái không gây đột biến (như `get`, `is`, `snapshot`) không được bị chặn bởi danh sách `available_actions` vốn chỉ khai báo các mutation patterns của control.
  - Ánh xạ đầy đủ toàn bộ v1 tool surface (`click`, `double_click`, `type_text`, `press_key`, `scroll`, `select`, `snapshot`, `find`, `wait`).
  - Khi model gặp ngoại lệ hoặc lỗi không parse được output, phải fail-closed ngay lập tức; cấm chuyển đổi lỗi của model thành lệnh `wait` thụ động.

## 4. Run Artifacts & Log Durability
- **Atomic & Line-Delimited Streaming**:
  - Các file log dữ liệu benchmark (`episodes.jsonl`, `steps.jsonl`, `artifacts.jsonl`) phải được ghi và flush ngay sau từng sự kiện (line-buffered with `flush()`/`fsync`).
  - **Artifact Record Tracking**: Bắt buộc tạo và kiểm tra bản ghi artifact tương ứng trong `artifacts.jsonl` bất cứ khi nào benchmark tạo snapshot, trace hoặc file bằng chứng, tuân thủ đúng schema `artifact.schema.json`.
  - Báo cáo đánh giá và manifest run (`baseline-report.md`, `run.json`) phải phản ánh đúng Git commit hash hiện tại của candidate đang được đánh giá, không được giữ nguyên commit cũ của plan ban đầu.
