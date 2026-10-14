# SoftFac v2 — Replacement continuation plan tối giản (3 milestone)

Ngày: 2026-09-12  
Trạng thái: **authoritative implementation plan; chưa thực thi trong lượt này**.

Tài liệu này thay thế kế hoạch rolling-increment trước đây trong chính file này và thay thế phần việc còn lại của `C:/Users/HH18/astra_plan.md`. Nó không sửa lịch sử: Steps 1–6 vẫn là các increment đã được Sol APPROVE/PASS; verdict Step 7 gần nhất vẫn có `STEP7-F001` và `STEP7-F002` OPEN cho đến khi candidate mới được review và approve.

Snapshot dùng để lập plan:

- Worktree: `E:/Downloads/hermes-software-factory-v2-hoh/migration-worktree-recovered2`
- Branch: `hermes/agy-migration-v2`
- HEAD: `322c13934d914eb0e870a9d06341226ab25307f7`
- Worktree đang dirty có chủ ý: implementation, tests và tracked Python bytecode. Không reset/clean/stage/commit trong lượt lập plan.
- Code dở dang đã có `validate_master_plan`, `master_plan_tasks`, `next_ready_master_task`, `failure_signature`, `is_stagnant`, planning ra `master_plan.json`, một phần task state và no-Luna repair semantics.
- Blocker hiện tại: public `FactoryEngine.execute()`/master-plan loop chưa hoàn thiện; `_execute_one_task()` vẫn dùng contract cũ ở một số chỗ; `resume()` và test fakes vẫn theo `sol_plan.json`/`Sol Planner` cũ. Focused no-Luna và preflight tests pass, nhưng full `tests/test_factory_v2.py` hiện chưa green.

Nguyên tắc trung tâm:

> **Astra lập chiến lược. Hermes lái dự án theo chiến lược đó. AGY xây. Runner kiểm chứng. Sol phán. Chỉ khi chiến lược không còn hợp lệ mới gọi Astra lại.**

## 1. Product definition mới

SoftFac v2 nhận một user objective, yêu cầu Astra tạo một master plan đủ chi tiết để Hermes tự điều phối toàn bộ execution. Hermes chọn task ready tiếp theo, dispatch AGY, gọi Runner, gọi Sol, commit exact approved candidate và cập nhật tiến độ. Routine execution không hỏi Astra task tiếp theo là gì.

Property bắt buộc:

```text
Normal N-task project, không có planning surprise:
Astra invocation count == 1
```

SoftFac v2 không phải planning platform, agent framework hay audit platform. V1 chỉ có một sequential task loop, một authoritative run state, một AGY boundary, một Runner gate, một Sol review path và một Hermes commit path. Luna nằm ngoài v1.

## 2. Role ownership

| Actor | Sở hữu | Không được làm |
|---|---|---|
| Astra | Initial master plan; decomposition; global criteria; invariants; assumptions; milestones; task graph; dependencies; task contracts; preservation constraints; non-goals; exceptional replan | Routine scheduling sau commit; implementation HOW; repair local; review/commit |
| Hermes | Master-plan cursor; ready-task selection; task/attempt state; budgets; candidate lifecycle; AGY/Runner/Sol sequencing; exceptional-replan detection; commit; resume; completion | Tự hạ criteria; tự sửa code; semantic approval thay Sol |
| AGY | Implement/repair current task trong editable scope; autonomy về HOW; optional local self-test | Acceptance; master-plan mutation; source/Git/trusted-state access; stage/commit |
| Runner | Scope/integrity checks; deterministic verification; stage; `git write-tree`; evidence; candidate identity | Semantic review thay Sol; commit/merge/push |
| Sol | Independent review trên exact candidate; APPROVE/REJECT; regression và criteria judgment | Sửa code; routine redesign master plan; commit |
| Luna | Không thuộc v1 production path | Không có route, preflight hoặc dispatch trong v1 |

Git authority được định nghĩa một câu: **Runner được stage và `git write-tree` trong host-owned candidate worktree; chỉ Hermes được `git commit`; AGY không bao giờ thấy `.git`.**

## 3. Target architecture

```text
request.json (objective + authorized scope)
                    │
                    ▼
          Astra initial master plan ───────────────┐
                    │                              │
                    ▼                              │ only verified
        immutable master_plan artifact             │ exceptional replan
                    │                              │
                    ▼                              │
         Hermes selects first ready task           │
                    │                              │
                    ▼                              │
 host-owned candidate worktree (.git host-only)    │
                    │                              │
       non-Git disposable mirror → AGY             │
                    │                 │             │
                    └── accepted atomic delta ◄────┘
                    │
                    ▼
 Runner: scope + verify + stage + git write-tree
                    │
          candidate identity =
          {base_commit, candidate_id}
                    │
                    ▼
            Sol independent review
            │                    │
          REJECT              APPROVE
            │                    │
         AGY repair      Hermes exact commit
            │                    │
            └──── Runner/Sol ◄───┘
                                 │
                    update progress/evidence
                                 │
                    Hermes selects next ready task
                                 │
                     all criteria proven? COMPLETE
```

Normal commit quay về Hermes task selection, không quay về Astra.

## 4. Astra master-plan contract

Master plan là một immutable, content-addressed JSON artifact. `run_state.json` chỉ trỏ tới artifact bằng `master_plan_ref`; task definitions không được copy sang state.

Minimal contract:

```json
{
  "schema_version": 1,
  "request_ref": "request.json",
  "global_criteria": [
    {"id": "G1", "statement": "..."}
  ],
  "architecture_invariants": [
    {"id": "A1", "statement": "..."}
  ],
  "assumptions": [
    {"id": "AS1", "statement": "...", "critical": true}
  ],
  "non_goals": ["..."],
  "milestones": [
    {
      "id": "M1",
      "objective": "...",
      "tasks": [
        {
          "id": "T1",
          "objective": "...",
          "depends_on": [],
          "editable_scope": ["..."],
          "acceptance_criteria": ["..."],
          "verification_commands": ["..."],
          "preservation_constraints": ["..."]
        }
      ]
    }
  ]
}
```

Validation bắt buộc:

- IDs unique và ổn định; dependency tồn tại, acyclic và chỉ trỏ task trong plan.
- Mọi `editable_scope` nằm trong authorized user scope; path canonical, không overlap protected roots.
- Mỗi task có objective và acceptance criteria kiểm tra được.
- Mỗi global criterion được ít nhất một task nhận trách nhiệm; coverage mapping chỉ chứng minh plan có task bao phủ, không chứng minh criterion đã PASS.
- `verification_commands` là đề xuất cho Runner và vẫn phải qua command policy; Astra không cấp shell authority.
- Master plan mô tả WHAT, WHY, ORDER, DEPENDENCIES, CONTRACT và ACCEPTANCE; không khóa implementation HOW.
- V1 chạy sequential theo stable plan order; không tạo scheduler, registry hoặc parallel execution engine.
- Exceptional replan chỉ được sửa current/pending plan. Completed commits và evidence không được viết lại.
- Để không reset budget khi replan, task đang active phải giữ nguyên `task_id`; nếu contract cũ bị disproved, replacement contract dùng cùng ID. Nếu không map được an toàn, Hermes BLOCKED thay vì đoán.

## 5. Hermes execution semantics

Hermes tính task state thay vì lưu duplicate truth:

- `COMMITTED`: task ID có trong `completed_commits`.
- `ACTIVE`: bằng `current_task_id`.
- `READY`: chưa committed, không active và mọi `depends_on` đã committed.
- `BLOCKED_BY`: dependency chưa committed.

Selection rule v1: chọn READY task đầu tiên theo thứ tự milestone/task trong immutable master plan. Không gọi model để scheduling.

Routine task flow:

1. Chọn ready task và khóa task contract từ master plan.
2. Persist attempt reservation rồi tăng `current_task_attempts` trước AGY dispatch.
3. Tạo non-Git disposable mirror từ host-owned candidate worktree.
4. AGY implement hoặc repair trong task scope.
5. Boundary kiểm tra toàn delta rồi atomic sync allowed changes về host candidate.
6. Runner kiểm tra scope/integrity, chạy deterministic verification, stage và tạo `candidate_id = git write-tree`.
7. Runner FAIL → AGY repair cùng task; Astra count không đổi.
8. Runner PASS → Sol review exact `{base_commit, candidate_id}`.
9. Sol REJECT → AGY repair → Runner → Sol recheck; Astra count không đổi.
10. Sol APPROVE → Hermes revalidate base/tree/approval rồi commit đúng tree.
11. Sau verified commit, append `completed_commits`, advance `base_commit`, clear candidate refs; chỉ khi Hermes chọn task khác mới reset `current_task_attempts = 0`.
12. Hermes chọn ready task tiếp theo trực tiếp từ master plan.

Resume/replan không refill attempt budget. AGY local self-tests là diagnostic input; chỉ Runner evidence và Sol decision có acceptance authority.

## 6. Exceptional replanning triggers

Hermes chỉ được gọi Astra lại khi có một trong năm trigger sau và có `replan_reason_ref` trỏ tới verified evidence:

1. **Plan assumption disproved:** evidence chứng minh critical assumption trong master plan sai.
2. **Required gap uncovered:** global requirement bắt buộc được Runner/Sol phát hiện nhưng không có pending task nào có contract/scope phù hợp để xử lý.
3. **Architecture/dependency conflict:** remaining task không thể thực hiện mà không phá invariant hoặc verified committed work.
4. **Plan exhausted but objective incomplete:** mọi planned task đã committed nhưng còn global criterion FAIL/UNVERIFIED.
5. **User changes objective or authorized scope:** một strategic input mới hợp lệ.

Không phải trigger:

```text
test fail
AGY bug hoặc implementation technique yếu
Sol REJECT
candidate changed trong repair
ordinary commit
resume sau crash
stagnation hoặc exhausted repair budget khi plan vẫn đúng
non-blocking reviewer suggestion
```

Các trường hợp này do Hermes + AGY + Runner + Sol xử lý; không hội tụ thì BLOCKED. Replan không reset `current_task_attempts`, không xóa candidate/evidence và không thay đổi completed commits. Astra nhận exact reason/evidence và chỉ thay pending portion.

## 7. Minimal state machine

Persisted phases:

```text
PLANNING ──initial/replan only──► IMPLEMENTING
                                   │
                                   ▼
                               VERIFYING
                             FAIL │   │ PASS
                                  │   ▼
                                  └─ REVIEWING
                                     │      │
                                  REJECT  APPROVE
                                     │      ▼
                                     └─ IMPLEMENTING
                                            │
                                        COMMITTING
                                            │
                              atomic progress update
                                            │
                        ready task ──────────┼── all criteria PASS ─► COMPLETE
                                            │
                              plan-invalid evidence
                                            ▼
                                        PLANNING

Any phase ── non-convergence/unsafe ambiguity/external prerequisite ─► BLOCKED
```

`SELECT_TASK` và `UPDATE_PROGRESS` là deterministic actions, không phải persisted phases. Sau commit, Hermes thực hiện hai action này rồi đi thẳng tới `IMPLEMENTING` của task mới hoặc `COMPLETE`; không đi qua `PLANNING` trừ exceptional trigger.

## 8. Minimal persistence schema

Authoritative artifacts:

- `request.json`: immutable user objective và authorized scope.
- `plans/<content-sha256>.json`: immutable Astra master plan; ref chứa identity, không cần `master_plan_sha256` field thứ hai.
- `run_state.json`: một atomic execution snapshot.
- Diff/log/verification/review/attempt files: evidence được trỏ bằng refs, không phải workflow state thứ hai.

Minimal `run_state.json`:

```json
{
  "schema_version": 3,
  "run_id": "...",
  "phase": "IMPLEMENTING",
  "master_plan_ref": "plans/<sha256>.json",
  "current_task_id": "T2",
  "current_task_attempts": 2,
  "active_attempt_ref": null,
  "base_commit": "...",
  "candidate_id": null,
  "verification_ref": null,
  "review_ref": null,
  "pending_commit": null,
  "completed_commits": [
    {"task_id": "T1", "commit": "..."}
  ],
  "criterion_evidence": {
    "G1": {"status": "PASS", "ref": "..."}
  },
  "replan_reason_ref": null,
  "block_reason": null
}
```

Field challenge:

- Không lưu `task_statuses`: derive từ master plan, `current_task_id` và `completed_commits`.
- Không lưu `remaining_gaps`: derive từ `global_criteria` và `criterion_evidence`.
- Không lưu task scope/criteria/preservation trong state: master plan authoritative.
- Không lưu increment counter: derive từ `completed_commits`.
- Không duplicate `base_commit` trong `pending_commit`; pending value chỉ cần `{candidate_id}` vì top-level base chưa advance trước verified commit.
- `active_attempt_ref` là cần thiết: thiếu nó, crash có thể replay một writer hoặc hoàn budget sai.
- `replan_reason_ref` là cần thiết: thiếu nó, routine failure có thể bị ngụy trang thành strategic replan.

## 9. Ba milestone còn lại

### Milestone 1 — Freeze AGY safety boundary và current recovery candidate

Mục tiêu: đóng Step 7 trên candidate hiện có, không làm lại Steps 1–6.

| Task | Depends on | Objective | Editable scope | Acceptance |
|---|---|---|---|---|
| T1 | Steps 1–6 approved baseline | Hoàn thiện current Step 7 boundary/provenance candidate: F001/F002, no-Luna v1 route và test evidence; loại generated bytecode khỏi release diff | `lib/hermes_factory_v2.py`, `tests/test_factory_agy_builder.py`, `tests/test_factory_preflight.py`, `tests/test_factory_v2.py` | Public AGY path dùng non-Git mirror và Step-2 isolation; protected/source/Git/trusted writes denied; whole-candidate baseline checks phân biệt tracked/index/untracked/ignored; Runner/Sol repair không gọi Luna; focused/full relevant suites pass; `git diff --check`; Sol DELTA_ONLY recheck resolve F001/F002 và regression liên quan; exact candidate committed, worktree clean |

Implementation notes:

- Snapshot HEAD/tree/status/file hashes trước khi chạm dirty worktree; không reset code đang làm dở.
- Tracked `.pyc` là release noise, không product change; bỏ khỏi candidate sau khi xác minh đúng target, không dùng broad clean.
- Review chỉ target unresolved Step 7 findings và no-Luna regression; không re-audit Steps 1–6 nếu không có concrete regression.
- Nếu runtime executable identity khác approved identity, revalidate identity trước live gate; không sửa expected hash để “cho pass”.

Không thêm sandbox abstraction thứ hai, security platform, credential manager hoặc review milestone riêng.

### Milestone 2 — Astra-once master plan và Hermes routine execution

Mục tiêu: hoàn thiện core HoH loop để Hermes tự chạy toàn task graph mà không gọi Astra sau mỗi commit.

| Task | Depends on | Objective | Editable scope | Acceptance |
|---|---|---|---|---|
| T2 | T1 | Hoàn thiện master-plan contract/validation và cập nhật deterministic actor fixtures | `lib/hermes_factory_v2.py`, `tests/test_factory_v2.py`, focused master-plan tests | Astra trả một immutable whole-project plan; unique/acyclic task graph; scope/criteria coverage validation; old `Sol Planner` fixture/runtime path không còn active; invalid plan dispatches zero AGY calls |
| T3 | T2 | Hoàn thiện public `execute()` làm Hermes master-plan loop; normalize one task contract cho `_execute_task` | Same engine/test scope | T1→T2→T3 chạy theo dependency/order; normal commit chọn task kế tiếp mà Astra count không tăng; public execute/status hoạt động; không dùng old `sol_plan.json` path |
| T4 | T3 | Hoàn thiện unified AGY repair, exceptional replan, completion và routine resume semantics | Engine, state tests và execution integration tests | Runner FAIL/Sol REJECT quay AGY; stagnation/exhaustion → BLOCKED, Luna count 0; crash sau task commit resume vào next ready task; chỉ năm exceptional trigger gọi Astra; plan exhausted nhưng missing criterion không COMPLETE; normal N-task Astra count = 1 |

Implementation rules:

- `_execute_one_task()` hiện còn old-plan fields như `allowed_files`/`implementation_steps`; đổi thành một normalized task contract lấy từ master plan, không duy trì hai execution implementations.
- `resume()` bỏ logic “không có `sol_plan.json` thì replan”. Resume đọc current master plan ref và phase; routine resume không gọi Astra.
- Attempt count persist trước mọi initial/repair dispatch và chỉ reset sau verified commit + Hermes chọn distinct next task.
- `preservation_constraints` chỉ là task criteria cho AGY/Runner/Sol, không thành acceptance engine thứ hai.

Không thêm DynamicScheduler, PlanDatabase, task registry service, plan revision manager hoặc Luna dispatch.

### Milestone 3 — Exact candidate, durable commit/resume, cleanup và final acceptance

Mục tiêu: biến loop green thành production-safe release với exact verified commit và legacy surface tối thiểu.

| Task | Depends on | Objective | Editable scope | Acceptance |
|---|---|---|---|---|
| T5 | T4 | Chốt candidate identity và authority | `_stage`, Runner gates, `_review`, commit path và candidate tests | `candidate_id = git write-tree`; verification và Sol approval bind `{base_commit,candidate_id}`; stale approval/candidate/base bị reject; committed parent/tree đúng; Runner không commit, Hermes-only commit |
| T6 | T5 | Durable attempts, locks và crash reconciliation | State loader/save, execute/resume/commit reconciliation và crash tests | Reservation không refund; active/ambiguous writer fail closed; resume ở VERIFYING/REVIEWING/COMMITTING không mất progress hoặc duplicate commit; concurrent mutation bị lock; corrupted state BLOCKED; no dual journal required |
| T7 | T6 | Xóa active legacy, đồng bộ CLI/docs và chạy final product acceptance | `lib`, tests, CLI/launcher, `.gitignore`, `README.md`, `docs/software-factory-SKILL.md`, checksums; bridge/service chỉ sau consumer verification | Zero active Aider/bridge/Luna production route; old evidence inspectable nhưng incompatible runs không resume; full offline suite green; real subprocess/sandbox fixtures green; authorized live feature, repair, review-reject và multi-task scenarios green; final all-changes Sol approval binds exact release tree; deployment chỉ sau explicit authorization |

Milestone 3 không tạo milestone review/deployment riêng. Review là gate của từng task; final integrated review là acceptance của T7.

## 10. Repair/review policy

- Runner FAIL: AGY nhận exact failing command/check, normalized failure signature và relevant output; sửa cùng task/scope; Runner chạy lại.
- Sol REJECT: AGY nhận required changes + prior review artifact; Runner chạy lại toàn affected verification; Sol delta recheck exact candidate.
- `validate_review()` v1 chỉ cho `route in {"none", "builder"}`. Không production branch invoke Luna.
- Stagnation: hai repair liên tiếp có `candidate_id unchanged && failure_signature unchanged` → BLOCKED. Không đoán bằng prose.
- Exhausted task budget khi plan vẫn đúng → BLOCKED, không Astra.
- Initial review xem observable output/current task criteria. Delta review chỉ xem unresolved findings, repair delta và affected regressions; không tự reopen PASS requirement nếu không có regression evidence.
- Any edit/base change sau approval invalidates approval.
- Safety blocker có invariant rõ, trong authorized task/scope và không cần quyền mới được Hermes auto-route sang AGY repair. External provisioning, credential/account choice, deployment hoặc scope expansion mới cần user.

## 11. COMPLETE và BLOCKED policy

Hermes chỉ set `COMPLETE` khi đồng thời:

```text
all required master-plan tasks committed
AND every global criterion has current verified PASS evidence
AND no unresolved blocking Runner/Sol finding
AND no pending/ambiguous candidate or commit
```

Nếu hết task nhưng còn criterion FAIL/UNVERIFIED: exceptional replan trigger D, không COMPLETE.

Nếu task không hội tụ nhưng master plan vẫn hợp lệ: BLOCKED với task ID, attempts used, candidate/base identity, failure signature, logs/evidence refs và Luna invocation count 0.

BLOCKED không tự refill budget hoặc tự replan. Resume chỉ tiếp tục khi blocking condition được giải quyết hoặc user cấp authority/config change hợp lệ.

## 12. Acceptance scenarios

| Scenario | Expected behavior |
|---|---|
| 1. Normal multi-task | Astra một lần; Hermes chọn T1→T2→T3; mỗi task Runner→Sol→commit; COMPLETE |
| 2. Runner failure | AGY repair→Runner PASS→Sol APPROVE→commit; Astra count không đổi |
| 3. Sol reject | AGY repair→Runner→Sol recheck→commit; Astra count không đổi |
| 4. Resume | Crash sau T1 commit; resume reconcile commit và chọn next ready task; không Astra |
| 5. True plan failure | Verified critical assumption disproved; `replan_reason_ref` persisted; Astra sửa pending plan, giữ commits/evidence |
| 6. Missing global requirement | Planned tasks hết nhưng criterion thiếu; no false COMPLETE; exceptional Astra replan |
| 7. Implementation exhaustion | AGY hết attempts/stagnant; BLOCKED; Astra count không đổi; Luna count 0 |
| 8. Quota property | Với N tasks không invalidation: `astra_invocation_count == 1` |
| 9. Exact candidate | Sol approve tree A; bất kỳ base/tree/index mutation nào trước commit đều reject; commit tree phải bằng A |
| 10. Crash during commit | Nếu commit đúng parent/tree đã tồn tại thì finalize state, không commit lại; không xác định được thì BLOCKED |

## 13. Migration từ plan/implementation hiện tại

1. Giữ nguyên commits và evidence Steps 1–6; không quay lại fixed 14-step chain.
2. Xem toàn bộ dirty worktree hiện tại là unapproved recovery candidate, không phải baseline mới.
3. Thực hiện T1 trước: snapshot, hoàn thiện F001/F002 + no-Luna evidence, chạy gates, Sol delta review, commit và làm sạch worktree.
4. Giữ các pure primitives đã đúng: `validate_master_plan`, task flattening/ready selection, `failure_signature`, `is_stagnant`; sửa contract hoặc tests chỉ khi evidence chỉ ra mismatch.
5. Hoàn thiện `execute()` và master-plan loop trước mọi feature khác; đây là blocker khiến full engine suite hiện fail.
6. Migrate tests từ `Sol Planner`/`sol_plan.json` sang one-shot `Astra Planner`/immutable master plan; không xóa behavioral assertions chỉ để suite green.
7. Sau Milestone 2 green, chốt tree OID/commit/recovery ở Milestone 3; không trộn legacy cleanup vào core loop trước khi behavior ổn định.
8. Mỗi task là một reviewed candidate/commit. Sol REJECT loop đến APPROVE hoặc task BLOCKED; normal commit không gọi Astra.
9. Sau T7, chạy final all-changes Sol review trên exact release tree. Merge/push/deploy không tự động và cần authority riêng.

## 14. DELETE / KEEP / MODIFY / DEFER

| Decision | Items |
|---|---|
| KEEP | Steps 1–6 approvals/evidence; Step-2 isolation contract; Step-6 supervision; AGY protocol parser/failure codes; non-Git mirror; source/Git/trusted guards; Runner/Sol independence; historical artifact inspection |
| KEEP after focused revalidation | Step 7 F003–F006 resolved behavior; current F001/F002 repair candidate; no-Luna correction; `validate_master_plan`, `next_ready_master_task`, `failure_signature`, `is_stagnant` |
| MODIFY | Rolling plan → initial master plan; `_perform_planning` → initial/exception-only; `_execute_one_task` → normalized task executor; add public Hermes loop; `resume`; state schema; candidate identity; Sol approval/commit binding; stale tests/fakes |
| DELETE now | Per-commit Astra call; active Luna preflight/route/repair; `sol_plan.json` as current runtime authority; duplicated task definitions/status/gaps in state; diff SHA as primary candidate identity |
| DELETE in T7 | Active Aider/bridge/API-key fallback and stale operational docs after AGY path passes acceptance; tracked generated bytecode from release candidate |
| DEFER | Luna v1.1; JSONL/event sourcing; distributed locks; parallel scheduler; provider framework; dashboard; generalized security platform; roadmap/finding registries |

## 15. Remaining risks and resolved ambiguities

- **Dirty recovery candidate:** must be snapshotted and reviewed before becoming baseline. Resolution: T1 first, no broad reset.
- **AGY executable identity drift:** current observed binary may differ from approved identity. Resolution: pin/revalidate exact runtime; do not silently update expected hash.
- **Full engine suite red:** current fixtures expect `Sol Planner`, and public execute loop is incomplete. Resolution: T2/T3; do not label as Luna regression.
- **Task identity across replan:** attempts could reset if Astra invents new ID. Resolution: active task ID remains stable across replan; ambiguous replacement BLOCKED.
- **Arbitrary verification commands:** plan text must not become shell authority. Resolution: Runner validates command policy before execution.
- **Completion evidence freshness:** a prior PASS can become stale after affected code changes. Resolution: Runner reruns affected regression set and updates criterion ref; no second acceptance engine.
- **OAuth/Sandbox operational dependency:** use the existing boundary contract. New credential/account/provisioning choice pauses for user; routine authenticated dispatch does not.
- **Legacy removal timing:** deleting Aider/bridge too early can obscure regression cause. Resolution: remove only in T7 after the new loop and exact commit gate are green.

## Anti-overengineering check

| Mechanism kept | Without it, concrete failure | Guarantee harmed |
|---|---|---|
| Immutable `master_plan_ref` | Resume could execute a silently changed strategy | Strategic-plan fidelity, interruption recovery |
| `active_attempt_ref` + reserve-before-dispatch | Crash could replay a writer or refund an attempt | Source safety, interruption recovery |
| `criterion_evidence` | All tasks could finish while objective remains unverified | Code quality, independent verification |
| `{base_commit,candidate_id}` tree binding | Sol could approve one tree and Hermes commit another/base khác | Exact verified-commit correctness |
| Exceptional `replan_reason_ref` | Routine test failure could trigger expensive strategy churn | Autonomous convergence, strategic-plan fidelity |
| One no-Luna repair loop | Multiple repair paths could bypass identical guards/budgets | Source safety, autonomous convergence |

Không tạo mechanism nào khác nếu không chỉ ra được một scenario và guarantee tương ứng.

## Final self-check

### Q1 — Normal project 10 tasks, không planning surprise, Astra gọi bao nhiêu lần?

```text
1
```

### Q2 — Ai quyết định task thứ 7 sau khi task thứ 6 commit?

```text
Hermes, từ immutable master plan + dependencies + completed_commits/current state.
```

### Q3 — Khi nào Astra quay lại?

```text
Chỉ khi verified evidence chứng minh master plan sai, thiếu hoặc không còn thực thi được,
hoặc user thay đổi objective/authorized scope.
```
