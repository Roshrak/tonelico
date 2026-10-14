import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { loadConfig } from "../src/config.js";
import { CapacityWaitTimeout } from "../src/capacityController.js";
import { TaskOrchestrator, type WorkflowExecutionContext, type WorkflowTaskExecutor, type WorkflowTaskResult } from "../src/orchestrator.js";
import type { RunManager } from "../src/runManager.js";

function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, milliseconds);
    const abort = () => { clearTimeout(timer); reject(new Error("cancelled")); };
    if (signal.aborted) abort(); else signal.addEventListener("abort", abort, { once: true });
  });
}

class FakeExecutor implements WorkflowTaskExecutor {
  active = 0;
  peak = 0;
  calls = new Map<string, number>();

  capabilities(): Record<string, unknown> { return { task_kinds: ["analysis", "research", "validation", "testing"], structured_results: true }; }

  async execute(task: { task_id: string; objective: string; attempts: number }, context: WorkflowExecutionContext): Promise<WorkflowTaskResult> {
    this.active += 1; this.peak = Math.max(this.peak, this.active); this.calls.set(task.task_id, (this.calls.get(task.task_id) || 0) + 1);
    try {
      context.reportProgress(25, "working");
      await delay(task.objective.includes("slow") ? 250 : 30, context.signal);
      if (task.objective.includes("flaky") && task.attempts === 1) return { status: "failed", summary: "transient worker error", retryable: true };
      return { status: "succeeded", summary: `${task.task_id} complete`, detailed_output: JSON.stringify({ dependencies: Object.keys(context.dependency_results) }), confidence: 0.9, usage: { input_tokens: 10, output_tokens: 5, total_tokens: 15 } };
    } finally { this.active -= 1; }
  }

  async cancel(): Promise<void> {}
}

function managerStub(): RunManager { return {} as RunManager; }

test("workflow runs independent tasks in parallel, then respects dependencies and aggregates results", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-orchestrator-"));
  const executor = new FakeExecutor();
  const config = loadConfig({ root, orchestrationMaxTasks: 8, orchestrationMaxParallel: 2, orchestrationMaxDepth: 3, orchestrationMaxAttempts: 3 });
  const orchestrator = new TaskOrchestrator(managerStub(), { config, executor });
  const started = await orchestrator.start({ repo_root: root, title: "parallel graph", tasks: [
    { task_id: "a", kind: "analysis", title: "A", objective: "independent A" },
    { task_id: "b", kind: "research", title: "B", objective: "independent B" },
    { task_id: "c", kind: "validation", title: "C", objective: "after dependencies", depends_on: ["a", "b"] },
  ] });
  const finished = await orchestrator.wait(String(started.workflow_id), 10);
  assert.equal(finished.state, "succeeded");
  assert.equal(executor.peak, 2);
  const report = await orchestrator.report(String(started.workflow_id));
  assert.equal((report.aggregate as any).succeeded, 3);
  assert.match(String((report.task_results as any).c.result.detailed_output), /a.*b|b.*a/);
  const stored = await fs.stat(path.join(root, "orchestration", "workflows", `${started.workflow_id}.json`));
  assert.ok(stored.isFile());
  await orchestrator.shutdown();
});

test("workflow supports retries, dynamic child tasks, priorities, and cycle safeguards", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-orchestrator-"));
  const executor = new FakeExecutor();
  const config = loadConfig({ root, orchestrationMaxTasks: 8, orchestrationMaxParallel: 1, orchestrationMaxDepth: 2, orchestrationMaxAttempts: 3 });
  const orchestrator = new TaskOrchestrator(managerStub(), { config, executor });
  const started = await orchestrator.start({ repo_root: root, title: "recovery graph", tasks: [{ task_id: "flaky", kind: "analysis", title: "Flaky", objective: "flaky", max_attempts: 2 }] });
  const added = await orchestrator.addTasks({ workflow_id: String(started.workflow_id), parent_task_id: "flaky", tasks: [{ task_id: "child", kind: "testing", title: "Child", objective: "child", depends_on: ["flaky"], priority: 10 }] });
  assert.deepEqual(added.added_task_ids, ["child"]);
  const finished = await orchestrator.wait(String(started.workflow_id), 10);
  assert.equal(finished.state, "succeeded");
  assert.equal(executor.calls.get("flaky"), 2);
  await assert.rejects(() => orchestrator.start({ repo_root: root, title: "cycle", tasks: [
    { task_id: "x", kind: "analysis", title: "X", objective: "x", depends_on: ["y"] },
    { task_id: "y", kind: "analysis", title: "Y", objective: "y", depends_on: ["x"] },
  ] }), /cycle/i);
  await orchestrator.shutdown();
});

test("workflow cancellation aborts active work without affecting persisted control state", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-orchestrator-"));
  const executor = new FakeExecutor();
  const config = loadConfig({ root, orchestrationMaxTasks: 4, orchestrationMaxParallel: 1, orchestrationMaxDepth: 1, orchestrationMaxAttempts: 2 });
  const orchestrator = new TaskOrchestrator(managerStub(), { config, executor });
  const started = await orchestrator.start({ repo_root: root, title: "cancel graph", tasks: [{ task_id: "slow", kind: "analysis", title: "Slow", objective: "slow work" }] });
  await delay(20, new AbortController().signal);
  const cancelled = await orchestrator.cancel(String(started.workflow_id));
  assert.equal(cancelled.state, "cancelled");
  const report = await orchestrator.report(String(started.workflow_id));
  assert.equal((report.task_results as any).slow.state, "cancelled");
  await orchestrator.shutdown();
});

test("a capacity wait timeout requeues the task without spending its attempt budget", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-orchestrator-"));
  class BusyThenFreeExecutor extends FakeExecutor {
    override async execute(task: { task_id: string; objective: string; attempts: number }, context: WorkflowExecutionContext): Promise<WorkflowTaskResult> {
      if ((this.calls.get(task.task_id) || 0) === 0) {
        this.calls.set(task.task_id, 1);
        throw new CapacityWaitTimeout("Timed out waiting for shared reasoning capacity");
      }
      return super.execute(task, context);
    }
  }
  const executor = new BusyThenFreeExecutor();
  const config = loadConfig({ root, orchestrationMaxTasks: 4, orchestrationMaxParallel: 1, orchestrationMaxDepth: 2, orchestrationMaxAttempts: 1 });
  const orchestrator = new TaskOrchestrator(managerStub(), { config, executor });
  const started = await orchestrator.start({ repo_root: root, title: "busy tier", tasks: [{ task_id: "busy", kind: "analysis", title: "Busy", objective: "busy", max_attempts: 1 }] });
  const finished = await orchestrator.wait(String(started.workflow_id), 10);
  assert.equal(finished.state, "succeeded");
  assert.equal(executor.calls.get("busy"), 2);
  await orchestrator.shutdown();
});

test("a failed task always records why it failed", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-orchestrator-"));
  class SilentFailureExecutor extends FakeExecutor {
    override async execute(): Promise<WorkflowTaskResult> {
      return { status: "failed", summary: "" };
    }
  }
  const config = loadConfig({ root, orchestrationMaxTasks: 4, orchestrationMaxParallel: 1, orchestrationMaxDepth: 2, orchestrationMaxAttempts: 1 });
  const orchestrator = new TaskOrchestrator(managerStub(), { config, executor: new SilentFailureExecutor() });
  const started = await orchestrator.start({ repo_root: root, title: "silent failure", tasks: [{ task_id: "silent", kind: "analysis", title: "Silent", objective: "silent" }] });
  const finished = await orchestrator.wait(String(started.workflow_id), 10);
  assert.equal(finished.state, "failed");
  const report = await orchestrator.report(String(started.workflow_id));
  assert.match(String((report.task_results as any).silent.last_error), /without a reason/);
  await orchestrator.shutdown();
});

test("a task that never gets AGY capacity fails after a bounded number of waits", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-orchestrator-"));
  class SaturatedExecutor extends FakeExecutor {
    override async execute(): Promise<WorkflowTaskResult> {
      this.calls.set("saturated", (this.calls.get("saturated") || 0) + 1);
      throw new CapacityWaitTimeout("Timed out waiting for shared reasoning capacity");
    }
  }
  const executor = new SaturatedExecutor();
  const config = loadConfig({ root, orchestrationMaxTasks: 4, orchestrationMaxParallel: 1, orchestrationMaxDepth: 2, orchestrationMaxAttempts: 1 });
  const orchestrator = new TaskOrchestrator(managerStub(), { config, executor });
  const started = await orchestrator.start({ repo_root: root, title: "saturated", tasks: [{ task_id: "saturated", kind: "analysis", title: "Saturated", objective: "saturated", max_attempts: 1 }] });
  const finished = await orchestrator.wait(String(started.workflow_id), 90);
  assert.equal(finished.state, "failed");
  assert.ok((executor.calls.get("saturated") || 0) <= 21, "capacity waits must be bounded");
  await orchestrator.shutdown();
});
