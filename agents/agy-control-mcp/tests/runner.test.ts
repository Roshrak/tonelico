import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { AgyRunner } from "../src/runner.js";

async function withLogs<T>(callback: (directory: string) => Promise<T>): Promise<T> {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "agy-runner-test-"));
  try { return await callback(directory); }
  finally { await fs.rm(directory, { recursive: true, force: true }); }
}

test("runner reconstructs an NDJSON result split across stdout chunks", async () => {
  await withLogs(async (directory) => {
    const event = JSON.stringify({ event: "result", result: { status: "SUCCESS", structured_output: { patch: "diff --git a/a b/a", summary: "ok", confidence: 1, changed_files: [], recommended_action: "ready_for_review" }, usage: { total_tokens: 1 } } }) + "\n";
    const script = `const text=${JSON.stringify(event)};process.stdout.write(text.slice(0,19));setTimeout(()=>process.stdout.write(text.slice(19)),30);`;
    const outcome = await new AgyRunner().run({ runId: "fragmented", command: process.execPath, args: ["-e", script], cwd: process.cwd(), prompt: "ignored", eventLogPath: path.join(directory, "events.ndjson"), stderrLogPath: path.join(directory, "stderr.log"), timeoutSeconds: 5, tokenBudget: 100, maxLogBytes: 4096 });
    assert.equal(outcome.state, "done");
    assert.equal((outcome.structuredOutput as any).summary, "ok");
    const eventLog = await fs.readFile(path.join(directory, "events.ndjson"), "utf8");
    assert.equal(eventLog.includes("diff --git"), false);
    assert.match(eventLog, /patch omitted/);
  });
});

test("runner kills the process tree immediately when the token budget is exceeded", async () => {
  await withLogs(async (directory) => {
    const event = JSON.stringify({ event: "step_update", step_update: { step_index: 1, usage: { output_tokens: 100 } } });
    const survivedPath = path.join(directory, "survived-natural-timeout");
    const script = `const fs=require('fs');console.log(${JSON.stringify(event)});setTimeout(()=>{fs.writeFileSync(${JSON.stringify(survivedPath)},'survived');process.exit(0)},5000);`;
    const outcome = await new AgyRunner().run({ runId: "budget", command: process.execPath, args: ["-e", script], cwd: process.cwd(), prompt: "ignored", eventLogPath: path.join(directory, "events.ndjson"), stderrLogPath: path.join(directory, "stderr.log"), timeoutSeconds: 10, tokenBudget: 10, maxLogBytes: 4096 });
    assert.equal(outcome.failureReason, "budget_exceeded");
    await assert.rejects(() => fs.access(survivedPath), /ENOENT/);
  });
});

test("runner enforces follow-up budgets using cumulative usage deltas", async () => {
  await withLogs(async (directory) => {
    const cumulative = { input_tokens: 1200, output_tokens: 800, thinking_tokens: 700, cache_read_tokens: 600, total_tokens: 2700 };
    const event = JSON.stringify({ event: "result", result: { conversation_id: "conversation", status: "SUCCESS", structured_output: { patch: "diff", summary: "ok", confidence: 1, changed_files: [], recommended_action: "ready_for_review" }, usage: cumulative } }) + "\n";
    const script = `process.stdout.write(${JSON.stringify(event)});`;
    const outcome = await new AgyRunner().run({
      runId: "delta", command: process.execPath, args: ["-e", script], cwd: process.cwd(), prompt: "ignored",
      eventLogPath: path.join(directory, "events.ndjson"), stderrLogPath: path.join(directory, "stderr.log"), timeoutSeconds: 5, tokenBudget: 600, maxLogBytes: 4096,
      conversationId: "conversation", conversationUsageBaseline: { input_tokens: 1000, output_tokens: 500, thinking_tokens: 500, cache_read_tokens: 400, total_tokens: 2000 }
    });
    assert.equal(outcome.state, "done");
    assert.deepEqual(outcome.usage, { input_tokens: 200, output_tokens: 300, thinking_tokens: 200, cache_read_tokens: 200, total_tokens: 700 });
    assert.deepEqual(outcome.conversationUsage, cumulative);
  });
});
