---
name: agy-control-worker
description: Automatically route nontrivial bounded implementation, refactor, migration, concurrency, security, or bulk document-processing tasks to the installed AGY Control MCP worker when the repository is committed, tracked-clean, path-scoped, and has deterministic tests. Do not use for tiny edits, review-only work, unbounded exploration, final clinical or study reasoning, grading, mastery, or dirty repositories.
---

# AGY Control automatic worker routing

Codex is the planner, orchestrator, integrator, and reviewer. AGY is an always-available execution layer. Do not wrap AGY in a native Codex subagent.

## Automatic workflow routing

For a meaningful task, first decide whether local work or delegation has better expected value. Use `agy_workflow_start` when the work has independent subtasks, dependencies, research/analysis/validation steps, or benefits from parallel execution. The workflow coordinator persists state, shares compact dependency summaries, schedules by priority, retries transient failures, and exposes `agy_workflow_status`/`agy_workflow_report`. Use `agy_workflow_add_tasks` for newly discovered bounded work and cancel or reprioritize work that is no longer useful. Use `agy_delegate` for a single bounded implementation task.

The MCP server is configured to start with Codex and run with live AGY enabled. If `agy_status` reports `live=false`, do not silently fall back to an uncontrolled native subagent; report the integration problem or continue locally.

## Eligible implementation task

Automatically use AGY only when all conditions hold:

1. The user asked to change/build/fix, not merely answer, review, or diagnose.
2. The repository is committed and tracked-clean.
3. Allowed paths, success criteria, and a deterministic test command are known.
4. The task is meaningful enough to justify worker context overhead: multi-file change, migration, API/schema work, concurrency/security, substantial refactor, or bulk processing.

For eligible implementation work, call `agy_status`, then `agy_delegate` with `delegation_mode: "automatic"`. Use only a supported deterministic test command: `npm test`, `npm run <script>`, `uv run pytest`, `cargo test`, `go test`, or `dotnet test`.

## Automatic model profiles

- `fast` uses `gemini-3.8-flash-high` as the primary workhorse model and Claude only if Gemini cannot run.
- `reasoning` also uses `gemini-3.8-flash-high` first for migrations, architecture, algorithms, public contracts, and cross-module root-cause work; Claude is the fallback.
- `expert` uses `claude-opus-4-6-thinking` for security, concurrency, corruption, nondeterministic bugs, and high-risk minimal fixes. Codex still reviews every result.
- Automatic routing uses only Gemini 3.8 Flash High and Claude Opus. Never choose Sonnet, GPT-OSS, or older Gemini models automatically.

After delegation, call `agy_wait`, `agy_report`, and every UTF-8 page of `agy_diff`; review the entire patch before any follow-up or application. `agy_apply` always requires explicit user approval. Call `agy_cleanup` only after a terminal run is safe to discard.

## Workflow task kinds

Workflow tasks may be `implementation`, `analysis`, `research`, `validation`, `testing`, or `planning`. Implementation tasks retain isolated patch generation and approval-gated application. The other kinds are read-only structured workers intended to reduce exploration and synthesis workload; they must not be used for final medical, clinical, study, grading, mastery, or decision authority.

## Document and study work

Use local document ingest/search first. Delegate only allowed clerical roles with a locked scope and sufficient evidence. Never delegate final teaching, diagnosis, prescribing, current-guidance interpretation, grading, mastery, or final answer keys.

## Stay local

Do not call AGY for a tiny edit, a dirty/uncommitted repository, missing deterministic verification, unbounded exploration, review-only/diagnosis-only work, patient decision-making, or material marked `local_only`.
