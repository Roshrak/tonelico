import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { loadConfig } from "../src/config.js";
import { discoverModels } from "../src/modelCatalog.js";

test("default budgets leave room for current AGY fast-model output and thinking", () => {
  const config = loadConfig();
  assert.deepEqual(config.budgets, { fast: 14000, reasoning: 24000, expert: 36000 });
});

test("budget environment overrides persistently raise AGY tier defaults", () => {
  const previous = {
    fast: process.env.AGY_CONTROL_FAST_BUDGET,
    reasoning: process.env.AGY_CONTROL_REASONING_BUDGET,
    expert: process.env.AGY_CONTROL_EXPERT_BUDGET
  };
  process.env.AGY_CONTROL_FAST_BUDGET = "42000";
  process.env.AGY_CONTROL_REASONING_BUDGET = "72000";
  process.env.AGY_CONTROL_EXPERT_BUDGET = "100000";
  try {
    assert.deepEqual(loadConfig().budgets, { fast: 42000, reasoning: 72000, expert: 100000 });
  } finally {
    for (const [name, value] of Object.entries({
      AGY_CONTROL_FAST_BUDGET: previous.fast,
      AGY_CONTROL_REASONING_BUDGET: previous.reasoning,
      AGY_CONTROL_EXPERT_BUDGET: previous.expert
    })) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
});

test("configured AGY model IDs provide a full non-interactive catalogue", async () => {
  const models = await discoverModels("unused", ["gemini-3.7-flash-high", "claude-opus-4-6-thinking"]);
  assert.deepEqual(models, [
    { id: "gemini-3.7-flash-high", tier: "fast" },
    { id: "claude-opus-4-6-thinking", tier: "expert" }
  ]);
});

test("model discovery uses the full catalogue instead of the selected model", { skip: process.platform === "win32" }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "agy-models-"));
  const command = path.join(directory, "agy-fake");
  try {
    await writeFile(command, `#!${process.execPath}\nif (process.argv[2] !== "models") process.exit(2);\nprocess.stdout.write("Fetching available models...\\ngemini-3.8-flash-high\\tCurrent\\ngemini-3.7-flash-high\\tFast\\ngemini-3.1-pro-high\\tReasoning\\n");\n`, { mode: 0o700 });
    assert.deepEqual(await discoverModels(command), [
      { id: "gemini-3.8-flash-high", tier: "fast" },
      { id: "gemini-3.7-flash-high", tier: "fast" },
      { id: "gemini-3.1-pro-high", tier: "reasoning" }
    ]);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
