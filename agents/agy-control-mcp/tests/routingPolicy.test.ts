import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";

test("repository guidance and routing skill require automatic AGY only for eligible work", async () => {
  const [guidance, skill] = await Promise.all([
    fs.readFile(path.resolve("AGENTS.md"), "utf8"),
    fs.readFile(path.resolve(".agents", "skills", "agy-control-worker", "SKILL.md"), "utf8"),
  ]);
  assert.match(guidance, /delegation_mode="automatic"/);
  assert.match(guidance, /agy_apply.*explicit user approval/i);
  assert.match(skill, /nontrivial bounded implementation/i);
  assert.match(skill, /tiny edit/i);
  assert.match(skill, /clinical|mastery/i);
  assert.match(skill, /Do not wrap AGY in a native Codex subagent/i);
  assert.match(skill, /gemini-3\.8-flash-high/);
  const studySkill = await fs.readFile(path.resolve(".agents", "skills", "study-herd", "SKILL.md"), "utf8");
  assert.match(studySkill, /Do not load this skill for generic software implementation/i);
});

test("multiclient smoke keeps the release gate at twenty rounds by default", async () => {
  const smoke = await fs.readFile(path.resolve("scripts", "mcp-multiclient-smoke.mjs"), "utf8");
  assert.match(smoke, /AGY_MULTICLIENT_ROUNDS \|\| 20/);
  assert.match(smoke, /AGY_CONTROL_STATUS_SKIP_DISCOVERY/);
  assert.match(smoke, /instance_ids/);
});
