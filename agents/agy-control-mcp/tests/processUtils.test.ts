import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import path from "node:path";
import test from "node:test";
import { execCommand } from "../src/processUtils.js";

test("execCommand terminates commands that exceed the output budget", async () => {
  await assert.rejects(
    () => execCommand(process.execPath, ["-e", "process.stdout.write('x'.repeat(20000))"], { timeout: 5_000, maxOutputBytes: 1_024 }),
    /output exceeded 1024 bytes/
  );
});

test("Windows executable resolution does not recursively resolve where.exe", async (t) => {
  if (!process.platform.startsWith("win")) return t.skip("Windows-specific executable resolution");
  const result = await execCommand("where.exe", ["git"], { timeout: 5_000 });
  assert.match(result.stdout, /git(?:\.exe)?/i);
});

test("Windows resolver ignores a same-directory git.js PATHEXT candidate", async (t) => {
  if (!process.platform.startsWith("win")) return t.skip("Windows-specific executable resolution");
  const previousCwd = process.cwd();
  // Compiled source lives beside git.js, exactly like the stdio MCP process.
  const sourceDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src");
  process.chdir(sourceDirectory);
  try {
    const result = await execCommand("git", ["--version"], { timeout: 5_000 });
    assert.match(result.stdout, /^git version /i);
  } finally {
    process.chdir(previousCwd);
  }
});
