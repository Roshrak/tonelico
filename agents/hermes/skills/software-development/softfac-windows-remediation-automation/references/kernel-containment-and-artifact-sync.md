# Windows Kernel Containment & Forensic Artifact Synchronization

Kinh nghiệm kỹ thuật chuyên sâu được đúc kết từ các vòng thẩm định gắt gao của Sol Reviewer (`gpt-6-sol`, reasoning: `high`) đối với findings `CU-F002`, `CU-F004`, và `CU-F009`.

---

## 1. Win32 Suspended Process Spawn & Job Object Containment (`CU-F009`)

### Vấn đề gốc rễ (Race Condition)
Khi một launcher trung gian (như batch script, shell wrapper, hoặc runner trung gian) spawn một tiến trình con rồi tự thoát ngay lập tức:
- Nếu gán Job Object sau khi spawn bằng `subprocess.Popen`, cửa sổ vài mili-giây giữa `Popen` và `AssignProcessToJobObject` là đủ để tiến trình con kịp sinh ra các cháu/chắt (detached processes) thoát ra ngoài Job Object.
- Luồng quét `psutil` hoặc WMI (`Win32_Process`) có chu kỳ lấy mẫu, hoàn toàn không thể bắt kịp các tiến trình sinh và thoát nhanh, dẫn đến rò rỉ tiến trình hệ thống (process leak).

### Giải pháp Win32 Kernel Chuẩn xác
Quy trình bắt buộc triển khai qua `ctypes.WinDLL('kernel32')`:
1. **Khởi tạo Job Object**:
   ```python
   h_job = kernel32.CreateJobObjectW(None, None)
   # Cấu hình JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
   ```
2. **Khai báo argtypes/restype tường minh 64-bit**:
   Trên Windows x64, mặc định `ctypes` coi return value là `c_int` (32-bit). Việc này sẽ cắt cụt các con trỏ handle `HANDLE` (64-bit), làm hỏng handle khi giá trị vượt quá dải 32-bit. Bắt buộc đặt:
   ```python
   kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
   kernel32.CreateJobObjectW.restype = wintypes.HANDLE
   kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
   kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
   kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
   kernel32.IsProcessInJob.restype = wintypes.BOOL
   kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
   kernel32.ResumeThread.restype = wintypes.DWORD
   ```
3. **Spawn ở trạng thái suspended**:
   Truyền cờ `CREATE_SUSPENDED = 0x00000004` vào Win32 `CreateProcessW`. Tiến trình được tạo nhưng luồng chính bị đóng băng ngay từ instruction đầu tiên trong kernel.
4. **Gán vào Job và xác minh**:
   - Gọi `kernel32.AssignProcessToJobObject(h_job, pi.hProcess)`.
   - Gọi `kernel32.IsProcessInJob(pi.hProcess, h_job, ctypes.byref(in_job))`. Kiểm tra `in_job.value == True` (fail-closed nếu false).
5. **Đánh thức tiến trình**:
   - Gọi `kernel32.ResumeThread(pi.hThread)`.
   - Đóng các handle trung gian `pi.hProcess` và `pi.hThread` bằng `CloseHandle` để giải phóng tài nguyên.
6. **Thu hồi triệt để khi kết thúc**:
   Trong hàm dọn dẹp (`cleanup_all`):
   - Đóng handle của Job Object (`CloseHandle(h_job)`).
   - Kernel Windows NT tự động hủy toàn bộ tiến trình con, cháu, chắt lập tức và vĩnh viễn mà không cần can thiệp user-space.

---

## 2. Đối soát Chéo Toàn Vẹn Hashes & Bảng Kê Artifacts (`CU-F002`)

### Cơ chế thẩm định forensic của Sol
Sol Reviewer không chỉ kiểm tra file code mà còn kiểm tra tính toàn vẹn của chuỗi chứng cứ (evidence ledger & manifests):
- `head_commit` và `head_tree` trong các file manifest phải khớp chính xác với Git commit HEAD đang được review.
- **Bẫy `artifacts.jsonl`**:
  Khi sửa đổi các file:
  - `benchmarks/windows-cu/design/baseline-manifest.json` (`art-manifest-0`)
  - `benchmarks/windows-cu/design/capability-matrix.md` (`art-capmat-0`)
  - `benchmarks/windows-cu/environment-manifest.json` (`art-envman-0`)
  - `benchmarks/windows-cu/baseline-report.md` (`art-baserep-0`)
  - `benchmarks/windows-cu/runs/.../run.json` (`art-runman-0`)
  Thì giá trị SHA-256 nội dung của chúng trên ổ đĩa sẽ thay đổi. Bảng kê `artifacts.jsonl` trong thư mục run ghi nhận trường `sha256` cho từng ID artifact trên. Nếu chỉ cập nhật commit hash trong file mà quên tính toán lại `sha256` và ghi vào `artifacts.jsonl`, Sol sẽ đánh fail-closed do checksum mismatch.

---

## 3. Strict Exact Matching & Tránh Name Collision (`CU-F004`)

- **Strict Exact Selector Match**: Khi so khớp selector UI với observed elements, tuyệt đối dùng exact matching (`target == observed`). Cấm match chéo ID (`#id`), Class (`.class`) hoặc display text.
- **Loại bỏ Display Name khỏi Bảng Ghi Đột Biến**: Trong các benchmark runner, chỉ lưu định danh phần tử duy nhất (`AutomationId`) vào danh sách `mutated_controls`. Tuyệt đối không lưu tên hiển thị (`name`), vì nhiều nút có thể mang nhãn trùng nhau (`OK`, `Cancel`, `Save`), gây ra xung đột giả (false collision) khi kiểm chứng tính độc lập của tương tác.
