import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { AntigravityClerkRunner, type DoctorReport, type ProcessResult, type WorkerProcess } from "../src/studyRunner.js";

async function temporaryDirectory(): Promise<string> {
  return await fs.mkdtemp(path.join(os.tmpdir(), "agy-study-runner-"));
}

function validResult(): Record<string, unknown> {
  return {
    status: "done", role: "source-clerk", scope_echo: { source_id: "slide-noninfectious", pages: [1, 13] },
    items: [{ id: "claim-1", text: "Candidate fact", locator: { source_id: "slide-noninfectious", page: 4 }, confidence: "medium" }],
    coverage: { expected: 1, covered: 1, missing: [] }, uncertainties: [], violations: [],
  };
}

class ReadyRunner extends AntigravityClerkRunner {
  constructor(runProcess: WorkerProcess) { super(runProcess); }
  async doctor(): Promise<DoctorReport> {
    return { installed: true, ready: true, reason: null, path: "agy", capabilities: {} };
  }
}

test("bounded clerk retries one transient failure, validates provenance, and audits attempts", async () => {
  const root = await temporaryDirectory();
  const workDirectory = path.join(root, ".study-work", "run-retry");
  const inputPath = path.join(workDirectory, "inputs", "source.md");
  await fs.mkdir(path.dirname(inputPath), { recursive: true });
  await fs.writeFile(inputPath, "Bounded source", "utf8");
  const taskPath = path.join(workDirectory, "task.json");
  await fs.writeFile(taskPath, JSON.stringify({
    task_id: "worker-1", role: "source-clerk", input_bundle: "inputs/source.md",
    scope: { source_id: "slide-noninfectious", pages: [1, 13] },
    acceptance: ["Extract only source-grounded claims."], worker_model: null,
  }), "utf8");
  let calls = 0;
  let sawPrompt = false;
  const runner = new ReadyRunner(async (command): Promise<ProcessResult> => {
    calls += 1;
    sawPrompt = sawPrompt || command.some((argument) => argument.includes("BEGIN UNTRUSTED SOURCE BUNDLE"));
    if (calls === 1) return { stdout: "", stderr: "temporary failure" };
    return { stdout: JSON.stringify({ status: "SUCCESS", structured_output: validResult() }), stderr: "" };
  });
  const result = await runner.run(taskPath, { work_dir: workDirectory, timeout_seconds: 30, max_retries: 1 });
  assert.equal(result.status, "done");
  assert.equal(calls, 2);
  assert.equal(sawPrompt, true);
  const audit = JSON.parse(await fs.readFile(path.join(workDirectory, "worker-run.json"), "utf8"));
  assert.equal(audit.attempt_count, 2);
  assert.equal(audit.worker_model, "gemini-3.8-flash-high");
});

test("bounded clerk refuses outside work directories without launching or creating them", async () => {
  const root = await temporaryDirectory();
  const taskHost = path.join(root, ".study-work", "task-host");
  await fs.mkdir(taskHost, { recursive: true });
  const taskPath = path.join(taskHost, "task.json");
  await fs.writeFile(taskPath, JSON.stringify({
    task_id: "worker-1", role: "source-clerk", input_bundle: "inputs/source.md",
    scope: { source_id: "slide" }, acceptance: ["Grounded"], worker_model: null,
  }), "utf8");
  const externalDirectory = path.join(root, "must-not-be-created");
  const runner = new ReadyRunner(async () => {
    throw new Error("subprocess must not run outside .study-work");
  });
  await assert.rejects(() => runner.run(taskPath, { work_dir: externalDirectory }), /inside a \.study-work directory/);
  await assert.rejects(() => fs.stat(externalDirectory), /ENOENT/);
});

test("bounded clerk rejects bundle escape and reversed page scope before launch", async () => {
  const root = await temporaryDirectory();
  const outsidePath = path.join(root, "outside.txt");
  await fs.writeFile(outsidePath, "outside", "utf8");
  const workDirectory = path.join(root, ".study-work", "escape");
  await fs.mkdir(workDirectory, { recursive: true });
  const escapedTaskPath = path.join(workDirectory, "task.json");
  await fs.writeFile(escapedTaskPath, JSON.stringify({
    task_id: "worker-escape", role: "source-clerk", input_bundle: outsidePath,
    scope: { source_id: "slide" }, acceptance: ["Grounded"],
  }), "utf8");
  const runner = new ReadyRunner(async () => {
    throw new Error("subprocess must not launch for an escaped bundle");
  });
  await assert.rejects(() => runner.run(escapedTaskPath, { work_dir: workDirectory }), /must stay inside its work directory/);
  const reversedPath = path.join(workDirectory, "reversed.json");
  await fs.writeFile(reversedPath, JSON.stringify({
    task_id: "worker-reversed", role: "source-clerk", input_bundle: "inputs/source.md",
    scope: { source_id: "slide", pages: [13, 1] }, acceptance: ["Grounded"],
  }), "utf8");
  await assert.rejects(() => runner.run(reversedPath, { work_dir: workDirectory }), /ascending order/);
});
