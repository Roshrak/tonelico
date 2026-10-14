---
name: softfac-windows-operations
description: Use when running SoftFac v2 on Windows with Codex and AGY.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [coding, builder, agy, astra, sol, softfac, windows]
---

# SoftFac v2 Windows Operations & Runtime Guidelines

### QUY TẮC BẤT BIẾN TUYỆT ĐỐI CỦA HERMES ORCHESTRATOR:
0. CẤM PROMPT BUILDER LẬP KẾ HOẠCH / PHÂN TÍCH: Mọi prompt gửi cho AGY/Aider Builder PHẢI LÀ MỆNH LỆNH THI CÔNG TRỰC TIẾP (code, test, patch ngay lập tức trong 1 lượt duy nhất, cấm chia 2 lượt plan/code, cấm builder ngồi lên kế hoạch dài dòng).
1. TUYỆT ĐỐI KHÔNG TỰ SỬA CODE thay Builder dù bất kỳ lý do gì (kể cả khi test fail, nôn nóng, hay gặp lỗi nhỏ). MỌI finding, MỌI lỗi test BẮT BUỘC PHẢI ném prompt cho AGY Builder tự sửa 100%.
2. AGY Builder chỉ viết/sửa code và chạy test, CẤM AGY commit. Chỉ sau khi AGY sửa xong và tiến trình AGY thoát hoàn toàn (clean exit, không còn trong tasklist), Hermes Orchestrator mới chạy lại test suite độc lập rồi chính tay Hermes commit. TUYỆT ĐỐI KHÔNG gọi Sol Reviewer khi AGY chưa build xong và chưa thoát hoàn toàn khỏi tasklist.
3. TUYỆT ĐỐI KHÔNG TỰ Ý TẮT HOẶC HỦY TIẾN TRÌNH SOL REVIEWER khi đang chạy nếu không có chỉ thị rõ ràng của User, tránh làm lãng phí quota thẩm định.
4. Giữ nguyên kết nối proxy pool Antigravity (http://127.0.0.1:8045) cho AGY CLI.
5. CHỈ ĐƯỢC CHUYỂN BƯỚC / MILESTONE KHI SOL APPROVE 100%: Báo cáo tiến độ bắt buộc phải trích xuất log JSON approve thực tế từ Sol Reviewer làm bằng chứng xác thực, không báo cáo suông.


Quy trình vận hành SoftFac v2 trên Windows. File này phân tách rõ **invariant chung của SoftFac**, **cách gọi Reviewer**, **runbook Windows/AGY**, và **knowledge riêng của project `agent-desktop-win`** để tránh áp dụng nhầm project-specific rules cho codebase khác.

## 1. Scope, Precedence & Canonical Execution Path

- **Canonical flow:** `Astra Planner -> AGY Builder -> Runner Verifier -> Sol Reviewer -> (nếu REJECT: Builder batch-fix -> Runner -> Sol findings-only) -> Hermes publish approved candidate -> milestone n+1`.
- Astra lập Master Plan/chia milestone; mặc định **không có Sol plan review**.
- Builder viết/sửa code và test nhưng **không commit/publish**.
- Runner là deterministic verifier/stager và xác lập candidate identity; Runner không sửa source và không approve.
- Sol chỉ review đúng candidate identity do Runner xác lập. Full Review diễn ra một lần cho mỗi milestone; các vòng sau là Findings-Only Review cho findings còn mở.
- Chỉ Hermes Orchestrator được commit/publish **exact candidate đã được Sol approve**.
- Nếu có mâu thuẫn giữa các đoạn cũ/project appendix và các invariant trong mục 1–3, **mục 1–3 thắng**.
- Mục 5 (`agent-desktop-win`) chỉ áp dụng khi repository/project hiện tại đúng là `agent-desktop-win` hoặc user explicitly yêu cầu dùng các rule đó.

### Vai trò, Candidate Ownership & Commit Ownership (Canonical)
- **Phân định rõ ranh giới vai trò**:
  - **Hermes Orchestrator**: Điều phối luồng, quản lý lifecycle, khảo sát trạng thái tiến trình, soạn task spec, tiếp nhận/chuyển giao findings và là **tác nhân duy nhất được publish commit**. Hermes chỉ được commit/publish đúng candidate đã qua Runner deterministic verification + Sol approval.
  - **AGY Builder**: Chịu trách nhiệm viết/sửa code theo milestone hoặc findings và chạy các test cần thiết. **Builder tuyệt đối không được `git commit`, `git reset`, `git update-ref`, rewrite history hoặc tự publish candidate**.
  - **Runner Verifier**: Chịu trách nhiệm deterministic verification/staging, chạy gate/test cần thiết và xác lập candidate identity (`base_commit`, `candidate_id`). Runner không sửa source và không có quyền approve.
  - **Sol Reviewer**: Chịu trách nhiệm thẩm định adversarial độc lập trên đúng candidate identity do Runner xác lập.
- **Quy tắc khi Builder dừng giữa chừng (timeout/stalled)**:
  - Khi Builder (`agy.exe`) dừng tiến trình (do chạm giới hạn `--print-timeout` hoặc subshell exit), **tuyệt đối Orchestrator không được tự ý vào sửa code thay cho Builder**.
  - Hành động đúng của Orchestrator:
    1. Kiểm tra diff và log (`git status`, `git diff`, test failures) để nắm rõ phần công việc Builder đã làm được và điểm đang tắc.
    2. Soạn tiếp instruction task nối tiếp (continuation prompt) chứa đầy đủ lỗi test hiện tại, danh sách checklist còn dang dở trong `tasks/todo.md`.
    3. Tái kích hoạt Builder (`agy`) tiếp tục xử lý cho đến khi hoàn thiện thay đổi và các test cần thiết, **không commit**.
    4. Sau khi Builder hoàn tất, Runner deterministic-verify/stage và xác lập candidate identity; chỉ khi đó mới gọi Sol Reviewer trên đúng candidate. Nếu Sol `APPROVE`, Hermes mới publish đúng candidate đã được duyệt; nếu Sol `REJECT`, quay lại repair loop mà không tạo commit trung gian từ AGY.

## 2. Core SoftFac Orchestration Protocol

### Model Selection Invariant
- Khi người dùng chỉ định rõ model cho Builder (ví dụ `gemini-3.8-flash-high`), **bắt buộc giữ nguyên model đó**.
- Tuyệt đối không tự ý đổi sang model khác khi gặp quota tạm thời, trừ khi người dùng đồng ý/chỉ thị chuyển đổi.
- Quota cooldown không trao quyền cho Hermes code thay Builder hoặc thay đổi commit ownership.

### Quy trình Khởi động Phase Mới (Astra Direct-to-Builder Execution Protocol)
- **Bỏ qua Sol Review Plan (Direct from Astra to Builder)**:
  - Khi Astra Planner (`gpt-6-astra`, `reasoning_effort=medium`) hoàn thành việc lập kế hoạch kỹ thuật chi tiết (Master Plan) cho phase hoặc milestone mới, **tuyệt đối không đưa plan cho Sol Reviewer thẩm định lại**.
  - Việc thẩm định lại kế hoạch của Astra gây lãng phí thời gian và làm nghẽn tiến độ không cần thiết.
  - Ngay sau khi Astra xuất bản Master Plan, Orchestrator lập tức chuyển giao bản kế hoạch đó (bắt đầu từ **CU-M0/M1**) cho Builder AGY (`gemini-3.8-flash-high`) để tiến hành triển khai mã nguồn ngay lập tức.
- **Xử lý Session Planning của Astra Khi Chạm Quota (Astra Planning Continuation)**:
  - Khi Astra (`gpt-6-astra`) đang phân tích và lên Master Plan dở dang mà bị hết quota (`usage_limit_reached` / `rate_limited`):
    1. Tuyệt đối không xóa bỏ hay hủy ngang ngữ cảnh; bảo toàn file chỉ thị gốc (ví dụ `ASTRA_WINDOWS_COMPUTER_USE_AMPLIFICATION_DIRECTIVE.md`) và log phân tích đã sinh ra trong `Temp/`.
    2. Khi người dùng yêu cầu tiếp tục hoặc quota đã reset, Orchestrator kích hoạt ngay script chuyên dụng tiếp tục nạp lại đúng chỉ thị gốc và codebase cho Astra (`gpt-6-astra`, `reasoning_effort=medium`, cờ `--sandbox danger-full-access`, bọc `cmd.exe /c` và truyền prompt qua `stdin` để tránh giới hạn ký tự Windows).
    3. Cronjob chờ đợi chỉ là phương án phụ trợ khi quota chưa reset; khi quota đã sẵn sàng, phải gọi ngay lập tức mà không chờ cronjob.
    4. Ngay khi Astra hoàn thành tạo file plan: tuân thủ nghiêm ngặt quy tắc bỏ qua Sol review plan, tự động trích xuất nội dung Milestone 1 giao thẳng cho AGY Builder (`gemini-3.8-flash-high`) triển khai ngay.
- **Quy trình Review Sau Khi Builder Hoàn Thành**:
  - Chỉ sau khi Builder AGY hoàn thành code và các test cần thiết của Milestone đó, **Runner Verifier** mới deterministic-verify/stage và xác lập `base_commit` + `candidate_id`.
  - Sol Reviewer chỉ được gọi để **Full Milestone Review** trên đúng candidate identity do Runner xác lập.
  - Nếu Sol trả findings: Builder sửa toàn bộ findings trong một batch, **không commit**; Runner xác lập candidate mới; Sol thực hiện **Findings-Only Review**. Lặp đến khi `APPROVED 100%`.
  - Chỉ Hermes Orchestrator được commit/publish exact candidate đã được Sol approve.

### Chu kỳ Review Milestone & Gate Chuyển Step (Bắt buộc theo lệnh người dùng)
- Sau khi hoàn thành **mỗi milestone**: Builder kết thúc implementation/test → Runner deterministic-verify/stage + xác lập candidate identity → **BẮT BUỘC Sol Full Milestone Review** trước khi được phép tiến hành milestone mới.
- Khi Sol trả về `REJECT` kèm danh sách findings:
  1. Không khởi động milestone/step tiếp theo. Giữ nguyên ranh giới **single active writer** và candidate lineage hiện tại.
  2. Tạo prompt chi tiết toàn bộ findings còn mở (`FINDING-1` đến `FINDING-N`) và dispatch cho Builder AGY để sửa **toàn bộ batch**; Builder chạy test nhưng **không commit**.
  3. Runner deterministic-verify/stage và xác lập candidate identity mới. Sau đó **CHỈ kích hoạt Sol Findings-Only Review** cho các findings còn mở.
  4. **TUYỆT ĐỐI KHÔNG ĐƯỢC CHUYỂN SANG STEP MỚI** khi chưa có phán quyết `APPROVED` cho toàn bộ 100% findings từ Sol Reviewer.

### Cấm Tuyệt Đối Ảo Giác "Final Review" Khi Chưa Được Sol Duyệt 100% Findings
- **Quy tắc Kiểm tra Bằng chứng Kết quả Thực tế (Anti-Hallucination Gate)**:
  - Tuyệt đối không được tự ý đặt tên prompt hay gọi một lượt review là "Final Review" hoặc tạo commit đóng milestone (như `docs: close Master Milestone N...`) khi chưa có file JSON kết quả thực tế mang trường `\"overall_verdict\": \"APPROVED\"` từ Sol Reviewer.
  - Phải phân biệt rõ ràng giữa các round review finding liên tiếp (Round 1, 2, ..., 10, 11) và kết quả duyệt cuối cùng. Khi một finding (ví dụ `FINDING-TRACE`) bị Sol từ chối liên tiếp qua nhiều vòng (do fail-open locking, test contention, thiếu isolated temp dir), Orchestrator phải trung thực báo cáo đúng số round thực tế và tiếp tục đưa finding đó cho Builder sửa.
  - **Nghiêm cấm báo cáo sai lệch hay làm tròn số round review** (ví dụ thực tế chạy đến Round 10-11 nhưng lại báo cáo chỉ có 7 round và đã duyệt ở round cũ).
  - Trước khi kết luận một Milestone đã PASS, Orchestrator bắt buộc phải đọc trực tiếp file JSON kết quả mới nhất của Sol (`sol_*_result.json`), kiểm tra `candidate_id`/`target_commit` tương ứng và xuất minh bạch toàn văn nội dung verdict làm bằng chứng cho người dùng.
  - **Cấm review final khi chưa duyệt hết 100% findings**: Bắt buộc giải quyết và review từng finding của milestone hiện tại cho đến khi tất cả các finding chuyển sang `APPROVED`. Tuyệt đối không được gộp tắt hay kích hoạt vòng \"final holistic review\" khi milestone vẫn còn finding bị `REJECTED`.

### Batch Remediation & Holistic Code Review Protocol (Bắt Buộc Khi Sửa Nhiều Findings)
- **Cấm Tuần Tự Hóa Sửa Từng Finding Đơn Lẻ (Strict Anti-Serialization Rule)**:
  - Khi một lượt review (Initial Holistic Review hoặc Milestone Review) phát hiện $N$ findings (ví dụ `F001` đến `F009`), **TUYỆT ĐỐI KHÔNG ĐƯỢC CHẠY THEO LUỒNG TUẦN TỰ**:
    `fix F001 -> Sol review -> fix F002 -> Sol review -> ...`
  - Mô hình tuần tự hóa từng finding đơn lẻ gây tắc nghẽn nghiêm trọng, lãng phí vòng lặp và làm người dùng ức chế.
  - **Quy trình Batch Remediation Chuẩn Hóa**:
    1. Orchestrator gom toàn bộ $N$ findings vào **một task duy nhất** bàn giao cho Builder AGY (`gemini-3.8-flash-high`) triển khai trọn gói trong một implementation run.
    2. Builder AGY sửa đồng bộ toàn bộ $N$ findings trên mã nguồn sản xuất, viết đầy đủ các bài regression test tương ứng cho từng finding, chạy cumulative tests (`cargo test`, `cargo clippy`, `cargo fmt`).
    3. Builder chạy cumulative tests nhưng **không commit**. Runner deterministic-verify/stage toàn bộ thay đổi và xác lập candidate identity mới.
    4. Triệu hồi Sol Reviewer (`gpt-6-sol`, reasoning `high`) **đúng một lần** cho đợt **Findings-Only Batch Review** trên đúng candidate đó, đánh giá đồng loạt cả $N$ findings.
    5. Nếu Sol còn từ chối một tập con (ví dụ F003 + F005), tiếp tục đưa toàn bộ tập con đó vào Batch Remediation Round 2 (`scope = F003 + F005`), tuyệt đối không quay lại sửa lẻ. Chỉ Hermes commit/publish sau khi candidate được Sol approve.

### Quản lý Phạm vi Review Nghiêm ngặt (Strict Scope Control & Anti-Redundant Review)
- Khi thực thi các vòng Review tiếp nối (Findings-Only Review) sau vòng đầu tiên:
  - **Bắt buộc kiểm tra lịch sử các vòng review trước**: Đọc kỹ các file kết quả review trước đó (`sol_*_result.json`) để xác định chính xác finding nào đã được `APPROVED` và finding nào bị `REJECTED`.
  - **Giới hạn phạm vi tuyệt đối (Scope Control)**: Chỉ gửi review các finding còn tồn đọng/bị reject (ví dụ chỉ review `FINDING-M4-3` nếu `M4-1`, `M4-2`, `M4-4` đã approved). **Tuyệt đối không yêu cầu Reviewer thẩm định lại các finding đã được duyệt**.
  - **Tiêu chí đóng Milestone**: Ngay khi finding cuối cùng còn lại nhận phán quyết `APPROVED`, lập tức đóng milestone hiện tại và chuyển sang milestone tiếp theo theo roadmap mà không được lặp lại review full milestone hay review thừa phạm vi.

### Quy tắc Chuyển Milestone & Quy Trình Khởi Động Milestone Mới (MANDATORY GATE PROTOCOL)
- **LUÔN TỰ ĐỘNG CHUYỂN SANG MILESTONE N+1 MỚI KHI SOL REVIEWER PHÊ DUYỆT 100% FINDINGS CỦA MILESTONE N** (Standing Directive):
  - Khi Sol Reviewer phê duyệt 100% findings của Milestone N, Orchestrator lập tức đóng Milestone N (cập nhật tasks/todo.md) và **tự động chuyển sang Milestone N+1 mới ngay lập tức**, tuyệt đối không dừng lại hỏi ý kiến người dùng hay xin phép xác nhận.
- **Quy Trình Nghiêm Ngặt Khi Khởi Động Milestone N+1 (Show PIDs & Không Nhảy Cóc Gọi Reviewer)**:
  - **BƯỚC 1: Khởi động Supervisor Watchdog Daemon**: Kiểm tra và đảm bảo Watchdog Singleton đang chạy, báo cáo rõ PID của Supervisor.
  - **BƯỚC 2: Giao việc cho Builder (AGY / `gemini-3.8-flash-high`)**: Soạn task spec chi tiết cho Milestone mới, khởi chạy AGY Builder qua script runner độc lập trong nền.
  - **BƯỚC 3: Báo cáo đầy đủ PIDs thời gian thực**: Bắt buộc báo cáo PID của Builder (`agy.exe`), PID của Supervisor (`supervisor_daemon_singleton.py`), và trạng thái tiến trình thực tế.
  - **BƯỚC 4: TUYỆT ĐỐI KHÔNG ĐƯỢC GỌI SOL REVIEWER KHI BUILDER CHƯA CODE XONG**:
    - Cấm tuyệt đối việc Orchestrator tự biên tập hay vội vã triệu tập Sol Reviewer Full Review cho Milestone N+1 khi Builder chưa code xong và chưa tạo ra candidate state hoàn chỉnh để Runner kiểm chứng. **Không yêu cầu và không cho phép AGY tạo commit trước review**.
    - Chỉ sau khi Builder (`agy.exe`) hoàn thành triển khai mã nguồn và các kiểm thử cần thiết (cargo test, cargo clippy, cargo fmt), Runner mới deterministic-verify/stage và xác lập candidate identity. Orchestrator chỉ được gọi Sol Reviewer Full Review trên candidate đó; **chỉ sau Sol APPROVE, Hermes mới commit đúng exact approved candidate**.
- **Quy tắc Kiểm Soát Phạm Vi Thẩm Định (Strict Scope Control & Anti-Redundant Review)**:
  - Khi Reviewer đã phê duyệt một phần các findings (ví dụ `FINDING-1` APPROVED, `FINDING-2` REJECTED), ở các round tiếp theo CHỈ ĐƯỢC PHÉP gửi review các findings còn bị REJECTED.
  - Tuyệt đối không bắt Reviewer thẩm định lại các findings đã APPROVED ở các round trước đó. Khi finding cuối cùng được duyệt, đóng ngay milestone và chuyển tiếp sang milestone mới.

### Vòng lặp Tự động Hóa Findings Remediation & Review Protocol (Auto Loop & PID Reporting)
- **Tự động lặp lại quy trình sửa finding và review (Auto Loop)**:
  - Khi Sol trả về `REJECTED`, Orchestrator tự động trích xuất toàn bộ lý do kỹ thuật chi tiết, soạn task spec, kích hoạt Builder sửa và tiếp tục gọi Reviewer thẩm định findings-only.
  - **Quy tắc Batch Remediation Bắt buộc (Batch-Remediate All Findings Before Re-review)**:
    - Khi một lượt review (như Initial Holistic Review hoặc milestone review) phát hiện N findings (ví dụ `F001` đến `F009`), **TUYỆT ĐỐI KHÔNG ĐƯỢC TUẦN TỰ HÓA SỬA TỪNG FINDING LẺ** (`fix F001 -> Sol review -> fix F002 -> Sol review...`). Mô hình tuần tự hóa từng finding đơn lẻ gây lãng phí vòng lặp, nghẽn pipeline và làm chậm tiến độ theo cấp số nhân. Người dùng sẽ phản đối gay gắt khi thấy sửa lắt nhắt từng cái một.
    - Orchestrator bắt buộc phải giao toàn bộ N findings trong cùng một đợt nhiệm vụ (remediation batch) cho Builder AGY giải quyết đồng thời trong một implementation run duy nhất.
    - Builder AGY phải sửa toàn bộ danh sách findings, viết các bài test hồi quy (focused regression tests) tương ứng cho từng finding và chạy cumulative test suite nhưng **không commit**. Runner deterministic-verify/stage + xác lập candidate identity mới trước khi bàn giao candidate đó cho Sol Reviewer.
    - Sol Reviewer chỉ được triệu hồi một lần duy nhất cho đợt review findings-only bao quát toàn bộ danh sách findings đó.
    - Nếu ở vòng sau Sol còn từ chối một tập con findings (ví dụ `F003` và `F005`), tiếp tục áp dụng batch remediation cho toàn bộ tập con đó (`scope = F003 + F005`), tuyệt đối không quay lại sửa lẻ từng cái.
  - **Khởi chạy Batch AGY Builder qua Background Process Tách Biệt**:
    - Khi giao batch nhiều findings cho AGY (`gemini-3.8-flash-high`), prompt task sẽ rất dài (thường > 20KB). Bắt buộc phải ghi file task tạm (`agy_batch_*.txt`), tạo script launcher Python (`subprocess.Popen` tách biệt) và khởi chạy ngầm. Tuyệt đối không chạy đồng bộ blocking trong subshell terminal foreground vì sẽ bị timeout (`Exit 124`).
    - Theo dõi tiến trình qua `tasklist | grep -i agy` và monitor liveness bằng `psutil` hoặc polling script. Không được ngắt giữa chừng khi AGY đang phân tích và áp dụng các thay đổi mã nguồn.
  - Vòng lặp remediation chạy liên tục mà không cần dừng lại hỏi người dùng cho đến khi **100% findings đều được Sol Reviewer APPROVED**.
  - **TỰ ĐỘNG CHUYỂN MILESTONE N+1 (Standing Directive)**: Khi Sol Reviewer đã phê duyệt toàn bộ 100% findings của Milestone N, **LUÔN tự động chuyển ngay sang Milestone N+1 mới** mà không dừng lại hỏi ý kiến người dùng hay xin phép xác nhận.

### Tự Động Kích Hoạt Loop và Bắt Sự Kiện Thay Thế Theo Dõi Thủ Công
- **Tự động hóa hoàn toàn Orchestrator Trigger (Anti-Manual Monitoring)**:
  - Người dùng không có nghĩa vụ phải ngồi canh terminal hay nhắc Orchestrator kiểm tra khi nào AGY hoặc Codex chạy xong.
  - Cần duy trì daemon nền (`auto_orchestrator_daemon.py`) liên tục bắt sự kiện chuyển đổi trạng thái `running -> stopped` của `agy.exe` và `codex.exe`.
  - Khi worker hoặc reviewer thoát, daemon phải ghi log và kích hoạt ngay bước tiếp theo (hoặc Orchestrator chủ động polling bằng vòng lặp nền có timeout dài) để tự động tiếp nối quy trình từ Builder -> Reviewer -> Builder Remediation mà không dừng lại chờ người dùng gõ lệnh nhắc nhở.
  - **Tránh Lỗi Ký tự Điều khiển Windows (`\r\n`) Khi Sinh Shell Script**: Tuyệt đối không dùng `$(powershell -Command ...)` nội suy trực tiếp trong bash script gán `GOOGLE_GEMINI_BASE_URL` hoặc `GEMINI_API_KEY` vì PowerShell luôn trả về `\r\n`. Khi gán vào biến môi trường, Go HTTP client trong AGY sẽ bị crash với lỗi `createAPIURL: error parsing base URL: parse "http://127.0.0.1:8045\r": net/url: invalid control character in URL`. Luôn dùng Python đọc biến môi trường, strip `\r` và `\n` rồi ghi thẳng chuỗi sạch (hardcoded/clean string) vào shell script runner.
  - **Dọn dẹp Đĩa Chủ Động Tránh Cạn Kiệt Ổ C:**: Quá trình build/test Rust lặp lại nhiều vòng làm phình to `target/` rất nhanh. Phải chủ động chạy `cargo clean` hoặc dọn temp khi dung lượng trống dưới 10GB để tránh lỗi out-of-disk gây crash hoặc treo tiến trình.

### Supervisor Watchdog Daemon Giám sát Tự động & Active Lifecycle Dispatcher
- Khi dispatch tác vụ nền dài cho Builder (AGY) hoặc Reviewer (Codex), có thể xảy ra tình trạng tiến trình con kết thúc sớm, wrapper/subshell thoát trước, hoặc PID bị tái sử dụng khiến việc nhìn riêng process name/PID cho kết luận sai.
- Triển khai **Singleton Watchdog Daemon** (ví dụ `supervisor_daemon_singleton.py`) chạy nền chu kỳ 5 giây, có PID file (`supervisor.pid`) và heartbeat/state file (`supervisor_status.json`).
- **Nguyên nhân cốt lõi khiến vòng lặp bị dừng sau khi AGY hoặc Codex thoát**:
  1. Daemon chỉ được thiết kế là **Passive Monitor** (chỉ thăm dò `tasklist` rồi ghi file json trạng thái mà không phát hiện sự kiện chuyển đổi trạng thái `running -> stopped`).
  2. Không có cơ chế **State Transition Event Dispatcher**: khi worker thoát, hệ điều hành chỉ thu hồi process, nếu Orchestrator không chủ động polling hoặc Daemon không có trigger thì vòng lặp rơi vào trạng thái im lặng, phải chờ user can thiệp thủ công.
- **Cơ chế Active Lifecycle Dispatcher Khắc phục**:
  - Daemon phải theo dõi transition: khi `agy_running` chuyển từ `True -> False` (Builder hoàn thành) hoặc `codex_running` chuyển từ `True -> False` (Reviewer hoàn thành), tự động kích hoạt logic chuyển bước (`trigger_next_step()`).
  - Ghi nhận trạng thái và phase hiện tại vào file điều phối tập trung `softfac_orchestrator_state.json` (bao gồm `phase: "BUILDER_RUNNING" | "BUILDER_DONE" | "REVIEWER_RUNNING" | "REVIEWER_DONE"`, timestamp, `base_commit`, `candidate_id`).
  - Tự động kiểm tra file kết quả (`sol_*_result.json` hoặc git diff/status) để quyết định bước tiếp theo: nếu review `APPROVED 100%`, tự động bump milestone; nếu `REJECTED`, tự trích xuất findings bị từ chối và khởi động lại Builder remediation.
- **Autonomous Infinite Pipeline Execution (Vòng lặp Vô tận Tự hành đến Hoàn tất Toàn bộ Plan)**:
  - Khi người dùng chỉ thị chạy liên tục / loop tới cùng (ví dụ "loop vô tận tới khi xong hết plan, không dừng lại vì bất cứ điều gì"):
  - **Orchestrator không được dừng lại chờ đợi hay xin ý kiến** ở bất kỳ bước nào:
    1. Builder hoàn thành (`BUILDER_DONE`) -> Tự động xác lập candidate, sinh prompt Sol review và spawn Sol Reviewer ngay lập tức.
    2. Sol Reviewer hoàn thành (`REVIEWER_DONE`):
       - Nếu có finding bị `REJECTED`: Trích xuất danh sách finding bị từ chối, tạo task remediation mới và spawn AGY Builder xử lý tiếp (scope-control: chỉ review các finding bị reject).
       - Nếu `APPROVED 100%`: Hermes Orchestrator đóng milestone hiện tại bằng commit/publish đúng candidate đã được duyệt (và cập nhật tài liệu nếu cần), rồi chuyển sang Milestone tiếp theo và khởi động Builder mới.
    3. Duy trì liveness của Active Supervisor Dispatcher (`supervisor_daemon_singleton.py`) liên tục để đảm bảo quá trình không bị gián đoạn khi máy tính restart hoặc subshell thoát.
- Khi giám sát `agy.exe` / `codex.exe`, bắt buộc gắn PID với **process creation identity / generation**, heartbeat, task/review identity và lease hiện hành. Việc một PID biến mất hoặc process name không còn xuất hiện **không đủ** để tự động kết luận worker đã chết và không đủ quyền để restart.
- Khi nghi ngờ worker/reviewer bị rớt, Watchdog phải kiểm tra tối thiểu: heartbeat đã hết hạn; PID + creation identity không còn hợp lệ; không còn descendant/process con đang tiếp tục chạy hoặc ghi worktree; task/review lease vẫn thuộc execution đó; và chưa có replacement worker đang hoạt động. Sau đó Watchdog chỉ phát sự kiện như `WORKER_CRASHED`, `REVIEWER_CRASHED` hoặc `LIVENESS_UNCERTAIN` cho Hermes Orchestrator.
- **Cấm Watchdog tự spawn/restart AGY, Codex hoặc tự gọi `resume`**. Chỉ **Hermes Orchestrator** được quyết định recovery/re-dispatch sau khi reconcile trạng thái repo/process tree và xác nhận invariant **single active writer**. Nếu trạng thái process/lease còn mơ hồ, phải giữ `LIVENESS_UNCERTAIN` và không tạo worker thứ hai.
- **Bảo toàn Liveness của chính Supervisor**: Trước và sau mỗi lượt dispatch hoặc báo cáo tiến trình, Orchestrator kiểm tra PID + creation identity + heartbeat của Supervisor Watchdog Daemon. Nếu chính Supervisor đã chết hoặc heartbeat hết hạn, Orchestrator được phép khởi động lại **Supervisor daemon** và báo cáo PID mới; quyền này không đồng nghĩa với việc Watchdog được tự restart Builder/Reviewer.

### Quy trình Kịp thời Báo cáo Kết quả Sol Reviewer & Điều phối Remediation Loop
- **Báo cáo Ngay khi có Kết quả**: Khi tiến trình Sol Reviewer (`codex.exe`) hoàn tất và đã tạo file kết quả (ví dụ `sol_m*_result.json`), Orchestrator phải lập tức phân tích và báo cáo kết quả chi tiết cho người dùng (trích xuất summary, finding statuses, overall_status JSON).
- **Phân nhánh Quyết định Theo Kết quả**:
  - Nếu kết quả là `REJECTED`: Orchestrator không dừng tiến trình hay hỏi ý kiến người dùng; lập tức kích hoạt vòng lặp tự động (Auto Loop) chuyển giao finding còn tồn đọng cho AGY Builder khắc phục (chỉ sửa finding-only), chạy test nhưng **không commit**, sau đó Runner deterministic-verify/stage candidate mới và Sol Reviewer thực hiện findings-only recheck. Chỉ khi toàn bộ findings được `APPROVED`, Hermes mới commit đúng exact approved candidate.
  - Nếu kết quả là `APPROVED 100%`: Đóng dứt điểm milestone hiện tại (cập nhật docs/tasks/todo.md) và tự động chuyển sang milestone n+1 mới ngay lập tức.
- **Duy trì Thông tin Liveness của Supervisor**: Bắt buộc kiểm tra và báo cáo PID của Supervisor Watchdog Daemon (`supervisor_daemon_singleton.py`) cùng với PID của Builder/Reviewer trong mọi thông báo trạng thái.

## 3. Sol Reviewer Invocation, Evidence & Reporting

### Sol Invocation Policy (Canonical)
- **FULL REVIEW / FINDINGS-ONLY REVIEW dùng để certify candidate code phải chạy qua tool-enabled environment** (`codex exec` hoặc `CodexRoleClient` tương đương) trên đúng workspace/candidate.
- Raw HTTP không có filesystem/shell/Git/test authority; chỉ dùng health/quota probe hoặc tác vụ không cần tools.
- HTTP success không phải review evidence. Approval chỉ hợp lệ khi có output/verdict của Sol trên đúng candidate identity và artifact JSON/result tương ứng.

### Cấu hình Cờ Dòng Lệnh và Sandbox cho Codex CLI (v0.153.1+)
- Cờ bypassed approvals trong `codex exec`: Cờ chính xác là `--dangerously-bypass-approvals-and-sandbox` (hoặc `--dangerously-bypass-approvals-and-deny-user-interaction` trong một số context). Nếu truyền nhầm tên cờ CLI sẽ thoát ngay với lỗi `error: unexpected argument ... tip: a similar argument exists: '--dangerously-bypass-approvals-and-sandbox'`.
- Khi gọi `codex exec` trực tiếp hoặc qua script wrapper, luôn sử dụng `--dangerously-bypass-approvals-and-sandbox` kết hợp `-c model_reasoning_effort=high` (hoặc cấu hình qua `CodexRoleClient` trong thư viện `hermes_factory_v2.py`).

### Bóc tách banner đầu ra của Codex CLI
- Khi `CodexRoleClient` (dùng cho Astra / Sol) gọi `codex exec`, CLI luôn in ra banner thông tin (`OpenAI Codex v0.153.1\n...\ncodex\n`) và footer thống kê (`\ntokens used\n...`).
- Hàm `parse_json_object` trong `hermes_factory_v2.py` phải bóc tách đoạn text JSON nằm giữa `\ncodex\n` và `\ntokens used\n` để tránh lỗi parse JSON.

### Khởi chạy Sol Reviewer qua Python: Xử lý Argument Types & Tránh Hang Tiến trình
- **Khởi chạy Codex CLI với Full Tool Access (Shell/Git/Cargo Execution)**:
  - Khi Sol Reviewer (`gpt-6-sol`) cần thực hiện thẩm định thực tế (đọc filesystem, chạy `cargo test`, `git log`, inspect repository), **bắt buộc chạy trực tiếp qua `codex exec` trên workspace repo**:
    `[r"C:\Users\HH18\AppData\Local\hermes\bin\codex.CMD", "exec", "--ephemeral", "-m", "gpt-6-sol", "-c", "reasoning_effort=high", "--sandbox", "danger-full-access", "-C", r"<workspace>", "-"]`
    kèm prompt truyền qua `stdin` (không truyền qua argument dòng lệnh để tránh vượt giới hạn độ dài ký tự).
  - **Mọi FULL REVIEW và FINDINGS-ONLY REVIEW dùng để certify code bắt buộc chạy trong tool-enabled environment (`codex exec`/`CodexRoleClient`)** để Sol có filesystem, Git, shell và khả năng chạy test. Tuyệt đối không dùng raw HTTP để certify code review, vì raw HTTP không có tool environment và Sol có thể từ chối với lý do: *"I cannot perform or truthfully certify this review... because no filesystem, shell, Git, build, or test-execution tools are available."*
- **Quy định kiểu dữ liệu tham số của `CodexRoleClient.call(...)`**:
  - Tham số `usage_path` và `output_path` **bắt buộc phải là đối tượng `pathlib.Path`**, tuyệt đối không truyền chuỗi `str`. Hàm `call()` gọi trực tiếp `usage_path.parent` và `output_path.parent`; nếu truyền `str` sẽ văng ngoại lệ `AttributeError: 'str' object has no attribute 'parent'`.
  - Giá trị trả về của `client.call(...)` có thể là một `dict` (chứa các trường phân tích cú pháp) hoặc chuỗi `str` tùy theo chế độ phản hồi. Khi ghi ra file kết quả `sol_*_result.json`, bắt buộc kiểm tra `if isinstance(resp, dict): json.dump(resp, out, indent=2) else: out.write(resp)`. Tuyệt đối không gọi trực tiếp `out.write(resp)` vì sẽ gây `TypeError: write() argument must be str, not dict`.
- **Tránh Foreground Hang khi Gọi Codex CLI qua Terminal Subshell**:
  - `CodexRoleClient.call()` bên trong sẽ kích hoạt `codex exec` chạy qua `subprocess`. Trên môi trường Windows MSYS/Git-bash, lệnh gọi đồng bộ ở foreground có thể vượt quá timeout terminal (120s) hoặc bị nuốt luồng I/O dẫn đến ngắt lệnh (`Exit 124`).
  - Luôn khởi chạy script Sol Reviewer bằng tiến trình nền tách biệt (`subprocess.Popen` từ Python hoặc `terminal(..., background=true)`) hoặc script wrapper bọc `cmd.exe /c`, sau đó theo dõi liveness của `codex.exe` thông qua Supervisor Watchdog Daemon.

### Tránh Lỗi Gọi API & Bóc Tách Dữ Liệu Sol Reviewer
- **Khởi tạo `CodexRoleClient` đúng signature**:
  - `CodexRoleClient` nhận `workspace_path` (đường dẫn worktree/repo). **Tuyệt đối không truyền `model` vào `CodexRoleClient.__init__()`** vì sẽ gây `TypeError: CodexRoleClient.__init__() got an unexpected keyword argument 'model'`.
  - Tham số `model` (ví dụ `model='gpt-6-sol'`), `role='reviewer'`, `provider='codex_local_access'`, `reasoning='high'`, `timeout=1200` bắt buộc phải truyền vào method `client.call(...)`.
- Khi invoke `client.call(...)` trực tiếp:
  - Bắt buộc truyền đầy đủ các keyword arguments bắt buộc: `role='reviewer'`, `provider='codex_local_access'`, `model='gpt-6-sol'`, `prompt=prompt_text`, `usage_path=Path(...)`, `output_path=Path(...)`, `reasoning='high'`, `timeout=1800`.
  - **Lưu ý quan trọng về signature**: `CodexRoleClient.call()` KHÔNG nhận tham số `reasoning_effort` (gây `TypeError: unexpected keyword argument 'reasoning_effort'`), chỉ nhận `reasoning`. Thiếu `provider`, `usage_path`, `output_path`, `timeout` sẽ gây `TypeError: missing 4 required keyword-only arguments`. Không truyền argument `cwd`.
  - Giá trị trả về từ `client.call(...)` là một `dict` (chứa các trường `content`, `usage`, `exit_code`, v.v.), **không phải string**. Tuyệt đối không dùng `f.write(response)` mà phải dùng `json.dump(response, f, indent=2)` hoặc `f.write(response.get('content', ''))`.
  - Kết quả in ra từ Codex CLI có thể kèm text trước/sau khối JSON hoặc trailing commentary dẫn đến `JSONDecodeError: Extra data: line ...`. Khi parse kết quả review từ file output, luôn dùng balanced brace extraction (tìm `{` đầu tiên và đếm mở/đóng ngoặc nhọn để cắt đúng substring JSON hợp lệ) trước khi gọi `json.loads`.

### Local Codex HTTP Service: Chỉ Dùng cho Health/Quota Probe, Không Certify Review
- Local Codex service hiện kết nối tới API pool `http://localhost:13844/v1` với model `gpt-6-sol` và token `agt_codex_N0ogpcmP85D728nGpWbVU5YRbdLpCtrA`.
- Raw HTTP **chỉ được dùng cho health check, quota/cooldown probe, hoặc tác vụ văn bản không cần filesystem/shell/Git/test**.
- **Cấm** dùng `/v1/responses`, `/v1/chat/completions` hoặc bất kỳ raw HTTP endpoint nào để thay thế `codex exec` cho Full Review, Findings-Only Review hoặc bất kỳ verdict nào dùng để certify candidate code.
- Probe quota nên dùng payload tối thiểu (ví dụ input ngắn và giới hạn output nhỏ) để đọc nhanh `429`, `reset_time`/`reset_seconds` mà không tiêu tốn đáng kể quota.
- Khi cần review thật: dùng `codex exec`/`CodexRoleClient` trên đúng workspace/candidate; HTTP probe thành công **không phải bằng chứng** candidate đã được review hay approved.

### Báo cáo Trạng thái & Giám sát Tiến trình Sol Reviewer (Codex)
- **Truy vết chính xác PID của Codex Engine**:
  - Khi gọi Sol Reviewer qua Python (`CodexRoleClient.call`), hệ thống sẽ khởi tạo một chuỗi tiến trình: `python.exe` (runner wrapper) -> `cmd.exe` -> `codex.exe` (core engine) -> `codex-code-mode-host.exe` -> `cockpit-cliproxy.exe`.
  - Khi người dùng yêu cầu PID của Codex Reviewer, bắt buộc phải truy vấn và cung cấp chính xác PID của tiến trình `codex.exe` thực tế (qua PowerShell `Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -match "codex"}` hoặc `tasklist`), không được báo cáo PID của python wrapper hay subshell.
- **Tách biệt subshell khởi tạo và tiến trình phân tích chính**:
  - Khi khởi chạy Sol Reviewer qua runner script chạy nền trong bash subshell (ví dụ `python run_sol.py > log 2>&1`), subshell bọc ngoài (bash / python) có thể hoàn thành việc bàn giao và ghi nhận kết thúc trước, trong khi tiến trình phân tích trí tuệ nhân tạo thực sự (`codex.exe` và `codex-code-mode-host.exe`) vẫn đang hoạt động ngầm.
  - Khi nhận thông báo process hoàn tất (`proc_... exited`), Orchestrator phải kiểm tra `tasklist | grep -i codex` hoặc `psutil` để xác định chính xác tiến trình `codex.exe` còn đang chạy hay đã thực sự hoàn thành trước khi vội vã báo cáo hoặc đọc file kết quả.
- **Tiêu chí Hoàn thành Thẩm định**: Chỉ coi Sol Reviewer đã xong khi cả `codex.exe` đã thoát và file kết quả JSON (ví dụ `sol_m4_round3_result.json`) đã được ghi đầy đủ dữ liệu hợp lệ trên đĩa.

### Nhận diện Chính xác Cây Tiến trình Builder & Reviewer (Anti-Process-Misidentification)
- Khi khởi chạy background tasks qua terminal tool (đặc biệt qua shell wrappers như `bash run_agy.sh`), PID trả về từ wrapper (`session_id`) thường là PID của subshell `bash.exe` (ví dụ Git for Windows / MSYS bash), KHÔNG PHẢI PID của binary AI engine thực sự (`agy.exe` hay `codex.exe`).
- **Quy tắc Kiểm tra Cây Tiến trình**:
  - Khi báo cáo PID cho người dùng và theo dõi nhịp tim qua Watchdog, bắt buộc phải truy vết xuống con cháu thực tế trong process tree (dùng `Get-CimInstance Win32_Process -Filter "Name = 'agy.exe'"` hoặc `tasklist | grep agy`).
  - Báo cáo rõ ràng phân cấp: Subshell Wrapper PID (ví dụ `bash.exe` PID 11500) vs. Worker Engine PID (ví dụ `agy.exe` PID 22144, 215MB RAM). Tuyệt đối không gắn nhãn sai một tiến trình `bash.exe` thành `agy.exe`.

### Tuyệt đối Không Spam Echo Placeholder & Đảm Bảo Tiến Độ Hành Động Thực Chất
- Khi người dùng yêu cầu kích hoạt Reviewer hoặc kiểm tra tiến trình: **thực thi ngay hành động thực tế** (soạn prompt file, chạy script nền, kiểm tra PID qua psutil/tasklist).
- **Nghiêm cấm hành vi gửi các lệnh vô nghĩa** hoặc lặp lại các lệnh terminal rỗng từ Orchestrator. Mỗi tool call phải tạo ra tiến bộ thực chất và trả kết quả chính xác (PID cụ thể của `codex.exe`, `agy.exe`, `python.exe`).

### Báo cáo Trực tiếp trên Telegram & Đa Nền tảng
- Khi chuyển đổi giao diện sang Telegram hoặc chat channel di động:
  - Báo cáo phải định dạng Markdown chuẩn, rõ ràng, gãy gọn, ưu tiên dạng danh sách gạch đầu dòng (bullets) và labeled lines.
  - Bắt buộc cập nhật đầy đủ và minh bạch: Commit hiện tại, số lượng tests PASS/FAIL, các findings đã APPROVED và các findings đang xử lý, kèm PID thực tế của Builder, Reviewer và Supervisor.
  - Tuyệt đối không dùng bảng markdown (table) trên Telegram vì vỡ khung hiển thị; dùng bullet points thay thế.

## 4. Windows / AGY / CLI Runtime Operations

### Cấu hình AGY CLI kết nối Antigravity Pool (Antigravity-Manager)
Để `agy CLI` (từ bản 1.1.13+) định tuyến qua pool tài khoản của Antigravity Manager thay vì gọi trực tiếp Google OAuth:
1. **Thiết lập provider & model trong settings.json**:
   Tại `%USERPROFILE%\.gemini\antigravity-cli\settings.json`, cấu hình chuẩn xác:
   ```json
   {
     "model": "Gemini 3.8 Flash (High)",
     "modelProvider": "gemini"
   }
   ```
   - **Xác thực file thực tế**: Kiểm tra chắc chắn file tồn tại và chứa key `"modelProvider": "gemini"`. Tránh suy diễn hoặc nhầm lẫn giữa biến môi trường session tạm thời với file config trên đĩa.
   - Giữ nguyên các trường hiện có như `trustedWorkspaces`, merge thêm key `modelProvider` và `model`.
2. **Quy tắc tham số dòng lệnh `--model` & `--effort` của `agy CLI`**:
   - `agy` phân biệt rõ giữa model trần và biến thể thinking: khi chỉ định model flash qua cờ dòng lệnh, nếu dùng tên base `--model gemini-3.8-flash` (hoặc `gemini-3.7-flash`), **bắt buộc phải kèm `--effort <low|medium|high>`**. Thiếu `--effort` sẽ khiến CLI thoát ngay với mã lỗi 1:
     `error: invalid model selection (--model "gemini-3.8-flash" --effort ""): --model gemini-3.8-flash requires --effort (available: low, medium, high)`
   - **Cú pháp gọi trực tiếp khuyên dùng**: Luôn dùng định dạng model gộp `--model gemini-3.8-flash-high` (hoặc `gemini-3.8-flash-low`, `gemini-3.1-pro-high`) để CLI tự suy luận effort tương ứng mà không cần thêm cờ phụ.
3. **Cơ chế Router và Upstream Quota của Antigravity Manager (Port 8045)**:
   - **Tại sao Gemini 3.1 Pro phản hồi cực nhanh**: Proxy có sẵn luật hardcode hệ thống: `gemini-3.1-pro -> gemini-3.1-pro-preview -> gemini-pro-agent`. Upstream Google Cloud Code luôn có quota cho biến thể này.
   - **Tại sao Gemini 3.8 Flash trần bị 429 / Loading vô hạn**: Upstream pool Cloud Code không nhận diện quota cho model trần `gemini-3.8-flash` (chỉ có quota cho `gemini-3.8-flash-high` / `-low`). Nếu request gửi tên trần, proxy thử toàn bộ accounts rồi trả về JSON lỗi 429 (`All accounts exhausted`), khiến stream socket của AGY CLI bị kẹt trong trạng thái chờ chunk dữ liệu đầu tiên.
   - **Khắc phục trên Proxy**: Cấu hình trong Antigravity Manager (Custom Mappings / Model Router) ánh xạ `gemini-3.8-flash` ➔ `gemini-3.8-flash-high` để tự động chuyển tiếp request đúng quota upstream.
4. **Biến môi trường vĩnh viễn (User Environment Variables)**:
   - `GOOGLE_GEMINI_BASE_URL` và `GEMINI_BASE_URL`: trỏ về endpoint native Gemini của proxy pool, ví dụ `http://127.0.0.1:8045` (chú ý: **không** thêm `/v1` hay `/v1beta` vì CLI tự append `/v1beta/models/...`). Khi subshell non-interactive khởi chạy AGY, **bắt buộc export cả `GOOGLE_GEMINI_BASE_URL` và `GEMINI_BASE_URL`** cùng lúc với `GEMINI_API_KEY`. Nếu thiếu base URL, AGY sẽ kết nối thẳng lên `generativelanguage.googleapis.com` và bị từ chối với lỗi 400 `API key not valid` do key của pool proxy không khớp với Google Cloud trực tiếp.
   - `GEMINI_API_KEY`: API key cấu hình trên proxy pool (ví dụ `sk-...`).
   - Lệnh thiết lập qua PowerShell:
     ```powershell
     [System.Environment]::SetEnvironmentVariable('GEMINI_API_KEY', '<api-key>', 'User')
     [System.Environment]::SetEnvironmentVariable('GOOGLE_GEMINI_BASE_URL', 'http://127.0.0.1:8045', 'User')
     [System.Environment]::SetEnvironmentVariable('GEMINI_BASE_URL', 'http://127.0.0.1:8045', 'User')
     ```
5. **Kiểm tra liveness & Chẩn đoán 429/Cooldown**:
   - Chạy `agy --model gemini-3.8-flash-high -p "ping"` để xác nhận proxy đã nhận request và routing hoạt động.
   - Khi AGY gọi model gặp tình trạng treo lâu hoặc retry liên tục: chạy kèm `--log-file "$HOME/agy-debug.log"` để kiểm tra log chi tiết. Nếu log xuất hiện `All accounts exhausted. Last error: HTTP 429: Resource has been exhausted`, proxy đang nhận diện tất cả tài khoản trong pool hết quota cho model đó; giữ nguyên cấu hình và đợi reset quota hoặc bổ sung account vào pool.



### Loại trừ thư mục build cache của Cargo (`target/`)
- Khi biên dịch Rust (`cargo check`, `cargo test`), hệ thống tự động sinh các file cache như `CACHEDIR.TAG`, `.fingerprint`, `.rmeta` trong thư mục `target/`.
- Hàm `_changed_files` trong factory engine không được liệt kê các file bị git ignore (`--ignored`) vào danh sách file bị sửa đổi, tránh kích hoạt lỗi `scope violation`.

### Tách biệt tiến trình nền & cơ chế Lock file trên Windows
- Trên Windows NT, tiến trình con giữ file descriptor có thể gây lỗi `Device or resource busy` khi đọc `run.lock` hoặc gây xung đột nếu gọi nhiều lệnh `resume` đồng thời.
- Phải đảm bảo tiến trình trước đó đã thoát hoàn toàn trước khi gọi lượt `resume` mới.

### Tích hợp Native Rust Toolchain & Multi-crate Workspace
- Kiểm tra `cargo check --manifest-path crates/<crate>/Cargo.toml` thay vì chỉ kiểm tra ở root workspace khi làm việc trên submodule.
- Luôn kiểm tra MSVC environment variables và đường dẫn Cargo trong `USERPROFILE/.cargo/bin` khi khởi chạy builder ngầm.

### Xử lý các task nghiên cứu / baseline không sinh code diff
- Các task nghiên cứu (như kiểm tra hợp đồng `BASELINE`) không thay đổi file trong worktree và kết thúc với `NO_PATCH`.
- Engine phải ghi nhận hoàn thành hợp lệ đối với task nghiên cứu baseline thay vì đếm thành lỗi navigation hay vi phạm attempt.

### Tăng Builder Timeout cho các module hệ thống lớn
- Mặc định builder timeout là 900s. Với các tác vụ phức tạp (như cài đặt subsystem COM / UI Automation), cần cấu hình `builder_timeout` lên 3,600s để tránh ngắt giữa chừng vì timeout in ấn.

### Tránh Lỗi Thoát Ký Tự Đường Dẫn Trên Windows (`SyntaxError: unicodeescape`)
- Trong các script Python điều phối (như launcher `run_*.py`), các đường dẫn Windows tuyệt đối như `C:\Users\HH18\project` nếu viết chuỗi thường hoặc chuỗi thô `r"<workspace>"` có thể kích hoạt lỗi cú pháp:
  `SyntaxError: (unicode error) 'unicodeescape' codec can't decode bytes in position ...: truncated \UXXXXXXXX escape` do ký tự `\U` bị hiểu là điểm mã Unicode 8 chữ số, hoặc `\a` trong `\agent` bị hiểu là mã chuông ASCII.
- **Quy tắc bắt buộc**: Luôn chuẩn hóa toàn bộ đường dẫn thành dấu gạch xuôi (`C:/Users/HH18/project`) hoặc escape tường minh dấu gạch chéo ngược (`C:\\Users\\HH18\\agent-desktop-win`).

### Sử Dụng Tool `write_file` Thay Vì Terminal Echo Heredoc Cho Script Phức Tạp
- Khi tạo các script launcher Python hoặc runner shell cho AGY/Codex: **tuyệt đối không dùng heredoc qua lệnh `terminal` hay chuỗi inline `python -c "..."` dài** vì subshell MSYS/Bash rất dễ làm méo mó ký tự ngoặc kép, dấu gạch chéo, hoặc bị parser shell cắt xén gây lỗi `[Error: No command provided]`.
- **Luôn sử dụng trực tiếp tool `write_file`** để ghi script sạch ra đĩa (`C:/Users/HH18/AppData/Local/Temp/...`), sau đó mới gọi qua terminal `python <script_path>`.


### Bắt buộc Khai báo Non-Empty `command` Parameter trong Terminal Schema & Tool Calling
- **Hiện tượng `echo "[OK: Action logged - Action logged]"` trong terminal AGY / Agent Desktop**:
  - **Bản chất kỹ thuật**: Không phải do model cố ý gõ dummy command hay lỗi subshell, mà xuất phát từ cơ chế an toàn (safe fallback injection) của Antigravity Tools proxy (`antigravity_tools_lib::proxy::mappers::openai::response`). Khi model upstream (đặc biệt là Gemini 3.8 qua pool) phát sinh tool call thực thi dòng lệnh (`terminal`, `bash`, `cmd`, `shell_command`) nhưng thiếu tham số `command` bắt buộc (hoặc chỉ gửi tham số mô tả như `description: "Action logged"`, hoặc gửi argument payload rỗng `{}`), proxy sẽ tự chèn `command: "echo \"[OK: Action logged - <description>]\""` vào arguments payload để tránh làm crash CLI downstream. CLI nhận payload này và thực thi chuỗi echo lặp lại vào terminal.
  - **Quy tắc Bắt buộc trên Schema & System Prompt**:
    1. **Schema Cứng (`TERMINAL_SCHEMA`)**: Khai báo tham số `command` là `type: string`, bổ sung `"minLength": 1`, kèm `"required": ["command"]`. Description phải chỉ định rõ `The non-empty shell command to execute. Must be a valid executable command string. Never empty or omitted, and never a description/log.`
    2. **System Instruction / Builder Slice Guidance**: Luôn tiêm chỉ thị tường minh cho model: *When invoking `terminal`, you MUST always supply the `command` argument with a non-empty executable shell command string (e.g. `{"command": "<bash command>"}`). NEVER leave arguments empty `{}` or omit `command`, and never pass descriptions or logs instead of executable commands.*
    3. **Fail-Closed Execution Guard**: Trong hàm xử lý tool (`_plan_execution` hoặc runner), từ chối ngay lập tức nếu `command` không phải string hoặc `not command.strip()`.
  - **Cách xử lý & khắc phục khi gặp trong vận hành**:
    1. Kiểm tra file log của proxy (`%USERPROFILE%/.antigravity_tools/logs/app.log`) tìm cảnh báo `Injected safe fallback 'command'` để xác định chính xác tool và description bị thiếu `command`.
    2. Nếu AGY CLI bị kẹt trong vòng lặp echo này: ngắt tiến trình AGY bị treo (`child.kill()`), kiểm tra lại prompt / task spec để nhấn mạnh quy tắc bắt buộc truyền `command` không rỗng trong tool call, hoặc re-dispatch với prompt cô đọng hơn.
    3. Tránh để task tiếp tục chạy mù khi thấy output xuất hiện liên tiếp chuỗi echo fallback này.

### Khởi chạy Builder AGY qua Dedicated Runner Script
- Khi chạy AGY Builder trong nền với prompt dài và cờ cấu hình (`--dangerously-skip-permissions`, `--print-timeout 3600s`), việc truyền chuỗi command trực tiếp qua shell dễ gặp lỗi thoát sớm (exit code 0 nhưng không chạy) do escape quote hoặc ngắt subshell.
- Luôn tạo một script runner độc lập (ví dụ `run_agy.sh` có `cd /c/Users/...` rõ ràng) rồi khởi chạy `bash /path/to/run_agy.sh > log 2>&1` ở chế độ background.
- Khi tạo file task prompt chứa shell substitution, cú pháp lệnh hoặc đoạn code, **luôn dùng `cat << 'EOF' > file` (quote EOF) hoặc script Python để ghi file**. Tránh dùng `echo "..."` hoặc bash unquoted heredoc `cat << EOF` vì bash sẽ thực thi command substitution (ví dụ `$(...)` hoặc `` `...` ``) ngay khi ghi file gây lỗi cú pháp hoặc mất nội dung prompt.

### Cảnh giác Lỗi Cấu hình AGY CLI: modelProvider & GEMINI_API_KEY Mismatch
- Khi AGY CLI chạy ở chế độ Google Cloud / Antigravity Provider mặc định, nếu trong `%USERPROFILE%\.gemini\antigravity-cli\settings.json` bị cấu hình `"modelProvider": "gemini"` nhưng biến `GEMINI_API_KEY` lại chứa token `sk-...` từ proxy pool cục bộ không tương thích, tiến trình `agy.exe` sẽ lập tức bị từ chối với lỗi `403 Forbidden: Invalid token` hoặc `token_rejected`.
- **Khắc phục Triệt để Triệu chứng Lỗi Thoát Ngay Lập Tức (Exit 403 / Exit 127)**:
  1. Khi AGY cần dùng session OAuth gốc: gỡ bỏ hoàn toàn dòng `"modelProvider": "gemini"` khỏi `%USERPROFILE%\.gemini\antigravity-cli\settings.json`, đồng thời xóa biến môi trường `GEMINI_API_KEY` trong runner script trước khi spawn child process.
  2. Khi dùng Antigravity Proxy Pool: bắt buộc xuất đồng bộ cả 3 biến môi trường cùng lúc: `GEMINI_API_KEY`, `GOOGLE_GEMINI_BASE_URL="http://127.0.0.1:8045"`, và `GEMINI_BASE_URL="http://127.0.0.1:8045"`; đồng thời bảo đảm `settings.json` có `"modelProvider": "gemini"`.
  3. Khi phát hiện AGY dừng đột ngột khi candidate chưa hoàn tất: kiểm tra ngay log khởi chạy (`agy_*.log`) để xác định mã lỗi 403, 400 hoặc crash môi trường thay vì suy đoán worker đang chạy.

### Xử lý Khoảng Trống Dòng & Ký Tự Điều Khiển Windows (`\r\n`) trong URL Proxy & Biến Môi Trường
- Khi đọc biến môi trường qua `powershell -Command "[System.Environment]::GetEnvironmentVariable(...)"` trên Windows, PowerShell mặc định trả về chuỗi có kèm ký tự ngắt dòng Windows (`\r\n`).
- **Nguy cơ Gây Lỗi Go net/http trong AGY CLI**:
  - Nếu gán biến `export GOOGLE_GEMINI_BASE_URL=$(powershell ...)` mà không loại bỏ triệt để ký tự `\r`, biến môi trường sẽ chứa `http://127.0.0.1:8045\r`.
  - Khi Go HTTP client trong `agy.exe` phân tích URL hoặc gán Header HTTP `X-Goog-Api-Key`, Go sẽ ném lỗi runtime ngay lập tức:
    `createAPIURL: error parsing base URL: parse "http://127.0.0.1:8045\r": net/url: invalid control character in URL`
    hoặc `net/http: invalid header field value for "X-Goog-Api-Key"`.
  - **Quy tắc Bắt buộc**: Luôn làm sạch triệt để bằng `tr -d '\r\n'` hoặc dùng `.replace('\r', '').replace('\n', '').strip()` trong Python script khi đọc biến môi trường gán cho subshell/runner của AGY.

### Quản Lý Dung Lượng Đĩa C: & Dọn Dẹp Cargo Build Cache Tự Động Trước Vòng Lặp
- Khi chạy build và test Rust lặp đi lặp lại nhiều vòng (`cargo test`), thư mục `target/` có thể phình to nhanh chóng (thường từ 7GB đến 20GB+), khiến ổ `C:` bị cạn kiệt (0 GB free).
- Khi dung lượng ổ đĩa chạm ngưỡng 0 GB, các tiến trình `codex.exe`, `agy.exe` hoặc các lệnh ghi file JSON sẽ bị crash hoặc timeout do không thể cấp phát bộ nhớ đệm hay ghi file tạm.
- **Quy tắc Vận Hành**:
  - Kiểm tra dung lượng trống của ổ `C:` trước khi khởi chạy các vòng review lớn. Nếu dung lượng dưới 5 GB, chủ động thực thi `cargo clean` tại repository làm việc (`cargo clean` giải phóng tức thì 7-10 GB dung lượng build cache) hoặc dọn dẹp các binary tạm trong `%LOCALAPPDATA%\Temp`.

### Quota Cooldown & Anti-Ghost-Coding Protocol
- Khi Builder (`agy.exe` sử dụng `gemini-3.8-flash-high`) gặp lỗi giới hạn quota tạm thời (`error: Individual quota reached. Resets in ...`):
  - **Giữ nguyên ranh giới Orchestrator**: Tuyệt đối không tự ý sửa file, commit thay, hoặc đổi sang model khác khi chưa có chỉ thị.
  - **Duy trì Watchdog & Thăm dò Tự động (Minimal Probe)**: Watchdog chỉ theo dõi liveness/heartbeat/process identity; **Hermes Orchestrator** mới là bên thực hiện probe provider nhẹ như `agy --model gemini-3.8-flash-high -p "ping"` hoặc script kiểm tra không sinh side-effect theo cadence hợp lý.
  - **Tự động Khôi phục & Tiếp nối**: Ngay khi probe phản hồi thành công (hết cooldown), Hermes reconcile process tree + task lease, xác nhận không có writer cũ còn sống rồi mới dispatch continuation cho Builder. Builder hoàn thiện thay đổi và test **không commit**; Runner verify/stage candidate, Sol review, và chỉ Hermes mới commit sau approval.

### Phòng chống Vòng lặp Lệnh Terminal Rỗng & Tool Loop Prevention
- Khi điều phối các tiến trình nền (background processes) hoặc ghi file tạm phức tạp qua terminal, tuyệt đối không gửi các lệnh terminal rỗng, lặp lại cùng một lệnh không đổi (như `echo "[OK: ...]"`), hoặc các lệnh kiểm tra thăm dò vô ích liên tiếp dẫn đến `identical_call_streak_halt`.
- Mọi thao tác ghi file tạm hoặc chuẩn bị runner script phải được thực thi trực tiếp qua các công cụ file hệ thống (`write_file`) hoặc một script Python ghi file độc lập (`with open(...) as f: f.write(...)`). Tránh lỗi bỏ sót argument `content` trong `write_file` dưới áp lực ngữ cảnh.
- Khi nhận tín hiệu "Stop" hoặc người dùng yêu cầu tạm dừng: ngay lập tức dừng toàn bộ các vòng lặp polling, đóng băng các tiến trình nền, lập báo cáo tóm tắt hiện trạng kỹ thuật rõ ràng (các commit đã xong, kết quả test suite, các gap còn lại) và chờ lệnh mới, không tự ý spawn thêm tiến trình hay lặp lại lệnh.
- Nếu một lệnh terminal thất bại hoặc gặp cảnh báo lặp lại (tool loop warning / identical call streak), phải lập tức chẩn đoán nguyên nhân cốt lõi và đổi phương án (ví dụ chuyển sang Python script hoặc kiểm tra đường dẫn tuyệt đối), không bao giờ cố gắng gọi lại lệnh giống hệt.

### Bounded Child Process Reaping & RAII Guard trong Thu hồi Tài nguyên Hệ thống
- Khi một tác vụ hệ thống (như Win32 GDI capture, I/O, IPC) có nguy cơ bị treo vô hạn:
  - Bắt buộc cô lập trong tiến trình con riêng biệt (`std::process::Child`) thay vì chạy trực tiếp trên calling/worker thread.
  - Khi timeout xảy ra, gọi `child.kill()` (`TerminateProcess`) để kernel hệ điều hành dọn dẹp sạch toàn bộ tài nguyên (HDC, HBITMAP, memory, threads).
  - **Bounded Reaping Contract**: Không bao giờ gọi `child.wait()` blocking không giới hạn sau khi kill, vì nếu tiến trình bị kẹt trong kernel driver I/O, thread cha sẽ bị treo vĩnh viễn. Bắt buộc dùng vòng lặp polling `child.try_wait()` kết hợp `sleep(10-50ms)` và deadline cứng (grace period 1-3s).
  - **Child Cleanup Guard trong Drop**: Mọi RAII guard bọc child process phải áp dụng bounded reaping polling khi Drop, tuyệt đối không được gọi `wait()` blocking vô hạn trong hàm `drop`.
  - **Strict Authorization**: Khi spawn worker executable, chỉ chấp nhận binary chính xác (`agent-desktop-capture-worker.exe`) hoặc canonical test executable (`current_exe()`). Cấm ủy quyền dựa trên so khớp chuỗi tên lỏng lẻo (`contains("test")`) hoặc fallback tùy tiện qua PATH.

## 5. Project-Specific Appendix — `agent-desktop-win`

**Scope guard:** Toàn bộ mục 5 là knowledge/runbook riêng của project Windows Native Runtime `agent-desktop-win` (T4–T10, Gates A–N, UIA/MSAA/CDP/Visual, packaging/evidence ledger, v.v.). **Không coi các rule này là invariant chung của SoftFac** và không áp dụng cho repository khác nếu user không yêu cầu.

### Unified RefMap, Multi-Provider Stale Detection & Action Verification (Master M6 / Task T8)
- **Unified RefMap Allocation & Address Space (T8 / Gate G)**:
  - Tất cả các provider (`UIA`, `Visual`, `MSAA`, `CDP`) phải được cấp phát và giải quyết trong một không gian địa chỉ ref thống nhất duy nhất của `crates/core` (`RefMap`).
  - Cấm phân bổ ref trùng lặp hoặc gán ref không chứa định danh nguồn gốc rõ ràng. Mỗi ref entry bắt buộc mang `ProviderSource` tương ứng.
- **Phát hiện Stale Ref & Từ chối Ambiguity Đa Provider (T8 / Gate H-I)**:
  - **Process/Window Stale**: Bắt buộc kiểm tra process generation timestamp khi phân giải HWND/UIA/MSAA. Nếu process ID bị tái sử dụng hoặc window bị đóng, lập tức từ chối với `ErrorCode::StaleRef`.
  - **Visual Pixel Hash Invalidation**: Bắt buộc tính toán và kiểm tra độ ổn định của `VisualHash` qua ảnh chụp fresh recapture trước khi thực hiện hành động. Nếu layout/vùng pixel thay đổi, trả về `StaleRef` hoặc `GeometryMismatch`.
  - **CDP Document Churn Invalidation**: Khi tab Chromium/Electron điều hướng hoặc tải lại (`DOM.documentUpdated`), thế hệ tài liệu `doc_gen` thay đổi, phải lập tức đánh dấu stale toàn bộ ref con của document cũ.
- **Tiêu chuẩn Tiền điều kiện Hành động Thống nhất (T8 Actionability Preflight / Gate J)**:
  - Mọi thao tác hành động xuyên suốt các provider (semantic hoặc physical) phải chạy qua bộ lọc preflight thống nhất: kiểm tra visible, enabled, hit-testable, và bounding box không âm trong desktop coordinates.
- **Xác minh Hậu điều kiện Tươi mới Sau Mutation (T8 Postcondition Verification / Gate K)**:
  - Mọi mutation (Invoke, SetValue, Toggle, Click, TypeText) không bao giờ được đánh dấu `DeliveredVerified` nếu chưa quan sát được trạng thái mới (re-read UIA/MSAA property, DOM attribute/value mới, hoặc pixel diff sau thao tác). Nếu không thể quan sát kiểm chứng, bắt buộc báo cáo trung thực là `DeliveredUnverified` (`PartialDelivery`).

### Session Lifecycle, Action Trace & Compatibility Matrix (Master M7 / Task T9)
- **Session Lifecycle & Cross-Session Ref Rejection (T9_SESSION)**:
  - Mỗi session tương tác client phải được gán một session token / correlation ID duy nhất.
  - Bộ nhớ đệm ref (`RefMap`) phải gắn chặt với vòng đời session. Mọi nỗ lực sử dụng ref được tạo ra từ một session đã đóng hoặc session khác bắt buộc phải bị từ chối fail-closed với `ErrorCode::StaleRef` hoặc `InvalidSession`.
- **Ghi File Action Trace JSONL Thread-Safe (T9_TRACE)**:
  - Việc ghi log trace các thao tác hành động (`ActionTraceWriter`) phải được bảo vệ bằng file lock hoặc cấu trúc thread-safe (`Mutex<File>`) để tránh hỏng định dạng khi nhiều thread ghi đồng thời.
  - Trường `delivery` trong trace event JSON bắt buộc phải serialize chuẩn xác theo enum `ActionDeliveryStatus` (`"DeliveredVerified"`, `"DeliveredUnverified"`, `"NotDelivered"`), không được xuất chuỗi tự do.
  - Các thao tác bị chặn từ bước preflight (như target không khả dụng, stale ref) phải được ghi log với `delivery: "NotDelivered"`.
- **Ma trận Tương thích Gate N (T9_MATRIX & T9_CLI)**:
  - Xuất kết quả tương thích của hệ thống dưới định dạng JSON có cấu trúc rõ ràng (`Structured Compatibility Matrix`), đối chiếu chi tiết khả năng hỗ trợ của từng provider (UIA, MSAA, CDP, Visual) trên từng loại control Win32 tiêu chuẩn và ứng dụng thực tế.

### Kỹ thuật MSAA IAccessible & Chromium CDP Fallback (Master M5 / T6, T7)
- **MSAA / IAccessible Hierarchical Child Routes (T6)**:
  - Các phần tử con `VT_DISPATCH` lồng nhau nếu chỉ gán chỉ số cục bộ sẽ gây trùng lặp định danh `msaa:<hwnd>:<index>:<role>`. Bắt buộc lưu trữ đường dẫn phân cấp (hierarchical child route vector, ví dụ `[child_id, sub_child_id, ...]`).
  - **Hỗ trợ Leaf Child ID (`VT_I4` / `CHILDID_SELF`) trong Route Resolution**: Phân giải route MSAA không được giả định mọi component đều là `VT_DISPATCH`. Với các standard control đơn giản (như item trong ListBox, phần tử con trong ComboBox/ToolBar), leaf node được biểu diễn bằng `VT_I4` child index. Route kết thúc bằng số nguyên `child_id` phải phân giải thành pair `(parent_accessible, VARIANT::from(child_id))` để hỗ trợ round-trip chính xác thay vì thất bại do ép kiểu `IDispatch`.
  - **Ghi nhận Traversal Truncation Rõ ràng**: Khi duyệt cây MSAA gặp giới hạn chiều sâu (`max_depth`) hoặc giới hạn số lượng phần tử (`max_count`), trạng thái snapshot phải ghi nhận cờ truncated/incomplete rõ ràng, không được âm thầm đánh dấu là `complete: true`.
  - **Giới hạn Fallback Vật lý khi Thất bại Default Action**: Tuyệt đối không fallback SendInput click mù quáng cho mọi mã lỗi OLE/COM. Chỉ kích hoạt SendInput fallback khi mã lỗi HRESULT phản ánh rõ ràng control không hỗ trợ semantic action (như `DISP_E_MEMBERNOTFOUND`, `E_NOTIMPL`). Các lỗi ngắt kết nối, timeout hoặc invalid argument phải trả về lỗi phân loại, không kích hoạt đột biến vật lý ngoài ý muốn.
  - **Kiểm chứng Tính Toàn vẹn Danh tính (Identity Integrity Revalidation)**: Khi revalidate element ref MSAA, phải so khớp stability hash và kích thước/role ban đầu với live control. Cấm ghi đè mù quáng observed name bằng live name mà không kiểm tra tính tương thích.
  - Tọa độ `accLocation` trả về là physical desktop pixels; bắt buộc phải chuyển đổi sang logical coordinates tương thích với model snapshot của core adapter.
  - Fallback từ UIA sang MSAA không được giới hạn cục bộ khi `node_count <= 1`; phải kích hoạt cho các cửa sổ có các standard controls (Button, Edit, ComboBox) mà UIA không bao quát đầy đủ.
- **Chromium / Electron CDP Discovery, Routing & Churn Invalidation (T7)**:
  - Khi bóc tách tham số dòng lệnh Chromium (`--remote-debugging-port`), bắt buộc dùng Win32 `CommandLineToArgvW` để xử lý chuẩn xác các đường dẫn có khoảng trắng nằm trong dấu ngoặc kép.
  - Trước khi kết nối WebSocket, bắt buộc probe endpoint HTTP `http://127.0.0.1:<port>/json/version` để xác thực `webSocketDebuggerUrl` và browser identity.
  - **Lưu trữ và Định tuyến Đúng `backendDOMNodeId`**: Accessibility tree của CDP trả về `nodeId` thuộc AXNode, nhưng các lệnh thao tác DOM (như `DOM.focus`, `DOM.getBoxModel`, `DOM.resolveNode`) yêu cầu `backendNodeId` / `backendDOMNodeId`. Bắt buộc phải trích xuất và lưu trữ `backendDOMNodeId` trong action route; tuyệt đối không truyền nhầm AX nodeId hoặc gán mặc định `nodeId = 1` khi phân giải.
  - **Đồng bộ Thế hệ Tài liệu/Điều hướng Chống Churn (Document Generation Tracking)**: Chromium target ID thường tồn tại xuyên suốt các lần chuyển hướng trang (page navigation). Do đó, AX nodeId có thể bị tái sử dụng ở tài liệu mới. Để chống stale ref, CDP ref bắt buộc phải nhúng thêm mã thế hệ tài liệu/frame (document generation counter hoặc loader ID). Khi thực thi action trên `CdpHandle`, bắt buộc kiểm tra thế hệ tài liệu hiện tại; nếu trang đã chuyển hướng hoặc DOM đã churn (`DOM.documentUpdated`), phải lập tức từ chối với lỗi `StaleRef`.
  - **Khớp Correlation ID trên CDP WebSocket**: Khi gửi command qua WebSocket JSON-RPC, `CdpWsClient` phải dùng vòng lặp chờ đúng message ID tương ứng với request; không được lấy ngay message đầu tiên nhận được từ WebSocket vì đó có thể là asynchronous event (như `Page.frameNavigated` hay `DOM.documentUpdated`), dẫn tới nhầm lẫn event thành kết quả lệnh mutation.

### Tài liệu Platform Skills, README & Integration Docs: Grounded Claims Tuyệt Đối (Milestone 6 / Docs Gate)
- **Cấm Quảng bá Tính năng Chưa Triển khai (Anti-Hallucinated Features)**:
  - Khi viết tài liệu kỹ năng (`skills/agent-desktop-<platform>/SKILL.md`) hoặc `README.md`: Tuyệt đối không liệt kê các công nghệ, API hoặc cờ dòng lệnh chưa được cài đặt trong mã nguồn thực tế.
  - Ví dụ trên Windows: Không tự ý khẳng định hỗ trợ *Windows Graphics Capture (WGC)* hay *Desktop Duplication API* khi mã nguồn chỉ mới dùng GDI `BitBlt` / `PrintWindow`. Không khẳng định hỗ trợ *Windows Notification Center Management* qua WinRT khi chưa có subsystem đó. Không tự bịa cú pháp cờ CLI (như `--args`) nếu bộ phân giải tham số (clap parser) chưa khai báo.
  - Không hướng dẫn các workflow không có cơ sở như khởi chạy ứng dụng bằng URI schemes (`start https://...`) nếu adapter chỉ hỗ trợ thực thi binary path qua `CreateProcessW`.
- **Đồng bộ 1:1 Bảng Mã Lỗi HRESULT & Kiểu Dữ Liệu**:
  - Bảng tra cứu mã lỗi HRESULT trong tài liệu phải phản ánh chính xác các hằng số hex và enum mapping trong code Rust (ví dụ `UIA_E_ELEMENTNOTAVAILABLE` = `0x80040201`, `RPC_S_SERVER_UNAVAILABLE` = `0x800706BA`, `RPC_E_DISCONNECTED` = `0x80010108`, `UIA_E_TIMEOUT` = `0x80040205`).
  - Hình dạng dữ liệu JSON của `platform_detail` phải khớp với cấu trúc Rust serializable thực tế (`HresultErrorDetail`), không tự bịa các trường dữ liệu tùy hứng.
- **Tính Di Động của Đường Dẫn Liên Kết (Portable Links)**:
  - Mọi liên kết tham chiếu tài liệu bên trong repository phải sử dụng đường dẫn tương đối (relative paths) từ thư mục tài liệu đó, tuyệt đối không dùng đường dẫn tuyệt đối gắn cứng theo ổ đĩa máy tính local (ví dụ `C:/Users/...`).

### Tối ưu Hóa Action::Select Trên Combobox Dưới Tải Song Song (Master M8 / T10_HANDOFF)
- Khi chạy toàn bộ test suite lớn song song dưới Cargo mặc định (`cargo test -p agent-desktop-windows`), các bài test native UI (như `native_gate_a_hardened`) thường xuyên thất bại tại thao tác `Action::Select` trên Win32 Combobox do timeout (`Select timeout`).
- **Nguyên nhân Kỹ thuật**:
  - `Action::Select` trên Combobox nếu chỉ chờ UIA `ISelectionItemPattern` trên container cha hoặc tìm kiếm item khi popup list chưa mở sẽ bị kẹt hoặc trả về rỗng.
  - Các pop-up dropdown list của Win32 `ComboBox` được tạo trên một HWND con hoặc cửa sổ popup riêng biệt (`ComboLBox`) có runtime depth khác với element chính.
- **Giải pháp Bắt buộc**:
  1. Khi thực thi `Action::Select` trên phần tử có control type `ComboBox`: kiểm tra và gọi `IExpandCollapsePattern::Expand` trước để buộc mở dropdown list.
  2. Bổ sung helper tìm kiếm item con duyệt cả children trực tiếp và popup list items với bounded retry loop (50-100ms interval, deadline 2-3s).
  3. Với mỗi item ứng viên tìm thấy, ưu tiên gọi `ISelectionItemPattern::Select`; nếu pattern không khả dụng, fallback sang `IInvokePattern::Invoke` hoặc click vật lý có tọa độ đã scale theo DPI trước khi đóng lại dropdown bằng `Collapse`.

### Thuật toán Trích xuất Visual Candidate: Histogram Background Estimation & 2D Span-Connected Components
- **Lấy mẫu Độ sáng Nền Đa điểm (Histogram Mode Estimation)**:
  - Lấy mẫu nền chỉ từ 4 góc ảnh (`inset corners`) sẽ bị sai lệch nghiêm trọng khi cửa sổ ứng dụng có thanh tiêu đề/banner sẫm màu ở phía trên và nền nội dung sáng ở phía dưới (hoặc ngược lại trong dark mode). Giá trị trung bình của hai cụm màu bị kéo lệch, dẫn đến việc phân loại nhầm toàn bộ nền nội dung thành foreground.
  - Phải sử dụng lưới điểm mẫu phân bổ đều toàn ảnh kết hợp histogram độ sáng 32-bin để tìm bin chiếm ưu thế (dominant mode, ví dụ $\ge 15\%$ tổng số mẫu).
- **Tránh Bẫy Gộp Bounding Box Toàn Cục (Span-Connected Components Trap)**:
  - Khi nhóm các đoạn pixel tiền cảnh (`spans`) qua từng dòng quét $y$ thành các vùng đối tượng (`regions`), tuyệt đối không được gộp span mới chỉ dựa vào việc nó nằm trong khoảng bounding box tổng quát (`reg.min_x - 4 .. reg.max_x + 4`) của Region.
  - Nếu cửa sổ có viền trái/phải hoặc banner phía trên, bounding box của viền cửa sổ sẽ bao trùm từ `x = 0` đến `x = width - 1`. Mọi nút bấm hoặc phần tử con bên trong cửa sổ sẽ bị nuốt chửng vào bounding box viền cửa sổ, tạo thành một component khổng lồ và bị bộ lọc loại bỏ do vượt quá kích thước tối đa.
  - Bắt buộc theo dõi `last_spans` (danh sách đoạn span ở dòng $y-1$ liền kề) và chỉ gộp span trên dòng $y$ khi có giao thoa vật lý 2D trực tiếp với ít nhất một span trong `last_spans` của Region đó.

### Quy tắc Cấp quyền Thực thi Worker & Thu hồi Tiến trình Nghiêm ngặt (Strict Worker Authorization & Bounded Reaping)
- **Cấm ủy quyền lỏng lẻo qua chuỗi tên hay biến môi trường**:
  - Không được dùng `name.contains("test")` hay `has_test_worker_capability` chạy thử binary rồi tin cậy stdout tự báo cáo để ủy quyền worker.
  - Trong production (`#[cfg(not(test))]`): **CHỈ DUY NHẤT** binary worker chuyên dụng có tên chính xác (`agent-desktop-capture-worker.exe`) nằm cạnh executable chính (`current_exe().parent().join(...)`) mới được cấp quyền. Không fallback ngầm qua PATH hay biến môi trường `CARGO_BIN_EXE_*`.
  - Trong test mode (`#[cfg(test)]`): **CHỈ DUY NHẤT** canonical binary hiện tại (`current_exe()`) mới được cấp quyền chạy worker entrypoint.
- **Thu hồi Tiến trình Con Bắt buộc có Bounded Reaping Polling**:
  - Khi ngắt tiến trình con bị treo/timeout (`child.kill()`), **cấm gọi `child.wait()` blocking không giới hạn**. Bắt buộc dùng vòng lặp polling `child.try_wait()` có hard deadline (grace period 1-3s).
  - Mọi `Drop` handler của RAII guard (như `ChildCleanupGuard`) bọc tiến trình con bắt buộc dùng bounded `try_wait` polling, không bao giờ để thread bị kẹt vĩnh viễn trong hàm `drop`.
  - Nếu kill hoặc reap thất bại trong grace period, phải báo cáo lỗi phân loại rõ ràng (`UncertainDelivery` / `PlatformError`) để caller biết việc thu hồi tài nguyên chưa được bảo đảm, không được báo cáo `Timeout` thành công giả tạo.

### Đối chiếu Hợp đồng Astra Master Plan Sau Khi Hoàn Thành Milestones Phụ (Post-M6 Reconciliation)
- Trong quá trình phát triển dài hạn, các milestone thực thi (như M4, M5, M6 hiện tại) thường bao hàm thêm nhiều hạng mục phát sinh có giá trị (shell surfaces, private state hardening, npm packaging, C ABI, skills/docs).
- **Quy tắc Bất biến về Hoàn thành**:
  - Không được suy diễn việc hoàn thành milestone đặt tên theo phase hiện tại (M1-M6) đồng nghĩa với việc hoàn thành toàn bộ hợp đồng Astra Master Plan ban đầu (`plans/*.json`).
  - Sau khi hoàn thành các milestone của phase đang chạy, **BẮT BUỘC thực hiện đối chiếu ma trận (Gap Reconciliation Matrix)** giữa repository HEAD thực tế với toàn bộ Tasks T1–T10 và Milestones M1–M8 của Astra Master Plan gốc.
  - Phân loại chính xác từng tiêu chí thành `PROVEN_COMPLETE`, `IMPLEMENTED_BUT_INSUFFICIENT_EVIDENCE`, `PARTIALLY_IMPLEMENTED`, hoặc `NOT_IMPLEMENTED`.
  - Chỉ tuyên bố hoàn thành toàn bộ dự án Windows Native Runtime khi:
    1. Toàn bộ các tasks T1–T10 đã được triển khai và có bằng chứng thực tế.
    2. Master M8 / T10 native acceptance chạy thành công (toàn bộ Gates A–N và mixed-DPI pass hoặc unverified có giải trình).
    3. Sol Reviewer hoàn tất holistic review toàn diện và trả về `APPROVED`.

### Master Milestone 8 / Task T10 & Final Holistic Review Pitfalls
- **Xử lý Tỉ lệ Co giãn Màn hình Thực tế (125% DPI Scale vs Physical Resolution)**:
  - Trên các hệ thống Windows chạy màn hình có tỉ lệ co giãn DPI không phải 100% (ví dụ 125% DPI, 120 DPI, scale factor 1.25):
  - Kích thước logic của màn hình (logical bounds) trả về qua Win32 APIs thường là `1536 x 864`, trong khi kích thước pixel vật lý thực tế của màn hình ảo (virtual screen) là `1920 x 1080`.
  - Mọi hàm chụp màn hình (`capture_display`, `capture_screen`, `capture_fullscreen`) và bài test xác thực (`native_gate_dpi`) bắt buộc phải scale kích thước logic theo DPI factor (`phys_width = ((bounds.width * scale).round() as i32).max(1)`). Tuyệt đối không truyền rectangle logic chưa scale vào `BitBlt` hoặc bộ đệm capture pixel thô.
  - Bắt buộc kiểm tra kích thước bộ đệm pixel thực tế thu được phải khớp chính xác độ phân giải vật lý (`1920 x 1080`), tránh bị Sol Reviewer từ chối vì lỗi lệch đơn vị DPI.
- **Ràng buộc Thuộc tính Bài test Native (`#[ignore]` Attribute)**:
  - Mọi bài kiểm thử native gate phụ thuộc vào phần cứng/môi trường hiển thị trực tiếp (`native_gate_dpi`, `native_gate_b`, `native_gate_d`, `native_gate_e`, `native_gate_f`) bắt buộc phải có thuộc tính `#[ignore]`.
  - Thiếu `#[ignore]` sẽ khiến bài test chạy lẫn vào các test unit thông thường, gây flakiness trong CI headless và khiến cờ `-- --ignored` của Cargo không thể chọn lọc thực thi đúng bài test.
- **Tránh Xung đột Timeout của Combobox Item Selection (`Action::Select`) Dưới Môi trường Chạy Song song**:
  - Khi chạy toàn bộ test suite lớn (145+ tests) song song dưới Cargo mặc định, các bài test tạo cửa sổ GUI Win32 thật (như `native_gate_a` / `native_gate_a_hardened`) rất dễ bị timeout khi thực thi `Action::Select("Option Beta")` trên Combobox nếu danh sách drop-down chưa kịp bung hoặc focus bị tranh chấp.
  - Cần củng cố helper `find_selectable_item` và cơ chế expand/collapse của combobox với vòng lặp chờ trạng thái có bounded polling hoặc `TEST_SERIALIZATION_LOCK`, đảm bảo toàn bộ suite chạy pass đồng bộ 100% mà không bị hụt ngưỡng số lượng test quy định.
- **Bắt buộc Hoàn thiện Bảng Sổ cái Handoff & Evidence Ledger**:
  - Bảng Evidence Ledger (`docs/evidence-ledger-gates-a-n.md` và `tasks/todo.md`) phải công khai minh bạch:
    1. Tên hàm kiểm thử cụ thể (exact test identifier) cho từng Gate từ Gate A đến Gate N và Gate DPI.
    2. Thông số môi trường Windows thực tế (Hệ điều hành, Build version, DPI scale factor, kích thước pixel vật lý).
    3. Phiên bản cụ thể của các ứng dụng thật và thư viện native (ví dụ Notepad, Calculator, USER32.DLL, COMCTL32.DLL).
- **Quy trình Final Holistic Review & Remediation Directive (Chỉ thị Thẩm định Toàn diện Cuối cùng)**:
  - **Không coi báo cáo 42/42 Acceptance Criteria là mặc nhiên hoàn tất**: Trước khi tuyên bố dự án kết thúc, bắt buộc kích hoạt một lượt **Full Project Holistic Review** độc lập, mang tính đối nghịch (adversarial) do Sol Reviewer (`gpt-6-sol`, reasoning: `high`) chủ trì trên toàn bộ repository.
  - **Mục tiêu của Holistic Review**: Quét toàn diện 18 lĩnh vực cốt lõi (Core contracts, UIA COM lifetime/MTA, Visual pixel candidates không phụ thuộc metadata, GDI/WGC capture isolation, MSAA fallback, CDP Web/Electron routing & churn, Unified RefMap, Actionability preflight, SendInput surrogate/Vietnamese NFC/NFD, Window/DPI math, Delivery & Verification, Session/Lease, LockFileEx JSONL trace, Security/DACL/anchored traversal, CLI/FFI/npm packaging, Real-world computer use, Test suite audit).
  - **Quy trình Remediation theo Finding IDs (`FINAL-WIN-Fxxx`)**:
    - Nếu Sol trả về bất kỳ finding nào (`REJECTED`), AGY Builder lập tức khắc phục theo từng finding.
    - Các vòng thẩm định tiếp theo **chỉ review trên các finding bị reject (Findings-Only Review)**, bảo toàn các finding đã APPROVED.
    - Sau khi tất cả `FINAL-WIN-Fxxx` đều đạt APPROVED, chạy lại toàn bộ Cumulative Regression Suite (146+ normal tests, 7 serial native gates, clippy, fmt, FFI, npm).
    - Chỉ sau khi Sol Reviewer xác nhận **`FINAL_PROJECT_VERDICT: APPROVED`**, Orchestrator mới được phép tuyên bố dự án hoàn thành 100%.
  - **Chẩn đoán Lỗi 429 Model Cooldown trên Codex CLI (API Pool / Local Service)**:
    - Khi backend `codex_local_access` qua Codex CLI trả về `HTTP 429: Too Many Requests` kèm payload `{"error": {"code": "model_cooldown", "last_upstream_error": "usage_limit_reached..."}}`: tất cả credentials của họ model GPT (`gpt-6-sol`, `gpt-6-astra`, `gpt-5.6-luna`, `gpt-5.6-terra`) đang chạm usage limit upstream và bị khóa trong `reset_seconds`.
    - Khi đó, lệnh gọi `codex exec` qua CLI sẽ bị treo chờ phản hồi cho đến khi hết timeout subshell (Exit 124).
    - Orchestrator phải chủ động **health/quota probe** local Codex service qua `POST /v1/responses` với input/output tối thiểu để bắt nhanh lỗi 429 và đọc `reset_time` / `reset_seconds`. Probe này chỉ kiểm tra availability/quota, **không được dùng để certify code review**.

### Thủ tục Backup Toàn diện Dự án khi Dọn dẹp Ổ đĩa (Project & Artifacts Backup Protocol)
- Khi người dùng yêu cầu backup toàn bộ dữ liệu dự án sang phân vùng khác (ví dụ ổ `E:\`) để dọn dẹp ổ hệ thống (`C:\`):
  - **4 Thành phần Bắt buộc Sao lưu**:
    1. **Mã nguồn thực thi chính (`agent-desktop-win`)**: Toàn bộ working tree và lịch sử git repository. Chú ý: có thể bao gồm cả thư mục `target/` để giữ artifacts/build cache hoặc exclude `/XD target` nếu phân vùng đích hạn chế dung lượng.
    2. **Mã nguồn gốc đối chiếu (`agent-desktop-source`)**: Bản sao upstream đầy đủ để phục vụ so sánh contract.
    3. **Toàn bộ Logs & Task Prompts Sol / AGY (`%LOCALAPPDATA%\Temp\`)**: Quét và copy toàn bộ các file log, task spec, commit prompts và kết quả thẩm định JSON (`sol_*_result.json`, `agy_*.log`, `supervisor*.json`, v.v.). Đây là bằng chứng pháp lý kỹ thuật của mọi quyết định SoftFac.
    4. **Dữ liệu Software Factory Engine (`%USERPROFILE%\.hermes\software-factory\runs\`)**: Chứa toàn bộ lịch sử runs, AST plans canonical, snapshots và audit ledger.
  - **Công cụ Sao lưu Chuẩn hóa trên Windows**:
    - Sử dụng `robocopy <src> <dst> /E /R:1 /W:1 /NP /NFL /NDL` để sao lưu đệ quy đa luồng, bảo toàn timestamp, permissions và tự động bỏ qua file khóa mà không làm treo subshell.
    - Với các file đơn lẻ trong `Temp`, dùng PowerShell lọc mẫu regex `Where-Object { $_.Name -match 'sol|agy|supervisor|m5|m6|m7|m8|softfac|native_gate|gate_' }` để gom toàn bộ logs liên quan.
  - **Hậu kiểm Xác thực Tính Toàn vẹn (Post-Backup Verification)**:
    - Sau khi copy, bắt buộc kiểm tra và báo cáo: Tổng số files, tổng dung lượng từng thư mục (MB/GB), trạng thái `git status` trên thư mục đích, và dung lượng còn trống trên ổ đĩa đích trước khi xác nhận an toàn để người dùng dọn dẹp ổ nguồn.

### Packaging, npm Postinstall & Windows CLI/Release Artifacts Pitfalls (Milestone 5 / Gate F)
- **Đồng bộ Ma trận Build Release & npm Packaging**:
  - Không được quảng bá nền tảng (ví dụ `win32-arm64`) trong `npm/package.json` hoặc script cài đặt nếu `.github/workflows/release.yml` chưa có runner hoặc cross-compilation sinh asset thực tế (`aarch64-pc-windows-msvc`). Phải đồng bộ 1:1 giữa danh sách target phân phối và release matrix.
- **Đồng bộ Tài liệu Kế hoạch khi Defer Kiến trúc (ARM64 Planning Deferral)**:
  - Khi hoãn phát hành một target nền tảng (như Windows ARM64) sang phase sau, bắt buộc phải rà soát và cập nhật đồng bộ toàn bộ tài liệu quy hoạch (`docs/plans/*.md`), bảng tiến độ và checklist nhiệm vụ (`tasks/todo.md`). Tuyệt đối không để sót các câu hứa hẹn asset artifact hoặc mô tả target đang được build trong Phase hiện tại, tránh bị Reviewer từ chối vì tài liệu mâu thuẫn với thực tế release.
- **Cô lập Kiểm thử CLI Action cho Nền tảng Mục tiêu (`#[cfg(target_os = "windows")]`)**:
  - Khi viết integration test cho native CLI action (như `cli_process.rs`), bắt buộc phải bọc test case trong `#[cfg(target_os = "windows")]`. Tránh để test chạy trên các worker CI khác (macOS/Linux) không có quyền trợ năng (Accessibility permissions) làm gãy pipeline kiểm thử chung.
- **Dọn dẹp Thư mục Tạm Postinstall khi thiếu công cụ ngoài**:
  - Script cài đặt `postinstall.js` không được phụ thuộc hoàn toàn vào command `trash` bên ngoài để xóa thư mục staging (`.extract-*`). Trên Windows không có sẵn lệnh `trash`, code phải có fallback cưỡng bức gọi trực tiếp `fs.rmSync(stagingDir, { recursive: true, force: true })` để không bỏ sót thư mục rác trên đĩa người dùng.
- **Ràng buộc Companion Worker khi Override Binary Path**:
  - Khi người dùng override đường dẫn binary qua biến môi trường `AGENT_DESKTOP_BINARY_PATH`, Windows runtime bắt buộc phải kiểm tra sự tồn tại của companion worker `agent-desktop-capture-worker.exe` bên cạnh binary được chỉ định (tương tự `agent-desktop-mac-helper` trên macOS), ném lỗi rõ ràng nếu thiếu để tránh lỗi sập runtime ngầm khi chụp màn hình.
- **Ổn định Hóa Shell-Surface Tests Dưới Chạy Song Song (`cargo test`)**:
  - Các tests kiểm tra shell surfaces (`Taskbar`, `SystemTray`) khi chạy song song cùng toàn bộ test suite của workspace dễ gặp timeout hoặc xung đột handle nếu cửa sổ Explorer shell bị bận hoặc chưa kịp render. Cần cấu hình timeout hợp lý hoặc mock/deadline isolation để toàn bộ bài test pass tin cậy dưới lệnh `cargo test` mặc định.

### Kiểm thử Adapter & Shell Surface Mapping khi Window ID là Chuỗi Non-numeric
- Khi caller gọi `observe_tree` với ID là tên tượng trưng (ví dụ `\"taskbar\"`, `\"system-tray\"`), adapter không được parse số trực tiếp (`id.parse::<usize>()` thất bại và trả về lỗi sớm).
- Bắt buộc kiểm tra `system::surfaces::match_shell_surface_id(id)` để phân giải chuỗi sang HWND tương ứng trước khi parse số thông thường, bảo đảm hợp đồng kiểm thử và tích hợp shell surface hoạt động trơn tru.

### Kỹ thuật Chặn Đứng Ancestor-Swap Race Cấp Kernel NT (`NtCreateFile` & Retained Directory Handles)
- **Hạn chế của Win32 Path APIs**: Việc mở và kiểm tra từng cấp thư mục bằng đường dẫn Win32 tuyệt đối (`CreateFileW`) luôn tồn tại cửa sổ thời gian (race condition) để kẻ tấn công hoán đổi một thư mục cha trung gian bằng Junction/Reparse Point trỏ ra ngoài root trước khi file con được tạo, gây side-effect tạo file rỗng hoặc thư mục trái phép ngoài ý muốn trước khi bước hậu kiểm phát hiện và từ chối handle.
- **Directory-Anchored Traversal (`NtCreateFile`)**:
  - Khởi tạo handle gốc an toàn cho thư mục private root (`AutoHandle`).
  - Mọi thao tác duyệt, tạo và mở thư mục con hoặc file lá bên trong phải sử dụng hàm NT native `NtCreateFile` từ `ntdll.dll` kết hợp trường `RootDirectory` trong `OBJECT_ATTRIBUTES` neo trực tiếp vào handle thư mục cha đã được xác thực trước đó.
  - Tên thành phần truyền vào `UNICODE_STRING` chỉ là tên relative trực tiếp của một cấp duy nhất (single path component), hoàn toàn triệt tiêu việc phân giải chuỗi đường dẫn ở tầng Win32 Object Manager namespace.
- **Giữ Handle Khóa Ancestor Không Cho Phép Xóa (`retained_ancestors`)**:
  - Toàn bộ handle các cấp thư mục trung gian từ root đến thư mục chứa file đích phải được lưu trữ trong danh sách giữ handle mở (`Vec<AutoHandle>`) với quyền chia sẻ loại trừ cờ `FILE_SHARE_DELETE`.
  - Giữ các handle này liên tục cho đến khi hoàn tất việc kiểm tra lá (`leaf validation`) và thao tác truncate. Kernel I/O Manager của Windows NT sẽ tự động từ chối bất kỳ nỗ lực đổi tên, xóa, hoặc thay thế bằng Junction nào trên chuỗi thư mục này từ các tiến trình khác (`STATUS_SHARING_VIOLATION`).
- **Xác thực Đầy đủ Cấp Lá Trước Khi Truncate**:
  - File con đích được mở bằng `FILE_OPEN_IF` (không dùng `CREATE_ALWAYS`).
  - Kiểm tra toàn diện `FILE_ATTRIBUTE_REPARSE_POINT`, `nNumberOfLinks <= 1`, và canonical containment bằng `GetFinalPathNameByHandleW` trên chính handle con vừa mở.
  - Chỉ khi toàn bộ kiểm tra bảo mật hợp lệ 100%, mới thực thi truncate file bằng `SetEndOfFile`.

### Triển khai Master Milestone 5 (T6 MSAA & T7 CDP) trong Ranh giới Scope Hợp lệ
- **Cấm Tạo Thư mục/Crate Mới Ngoài Scope**:
  - Không được tạo các crate hoặc module mới chưa được phê chuẩn như `crates/windows/src/msaa/` hoặc `crates/windows/src/cdp/`.
  - Toàn bộ logic tương tác IAccessible/MSAA và endpoint CDP phải được tích hợp trực tiếp vào `crates/windows/src/adapter.rs` hoặc mở rộng trên các submodule hiện hữu đã được duyệt (`uia/`, `system/`, `process/`).
- **Phân tách Rõ Ràng Hành Vi Giữa Native Chrome và Web Content**:
  - Đối với ứng dụng Chromium/Electron (T7 / Gate E): Native window frame/chrome vẫn do Win32/UIA layer đảm nhiệm; chỉ vùng web document view mới được định tuyến qua CDP adapter.
  - Mọi sự cố ngắt kết nối (CDP disconnect) sau khi submit command không được coi là bằng chứng không có mutation xảy ra (`mutation uncertain`).

### Kỹ thuật Lập trình Windows Visual Candidate & Physical Input Pitfalls (Master M4 / T4, T5)
- **Pixel Capture Origin & Screen-Space Bounding Coordinates**:
  - `ImageBuffer` khi chụp cửa sổ hoặc màn hình bắt buộc phải lưu trữ tọa độ gốc vật lý (`capture_origin_x`, `capture_origin_y` theo desktop physical pixels) và bảo toàn gốc này xuyên suốt quá trình encode/decode ảnh (PNG, Bitmap).
  - Khi trích xuất ứng viên trực quan (Visual Candidates / OCR), bounding box của phần tử phải được offset cộng dồn với tọa độ gốc vật lý của ảnh chụp thay vì chỉ trả về tọa độ cục bộ trên ảnh (`image-local`). Nếu không cộng offset, thao tác click/move sẽ trượt lên góc trái trên màn hình desktop.
  - Chuẩn hóa layout byte kênh màu giữa GDI/GDI+ (thường là BGRA) và core model (RGBA) tránh đảo màu đỏ/xanh khi phân tích ảnh hoặc bóc tách candidate.
- **Window ID Parsing cho Visual Observation Tree**:
  - Khi quan sát cây phần tử trực quan (`observe_visual_tree`), chuỗi định danh cửa sổ từ `WindowInfo` thường mang tiền tố phân loại (ví dụ `w-<HWND>` hoặc format chuỗi).
  - Bắt buộc phải bóc tách tiền tố chuỗi (strip prefix `w-`) trước khi parse thành số nguyên HWND; tuyệt đối không gọi trực tiếp `id.parse::<isize>()` trên chuỗi `w-...` vì sẽ thất bại âm thầm dẫn đến không sinh được visual refs cho cửa sổ.
- **Visual Refs Không Mang Semantic Actions & Preflight Chặt Chẽ**:
  - Phần tử có nguồn gốc trực quan (`source: visual`, `IdentifierKind::VisualHash`) không bao giờ có các semantic patterns (như UIA `Invoke`, `Toggle`, `SetValue`).
  - Phải gán quyền hành động rỗng (`available_actions: []`) và định tuyến qua physical action preflight (`SendInput` mouse click/move/drag hoặc keyboard text). Từ chối mọi yêu cầu semantic action với mã lỗi `ActionNotSupported`.
  - Trong preflight: `TypeText` chỉ click kích hoạt focus khi có cờ `allow_cursor_move: true`. Bắt buộc kiểm tra `GetWindowRect` thành công với kích thước dương, và bảo đảm tính toán chính xác khi cửa sổ nằm trên màn hình có tọa độ ảo âm (`win_left < 0` hoặc `win_top < 0`).
- **Kiểm chứng Hình học Revalidation trên Visual Refs**:
  - Khi caller ra lệnh tương tác trên một visual ref entry, adapter bắt buộc phải chụp lại ảnh hoặc kiểm tra tính hợp lệ của hash pixel / vùng hình học trước khi click. Nếu cửa sổ bị di chuyển, cuộn, hoặc thay đổi nội dung, phải lập tức từ chối với lỗi `StaleRef` hoặc `GeometryMismatch`.
- **Tích Lũy Trạng Thái Phân Phối (Accumulated Delivery State)**:
  - Khi thực hiện chuỗi thao tác tổng hợp vật lý (ví dụ: `MoveCursor` -> `MouseDown` -> `MouseUp` hoặc chuyển đổi focus):
  - Trạng thái gửi phải được cộng dồn theo từng bước. Nếu đã thực hiện ít nhất một thao tác vật lý thành công (hoặc focus đã thay đổi) nhưng bước sau thất bại, bắt buộc phải báo cáo trung thực là `PartialDelivery` (`DeliveredUnverified`), tuyệt đối không được ghi đè bằng `NotDelivered` (gây retry trùng lặp) hoặc `DeliveredVerified` (khi chưa có hậu kiểm).
- **Hardening Native Input Verification Test (`native_gate_f`)**:
  - Trong kiểm thử tương tác thực tế với Win32 Edit Control, phải assert `SetFocus` trả về thành công (`!prev_focus.is_null() || current_focus == edit_hwnd`).
  - Bắt buộc bổ sung vòng lặp Windows Message Pumping (`PeekMessageW` / `TranslateMessage` / `DispatchMessageW`) ngay sau khi đổi focus, sau khi phát sự kiện chuột và sau khi gửi text.
  - Phải kiểm tra và xác nhận đồng thời cả văn bản dựng sẵn NFC và văn bản tổ hợp NFD (Unicode combining diacritics như `'e' + '\u0301' = 'é'`) được nhận chính xác trong Edit Control và bắt được các thông điệp Win32 thực tế (`WM_KEYDOWN`, `WM_CHAR`, `WM_LBUTTONDOWN`).

### Đối chiếu Hợp đồng Toàn diện & Phục hồi Kế hoạch Gốc (Canonical Master Plan Reconciliation)
- **Kiểm đếm Từng Tiêu chí Độc lập (Granular Criteria Counting)**:
  - Khi đối chiếu repository thực tế với Master Plan gốc (Astra Planner), không được gộp các tiêu chí thành đại diện theo task hay milestone.
  - Phải liệt kê và đánh giá trạng thái độc lập của từng acceptance criterion một cách rõ ràng (ví dụ toàn bộ 42 tiêu chí từ T1_BASELINE đến T10_HANDOFF), tránh việc suy diễn sai lệch tỷ lệ hoàn thành.
- **Phân định Rõ ràng Biên giới Mã nguồn Được phép Sửa đổi (Scope Reconciliation)**:
  - Trước khi sửa đổi mã nguồn theo hợp đồng Master Plan, phải đối chiếu giữa phạm vi file ban đầu (`editable_scope`) và kiến trúc phân rã module thực tế đã được Sol Reviewer phê duyệt ở các round trước (như `geometry/`, `input/`, `process/`, `system/`, `uia/`).
  - Tuyệt đối không tự ý tạo thêm các module/crate nằm ngoài ranh giới đã phê duyệt nếu chưa được Reviewer chấp thuận; nếu thiếu phạm vi, phải thực hiện đánh giá `BLOCKED_SCOPE` hoặc tích hợp vào các module đã được duyệt hợp lệ.
- **Tiêu chuẩn Hoàn thành Tối thượng**:
  - Không lấy việc hoàn thành các milestone đặt tên theo phase (như Milestone 1 đến Milestone 6) làm bằng chứng thay thế cho Astra Master Milestones M1 đến M8.
  - Chỉ tuyên bố hoàn thành toàn bộ hệ thống khi tất cả tiêu chí gốc T1–T10 được kiểm chứng, toàn bộ các Native Gates A–N và mixed-DPI được thực thi, và Sol Reviewer hoàn tất Holistic Final Review trả về APPROVED 100%.

### Native Synthetic Input, Windows Shell Surfaces & State Directory Security Pitfalls (Milestone 4 / Gate B, D, E)
- **Native Synthetic Input (`SendInput`) & Unicode Surrogates**:
  - Khi phát ký tự ngoài BMP (Unicode code point > `0xFFFF`, ví dụ emoji), bắt buộc phải tính toán và phát đủ cả 2 phần tử surrogate pair (High Surrogate `0xD800..0xDBFF` và Low Surrogate `0xDC00..0xDFFF`) với cờ `KEYEVENTF_UNICODE`. Không bao giờ chỉ phát duy nhất surrogate đầu tiên.
  - `VK_RSHIFT` trên Windows không mang cờ `KEYEVENTF_EXTENDEDKEY`. Chỉ các phím như `VK_RCONTROL`, `VK_RMENU` (AltGr/Right Alt), Insert, Delete, Home, End, Prior, Next, và các phím điều hướng mới là extended keys.
  - Không bao giờ nuốt lỗi khi thu hồi modifier keys (Shift, Ctrl, Alt). Lỗi bắn input phải được chẩn đoán và trả về lỗi có cấu trúc.
  - Khi chạy trong môi trường CI/Terminal không có desktop tương tác hoặc không có quyền Admin, `SendInput` có thể trả về `0` với Win32 error 5 (`Access is denied` do UIPI). Bắt buộc phải ánh xạ thành `ActionFailed` / `PlatformUnsupported` có cấu trúc với chi tiết UIPI thay vì hoảng loạn `unwrap()`.
  - Khi đọc clipboard kiểu `CF_UNICODETEXT`, không được duyệt con trỏ `*ptr != 0` không giới hạn; bắt buộc kiểm tra độ dài tối đa qua `GlobalSize(h_mem) / sizeof(u16)` để tránh tràn bộ nhớ khi clipboard data không có null terminator.
- **Windows Shell Surfaces Resolution & Snapshot Integration**:
  - Khi caller yêu cầu snapshot/observe một surface đặc biệt (`SnapshotSurface != Window`, ví dụ Taskbar, SystemTray, ActionCenter, StartMenu), resolver chuyên dụng của shell surface bắt buộc phải có độ ưu tiên cao hơn việc chọn cửa sổ ứng dụng thông thường (`app_name`) và kiểm tra `window_id` (`surface.is_shell_surface()` phải được xử lý TRƯỚC `if let Some(id) = window_id`).
  - Ánh xạ đầy đủ toàn bộ enum `SnapshotSurface` sang Win32 HWND/Class name thực tế (`Shell_TrayWnd`, `TrayNotifyWnd`, `Windows.UI.Core.CoreWindow`).
  - Khi tra cứu tiến trình của shell surface, không bao giờ bịa danh tính giả mạo (`explorer.exe`); phải lấy PID thực tế từ HWND qua `GetWindowThreadProcessId` và truy vấn process instance token thực tế.
  - Khi phân giải HWND của shell surface thất bại, phải **fail-closed** (trả về `Error::NotFound` hoặc `Error::TargetClosed`), cấm nuốt lỗi hay bịa đặt dummy `WindowInfo` với PID 0. Các bề mặt của OS khác (Dock, Spotlight) trên Windows phải trả về `Error::PlatformUnsupported`.
  - Trong `adapter.rs::observe_tree`, khi `ObservationRoot::Window(win)` có `win.id` là chuỗi không phải số (như `"taskbar"`, `"system-tray"`), phải ánh xạ qua `system::surfaces::match_shell_surface_id(&win.id)` để lấy HWND thực tế thay vì parse `usize` lỗi rồi fail.
- **Private State Directory Security Gate & Anti-TOCTOU**:
  - Khi tạo/xác thực thư mục trạng thái riêng tư, bắt buộc thiết lập DACL bảo vệ (`PROTECTED_DACL_SECURITY_INFORMATION`) và duyệt kiểm tra từng ACE qua `GetAce`: chỉ duy nhất current User SID (hoặc SYSTEM) được cấp quyền `GENERIC_ALL`, từ chối bất kỳ ACE nào cấp quyền cho nhóm khác (như `BUILTIN\\Users` hay `Everyone`).
  - Xác thực số lượng hardlinks `nNumberOfLinks == 1` và quét toàn bộ cây thư mục tổ tiên để bảo đảm không có symlink/junction reparse point.
  - Khi mở handle xác thực thư mục, **tuyệt đối không truyền cờ `FILE_SHARE_DELETE`** (chỉ cho phép `FILE_SHARE_READ | FILE_SHARE_WRITE`). Giữ handle đã verify trong cấu trúc RAII (`PrivateStateDir`) để chặn đối thủ xóa, di chuyển hoặc hoán đổi thư mục (chống tấn công TOCTOU).
  - Trong `resolve_relative_path`: phải từ chối cả `Component::Prefix` và `Component::RootDir` (các đường dẫn tuyệt đối như `C:\outside` hoặc `\outside`), chỉ chấp nhận `Component::Normal` và `Component::CurDir` để triệt tiêu path traversal ngoài cây thư mục bảo mật.
  - **Chống Truncation Race trên Child Files (`CREATE_ALWAYS` Trap)**: Trong `create_child_file`, không được mở bằng `CREATE_ALWAYS` trực tiếp vì kernel sẽ cắt cụt file (`TRUNCATE`) trước khi code kịp đọc metadata kiểm tra hardlink count `nNumberOfLinks`. Nếu kẻ tấn công đặt trước một hardlink trỏ đến file nhạy cảm ngoài thư mục, thao tác này sẽ phá hủy file đó trước khi hàm kịp phát hiện và trả về `PermDenied`. Bắt buộc mở bằng `OPEN_ALWAYS` / `CREATE_NEW`, kiểm tra `nNumberOfLinks <= 1` và `reparse_point == false` trên handle mở, rồi mới truncate/write.
  - **Triệt tiêu Ancestor-Swap Race bằng Post-Open Handle Verification**: Sau khi gọi `CreateFileW`, dùng ngay `GetFinalPathNameByHandleW(handle, ..., FILE_NAME_NORMALIZED | VOLUME_NAME_DOS)` trên chính handle vừa mở để xác thực đường dẫn vật lý thực tế nằm trọn vẹn trong `canonical_root`, bảo đảm không bị hoán đổi thư mục cha bằng symlink/junction giữa thời điểm kiểm tra đường dẫn và mở file.

### Kỹ thuật lập trình hệ thống Windows, COM/UIA & Win32 API Pitfalls
- **COM Apartment Isolation & UIA Lifetime Rules**:
  - Microsoft UIA client elements bị ràng buộc chặt chẽ với COM apartment đã khởi tạo chúng. Không được để `UiaElement` outlive `ComApartmentGuard` (nơi gọi `CoUninitialize`), và không declare `Send`/`Sync` tùy tiện cho COM raw wrappers.
  - Mọi thao tác UIA (acquisition, tree traversal, pattern execution, element release) phải chạy trên một dedicated long-lived MTA worker thread.
  - Không coi `RPC_E_CHANGED_MODE` là thành công khi vào MTA; phải coi đó là error và fail-closed.
  - Luôn sử dụng safe wrappers (`SafeBstr`, `SafeArray`) tự giải phóng bộ nhớ qua `SysFreeString` và `SafeArrayDestroy` thay vì thao tác con trỏ trần. Kiểm tra `SafeArrayGetVartype(psa, &mut vt)` đảm bảo đúng kiểu (`VT_I4` / `VT_INT`), và không bỏ qua HRESULT của `SafeArrayUnaccessData` trong AccessGuard.
- **Tree Materialization & Traversal Fail-Closed**:
  - Không bao giờ chuyển các read property bị lỗi thành giá trị mặc định (như 0 hay chuỗi rỗng) rồi đánh dấu là `Known`.
  - Nếu duyệt first-child bị lỗi HRESULT, không được suy diễn phần tử đó là leaf rỗng; phải ghi nhận lỗi hoặc fail-closed. `states_complete` chỉ được đặt là `true` khi tất cả các lần đọc thuộc tính thành công 100%.
- **Cache Request Contract & Buffer Limiting (G14)**:
  - Khi `BuildUpdatedCache` hoặc lấy window-root cache bị lỗi, cấm fallback âm thầm sang uncached element; phải fail-closed.
  - Bắt buộc thực thi cắt tỉa độ dài chuỗi theo `max_text_bytes` và `max_field_bytes` khi trích xuất text từ UIA elements.
- **Action Worker Deadline & Postcondition Verification (G16)**:
  - Kênh worker thực thi Action Pattern phải nhận `Deadline` và kiểm tra hạn chót trước mỗi thao tác; timeout của caller phải clamp theo lease deadline.
  - Chỉ gọi thành công HRESULT chưa đủ để coi là `verified`. Mọi semantic action (`Invoke`, `SetValue`, `Toggle`, `Select`) phải được phân loại là `delivered_unverified` trừ khi có quan sát kiểm chứng postcondition thực tế (re-read `Value`, `ToggleState`, selection, hoặc focus). Với `Toggle`, `Check`/`Uncheck` phải chạy vòng lặp kiểm tra trạng thái mục tiêu, không được chỉ toggle mù 1 lần.
- **GDI & Capture Worker Deadline Isolation & Process Reclamation (G18)**:
  - Mọi handle GDI (`HDC`, `HBITMAP`, object được select qua `SelectObject`) bắt buộc bọc trong RAII guards.
  - Các hàm Win32 blocking như `PrintWindow`, `BitBlt` hoặc mã hóa PNG có thể treo vô hạn nếu ứng dụng mục tiêu bị treo (hung). Bắt buộc thực thi chụp màn hình trên một bounded capture worker process (`agent-desktop-capture-worker.exe`) riêng biệt có khả năng ngắt bằng `TerminateProcess`.
  - Tuyệt đối không giải phóng GDI handles đồng thời từ calling thread khi worker thread còn đang thực thi native Win32 call (ngăn chặn use-after-free).
  - Khi timeout hoặc kill tiến trình con, bắt buộc thực hiện **bounded polling reap (`child.try_wait()`)** có timeout giới hạn (grace period) thay vì gọi `child.wait()` blocking vô hạn.
  - Chỉ ủy quyền cho binary worker con hợp lệ (`agent-desktop-capture-worker.exe` hoặc test binary canonical), cấm fallback ngầm về arbitrary executables dựa trên chuỗi tên tự do.
- **Deadline Clamping cho Win32 Waits (`WaitForSingleObject`)**:
  - Hằng số `INFINITE` trong Win32 có giá trị `0xFFFFFFFF` (`u32::MAX`).
  - Khi chuyển đổi finite deadline sang Win32 timeout milliseconds, nếu `remaining_ms >= u32::MAX as u128` thì **phải giới hạn cứng thành `u32::MAX - 1`** để tránh việc Win32 hiểu nhầm thành đợi vô hạn (`INFINITE`).
  - Phép chia hoặc làm tròn `as_millis()` làm mất phần dư sub-millisecond; nếu `remaining > Duration::ZERO` nhưng `as_millis() == 0`, phải làm tròn lên tối thiểu `1 ms` để giữ trọn vẹn thời lượng timeout.
- **Fail-Closed Process Identity & PID Reuse**:
  - PID trên Windows NT được tái sử dụng rất nhanh. Do đó, việc ánh xạ cửa sổ (`resolve_window`) hoặc tiến trình (`verify_process_generation`) phải gắn liền với creation token (`process_instance` timestamp). Thiếu token này hoặc token không khớp phải lập tức ném lỗi fail-closed (`StaleRef` / `NoSuchProcess`), cấm fallback âm thầm.
- **Strict Element Ref Resolution (Gate A)**:
  - Trước khi resolve element, phải verify `source_window_id` thuộc về live PID và generation hợp lệ.
  - Khi tìm kiếm element theo `AutomationId`, phải quét toàn bộ ứng viên để phát hiện duplicate ID. Nếu có nhiều hơn 1 element trùng ID, bắt buộc ném lỗi `AmbiguousTarget`, không được chọn bừa phần tử đầu tiên.
- **Action Pattern Verification (Gate A)**:
  - Chỉ gọi thành công HRESULT chưa đủ để coi là `verified`. Mọi semantic action (`Invoke`, `SetValue`, `Toggle`, `Select`) phải được phân loại là `delivered_unverified` trừ khi có quan sát kiểm chứng postcondition thực tế (re-read `Value`, `ToggleState`, selection, hoặc focus).
  - Với control 3 trạng thái (`Toggle`), `Check`/`Uncheck` phải chạy vòng lặp kiểm tra trạng thái mục tiêu, không được chỉ toggle mù 1 lần.
- **GDI & Capture Resource Cleanup (Gate A/Gate C)**:
  - Mọi handle GDI (`HDC`, `HBITMAP`, object được select qua `SelectObject`) và stream GDI+ bắt buộc phải được bọc trong RAII guards để đảm bảo giải phóng tài nguyên kể cả khi xảy ra early return (`?`).
  - Cấm fallback trả về ảnh trắng/rỗng nếu cả `PrintWindow` và `BitBlt` đều fail; phải fail-closed với lỗi cấu trúc.
- **Parallel Test Isolation trên Windows**:
  - Test runner mặc định của Cargo chạy đa luồng song song. Các test tương tác trực tiếp với Windows GUI (tạo window, focus HWND, move window, capture) dễ bị tranh chấp focus/deadline. Cần có cơ chế process-wide lock hoặc serialization guard để toàn bộ test suite pass tin cậy dưới lệnh mặc định `cargo test`.
- **Tương thích CLI Subprocess & Command Length trên Windows**:
  - Khi truyền prompt dài cho các CLI tool (như Codex/AGY) qua shell/terminal, tránh truyền argument trực tiếp vượt quá giới hạn 8191 ký tự của Windows `cmd.exe`/Win32 `CreateProcess`. Bắt buộc truyền qua stdin hoặc file tạm.
  - Khi đợi background subagent hoặc reviewer, dùng polling qua `tasklist`/`psutil` với interval hợp lý, tránh lặp blind sleep ngắn gây lãng phí CPU.

### Regression Tests & Evidence Ledger — agent-desktop-win
  - Khi viết regression test cho một finding (như kiểm thử dispatch mock CDP `DOM.scrollIntoViewIfNeeded` cho F009):
    - Test **bắt buộc phải assert mutation/dispatch thực tế** trên mock server hoặc live backend (ví dụ kiểm tra danh sách request log / counter của server: `assert!(logged_reqs.iter().any(|m| m == "DOM.scrollIntoViewIfNeeded"))`).
    - Tuyệt đối không viết test chỉ kiểm tra rỗng, chỉ assert `result.is_ok()` hời hợt mà không kiểm chứng lệnh có thực sự được gửi tới server hay không, hoặc chỉ assert trường hợp từ chối ID = 0 rồi đặt tên hàm là \"cdp dispatch\". Sol Reviewer sẽ lập tức từ chối các bài test hình thức này.
- **Đồng Bộ Hoàn Toàn 1:1 Giữa Evidence Ledger và Todo Checklist (Verbatim Synchronization)**:
  - Tài liệu bàn giao (`docs/evidence-ledger-gates-a-n.md`) và file theo dõi (`tasks/todo.md`) phải được đồng bộ chính xác từng từ (verbatim), không dùng tóm tắt rút gọn hay diễn giải lệch pha.
  - Trạng thái checklist phải phản ánh đúng tình trạng mã nguồn trên commit HEAD thực tế, không được để nhãn `IN PROGRESS` hay bỏ trống ô checkbox khi code đã hoàn thành.

### Full-Project Holistic Review Semantics — agent-desktop-win
- **Bản Chất Đích Thực Của Full-Project Holistic Review (Anti-Surface Check Trap)**:
  - Một lượt review toàn diện (Holistic Review) **KHÔNG PHẢI LÀ REVIEW TEST CHẠY PASS HAY DỌN DẸP FILE DOCS**.
  - Việc kiểm tra repo compile được, unit tests pass (146/146), clippy/fmt clean, hay dọn dẹp `tasks/todo.md` chỉ là bằng chứng bề mặt (superficial evidence), tuyệt đối không đồng nghĩa với tính đúng đắn của runtime logic.
  - Reviewer (Sol `gpt-6-sol`, reasoning `high`) bắt buộc phải dành phần lớn thời gian và tokens để **đọc trực tiếp từng dòng mã nguồn sản xuất (Implementation -> Behavior)**, truy vết các mutation path, fallback ordering, concurrency, stale identity, delivery semantics và 20 kịch bản đối kháng (adversarial scenarios) để phát hiện các lỗi ẩn mà unit test chưa bao quát được.
  - Orchestrator tuyệt đối không được coi việc test pass hay dọn docs là đã xong việc để vội vã tuyên bố kết thúc dự án. Phải đợi Sol Reviewer đọc sâu production code, xuất findings có mã định danh chuẩn `FINAL-WIN-Fxxx`, cho AGY batch-remediate toàn bộ findings, review findings-only đạt 100% approved, rồi mới tiến hành Final Closure Review.
- **Bắt buộc hiển thị PID tiến trình thời gian thực**:
- Mỗi khi kích hoạt hoặc báo cáo trạng thái của Builder (AGY / `agy.exe`), Reviewer (Sol / `codex.exe`) hoặc Watchdog Daemon, bắt buộc phải xuất đầy đủ PID thực tế, trạng thái thực thi (`running`/`exit`), và mức sử dụng tài nguyên (RAM) làm bằng chứng minh bạch, không nói chung chung.
- **Bằng chứng Nghiệm thu**: Bắt buộc xuất toàn văn file JSON / log output có `overall_status: "APPROVED"` làm bằng chứng thực tế trước khi chuyển sang Milestone tiếp theo.

### Win32 Private State Error Mapping (T9 / Gate L-M-N)
- Trong hàm `open_directory_handle_with_access`: khi `CreateFileW` mở thư mục bảo mật thất bại với `ERROR_ACCESS_DENIED`, ánh xạ sang `ErrorCode::PermDenied` thay vì `ErrorCode::ActionFailed`.
- Các test như `test_deny_dacl_ace_rejected` phải phân loại đúng access-denied ACE theo `ErrorCode::PermDenied`.

### Computer-Use Amplification & Remediation Invariants (CU-M0 đến CU-M10)
- **Fail-Closed Oracle Semantics**: Không bao giờ mặc định `True` với tiêu chí lạ. Bắt buộc tất cả criteria cùng thỏa mãn (`all(...)`). Bắt buộc capture pre-action state để loại trừ các file/state đã có sẵn từ trước. Luôn đảm bảo import đầy đủ (như `import uuid`) tránh runtime `NameError`.
- **Chính xác Cờ Dòng Lệnh CLI**: Ánh xạ lệnh từ runner sang CLI phải khớp chính xác schema của clap parser (ví dụ `get` và `is` dùng `--property`, không dùng `--prop` hay `--state`). Các lệnh đọc/kiểm tra (`get`, `is`, `snapshot`) không được bị chặn bởi danh sách `available_actions` vốn chỉ dành cho mutation.
- **Ghi Nhận & Bền Vững Hóa Artifacts**: File log dữ liệu (`episodes.jsonl`, `steps.jsonl`, `artifacts.jsonl`) phải được flush/fsync từng dòng; bắt buộc tạo bản ghi artifact chuẩn theo `artifact.schema.json` khi phát sinh snapshot/trace. Báo cáo đánh giá (`baseline-report.md`, `run.json`) phải cập nhật đúng Git commit hash hiện tại của candidate.
- **Quản Lý Sandbox & Process Tree**: Giới hạn thao tác file trong `sandbox/`, chặn `..` traversal. Khi dọn dẹp tiến trình, chỉ terminate đệ quy process con do chính harness spawn, bọc trong khối `finally` xử lý cả `BaseException`.

## 6. Consistency Checklist
- Không có bước `Astra -> Sol review plan` mặc định.
- Không có đường nào cho phép AGY commit, reset, update-ref, rewrite history hoặc publish candidate.
- Runner xác lập candidate; Sol review candidate; Hermes là tác nhân duy nhất publish exact approved candidate.
- Raw HTTP không được dùng để certify Full Review/Findings-Only Review.
- Không chuyển milestone khi còn finding chưa APPROVED.
- Project-specific rules phải ở mục 5 và không override core invariants.


## BẤT BIẾN AGY CLI & ANTIGRAVITY PROXY POOL (CẤM THAY ĐỔI)
- agy CLI đã được nối vào API pool Antigravity (http://127.0.0.1:8045).
- TUYỆT ĐỐI CẤM SỬA HOẶC XÓA modelProvider trong ~/.gemini/antigravity-cli/settings.json.
- BẮT BUỘC giữ nguyên modelProvider: gemini và model: Gemini 3.8 Flash (High).
- Biến môi trường GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:8045 và GEMINI_API_KEY được duy trì cho pool.


## QUY TẮC CỐT LÕI VỀ GIAO VIỆC CHO BUILDER (CẤM CHO LÊN PLAN 2 LƯỢT)
- Khi Sol Reviewer trả về findings (REJECTED), Orchestrator BẮT BUỘC ném ĐÚNG 1 PROMPT THI CÔNG TRỰC TIẾP cho Builder.
- PROMPT PHẢI CHỈ RÕ: ĐÂY LÀ TASK FIX CODE TRỰC TIẾP, CẤM LÊN PLAN/ANALYSIS, YÊU CẦU SỬA FILE VÀ COMMIT NGAY TRONG 1 LƯỢT DUY NHẤT.
- TUYỆT ĐỐI CẤM chia làm 2 lượt (lượt 1 lên plan rồi lượt 2 mới thực thi). Builder phải edit file và commit ngay lập tức!
