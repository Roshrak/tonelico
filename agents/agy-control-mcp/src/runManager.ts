import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { loadConfig, type ControlConfig } from "./config.js";
import { discoverModels, type ModelInfo } from "./modelCatalog.js";
import { classifyImplementation, MODEL_ROUTING_POLICY_VERSION, routingDecision, selectModel, TIER_CANDIDATES, type ModelSelection } from "./modelPolicy.js";
import { compileFollowUpPrompt, compileWorkerPrompt, PromptValidationError, redactForStorage, redactSecrets } from "./promptCompiler.js";
import { applyPatch, applySnapshotPatch, assertGitWorkspaceSafe, assertNoTrackedChanges, assertNoUntrackedCollisions, assertNoUntrackedFiles, checkFileScope, createWorktree, currentHead, generatePatch, normalizeScopePaths, patchPaths, repositoryRoot, runTestCommand, worktreeFingerprint } from "./git.js";
import { execCommand } from "./processUtils.js";
import { AgyRunner, type AgyRunnerLike } from "./runner.js";
import { assertSnapshotBaseline, canonicalManifest, createSnapshotWorkspace } from "./workspace.js";
import type { AgyOutcome, DelegateInput, DelegationMode, FollowUpInput, GateResult, ModelAttempt, ResolvedTier, RunMetadata, TokenUsage, WorkerReport, WorkspaceMode } from "./types.js";
import { CapacityController, sharedCapacityController } from "./capacityController.js";

export class ToolInputError extends Error {
  readonly questions: string[];
  constructor(message: string, questions: string[] = []) {
    super(message);
    this.name = "ToolInputError";
    this.questions = questions;
  }
}

interface InternalJobInput {
  title: string;
  objective: string;
  current_state: string;
  target_state: string;
  context?: string;
  allowed_paths: string[];
  forbidden_paths: string[];
  success_criteria: string[];
  test_command: string;
  timeout: number;
  budget: number;
  delegationMode: DelegationMode;
  workspaceMode: "auto" | WorkspaceMode;
}

interface RunReport {
  run_id: string;
  state: RunMetadata["state"];
  title: string;
  model?: string;
  summary?: string;
  confidence?: number;
  recommended_action?: string;
  actual_changed_paths: string[];
  diff_stat?: string;
  base_commit: string;
  patch_sha256?: string;
  usage: TokenUsage;
  gates: GateResult[];
  prompt_audit?: RunMetadata["prompt_audit"];
  routing_decision?: RunMetadata["routing_decision"];
  model_attempts?: RunMetadata["model_attempts"];
  fallback_used?: boolean;
  fallback_reason?: string;
  unsafe_shell_command: true;
  security: {
    run_id: string;
    repo_root: string;
    workspace_mode: WorkspaceMode;
    worktree_path: string;
    artifact_path: string;
    allowed_paths: string[];
    forbidden_paths: string[];
    test_command: string;
    base_commit: string;
    snapshot_baseline?: RunMetadata["snapshot_baseline"];
    snapshot_fingerprint?: string;
    actual_changed_paths: string[];
    patch_sha256?: string;
  };
  error?: string;
  report_sha256: string;
}

export interface RunManagerOptions {
  config?: ControlConfig;
  runner?: AgyRunnerLike;
  modelResolver?: (tier: ResolvedTier) => Promise<string>;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value).filter(([, item]) => item !== undefined).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
  return JSON.stringify(value);
}

function sha256(value: string): string { return createHash("sha256").update(value).digest("hex"); }
function sleep(milliseconds: number): Promise<void> { return new Promise((resolve) => setTimeout(resolve, milliseconds)); }
function isWithin(candidate: string, root: string): boolean {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function runBasePath(configRoot: string, metadata: Pick<RunMetadata, "run_id" | "repo_root">): string {
  const repoHash = sha256(path.resolve(metadata.repo_root).toLowerCase()).slice(0, 16);
  return path.join(path.resolve(configRoot), "runs", repoHash, metadata.run_id);
}

function metadataSecurity(metadata: RunMetadata): RunReport["security"] {
  return {
    run_id: metadata.run_id,
    repo_root: metadata.repo_root,
    workspace_mode: metadata.workspace_mode,
    worktree_path: metadata.worktree_path,
    artifact_path: metadata.artifact_path,
    allowed_paths: metadata.allowed_paths,
    forbidden_paths: metadata.forbidden_paths,
    test_command: metadata.test_command,
    base_commit: metadata.base_commit,
    snapshot_baseline: metadata.snapshot_baseline,
    snapshot_fingerprint: metadata.snapshot_fingerprint,
    actual_changed_paths: metadata.actual_changed_paths,
    patch_sha256: metadata.patch_sha256,
  };
}

function addUsage(target: TokenUsage, source?: TokenUsage): void {
  for (const key of ["input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens", "total_tokens"] as const) target[key] = (target[key] || 0) + (source?.[key] || 0);
}

function outputRecord(value: unknown): WorkerReport {
  if (!value || typeof value !== "object") throw new Error("AGY returned no structured object");
  const output = value as Record<string, unknown>;
  if (typeof output.patch !== "string" || typeof output.summary !== "string" || typeof output.confidence !== "number" || !Array.isArray(output.changed_files) || output.changed_files.length > 200 || output.changed_files.some((item) => typeof item !== "string")) throw new Error("Structured output lacks the implementation contract");
  if (output.patch.trim() && !/^diff --git a\/.+ b\/.+[\s\S]*^--- /m.test(output.patch)) throw new Error("Structured patch must be an extended unified Git diff beginning with diff --git");
  if (!Number.isFinite(output.confidence) || output.confidence < 0 || output.confidence > 1) throw new Error("confidence must be within 0..1");
  if (!["ready_for_review", "needs_changes", "blocked"].includes(String(output.recommended_action))) throw new Error("recommended_action is invalid");
  return output as unknown as WorkerReport;
}

export class RunManager {
  private readonly config: ControlConfig;
  private readonly runner: AgyRunnerLike;
  private readonly modelResolver?: (tier: ResolvedTier) => Promise<string>;
  private readonly runs = new Map<string, RunMetadata>();
  private readonly activeJobs = new Map<string, Promise<RunMetadata>>();
  private readonly cancelRequested = new Set<string>();
  private readonly cooldowns = new Map<string, number>();
  private readonly capacity: CapacityController;
  private readonly applyQueue = new Map<string, Promise<void>>();
  private readonly ready: Promise<void>;
  private shuttingDown = false;
  private modelCatalog: ModelInfo[] | undefined;

  constructor(options: RunManagerOptions = {}) {
    this.config = options.config || loadConfig();
    this.runner = options.runner || new AgyRunner();
    this.modelResolver = options.modelResolver;
    this.capacity = sharedCapacityController(this.config);
    this.ready = this.restoreRuns();
  }

  /** Configuration is shared with the workflow coordinator so both layers use the same limits and state root. */
  getConfig(): ControlConfig { return this.config; }

  private async restoreRuns(): Promise<void> {
    const rootStats = await fs.lstat(this.config.root).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined;
      throw error;
    });
    if (!rootStats) return;
    if (!rootStats.isDirectory() || rootStats.isSymbolicLink()) throw new Error("AGY control root must be a non-symlink directory");
    await fs.chmod(this.config.root, 0o700);
    const root = path.join(this.config.root, "runs");
    const repos = await fs.readdir(root, { withFileTypes: true }).catch(() => []);
    for (const repo of repos.filter((entry) => entry.isDirectory())) {
      const runDirectories = await fs.readdir(path.join(root, repo.name), { withFileTypes: true }).catch(() => []);
      for (const runDirectory of runDirectories.filter((entry) => entry.isDirectory())) {
        const runBase = path.join(root, repo.name, runDirectory.name);
        const metadataPath = path.join(runBase, "artifacts", "metadata.json");
        try {
          const metadata = JSON.parse(await fs.readFile(metadataPath, "utf8")) as RunMetadata;
          if (!metadata.run_id || metadata.run_id !== runDirectory.name || !metadata.repo_root || !["git", "snapshot"].includes(metadata.workspace_mode)) continue;
          const expectedBase = runBasePath(this.config.root, metadata);
          const expectedArtifact = path.join(expectedBase, "artifacts");
          const expectedWorkspace = path.join(expectedBase, metadata.workspace_mode === "snapshot" ? "snapshot" : "worktree");
          if (path.resolve(runBase) !== path.resolve(expectedBase) || path.resolve(metadata.artifact_path) !== path.resolve(expectedArtifact) || path.resolve(metadata.worktree_path) !== path.resolve(expectedWorkspace)) continue;
          if (!isWithin(expectedArtifact, this.config.root) || !isWithin(expectedWorkspace, this.config.root)) continue;
          const age = Date.now() - Date.parse(metadata.updated_at || metadata.created_at || "");
          if (Number.isFinite(age) && age > this.config.artifactRetentionDays * 24 * 60 * 60 * 1000 && !["queued", "running"].includes(metadata.state)) {
            await this.removeManagedPath(metadata.worktree_path);
            await this.removeManagedPath(runBase);
            continue;
          }
          if (metadata.state === "queued" || metadata.state === "running") {
            metadata.state = "interrupted";
            metadata.error = "The MCP server restarted while this run was active; use agy_follow_up to continue from the preserved worktree.";
            await this.writeMetadata(metadata);
          }
          this.runs.set(metadata.run_id, metadata);
        } catch {
          // Ignore incomplete or malformed artifact directories.
        }
      }
    }
  }

  private requireLive(): void {
    if (!this.config.live) throw new Error("Live AGY execution is disabled. Set AGY_CONTROL_LIVE=1.");
  }

  private artifactPaths(metadata: RunMetadata) {
    return {
      metadata: path.join(metadata.artifact_path, "metadata.json"),
      events: path.join(metadata.artifact_path, "events.ndjson"),
      stderr: path.join(metadata.artifact_path, "agy.stderr.log"),
      schema: path.join(metadata.artifact_path, "output-schema.json"),
      prompt: path.join(metadata.artifact_path, "compiled-prompt.md"),
      patch: path.join(metadata.artifact_path, "patch.diff"),
      gate: path.join(metadata.artifact_path, "gate.log"),
      report: path.join(metadata.artifact_path, "report.json"),
      result: path.join(metadata.artifact_path, "result.json")
    };
  }

  private async writeMetadata(metadata: RunMetadata): Promise<void> {
    metadata.updated_at = new Date().toISOString();
    await this.ensureStateRoot();
    await fs.mkdir(metadata.artifact_path, { recursive: true, mode: 0o700 });
    await fs.chmod(metadata.artifact_path, 0o700);
    const target = this.artifactPaths(metadata).metadata;
    const temporary = `${target}.${process.pid}.${randomUUID()}.tmp`;
    await fs.writeFile(temporary, JSON.stringify(metadata, null, 2), { encoding: "utf8", mode: 0o600, flag: "wx" });
    await fs.rename(temporary, target);
    await fs.chmod(target, 0o600);
  }

  private async ensureStateRoot(): Promise<void> {
    await fs.mkdir(this.config.root, { recursive: true, mode: 0o700 });
    const stats = await fs.lstat(this.config.root);
    if (!stats.isDirectory() || stats.isSymbolicLink()) throw new Error("AGY control root must be a non-symlink directory");
    await fs.chmod(this.config.root, 0o700);
  }

  private async removeManagedPath(target: string): Promise<void> {
    await this.assertManagedPath(target);
    await fs.rm(path.resolve(target), { recursive: true, force: true });
  }

  private async assertManagedPath(target: string): Promise<void> {
    const managedRoot = await fs.realpath(this.config.root);
    const absoluteTarget = path.resolve(target);
    if (!isWithin(absoluteTarget, managedRoot) || absoluteTarget === managedRoot) throw new Error("Refusing to remove a path outside the managed control root");
    const stats = await fs.lstat(absoluteTarget).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined;
      throw error;
    });
    if (!stats) return;
    if (stats.isSymbolicLink()) throw new Error("Refusing to remove a symlink from the managed control root");
    const realTarget = await fs.realpath(absoluteTarget);
    if (!isWithin(realTarget, managedRoot) || realTarget === managedRoot) throw new Error("Refusing to remove a path outside the managed control root");
  }

  private async assertTrustedMetadataPaths(metadata: RunMetadata): Promise<void> {
    const expectedBase = runBasePath(this.config.root, metadata);
    const expectedArtifact = path.join(expectedBase, "artifacts");
    const expectedWorkspace = path.join(expectedBase, metadata.workspace_mode === "snapshot" ? "snapshot" : "worktree");
    if (!["git", "snapshot"].includes(metadata.workspace_mode) || path.resolve(metadata.artifact_path) !== path.resolve(expectedArtifact) || path.resolve(metadata.worktree_path) !== path.resolve(expectedWorkspace) || !isWithin(expectedBase, this.config.root)) {
      throw new Error("Persisted run paths are invalid or outside the managed control root");
    }
    for (const target of [expectedBase, expectedArtifact, expectedWorkspace]) {
      const stats = await fs.lstat(target).catch((error: NodeJS.ErrnoException) => {
        if (error.code === "ENOENT") return undefined;
        throw error;
      });
      if (stats?.isSymbolicLink()) throw new Error("Persisted run paths contain a symlink");
      if (stats) {
        const realTarget = await fs.realpath(target);
        const managedRoot = await fs.realpath(this.config.root);
        if (!isWithin(realTarget, managedRoot)) throw new Error("Persisted run paths are outside the managed control root");
      }
    }
  }

  private async assertPersistedMetadataMatches(metadata: RunMetadata): Promise<void> {
    await this.assertArtifactFile(this.artifactPaths(metadata).metadata, metadata.artifact_path);
    const stored = JSON.parse(await fs.readFile(this.artifactPaths(metadata).metadata, "utf8")) as RunMetadata;
    if (canonicalJson(stored) !== canonicalJson(metadata)) throw new Error("Persisted run metadata was modified after delegation");
  }

  private async assertArtifactFile(target: string, artifactRoot: string): Promise<void> {
    const stats = await fs.lstat(target).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined;
      throw error;
    });
    if (!stats) throw new Error("Required AGY artifact is missing");
    if (!stats.isFile() || stats.isSymbolicLink()) throw new Error("AGY artifact must be a regular file");
    const realTarget = await fs.realpath(target);
    const realRoot = await fs.realpath(artifactRoot);
    if (!isWithin(realTarget, realRoot)) throw new Error("AGY artifact is outside the managed artifact directory");
  }

  private async persist(metadata: RunMetadata): Promise<void> {
    this.runs.set(metadata.run_id, metadata);
    await this.writeMetadata(metadata);
  }

  private validateDelegate(input: DelegateInput): InternalJobInput {
    const missing: string[] = [];
    for (const field of ["repo_root", "title", "objective", "current_state", "target_state", "test_command"] as const) if (!input[field] || !String(input[field]).trim()) missing.push(field);
    if (!Array.isArray(input.allowed_paths) || !input.allowed_paths.length) missing.push("allowed_paths");
    if (!Array.isArray(input.success_criteria) || !input.success_criteria.length) missing.push("success_criteria");
    if (missing.length) throw new ToolInputError(`Missing required task fields: ${missing.join(", ")}`, missing.slice(0, 3));
    const timeout = input.timeout_seconds ?? this.config.defaultTimeoutSeconds;
    const tier = input.tier || "auto";
    const budget = input.token_budget ?? (tier === "auto" ? this.config.budgets.fast : this.config.budgets[tier]);
    const delegationMode = input.delegation_mode || "user_requested";
    const workspaceMode = input.workspace_mode || "auto";
    if (!["auto", "git", "snapshot"].includes(workspaceMode)) throw new ToolInputError("workspace_mode must be 'auto', 'git', or 'snapshot'");
    if (!Number.isInteger(timeout) || timeout < 10 || timeout > this.config.maxTimeoutSeconds) throw new ToolInputError(`timeout_seconds must be 10..${this.config.maxTimeoutSeconds}`);
    if (!Number.isInteger(budget) || budget < 500 || budget > 100000) throw new ToolInputError("token_budget must be 500..100000");
    if (redactSecrets(input.test_command).labels.size) throw new ToolInputError("test_command contains secret-like material and cannot be persisted or executed");
    if (delegationMode === "automatic") this.validateAutomaticTestCommand(input.test_command);
    try {
      return { title: input.title.trim(), objective: input.objective.trim(), current_state: input.current_state.trim(), target_state: input.target_state.trim(), context: input.context, allowed_paths: normalizeScopePaths(input.allowed_paths), forbidden_paths: normalizeScopePaths(input.forbidden_paths || [], true), success_criteria: input.success_criteria.map((item) => item.trim()).filter(Boolean), test_command: input.test_command.trim(), timeout, budget, delegationMode, workspaceMode };
    } catch (error) {
      throw new ToolInputError(error instanceof Error ? error.message : String(error));
    }
  }

  private validateAutomaticTestCommand(command: string): void {
    const normalized = command.trim();
    if (/[\r\n;&|<>`]|\$\(|\b(?:curl|wget|irm|iwr|invoke-webrequest|powershell|cmd(?:\.exe)?)\b/i.test(normalized)) {
      throw new ToolInputError("automatic delegation rejects shell composition, downloaders, and command interpreters in test_command");
    }
    const permitted = [
      /^npm test(?: -- [\w:.,=\- ]+)?$/,
      /^npm run [a-z0-9][a-z0-9:_\-]*(?: -- [\w:.,=\- ]+)?$/i,
      /^uv run pytest(?: [\w:./=\- ]+)?$/,
      /^cargo test(?: [\w:./=\- ]+)?$/,
      /^go test(?: [\w:./=\- ]+)?$/,
      /^dotnet test(?: [\w:./=\- ]+)?$/,
    ];
    if (!permitted.some((pattern) => pattern.test(normalized))) throw new ToolInputError("automatic delegation requires a supported deterministic test-command family");
  }

  classifyRisk(input: Pick<InternalJobInput, "title" | "objective" | "target_state" | "context" | "allowed_paths">): ReturnType<typeof classifyImplementation> {
    return classifyImplementation(input);
  }

  private async selectTierModel(tier: ResolvedTier, startIndex = 0, fallbackReason?: ModelSelection["fallback_reason"]): Promise<ModelSelection> {
    if (this.modelResolver) {
      const model = await this.modelResolver(tier);
      return { model, candidate_index: startIndex, fallback_used: startIndex > 0, fallback_reason: startIndex > 0 ? fallbackReason : undefined, candidate_chain: [...TIER_CANDIDATES[tier]] };
    }
    this.modelCatalog ||= await discoverModels(this.config.agyCommand, this.config.modelIds);
    if (!this.modelCatalog.length) throw new Error("AGY model discovery failed; no model will be guessed.");
    const available = new Set(this.modelCatalog.map((model) => model.id).filter((model) => Date.now() >= (this.cooldowns.get(model) || 0)));
    const selected = selectModel(tier, available, startIndex, fallbackReason);
    if (!selected) throw new Error(`No policy-approved model is available for tier ${tier}`);
    return selected;
  }

  private async runAgy(metadata: RunMetadata, prompt: string, audit: RunMetadata["prompt_audit"], conversationId?: string, startIndex = 0, fallbackReason?: ModelSelection["fallback_reason"], tokenBudget = metadata.token_budget): Promise<AgyOutcome> {
    const paths = this.artifactPaths(metadata);
    await fs.mkdir(metadata.artifact_path, { recursive: true });
    await fs.writeFile(paths.prompt, prompt, { encoding: "utf8", mode: 0o600 });
    const tier = audit?.tier || "fast";
    const selection = await this.selectTierModel(tier, startIndex, fallbackReason);
    const model = selection.model;
    metadata.selected_model = model;
    metadata.fallback_used ||= selection.fallback_used;
    metadata.fallback_reason ||= selection.fallback_reason;
    metadata.prompt_audit = audit;
    metadata.state = "running";
    metadata.phase = `implement:${tier}`;
    await this.persist(metadata);
    const schema = {
      type: "object", additionalProperties: false,
      required: ["patch", "summary", "confidence", "changed_files", "recommended_action"],
      properties: {
        patch: { type: "string", maxLength: this.config.maxPatchBytes }, summary: { type: "string", maxLength: 16000 }, confidence: { type: "number", minimum: 0, maximum: 1 },
        changed_files: { type: "array", maxItems: 200, items: { type: "string" } }, assumptions: { type: "array", items: { type: "string" } }, risks: { type: "array", items: { type: "string" } }, tests_run: { type: "array", items: { type: "string" } }, uncertainties: { type: "array", items: { type: "string" } },
        recommended_action: { type: "string", enum: ["ready_for_review", "needs_changes", "blocked"] }
      }
    };
    await fs.writeFile(paths.schema, JSON.stringify(schema, null, 2), { encoding: "utf8", mode: 0o600 });
    const args = ["--sandbox", "--mode", "plan", "--model", model, "--add-dir", metadata.worktree_path, "--disable-slash-commands", "--input-format", "stream-json", "--output-format", "stream-json", "--json-schema", paths.schema];
    if (conversationId) args.push("--conversation", conversationId);
    if (this.shuttingDown) throw new Error("Run manager is shutting down");
    const releaseCapacity = await this.capacity.acquire(
      tier,
      metadata.timeout_seconds,
      () => this.shuttingDown || this.cancelRequested.has(metadata.run_id),
    );
    try {
      if (this.cancelRequested.has(metadata.run_id)) return { state: "cancelled", failureReason: "interrupted", exitCode: null, usage: {} };
      const outcome = await this.runner.run({ runId: metadata.run_id, command: this.config.agyCommand, args, cwd: metadata.worktree_path, prompt, eventLogPath: paths.events, stderrLogPath: paths.stderr, timeoutSeconds: metadata.timeout_seconds, tokenBudget, maxLogBytes: this.config.maxLogBytes, conversationId, conversationUsageBaseline: conversationId ? (metadata.conversation_usage || metadata.usage) : undefined });
      addUsage(metadata.usage, outcome.usage);
      const trigger: ModelAttempt["trigger"] = selection.fallback_reason || "primary";
      metadata.model_attempts = [...metadata.model_attempts || [], { tier, model, trigger, outcome: outcome.state, usage: outcome.usage, error: outcome.errorMessage }];
      if (outcome.conversationUsage) metadata.conversation_usage = outcome.conversationUsage;
      else if (!metadata.conversation_usage) metadata.conversation_usage = outcome.usage;
      if (outcome.conversationId) metadata.conversation_id = outcome.conversationId;
      if (outcome.failureReason === "quota_exhausted") this.cooldowns.set(model, Date.now() + 5 * 60 * 1000);
      const storedOutcome = { ...outcome, response: undefined, structuredOutput: outcome.structuredOutput && typeof outcome.structuredOutput === "object" ? { ...(outcome.structuredOutput as Record<string, unknown>), patch: undefined } : undefined };
      await fs.writeFile(paths.result, JSON.stringify(redactForStorage(storedOutcome), null, 2), { encoding: "utf8", mode: 0o600 });
      return outcome;
    } finally {
      await releaseCapacity();
    }
  }

  private async applyWorkerPatch(metadata: RunMetadata, output: WorkerReport, beforeHash: string): Promise<void> {
    const afterHash = await worktreeFingerprint(metadata.worktree_path);
    if (afterHash !== beforeHash) throw new Error("AGY modified the isolated worktree directly; patch-only contract was violated.");
    const patch = output.patch.trim();
    if (!patch) throw new Error("Worker returned no unified Git patch");
    if (Buffer.byteLength(patch, "utf8") > this.config.maxPatchBytes) throw new Error("Worker patch exceeds the configured size limit");
    if (redactSecrets(patch).labels.size) throw new Error("Worker patch contains secret-like material and was blocked");
    patchPaths(patch);
    const modelPatchPath = path.join(metadata.artifact_path, "model.patch");
    await fs.writeFile(modelPatchPath, `${patch.replace(/\r?\n/g, "\n")}\n`, { encoding: "utf8", mode: 0o600 });
    await execCommand("git", ["apply", "--whitespace=nowarn", modelPatchPath], { cwd: metadata.worktree_path, timeout: 30000 }).catch((error) => { throw new Error(`Worker patch failed to apply: ${error instanceof Error ? error.message : String(error)}`); });
  }

  private async runGates(metadata: RunMetadata): Promise<boolean> {
    const paths = this.artifactPaths(metadata);
    const gates: GateResult[] = [];
    const scope = await checkFileScope(metadata.worktree_path, metadata.allowed_paths, metadata.forbidden_paths);
    metadata.actual_changed_paths = scope.changed_paths;
    gates.push({ name: "file_scope", passed: scope.passed, detail: scope.passed ? scope.changed_paths.join(", ") : JSON.stringify(scope.violations) });
    let testPassed = false;
    if (scope.passed) {
      const test = await runTestCommand(metadata.test_command, metadata.worktree_path, metadata.timeout_seconds, this.config.maxLogBytes);
      const cleanLog = redactSecrets(test.output).text;
      await fs.writeFile(paths.gate, cleanLog, { encoding: "utf8", mode: 0o600 });
      testPassed = test.passed;
      gates.push({ name: "tests", passed: testPassed, detail: `exit=${test.exitCode}; unsafe_shell_command=true` });
    }
    let patchGenerated = false;
    if (scope.passed && testPassed) {
      const patch = await generatePatch(metadata.worktree_path, paths.patch, this.config.maxPatchBytes);
      const content = await fs.readFile(paths.patch, "utf8");
      const containsSecret = redactSecrets(content).labels.size > 0;
      patchGenerated = patch.stat !== "(empty diff)" && !containsSecret;
      metadata.patch_sha256 = patch.sha256;
      gates.push({ name: "nonempty_patch", passed: patch.stat !== "(empty diff)", detail: patch.stat });
      gates.push({ name: "patch_secret_scan", passed: !containsSecret, detail: containsSecret ? "secret-like material detected" : "clear" });
    }
    metadata.gates = gates;
    metadata.state = !scope.passed ? "blocked" : testPassed && patchGenerated ? "ready_for_review" : "failed";
    return metadata.state === "ready_for_review";
  }

  private async buildReport(metadata: RunMetadata, workerOutput?: WorkerReport): Promise<RunReport> {
    const paths = this.artifactPaths(metadata);
    const previous = JSON.parse(await fs.readFile(paths.report, "utf8").catch(() => "{}")) as Partial<RunReport>;
    const cleanSummary = workerOutput?.summary ? redactSecrets(workerOutput.summary).text : undefined;
    const report: RunReport = {
      run_id: metadata.run_id, state: metadata.state, title: redactSecrets(metadata.title).text, model: metadata.selected_model,
      summary: cleanSummary ?? previous.summary, confidence: workerOutput?.confidence ?? previous.confidence, recommended_action: workerOutput?.recommended_action ?? previous.recommended_action,
      actual_changed_paths: metadata.actual_changed_paths, diff_stat: metadata.gates.find((gate) => gate.name === "nonempty_patch")?.detail ?? previous.diff_stat,
      base_commit: metadata.base_commit, patch_sha256: metadata.patch_sha256, usage: metadata.usage, gates: metadata.gates,
      prompt_audit: metadata.prompt_audit, routing_decision: metadata.routing_decision, model_attempts: metadata.model_attempts,
      fallback_used: metadata.fallback_used, fallback_reason: metadata.fallback_reason,
      unsafe_shell_command: true, security: metadataSecurity(metadata), error: metadata.error, report_sha256: ""
    };
    report.report_sha256 = sha256(canonicalJson(report));
    metadata.report_sha256 = report.report_sha256;
    await fs.writeFile(paths.report, JSON.stringify(report, null, 2), { encoding: "utf8", mode: 0o600 });
    return report;
  }

  private async finalize(metadata: RunMetadata, workerOutput?: WorkerReport): Promise<RunMetadata> {
    await this.buildReport(metadata, workerOutput);
    await this.persist(metadata);
    return metadata;
  }

  private async tryAutomaticRepair(
    metadata: RunMetadata,
    audit: RunMetadata["prompt_audit"],
    repairAttempt: number,
    reason: string,
  ): Promise<RunMetadata | undefined> {
    if (metadata.delegation_mode !== "automatic" || repairAttempt >= 1 || this.cancelRequested.has(metadata.run_id)) return undefined;
    const usedGeneratedTokens = (metadata.usage.output_tokens || 0) + (metadata.usage.thinking_tokens || 0);
    const remainingBudget = metadata.token_budget - usedGeneratedTokens;
    if (remainingBudget < 500) return undefined;
    const tier = audit?.tier || metadata.routing_decision?.resolved_tier || "fast";
    const compiled = compileFollowUpPrompt({
      run_id: metadata.run_id,
      requested_correction: "Correct the current isolated implementation so every unchanged acceptance criterion and deterministic gate passes.",
      failing_tests_or_logs: redactSecrets(reason).text.slice(-8000),
      decisions_to_keep: [
        "Do not expand the allowed file scope.",
        "Keep the original objective and acceptance criteria.",
        "Return only an incremental patch against the current isolated worktree.",
      ],
      unchanged_allowed_paths: metadata.allowed_paths,
      current_success_criteria: metadata.success_criteria,
    }, { tier, contextBudgetTokens: this.config.contextBudgets[tier] });
    metadata.state = "queued";
    metadata.phase = "automatic_repair";
    metadata.error = undefined;
    metadata.gates = [];
    await this.persist(metadata);
    return await this.runPipeline(metadata, compiled.prompt, compiled.audit, metadata.conversation_id, repairAttempt + 1, remainingBudget);
  }

  private async runPipeline(metadata: RunMetadata, prompt: string, audit: RunMetadata["prompt_audit"], conversationId?: string, repairAttempt = 0, tokenBudget = metadata.token_budget): Promise<RunMetadata> {
    let workerOutput: WorkerReport | undefined;
    try {
      let startIndex = 0;
      let fallbackReason: ModelSelection["fallback_reason"] | undefined;
      let outcome: AgyOutcome | undefined;
      let beforeHash = "";
      for (let attempt = 0; attempt < 2; attempt += 1) {
        beforeHash = await worktreeFingerprint(metadata.worktree_path);
        outcome = await this.runAgy(metadata, prompt, audit, conversationId, startIndex, fallbackReason, tokenBudget);
        if (outcome.state === "done") break;
        const detail = `${outcome.errorMessage || ""}\n${outcome.response || ""}`;
        const canFallback = outcome.failureReason === "quota_exhausted" || /invalid model selection|not recognized as a known model|unknown model/i.test(detail);
        if (!canFallback || attempt === 1) break;
        const currentIndex = (metadata.routing_decision?.candidate_chain || []).indexOf(metadata.selected_model || "");
        const runTier = audit?.tier || "fast";
        if (currentIndex < 0 || currentIndex + 1 >= TIER_CANDIDATES[runTier].length) break;
        startIndex = currentIndex + 1;
        fallbackReason = outcome.failureReason === "quota_exhausted" ? "quota_fallback" : "model_selection_fallback";
      }
      if (!outcome) throw new Error("AGY produced no outcome");
      if (outcome.state !== "done") throw new Error(outcome.errorMessage || `AGY job state ${outcome.state}`);
      try {
        workerOutput = outputRecord(outcome.structuredOutput);
      } catch (error) {
        const repaired = await this.tryAutomaticRepair(metadata, audit, repairAttempt, error instanceof Error ? error.message : String(error));
        if (repaired) return repaired;
        throw error;
      }
      if (workerOutput.recommended_action === "blocked") { metadata.state = "blocked"; return await this.finalize(metadata, workerOutput); }
      if (workerOutput.recommended_action === "needs_changes") {
        const repaired = await this.tryAutomaticRepair(metadata, audit, repairAttempt, [
          workerOutput.summary,
          ...(workerOutput.uncertainties || []),
          ...(workerOutput.risks || []),
        ].filter(Boolean).join("\n"));
        if (repaired) return repaired;
        metadata.state = "needs_follow_up";
        return await this.finalize(metadata, workerOutput);
      }
      try {
        await this.applyWorkerPatch(metadata, workerOutput, beforeHash);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        if (/^Patch (?:path|has|contains)/i.test(message)) {
          metadata.state = "blocked";
          metadata.error = redactSecrets(message).text;
          return await this.finalize(metadata, workerOutput);
        }
        const repairable = !/modified the isolated worktree directly|secret-like material|exceeds the configured size limit/i.test(message);
        const repaired = repairable ? await this.tryAutomaticRepair(metadata, audit, repairAttempt, message) : undefined;
        if (repaired) return repaired;
        throw error;
      }
      const passed = await this.runGates(metadata);
      if (!passed) {
        const scopeFailed = metadata.gates.some((gate) => gate.name === "file_scope" && !gate.passed);
        const secretFailed = metadata.gates.some((gate) => gate.name === "patch_secret_scan" && !gate.passed);
        if (!scopeFailed && !secretFailed) {
          const gateLog = await fs.readFile(this.artifactPaths(metadata).gate, "utf8").catch(() => "");
          const reason = [
            `Deterministic gates failed: ${metadata.gates.filter((gate) => !gate.passed).map((gate) => `${gate.name}: ${gate.detail || "failed"}`).join("; ")}`,
            gateLog.slice(-8000),
          ].filter(Boolean).join("\n");
          const repaired = await this.tryAutomaticRepair(metadata, audit, repairAttempt, reason);
          if (repaired) return repaired;
        }
      }
      return await this.finalize(metadata, workerOutput);
    } catch (error) {
      metadata.state = this.cancelRequested.has(metadata.run_id) ? "cancelled" : "failed";
      metadata.error = redactSecrets(error instanceof Error ? error.message : String(error)).text;
      return await this.finalize(metadata, workerOutput);
    } finally {
      this.cancelRequested.delete(metadata.run_id);
      this.activeJobs.delete(metadata.run_id);
    }
  }

  async delegate(rawInput: DelegateInput): Promise<{ run_id: string; state: "queued"; resolved_tier: ResolvedTier; base_commit: string; prompt_audit: RunMetadata["prompt_audit"]; budget: number; timeout_seconds: number }> {
    await this.ready;
    if (this.shuttingDown) throw new Error("Run manager is shutting down");
    this.requireLive();
    const input = this.validateDelegate(rawInput);
    const requestedTier = rawInput.tier || "auto";
    const classified = this.classifyRisk(input);
    const tier = requestedTier === "auto" ? classified.tier : requestedTier;
    let compiled;
    try { compiled = compileWorkerPrompt(input, { tier, contextBudgetTokens: this.config.contextBudgets[tier] }); }
    catch (error) { if (error instanceof PromptValidationError) throw new ToolInputError(error.message, error.questions); throw error; }
    const sourceRoot = await fs.realpath(rawInput.repo_root).catch(() => { throw new ToolInputError("repo_root must be an existing directory"); });
    if (!(await fs.stat(sourceRoot)).isDirectory()) throw new ToolInputError("repo_root must be a directory");
    const configuredStateRoot = path.resolve(this.config.root);
    const stateRootStats = await fs.lstat(configuredStateRoot).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined;
      throw error;
    });
    if (stateRootStats?.isSymbolicLink()) throw new ToolInputError("AGY control state root must not be a symlink");
    const canonicalStateRoot = path.join(await fs.realpath(path.dirname(configuredStateRoot)), path.basename(configuredStateRoot));
    if (isWithin(canonicalStateRoot, sourceRoot)) throw new ToolInputError("AGY control state must be outside the target project");
    const repoHash = sha256(path.resolve(sourceRoot).toLowerCase()).slice(0, 16);
    const runId = `${new Date().toISOString().replace(/[-:.TZ]/g, "")}-${randomUUID().slice(0, 8)}`;
    const base = path.join(this.config.root, "runs", repoHash, runId);
    const artifactPath = path.join(base, "artifacts");
    await fs.mkdir(artifactPath, { recursive: true });
    let repoRoot = sourceRoot;
    let workspaceMode: WorkspaceMode = "snapshot";
    let worktreePath = path.join(base, "snapshot");
    let baseCommit: string | undefined;
    let snapshotBaseline: RunMetadata["snapshot_baseline"];
    let snapshotFingerprint: string | undefined;
    try {
      if (input.workspaceMode !== "snapshot") {
        const gitWorktreePath = path.join(base, "worktree");
        let candidateGitRoot: string | undefined;
        try {
          candidateGitRoot = await repositoryRoot(sourceRoot);
          candidateGitRoot = await fs.realpath(candidateGitRoot);
          if (candidateGitRoot !== sourceRoot) throw new Error("repo_root is inside a larger Git repository; snapshot mode is required");
          await assertNoTrackedChanges(candidateGitRoot);
          await assertNoUntrackedFiles(candidateGitRoot);
          await assertGitWorkspaceSafe(candidateGitRoot);
          const gitBaseCommit = await currentHead(candidateGitRoot);
          await createWorktree(candidateGitRoot, gitWorktreePath, gitBaseCommit);
          repoRoot = candidateGitRoot;
          workspaceMode = "git";
          worktreePath = gitWorktreePath;
          baseCommit = gitBaseCommit;
        } catch (error) {
          if (candidateGitRoot) await this.removeManagedPath(gitWorktreePath).catch(() => undefined);
          if (input.workspaceMode === "git") throw error;
          await this.removeManagedPath(gitWorktreePath).catch(() => undefined);
        }
      }
      if (workspaceMode === "snapshot") {
        const snapshot = await createSnapshotWorkspace(sourceRoot, worktreePath);
        baseCommit = snapshot.base_commit;
        snapshotBaseline = { files: snapshot.files, directories: snapshot.directories };
        snapshotFingerprint = snapshot.fingerprint;
      }
    } catch (error) { await this.removeManagedPath(base).catch(() => undefined); throw error; }
    if (!baseCommit) throw new Error("Isolated workspace has no baseline commit");
    const now = new Date().toISOString();
    const budget = rawInput.token_budget ?? this.config.budgets[tier];
    const profile = requestedTier === "auto" ? classified.profile : tier === "fast" ? "workhorse" : tier === "reasoning" ? "deep_reasoning" : "high_risk_debug";
    const reasons = requestedTier === "auto" ? classified.reason_codes : ["explicit_tier_override"];
    const metadata: RunMetadata = { run_id: runId, repo_root: repoRoot, workspace_mode: workspaceMode, worktree_path: worktreePath, artifact_path: artifactPath, title: redactForStorage(input.title) as string, requested_tier: requestedTier, delegation_mode: input.delegationMode, risk_level: classified.risk, routing_decision: routingDecision(profile, reasons, requestedTier, tier), model_attempts: [], state: "queued", phase: "compiled", allowed_paths: input.allowed_paths, forbidden_paths: input.forbidden_paths, success_criteria: redactForStorage(input.success_criteria) as string[], test_command: input.test_command, timeout_seconds: input.timeout, token_budget: budget, usage: {}, gates: [], base_commit: baseCommit, snapshot_baseline: snapshotBaseline, snapshot_fingerprint: snapshotFingerprint, actual_changed_paths: [], unsafe_shell_command: true, created_at: now, updated_at: now };
    await this.persist(metadata);
    const job = this.runPipeline(metadata, compiled.prompt, compiled.audit);
    this.activeJobs.set(runId, job);
    return { run_id: runId, state: "queued", resolved_tier: tier, base_commit: baseCommit, prompt_audit: compiled.audit, budget: metadata.token_budget, timeout_seconds: input.timeout };
  }

  async followUp(rawInput: FollowUpInput): Promise<{ run_id: string; state: "queued" }> {
    await this.ready;
    if (this.shuttingDown) throw new Error("Run manager is shutting down");
    this.requireLive();
    const metadata = this.runs.get(rawInput.run_id);
    if (!metadata) throw new ToolInputError(`Unknown run_id: ${rawInput.run_id}`);
    if (this.activeJobs.has(metadata.run_id)) throw new Error("Run is still active; call agy_wait first.");
    if (!["ready_for_review", "needs_follow_up", "blocked", "failed", "interrupted"].includes(metadata.state)) throw new Error(`Cannot follow up run in state ${metadata.state}`);
    if (!rawInput.requested_correction?.trim()) throw new ToolInputError("requested_correction is required");
    if (rawInput.timeout_seconds !== undefined && (!Number.isInteger(rawInput.timeout_seconds) || rawInput.timeout_seconds < 10 || rawInput.timeout_seconds > this.config.maxTimeoutSeconds)) throw new ToolInputError(`timeout_seconds must be 10..${this.config.maxTimeoutSeconds}`);
    if (rawInput.token_budget !== undefined && (!Number.isInteger(rawInput.token_budget) || rawInput.token_budget < 500 || rawInput.token_budget > 100000)) throw new ToolInputError("token_budget must be 500..100000");
    metadata.state = "queued";
    metadata.error = undefined;
    metadata.gates = [];
    if (rawInput.timeout_seconds) metadata.timeout_seconds = rawInput.timeout_seconds;
    if (rawInput.token_budget) metadata.token_budget = rawInput.token_budget;
    if (rawInput.updated_success_criteria?.length) metadata.success_criteria = redactForStorage(rawInput.updated_success_criteria.map((item) => item.trim()).filter(Boolean)) as string[];
    const classified = this.classifyRisk({ title: metadata.title, objective: rawInput.requested_correction, target_state: rawInput.requested_correction, context: rawInput.failing_tests_or_logs, allowed_paths: metadata.allowed_paths });
    const tier = metadata.requested_tier === "auto" ? classified.tier : metadata.requested_tier as ResolvedTier;
    metadata.routing_decision = routingDecision(metadata.requested_tier === "auto" ? classified.profile : tier === "fast" ? "workhorse" : tier === "reasoning" ? "deep_reasoning" : "high_risk_debug", metadata.requested_tier === "auto" ? classified.reason_codes : ["explicit_tier_override"], metadata.requested_tier, tier);
    const compiled = compileFollowUpPrompt({ ...rawInput, unchanged_allowed_paths: metadata.allowed_paths, current_success_criteria: metadata.success_criteria }, { tier, contextBudgetTokens: this.config.contextBudgets[tier] });
    await this.persist(metadata);
    const job = this.runPipeline(metadata, compiled.prompt, compiled.audit, metadata.conversation_id);
    this.activeJobs.set(metadata.run_id, job);
    return { run_id: metadata.run_id, state: "queued" };
  }

  async wait(runId: string, timeoutSeconds = 30): Promise<RunMetadata> {
    await this.ready;
    if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 1 || timeoutSeconds > 90) throw new ToolInputError("timeout_seconds must be 1..90");
    const started = Date.now();
    while (Date.now() - started < timeoutSeconds * 1000) {
      const metadata = this.runs.get(runId);
      if (!metadata) throw new ToolInputError(`Unknown run_id: ${runId}`);
      if (!this.activeJobs.has(runId)) return metadata;
      await sleep(250);
    }
    const metadata = this.runs.get(runId);
    if (!metadata) throw new ToolInputError(`Unknown run_id: ${runId}`);
    return metadata;
  }

  async report(runId: string): Promise<Record<string, unknown>> {
    await this.ready;
    const metadata = this.runs.get(runId);
    if (!metadata) throw new ToolInputError(`Unknown run_id: ${runId}`);
    await this.assertTrustedMetadataPaths(metadata);
    const report = JSON.parse(await fs.readFile(this.artifactPaths(metadata).report, "utf8").catch(() => "{}")) as Record<string, unknown>;
    return { metadata: { ...metadata, worktree_path: undefined, artifact_path: undefined, test_command: undefined }, report };
  }

  async diff(runId: string, offset = 0, limitBytes = 48000): Promise<Record<string, unknown>> {
    await this.ready;
    const metadata = this.runs.get(runId);
    if (!metadata) throw new ToolInputError(`Unknown run_id: ${runId}`);
    await this.assertTrustedMetadataPaths(metadata);
    if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(limitBytes) || limitBytes < 1024 || limitBytes > 48000) throw new ToolInputError("offset must be >=0 and limit_bytes must be 1024..48000");
    const content = await fs.readFile(this.artifactPaths(metadata).patch).catch(() => Buffer.alloc(0));
    if (offset > content.length || (offset < content.length && (content[offset] & 0xc0) === 0x80)) throw new ToolInputError("offset must be a valid UTF-8 byte boundary within the patch");
    let end = Math.min(content.length, offset + limitBytes);
    while (end < content.length && end > offset && (content[end] & 0xc0) === 0x80) end -= 1;
    const page = content.subarray(offset, end).toString("utf8");
    return { run_id: runId, offset, next_offset: end, complete: end >= content.length, patch_sha256: metadata.patch_sha256, diff: page };
  }

  async cancel(runId: string): Promise<RunMetadata> {
    await this.ready;
    const metadata = this.runs.get(runId);
    if (!metadata) throw new ToolInputError(`Unknown run_id: ${runId}`);
    if (metadata.state === "cancelled") return metadata;
    if (!this.activeJobs.has(runId) || !["queued", "running"].includes(metadata.state)) throw new Error(`Cannot cancel run in state ${metadata.state}`);
    this.cancelRequested.add(runId);
    await this.runner.kill(runId);
    metadata.state = "cancelled";
    metadata.error = "Cancellation requested";
    await this.persist(metadata);
    return metadata;
  }

  private async acquireApplyFilesystemLock(repoRoot: string): Promise<() => Promise<void>> {
    const lockRoot = path.join(this.config.root, "apply-locks", sha256(path.resolve(repoRoot).toLowerCase()).slice(0, 16));
    const lockPath = path.join(lockRoot, "lock");
    await fs.mkdir(lockRoot, { recursive: true, mode: 0o700 });
    const deadline = Date.now() + 90_000;
    while (Date.now() < deadline) {
      try {
        await fs.mkdir(lockPath, { mode: 0o700 });
        await fs.writeFile(path.join(lockPath, "owner.json"), JSON.stringify({ pid: process.pid, created_at: new Date().toISOString() }), { encoding: "utf8", mode: 0o600 });
        return async () => { await this.removeManagedPath(lockPath).catch(() => undefined); };
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
        const owner = JSON.parse(await fs.readFile(path.join(lockPath, "owner.json"), "utf8").catch(() => "{}")) as { pid?: number };
        let alive = false;
        if (Number.isInteger(owner.pid) && owner.pid! > 0) {
          try { process.kill(owner.pid!, 0); alive = true; } catch { alive = false; }
        }
        const stats = await fs.stat(lockPath).catch(() => undefined);
        if (!alive && stats && Date.now() - stats.mtimeMs > (this.config.maxTimeoutSeconds + 120) * 1000) await this.removeManagedPath(lockPath).catch(() => undefined);
      }
      await sleep(100);
    }
    throw new Error("Timed out waiting for the repository apply lock");
  }

  private async withApplyLock<T>(repoRoot: string, operation: () => Promise<T>): Promise<T> {
    const key = path.resolve(repoRoot).toLowerCase();
    const previous = this.applyQueue.get(key);
    let releaseQueue!: () => void;
    const current = new Promise<void>((resolve) => { releaseQueue = resolve; });
    this.applyQueue.set(key, current);
    if (previous) await previous;
    let releaseFilesystem: (() => Promise<void>) | undefined;
    try {
      releaseFilesystem = await this.acquireApplyFilesystemLock(repoRoot);
      return await operation();
    } finally {
      await releaseFilesystem?.();
      releaseQueue();
      if (this.applyQueue.get(key) === current) this.applyQueue.delete(key);
    }
  }

  async apply(runId: string, reportHash: string): Promise<{ run_id: string; state: "applied"; applied: true }> {
    await this.ready;
    const metadata = this.runs.get(runId);
    if (!metadata) throw new ToolInputError(`Unknown run_id: ${runId}`);
    await this.assertTrustedMetadataPaths(metadata);
    return await this.withApplyLock(metadata.repo_root, async () => {
      await this.assertPersistedMetadataMatches(metadata);
      if (metadata.state !== "ready_for_review" || !metadata.patch_sha256 || !metadata.report_sha256) throw new Error(`Run is not ready for review; current state=${metadata.state}`);
      if (reportHash !== metadata.report_sha256) throw new Error("Report hash is stale or invalid");
      const reportPath = this.artifactPaths(metadata).report;
      await this.assertArtifactFile(reportPath, metadata.artifact_path);
      const report = JSON.parse(await fs.readFile(reportPath, "utf8")) as RunReport;
      const suppliedHash = report.report_sha256;
      report.report_sha256 = "";
      if (suppliedHash !== reportHash || report.state !== "ready_for_review" || sha256(canonicalJson(report)) !== reportHash || canonicalJson(report.security) !== canonicalJson(metadataSecurity(metadata))) throw new Error("Persisted report was modified after review");
      const patchPath = this.artifactPaths(metadata).patch;
      await this.assertArtifactFile(patchPath, metadata.artifact_path);
      const patch = await fs.readFile(patchPath, "utf8");
      if (sha256(patch) !== metadata.patch_sha256 || report.patch_sha256 !== metadata.patch_sha256) throw new Error("Patch was modified after review");
      if (metadata.workspace_mode === "snapshot") {
        if (!metadata.snapshot_baseline) throw new Error("Snapshot baseline is missing; create a new delegation");
        if (metadata.snapshot_fingerprint && sha256(canonicalManifest(metadata.snapshot_baseline.files, metadata.snapshot_baseline.directories)) !== metadata.snapshot_fingerprint) {
          throw new Error("Snapshot baseline fingerprint is invalid or tampered");
        }
        await assertSnapshotBaseline(metadata.repo_root, metadata.snapshot_baseline.files, metadata.actual_changed_paths, metadata.snapshot_baseline.directories);
        await applySnapshotPatch(metadata.repo_root, patch);
      } else {
        if (await currentHead(metadata.repo_root) !== metadata.base_commit) throw new Error("Repository HEAD changed since the isolated run; create a new delegation");
        await assertNoTrackedChanges(metadata.repo_root);
        await assertNoUntrackedCollisions(metadata.repo_root, metadata.actual_changed_paths);
        await applyPatch(metadata.repo_root, patch, metadata.base_commit);
      }
      metadata.state = "applied";
      await this.finalize(metadata);
      return { run_id: runId, state: "applied", applied: true };
    });
  }

  async cleanup(runId: string): Promise<{ run_id: string; cleaned: true }> {
    await this.ready;
    const metadata = this.runs.get(runId);
    if (!metadata) throw new ToolInputError(`Unknown run_id: ${runId}`);
    await this.assertTrustedMetadataPaths(metadata);
    if (this.activeJobs.has(runId)) throw new Error("Run is active; cancel and wait before cleanup");
    if (metadata.state === "ready_for_review") throw new Error("A ready patch cannot be discarded by cleanup; review it, apply it, or request a follow-up.");
    if (metadata.workspace_mode === "snapshot") await this.removeManagedPath(metadata.worktree_path);
    else await this.removeManagedPath(metadata.worktree_path);
    if (metadata.state !== "applied") metadata.state = "discarded";
    await this.finalize(metadata);
    return { run_id: runId, cleaned: true };
  }

  async shutdown(): Promise<void> {
    await this.ready;
    if (this.shuttingDown) return;
    this.shuttingDown = true;
    const active = [...this.activeJobs.entries()];
    for (const [runId] of active) {
      this.cancelRequested.add(runId);
      const metadata = this.runs.get(runId);
      if (metadata) {
        metadata.state = "cancelled";
        metadata.error = "MCP server shutdown cancelled the active run";
        await this.persist(metadata);
      }
      await this.runner.kill(runId).catch(() => undefined);
    }
    await Promise.race([Promise.allSettled(active.map(([, job]) => job)), sleep(5000)]);
  }

  async status(): Promise<Record<string, unknown>> {
    await this.ready;
    let version: string | undefined;
    let models: ModelInfo[] = [];
    if (/^(1|true|yes)$/i.test(process.env.AGY_CONTROL_STATUS_SKIP_DISCOVERY || "")) {
      version = "skipped-for-multiclient-smoke";
      models = this.modelCatalog || this.config.modelIds.map((id) => ({ id, tier: id.includes("opus") ? "expert" as const : id.includes("pro") || id.includes("sonnet") ? "reasoning" as const : "fast" as const }));
    } else {
      try {
        const { stdout } = await execCommand(this.config.agyCommand, ["--version"], { timeout: 10000 });
        version = stdout.trim();
        models = this.modelCatalog || await discoverModels(this.config.agyCommand, this.config.modelIds);
        this.modelCatalog = models;
      } catch (error) { version = error instanceof Error ? error.message : String(error); }
    }
    return { live: this.config.live, agy_version: version, models, model_policy: { version: MODEL_ROUTING_POLICY_VERSION, tiers: TIER_CANDIDATES, manual_only_models: ["claude-sonnet-4-6", "gpt-oss-120b-medium"] }, active_runs: [...this.activeJobs.keys()], cooldowns: Object.fromEntries([...this.cooldowns].map(([model, until]) => [model, new Date(until).toISOString()])), concurrency: { ...this.config.concurrency, global: this.config.globalConcurrency }, budgets: this.config.budgets, unsafe_shell_command: true };
  }

  async listModels(): Promise<ModelInfo[]> {
    await this.ready;
    this.modelCatalog = await discoverModels(this.config.agyCommand, this.config.modelIds);
    return this.modelCatalog;
  }
}
