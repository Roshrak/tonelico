import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { DocumentManager } from "../src/documentManager.js";
import type { AgyOutcome, AgyRunnerLike } from "../src/runner.js";
import { loadConfig } from "../src/config.js";

async function temporaryDirectory(): Promise<string> {
  return await fs.mkdtemp(path.join(os.tmpdir(), "agy-document-"));
}

async function waitForTerminal(manager: DocumentManager, jobId: string, timeoutMilliseconds = 20_000): Promise<any> {
  const deadline = Date.now() + timeoutMilliseconds;
  let state: any;
  do {
    state = await manager.wait(jobId, Math.max(1, Math.min(5, Math.ceil((deadline - Date.now()) / 1000))));
    if (!["queued", "running"].includes(String(state.state))) return state;
  } while (Date.now() < deadline);
  assert.fail(`Timed out waiting for ${jobId}; last state=${String(state?.state)}`);
}

function fakeRunner(): AgyRunnerLike & { calls: number; prompts: string[] } {
  const runner = {
    calls: 0,
    prompts: [] as string[],
    async run(job: any): Promise<AgyOutcome> {
      runner.calls += 1;
      runner.prompts.push(job.prompt);
      const locked = JSON.parse(job.prompt.split("# Locked Scope\n")[1].split("\n\n")[0]);
      const evidence = JSON.parse(job.prompt.split("<untrusted_evidence>\n")[1].split("\n</untrusted_evidence>")[0]);
      return {
        state: "done", exitCode: 0,
        structuredOutput: {
          status: "done", role: "locator-map",
          scope_echo: { scope_sha256: locked.scope_sha256, source_ids: locked.source_ids },
          items: [{ id: "ev-1", text: String(evidence[0].text).split("\n").filter(Boolean).at(-1), locator: evidence[0].locator, confidence: "high" }],
          coverage: { expected: evidence.length, covered: evidence.length, missing: [], covered_ids: evidence.map((item: any) => item.id), missing_ids: [] },
          uncertainties: [], violations: [],
        },
        numTurns: 1, usage: { input_tokens: 100, output_tokens: 20, total_tokens: 120 },
      };
    },
    async kill(): Promise<void> {},
    registerProcess(): void {},
  };
  return runner;
}

test("document ingest, scoped retrieval, cache, and unchanged re-ingest reduce local work", async () => {
  const root = await temporaryDirectory();
  const sourcePath = path.join(root, "ras-vi.md");
  await fs.writeFile(sourcePath, "# RAS trang 1\n\nLoét aphthous tái phát là tổn thương niêm mạc.\n\n# Chủ đề khác\n\nBệnh Parkinson không thuộc phạm vi này.\n", "utf8");
  const config = loadConfig({ root });
  const manager = new DocumentManager({ config });
  try {
    const queued = await manager.ingest({ collection_name: "Noi khoa", paths: [sourcePath] }) as any;
    const completed = await waitForTerminal(manager, queued.job_id);
    assert.equal(completed.state, "ready_for_commander");
    assert.equal(completed.result.parsed_sources, 1);
    const scope = await manager.createScope({ collection_id: queued.collection_id, profile: "study", selectors: [{ source_id: "ras-vi.md", sections: ["RAS trang 1"] }], forbidden_topics: ["Parkinson"] }) as any;
    assert.match(scope.scope_sha256, /^[a-f0-9]{64}$/);
    const first = await manager.search({ collection_id: queued.collection_id, scope_id: scope.scope_id, query: "aphthous tái phát", token_budget: 1000 }) as any;
    assert.equal(first.cache_hit, false);
    assert.match(first.bundle_id, /^bundle-[a-f0-9]{32}$/);
    assert.equal(first.items.length, 1);
    assert.equal(first.items[0].locator.source_sha256, scope.source_hashes["ras-vi.md"]);
    assert.ok(first.items.some((item: any) => typeof item.dense_rank === "number"));
    assert.equal(first.coverage.missing.length, 0);
    assert.ok(first.estimated_tokens < Buffer.byteLength(await fs.readFile(sourcePath, "utf8"), "utf8") / 3);
    const cached = await manager.search({ collection_id: queued.collection_id, scope_id: scope.scope_id, query: "APHThous TÁI PHÁT", token_budget: 1000 }) as any;
    assert.equal(cached.cache_hit, true);
    assert.equal(cached.bundle_id, first.bundle_id);
    const evidencePage = await manager.readEvidence({ bundle_id: first.bundle_id, token_budget: 1000 }) as any;
    assert.equal(evidencePage.complete, true);
    assert.equal(evidencePage.items[0].id, first.items[0].id);
    const equivalentScope = await manager.createScope({ collection_id: queued.collection_id, profile: "study", selectors: [{ source_id: "ras-vi.md", sections: ["RAS trang 1"] }], forbidden_topics: ["Parkinson"] }) as any;
    assert.notEqual(equivalentScope.scope_id, scope.scope_id);
    assert.equal(equivalentScope.scope_key, scope.scope_key);
    const wholeSourceScope = await manager.createScope({ collection_id: queued.collection_id, selectors: [{ source_id: "ras-vi.md" }] }) as any;
    assert.deepEqual(wholeSourceScope.source_ids, ["ras-vi.md"]);
    await assert.rejects(() => manager.createScope({ collection_id: queued.collection_id, selectors: [{ source_id: "ras-vi.md", page_start: 2, page_end: 3 }] }), /Page range exceeds indexed pages/);
    const again = await manager.ingest({ collection_name: "Noi khoa", paths: [sourcePath] }) as any;
    const unchanged = await manager.wait(again.job_id, 5) as any;
    assert.equal(unchanged.result.parsed_sources, 0);
    assert.equal(unchanged.result.unchanged_skipped, 1);
    assert.equal(unchanged.result.agy_tokens_used, 0);
    await fs.writeFile(sourcePath, "# RAS trang 1\n\nTái phát loét niêm mạc cần scope mới.\n", "utf8");
    const changed = await manager.ingest({ collection_name: "Noi khoa", paths: [sourcePath], force: true }) as any;
    await manager.wait(changed.job_id, 5);
    await assert.rejects(() => manager.search({ collection_id: queued.collection_id, scope_id: scope.scope_id, query: "loét niêm mạc" }), /Scope is stale/);
    await assert.rejects(() => manager.readEvidence({ bundle_id: first.bundle_id }), /Evidence bundle is stale/);
  } finally { await manager.shutdown(); }
});

test("document delegation enforces clerical roles, provenance, caps, and worker result cache", async () => {
  const root = await temporaryDirectory();
  const sourcePath = path.join(root, "slide.md");
  await fs.writeFile(sourcePath, "# Slide 1\n\nCơ chế first-line treatment cần trích nguyên văn.\n", "utf8");
  const config = loadConfig({ root });
  const runner = fakeRunner();
  const manager = new DocumentManager({ config, runner, modelResolver: async () => "gemini-test-fast" });
  try {
    await assert.rejects(() => manager.delegate({ title: "bad", collection_id: "missing", scope_id: "missing", role: "diagnosis", objective: "diagnose" }), /role must be one of/);
    const queued = await manager.ingest({ collection_name: "slides", paths: [sourcePath] }) as any;
    await manager.wait(queued.job_id, 5);
    const scope = await manager.createScope({ collection_id: queued.collection_id, profile: "study", selectors: [{ source_id: "slide.md", sections: ["Slide 1"] }] }) as any;
    await assert.rejects(() => manager.delegate({ title: "local", collection_id: queued.collection_id, scope_id: scope.scope_id, role: "locator-map", objective: "map locators", data_policy: "local_only" }), /local_only/);
    await assert.rejects(() => manager.delegate({ title: "small", collection_id: queued.collection_id, scope_id: scope.scope_id, role: "locator-map", objective: "Cơ chế first-line" }), /below the AGY delegation threshold/);
    const request = { title: "Map locators", collection_id: queued.collection_id, scope_id: scope.scope_id, role: "locator-map", objective: "Cơ chế first-line", tier: "fast" as const };
    const started = await manager.delegate(request) as any;
    assert.equal(started.resolved_tier, "fast");
    assert.ok(started.evidence_items <= 12 && started.evidence_tokens <= 4000);
    const finished = await manager.wait(started.run_id, 5) as any;
    assert.equal(finished.external_processing, true);
    assert.deepEqual(finished.scope_source_hashes, scope.source_hashes);
    assert.deepEqual(finished.usage.input_tokens, 100);
    assert.equal(finished.gates.find((gate: any) => gate.name === "allowed_clerical_role").passed, true);
    const report = await manager.report(started.run_id) as any;
    assert.equal(report.kind, "document");
    assert.match(report.report_sha256, /^[a-f0-9]{64}$/);
    assert.equal(report.apply_supported, false);
    assert.equal(report.diff_supported, false);
    assert.equal(runner.calls, 1);
    assert.doesNotMatch(runner.prompts[0], /--sandbox|add-dir|filesystem access allowed/i);
    assert.match(runner.prompts[0], /untrusted_evidence/);
    const repeated = await manager.delegate(request) as any;
    const cachedRun = await manager.wait(repeated.run_id, 5) as any;
    assert.equal(cachedRun.cache_hit, true);
    assert.equal(cachedRun.usage.total_tokens ?? 0, 0);
    assert.equal(runner.calls, 1);
  } finally { await manager.shutdown(); }
});

test("Study Herd manifests preserve source IDs and excluded-source visibility", async () => {
  const root = await temporaryDirectory();
  const sourcePath = path.join(root, "ras.md");
  const manifestPath = path.join(root, "source-manifest.yaml");
  await fs.writeFile(sourcePath, "# RAS\n\nAphthous recurrence needs scope-locked evidence.\n", "utf8");
  await fs.writeFile(manifestPath, [
    "subject: noi-khoa-vung-mieng",
    "sources:",
    "  - id: slide-ras-custom",
    "    kind: course-slide",
    `    path: '${sourcePath.replace(/\\/g, "\\\\")}'`,
    "  - id: unrelated",
    "    include: false",
    "    reason: outside requested range",
    "",
  ].join("\n"), "utf8");
  const manager = new DocumentManager({ config: loadConfig({ root }) });
  try {
    const result = await manager.ingest({ manifest_path: manifestPath }) as any;
    assert.equal(result.kind, "manifest_ingest");
    assert.equal(result.included.length, 1);
    assert.equal(result.excluded[0].source_id, "unrelated");
    const scope = await manager.createScope({ collection_id: result.collection_id ?? "documents", profile: "study", selectors: [{ source_id: "slide-ras-custom", sections: ["RAS"] }] }) as any;
    assert.equal(scope.source_ids[0], "slide-ras-custom");
  } finally { await manager.shutdown(); }
});

test("manifest ingest batches included sources into one collection job and preserves authority", async () => {
  const root = await temporaryDirectory();
  const slidePath = path.join(root, "slide.md");
  const examPath = path.join(root, "exam.md");
  const manifestPath = path.join(root, "source-manifest.yaml");
  await fs.writeFile(slidePath, "# Slide\n\nExam-axis fact.\n", "utf8");
  await fs.writeFile(examPath, "# Exam\n\nRecurrence only.\n", "utf8");
  await fs.writeFile(manifestPath, [
    "subject: demo", "sources:",
    "  - id: slide", "    kind: course-slide", `    path: '${slidePath.replace(/\\/g, "\\\\")}'`,
    "  - id: exam", "    kind: past-exam", `    path: '${examPath.replace(/\\/g, "\\\\")}'`, "",
  ].join("\n"), "utf8");
  const manager = new DocumentManager({ config: loadConfig({ root }) });
  try {
    const result = await manager.ingest({ manifest_path: manifestPath }) as any;
    assert.match(result.job_id, /^doc-ingest-/);
    assert.equal(result.included.length, 2);
    assert.equal(result.result.parsed_sources, 2);
    const scope = await manager.createScope({ collection_id: result.collection_id, selectors: [{ source_id: "slide" }] });
    const evidence = await manager.search({ collection_id: result.collection_id, scope_id: scope.scope_id, query: "Exam-axis fact" }) as any;
    assert.equal(evidence.items[0].authority, "exam_axis");
  } finally { await manager.shutdown(); }
});

test("ordered and cross-source retrieval modes change selection behavior without exceeding evidence caps", async () => {
  const root = await temporaryDirectory();
  const firstPath = path.join(root, "a.md");
  const secondPath = path.join(root, "b.md");
  await fs.writeFile(firstPath, "# Topic\n\nShared mechanism from source A.\n\n" + "Long supporting detail. ".repeat(80), "utf8");
  await fs.writeFile(secondPath, "# Topic\n\nShared mechanism from source B.\n", "utf8");
  const manager = new DocumentManager({ config: loadConfig({ root }) });
  try {
    const queued = await manager.ingest({
      collection_name: "multi-source",
      paths: [
        { path: firstPath, source_id: "a", source_kind: "course-slide" },
        { path: secondPath, source_id: "b", source_kind: "lecture-transcript" },
      ],
    }) as any;
    const indexed = await waitForTerminal(manager, queued.job_id);
    assert.equal(indexed.state, "ready_for_commander", indexed.error);
    const scope = await manager.createScope({ collection_id: queued.collection_id, profile: "study", selectors: [{ sections: ["Topic"] }] });
    const crossSource = await manager.search({
      collection_id: queued.collection_id,
      scope_id: scope.scope_id,
      query: "shared mechanism",
      mode: "cross_source",
      limit: 2,
      token_budget: 1000,
    }) as any;
    assert.deepEqual(new Set(crossSource.items.map((item: any) => item.locator.source_id)), new Set(["a", "b"]));
    const ordered = await manager.search({
      collection_id: queued.collection_id,
      scope_id: scope.scope_id,
      query: "term that is absent",
      mode: "ordered_scope",
      limit: 2,
      token_budget: 1000,
    }) as any;
    assert.equal(ordered.retrieval_mode, "ordered_scope");
    assert.equal(ordered.items.length, 2);
    assert.equal(ordered.items[0].locator.source_id, "a");
    assert.equal(ordered.uncertainties.includes("dense_retrieval_unavailable"), false);
    const oversized = ordered.items.find((item: any) => item.estimated_tokens > 256);
    assert.ok(oversized);
    await assert.rejects(
      () => manager.readEvidence({ bundle_id: ordered.bundle_id, item_ids: [oversized.id], token_budget: 256 }),
      /token_budget is smaller than evidence item/,
    );
  } finally { await manager.shutdown(); }
});

test("registered Study Herd subjects resolve manifests and append-only progress state", async () => {
  const root = await temporaryDirectory();
  const studyHome = path.join(root, "study-herd");
  const sourcePath = path.join(root, "ras.md");
  await fs.mkdir(path.join(studyHome, "subjects", "noi-khoa"), { recursive: true });
  await fs.writeFile(sourcePath, "# RAS\n\nAphthous evidence.\n", "utf8");
  await fs.writeFile(path.join(studyHome, "subjects", "noi-khoa", "source-manifest.yaml"), [
    "subject: noi-khoa", "sources:", "  - id: slide-ras", "    kind: course-slide", `    path: '${sourcePath.replace(/\\/g, "\\\\")}'`, "",
  ].join("\n"), "utf8");
  await fs.writeFile(path.join(studyHome, "subjects", "noi-khoa", "concept-map.json"), JSON.stringify({ concepts: [{ id: "ras" }] }), "utf8");
  const config = loadConfig({ root, studyHerdHome: studyHome });
  const manager = new DocumentManager({ config, transcriptionSidecar: {
    supports: () => false,
    availability: async () => ({ enabled: true, protocol_version: 1 as const, application_home: root, python_path: "python", model_directory: root, model_files_complete: true }),
    activeCount: () => 0,
    transcribe: async () => { throw new Error("not used"); },
  } as any });
  try {
    const queued = await manager.ingest({ subject_id: "noi-khoa" }) as any;
    assert.equal(queued.collection_id.startsWith("col-"), true);
    const scope = await manager.createScope({ collection_id: queued.collection_id, profile: "study", selectors: [{ source_id: "slide-ras", sections: ["RAS"] }] }) as any;
    assert.deepEqual(scope.source_ids, ["slide-ras"]);
    const paths = manager.studyProgressPaths("noi-khoa");
    assert.equal(paths.concepts_path.endsWith("concept-map.json"), true);
    assert.equal(paths.attempts_path.startsWith(path.join(root, "study")), true);
    assert.throws(() => manager.studyProgressPaths("../escape"), /invalid characters/);
  } finally { await manager.shutdown(); }
});

test("PhoWhisper sidecar transcripts are indexed with timestamp locators and cache unchanged media", async () => {
  const root = await temporaryDirectory();
  const audioPath = path.join(root, "lecture.mp3");
  await fs.writeFile(audioPath, Buffer.from([0xff, 0xfb]), "utf8");
  let calls = 0;
  const transcriber = {
    calls,
    supports(filePath: string): boolean { return filePath.toLowerCase().endsWith(".mp3"); },
    async availability(): Promise<Record<string, unknown>> {
      return { enabled: true, protocol_version: 1, application_home: root, python_path: "python", model_directory: root, model_files_complete: true };
    },
    activeCount(): number { return 0; },
    async transcribe(filePath: string): Promise<any> {
      this.calls += 1;
      assert.equal(path.resolve(filePath), path.resolve(audioPath));
      return {
        parser_version: "phowhisper-sidecar-v1", extraction_method: "phowhisper-jsonl",
        elements: [
          { ordinal: 1, element_type: "transcript", text: "Xin chào bác sĩ", start_ms: 0, end_ms: 1250, confidence: "medium" },
          { ordinal: 2, element_type: "transcript", text: "Cơn đau tăng về đêm", start_ms: 1250, end_ms: 2500, confidence: "medium" },
        ],
        warnings: [],
      };
    },
  };
  const config = loadConfig({ root });
  const manager = new DocumentManager({ config, transcriptionSidecar: transcriber as any });
  try {
    const queued = await manager.ingest({ collection_name: "media", paths: [audioPath] }) as any;
    const completed = await waitForTerminal(manager, queued.job_id);
    assert.equal(completed.state, "ready_for_commander");
    assert.equal(completed.result.parsed_sources, 1);
    assert.equal(transcriber.calls, 1);
    const evidence = await manager.search({ collection_id: queued.collection_id, query: "Xin chào bác sĩ" }) as any;
    assert.equal(evidence.items.length >= 1, true);
    const greeting = evidence.items.find((item: any) => item.locator.start_ms === 0);
    assert.ok(greeting, JSON.stringify(evidence));
    assert.equal(greeting.locator.end_ms, 1250);
    assert.equal(greeting.extraction_method, "phowhisper-jsonl");
    const repeated = await manager.ingest({ collection_name: "media", paths: [audioPath] }) as any;
    const unchanged = await waitForTerminal(manager, repeated.job_id);
    assert.equal(unchanged.result.parsed_sources, 0);
    assert.equal(unchanged.result.unchanged_skipped, 1);
    assert.equal(transcriber.calls, 1);
    const status = await manager.status() as any;
    assert.equal(status.gpu_queue.media_transcription_active, 0);
    assert.equal(status.gpu_queue.limit, 1);
  } finally { await manager.shutdown(); }
});

test("image OCR fails closed unless explicitly enabled with local traineddata", async () => {
  const root = await temporaryDirectory();
  const imagePath = path.join(root, "scan.png");
  await fs.writeFile(imagePath, Buffer.from([137, 80, 78, 71]), "utf8");
  const config = loadConfig({ root });
  const manager = new DocumentManager({ config, transcriptionSidecar: {
    supports: () => false,
    availability: async () => ({ enabled: true, protocol_version: 1 as const, application_home: root, python_path: "python", model_directory: root, model_files_complete: true }),
    activeCount: () => 0,
    transcribe: async () => { throw new Error("not used"); },
  } as any });
  try {
    delete process.env.AGY_DOCUMENT_ENABLE_OCR;
    const queued = await manager.ingest({ collection_name: "ocr", paths: [imagePath] }) as any;
    const completed = await manager.wait(queued.job_id, 5) as any;
    assert.equal(completed.state, "failed");
    assert.match(completed.error, /Image OCR is disabled/);
  } finally {
    delete process.env.AGY_DOCUMENT_ENABLE_OCR;
    await manager.shutdown();
  }
});
