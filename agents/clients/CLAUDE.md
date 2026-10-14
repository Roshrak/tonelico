# AGY Control

AGY Control is configured as the user-scoped `agy-control` MCP server and is
available across projects. In Claude Code sessions, Claude is the commander:
keep architecture, important judgment, integration, and final decisions with
Claude. AGY tools may describe their commander generically (or as Codex); in a
Claude Code session the commander is Claude.

Claude uses `/home/aesc/.local/state/agy-control-mcp-claude` for AGY job state.
Keep this root separate from other clients' AGY state: server startup recovers
persisted jobs and workflows, so sharing a root can interfere with another live
client. Each client is registered through `scripts/agy-control-mcp --client <name>`
(see the repo README).

- Proactively use AGY for useful, nontrivial, bounded supporting work such as
  repository inspection, research, implementation, and validation.
- Call `mcp__agy-control__agy_capabilities` or `mcp__agy-control__agy_status`
  before routing work. Use the actual tool names exposed by the MCP client.
- Use `agy_workflow_start` for read-only analysis/research/validation and for
  multiple independent or dependent tasks. Use `agy_delegate` for a single
  bounded implementation task.
- Give every worker a tightly scoped objective, repository root, allowed paths,
  forbidden paths, and explicit success criteria. Keep credentials and unrelated
  user files outside worker scope.
- Let workflows manage dependencies, scheduling, retries, context handoff,
  progress, and cancellation. Continue useful commander work while workers run,
  then inspect wait/status/report results and complete diffs.
- Implementation workers produce isolated patches. Verify the base state and
  independently test results before accepting changes. The user gave standing
  approval on 2026-10-13: Claude may call `agy_apply` without asking, once the
  review passes. The review is the safeguard, so do all of it first: the run
  is `ready_for_review` with every gate passing; the whole diff was read
  (every page) and each objective case is matched; every changed path is
  inside `allowed_paths`; the test command runs real project tests; the
  repository HEAD has not moved; the run came from this task. If the server
  blocks a patch for protected files, pass `allow_protected` only when the
  objective names those files. If any check fails, do not apply; follow up,
  discard, or do the work directly. Say what was applied and the run id.
- Use `delegation_mode="automatic"` only for nontrivial bounded implementation
  work in a clean, committed repository with explicit paths and deterministic
  tests. Read-only workers cannot edit files, execute commands, access the
  network, or spawn workers.
- Do not delegate tiny edits, unbounded exploration, final reasoning, grading,
  mastery decisions, destructive actions, or irreversible external actions.
- Distinguish intended actions, command results, and independently verified
  outcomes. Report completion only after a fresh observation verifies it.
