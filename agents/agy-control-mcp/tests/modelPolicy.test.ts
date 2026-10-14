import assert from "node:assert/strict";
import test from "node:test";
import { AUTOMATIC_MODEL_IDS, classifyImplementation, documentAutoTier, isDisallowedGemini37Effort, MODEL_ROUTING_POLICY_VERSION, selectModel, TIER_CANDIDATES } from "../src/modelPolicy.js";
import { validateTaskObject } from "../src/studyValidation.js";

test("automatic tier policy uses Gemini 3.8 Flash High by default and Claude for expert work", () => {
  assert.deepEqual(TIER_CANDIDATES, {
    fast: ["gemini-3.8-flash-high", "claude-opus-4-6-thinking"],
    reasoning: ["gemini-3.8-flash-high", "claude-opus-4-6-thinking"],
    expert: ["claude-opus-4-6-thinking", "gemini-3.8-flash-high"],
  });
  const available = new Set(AUTOMATIC_MODEL_IDS);
  assert.deepEqual(["fast", "reasoning", "expert"].map((tier) => selectModel(tier as "fast" | "reasoning" | "expert", available)?.model), ["gemini-3.8-flash-high", "gemini-3.8-flash-high", "claude-opus-4-6-thinking"]);
  assert.ok(AUTOMATIC_MODEL_IDS.every((model) => !isDisallowedGemini37Effort(model)));
  assert.equal(MODEL_ROUTING_POLICY_VERSION, "model-routing-v4");
});

test("controlled fallback stays within Gemini 3.8 High and Claude Opus", () => {
  const fast = selectModel("fast", new Set(["claude-opus-4-6-thinking"]));
  const reasoning = selectModel("reasoning", new Set(["claude-opus-4-6-thinking"]));
  const expert = selectModel("expert", new Set(["gemini-3.8-flash-high"]));
  assert.deepEqual([fast?.model, reasoning?.model, expert?.model], ["claude-opus-4-6-thinking", "claude-opus-4-6-thinking", "gemini-3.8-flash-high"]);
  assert.ok([fast, reasoning, expert].every((selection) => selection?.fallback_used));
});

test("implementation routing profiles distinguish workhorse, deep reasoning, and high-risk debugging", () => {
  assert.equal(classifyImplementation({ title: "Fix form validation", objective: "Correct the component and test", target_state: "Test passes", allowed_paths: ["src/form.ts", "tests/form.test.ts"] }).tier, "fast");
  assert.equal(classifyImplementation({ title: "Migrate schema", objective: "Plan a database schema migration", target_state: "Compatibility preserved", allowed_paths: ["src/db.ts"] }).tier, "reasoning");
  assert.equal(classifyImplementation({ title: "Fix race", objective: "Reproduce a concurrency deadlock", target_state: "No data corruption", allowed_paths: ["src/queue.ts"] }).tier, "expert");
  assert.equal(classifyImplementation({ title: "Routine refactor", objective: "Rename bounded modules", target_state: "Tests pass", allowed_paths: Array.from({ length: 8 }, (_, index) => `src/${index}.ts`) }).tier, "reasoning");
});

test("document routing reserves expert escalation and classifies clerical work deterministically", () => {
  assert.equal(documentAutoTier("locator-map", 3000, 10, 1).tier, "fast");
  assert.equal(documentAutoTier("coverage-check", 1000, 1, 1).tier, "reasoning");
  assert.equal(documentAutoTier("table-normalize", 3000, 10, 2).tier, "reasoning");
  assert.equal(documentAutoTier("field-extract", 4001, 10, 1).tier, "reasoning");
});

test("legacy Study Herd task rejects Gemini 3.7 low and medium overrides", () => {
  for (const model of ["gemini-3.7-flash-low", "gemini-3.7-flash-medium"]) {
    const result = validateTaskObject({ task_id: "worker", role: "source-clerk", input_bundle: "inputs/source.md", scope: { source_id: "slide" }, acceptance: ["Grounded"], worker_model: model });
    assert.equal(result.valid, false);
    assert.ok(result.errors.includes("model_effort_not_allowed"));
  }
});
