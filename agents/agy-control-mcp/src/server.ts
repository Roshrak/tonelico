import { McpServer } from "@modelcontextprotocol/server";
import { serveStdio, type StdioServerHandle } from "@modelcontextprotocol/server/stdio";
import fs from "node:fs/promises";
import { z } from "zod";
import { randomUUID } from "node:crypto";
import { readBuildInfo } from "./buildInfo.js";
import { DocumentManager } from "./documentManager.js";
import { appendAttempt, deriveProgress } from "./studyProgress.js";
import { RunManager, ToolInputError } from "./runManager.js";
import { MODEL_ROUTING_POLICY_VERSION } from "./modelPolicy.js";
import { TaskOrchestrator } from "./orchestrator.js";

const instructions = "AGY Control is an always-available execution layer for this commander session (any MCP client: Claude Code, Codex, OpenCode, Hermes). Automatically call agy_capabilities or agy_status when delegation may help. Use agy_workflow_start for two or more independent bounded tasks, dependencies, research/analysis/validation, or parallel work; use agy_delegate for one implementation task. Continue useful commander work while queued workers run when possible, then use agy_workflow_wait/status/report for compact results. Add, reprioritize, retry, or cancel tasks as the plan changes. Implementation workers are isolated patch-only and agy_apply remains approval-gated. Read-only workers may inspect scoped repository material but cannot edit, execute commands, access network, or spawn workers. Do not delegate tiny edits, unbounded exploration, final study/clinical reasoning, grading, mastery, destructive actions, or irreversible external actions. The commander remains planner, orchestrator, integrator, and final decision-maker.";
const instanceId = randomUUID();
const startedAt = new Date().toISOString();

function toolResult(value: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(value) }], structuredContent: value as Record<string, unknown> };
}

async function invoke<T>(operation: () => Promise<T>) {
  try { return toolResult(await operation()); }
  catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const payload = {
      error: {
        code: error instanceof ToolInputError ? "invalid_tool_input" : (error as { name?: string })?.name || "operation_failed",
        message,
        retryable: /timeout|temporar|quota|capacity|interrupted/i.test(message),
        questions: error instanceof ToolInputError ? error.questions : [],
      },
    };
    return { content: [{ type: "text" as const, text: JSON.stringify(payload) }], isError: true };
  }
}

function waitProjection(value: Record<string, unknown>): Record<string, unknown> {
  return {
    kind: value.kind,
    run_id: value.run_id,
    workflow_id: value.workflow_id,
    job_id: value.job_id,
    state: value.state,
    phase: value.phase,
    task_counts: value.task_counts,
    tasks: value.tasks,
    result: value.result,
    error: value.error,
    usage: value.usage,
    updated_at: value.updated_at,
  };
}

const emptySchema = z.object({}).strict();
const implementationDelegateSchema = z.object({
  repo_root: z.string().min(1), title: z.string().min(1), objective: z.string().min(1), current_state: z.string().min(1), target_state: z.string().min(1), context: z.string().optional(),
  allowed_paths: z.array(z.string().min(1)).min(1), forbidden_paths: z.array(z.string().min(1)).optional(), success_criteria: z.array(z.string().min(1)).min(1), test_command: z.string().min(1),
  tier: z.enum(["auto", "fast", "reasoning", "expert"]).optional(), delegation_mode: z.enum(["automatic", "user_requested"]).optional(), workspace_mode: z.enum(["auto", "git", "snapshot"]).optional(), timeout_seconds: z.number().int().min(10).max(3600).optional(), token_budget: z.number().int().min(500).max(100000).optional()
}).strict();
const followUpSchema = z.object({
  run_id: z.string().min(1), requested_correction: z.string().min(1), failing_tests_or_logs: z.string().optional(), decisions_to_keep: z.array(z.string()).optional(), updated_success_criteria: z.array(z.string().min(1)).min(1).optional(),
  timeout_seconds: z.number().int().min(10).max(3600).optional(), token_budget: z.number().int().min(500).max(100000).optional()
}).strict();
const runIdSchema = z.object({ run_id: z.string().min(1) }).strict();

const ingestSchema = z.object({
  collection_name: z.string().min(1).optional(), collection_id: z.string().min(1).optional(), subject_id: z.string().min(1).optional(),
  paths: z.array(z.union([z.string().min(1), z.object({ path: z.string().min(1), source_id: z.string().min(1), source_kind: z.string().min(1).optional() }).strict()])).min(1).optional(), manifest_path: z.string().min(1).optional(),
  force: z.boolean().optional()
}).strict();
const scopeSchema = z.object({
  collection_id: z.string().min(1), profile: z.enum(["general", "study", "clinical_record"]).optional(),
  selectors: z.array(z.object({
    source_id: z.string().min(1).optional(), page_start: z.number().int().min(1).optional(), page_end: z.number().int().min(1).optional(),
    slides: z.tuple([z.number().int().min(1), z.number().int().min(1)]).optional(), sheets: z.array(z.string().min(1)).optional(),
    sections: z.array(z.string().min(1)).optional(), time_range_ms: z.tuple([z.number().int().min(0), z.number().int().min(0)]).optional()
  }).strict()).length(1), forbidden_topics: z.array(z.string().min(1)).optional()
}).strict();
const searchSchema = z.object({
  collection_id: z.string().min(1), query: z.string().min(1), scope_id: z.string().min(1).optional(),
  limit: z.number().int().min(1).max(12).optional(), token_budget: z.number().int().min(256).max(16000).optional(),
  mode: z.enum(["semantic", "ordered_scope", "cross_source"]).optional()
}).strict();
const evidenceReadSchema = z.object({
  bundle_id: z.string().min(1), cursor: z.number().int().min(0).optional(),
  item_ids: z.array(z.string().min(1)).min(1).optional(), token_budget: z.number().int().min(256).max(16000).optional()
}).strict();
const attemptSchema = z.object({
  attempts_path: z.string().min(1).optional(), subject_id: z.string().min(1).optional(), session_id: z.string().min(1).optional(), attempt_id: z.string().min(1).optional(), concept_id: z.string().min(1), correct: z.boolean(),
  difficulty: z.enum(["recall", "mechanism", "clinical", "multi-step"]), context_signature: z.string().min(1),
  reasoning_quality: z.enum(["weak", "partial", "sound"]), occurred_at: z.string().min(1).optional()
}).strict();
const progressSchema = z.object({ concepts_path: z.string().min(1).optional(), attempts_path: z.string().min(1).optional(), subject_id: z.string().min(1).optional(), output_path: z.string().min(1).optional() }).strict();
const studySessionStartSchema = z.object({
  subject_id: z.string().min(1), collection_id: z.string().min(1), scope_id: z.string().min(1),
  mode: z.enum(["teach-deep", "quiz-adaptive", "solve-exam", "zone-review", "finish-session"]),
  commander_model: z.string().min(1).optional(), active_concept_ids: z.array(z.string().min(1)).optional(),
}).strict();
const studySessionIdSchema = z.object({ session_id: z.string().min(1) }).strict();
const studyPreflightSchema = z.object({ session_id: z.string().min(1), draft: z.string().optional() }).strict();
const documentDelegateSchema = z.object({
  title: z.string().min(1), collection_id: z.string().min(1), scope_id: z.string().min(1), role: z.string().min(1),
  objective: z.string().min(1), profile: z.enum(["general", "study", "clinical_record"]).optional(),
  tier: z.enum(["auto", "fast", "reasoning", "expert"]).optional(), data_policy: z.enum(["standard", "local_only"]).optional(),
  force_worker: z.boolean().optional(), timeout_seconds: z.number().int().min(10).max(3600).optional(),
  bundle_id: z.string().min(1).optional()
}).strict();
const workflowTaskSchema = z.object({
  task_id: z.string().regex(/^[a-zA-Z0-9._-]{1,80}$/).optional(), parent_task_id: z.string().regex(/^[a-zA-Z0-9._-]{1,80}$/).optional(),
  kind: z.enum(["implementation", "analysis", "research", "validation", "testing", "planning"]).optional(), title: z.string().min(1), objective: z.string().min(1), current_state: z.string().optional(), target_state: z.string().optional(), context: z.string().optional(),
  allowed_paths: z.array(z.string().min(1)).optional(), forbidden_paths: z.array(z.string().min(1)).optional(), success_criteria: z.array(z.string().min(1)).optional(), test_command: z.string().min(1).optional(),
  tier: z.enum(["auto", "fast", "reasoning", "expert"]).optional(), delegation_mode: z.enum(["automatic", "user_requested"]).optional(), workspace_mode: z.enum(["auto", "git", "snapshot"]).optional(), timeout_seconds: z.number().int().min(10).max(3600).optional(), token_budget: z.number().int().min(500).max(100000).optional(), depends_on: z.array(z.string().regex(/^[a-zA-Z0-9._-]{1,80}$/)).optional(), priority: z.number().int().min(-100).max(100).optional(), max_attempts: z.number().int().min(1).max(10).optional()
}).strict();
const workflowStartSchema = z.object({
  repo_root: z.string().min(1), title: z.string().min(1), objective: z.string().optional(), shared_context: z.string().optional(), tasks: z.array(workflowTaskSchema).min(1).max(32), max_parallel: z.number().int().min(1).max(16).optional(), max_depth: z.number().int().min(0).max(8).optional(), continue_on_failure: z.boolean().optional()
}).strict();
const workflowAddSchema = z.object({ workflow_id: z.string().min(1), parent_task_id: z.string().regex(/^[a-zA-Z0-9._-]{1,80}$/).optional(), tasks: z.array(workflowTaskSchema).min(1).max(32) }).strict();
const workflowTaskControlSchema = z.object({ workflow_id: z.string().min(1), task_id: z.string().min(1) }).strict();
const workflowPrioritySchema = z.object({ workflow_id: z.string().min(1), task_id: z.string().min(1), priority: z.number().int().min(-100).max(100) }).strict();
const workflowIdSchema = z.object({ workflow_id: z.string().min(1) }).strict();

export function createMcpServer(manager = new RunManager(), documentManager = new DocumentManager(), orchestrator = new TaskOrchestrator(manager)): McpServer {
  const server = new McpServer({ name: "agy-control-mcp", version: "0.3.0" }, { instructions });
  server.registerTool("agy_status", { title: "AGY status", description: "Return build identity, instance health, implementation/document status, model catalog, concurrency, budgets, and active jobs.", inputSchema: emptySchema, annotations: { readOnlyHint: true, idempotentHint: true } }, async () => invoke(async () => ({
    server: { instance_id: instanceId, server_pid: process.pid, parent_pid: process.ppid, started_at: startedAt, build: await readBuildInfo(), routing_policy_version: MODEL_ROUTING_POLICY_VERSION },
    ...await manager.status(), document: await documentManager.status(), orchestration: await orchestrator.statusSummary(),
  })));
  server.registerTool("agy_capabilities", { title: "Discover AGY capabilities", description: "Return the current AGY task types, safety boundaries, workflow graph features, resource limits, models, and health metadata so the commander can route work dynamically.", inputSchema: emptySchema, annotations: { readOnlyHint: true, idempotentHint: true } }, async () => invoke(async () => ({ capabilities: orchestrator.capabilities(), health: await manager.status(), document: await documentManager.status() })));
  server.registerTool("list_models", { title: "List AGY models", description: "List available Antigravity model IDs and their logical tiers.", inputSchema: emptySchema, annotations: { readOnlyHint: true, idempotentHint: true } }, async () => invoke(() => manager.listModels()));
  server.registerTool("agy_delegate", { title: "Delegate implementation", description: "For an eligible bounded implementation task, start a patch-only AGY worker in an isolated Git worktree when possible, otherwise a private snapshot workspace. automatic mode accepts only safe deterministic test-command families; user_requested retains the documented shell risk.", inputSchema: implementationDelegateSchema, annotations: { destructiveHint: false, idempotentHint: false, openWorldHint: true } }, async (args) => invoke(() => manager.delegate(args)));
  server.registerTool("agy_follow_up", { title: "Correct implementation", description: "Resume the same AGY conversation to correct a bounded isolated worktree without expanding file scope.", inputSchema: followUpSchema, annotations: { destructiveHint: false, idempotentHint: false, openWorldHint: true } }, async (args) => invoke(() => manager.followUp(args)));
  server.registerTool("agy_wait", { title: "Wait for run or workflow", description: "Poll an implementation, document, or workflow run and return a compact current-state projection.", inputSchema: z.object({ run_id: z.string().min(1), timeout_seconds: z.number().int().min(1).max(90).optional() }).strict(), annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(async () => args.run_id.startsWith("wf-")
    ? waitProjection(await orchestrator.wait(args.run_id, args.timeout_seconds))
    : waitProjection(await documentManager.hasJob(args.run_id) ? await documentManager.wait(args.run_id, args.timeout_seconds) : await manager.wait(args.run_id, args.timeout_seconds) as unknown as Record<string, unknown>)));
  server.registerTool("agy_report", { title: "Read run or workflow report", description: "Return the discriminated integrity-bound report for an implementation, document, or workflow run.", inputSchema: runIdSchema, annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(async () => {
    if (args.run_id.startsWith("wf-")) return await orchestrator.report(args.run_id);
    if (await documentManager.hasJob(args.run_id)) return await documentManager.report(args.run_id);
    return { kind: "implementation", ...await manager.report(args.run_id) };
  }));
  server.registerTool("agy_diff", { title: "Read generated diff", description: "Read a generated final diff page before deciding whether to apply it.", inputSchema: z.object({ run_id: z.string().min(1), offset: z.number().int().min(0).optional(), limit_bytes: z.number().int().min(1024).max(48000).optional() }).strict(), annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(async () => {
    if (await documentManager.hasJob(args.run_id)) throw new Error("operation_not_applicable_to_document_run");
    return await manager.diff(args.run_id, args.offset, args.limit_bytes);
  }));
  server.registerTool("agy_cancel", { title: "Cancel run or workflow", description: "Cancel an implementation, document, or workflow run, preserving diagnostics and completed results.", inputSchema: runIdSchema, annotations: { destructiveHint: true, idempotentHint: true } }, async (args) => invoke(async () => {
    if (args.run_id.startsWith("wf-")) return await orchestrator.cancel(args.run_id);
    // Generic cancel dispatches document jobs too; agy_document_cancel stays as a one-release alias.
    if (await documentManager.hasJob(args.run_id)) return await documentManager.cancel(args.run_id);
    return await manager.cancel(args.run_id);
  }));
  server.registerTool("agy_apply", { title: "Apply reviewed patch", description: "After user approval, verify report, patch, base commit, and clean repository state before applying the patch without commit or push.", inputSchema: z.object({ run_id: z.string().min(1), report_sha256: z.string().length(64), decision: z.literal("apply") }).strict(), annotations: { destructiveHint: true, idempotentHint: false } }, async (args) => invoke(async () => {
    if (await documentManager.hasJob(args.run_id)) throw new Error("operation_not_applicable_to_document_run");
    return await manager.apply(args.run_id, args.report_sha256);
  }));
  server.registerTool("agy_cleanup", { title: "Clean isolated worktree", description: "Remove a completed isolated worktree while retaining reports and diagnostics for retention.", inputSchema: runIdSchema, annotations: { destructiveHint: true, idempotentHint: true } }, async (args) => invoke(() => manager.cleanup(args.run_id)));
  server.registerTool("agy_workflow_start", { title: "Start AGY workflow", description: "Start a persisted bounded task graph. Independent tasks run concurrently; dependencies, priorities, retries, shared context, and nested parent tasks are enforced by the control plane.", inputSchema: workflowStartSchema, annotations: { destructiveHint: false, idempotentHint: false, openWorldHint: true } }, async (args) => invoke(() => orchestrator.start(args)));
  server.registerTool("agy_workflow_wait", { title: "Wait for AGY workflow", description: "Wait for a bounded interval and return compact workflow progress without replaying task logs.", inputSchema: z.object({ workflow_id: z.string().min(1), timeout_seconds: z.number().int().min(1).max(90).optional() }).strict(), annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(() => orchestrator.wait(args.workflow_id, args.timeout_seconds)));
  server.registerTool("agy_workflow_status", { title: "Inspect AGY workflow", description: "Return task states, dependencies, progress, retries, and active worker IDs for a workflow.", inputSchema: workflowIdSchema, annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(() => orchestrator.status(args.workflow_id)));
  server.registerTool("agy_workflow_report", { title: "Aggregate AGY workflow", description: "Return structured task results and aggregate usage for a completed or active workflow.", inputSchema: workflowIdSchema, annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(() => orchestrator.report(args.workflow_id)));
  server.registerTool("agy_workflow_add_tasks", { title: "Add AGY workflow tasks", description: "Dynamically add bounded tasks or child tasks to a workflow; new runnable tasks are scheduled immediately.", inputSchema: workflowAddSchema, annotations: { destructiveHint: false, idempotentHint: false, openWorldHint: true } }, async (args) => invoke(() => orchestrator.addTasks(args)));
  server.registerTool("agy_workflow_reprioritize", { title: "Prioritize AGY task", description: "Change the priority of a queued workflow task; higher priority tasks are selected first when capacity opens.", inputSchema: workflowPrioritySchema, annotations: { destructiveHint: false, idempotentHint: false } }, async (args) => invoke(() => orchestrator.reprioritize(args.workflow_id, args.task_id, args.priority)));
  server.registerTool("agy_workflow_cancel", { title: "Cancel AGY workflow", description: "Cancel queued and active tasks in a workflow while retaining results and audit state.", inputSchema: workflowIdSchema, annotations: { destructiveHint: true, idempotentHint: true } }, async (args) => invoke(() => orchestrator.cancel(args.workflow_id)));
  server.registerTool("agy_workflow_cancel_task", { title: "Cancel AGY task", description: "Cancel one queued or active task without cancelling unrelated workflow tasks.", inputSchema: workflowTaskControlSchema, annotations: { destructiveHint: true, idempotentHint: true } }, async (args) => invoke(() => orchestrator.cancelTask(args.workflow_id, args.task_id)));
  server.registerTool("agy_workflow_retry_task", { title: "Retry AGY task", description: "Requeue a failed, blocked, or cancelled task and resume its workflow.", inputSchema: workflowTaskControlSchema, annotations: { destructiveHint: false, idempotentHint: false } }, async (args) => invoke(() => orchestrator.retryTask(args.workflow_id, args.task_id)));
  server.registerTool("agy_document_ingest", { title: "Ingest documents or a registered Study Herd subject", description: "Asynchronously parse local files, an explicit YAML manifest, or a registered subject's source manifest into SQLite/FTS5 without changing sources or calling AGY.", inputSchema: ingestSchema, annotations: { readOnlyHint: false, idempotentHint: true, openWorldHint: false } }, async (args) => invoke(() => documentManager.ingest(args)));
  server.registerTool("agy_document_wait", { title: "Wait for document job", description: "Deprecated alias for compact document wait.", inputSchema: z.object({ job_id: z.string().min(1), timeout_seconds: z.number().int().min(1).max(90).optional() }).strict(), annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(async () => waitProjection(await documentManager.wait(args.job_id, args.timeout_seconds))));
  server.registerTool("agy_scope_create", { title: "Create document scope", description: "Lock source hashes, parser/config version, and one page/slide/sheet/section/time selector before retrieval.", inputSchema: scopeSchema, annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(() => documentManager.createScope(args)));
  server.registerTool("agy_evidence_search", { title: "Search evidence", description: "Run local FTS5 retrieval and return a provenance-bound Evidence Bundle under a hard token cap without calling AGY.", inputSchema: searchSchema, annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(() => documentManager.search(args)));
  server.registerTool("agy_evidence_read", { title: "Read evidence bundle", description: "Read selected or paged evidence from a server-side bundle without repeating retrieval.", inputSchema: evidenceReadSchema, annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(() => documentManager.readEvidence(args)));
  server.registerTool("agy_document_delegate", { title: "Delegate document clerk", description: "Send only locked, capped evidence to a bounded AGY clerical role. data_policy=local_only blocks this tool. It cannot produce diagnoses, prescriptions, grades, mastery, or final answers.", inputSchema: documentDelegateSchema, annotations: { readOnlyHint: false, idempotentHint: false, openWorldHint: true } }, async (args) => invoke(() => documentManager.delegate(args)));
  server.registerTool("agy_document_report", { title: "Read document report", description: "Return document provenance, gates, attempts, cache state, external-processing flag, and usage.", inputSchema: runIdSchema, annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(() => documentManager.report(args.run_id)));
  server.registerTool("agy_artifact", { title: "Read document artifact", description: "Read a prompt, result, or report by UTF-8-safe byte pages.", inputSchema: z.object({ run_id: z.string().min(1), artifact: z.enum(["prompt", "result", "report"]), offset: z.number().int().min(0).optional(), limit_bytes: z.number().int().min(1024).max(48000).optional() }).strict(), annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(() => documentManager.artifact(args.run_id, args.artifact, args.offset, args.limit_bytes)));
  server.registerTool("agy_study_session_start", { title: "Start Study Herd session", description: "Persist a locked Study Herd session so the commander can resume compact state without replaying chat history.", inputSchema: studySessionStartSchema, annotations: { destructiveHint: true, idempotentHint: false, openWorldHint: false } }, async (args) => invoke(() => documentManager.startStudySession(args)));
  server.registerTool("agy_study_session_resume", { title: "Resume Study Herd session", description: "Return compact persisted Study Herd session state after revalidating its locked scope.", inputSchema: studySessionIdSchema, annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(() => documentManager.resumeStudySession(args.session_id)));
  server.registerTool("agy_study_preflight", { title: "Preflight Study Herd material", description: "Validate the active locked scope, forbidden topics, and source labels before commander teaching or testing.", inputSchema: studyPreflightSchema, annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(() => documentManager.preflightStudySession(args)));
  server.registerTool("agy_study_record_attempt", { title: "Record learner attempt", description: "Record an idempotent, concept-validated learner attempt; session attempts are also mirrored to the legacy NDJSON ledger.", inputSchema: attemptSchema, annotations: { destructiveHint: true, idempotentHint: false, openWorldHint: false } }, async (args) => invoke(async () => {
    if (!args.subject_id && !args.session_id) {
      if (!args.attempts_path) throw new Error("subject_id, session_id, or attempts_path is required");
      return { attempt: await appendAttempt(args.attempts_path, args), duplicate: false };
    }
    return await documentManager.recordStudyAttempt(args);
  }));
  server.registerTool("agy_study_progress", { title: "Derive study progress", description: "Derive conservative concept mastery from immutable concept IDs and append-only attempts.", inputSchema: progressSchema, annotations: { readOnlyHint: true, idempotentHint: true } }, async (args) => invoke(async () => {
    const paths = args.subject_id ? documentManager.studyProgressPaths(args.subject_id) : { concepts_path: args.concepts_path!, attempts_path: args.attempts_path! };
    if (!paths.concepts_path || !paths.attempts_path) throw new Error("subject_id or both concepts_path and attempts_path are required");
    const progress = await deriveProgress(paths.concepts_path, paths.attempts_path);
    if (args.output_path) await fs.writeFile(args.output_path, `${JSON.stringify(progress, null, 2)}\n`, "utf8");
    return progress;
  }));
  server.registerTool("agy_document_cancel", { title: "Cancel document run", description: "Cancel the active external document process and preserve diagnostics.", inputSchema: runIdSchema, annotations: { destructiveHint: true, idempotentHint: true } }, async (args) => invoke(() => documentManager.cancel(args.run_id)));
  server.registerTool("agy_document_cleanup", { title: "Discard disposable document run", description: "Remove failed or partial document artifacts; ready-for-commander evidence is protected.", inputSchema: runIdSchema, annotations: { destructiveHint: true, idempotentHint: true } }, async (args) => invoke(() => documentManager.cleanup(args.run_id)));
  return server;
}

export function startServer(): StdioServerHandle {
  const manager = new RunManager();
  const documentManager = new DocumentManager();
  const orchestrator = new TaskOrchestrator(manager);
  const handle = serveStdio(() => createMcpServer(manager, documentManager, orchestrator), { onerror: (error) => process.stderr.write(`agy-control-mcp: ${error.message}\n`) });
  let closing: Promise<void> | undefined;
  const close = () => closing ||= (async () => { await Promise.all([manager.shutdown(), documentManager.shutdown(), orchestrator.shutdown()]); await handle.close(); })();
  process.once("SIGINT", () => { void close(); });
  process.once("SIGTERM", () => { void close(); });
  process.stdin.once("end", () => { void close(); });
  return { close };
}
