# AGY Builder Operating Envelope & Token-Budget Recovery

This document defines the operating limits, error taxonomy, and adaptive recovery policy for the AGY 1.2.2 builder (`gemini-3.8-flash-high`) in Software Factory v2.

## 1. Invocation Budget vs. Account Quota

- **API Quota**: Google/Gemini account-level rate limits (RPM, TPM, daily credits). Quota exhaustion presents as HTTP 429 / RESOURCE_EXHAUSTED. Separate completely into `RATE_LIMIT` and `PROVIDER_QUOTA` in telemetry.
- **Session Token/Turn Budget**: Per-run execution envelope inside a single AGY CLI invocation (`--print`). Governed by context window, tool turn limits (`num_turns`), thinking tokens, and elapsed duration.
- **Root Failure Mode**: On very large single files (>250 KB, such as `hermes_factory_v2.py` ~473 KB) or overly broad monolithic milestone instructions, AGY exhausts its internal turn/token budget while inspecting code and planning, exiting with `actual_changed_paths=[]` or incomplete output without emitting a valid patch. Retrying with the identical prompt results in 100% recurring failure.
- **Diagnostic Metrics**: Record `time_to_first_write` and `turns_before_first_write`. A high turn count before the first write (or timing out with zero writes) indicates tool-reading loops and navigation exhaustion.

## 2. Telemetry Schema & Error Classification

Each AGY builder attempt records normalized telemetry at `<attempt_dir>/agy_telemetry.json`:

```json
{
  "task_id": "T3_modify_review_contract",
  "attempt": 1,
  "expected_change": true,
  "model": "gemini-3.8-flash-high",
  "prompt_chars": 3420,
  "target_files_bytes": 473765,
  "context_bytes_provided": 3200,
  "bytes_read_by_agy_tools": null,
  "tool_read_calls": 3,
  "symbols_exposed": 1,
  "elapsed_seconds": 42.6,
  "exit_code": 0,
  "num_turns": 4,
  "usage": {
    "input_tokens": 128450,
    "output_tokens": 1220,
    "thinking_tokens": 890,
    "total_tokens": 130560
  },
  "outcome": {
    "status": "SUCCESS",
    "termination_reason": "SUCCESS",
    "changed_paths": ["lib/hermes_factory_v2.py"],
    "patch_bytes": 1420
  }
}
```

*Note on schema fields:* `usage`, `thinking_tokens`, and `bytes_read_by_agy_tools` allow `null` if unexposed by the AGY CLI event stream. Never fabricate missing token counts.

### Termination Reason Enum & Rules
- `SUCCESS`: Clean exit, event stream complete, `changed_paths` non-empty and verified within `allowed_files`.
- `TOKEN_BUDGET_EXHAUSTED`: Only assigned when there is direct evidence of budget exhaustion from the CLI stream/error. Never infer budget exhaustion merely from `exit_code==0` with empty diffs.
- `RATE_LIMIT`: Account/provider RPM/TPM rate limits or HTTP 429. Distinct from session token budget.
- `PROVIDER_QUOTA`: Daily/monthly credit exhaustion or quota limits.
- `TIMEOUT`: Exceeded bounded CLI timeout (`--print-timeout`).
- `NO_PATCH`: CLI exited 0 with valid stream, but git index/diff has zero changes when `expected_change: true`. If `expected_change: false` (inspection/analysis), zero changes is a valid `SUCCESS`.
- `PROCESS_ERROR`: Non-zero exit code or abnormal OS process crash.
- `PROTOCOL_ERROR`: Malformed event stream, missing `init`/`result`, or invalid JSON.
- `CANCELLED`: Interrupted by orchestrator or timeout kill tree.

## 3. P4 Hybrid Retry & Slicing Decision Flow

### Unified Dispatch Budget Rule
- **Global Task Dispatch Budget**: All AGY invocations (whether original, shrunk, or sliced) draw from the single `max_task_attempts = 12` budget. Do not track separate attempt counters that hide invocations.
- **Per-Slice Progress Gate**: Maximum 3 dispatch attempts without progress on the same sub-slice.
- **Stagnation Gate**: If the failure signature or candidate diff remains identical across 2 consecutive attempts, abort the sub-slice immediately and advance to the next recovery step.

### Recovery Sequence on Failure (`TOKEN_BUDGET_EXHAUSTED` or `NO_PATCH`)

```text
Attempt 1 Fail (Token budget, timeout, or empty patch)
      │
      ▼
Attempt 2: P2 Context Shrink
      • Strip broad runner logs, run-state dumps, and historical narrative.
      • Retain only minimal failing test assertion + stacktrace (<= 500 chars).
      • Provide exact symbol signatures rather than full file dumps.
      │
      ├─► SUCCESS ──► Forward to Runner
      ▼
Attempt 3: P3 Symbol Localization & Pre-extraction (Prioritized over slicing)
      • Pre-localize symbols: isolate target function/class into a temporary slice or pass exact line boundaries.
      • Preserves logical task continuity while eliminating tool-reading loops.
      │
      ├─► SUCCESS ──► Forward to Runner
      ▼
Attempt 4..N: P4 Task Slicing (If localization alone is insufficient)
      • Decompose the task into 2–3 bounded sub-slices executed sequentially:
          - Slice A: Data types, interfaces, and contract definitions.
          - Slice B: Core internal logic implementation.
          - Slice C: Test updates and edge-case repairs.
      │
      ├─► SUCCESS ──► Forward to Runner
      ▼
Remaining budget exhausted without progress: Safe BLOCKED
      • Halt automated retries; mark state BLOCKED with retained attempt evidence.
      • Do NOT loop endlessly with naive retries.
      • Do NOT escalate implementation/budget failures to Astra, Luna, or Sol.
```

## 4. Benchmark & Testing Guidelines
- **Disposable Fixtures**: Never run benchmarks or stress tests directly against active approved repository sources. Use `git archive` or disposable temporary worktree snapshots.
- **Process Containment on Windows**: Verify complete process-tree termination (parent `agy.exe` + child node processes). An orchestrator cancel or timeout must guarantee zero orphan writers and zero candidate sync.

## 5. Capsule Targeting & Discovery Layer Protocol (S0 / S1 / S2 Benchmark)

When instructions or failure evidence lack explicit `file:line` or symbol hints, SoftFac localizes the builder surface before falling back to `path_reduced`.

### Strategy Definitions
- **S0 (Current Baseline)**: `_navigation_hints` regex (matching explicit `file:line` or qualified symbol) → existing Python AST parser.
- **S1 (RG + AST)**: Extract deterministic lexical anchors (snake_case, CamelCase, UPPER_CASE, quoted error strings) → `ripgrep` for path/line hits → enclosing Python AST maps line to symbol.
- **S2 (RG + ast-grep + AST)**: `ripgrep` narrows repo to 2–8 candidate files → `ast-grep outline --items structure --view expanded --json=stream --color never` produces structural JSON ranges → existing Python AST validates.

### Operational Boundaries & Hard Gates
- **Authority Separation**: Neither `ripgrep` nor `ast-grep` is an authority. Built-in Python AST is the sole authority for syntax validation, exact byte ranges, and source hashing. `ast-grep` is strictly a read-only candidate generator; never use `--rewrite` or rule engines in production.
- **Fail-Closed Hard Gate (`WRONG_TARGET = 0`)**: An erroneous candidate is fatal because AGY will patch the wrong symbol. If multiple candidate symbols match without decisive evidence, the locator MUST return `MUST_ABSTAIN` (safe fallback to `path_reduced`).
- **80/20 Marginal Value Rule**: If S1 (RG + AST) achieves $\ge 80\%$ of S2's exact target localization with `WRONG_TARGET = 0`, reject `ast-grep` as a dependency.
- **Phased Evaluation Protocol**:
  1. *Phase 1 (12-case pilot)*: 9 UNIQUE (3 explicit control, 3 known file unknown symbol, 3 known identifier unknown path) + 3 MUST_ABSTAIN (ambiguity/decoy). Gate to stop and adopt S1: UNIQUE >= 8/9, MUST_ABSTAIN = 3/3, and WRONG_TARGET = 0.
  2. *Phase 2 (25-case expansion)*: Test failures and Sol judge findings only if S1 fails Phase 1. Floor gate for S1 adoption: WRONG_TARGET = 0, safe_abstain = 5/5, S1_exact >= 16/20, AND S1_exact >= 80% of S2_exact.
  3. *Phase 3 (Live AGY validation)*: Only 4–6 hardest cases where S1 fails/ambiguous and S2 uniquely succeeds. Measure token savings, latency to first host write, and Runner candidate pass rate.
- **Baseline Binding & High-Signal Anchors**:
  - S0 baseline must bind to a disposable snapshot of the exact approved release commit (e.g. `71651e6`), not a hand-copied re-implementation.
  - S1 anchor extraction must discard generic conversational English words (`fix`, `error`, `handling`, `provider`) and retain only high-information code tokens (`snake_case`, `CamelCase`, `UPPER_CASE`, exact quoted strings, error codes, explicit file paths).

## 6. Operational Boundaries (Operating Envelope)

| Context Category | Sizing Envelope | Recommended Strategy |
| :--- | :--- | :--- |
| **Small / Bounded** | Single file < 100 KB, 1–3 affected functions | Standard bounded prompt (`task + file + failing test`) |
| **Medium Multi-file** | 2–4 files, total context 100–250 KB | Bounded prompt with strict `allowed_files` |
| **Large Single-file** | Target file > 250 KB (e.g. monolithic engines) | **Symbol-local targeting**: identify symbol line bounds; do NOT dump full file context |
| **Milestone Refactor** | Architectural or multi-subsystem feature | **Mandatory 3-stage slicing**: Contract -> Implementation -> Tests |
