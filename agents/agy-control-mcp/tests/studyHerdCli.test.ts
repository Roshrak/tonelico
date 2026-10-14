import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const cliPath = path.resolve("dist-test/src/studyHerdCli.js");

async function temporaryDirectory(): Promise<string> {
  return await fs.mkdtemp(path.join(os.tmpdir(), "agy-study-cli-"));
}

async function run(args: string[]): Promise<{ stdout: string; code: number }> {
  try {
    const result = await execFileAsync(process.execPath, [cliPath, ...args], { encoding: "utf8", timeout: 15000 });
    return { stdout: result.stdout, code: 0 };
  } catch (error) {
    const failure = error as { stdout?: string; code?: number };
    return { stdout: failure.stdout || "", code: typeof failure.code === "number" ? failure.code : 1 };
  }
}

test("compatibility CLI handles Unicode index, forbidden topics, and learner attempts", async () => {
  const directory = await temporaryDirectory();
  const sourcePath = path.join(directory, "Bài giảng.md");
  await fs.writeFile(sourcePath, "# Đại cương\nNội dung cơ chế", "utf8");
  const manifestPath = path.join(directory, "sources.yaml");
  await fs.writeFile(manifestPath, ["subject: oral-medicine", "sources:", "  - id: lecture", "    kind: lecture-transcript", `    path: '${sourcePath.replace(/\\/g, "\\\\")}'`, ""].join("\n"), "utf8");
  const indexPath = path.join(directory, "index.json");
  const indexed = await run(["index", manifestPath, "--output", indexPath]);
  assert.equal(indexed.code, 0);
  const parsedIndex = JSON.parse(await fs.readFile(indexPath, "utf8"));
  assert.equal(parsedIndex.included_sources[0].status, "indexed");
  parsedIndex.included_sources[0].page_previews = [];
  assert.match(indexed.stdout, /"indexed": 1/u);

  for (let page = 1; page <= 33; page += 1) parsedIndex.included_sources[0].page_previews.push(`Page ${page}`);
  parsedIndex.included_sources[0].page_count = 33;
  await fs.writeFile(indexPath, JSON.stringify(parsedIndex), "utf8");
  const scopePath = path.join(directory, "scope.json");
  const scoped = await run(["scope", indexPath, "--source-id", "lecture", "--pages", "1:13", "--topic", "RAS", "--forbidden-topic", "liệt mặt", "--output", scopePath]);
  assert.equal(scoped.code, 0);
  const draftPath = path.join(directory, "draft.md");
  await fs.writeFile(draftPath, "Phần này lạc sang liệt mặt.", "utf8");
  const rejected = await run(["validate-scope", scopePath, "--source-index", indexPath, "--draft-file", draftPath]);
  assert.equal(rejected.code, 2);
  assert.match(rejected.stdout, /Draft mentions forbidden topic: liệt mặt/u);

  const conceptsPath = path.join(directory, "concepts.json");
  await fs.writeFile(conceptsPath, JSON.stringify({ concepts: [{ id: "ras", label: "RAS", tier: "A" }] }), "utf8");
  const attemptsPath = path.join(directory, "attempts.jsonl");
  const progressPath = path.join(directory, "progress.json");
  const recorded = await run([
    "record-attempt", "--concepts", conceptsPath, "--attempts", attemptsPath, "--progress-output", progressPath,
    "--concept-id", "ras", "--difficulty", "clinical", "--context", "case-1", "--reasoning", "sound", "--correct",
    "--occurred-at", "2026-08-20T10:00:00+07:00",
  ]);
  assert.equal(recorded.code, 0);
  const progress = JSON.parse(await fs.readFile(progressPath, "utf8"));
  assert.equal(progress.concepts[0].status, "working");
});

test("doctor reports a commander-only fallback when AGY is unavailable", async () => {
  const result = await run(["doctor"]);
  assert.equal(result.code, 0);
  const report = JSON.parse(result.stdout) as { worker_mode?: string; runtimes?: { antigravity?: { ready?: boolean } } };
  assert.equal(report.worker_mode, "commander-only");
  assert.equal(report.runtimes?.antigravity?.ready, false);
});

test("compatibility CLI emits structured errors for unknown commands", async () => {
  const result = await run(["unknown-command"]);
  assert.equal(result.code, 1);
  assert.match(result.stdout, /Unknown command: unknown-command/u);
});
