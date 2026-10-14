import assert from "node:assert/strict";
import test from "node:test";
import { compileFollowUpPrompt, compileWorkerPrompt, PromptValidationError } from "../src/promptCompiler.js";

const validTask = {
  title: "Add helper",
  objective: "Create src/example.ts exporting answer() as number 42.",
  current_state: "src/example.ts does not exist.",
  target_state: "src/example.ts exports answer() returning 42.",
  context: "Existing style uses named exports.\nUnrelated line that should be retained when relevant.",
  allowed_paths: ["src/example.ts"],
  forbidden_paths: ["package.json"],
  success_criteria: ["node -e \"import('./src/example.ts').then(m => m.answer())\" exits zero."],
  test_command: "node -e \"process.exit(0)\"",
  mode: "implement" as const
};

test("implementer prompt has a front-loaded safety contract", () => {
  const compiled = compileWorkerPrompt(validTask, { tier: "fast", contextBudgetTokens: 1000 });
  assert.ok(compiled.prompt.startsWith("SAFETY CONTRACT"));
  assert.ok(compiled.prompt.indexOf("Allowed paths") < compiled.prompt.indexOf("# Objective"));
  assert.match(compiled.prompt, /MUST satisfy: node -e/);
  assert.match(compiled.prompt, /recommended_action/);
});

test("vague tasks are rejected with bounded clarification questions", () => {
  assert.throws(() => compileWorkerPrompt({ ...validTask, objective: "make it better" }, { tier: "fast", contextBudgetTokens: 1000 }), (error: unknown) => {
    assert.ok(error instanceof PromptValidationError);
    assert.ok(error.questions.length > 0 && error.questions.length <= 3);
    return true;
  });
});

test("secrets are redacted from inert context", () => {
  const compiled = compileWorkerPrompt({
    ...validTask,
    context: "api_key=abcdef1234567890\nUse this configuration."
  }, { tier: "fast", contextBudgetTokens: 1000 });
  assert.ok(!compiled.prompt.includes("abcdef1234567890"));
  assert.deepEqual(compiled.audit.redactions, ["api_key"]);
});

test("oversized context is relevance-truncated", () => {
  const lines = Array.from({ length: 500 }, (_, index) => `unrelated ${index} ${index % 20 === 0 ? "example.ts" : "noise"}`);
  const compiled = compileWorkerPrompt({ ...validTask, context: lines.join("\n") }, { tier: "fast", contextBudgetTokens: 50 });
  assert.equal(compiled.audit.truncated_context, true);
  assert.match(compiled.prompt, /Context was relevance-truncated/);
});

test("follow-up prompt keeps scope and correction contract", () => {
  const compiled = compileFollowUpPrompt({
    run_id: "run",
    requested_correction: "Change the returned constant to 43 only in src/example.ts.",
    failing_tests_or_logs: "expected 42 received 41",
    unchanged_allowed_paths: ["src/example.ts"],
    current_success_criteria: ["answer() returns 43."]
  }, { tier: "fast", contextBudgetTokens: 1000 });
  assert.match(compiled.prompt, /ONLY paths src\/example\.ts remain in scope/);
  assert.match(compiled.prompt, /Requested Correction/);
});

test("follow-up redacts secrets before returning the prompt", () => {
  const secret = "abcdef1234567890";
  const compiled = compileFollowUpPrompt({
    run_id: "run", requested_correction: "Fix the test failure.", failing_tests_or_logs: `api_key=${secret}`,
    unchanged_allowed_paths: ["src/example.ts"], current_success_criteria: ["answer() returns 42."]
  }, { tier: "fast", contextBudgetTokens: 1000 });
  assert.ok(!compiled.prompt.includes(secret));
  assert.deepEqual(compiled.audit.redactions, ["api_key"]);
});
