import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";

test("installer fails before node_modules mutation when a live MCP can lock native addons", async () => {
  const script = await fs.readFile(path.resolve("scripts", "install-codex.ps1"), "utf8");
  assert.match(script, /Active agy-control MCP process/);
  assert.match(script, /Invoke-Checked "npm ci"/);
  assert.match(script, /required = true/);
  assert.match(script, /AGY_CONTROL_LIVE = "1"/);
  assert.match(script, /AGY_CONTROL_BUILD_COMMIT/);
  assert.match(script, /gemini-3\.8-flash-high/);
  assert.doesNotMatch(script, /gemini-3\.7-flash-low",\s*"gemini-3\.7-flash-medium/);
  for (const tool of ["agy_capabilities", "agy_workflow_start", "agy_workflow_report", "agy_workflow_cancel", "agy_evidence_read", "agy_evidence_search", "agy_study_session_start", "agy_study_session_resume", "agy_study_preflight"]) {
    assert.match(script, new RegExp(`enabled_tools = \\[[^\\r\\n]*"${tool}"`));
  }
  assert.match(script, /\[string\]\$existingGuidance = ""/);
  assert.ok(script.indexOf("Active agy-control MCP process") < script.indexOf("Invoke-Checked \"npm ci\""));
});

test("MCP probe forwards model policy for doctor validation", async () => {
  const probe = await fs.readFile(path.resolve("scripts", "mcp-probe.mjs"), "utf8");
  assert.match(probe, /model_policy:\s*status\.model_policy/);
  const doctor = await fs.readFile(path.resolve("scripts", "doctor.ps1"), "utf8");
  assert.match(doctor, /MCP probe did not report model routing policy/);
});
