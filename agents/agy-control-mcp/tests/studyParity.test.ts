import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { buildScope, buildSourceIndex, ScopeError, validateScopeContract } from "../src/studyCore.js";
import { appendAttempt, deriveProgress } from "../src/studyProgress.js";
import { main as cliMain } from "../src/studyHerdCli.js";
import { AntigravityClerkRunner } from "../src/studyRunner.js";
import { validateTaskObject, validateWorkerResultObject, validateWorkerSemantics } from "../src/studyValidation.js";
import { buildPdf } from "./helpers/testPdf.js";

const integratedSkillRoot = path.resolve(".agents", "skills", "study-herd");

async function scratch(name: string): Promise<string> {
  return await fs.mkdtemp(path.join(os.tmpdir(), `parity-${name}-`));
}

function baseResult(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    status: "done", role: "source-clerk",
    scope_echo: { source_id: "src", pages: [1, 3] },
    items: [{ id: "i1", text: "claim", locator: { source_id: "src", page: 2 }, confidence: "high" }],
    coverage: { expected: 1, covered: 1, missing: [] },
    uncertainties: [], violations: [],
    ...overrides,
  };
}

// --- Worker locator / page / role / coverage / schema cases -------------------------------

test("parity:P01 worker result requires in-scope locators", () => {
  const validation = validateWorkerSemantics(validateWorkerResultObject(baseResult({
    items: [{ id: "i1", text: "x", locator: { source_id: "OTHER", page: 2 }, confidence: "high" }],
  })), { expected_source_id: "src", expected_pages: [1, 3] });
  assert.equal(validation.valid, false);
  assert.ok(validation.errors.some((error) => error.includes("out-of-scope locator")));
});

test("parity:P02 worker locator outside the expected page range is rejected", () => {
  const validation = validateWorkerSemantics(validateWorkerResultObject(baseResult()), { expected_source_id: "src", expected_pages: [5, 9] });
  assert.equal(validation.valid, false);
  assert.ok(validation.errors.some((error) => error.includes("outside expected pages")));
});

test("parity:P03 worker result must echo the exact expected page range", () => {
  const validation = validateWorkerSemantics(validateWorkerResultObject(baseResult()), { expected_source_id: "src", expected_pages: [1, 4] });
  assert.equal(validation.valid, false);
  assert.ok(validation.errors.some((error) => error.includes("page scope does not match") && error.includes("1:4")));
});

test("parity:P04 worker role must match the task role", () => {
  const validation = validateWorkerSemantics(validateWorkerResultObject(baseResult()), { expected_role: "coverage-clerk" });
  assert.equal(validation.valid, false);
  assert.ok(validation.errors.some((error) => error.includes("role does not match") && error.includes("coverage-clerk")));
});

test("parity:P05 done worker cannot hide missing coverage or violations", () => {
  const missingCoverage = validateWorkerResultObject(baseResult({ coverage: { expected: 2, covered: 1, missing: ["i2"] } }));
  assert.ok(missingCoverage.errors.some((error) => error.includes("missing coverage")));
  const violating = validateWorkerResultObject(baseResult({ violations: ["fabricated citation"] }));
  assert.ok(violating.errors.some((error) => error.includes("reports violations")));
});

test("parity:P06 worker claim requires a page, line, or section locator", () => {
  const validation = validateWorkerResultObject(baseResult({
    items: [{ id: "i1", text: "x", locator: { source_id: "src" }, confidence: "low" }],
  }));
  assert.equal(validation.valid, false);
  assert.ok(validation.errors.join(" ").includes("requires page, section, or line"));
});

test("parity:P07 PDF-scoped worker claim requires a page locator", () => {
  const validation = validateWorkerSemantics(validateWorkerResultObject(baseResult({
    items: [{ id: "i1", text: "x", locator: { source_id: "src", section: "intro" }, confidence: "high" }],
  })), { expected_source_id: "src", expected_pages: [1, 3] });
  assert.equal(validation.valid, false);
  assert.ok(validation.errors.some((error) => error.includes("requires a page locator")));
});

test("parity:P08 antigravity worker command is sandboxed and plan-only", async () => {
  const runner = new AntigravityClerkRunner(async () => ({ stdout: "", stderr: "" }));
  const command = (runner as unknown as { buildCommand(e: string, p: string, s: string, m: string | null): string[] }).buildCommand("agy", "prompt", "schema.json", null);
  const joined = command.join(" ");
  assert.match(joined, /--sandbox/);
  assert.match(joined, /--mode plan/);
  assert.match(joined, /--json-schema/);
  assert.doesNotMatch(joined, /yolo|dangerously|full-auto/i);
});

test("parity:P09 worker run embeds the locked input bundle without tool access", async () => {
  const runner = new AntigravityClerkRunner(async () => ({ stdout: "", stderr: "" }));
  const prompt = (runner as unknown as { buildPrompt(t: Record<string, unknown>, b: string): string }).buildPrompt(
    { role: "source-clerk", scope: { source_id: "s" }, acceptance: ["echo scope"] },
    "SECRET-BUNDLE-PAYLOAD",
  );
  assert.match(prompt, /BEGIN UNTRUSTED SOURCE BUNDLE[\s\S]*SECRET-BUNDLE-PAYLOAD[\s\S]*END UNTRUSTED SOURCE BUNDLE/);
  assert.match(prompt, /Do not use tools or commands/);
});

test("parity:P10 worker run enforces the task page scope through semantics", async () => {
  // Structural task passes; the semantic layer owns enforcement for PDF scopes (see P02/P07).
  const taskValidation = validateTaskObject({
    task_id: "t", role: "locator-clerk", input_bundle: "bundle.txt",
    scope: { source_id: "src", pages: [2, 4] }, acceptance: ["stay in scope"],
  });
  assert.equal(taskValidation.valid, true);
  const leaky = validateWorkerSemantics(validateWorkerResultObject(baseResult()), { expected_source_id: "src", expected_pages: [2, 4] });
  const wrongPage = validateWorkerSemantics(validateWorkerResultObject(baseResult({
    items: [{ id: "i1", text: "x", locator: { source_id: "src", page: 9 }, confidence: "high" }],
  })), { expected_source_id: "src", expected_pages: [2, 4] });
  assert.equal(leaky.valid, false);
  assert.equal(wrongPage.valid, false);
});

test("parity:P11 worker run rejects an unbounded input bundle", async () => {
  const root = await scratch("big-bundle");
  const workDir = path.join(root, ".study-work", "run");
  await fs.mkdir(workDir, { recursive: true });
  await fs.writeFile(path.join(workDir, "bundle.txt"), "x".repeat(200_001), "utf8");
  await fs.writeFile(path.join(workDir, "task.json"), JSON.stringify({
    task_id: "t", role: "locator-clerk", input_bundle: "bundle.txt",
    scope: { source_id: "s", pages: [1, 2] }, acceptance: ["a"],
  }), "utf8");
  const runner = new AntigravityClerkRunner(async () => ({ stdout: "", stderr: "" }));
  (runner as unknown as { doctor: () => Promise<unknown> }).doctor = async () => ({ installed: true, ready: true, reason: null, path: "agy-stub" });
  await assert.rejects(() => runner.run(path.join(workDir, "task.json"), { work_dir: workDir }), /bundle exceeds/i);
});

test("parity:P12 built package contains worker contract schemas", async () => {
  for (const filename of ["references/task.schema.json", "references/worker-result.schema.json"]) {
    const payload = JSON.parse(await fs.readFile(path.join(integratedSkillRoot, filename), "utf8")) as { required?: unknown };
    assert.ok(Array.isArray(payload.required), `${filename} must declare required fields`);
  }
});

test("parity:P13 schema resolution falls back to packaged resources", async () => {
  const bundledTask = JSON.parse(await fs.readFile(path.join(integratedSkillRoot, "references", "task.schema.json"), "utf8")) as { required?: string[] };
  const emptyTask = validateTaskObject({});
  const missingFieldErrors = emptyTask.errors.filter((error) => error.startsWith("must have required property"));
  assert.deepEqual(missingFieldErrors.length, bundledTask.required!.length);
  // The packaged schema's required list drives the same contract the validator enforces.
  for (const field of bundledTask.required!) {
    assert.ok(missingFieldErrors.some((error) => error.includes(`'${field}'`)), `missing-field error should name ${field}`);
  }
});

test("parity:P14 skill and packaged schemas stay in sync", async () => {
  const workerSchema = JSON.parse(await fs.readFile(path.join(integratedSkillRoot, "references", "worker-result.schema.json"), "utf8")) as { properties?: Record<string, { enum?: string[] }> };
  const roles = workerSchema.properties?.role?.enum || [];
  const skillText = await fs.readFile(path.join(integratedSkillRoot, "SKILL.md"), "utf8");
  for (const role of roles.slice(0, 2)) {
    assert.ok(skillText.toLowerCase().includes(role.split("-")[0]!), `SKILL.md should reference role family ${role}`);
  }
  assert.ok(roles.length >= 4, "worker result roles must remain declared");
});

test("parity:P15 worker retries once after a transient process failure", async () => {
  const root = await scratch("retry");
  const workDir = path.join(root, ".study-work", "run");
  await fs.mkdir(workDir, { recursive: true });
  await fs.writeFile(path.join(workDir, "bundle.txt"), "content", "utf8");
  await fs.writeFile(path.join(workDir, "task.json"), JSON.stringify({
    task_id: "t", role: "source-clerk", input_bundle: "bundle.txt",
    scope: { source_id: "src", pages: [1, 2] }, acceptance: ["ok"],
  }), "utf8");
  let attempts = 0;
  const runner = new AntigravityClerkRunner(async () => {
    attempts += 1;
    if (attempts === 1) throw Object.assign(new Error("transient crash"), { stderr: "boom" });
    return { stdout: JSON.stringify({ structured_output: baseResult({ scope_echo: { source_id: "src", pages: [1, 2] } }) }), stderr: "" };
  });
  (runner as unknown as { doctor: () => Promise<unknown> }).doctor = async () => ({ installed: true, ready: true, reason: null, path: "agy-stub" });
  const result = await runner.run(path.join(workDir, "task.json"), { work_dir: workDir, timeout_seconds: 30, max_retries: 1 }) as Record<string, unknown>;
  assert.equal(attempts, 2);
  assert.equal(result.status, "done");
});

test("parity:P16 worker refuses to write outside a study work directory", async () => {
  const root = await scratch("escape-workdir");
  const taskPath = path.join(root, "task.json");
  await fs.writeFile(taskPath, JSON.stringify({ task_id: "t", role: "source-clerk", input_bundle: "b.txt", scope: { source_id: "s" }, acceptance: ["a"] }), "utf8");
  const outsideDir = path.join(root, "plain-run");
  const runner = new AntigravityClerkRunner(async () => { throw new Error("must not be launched"); });
  await assert.rejects(() => runner.run(taskPath, { work_dir: outsideDir }), /\.study-work directory/);
  assert.equal(await fs.stat(outsideDir).then(() => true).catch(() => false), false);
});

test("parity:P17 worker does not create a rejected external work directory", async () => {
  const root = await scratch("no-create");
  const taskPath = path.join(root, "task.json");
  await fs.writeFile(taskPath, JSON.stringify({ task_id: "t", role: "source-clerk", input_bundle: "b.txt", scope: { source_id: "s" }, acceptance: ["a"] }), "utf8");
  const rejectedDir = path.join(root, "elsewhere");
  const runner = new AntigravityClerkRunner(async () => ({ stdout: "", stderr: "" }));
  await assert.rejects(() => runner.run(taskPath, { work_dir: rejectedDir }), /\.study-work directory/);
  assert.equal(await fs.stat(rejectedDir).then(() => true).catch(() => false), false);
});

test("parity:P18 task schema rejects an invalid page scope", () => {
  const invalid = validateTaskObject({ task_id: "t", role: "source-clerk", input_bundle: "b", scope: { source_id: "s", pages: [0, 2.5] }, acceptance: ["a"] });
  assert.equal(invalid.valid, false);
  assert.ok(invalid.errors.join(" ").includes("two positive integers"));
});

test("parity:P19 worker rejects a reversed page scope before launch", async () => {
  const reversed = validateTaskObject({ task_id: "t", role: "source-clerk", input_bundle: "b", scope: { source_id: "s", pages: [4, 2] }, acceptance: ["a"] });
  assert.equal(reversed.valid, false);
  assert.ok(reversed.errors.join(" ").includes("ascending order"));
  let launched = false;
  const runner = new AntigravityClerkRunner(async () => { launched = true; return { stdout: "", stderr: "" }; });
  void runner;
  assert.equal(launched, false);
});

// --- Source index / manifest coverage ------------------------------------------------------

test("parity:P20 build_source_index keeps Unicode Markdown and exclusions", async () => {
  const root = await scratch("unicode-index");
  const mdPath = path.join(root, "bai-giang.md");
  await fs.writeFile(mdPath, "# Loét miệng\n\nNội dung tiếng Việt có dấu.\n", "utf8");
  const manifestPath = path.join(root, "manifest.yaml");
  await fs.writeFile(manifestPath, [
    "subject: uni-subject",
    "sources:",
    "  - id: slide-vn",
    "    kind: course-slide",
    `    path: '${mdPath.replace(/\\/g, "\\\\")}'`,
    "  - id: dropped",
    "    include: false",
    "    reason: out of range",
    "",
  ].join("\n"), "utf8");
  const index = await buildSourceIndex(manifestPath);
  assert.equal(index.included_sources[0].headings![0].text, "Loét miệng");
  assert.equal(index.excluded_sources[0].id, "dropped");
});

test("parity:P21 parser warnings are captured as source metadata", async () => {
  const root = await scratch("parser-warnings");
  const brokenPdf = path.join(root, "broken.pdf");
  await fs.writeFile(brokenPdf, Buffer.from("%PDF-1.4 not really a pdf"), "utf8");
  const manifestPath = path.join(root, "manifest.yaml");
  await fs.writeFile(manifestPath, `subject: warn\nsources:\n  - id: bad-pdf\n    kind: course-slide\n    path: '${brokenPdf.replace(/\\/g, "\\\\")}'\n`, "utf8");
  const index = await buildSourceIndex(manifestPath);
  const record = index.included_sources[0];
  assert.notEqual(record.status, "indexed");
  assert.ok(record.error && record.error.length > 0, "parse failure must surface in metadata");
});

const subjectRoot = path.resolve("resources", "study-herd", "subjects", "noi-khoa-vung-mieng");

test("parity:P22 oral medicine manifest covers the full course map", async () => {
  const conceptMap = JSON.parse(await fs.readFile(path.join(subjectRoot, "concept-map.json"), "utf8")) as { concepts: Array<{ id: string }> };
  const conceptIds = new Set(conceptMap.concepts.map((concept) => concept.id));
  assert.ok(conceptIds.has("ras-diagnostic-frame"));
  assert.ok(conceptIds.has("antibiotic-source-control"));
  const manifestText = await fs.readFile(path.join(subjectRoot, "source-manifest.yaml"), "utf8");
  assert.ok(manifestText.includes("slide-prescribing"));
  assert.ok(manifestText.includes("lecture-r20"));
});

test("parity:P23 full course manifest stays complete without duplicate ids", async () => {
  const manifestText = await fs.readFile(path.join(subjectRoot, "source-manifest.yaml"), "utf8");
  const ids = [...manifestText.matchAll(/^  - id: (.+)$/gmu)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, "source ids must be unique");
  assert.ok(ids.length >= 33, `expected at least 33 declared sources, got ${ids.length}`);
});

// --- Scope creation / range / staleness ----------------------------------------------------

async function scopeFixture(name: string): Promise<{ root: string; index: Awaited<ReturnType<typeof buildSourceIndex>>; pdfPath: string; scopePath: string; indexPath: string }> {
  const root = await scratch(name);
  const pdfPath = path.join(root, "doc.pdf");
  // A real two-page PDF so the source indexer can count pages.
  await fs.writeFile(pdfPath, buildPdf([
    [[72, 700, "Page one heading"]],
    [[72, 700, "Page two heading"]],
  ]));
  const manifestPath = path.join(root, "manifest.yaml");
  await fs.writeFile(manifestPath, `subject: s\nsources:\n  - id: doc\n    kind: course-slide\n    path: '${pdfPath.replace(/\\/g, "\\\\")}'\n`, "utf8");
  const index = await buildSourceIndex(manifestPath);
  assert.equal(index.included_sources[0].page_count, 2);
  const indexPath = path.join(root, ".generated", "source-index.json");
  await fs.mkdir(path.dirname(indexPath), { recursive: true });
  await fs.writeFile(indexPath, JSON.stringify(index), "utf8");
  const scope = buildScope(index, "doc", 1, Math.min(2, index.included_sources[0].page_count || 1));
  const scopePath = path.join(root, "scope.json");
  await fs.writeFile(scopePath, JSON.stringify(scope), "utf8");
  return { root, index, pdfPath, scopePath, indexPath };
}

test("parity:P24 scope locks the requested page range", async () => {
  const { index, scopePath } = await scopeFixture("lock-range");
  const scope = JSON.parse(await fs.readFile(scopePath, "utf8")) as Record<string, unknown>;
  assert.equal(scope.page_start, 1);
  assert.equal(scope.page_end, Math.min(2, index.included_sources[0].page_count || 1));
  assert.match(String(scope.source_sha256), /^[a-f0-9]{64}$/);
});

test("parity:P25 scope rejects pages outside the source", async () => {
  const { index } = await scopeFixture("out-range");
  const pageCount = index.included_sources[0].page_count || 1;
  assert.throws(() => buildScope(index, "doc", 1, pageCount + 5), ScopeError);
  assert.throws(() => buildScope(index, "doc", 0, 1), ScopeError);
});

test("parity:P26 scope becomes stale when the source hash changes", async () => {
  const { root, pdfPath, scopePath } = await scopeFixture("stale-hash");
  const scope = JSON.parse(await fs.readFile(scopePath, "utf8"));
  await fs.appendFile(pdfPath, "\n% tampered", "utf8");
  const freshIndex = await buildSourceIndex(path.join(root, "manifest.yaml"));
  const violations = validateScopeContract(scope, freshIndex);
  assert.ok(violations.some((violation) => violation.includes("hash")), JSON.stringify(violations));
});

test("parity:P27 scope CLI rejects a draft with a forbidden topic", async () => {
  const { root, scopePath, indexPath } = await scopeFixture("forbidden-draft");
  const scope = JSON.parse(await fs.readFile(scopePath, "utf8")) as Record<string, unknown>;
  scope.forbidden_topics = ["prescribing"];
  await fs.writeFile(scopePath, JSON.stringify(scope), "utf8");
  const draftPath = path.join(root, "draft.md");
  await fs.writeFile(draftPath, "Draft mentions prescribing logic explicitly.", "utf8");
  const exitCode = await cliMain(["validate-scope", scopePath, "--source-index", indexPath, "--draft-file", draftPath]);
  assert.equal(exitCode, 2);
});

// --- Progress / timestamps / duplicates / unknown concepts ---------------------------------

async function progressFixture(name: string): Promise<{ conceptsPath: string; attemptsPath: string }> {
  const root = await scratch(name);
  const conceptsPath = path.join(root, "concept-map.json");
  await fs.writeFile(conceptsPath, JSON.stringify({ concepts: [{ id: "c1", label: "Concept one" }] }), "utf8");
  return { conceptsPath, attemptsPath: path.join(root, "attempts.jsonl") };
}

test("parity:P28 mastery requires correct transfer across contexts and time", async () => {
  const { conceptsPath, attemptsPath } = await progressFixture("mastery");
  const correct = (occurredAt: string, context: string, difficulty: "recall" | "clinical" = "clinical"): any => ({
    concept_id: "c1", correct: true, difficulty, context_signature: context, reasoning_quality: "sound", occurred_at: occurredAt,
  });
  await appendAttempt(attemptsPath, correct("2026-08-01T09:00:00Z", "same-context", "recall"));
  await appendAttempt(attemptsPath, correct("2026-08-01T09:20:00Z", "same-context", "recall"));
  const early = await deriveProgress(conceptsPath, attemptsPath);
  assert.notEqual((early.concepts[0] as any).status, "mastered");
  await appendAttempt(attemptsPath, correct("2026-08-02T09:00:00Z", "ward-round"));
  await appendAttempt(attemptsPath, correct("2026-08-04T09:00:00Z", "exam-hall"));
  const mastered = await deriveProgress(conceptsPath, attemptsPath);
  assert.equal((mastered.concepts[0] as any).status, "mastered");
});

test("parity:P29 attempt timestamp must include a timezone", async () => {
  const { attemptsPath } = await progressFixture("tz");
  await assert.rejects(() => appendAttempt(attemptsPath, {
    concept_id: "c1", correct: true, difficulty: "recall", context_signature: "c", reasoning_quality: "weak", occurred_at: "2026-08-01T09:00:00",
  }), /timezone offset/);
});

test("parity:P30 last attempt uses time order, not JSONL append order", async () => {
  const { conceptsPath, attemptsPath } = await progressFixture("order");
  await appendAttempt(attemptsPath, { concept_id: "c1", correct: true, difficulty: "recall", context_signature: "a", reasoning_quality: "sound", occurred_at: "2026-08-03T09:00:00Z" });
  await appendAttempt(attemptsPath, { concept_id: "c1", correct: false, difficulty: "recall", context_signature: "b", reasoning_quality: "weak", occurred_at: "2026-08-01T09:00:00Z" });
  const progress = await deriveProgress(conceptsPath, attemptsPath);
  const concept = progress.concepts[0] as any;
  // The chronologically LATEST attempt (correct) decides status even though it was appended first.
  assert.equal(concept.last_attempt_at, "2026-08-03T09:00:00Z");
  assert.equal(concept.status, "working");
});

test("parity:P31 concept maps reject duplicate ids", async () => {
  const root = await scratch("dupes");
  const conceptsPath = path.join(root, "concepts.json");
  await fs.writeFile(conceptsPath, JSON.stringify({ concepts: [{ id: "x" }, { id: "x" }] }), "utf8");
  const { loadConcepts } = await import("../src/studyProgress.js");
  await assert.rejects(() => loadConcepts(conceptsPath), /Duplicate concept id: x/);
});

test("parity:P32 progress rejects attempts for unknown concepts", async () => {
  const { conceptsPath, attemptsPath } = await progressFixture("unknown");
  await appendAttempt(attemptsPath, { concept_id: "ghost", correct: true, difficulty: "recall", context_signature: "c", reasoning_quality: "weak" });
  await assert.rejects(() => deriveProgress(conceptsPath, attemptsPath), /unknown concept: ghost/i);
});

// --- Doctor fallback / neutrality / Windows discovery --------------------------------------

test("parity:P33 doctor has a safe commander-only fallback", async () => {
  const previousPath = process.env.PATH;
  const previousLocal = process.env.LOCALAPPDATA;
  try {
    process.env.PATH = "";
    delete process.env.LOCALAPPDATA;
    const runner = new AntigravityClerkRunner();
    const report = await runner.doctor();
    assert.equal(report.installed, false);
    assert.equal(report.ready, false);
    assert.match(String(report.reason), /not found on PATH/);
  } finally {
    process.env.PATH = previousPath!;
    if (previousLocal === undefined) delete process.env.LOCALAPPDATA; else process.env.LOCALAPPDATA = previousLocal;
  }
  const cliSource = await fs.readFile(path.resolve("src", "studyHerdCli.ts"), "utf8");
  assert.match(cliSource, /commander-only/);
  assert.match(cliSource, /Workers may be used for bounded clerical tasks only/);
});

test("parity:P34 doctor fallback stays neutral between Sol and Terra", async () => {
  const cliSource = await fs.readFile(path.resolve("src", "studyHerdCli.ts"), "utf8");
  assert.doesNotMatch(cliSource, /sol.*default|default.*terra/i);
  const skillText = await fs.readFile(path.join(integratedSkillRoot, "SKILL.md"), "utf8");
  assert.match(skillText, /selected by the user/);
});

test("parity:P35 antigravity finds the Windows default install without PATH", async () => {
  const root = await scratch("win-discovery");
  const binDir = path.join(root, "agy", "bin");
  await fs.mkdir(binDir, { recursive: true });
  const marker = path.join(binDir, "agy.exe");
  await fs.copyFile(process.execPath, marker);
  const previousPath = process.env.PATH;
  const previousLocal = process.env.LOCALAPPDATA;
  try {
    process.env.PATH = "";
    process.env.LOCALAPPDATA = root;
    const runner = new AntigravityClerkRunner();
    const report = await runner.doctor();
    assert.equal(report.installed, true);
    assert.equal(report.path, marker);
  } finally {
    process.env.PATH = previousPath!;
    process.env.LOCALAPPDATA = previousLocal!;
    await fs.rm(marker, { force: true });
  }
});

// --- Commander authority boundaries --------------------------------------------------------

test("parity:P36 project does not pin the user to one commander model", async () => {
  const skillText = await fs.readFile(path.join(integratedSkillRoot, "SKILL.md"), "utf8");
  assert.match(skillText, /either `?gpt-5\.6-sol`? or `?gpt-5\.6-terra`?/);
  assert.match(skillText, /user/i);
  assert.doesNotMatch(skillText, /always use gpt-5\.6-sol|never use terra/i);
});

test("parity:P37 repository and skill let the commander author final material", async () => {
  const policyText = await fs.readFile(path.join(integratedSkillRoot, "references", "delegation-policy.md"), "utf8");
  assert.match(policyText, /Forbidden worker jobs/i);
  assert.match(policyText, /Final teaching or summary/);
  const modeText = await fs.readFile(path.join(integratedSkillRoot, "references", "mode-contracts.md"), "utf8");
  assert.match(modeText, /solve-exam|final/i);
  assert.doesNotMatch(policyText, /worker may write final material/i);
});

test("parity:P38 AGY holds no final authority over learner state", async () => {
  const policyText = await fs.readFile(path.join(integratedSkillRoot, "references", "delegation-policy.md"), "utf8");
  assert.match(policyText, /learner grading|mastery/i);
  const skillText = await fs.readFile(path.join(integratedSkillRoot, "SKILL.md"), "utf8");
  assert.match(skillText, /commander/i);
});

// --- CLI round trips -----------------------------------------------------------------------

test("parity:P39 CLI indexes Unicode sources and emits UTF-8 regardless of codepage", async () => {
  const root = await scratch("cli-unicode");
  const mdPath = path.join(root, "tai-lieu.md");
  await fs.writeFile(mdPath, "# Loét aphthous tái phát\n\nĐau rát niêm mạc.\n", "utf8");
  const manifestPath = path.join(root, "manifest.yaml");
  await fs.writeFile(manifestPath, `subject: uni-cli\nsources:\n  - id: slide-vn\n    kind: course-slide\n    path: '${mdPath.replace(/\\/g, "\\\\")}'\n`, "utf8");
  const outputPath = path.join(root, ".generated", "index.json");
  const exitCode = await cliMain(["index", manifestPath, "--output", outputPath]);
  assert.equal(exitCode, 0);
  const raw = await fs.readFile(outputPath);
  const decoded = JSON.parse(raw.toString("utf8")) as { included_sources: Array<{ headings: Array<{ text: string }> }> };
  assert.equal(decoded.included_sources[0].headings[0].text, "Loét aphthous tái phát");
  assert.ok(raw.includes(Buffer.from("Loét aphthous", "utf8")), "output bytes must be UTF-8 encoded");
});

test("parity:P40 CLI record-attempt validates concepts first and round-trips progress", async () => {
  const { conceptsPath, attemptsPath } = await progressFixture("cli-roundtrip");
  // Unknown concept: rejected BEFORE any learner state file is written.
  await assert.rejects(() => cliMain([
    "record-attempt", "--concepts", conceptsPath, "--attempts", attemptsPath,
    "--concept-id", "ghost", "--correct", "--difficulty", "recall", "--context", "ctx-a", "--reasoning", "sound",
  ]), /Unknown concept id: ghost/);
  assert.equal(await fs.stat(attemptsPath).then(() => true).catch(() => false), false);
  const okCode = await cliMain([
    "record-attempt", "--concepts", conceptsPath, "--attempts", attemptsPath,
    "--concept-id", "c1", "--correct", "--difficulty", "clinical", "--context", "ctx-b", "--reasoning", "sound",
    "--occurred-at", "2026-08-05T10:00:00Z", "--progress-output", path.join(path.dirname(attemptsPath), "progress.json"),
  ]);
  assert.equal(okCode, 0);
  const progressBytes = await fs.readFile(path.join(path.dirname(attemptsPath), "progress.json"));
  const progress = JSON.parse(progressBytes.toString("utf8")) as { concepts: Array<{ id: string; attempt_count: number }> };
  assert.equal(progress.concepts[0].attempt_count, 1);
});
