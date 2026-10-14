import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { buildScope, buildSourceIndex, summarizeSourceIndex, validateDraftTopics, validateScopeContract } from "../src/studyCore.js";
import { validateTaskObject, validateWorkerResultObject, validateWorkerSemantics } from "../src/studyValidation.js";
import { loadConfig } from "../src/config.js";

async function temporaryDirectory(): Promise<string> {
  return await fs.mkdtemp(path.join(os.tmpdir(), "agy-study-core-"));
}

function indexedSource(overrides: Record<string, unknown> = {}): Record<string, unknown>[] {
  return [{
    id: "slide-noninfectious", status: "indexed", path: "C:/course/slide-7.pdf", sha256: "digest-v1",
    page_count: 33, page_previews: Array.from({ length: 33 }, (_, index) => `Page ${index + 1}`), ...overrides,
  }];
}

test("source indexing preserves Vietnamese Markdown and manifest exclusions", async () => {
  const directory = await temporaryDirectory();
  const sourcePath = path.join(directory, "Bài giảng.md");
  await fs.writeFile(sourcePath, "# Đại cương\n\n## Cơ chế\nNội dung", "utf8");
  const manifestPath = path.join(directory, "sources.yaml");
  await fs.writeFile(manifestPath, [
    "subject: demo", "sources:",
    `  - id: lecture`, "    kind: lecture-transcript", `    path: '${sourcePath.replace(/\\/g, "\\\\")}'`,
    "  - id: cache", "    kind: generated-cache", "    include: false", "    reason: Never index generated data", "",
  ].join("\n"), "utf8");
  const index = await buildSourceIndex(manifestPath);
  assert.equal(index.included_sources[0].status, "indexed");
  assert.equal(index.included_sources[0].line_count, 4);
  assert.deepEqual(index.included_sources[0].headings?.[1], { line: 3, level: 2, text: "Cơ chế" });
  assert.equal(index.excluded_sources[0].reason, "Never index generated data");
  assert.deepEqual(summarizeSourceIndex(index).statuses, { indexed: 1 });
});

test("legacy scope locks page ranges, detects stale hashes, and rejects forbidden drafts", () => {
  const index = { included_sources: indexedSource() };
  const scope = buildScope(index as any, "slide-noninfectious", 1, 13, ["RAS"], ["liệt mặt", "đau dây V"]);
  assert.equal(scope.first_page_preview, "Page 1");
  assert.equal(scope.last_page_preview, "Page 13");
  assert.deepEqual(validateScopeContract(scope as any, index as any), []);
  assert.deepEqual(validateDraftTopics(scope, "Đây là liệt mặt ngoại biên"), ["Draft mentions forbidden topic: liệt mặt"]);
  assert.throws(() => buildScope(index as any, "slide-noninfectious", 23, 34), /Invalid page range/);
  const changed = { included_sources: indexedSource({ sha256: "digest-v2" }) };
  assert.ok(validateScopeContract(scope as any, changed as any).includes("Scope source hash does not match the current source index"));
});

function validResult(): Record<string, unknown> {
  return {
    status: "done", role: "source-clerk", scope_echo: { source_id: "slide-noninfectious", pages: [1, 13] },
    items: [{ id: "claim-1", text: "Candidate fact", locator: { source_id: "slide-noninfectious", page: 4 }, confidence: "medium" }],
    coverage: { expected: 1, covered: 1, missing: [] }, uncertainties: [], violations: [],
  };
}

test("worker validation rejects stale scope, outside pages, missing locators, and partial done coverage", () => {
  const valid = validateWorkerResultObject(validResult());
  assert.equal(valid.valid, true);
  const wrongSource = structuredClone(validResult());
  (wrongSource.items as any[])[0].locator.source_id = "wrong-source";
  const wrongSourceValidation = validateWorkerSemantics(validateWorkerResultObject(wrongSource), { expected_source_id: "slide-noninfectious" });
  assert.match(wrongSourceValidation.errors.join("; "), /out-of-scope locator/);
  const outsidePages = structuredClone(validResult());
  (outsidePages.items as any[])[0].locator.page = 23;
  const outsideValidation = validateWorkerSemantics(validateWorkerResultObject(outsidePages), { expected_pages: [1, 13] });
  assert.ok(outsideValidation.errors.some((error) => error.includes("outside expected pages 1:13")));
  const wrongEcho = structuredClone(validResult());
  (wrongEcho.scope_echo as any).pages = [1, 12];
  const echoValidation = validateWorkerSemantics(validateWorkerResultObject(wrongEcho), { expected_pages: [1, 13] });
  assert.match(echoValidation.errors.join("; "), /page scope does not match/);
  const missingLocator = validResult();
  (missingLocator.items as any[])[0].locator = { source_id: "slide-noninfectious" };
  assert.match(validateWorkerResultObject(missingLocator).errors.join(";"), /requires page|section|line|locator requires/);
  const partial = validResult();
  partial.coverage = { expected: 2, covered: 1, missing: ["claim-2"] };
  partial.violations = ["source line was unreadable"];
  const partialErrors = validateWorkerResultObject(partial).errors;
  assert.ok(partialErrors.includes("Worker done result has missing coverage"));
  assert.ok(partialErrors.includes("Worker done result reports violations"));
});

test("worker tasks reject a reversed PDF page scope before launch", () => {
  const result = validateTaskObject({
    task_id: "worker-1", role: "source-clerk", input_bundle: ".study-work/run/inputs/source.md",
    scope: { source_id: "slide", pages: [13, 1] }, acceptance: ["Extract only grounded claims."], worker_model: null,
  });
  assert.equal(result.valid, false);
  assert.ok(result.errors.some((error) => error.includes("ascending order")));
});

test("integrated runtime bundles Study Herd policy and subject metadata without the legacy checkout", async () => {
  const config = loadConfig({ root: await temporaryDirectory() });
  await fs.access(path.join(config.studyHerdHome, "subjects", "noi-khoa-vung-mieng", "source-manifest.yaml"));
  await fs.access(path.join(config.studyHerdHome, "subjects", "noi-khoa-vung-mieng", "concept-map.json"));
  await fs.access(path.resolve(".agents", "skills", "study-herd", "SKILL.md"));
});
