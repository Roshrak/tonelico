# SoftFac v2: Aider → Antigravity CLI migration plan

The migration should replace the Builder execution boundary—not the factory’s planning, testing, review, memory, or commit authority.

A simple class rename and command substitution is insufficient: `agy --dangerously-skip-permissions` can execute commands as well as edit files. The cutover must therefore prove process containment, completion detection, scope enforcement, and crash safety before making `AgyBuilder` the production default.

This is an implementation plan only. No source files, installed skills, credentials, or services were changed.

## 1. Verified baseline and architectural decisions

### Current evidence

| Item | Verified state |
|---|---|
| Main HOH checkout | `C:\Users\HH18\Downloads\hermes-software-factory-v2-hoh\hermes-software-factory-v2` |
| Main commit | `066e885966420b14d470dc159f0ff39acf2099a9` |
| Main regression suite | **29 tests passed**, rerun during this inspection |
| Audit checkout | `C:\Users\HH18\softfac-audit-worktree`; contains staged, unstaged, and untracked work |
| Audit regression suite | **58 tests run: 57 passed, 1 opt-in test skipped** |
| Installed CLI | `C:\Users\HH18\AppData\Local\agy\bin\agy.exe`, version **1.2.0** |
| Model catalog | Includes **`gemini-3.8-flash-high`** |
| Actual ledger files | `ledger/issue_ledger.json` and `ledger/trajectory.json`, currently JSON snapshots—not JSONL |
| Existing obsolete arguments | `--bridge-url` and hidden `--builder-architect-model`; inspected main does **not** currently expose `--aider-bin` |

The [main implementation](C:/Users/HH18/Downloads/hermes-software-factory-v2-hoh/hermes-software-factory-v2/lib/hermes_factory_v2.py:918) and [audit implementation](C:/Users/HH18/softfac-audit-worktree/lib/hermes_factory_v2.py:1191) are not interchangeable baselines. The audit checkout has additional slice, budget, and locking behavior; passing tests do not establish that every installed-skill invariant is already implemented correctly.

### Decisions governing the plan

1. **Default target:** the clean main HOH checkout above, implemented in a new migration worktree. Reuse audit changes only through individually reviewed patches.
2. **Builder:** direct `agy` subprocess; no Aider compatibility backend and no Builder HTTP bridge.
3. **Model:** exact slug `gemini-3.8-flash-high`; no `openai/` prefix and no silent model fallback.
4. **Responsibilities:** Astra plans; AGY implements; Luna diagnoses; Sol independently reviews; the runner owns tests, evidence, staging, rollback, and commits.
5. **Determinism:** reproducible inputs, configuration, transitions, evidence, and gate decisions—not guaranteed identical model-generated patches.
6. **Historical compatibility:** preserve old evidence and `--prior-run`; never silently resume a partially executed old-Builder candidate under AGY.
7. **JSONL:** deliver the requested journals as a separately audited persistence change, retaining existing JSON snapshot compatibility.
8. **Release condition:** unavailable or unproven safety capability means `blocked`, not a reduced-safety fallback.

Google documents structured headless output, including a terminal result and stream initialization metadata. Use those machine-readable surfaces instead of interpreting conversational success text. Their behavior still needs fixtures from the installed 1.2.0 executable. [Official headless documentation](https://antigravity.google/docs/cli/headless/)

## 2. Invariants and ownership

Treat the following as the migration’s acceptance contract.

| Invariant | Enforcement owner | Required proof |
|---|---|---|
| Approved plan and bounded steps | `validate_plan` / runner | Invalid plans cause zero Builder dispatches |
| Candidate isolation | Runner and execution boundary | Builder cannot modify source checkout or trusted run state |
| `allowed_files` | Path validation and scope gates | Out-of-scope changes cannot reach tests/review/commit |
| Per-slice scope | Dispatcher | Slice N cannot edit another slice’s files |
| Fresh Builder context | `AgyBuilder` | Separate invocation and conversation per call |
| No Builder Git authority | Execution boundary and Git guards | Builder cannot stage, commit, reset, merge, or alter refs |
| Durable budgets | Locked run-state persistence | Crash/resume never replenishes consumed budget |
| HOH memory | `MemoryLedger` | Stable issue identity, lifecycle, sequence, and provenance |
| Independent Sol review | Existing review path | Fresh review receives exact candidate evidence, not Builder conversation |
| Deterministic pre-review checks | `_pre_review_gate` | Invalid candidates never invoke Sol |
| Hash-checked commit | Runner | Approved diff, staged tree, and committed tree agree |
| Safe rollback | `_safe_rollback` | Exact authorized checkpoint restored; source untouched |
| Fail-closed resume | State loader and execution entry points | Ambiguous/partial Builder execution cannot restart implicitly |

“GOAP gates” here means the existing action preconditions and state transitions. Do not introduce a new GOAP search engine or rename the factory’s phases as part of this migration.

The required action ordering remains:

```text
Preflight → Validated plan → Isolated candidate → Sequential Builder slices
    → Scope/integrity checks → Tests
        → Luna repair → Builder → Checks → Tests, when needed
    → Deterministic pre-review gate → Fresh Sol review
        → Rework → Checks → Tests → Fresh review, when rejected
    → Revalidate approved candidate → Task-branch commit
```

## 3. Execution and approval protocol

The steps below are sequential release increments, not one oversized factory plan. Where the factory limits a plan to eight implementation steps, submit each increment separately; retain stricter request-specific limits.

For **every step**, Hermes must give Sol High:

- Base commit and current file hashes.
- Exact allowed paths.
- Complete diff, including all pages and new files.
- Exact verification commands, exit codes, and test counts.
- Invariant-to-test mapping.
- Known limitations, skipped checks, and release blockers.
- Candidate diff SHA-256 and explicit `APPROVE` or `REJECT`.

Any edit after approval invalidates that approval.

For eligible implementation increments, follow `agy-control-worker`: automatic isolated delegation, complete report/diff inspection, and **no `agy_apply` without explicit user approval**. Do not let the partially migrated factory approve or deploy itself.

---

## Step 1 — Freeze the baseline and inventory the removal surface

**Goal and scope**

Establish exactly what is being migrated, preserving all existing work and evidence.

**Files**

Create:

- `docs/agy-migration-plan.md`
- `docs/agy-migration-baseline.md`

Inspect all tracked runtime, tests, launchers, dependency files, service examples, and documentation.

**Concrete changes**

1. Create a dedicated migration branch/worktree from the approved main commit.
2. Record:
   - HEAD and worktree status.
   - Python/Git versions.
   - Tracked-file hashes.
   - Main and audit regression results separately.
3. Inventory:
   ```text
   AiderBuilder
   clean_aider_generated_artifacts
   DEFAULT_AIDER_MODEL
   DEFAULT_AIDER_URL
   DEFAULT_BUILDER_ARCHITECT_MODEL
   DEFAULT_BRIDGE_URL
   aider_bin
   bridge_url
   builder_architect_model
   urllib
   LiteLLM
   model metadata/settings
   generated histories/caches
   ```
4. Include `.gitignore`, `SHA256SUMS`, `bridge/agy_bridge.py`, and `systemd/agy-bridge.service.example`.
5. Identify installed launcher/module locations before planning deployment; do not assume editing the repository updates the running installation.
6. Record which audit-worktree protections need to be ported. Do not copy its entire dirty file.

**Verification**

```powershell
git -C "<migration-worktree>" status --short
python -B tests/test_factory_v2.py
git -C "<migration-worktree>" grep -n -i -E "aider|litellm|bridge_url|builder_architect|model-metadata-file|model-settings-file"
```

The baseline must retain all 29 main test outcomes and record the 58-test audit suite separately.

**Pitfalls and mitigation**

- **Wrong checkout:** record absolute paths in every audit packet.
- **Uncommitted audit changes lost:** prohibit resets, blanket checkout restoration, or automatic merging.
- **Sensitive legacy defaults:** record their existence without reproducing credentials; remove Builder credential fallbacks later. Credential rotation is a separate authorized operation.

---

## Step 2 — Specify the AGY runtime and isolation contract

**Goal and scope**

Resolve safety capabilities before relying on permission-skipping execution.

**Files**

Create:

- `docs/agy-builder-contract.md`
- Sanitized fixtures under `tests/fixtures/agy/1.2.0/`

No production backend switch yet.

**Concrete specifications**

Record and verify:

- Executable resolution and version format.
- Required flags.
- Exact model selection.
- Fresh-conversation behavior.
- Effective working directory.
- Configuration, rules, hooks, plugins, MCP, and credential discovery.
- Terminal completion/error schema.
- Timeout and descendant-process behavior.
- Files created outside the candidate.

Define two separate boundaries:

1. **Execution isolation:** prevent writes to the source checkout, shared Git metadata, trusted state, approvals, and unrelated host files.
2. **Candidate acceptance scope:** reject any candidate changes outside `allowed_files` and the current slice boundary.

A prompt and `cwd=worktree` enforce neither boundary by themselves.

The required `--dangerously-skip-permissions` flag approves tool operations; it must not be represented as a safety feature. [Official permissions documentation](https://antigravity.google/docs/cli/headless/#permissions-in-headless-mode)

Select an audited external execution boundary where necessary. Its policy must cover native file tools and descendants, not only terminal commands. The current sandbox documentation describes Linux/macOS mechanisms; it is not evidence of equivalent Windows coverage. [Official sandbox documentation](https://antigravity.google/docs/cli/sandbox/)

**Verification**

Use disposable fixtures to attempt:

- An allowed file edit.
- An out-of-scope candidate edit.
- A source-checkout write.
- A write to `run_state.json` and review artifacts.
- Git ref/index modification.
- A delayed child write after cancellation.

Only the authorized edit may succeed within the enforced boundary.

**Pitfalls and mitigation**

- **Windows isolation requires provisioning:** stop for explicit authorization to provision it. Do not silently run unrestricted.
- **Shared `.git` access:** linked worktrees share repository metadata; making only the source directory read-only is insufficient.
- **Prompt compliance mistaken for enforcement:** malicious fixture processes must exercise the same launch boundary as AGY.
- **Impossible required capability:** retain a release blocker rather than weaken “100% preservation.”

---

## Step 3 — Characterize the invariants before replacing the Builder

**Goal and scope**

Turn current safety expectations into regression tests.

**Files**

Modify:

- `tests/test_factory_v2.py`

Create focused test modules if needed:

- `tests/test_factory_builder_contract.py`
- `tests/test_factory_resume_contract.py`

**Concrete changes**

Preserve existing tests for:

- Safe/tool-less role invocation.
- Committed-HEAD planning and dirty-checkout preservation.
- Symlink rejection.
- Scope violations.
- Luna repair routing.
- Sol rejection and fresh re-review.
- Wrong approval hash.
- Rollback.
- Issue lifecycle and prior-run disclosure.

Add missing characterization tests for:

- Empty candidate diff.
- Zero tests discovered.
- Builder changes index or HEAD.
- Builder writes partial files and then raises.
- Builder writes outside scope and raises simultaneously.
- Resume after ambiguous dispatch.
- Budget reservation before dispatch.
- Trusted ledger/review artifact tampering.
- Out-of-scope ignored files.
- Multiple slices with different editable-file sets.

Port audit-worktree tests selectively; do not equate test presence with sufficient assertion strength.

**Verification**

Run the existing suite plus the new targeted suite. Record pre-existing failures separately. A newly exposed invariant gap must become an explicit prerequisite fix, not an `xfail` hidden inside migration acceptance.

**Pitfalls and mitigation**

- **Broad mocks skip orchestration:** retain fake roles/builders for engine tests, but introduce real subprocess fixtures later.
- **Test-count preservation instead of behavior preservation:** map every removed Builder-specific test to its AGY replacement.

---

## Step 4 — Introduce AGY configuration and historical-state compatibility

**Goal and scope**

Make AGY a first-class, persisted Builder configuration without breaking historical inspection.

**Files**

Modify:

- `lib/hermes_factory_v2.py`
- Configuration/CLI/state tests.

**Concrete changes**

Target configuration:

```python
DEFAULT_BUILDER_MODEL = "gemini-3.8-flash-high"

@dataclass
class Config:
    # Existing non-Builder fields remain unchanged.
    ...
    builder_model: str = DEFAULT_BUILDER_MODEL
    agy_bin: str | None = None
```

Remove from active configuration and CLI:

- `DEFAULT_AIDER_MODEL`
- `DEFAULT_AIDER_URL`
- `DEFAULT_BUILDER_ARCHITECT_MODEL`
- Builder-only `DEFAULT_BRIDGE_URL`
- `bridge_url`
- `builder_architect_model`
- `--bridge-url`
- `--builder-architect-model`
- `--aider-bin`, wherever another supported baseline exposes it.

Add in `add_common` and `config_from_args`:

```python
parser.add_argument("--agy-bin", default=None)
parser.add_argument("--builder-model", default=DEFAULT_BUILDER_MODEL)
```

Preserve integer/budget validation; do not replace strict validation with silent coercion.

Introduce a run-configuration version separate from ledger versions:

```python
RUN_CONFIG_VERSION = 2

def load_config_for_execution(state: dict[str, Any]) -> Config: ...
def read_run_state(run_dir: Path) -> dict[str, Any]: ...
```

New runs record:

```json
{
  "run_config_version": 2,
  "builder_backend": "agy",
  "builder_contract_version": 1
}
```

Change `status()` to read historical state without constructing today’s `Config` or resolving AGY.

Old runs:

- Remain inspectable.
- Remain eligible as validated prior-run evidence.
- Cannot execute/resume under the new backend without a new run and fresh plan.
- Unknown schemas and unknown active configuration keys fail closed.

**Verification**

Test CLI defaults, explicit executable paths, serialization round trips, removed-argument rejection, old-run status, old-run execution rejection, and historical prior-run loading.

**Pitfalls and mitigation**

- **`Config(**old_state["config"])` crashes:** separate raw inspection from executable configuration.
- **Global schema bump breaks HOH history:** version configuration independently.
- **Silent prefix conversion:** reject obsolete `openai/...` Builder model values instead of silently rewriting them during execution.

---

## Step 5 — Implement executable resolution and capability preflight

**Goal and scope**

Prove that the selected executable can satisfy the audited Builder contract before candidate creation.

**Files**

Modify:

- `lib/hermes_factory_v2.py`
- Builder preflight tests.

**Concrete changes**

Add:

```python
def resolve_agy_executable(explicit: str | None) -> Path: ...

class AgyBuilder:
    def __init__(self, agy_bin: str | None = None) -> None: ...

    def preflight(
        self, config: Config, run_dir: Path
    ) -> dict[str, Any]: ...
```

Resolution order:

1. Explicit `--agy-bin`.
2. `shutil.which("agy")`.
3. On Windows, `%LOCALAPPDATA%/agy/bin/agy.exe`.

On this machine, the fallback resolves to the requested `C:/Users/HH18/AppData/Local/agy/bin/agy.exe`.

Rules:

- An invalid explicit path is an error; do not fall back.
- Resolve once to an absolute executable path.
- Reject directories and unsupported shell shims.
- Never launch `.cmd`/`.bat` through an improvised shell string.
- Pin the executable identity through the run.

For observed bare semantic-version output, use `re.fullmatch`, for example:

```python
r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
```

Do not accept arbitrary banners containing a version substring. Version 1.2.0 becomes supported only after Step 2’s contract audit.

Preflight order:

1. Resolve executable.
2. Check `--version` and binary hash.
3. Check required capabilities.
4. Check exact model catalog entry.
5. Run a bounded no-edit capability probe in a disposable confined directory.
6. Verify completion and effective model/cwd evidence.
7. Persist sanitized `preflight_builder.json`.

No HTTP requests to a Builder bridge, no API-key fallback, and no automatic installation/login/update.

**Verification**

Missing binary, invalid explicit path, unsupported version, missing model, malformed catalog, unauthenticated runtime, failed probe, and wrong effective model must all block before candidate creation.

**Pitfalls and mitigation**

- **`--version` mistaken for authentication proof:** require the separate capability probe.
- **Model self-report mistaken for routing evidence:** inspect CLI metadata, not generated prose.
- **PATH changes between calls:** recheck the pinned binary identity before dispatch.

---

## Step 6 — Implement the bounded AGY subprocess runtime

**Goal and scope**

Launch AGY safely, preserve diagnostic evidence, and stop all writers before downstream gates.

**Files**

Modify:

- `lib/hermes_factory_v2.py`

Create:

- `tests/test_factory_builder_process.py`
- `tests/fixtures/builder_process_fixture.py`

**Concrete changes**

Use a dedicated Builder process helper rather than changing every role/test invocation:

```python
def run_builder_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    stdout_path: Path,
    stderr_path: Path,
) -> subprocess.CompletedProcess[str]: ...
```

The approved invocation retains the requested core command:

```text
agy --model gemini-3.8-flash-high
    --dangerously-skip-permissions
    --output-format stream-json
    --disable-slash-commands
    --print-timeout <bounded-duration>
    --print <instruction>
```

Additional flags must be verified by Step 2; place all options before the final prompt argument.

Runtime requirements:

- Argument list; `shell=False`.
- Exact resolved candidate `cwd`.
- No `--continue`, `--conversation`, inherited project override, or extra workspace directories.
- Non-interactive stdin.
- Concurrently drain stdout/stderr with bounded storage.
- Explicit UTF-8 handling; retain undecodable raw evidence and fail closed.
- Separate CLI timeout from the outer watchdog, leaving a bounded shutdown margin.
- Windows process ownership through a Job Object or equivalent audited boundary; prevent escape before process execution.
- On other supported platforms, use an audited process-group/container lifecycle.
- Await writer termination before tests, snapshots, rollback, or review.
- Preserve partial logs on timeout, cancellation, spawn error, or output overflow.
- Do not print full prompt-bearing argv in errors.

Reject NUL-containing or oversized prompts before spawning. On Windows, measure the serialized command line in UTF-16 code units with conservative headroom. Do not silently truncate or change input protocols.

**Verification**

Real fixture subprocess tests must cover Unicode paths, spaces, quotes, shell metacharacters, huge stderr, malformed UTF-8, timeout, cancellation, delayed child writes, and output exhaustion.

**Pitfalls and mitigation**

- **Killing only the parent leaves a writer:** process-tree termination is a release gate.
- **Output deadlock:** drain both pipes concurrently.
- **Isolation breaks authentication:** use the approved AGY identity/configuration route; do not blindly copy Aider’s child-home manipulation.
- **Orphaned external daemon:** track or prohibit external writer services; process groups alone are not proof.

---

## Step 7 — Implement `AgyBuilder.run` and fail-closed result validation

**Goal and scope**

Replace Aider’s editing invocation while preserving the injected Builder interface.

**Files**

Modify:

- `lib/hermes_factory_v2.py`
- Builder contract tests and AGY fixtures.

**Concrete changes**

Preserve the existing engine-facing signature:

```python
def run(
    self,
    *,
    worktree: Path,
    instruction: str,
    allowed_files: list[str],
    config: Config,
    run_dir: Path,
    label: str,
) -> None: ...
```

Add:

```python
def parse_agy_event_stream(raw: bytes) -> dict[str, Any]: ...
```

Before dispatch:

1. Validate label, canonical worktree, and file boundary.
2. Revalidate executable/configuration identity.
3. Create unique attempt artifacts outside the candidate.
4. Bind instruction hash, allowed paths, model, executable, and candidate baseline.

Recommended label validation:

```python
r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}"
```

The parser must require the audited stream structure:

- Exactly one initialization event.
- Matching canonical cwd and configured model.
- One fresh conversation for this invocation.
- Exactly one terminal result.
- Process exit zero and terminal `SUCCESS`.
- No contradictory error or unsupported terminal state.
- No missing, truncated, duplicated, or malformed terminal evidence.

Treat the stream as an untrusted protocol: bound record sizes, validate types, and reject duplicate keys in security-relevant objects.

Add structured errors:

```python
class BuilderFailure(FactoryError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        non_resumable: bool,
        evidence_path: str | None = None,
    ) -> None: ...
```

Stable codes should include:

```text
agy_spawn_failed
agy_timeout
agy_canceled
agy_protocol_error
agy_runtime_error
agy_model_mismatch
agy_identity_changed
agy_output_incomplete
agy_isolation_failed
```

The CLI’s `SUCCESS` means completion, not a valid implementation. Changed-file, test, and review gates remain authoritative.

**Verification**

Test all audited non-success statuses, zero exit with an error result, wrong model/cwd, stale conversation reuse, missing final result, duplicate result, partial file edits followed by failure, and ordinary response text containing words such as “error” or “token limit.”

**Pitfalls and mitigation**

- **Porting Aider marker regexes:** remove them; classify AGY using its own verified protocol.
- **Demanding nonexistent `structured_output`:** require it only if the invocation actually uses an audited `--json-schema`.
- **Inventing upstream quota causes:** record unknown causes as unknown.
- **Success with no patch:** block at the candidate gate, not by trusting a “done” sentence.

---

## Step 8 — Centralize every Builder dispatch and preserve slices

**Goal and scope**

Ensure initial build, Luna repair, and reviewer rework all use identical safety handling.

**Files**

Modify:

- `FactoryEngine`
- `_builder_instruction`
- `_builder_slice_instruction`, if ported
- `_luna_repair`
- Execution-loop tests.

**Concrete changes**

Introduce:

```python
def _dispatch_builder(
    self,
    *,
    run_dir: Path,
    state: dict[str, Any],
    config: Config,
    worktree: Path,
    instruction: str,
    editable_files: list[str],
    label: str,
    ledger: MemoryLedger,
) -> None: ...
```

This method must:

1. Validate a nonempty subset of plan `allowed_files`.
2. Persist the attempt reservation and increment `builder_calls_used`.
3. Persist the slice/attempt manifest before dispatch.
4. Snapshot the candidate and trusted boundary.
5. Invoke the Builder.
6. Run integrity and scope checks even when the Builder raises.
7. Persist all failures without masking one with another.
8. Mark completion only after all postconditions pass.

Route through this method:

- Initial slices.
- Test-failure repairs.
- Direct Sol-requested rework.
- Sol → Luna rework.
- Test failures following reviewer rework.

Use structured step targets:

```json
{
  "step": "Implement the validated decoder change",
  "editable_files": ["src/decoder.py"]
}
```

Reject empty, ambiguous, or out-of-bound targets. Do not infer scope from ambiguous basenames or fall back to the entire plan boundary.

Prompts must include only the current objective, step, editable files, relevant constraints, and completion instruction. Explicitly prohibit Git operations, dependency installation, unrelated edits, and treating Builder-run tests as factory evidence.

**Verification**

Tests must prove slice ordering, manifest-before-dispatch, prompt isolation, distinct conversations, durable call counts, immediate stopping on slice failure, and equivalent guards for every repair route.

**Pitfalls and mitigation**

- **Cumulative diff rejects earlier slices:** compare each invocation’s before/after changes to its slice scope; compare the cumulative candidate to plan scope.
- **Audit code contains broad fallback behavior:** port intended invariants, not its current fallback implementation.
- **Repair path bypasses checks:** assert every Builder call passes through `_dispatch_builder`.

---

## Step 9 — Harden scope, Git authority, and candidate identity

**Goal and scope**

Prevent AGY’s broader tool capabilities from bypassing the existing candidate gates.

**Files**

Modify:

- `normalize_path`
- `ensure_paths_confined`
- `_changed_files`
- `_scope_check`
- `_assert_source_unchanged`
- `_stage`
- Candidate-integrity tests.

**Concrete changes**

1. Use NUL-delimited Git path output rather than `splitlines()` for filenames.
2. Reject path traversal, absolute paths, drive/UNC escapes, unsafe symlinks/junctions, and unsupported file types.
3. Handle Windows case-insensitive path collisions explicitly.
4. Snapshot candidate HEAD, index, tracked files, untracked files, and relevant ignored files.
5. Protect linked-worktree Git metadata, refs, configuration, and hooks.
6. Require candidate HEAD/index to remain unchanged during Builder execution; staging belongs to the runner.
7. Remove `clean_aider_generated_artifacts` and both call sites.
8. Do not add `clean_agy_generated_artifacts` or ignore `.agy*` broadly.
9. Keep runtime logs and CLI state outside the candidate.
10. Use a separately declared policy for test-generated artifacts; the Builder must not gain those write permissions implicitly.

For source protection, preserve existing legitimate dirty-checkout behavior. Do not expand a preservation check into a blanket requirement to erase unrelated user edits.

**Verification**

Exercise rename/delete/new-file/binary changes; Unicode and newline filenames; ignored-file edits; symlink/junction escapes; index staging; commits; ref changes; `.gitignore` modification; and out-of-scope writes followed by failure.

**Pitfalls and mitigation**

- **Post-run checks cannot undo external damage:** execution isolation from Step 2 remains mandatory.
- **Ignoring generated files hides malicious changes:** enumerate runtime scratch paths explicitly.
- **Source status text is not content integrity:** use content hashes where state equality matters.
- **Hook execution mutates the reviewed tree:** control hooks in runner Git operations without editing user Git configuration.

---

## Step 10 — Make resume, budgets, and rollback provider-neutral

**Goal and scope**

Remove dependence on Aider artifacts while preserving crash and rollback guarantees.

**Files**

Modify:

- `_load` / executable-state loading.
- `execute`, `resume`, and locked variants.
- `_create_checkpoint`
- `_safe_rollback`
- Budget/fingerprint logic.
- Crash-recovery tests.

**Concrete changes**

1. Use OS-backed single-writer locking for state-mutating entry points.
2. Enforce `non_resumable` in **both** `execute` and `resume` before capability calls.
3. Replace checks for `*.token_limit.json` with authoritative state.
4. Persist attempt states:

   ```text
   reserved → dispatched → completed
                        ↘ failed / ambiguous
   ```

5. A crash after reservation does not refund the attempt.
6. An incomplete dispatch record blocks automatic replay.
7. Preserve `debug_attempts_used`, `review_cycles_used`, and `builder_calls_used` monotonically.
8. Resume verifies plan hash, candidate identity, model, executable, and configuration contract.
9. Preserve failed candidates and logs; do not delete them merely because resume was requested.
10. Rollback operates only inside the validated candidate, after all writers stop.
11. Include tracked, untracked, staged, unstaged, and binary state in checkpoint/no-progress fingerprints using canonical length-delimited records.

**Verification**

Inject crashes before/after reservation, process spawn, result persistence, budget update, checkpoint creation, and rollback.

Test concurrent execute/resume, deleted failure artifacts, modified plans, exhausted budgets, and rollback after staged/untracked changes.

**Pitfalls and mitigation**

- **Automatic candidate deletion destroys evidence:** quarantine first; cleanup is separate.
- **State corruption resets counters:** reject invalid/missing required execution fields instead of defaulting them to zero.
- **Rollback races a writer:** require proven writer quiescence.
- **Old-run resume silently changes backend:** reject and instruct creation of a new run with `--prior-run`.

---

## Step 11 — Preserve HOH memory and add the requested JSONL journals

**Goal and scope**

Preserve issue/trajectory semantics while delivering JSONL without breaking existing consumers.

**Files**

Modify:

- `MemoryLedger`
- `load_prior_run_context`
- Ledger consistency/recovery tests.

Create:

- `docs/ledger-compatibility.md`

**Concrete changes**

Retain:

```text
ledger/issue_ledger.json
ledger/trajectory.json
```

Add for new runs:

```text
ledger/issue_ledger.jsonl
ledger/trajectory.jsonl
```

Define the relationship explicitly:

- `trajectory.jsonl` contains the canonical sequenced transaction record, including issue deltas.
- `issue_ledger.jsonl` is an idempotent issue-event projection.
- Existing `.json` files remain versioned materialized snapshots.

Every transaction includes:

```text
schema_version, run_id, transaction_id, seq,
event_type, issue_id when applicable,
payload, previous_hash, record_hash
```

Under the single-writer lock:

1. Append and flush the canonical record.
2. Append the corresponding issue projection, when applicable.
3. Atomically replace snapshots.
4. Record the completed generation.

Recovery replays valid canonical records and deduplicates projection transaction IDs. Preserve torn/corrupt evidence; never replace it with an empty ledger.

Preserve issue IDs, fingerprints, root objective classification, lifecycle rules, evidence references, and progressive-disclosure limits. Add backend/model/attempt metadata without renaming historical issue sources.

Legacy snapshot-only runs stay readable without rewriting them. Corrupt legacy data blocks with evidence.

**Verification**

Test legacy snapshots, new journals, issue deduplication, reopening/regression, no premature resolution, prior-run bounds, interleaved crash points, duplicate transaction recovery, torn tails, and corrupt records.

**Pitfalls and mitigation**

- **Two independent authoritative journals diverge:** use one canonical transaction history.
- **Global version change invalidates prior runs:** maintain explicit schema readers.
- **Migration becomes a memory redesign:** preserve lifecycle semantics; limit change to durable representation and recovery.
- **Sensitive logs leak into journals:** store sanitized metadata and artifact references, not credentials or full conversations.

---

## Step 12 — Reprove deterministic review and commit gates

**Goal and scope**

Bind approval to the exact tested candidate and prevent post-approval mutation.

**Files**

Modify only where necessary:

- `_test`
- `_pre_review_gate`
- `_candidate_source_context`
- `_review`
- Commit path.
- Gate regression tests.

**Concrete changes**

1. Keep existing test, syntax, conflict-marker, nonempty-diff, and scope checks.
2. Preserve the current conflict detection baseline:
   ```python
   re.compile(r"^\+(<<<<<<<|=======|>>>>>>>)", re.MULTILINE)
   ```
   Any refinement must have separate fixtures.
3. Make test discovery evidence runner-specific. A bare exit code zero is insufficient when no tests ran.
4. Bind test results to a candidate content/tree identity.
5. Require staged content to match the tested candidate.
6. Keep reviewer source context index-derived and independent.
7. Persist:
   - Base commit.
   - Approved staged diff SHA-256.
   - Approved Git tree OID.
   - Test evidence identity.
   - Sol decision and model.
8. Immediately before commit, recheck scope, source integrity, HEAD, index/tree, diff hash, and writer quiescence.
9. Verify the resulting commit’s parent and tree.
10. Mark `committed` only after post-commit verification succeeds.
11. Preserve task-branch-only behavior; no automatic merge or push.

**Verification**

Tests must block review/commit for no discovery, failed tests, syntax errors, conflicts, empty diff, wrong hash, altered staged content, same-path unstaged mutations, moving base, and post-review writes.

Success must prove:

```text
tested candidate = approved staged tree = committed tree
```

**Pitfalls and mitigation**

- **Same filenames hide changed content:** bind content identities, not path lists.
- **Tests modify their own source:** invalidate the evidence or enforce a clean source boundary.
- **Commit succeeds but final state write crashes:** recover by verifying the expected parent/tree; never create a duplicate commit blindly.
- **Hash-format change breaks old records:** version the new candidate contract; do not reinterpret historical hashes.

---

## Step 13 — Complete Aider removal and synchronize documentation

**Goal and scope**

Remove all active Aider dependencies, transport assumptions, generated artifacts, and operational instructions.

**Files**

Modify:

- `lib/hermes_factory_v2.py`
- `tests/test_factory_v2.py`
- `.gitignore`
- `README.md`
- `docs/software-factory-SKILL.md`
- `SHA256SUMS`
- Dependency/package manifests if present.
- Launchers/install scripts where required.

Remove from the shipped factory bundle, after consumer verification:

- `bridge/agy_bridge.py`
- `systemd/agy-bridge.service.example`

Update at deployment:

- `C:/Users/HH18/AppData/Local/hermes/skills/software-development/software-factory-v2/SKILL.md`

**Concrete changes**

Delete:

- `AiderBuilder`.
- Aider-only version/model/configuration helpers.
- Metadata/settings writers.
- API-base and LiteLLM request plumbing.
- Aider history parsing and cleanup.
- Aider-specific mock HTTP server and opt-in tests.
- `.aider*` ignore rule.
- Unused `urllib` imports and Builder bridge constants.

Replace `test_aider_runs_lean_gemini_builder` with an AGY contract test asserting the new argv, exact model, cwd, timeout, result validation, and absent legacy flags.

Update docs to describe:

- Astra → AGY → Luna → Sol responsibilities.
- Exact default model and `--agy-bin`.
- AGY authentication and audited runtime prerequisites.
- Isolation limitations and fail-closed conditions.
- New artifacts, historical-run policy, JSONL compatibility.
- Offline versus live verification.
- No automatic model substitution, merge, or credential fallback.

Remove the installed skill’s “Keep Aider as the normal Builder” rule at deployment.

**Verification**

Add `tests/test_no_legacy_builder_dependencies.py` to check production imports, CLI help, configuration fields, package contents, and generated run artifacts.

A lexical scan may retain explicitly allowlisted migration history and negative tests. It must find zero **active** Aider requirements.

**Pitfalls and mitigation**

- **Blind replacement damages names/history:** use symbol- and context-aware edits.
- **Removing shared services:** remove factory package dependencies, not unrelated running services.
- **Old `.aider*` files become visible:** preserve user files; never clean source content to make the scan pass.
- **Checksum manifest stale:** regenerate only after final file content stabilizes.

---

## Step 14 — Run acceptance, obtain release approval, and deploy

**Goal and scope**

Demonstrate the complete pipeline without Aider or the Builder bridge.

**Files**

Create:

- `docs/agy-migration-acceptance.md`

Update only approved deployed module/launcher/skill copies.

**Concrete verification layers**

### A. Offline deterministic suite

Run from the migration worktree:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
python -B -m unittest discover -s tests -p "test_*.py"
python -B bin/hermes-code-factory-v2 run --help
python -B bin/hermes-code-factory-v2 plan --help
git diff --check
```

Require all supported baseline behaviors plus migration tests to pass.

### B. Real subprocess fixtures

Exercise the actual process supervisor, parser, timeouts, writer containment, and argument handling without a model.

### C. Installed AGY contract tests

With explicit authorization for model use:

- Verify exact version/model/configuration.
- Complete a tiny allowed edit.
- Verify fresh conversations across two slices.
- Verify UTF-8 paths and output.
- Verify unavailable-model/authentication failure.
- Verify no source, Git metadata, trusted-state, or scope escape.

### D. End-to-end factory tests

Use disposable repositories to exercise:

1. Successful build → tests → Sol approval → task commit.
2. Test failure → Luna → AGY repair → retest → approval.
3. Sol rejection → AGY rework → retest → fresh approval.
4. Sol rejection routed through Luna.
5. Builder timeout/partial output → retained non-resumable failure.
6. Scope violation → no review and no commit.
7. Post-approval mutation → hash gate rejection.
8. Prior-run disclosure from a legacy run.

Perform acceptance with Aider absent from the test runtime and no Builder bridge dependency. Do not stop unrelated user services merely to simulate absence.

**Deployment sequence**

1. Freeze the reviewed release tree and hashes.
2. Obtain Sol High’s approval of that exact tree.
3. Obtain explicit deployment/application authorization.
4. Back up exact deployed files.
5. Install module, launcher, docs/skill, and checksums as one reviewed release.
6. Run launcher help/status checks and the approved live smoke.
7. Compare deployed hashes to the release manifest.

**Pitfalls and mitigation**

- **Mocks presented as production proof:** report each layer independently.
- **Installed skill precedes working runtime:** deploy the approved set together.
- **AGY auto-update invalidates evidence:** require re-audit on identity change.
- **Deployment fails:** stop new dispatches and restore the reviewed installation backup. Never silently replay an AGY candidate through Aider.

## 4. Final release checklist

Sol High must reject the migration unless all of the following are evidenced:

- [ ] `AgyBuilder` is the only production Builder implementation.
- [ ] Default model is exactly `gemini-3.8-flash-high`.
- [ ] `--agy-bin` is resolved, persisted, and correctly used after resume.
- [ ] No active Aider executable, configuration, history, metadata/settings, LiteLLM, or Builder bridge dependency remains.
- [ ] AGY permission-skipping execution has an approved isolation boundary.
- [ ] Every Builder route uses the same durable dispatch and integrity checks.
- [ ] Per-slice and whole-plan scope gates are independently tested.
- [ ] Ambiguous/partial execution cannot reach tests, review, commit, or automatic replay.
- [ ] Budgets, locks, checkpoints, rollback, and failed evidence survive crashes.
- [ ] Issue history, trajectory, progressive disclosure, and legacy inspection remain functional.
- [ ] Requested JSONL journals have deterministic recovery and snapshot compatibility.
- [ ] Sol remains independent and approval binds the tested/staged/committed candidate.
- [ ] Main/source checkout and unrelated user changes remain preserved.
- [ ] Offline, installed-CLI, and live end-to-end evidence are reported separately.
- [ ] Repository and deployed artifacts match the formally approved release.

**Recommended execution order:** approve the baseline and runtime/isolation contract first. Then implement the adapter and provider-neutral guards. Switch the default only after those gates pass; remove the legacy package surface and deploy last.

