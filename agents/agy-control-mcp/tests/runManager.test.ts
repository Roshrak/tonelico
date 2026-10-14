import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { loadConfig } from "../src/config.js";
import { RunManager } from "../src/runManager.js";
import type { AgyOutcome, AgyRunnerLike, RunnerJob } from "../src/runner.js";

class FakeRunner implements AgyRunnerLike {
  readonly jobs: RunnerJob[] = [];
  quotaOnce = false;
  registerProcess(): void {}
  async kill(): Promise<void> {}
  async run(job: RunnerJob): Promise<AgyOutcome> {
    this.jobs.push(job);
    if (this.quotaOnce) {
      this.quotaOnce = false;
      return { state: "failed", failureReason: "quota_exhausted", errorMessage: "quota exhausted", exitCode: 1, usage: { total_tokens: 1 } };
    }
    if (job.prompt.includes("direct-mutation")) {
      await fs.mkdir(path.join(job.cwd, "src"), { recursive: true });
      await fs.writeFile(path.join(job.cwd, "src", "example.ts"), "export const mutated = true;\n");
    }
    const implementer = job.prompt.includes("PATCH-ONLY PROTOCOL");
    if (implementer) {
      const unicodePatch = Array.from({ length: 180 }, (_, index) => `+// dòng-${String(index).padStart(3, "0")} tiếng Việt`).join("\n");
      let patch = `diff --git a/src/example.ts b/src/example.ts\nnew file mode 100644\nindex 0000000..7898192\n--- /dev/null\n+++ b/src/example.ts\n@@ -0,0 +1 @@\n+export function answer(): number { return 42; }\n`;
      let changedFiles = ["src/example.ts"];
      if (job.prompt.includes("unicode-pagination")) {
        patch = `diff --git a/src/unicode.ts b/src/unicode.ts\nnew file mode 100644\nindex 0000000..7898192\n--- /dev/null\n+++ b/src/unicode.ts\n@@ -0,0 +1,180 @@\n${unicodePatch}\n`;
        changedFiles = ["src/unicode.ts"];
      } else if (job.prompt.includes("leak-scope")) {
        patch = `diff --git a/src/example.ts b/src/example.ts\nnew file mode 100644\nindex 0000000..7898192\n--- /dev/null\n+++ b/src/example.ts\n@@ -0,0 +1 @@\n+export function answer(): number { return 42; }\ndiff --git a/.env b/.env\nnew file mode 100644\nindex 0000000..7898192\n--- /dev/null\n+++ b/.env\n@@ -0,0 +1 @@\n+BAD=1\n`;
      } else if (job.prompt.includes("snapshot-lifecycle-crud")) {
        patch = `diff --git a/src/existing.ts b/src/existing.ts\nindex 1111111..2222222 100644\n--- a/src/existing.ts\n+++ b/src/existing.ts\n@@ -1 +1 @@\n-export const initial = 1;\n+export const initial = 2;\ndiff --git a/src/nested/new.ts b/src/nested/new.ts\nnew file mode 100644\nindex 0000000..3333333\n--- /dev/null\n+++ b/src/nested/new.ts\n@@ -0,0 +1 @@\n+export const created = true;\ndiff --git a/src/obsolete.ts b/src/obsolete.ts\ndeleted file mode 100644\nindex 4444444..0000000\n--- a/src/obsolete.ts\n+++ /dev/null\n@@ -1 +0,0 @@\n-export const removeMe = true;\n`;
        changedFiles = ["src/existing.ts", "src/nested/new.ts", "src/obsolete.ts"];
      }
      return {
        state: "done", exitCode: 0, conversationId: "fake-conversation", numTurns: 1,
        usage: { input_tokens: 10, output_tokens: 2, total_tokens: 12 },
        structuredOutput: {
          patch,
          summary: "Added helper", confidence: 0.95, changed_files: changedFiles,
          recommended_action: "ready_for_review"
        }
      };
    }
    return {
      state: "done", exitCode: 0, conversationId: "review-conversation", numTurns: 1,
      usage: { input_tokens: 5, output_tokens: 1, total_tokens: 6 },
      structuredOutput: { decision: "approve", summary: "Patch is correct.", confidence: 0.9, findings: [] }
    };
  }
}

class BlockingRunner implements AgyRunnerLike {
  readonly killed: string[] = [];
  private resolveStarted!: () => void;
  private resolveRun?: (outcome: AgyOutcome) => void;
  readonly started = new Promise<void>((resolve) => { this.resolveStarted = resolve; });
  registerProcess(): void {}
  async run(): Promise<AgyOutcome> {
    this.resolveStarted();
    return await new Promise<AgyOutcome>((resolve) => { this.resolveRun = resolve; });
  }
  async kill(runId: string): Promise<void> {
    this.killed.push(runId);
    this.resolveRun?.({ state: "cancelled", failureReason: "interrupted", exitCode: null, usage: {} });
  }
}

class RepairRunner implements AgyRunnerLike {
  readonly jobs: RunnerJob[] = [];
  registerProcess(): void {}
  async kill(): Promise<void> {}
  async run(job: RunnerJob): Promise<AgyOutcome> {
    this.jobs.push(job);
    const first = this.jobs.length === 1;
    return {
      state: "done",
      exitCode: 0,
      conversationId: "repair-conversation",
      usage: { input_tokens: 10, output_tokens: 2, total_tokens: 12 },
      structuredOutput: {
        patch: first
          ? "diff --git a/src/example.ts b/src/example.ts\nnew file mode 100644\nindex 0000000..1111111\n--- /dev/null\n+++ b/src/example.ts\n@@ -0,0 +1 @@\n+export function answer(): number { return 41; }\n"
          : "diff --git a/src/example.ts b/src/example.ts\nindex 1111111..2222222 100644\n--- a/src/example.ts\n+++ b/src/example.ts\n@@ -1 +1 @@\n-export function answer(): number { return 41; }\n+export function answer(): number { return 42; }\n",
        summary: first ? "Initial implementation" : "Corrected failing test",
        confidence: 0.9,
        changed_files: ["src/example.ts"],
        recommended_action: "ready_for_review",
      },
    };
  }
}

async function createRepo(prefix: string): Promise<string> {
  const repo = await fs.mkdtemp(path.join(os.tmpdir(), `${prefix}-`));
  execFileSync("git", ["init"], { cwd: repo });
  execFileSync("git", ["config", "user.name", "Test"], { cwd: repo });
  execFileSync("git", ["config", "user.email", "test@example.com"], { cwd: repo });
  await fs.writeFile(path.join(repo, "README.md"), "# demo\n");
  execFileSync("git", ["add", "."], { cwd: repo });
  execFileSync("git", ["commit", "-m", "initial"], { cwd: repo });
  return repo;
}

async function createProject(prefix: string): Promise<string> {
  const project = await fs.mkdtemp(path.join(os.tmpdir(), `${prefix}-`));
  await fs.writeFile(path.join(project, "README.md"), "# snapshot project\n");
  return project;
}

function manager(_repo: string, root: string, runner: AgyRunnerLike = new FakeRunner()): RunManager {
  return new RunManager({
    config: loadConfig({
      root,
      live: true,
      budgets: { fast: 6000, reasoning: 16000, expert: 24000 },
      contextBudgets: { fast: 3600, reasoning: 9600, expert: 14400 },
      concurrency: { fast: 1, reasoning: 1, expert: 1 },
      globalConcurrency: 2
    }),
    runner,
    modelResolver: async () => "fake-model"
  });
}

test("delegate applies a scoped worker patch and cleans up", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-clean");
  const root = path.join(repo, "..", `${path.basename(repo)}-control`);
  const control = manager(repo, root);
  const gitMetadataBefore = await fs.readdir(path.join(repo, ".git"));
  const delegated = await control.delegate({
    repo_root: repo, title: "Add helper", objective: "Create src/example.ts returning 42.",
    current_state: "No helper exists.", target_state: "answer() returns 42.",
    context: "Named exports are preferred.", allowed_paths: ["src/example.ts"], forbidden_paths: [".env"],
    success_criteria: ["answer() returns 42."], test_command: "node -e \"process.exit(0)\"", tier: "fast"
  });
  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.state, "ready_for_review");
  assert.deepEqual(await fs.readdir(path.join(repo, ".git")), gitMetadataBefore);
  await assert.rejects(() => fs.stat(path.join(repo, ".git", "worktrees")), /ENOENT/);
  assert.ok(metadata.report_sha256);
  assert.equal(metadata.routing_decision?.profile, "workhorse");
  assert.equal(metadata.model_attempts?.length, 1);
  const report = await control.report(delegated.run_id);
  assert.equal((report.report as any).report_sha256, metadata.report_sha256);
  const storedResult = JSON.parse(await fs.readFile(path.join(metadata.artifact_path, "result.json"), "utf8"));
  assert.equal(storedResult.structuredOutput?.patch, undefined);
  assert.equal(storedResult.response, undefined);
  await control.apply(delegated.run_id, metadata.report_sha256!);
  assert.match(await fs.readFile(path.join(repo, "src", "example.ts"), "utf8"), /return 42/);
  assert.equal(((await control.report(delegated.run_id)).report as any).summary, "Added helper");
  await assert.rejects(() => control.cancel(delegated.run_id), /Cannot cancel/);
  await control.cleanup(delegated.run_id);
  const retained = await control.report(delegated.run_id);
  assert.equal((retained.metadata as any).state, "applied");
  assert.equal((retained.report as any).summary, "Added helper");
});

test("auto mode uses snapshot for a project nested inside a parent repository", { timeout: 20_000 }, async () => {
  const parent = await createRepo("agy-parent-repo");
  const project = path.join(parent, "nested-project");
  await fs.mkdir(project);
  await fs.writeFile(path.join(project, "README.md"), "nested\n");
  const control = manager(project, path.join(parent, "..", `${path.basename(parent)}-control`));
  const delegated = await control.delegate({
    repo_root: project, title: "Nested task", objective: "Create src/example.ts returning 42.", current_state: "Missing.", target_state: "Exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["exists"], test_command: "node -e \"process.exit(0)\"", tier: "fast",
  });
  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.workspace_mode, "snapshot");
  await assert.rejects(() => fs.stat(path.join(project, ".git")), /ENOENT/);
  await control.apply(delegated.run_id, metadata.report_sha256!);
  await control.cleanup(delegated.run_id);
});

test("auto mode snapshots a Git project instead of exposing tracked sensitive files", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-tracked-secret");
  await fs.writeFile(path.join(repo, ".env"), "TOKEN=must-not-reach-worker\n");
  execFileSync("git", ["add", ".env"], { cwd: repo });
  execFileSync("git", ["commit", "-m", "secret fixture"], { cwd: repo });
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`));
  const delegated = await control.delegate({
    repo_root: repo, title: "Safe task", objective: "Create src/example.ts returning 42.", current_state: "Missing.", target_state: "Exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["exists"], test_command: "node -e \"process.exit(0)\"", tier: "fast",
  });
  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.workspace_mode, "snapshot");
  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, ".env")), /ENOENT/);
  await control.apply(delegated.run_id, metadata.report_sha256!);
  await control.cleanup(delegated.run_id);
});

test("non-Git delegation uses a private snapshot and leaves the original untouched until apply", { timeout: 20_000 }, async () => {
  const project = await createProject("agy-snapshot");
  const control = manager(project, path.join(project, "..", `${path.basename(project)}-control`));
  const delegated = await control.delegate({
    repo_root: project, title: "Add helper", objective: "Create src/example.ts returning 42.",
    current_state: "No helper exists.", target_state: "answer() returns 42.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists"], test_command: "node -e \"process.exit(0)\"", tier: "fast",
  });
  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.workspace_mode, "snapshot");
  await assert.rejects(() => fs.readFile(path.join(project, "src", "example.ts"), "utf8"), /ENOENT/);
  assert.equal(await fs.readFile(path.join(project, "README.md"), "utf8"), "# snapshot project\n");
  await control.apply(delegated.run_id, metadata.report_sha256!);
  assert.match(await fs.readFile(path.join(project, "src", "example.ts"), "utf8"), /return 42/);
  await control.cleanup(delegated.run_id);
});

test("delegation refuses a control state root inside the target before creating any state", async () => {
  const project = await createProject("agy-state-inside-project");
  const stateRoot = path.join(project, ".agy-control-state");
  const control = manager(project, stateRoot);
  await assert.rejects(() => control.delegate({
    repo_root: project, title: "Add helper", objective: "Create src/example.ts returning 42.", current_state: "No helper.", target_state: "Helper exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists"], test_command: "node -e \"process.exit(0)\"", tier: "fast",
  }), /control state must be outside/);
  await assert.rejects(() => fs.stat(stateRoot), /ENOENT/);
});

test("an uncommitted Git directory falls back to a private snapshot", { timeout: 20_000 }, async () => {
  const project = await createProject("agy-no-head");
  execFileSync("git", ["init"], { cwd: project });
  const control = manager(project, path.join(project, "..", `${path.basename(project)}-control`));
  const delegated = await control.delegate({
    repo_root: project, title: "Add helper", objective: "Create src/example.ts returning 42.",
    current_state: "No helper exists.", target_state: "answer() returns 42.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists"], test_command: "node -e \"process.exit(0)\"", tier: "fast",
  });
  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.workspace_mode, "snapshot");
  await assert.rejects(() => fs.readFile(path.join(project, "src", "example.ts"), "utf8"), /ENOENT/);
  await control.cleanup(delegated.run_id).catch(() => undefined);
});

test("a clean Git repository with untracked source files uses a snapshot", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-untracked-source");
  await fs.mkdir(path.join(repo, "src"), { recursive: true });
  await fs.writeFile(path.join(repo, "src", "untracked.ts"), "export const source = true;\n");
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`));
  const delegated = await control.delegate({
    repo_root: repo, title: "Add helper", objective: "Create src/example.ts returning 42.", current_state: "No helper.", target_state: "Helper exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists"], test_command: "node -e \"process.exit(0)\"", tier: "fast",
  });
  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.workspace_mode, "snapshot");
  assert.equal(await fs.readFile(path.join(metadata.worktree_path, "src", "untracked.ts"), "utf8"), "export const source = true;\n");
  await control.apply(delegated.run_id, metadata.report_sha256!);
  await control.cleanup(delegated.run_id);
});

test("a non-Git worker mutation cannot reach the original project", { timeout: 20_000 }, async () => {
  const project = await createProject("agy-snapshot-direct");
  const control = manager(project, path.join(project, "..", `${path.basename(project)}-control`));
  const delegated = await control.delegate({
    repo_root: project, title: "direct-mutation", objective: "Create src/example.ts returning 42.",
    current_state: "No helper exists.", target_state: "answer() returns 42.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists"], test_command: "node -e \"process.exit(0)\"", tier: "fast",
  });
  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.workspace_mode, "snapshot");
  assert.equal(metadata.state, "failed");
  assert.match(metadata.error || "", /modified the isolated worktree directly/);
  await assert.rejects(() => fs.readFile(path.join(project, "src", "example.ts"), "utf8"), /ENOENT/);
  await control.cleanup(delegated.run_id);
});

test("quota exhaustion retries once with the controlled fast-tier fallback", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-quota-fallback");
  const root = path.join(repo, "..", `${path.basename(repo)}-control`);
  const runner = new FakeRunner();
  runner.quotaOnce = true;
  const control = new RunManager({
    config: loadConfig({ root, live: true, modelIds: ["gemini-3.8-flash-high", "claude-opus-4-6-thinking"], concurrency: { fast: 1, reasoning: 1, expert: 1 }, globalConcurrency: 1 }),
    runner,
  });
  const delegated = await control.delegate({
    repo_root: repo, title: "Add helper", objective: "Create src/example.ts returning 42.", current_state: "No helper exists.", target_state: "answer() returns 42.",
    allowed_paths: ["src/example.ts"], success_criteria: ["answer() returns 42."], test_command: "node -e \"process.exit(0)\"", tier: "fast",
  });
  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.state, "ready_for_review");
  assert.equal(metadata.selected_model, "claude-opus-4-6-thinking");
  assert.equal(metadata.fallback_used, true);
  assert.equal(metadata.fallback_reason, "quota_fallback");
  assert.deepEqual(metadata.model_attempts?.map((attempt) => attempt.model), ["gemini-3.8-flash-high", "claude-opus-4-6-thinking"]);
  assert.deepEqual(metadata.model_attempts?.map((attempt) => attempt.trigger), ["primary", "quota_fallback"]);
  await control.cleanup(delegated.run_id).catch(() => undefined);
});

test("outside-scope edits are blocked before apply", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-block");
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`));
  const delegated = await control.delegate({
    repo_root: repo, title: "leak-scope task", objective: "Create src/example.ts but intentionally leak-scope into .env.",
    current_state: "Files absent.", target_state: "Only example.ts should exist.",
    allowed_paths: ["src/example.ts"], forbidden_paths: [".env"],
    success_criteria: ["example.ts exists."], test_command: "node -e \"process.exit(0)\"", tier: "fast"
  });
  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.state, "blocked");
  await assert.rejects(() => control.apply(delegated.run_id, metadata.report_sha256 || ""));
  await control.cleanup(delegated.run_id);
});

test("delegate rejects secret-like material in the executable test contract", async () => {
  const repo = await createRepo("agy-secret-command");
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`));
  await assert.rejects(() => control.delegate({
    repo_root: repo, title: "Task", objective: "Create src/example.ts.", current_state: "Missing.", target_state: "Exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["exists."], test_command: "node -e \"api_key=abcdef1234567890\"", tier: "fast"
  }), /test_command contains secret-like material/);
});

test("automatic delegation accepts deterministic test families and rejects shell composition", async () => {
  const repo = await createRepo("agy-automatic");
  await fs.writeFile(path.join(repo, "package.json"), JSON.stringify({ scripts: { test: "node -e \"process.exit(0)\"" } }));
  execFileSync("git", ["add", "package.json"], { cwd: repo });
  execFileSync("git", ["commit", "-m", "test script"], { cwd: repo });
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`));
  const accepted = await control.delegate({
    repo_root: repo, title: "automatic", objective: "Add a scoped helper.", current_state: "Missing helper.", target_state: "Helper exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists"], test_command: "npm test", delegation_mode: "automatic", tier: "fast",
  });
  assert.equal(((await control.report(accepted.run_id)).metadata as any).delegation_mode, "automatic");
  await assert.rejects(() => control.delegate({
    repo_root: repo, title: "unsafe automatic", objective: "Add a scoped helper.", current_state: "Missing helper.", target_state: "Helper exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists"], test_command: "npm test; curl https://example.invalid", delegation_mode: "automatic", tier: "fast",
  }), /automatic delegation rejects/);
});

test("automatic delegation repairs one deterministic test failure without expanding scope", { timeout: 30_000 }, async () => {
  const repo = await createRepo("agy-automatic-repair");
  await fs.writeFile(path.join(repo, "package.json"), JSON.stringify({
    private: true,
    scripts: {
      test: "node -e \"const fs=require('fs');process.exit(fs.readFileSync('src/example.ts','utf8').includes('42')?0:1)\"",
    },
  }, null, 2));
  execFileSync("git", ["add", "package.json"], { cwd: repo });
  execFileSync("git", ["commit", "-m", "add deterministic test"], { cwd: repo });
  const runner = new RepairRunner();
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`), runner);
  const delegated = await control.delegate({
    repo_root: repo,
    title: "automatic repair",
    objective: "Create src/example.ts whose answer() returns 42.",
    current_state: "The helper is missing.",
    target_state: "The deterministic npm test passes.",
    allowed_paths: ["src/example.ts"],
    success_criteria: ["answer() returns 42", "npm test exits 0"],
    test_command: "npm test",
    delegation_mode: "automatic",
    tier: "fast",
  });
  const metadata = await control.wait(delegated.run_id, 20);
  assert.equal(metadata.state, "ready_for_review", metadata.error);
  assert.equal(runner.jobs.length, 2);
  assert.ok(runner.jobs[1]!.tokenBudget < runner.jobs[0]!.tokenBudget);
  assert.match(runner.jobs[1]!.prompt, /Correct the current isolated implementation/);
  assert.equal(metadata.model_attempts?.length, 2);
  const patch = await control.diff(delegated.run_id) as any;
  assert.match(patch.diff, /return 42/);
  assert.doesNotMatch(patch.diff, /return 41/);
  await control.cleanup(delegated.run_id).catch(() => undefined);
});

test("apply refuses a tracked-dirty repository", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-dirty");
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`));
  const delegated = await control.delegate({
    repo_root: repo, title: "Add helper", objective: "Create src/example.ts returning 42.",
    current_state: "No helper.", target_state: "Helper exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists."], test_command: "node -e \"process.exit(0)\"", tier: "fast"
  });
  const metadata = await control.wait(delegated.run_id, 15);
  await fs.writeFile(path.join(repo, "README.md"), "# dirty\n");
  await assert.rejects(() => control.apply(delegated.run_id, metadata.report_sha256!), /tracked changes/);
  await fs.writeFile(path.join(repo, "README.md"), "# demo\n");
  await control.apply(delegated.run_id, metadata.report_sha256!);
  await control.cleanup(delegated.run_id);
});

test("apply rejects a patch tampered with after review", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-tamper");
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`));
  const delegated = await control.delegate({
    repo_root: repo, title: "Add helper", objective: "Create src/example.ts returning 42.", current_state: "No helper.", target_state: "Helper exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists."], test_command: "node -e \"process.exit(0)\"", tier: "fast"
  });
  const metadata = await control.wait(delegated.run_id, 15);
  const patchPath = path.join(metadata.artifact_path, "patch.diff");
  const original = await fs.readFile(patchPath, "utf8");
  await fs.writeFile(patchPath, `${original}\n# tampered\n`);
  await assert.rejects(() => control.apply(delegated.run_id, metadata.report_sha256!), /Patch was modified/);
  await fs.writeFile(patchPath, original);
  await control.apply(delegated.run_id, metadata.report_sha256!);
  await control.cleanup(delegated.run_id);
});

test("apply rejects persisted metadata tampering before trusting a new destination", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-metadata-tamper");
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`));
  const delegated = await control.delegate({
    repo_root: repo, title: "Add helper", objective: "Create src/example.ts returning 42.", current_state: "No helper.", target_state: "Helper exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists"], test_command: "node -e \"process.exit(0)\"", tier: "fast",
  });
  const metadata = await control.wait(delegated.run_id, 15);
  const metadataPath = path.join(metadata.artifact_path, "metadata.json");
  const original = await fs.readFile(metadataPath, "utf8");
  const tampered = JSON.parse(original) as Record<string, unknown>;
  tampered.repo_root = "/tmp/not-the-original-project";
  await fs.writeFile(metadataPath, JSON.stringify(tampered));
  await assert.rejects(() => control.apply(delegated.run_id, metadata.report_sha256!), /Persisted run metadata was modified|Persisted run paths are invalid/);
  await fs.writeFile(metadataPath, original);
  await control.apply(delegated.run_id, metadata.report_sha256!);
  await control.cleanup(delegated.run_id);
});

test("concurrent apply calls serialize and only one can consume a ready run", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-double-apply");
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`));
  const delegated = await control.delegate({
    repo_root: repo, title: "Add helper", objective: "Create src/example.ts returning 42.", current_state: "No helper.", target_state: "Helper exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists"], test_command: "node -e \"process.exit(0)\"", tier: "fast",
  });
  const metadata = await control.wait(delegated.run_id, 15);
  const outcomes = await Promise.allSettled([
    control.apply(delegated.run_id, metadata.report_sha256!),
    control.apply(delegated.run_id, metadata.report_sha256!),
  ]);
  assert.equal(outcomes.filter((item) => item.status === "fulfilled").length, 1);
  assert.equal(outcomes.filter((item) => item.status === "rejected").length, 1);
  await control.cleanup(delegated.run_id);
});

test("direct AGY worktree mutations are blocked", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-direct");
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`));
  const delegated = await control.delegate({
    repo_root: repo, title: "direct-mutation", objective: "Create src/example.ts returning 42.", current_state: "No helper.", target_state: "Helper exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists."], test_command: "node -e \"process.exit(0)\"", tier: "fast"
  });
  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.state, "failed");
  assert.match(metadata.error || "", /modified the isolated worktree directly/);
  await control.cleanup(delegated.run_id);
});

test("model slugs that encode effort are not combined with a conflicting effort flag", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-model-args");
  const runner = new FakeRunner();
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`), runner);
  const delegated = await control.delegate({
    repo_root: repo, title: "Add helper", objective: "Create src/example.ts returning 42.", current_state: "No helper.", target_state: "Helper exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists."], test_command: "node -e \"process.exit(0)\"", tier: "fast"
  });
  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.state, "ready_for_review");
  assert.ok(runner.jobs[0].args.includes("--model"));
  assert.equal(runner.jobs[0].args.includes("--effort"), false);
  await control.apply(delegated.run_id, metadata.report_sha256!);
  await control.cleanup(delegated.run_id);
});

test("agy_diff paginates by UTF-8 byte offsets without corrupting Unicode", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-unicode-page");
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`));
  const delegated = await control.delegate({
    repo_root: repo, title: "unicode-pagination", objective: "Create a Unicode fixture in src/unicode.ts.", current_state: "No fixture.", target_state: "Fixture exists.",
    allowed_paths: ["src/unicode.ts"], success_criteria: ["fixture exists."], test_command: "node -e \"process.exit(0)\"", tier: "fast"
  });
  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.state, "ready_for_review");
  let offset = 0;
  let reconstructed = "";
  while (true) {
    const page = await control.diff(delegated.run_id, offset, 1024) as any;
    assert.ok(Buffer.byteLength(page.diff, "utf8") <= 1024);
    reconstructed += page.diff;
    offset = page.next_offset;
    if (page.complete) break;
  }
  const actual = await fs.readFile(path.join(metadata.artifact_path, "patch.diff"), "utf8");
  assert.equal(reconstructed, actual);
  await control.apply(delegated.run_id, metadata.report_sha256!);
  await control.cleanup(delegated.run_id);
});

test("shutdown cancels and persists active runs", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-shutdown");
  const runner = new BlockingRunner();
  const control = new RunManager({
    config: loadConfig({ root: path.join(repo, "..", `${path.basename(repo)}-control`), live: true, concurrency: { fast: 1, reasoning: 1, expert: 1 }, globalConcurrency: 1 }),
    runner,
    modelResolver: async () => "gemini-3.7-flash-high"
  });
  const delegated = await control.delegate({
    repo_root: repo, title: "Long task", objective: "Create src/example.ts returning 42.", current_state: "No helper.", target_state: "Helper exists.",
    allowed_paths: ["src/example.ts"], success_criteria: ["helper exists."], test_command: "node -e \"process.exit(0)\"", tier: "fast"
  });
  await runner.started;
  await control.shutdown();
  const reported = await control.report(delegated.run_id);
  assert.equal((reported.metadata as any).state, "cancelled");
  assert.deepEqual(runner.killed, [delegated.run_id]);
  await control.cleanup(delegated.run_id);
});

test("explicit workspace_mode='snapshot' on a clean Git repository uses snapshot mode", { timeout: 20_000 }, async () => {
  const repo = await createRepo("agy-explicit-snap");
  const control = manager(repo, path.join(repo, "..", `${path.basename(repo)}-control`));
  const delegated = await control.delegate({
    repo_root: repo,
    title: "Add helper",
    objective: "Create src/example.ts returning 42.",
    current_state: "No helper exists.",
    target_state: "answer() returns 42.",
    allowed_paths: ["src/example.ts"],
    success_criteria: ["helper exists"],
    test_command: "node -e \"process.exit(0)\"",
    workspace_mode: "snapshot",
    tier: "fast",
  });
  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.workspace_mode, "snapshot");
  assert.ok(metadata.snapshot_baseline);
  assert.ok(metadata.snapshot_fingerprint);
  await control.apply(delegated.run_id, metadata.report_sha256!);
  assert.match(await fs.readFile(path.join(repo, "src", "example.ts"), "utf8"), /return 42/);
  await control.cleanup(delegated.run_id);
});

test("explicit workspace_mode='git' rejects a non-Git directory instead of silently snapshotting", async () => {
  const project = await createProject("agy-reject-git-mode");
  const control = manager(project, path.join(project, "..", `${path.basename(project)}-control`));
  await assert.rejects(
    () => control.delegate({
      repo_root: project,
      title: "Add helper",
      objective: "Create src/example.ts returning 42.",
      current_state: "No helper exists.",
      target_state: "answer() returns 42.",
      allowed_paths: ["src/example.ts"],
      success_criteria: ["helper exists"],
      test_command: "node -e \"process.exit(0)\"",
      workspace_mode: "git",
      tier: "fast",
    }),
    /not a git repository|fatal/i
  );
  // Verify project remains untouched and has no .git
  await assert.rejects(() => fs.stat(path.join(project, ".git")), /ENOENT/);
});

test("snapshot delegation handles modified, newly added, deleted, and nested files, leaving original untouched until apply", { timeout: 20_000 }, async () => {
  const project = await createProject("agy-snap-crud");
  await fs.mkdir(path.join(project, "src"), { recursive: true });
  await fs.writeFile(path.join(project, "src", "existing.ts"), "export const initial = 1;\n");
  await fs.writeFile(path.join(project, "src", "obsolete.ts"), "export const removeMe = true;\n");

  const control = manager(project, path.join(project, "..", `${path.basename(project)}-control`));
  const delegated = await control.delegate({
    repo_root: project,
    title: "CRUD task",
    objective: "Execute snapshot-lifecycle-crud patch.",
    current_state: "existing.ts is 1, obsolete.ts exists, new.ts missing.",
    target_state: "existing.ts is 2, obsolete.ts removed, new.ts added.",
    allowed_paths: ["src/existing.ts", "src/nested/new.ts", "src/obsolete.ts"],
    success_criteria: ["crud operations complete"],
    test_command: "node -e \"process.exit(0)\"",
    tier: "fast",
  });

  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.state, "ready_for_review");
  assert.equal(metadata.workspace_mode, "snapshot");

  // Verify original directory is completely untouched during delegation and has NO .git
  assert.equal(await fs.readFile(path.join(project, "src", "existing.ts"), "utf8"), "export const initial = 1;\n");
  assert.equal(await fs.readFile(path.join(project, "src", "obsolete.ts"), "utf8"), "export const removeMe = true;\n");
  await assert.rejects(() => fs.stat(path.join(project, "src", "nested", "new.ts")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(project, ".git")), /ENOENT/);

  // Apply reviewed patch
  await control.apply(delegated.run_id, metadata.report_sha256!);

  // Verify changes appear in original directory
  assert.equal(await fs.readFile(path.join(project, "src", "existing.ts"), "utf8"), "export const initial = 2;\n");
  assert.equal(await fs.readFile(path.join(project, "src", "nested", "new.ts"), "utf8"), "export const created = true;\n");
  await assert.rejects(() => fs.stat(path.join(project, "src", "obsolete.ts")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(project, ".git")), /ENOENT/);

  // Cleanup removes temporary snapshot worktree but does not damage project
  await control.cleanup(delegated.run_id);
  assert.equal(await fs.readFile(path.join(project, "src", "existing.ts"), "utf8"), "export const initial = 2;\n");
  await assert.rejects(() => fs.stat(metadata.worktree_path), /ENOENT/);
});

test("snapshot delegation excludes dependency, build, cache, and secret directories from private workspace", { timeout: 20_000 }, async () => {
  const project = await createProject("agy-snap-exclusions");
  await fs.mkdir(path.join(project, "src"), { recursive: true });
  await fs.writeFile(path.join(project, "src", "main.ts"), "export const main = true;\n");
  await fs.mkdir(path.join(project, "node_modules", "dep"), { recursive: true });
  await fs.writeFile(path.join(project, "node_modules", "dep", "index.js"), "module.exports = 1;\n");
  await fs.mkdir(path.join(project, "dist"), { recursive: true });
  await fs.writeFile(path.join(project, "dist", "bundle.js"), "bundled\n");
  await fs.mkdir(path.join(project, "dist-test"), { recursive: true });
  await fs.writeFile(path.join(project, "dist-test", "test.js"), "tested\n");
  await fs.mkdir(path.join(project, "build"), { recursive: true });
  await fs.writeFile(path.join(project, "build", "app.js"), "built\n");
  await fs.mkdir(path.join(project, "coverage"), { recursive: true });
  await fs.writeFile(path.join(project, "coverage", "lcov.info"), "coverage\n");
  await fs.mkdir(path.join(project, ".cache"), { recursive: true });
  await fs.writeFile(path.join(project, ".cache", "data.json"), "{}\n");
  await fs.mkdir(path.join(project, ".next"), { recursive: true });
  await fs.writeFile(path.join(project, ".next", "cache.json"), "{}\n");
  await fs.mkdir(path.join(project, "target", "debug"), { recursive: true });
  await fs.writeFile(path.join(project, "target", "debug", "binary"), "bin\n");
  await fs.writeFile(path.join(project, ".env"), "SECRET=true\n");
  await fs.writeFile(path.join(project, ".env.local"), "SECRET_LOCAL=true\n");
  await fs.mkdir(path.join(project, "secrets"), { recursive: true });
  await fs.writeFile(path.join(project, "secrets", "key.txt"), "secret\n");
  await fs.writeFile(path.join(project, "credentials.json"), "{\"auth\": 1}\n");
  await fs.writeFile(path.join(project, "id_rsa"), "private-key\n");

  const control = manager(project, path.join(project, "..", `${path.basename(project)}-control`));
  const delegated = await control.delegate({
    repo_root: project,
    title: "Task",
    objective: "Create src/example.ts returning 42.",
    current_state: "Missing.",
    target_state: "Exists.",
    allowed_paths: ["src/example.ts"],
    success_criteria: ["exists"],
    test_command: "node -e \"process.exit(0)\"",
    tier: "fast",
  });

  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.workspace_mode, "snapshot");

  // Verify snapshot workspace contains src/main.ts and README.md, but none of the excluded directories/files
  assert.ok(await fs.stat(path.join(metadata.worktree_path, "src", "main.ts")));
  assert.ok(await fs.stat(path.join(metadata.worktree_path, "README.md")));

  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, "node_modules")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, "dist")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, "dist-test")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, "build")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, "coverage")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, ".cache")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, ".next")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, "target")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, ".env")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, ".env.local")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, "secrets")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, "credentials.json")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(metadata.worktree_path, "id_rsa")), /ENOENT/);

  await control.cleanup(delegated.run_id).catch(() => undefined);
});

test("stale modified original file blocks agy_apply in snapshot mode", { timeout: 20_000 }, async () => {
  const project = await createProject("agy-snap-stale-mod");
  await fs.mkdir(path.join(project, "src"), { recursive: true });
  await fs.writeFile(path.join(project, "src", "existing.ts"), "export const initial = 1;\n");
  await fs.writeFile(path.join(project, "src", "obsolete.ts"), "export const removeMe = true;\n");

  const control = manager(project, path.join(project, "..", `${path.basename(project)}-control`));
  const delegated = await control.delegate({
    repo_root: project,
    title: "CRUD task",
    objective: "Execute snapshot-lifecycle-crud patch.",
    current_state: "existing.ts is 1, obsolete.ts exists, new.ts missing.",
    target_state: "existing.ts is 2, obsolete.ts removed, new.ts added.",
    allowed_paths: ["src/existing.ts", "src/nested/new.ts", "src/obsolete.ts"],
    success_criteria: ["crud operations complete"],
    test_command: "node -e \"process.exit(0)\"",
    tier: "fast",
  });

  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.state, "ready_for_review");

  // Mutate existing.ts in original project after delegation
  await fs.writeFile(path.join(project, "src", "existing.ts"), "export const initial = 999;\n");

  await assert.rejects(
    () => control.apply(delegated.run_id, metadata.report_sha256!),
    /original file changed: src\/existing\.ts/
  );

  // Restore and apply should succeed
  await fs.writeFile(path.join(project, "src", "existing.ts"), "export const initial = 1;\n");
  await control.apply(delegated.run_id, metadata.report_sha256!);
  await control.cleanup(delegated.run_id);
});

test("newly occupied destination path blocks agy_apply in snapshot mode", { timeout: 20_000 }, async () => {
  const project = await createProject("agy-snap-stale-new");
  await fs.mkdir(path.join(project, "src"), { recursive: true });
  await fs.writeFile(path.join(project, "src", "existing.ts"), "export const initial = 1;\n");
  await fs.writeFile(path.join(project, "src", "obsolete.ts"), "export const removeMe = true;\n");

  const control = manager(project, path.join(project, "..", `${path.basename(project)}-control`));
  const delegated = await control.delegate({
    repo_root: project,
    title: "CRUD task",
    objective: "Execute snapshot-lifecycle-crud patch.",
    current_state: "existing.ts is 1, obsolete.ts exists, new.ts missing.",
    target_state: "existing.ts is 2, obsolete.ts removed, new.ts added.",
    allowed_paths: ["src/existing.ts", "src/nested/new.ts", "src/obsolete.ts"],
    success_criteria: ["crud operations complete"],
    test_command: "node -e \"process.exit(0)\"",
    tier: "fast",
  });

  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.state, "ready_for_review");

  // Create src/nested/new.ts in original project before apply
  await fs.mkdir(path.join(project, "src", "nested"), { recursive: true });
  await fs.writeFile(path.join(project, "src", "nested", "new.ts"), "already here\n");

  await assert.rejects(
    () => control.apply(delegated.run_id, metadata.report_sha256!),
    /new target (?:parent|path) already exists: src\/(?:nested|nested\/new\.ts)/
  );

  // Remove collision and apply should succeed
  await fs.rm(path.join(project, "src", "nested", "new.ts"));
  await fs.rmdir(path.join(project, "src", "nested"));
  await control.apply(delegated.run_id, metadata.report_sha256!);
  await control.cleanup(delegated.run_id);
});

test("failed test or validation in snapshot mode leaves original project untouched", { timeout: 20_000 }, async () => {
  const project = await createProject("agy-snap-failed-test");
  await fs.mkdir(path.join(project, "src"), { recursive: true });
  await fs.writeFile(path.join(project, "src", "app.ts"), "export const original = true;\n");

  const control = manager(project, path.join(project, "..", `${path.basename(project)}-control`));
  const delegated = await control.delegate({
    repo_root: project,
    title: "Failing test task",
    objective: "Create src/example.ts returning 42.",
    current_state: "No helper.",
    target_state: "Helper exists.",
    allowed_paths: ["src/example.ts"],
    success_criteria: ["helper exists"],
    test_command: "node -e \"process.exit(1)\"",
    tier: "fast",
  });

  const metadata = await control.wait(delegated.run_id, 15);
  assert.equal(metadata.state, "failed");

  // Verify original directory is completely untouched and contains no .git
  assert.equal(await fs.readFile(path.join(project, "src", "app.ts"), "utf8"), "export const original = true;\n");
  assert.equal(await fs.readFile(path.join(project, "README.md"), "utf8"), "# snapshot project\n");
  await assert.rejects(() => fs.stat(path.join(project, "src", "example.ts")), /ENOENT/);
  await assert.rejects(() => fs.stat(path.join(project, ".git")), /ENOENT/);

  await control.cleanup(delegated.run_id);
});
