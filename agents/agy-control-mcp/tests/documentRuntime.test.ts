import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { DocumentManager } from "../src/documentManager.js";
import type { AgyOutcome, AgyRunnerLike, RunnerJob } from "../src/runner.js";
import { loadConfig } from "../src/config.js";

async function temporaryDirectory(): Promise<string> {
  return await fs.mkdtemp(path.join(os.tmpdir(), "agy-runtime-"));
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

type Behavior = (job: RunnerJob) => Promise<AgyOutcome>;

/** Controllable runner: swap `behavior` between attempts to simulate failures and escalation. */
function scriptedRunner(initial: Behavior): AgyRunnerLike & { behavior: Behavior; calls: number; killed: string[] } {
  const runner = {
    calls: 0,
    killed: [] as string[],
    behavior: initial,
    async run(job: RunnerJob): Promise<AgyOutcome> {
      runner.calls += 1;
      return await runner.behavior(job);
    },
    async kill(runId: string): Promise<void> { runner.killed.push(runId); },
    registerProcess(): void {},
  };
  return runner;
}

function succeedFromPrompt(role: string): Behavior {
  return async (job) => {
    const locked = JSON.parse(job.prompt.split("# Locked Scope\n")[1].split("\n\n")[0]);
    const evidence = JSON.parse(job.prompt.split("<untrusted_evidence>\n")[1].split("\n</untrusted_evidence>")[0]);
    const items = evidence.map((item: any) => ({
      id: item.id, text: String(item.text).split("\n").filter(Boolean).at(-1), locator: item.locator, confidence: "high",
    }));
    return {
      state: "done", exitCode: 0,
      structuredOutput: {
        status: "done", role,
        scope_echo: { scope_sha256: locked.scope_sha256, source_ids: locked.source_ids },
        items,
        coverage: { expected: evidence.length, covered: evidence.length, missing: [], covered_ids: evidence.map((item: any) => item.id), missing_ids: [] },
        uncertainties: [], violations: [],
      },
      numTurns: 1, usage: { input_tokens: 100, output_tokens: 20, total_tokens: 120 },
    };
  };
}

const rejectScopeEcho: Behavior = async () => ({
  state: "done", exitCode: 0,
  structuredOutput: { status: "done", role: "coverage-check", scope_echo: { scope_sha256: "wrong", source_ids: [] }, items: [], coverage: { expected: 9, covered: 9, missing: [], covered_ids: [], missing_ids: [] }, uncertainties: [], violations: [] },
  numTurns: 1, usage: { input_tokens: 50, output_tokens: 10, total_tokens: 60 },
});

test("concurrent document managers serialize SQLite bootstrap for one shared control root", async () => {
  const root = await temporaryDirectory();
  const managers = Array.from({ length: 8 }, () => new DocumentManager({ config: loadConfig({ root }) }));
  try {
    const statuses = await Promise.all(managers.map((manager) => manager.status()));
    assert.equal(statuses.length, 8);
    assert.ok(statuses.every((status: any) => Boolean(status.document_engine.sqlite_version)));
  } finally {
    await Promise.all(managers.map((manager) => manager.shutdown()));
  }
});

async function seedCollection(manager: DocumentManager, root: string): Promise<{ collectionId: string; scopeId: string }> {
  const sourcePath = path.join(root, "slide.md");
  await fs.writeFile(sourcePath, "# Slide 1\n\nCơ chế first-line treatment cần trích nguyên văn.\n\n# Slide 2\n\nDữ liệu bổ sung cho phạm vi học tập.\n", "utf8");
  const queued = await manager.ingest({ collection_name: "runtime", paths: [sourcePath] }) as any;
  const indexed = await waitForTerminal(manager, queued.job_id);
  assert.equal(indexed.state, "ready_for_commander", indexed.error);
  const scope = await manager.createScope({ collection_id: queued.collection_id, profile: "study", selectors: [{ sections: ["Slide 1"] }] }) as any;
  return { collectionId: queued.collection_id, scopeId: scope.scope_id };
}

test("cancelling an ingest marks the job cancelled and leaves the previous index intact", async () => {
  const root = await temporaryDirectory();
  const sourcePath = path.join(root, "ras.md");
  await fs.writeFile(sourcePath, "# RAS\n\nAphthous recurrence needs scope-locked evidence.\n", "utf8");
  const manager = new DocumentManager({ config: loadConfig({ root }) });
  try {
    const first = await manager.ingest({ collection_name: "cancel-check", paths: [sourcePath] }) as any;
    await manager.wait(first.job_id, 5);
    // Second ingest with changed content is cancelled mid-flight.
    await fs.writeFile(sourcePath, "# RAS\n\nReplaced content that should never be committed.\n".repeat(600), "utf8");
    const second = await manager.ingest({ collection_name: "cancel-check", paths: [sourcePath], force: true }) as any;
    await manager.cancel(second.job_id);
    const state = await manager.wait(second.job_id, 5) as any;
    assert.equal(state.state, "cancelled");
    // The previously indexed version survives: search still finds the original text.
    const evidence = await manager.search({ collection_id: first.collection_id, query: "Aphthous recurrence" }) as any;
    assert.equal(evidence.items.length >= 1, true);
  } finally { await manager.shutdown(); }
});

test("a cancelled document delegation stays cancelled, keeps its report, and never becomes failed", async () => {
  const root = await temporaryDirectory();
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const runner = scriptedRunner(async (job) => { await gate; return await succeedFromPrompt("coverage-check")(job); });
  const manager = new DocumentManager({ config: loadConfig({ root }), runner, modelResolver: async (tier) => `model-${tier}` });
  try {
    const { collectionId, scopeId } = await seedCollection(manager, root);
    const started = await manager.delegate({ title: "Cancel me", collection_id: collectionId, scope_id: scopeId, role: "coverage-check", objective: "Cơ chế first-line", tier: "fast", force_worker: true }) as any;
    await new Promise((resolve) => setTimeout(resolve, 40));
    await manager.cancel(started.run_id);
    release?.();
    const finished = await manager.wait(started.run_id, 5) as any;
    assert.equal(finished.state, "cancelled");
    assert.equal(finished.attempts.some((attempt: any) => attempt.outcome === "cache_hit"), false);
    // The still-blocked job finishes shortly after release; poll until its canonical report lands.
    const reportPath = path.join(String(finished.artifact_path), "report.json");
    let reportText: string | undefined;
    for (let attempt = 0; attempt < 50 && !reportText; attempt += 1) {
      reportText = await fs.readFile(reportPath, "utf8").catch(() => undefined);
      if (!reportText) await new Promise((resolve) => setTimeout(resolve, 40));
    }
    const report = JSON.parse(reportText!) as any;
    assert.equal(report.state, "cancelled");
    assert.match(report.report_sha256, /^[a-f0-9]{64}$/);
  } finally { await manager.shutdown(); }
});

test("a valid worker blocked result remains blocked rather than becoming commander-ready", async () => {
  const root = await temporaryDirectory();
  const runner = scriptedRunner(async (job) => {
    const locked = JSON.parse(job.prompt.split("# Locked Scope\n")[1].split("\n\n")[0]);
    const evidence = JSON.parse(job.prompt.split("<untrusted_evidence>\n")[1].split("\n</untrusted_evidence>")[0]);
    return {
      state: "done", exitCode: 0,
      structuredOutput: {
        status: "blocked", role: "coverage-check",
        scope_echo: { scope_sha256: locked.scope_sha256, source_ids: locked.source_ids },
        items: evidence.map((item: any) => ({ id: item.id, text: item.text, locator: item.locator, confidence: "medium" })),
        coverage: { expected: evidence.length, covered: evidence.length, missing: [], covered_ids: evidence.map((item: any) => item.id), missing_ids: [] },
        uncertainties: ["source is incomplete"], violations: [],
      },
      usage: { total_tokens: 10 },
    };
  });
  const manager = new DocumentManager({ config: loadConfig({ root }), runner, modelResolver: async (tier) => `model-${tier}` });
  try {
    const { collectionId, scopeId } = await seedCollection(manager, root);
    const started = await manager.delegate({ title: "blocked", collection_id: collectionId, scope_id: scopeId, role: "coverage-check", objective: "Cơ chế first-line", tier: "fast", force_worker: true }) as any;
    const finished = await manager.wait(started.run_id, 5) as any;
    assert.equal(finished.state, "blocked");
  } finally { await manager.shutdown(); }
});

test("worker cache does not reuse an escalated result when the policy-selected model differs", async () => {
  const root = await temporaryDirectory();
  const runner = scriptedRunner(rejectScopeEcho);
  const tiers: string[] = [];
  const manager = new DocumentManager({ config: loadConfig({ root }), runner, modelResolver: async (tier) => { tiers.push(tier); return `model-${tier}`; } });
  try {
    const { collectionId, scopeId } = await seedCollection(manager, root);
    const objective = "Escalation probe objective for cache reuse";
    // Seed: fast-tier selection is reasoning for coverage-check; first attempt fails validation,
    // escalates to expert, which succeeds and stores the FINAL tier in the cache record.
    const succeed = succeedFromPrompt("coverage-check");
    runner.behavior = async (job) => (runner.calls % 2 === 1 ? rejectScopeEcho(job) : await succeed(job));
    const first = await manager.delegate({ title: "escalate", collection_id: collectionId, scope_id: scopeId, role: "coverage-check", objective, tier: "auto", force_worker: true }) as any;
    const firstDone = await manager.wait(first.run_id, 5) as any;
    assert.equal(firstDone.state, "ready_for_commander", firstDone.error || firstDone.state);
    assert.deepEqual(tiers, ["reasoning", "expert"]);
    assert.equal(runner.calls, 2);
    // Replay starts on reasoning again. The expert result is deliberately not reused
    // because worker cache identity includes the policy-selected model.
    const replay = await manager.delegate({ title: "reuse", collection_id: collectionId, scope_id: scopeId, role: "coverage-check", objective, tier: "auto", force_worker: true }) as any;
    const replayDone = await manager.wait(replay.run_id, 5) as any;
    assert.equal(replayDone.cache_hit, false);
    assert.equal(replayDone.state, "ready_for_commander");
    assert.equal(runner.calls, 4);
  } finally { await manager.shutdown(); }
});

test("explicit-tier requests only reuse cache records whose final tier matches the policy", async () => {
  const root = await temporaryDirectory();
  const runner = scriptedRunner(succeedFromPrompt("coverage-check"));
  const manager = new DocumentManager({ config: loadConfig({ root }), runner, modelResolver: async (tier) => `model-${tier}` });
  try {
    const { collectionId, scopeId } = await seedCollection(manager, root);
    const objective = "Explicit tier isolation objective";
    const seed = await manager.delegate({ title: "seed", collection_id: collectionId, scope_id: scopeId, role: "coverage-check", objective, tier: "fast", force_worker: true }) as any;
    const seedDone = await manager.wait(seed.run_id, 5) as any;
    assert.equal(seedDone.state, "ready_for_commander");
    const callsAfterSeed = runner.calls;
    // An explicit reasoning request must not consume the fast-tier record.
    const reasoning = await manager.delegate({ title: "reasoning", collection_id: collectionId, scope_id: scopeId, role: "coverage-check", objective, tier: "reasoning", force_worker: true }) as any;
    const reasoningDone = await manager.wait(reasoning.run_id, 5) as any;
    assert.equal(reasoningDone.cache_hit, false);
    assert.equal(runner.calls, callsAfterSeed + 1);
    // The matching explicit reasoning request does reuse it without a new AGY call.
    const repeat = await manager.delegate({ title: "repeat", collection_id: collectionId, scope_id: scopeId, role: "coverage-check", objective, tier: "reasoning", force_worker: true }) as any;
    const repeatDone = await manager.wait(repeat.run_id, 5) as any;
    assert.equal(repeatDone.cache_hit, true);
    assert.equal(repeatDone.usage.total_tokens ?? 0, 0);
    assert.equal(runner.calls, callsAfterSeed + 1);
  } finally { await manager.shutdown(); }
});

test("cache hits produce full artifacts and reports without fabricating a model attempt", async () => {
  const root = await temporaryDirectory();
  const runner = scriptedRunner(succeedFromPrompt("coverage-check"));
  const manager = new DocumentManager({ config: loadConfig({ root }), runner, modelResolver: async (tier) => `model-${tier}` });
  try {
    const { collectionId, scopeId } = await seedCollection(manager, root);
    const request = { title: "cache artifacts", collection_id: collectionId, scope_id: scopeId, role: "coverage-check", objective: "Artifact completeness probe", tier: "fast" as const, force_worker: true };
    const seed = await manager.delegate(request) as any;
    await manager.wait(seed.run_id, 5);
    const equivalentScope = await manager.createScope({ collection_id: collectionId, profile: "study", selectors: [{ sections: ["Slide 1"] }] }) as any;
    const repeat = await manager.delegate({ ...request, scope_id: equivalentScope.scope_id }) as any;
    const done = await manager.wait(repeat.run_id, 5) as any;
    assert.equal(done.cache_hit, true);
    assert.deepEqual(done.attempts, []);
    assert.ok(Array.isArray(done.audit_events) && done.audit_events.some((event: any) => event.event === "cache_hit"));
    const artifactDir = String(done.artifact_path);
    for (const filename of ["compiled-prompt.md", "worker-result.schema.json", "result.json", "report.json"]) {
      await fs.access(path.join(artifactDir, filename));
    }
    const resultPayload = JSON.parse(await fs.readFile(path.join(artifactDir, "result.json"), "utf8")) as any;
    assert.equal(resultPayload.outcome.state, "cache_hit");
    const report = JSON.parse(await fs.readFile(path.join(artifactDir, "report.json"), "utf8")) as any;
    assert.equal(report.cache_hit, true);
    assert.match(report.prompt_sha256, /^[a-f0-9]{64}$/);
    assert.match(report.result_sha256, /^[a-f0-9]{64}$/);
  } finally { await manager.shutdown(); }
});

test("agy_artifact recomputes hashes over stored bytes before returning data", async () => {
  const root = await temporaryDirectory();
  const runner = scriptedRunner(succeedFromPrompt("coverage-check"));
  const manager = new DocumentManager({ config: loadConfig({ root }), runner, modelResolver: async (tier) => `model-${tier}` });
  try {
    const { collectionId, scopeId } = await seedCollection(manager, root);
    const started = await manager.delegate({ title: "hashes", collection_id: collectionId, scope_id: scopeId, role: "coverage-check", objective: "Hash verification probe", tier: "fast", force_worker: true }) as any;
    const done = await manager.wait(started.run_id, 5) as any;
    assert.equal(done.state, "ready_for_commander");
    const artifact = await manager.artifact(done.run_id, "report") as any;
    assert.match(artifact.file_sha256, /^[a-f0-9]{64}$/);
    assert.match(artifact.page_sha256, /^[a-f0-9]{64}$/);
    assert.equal(artifact.complete, true);
    assert.ok(artifact.stored_hashes.prompt_sha256 && artifact.stored_hashes.result_sha256 && artifact.stored_hashes.report_sha256);
    const promptArtifact = await manager.artifact(done.run_id, "prompt") as any;
    assert.equal(promptArtifact.hash_matches_metadata, true);
  } finally { await manager.shutdown(); }
});
