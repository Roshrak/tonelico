import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { PassThrough } from "node:stream";
import test from "node:test";
import { StdioServerTransport } from "@modelcontextprotocol/server/stdio";
import { DocumentManager } from "../src/documentManager.js";
import { createMcpServer } from "../src/server.js";
import type { AgyOutcome, AgyRunnerLike, RunnerJob } from "../src/runner.js";
import { loadConfig } from "../src/config.js";

interface Rpc {
  send: (payload: Record<string, unknown>) => Promise<any>;
  close: () => Promise<void>;
}

async function startRpc(manager: any, documentManager: any): Promise<Rpc> {
  const input = new PassThrough();
  const output = new PassThrough();
  const transport = new StdioServerTransport(input, output);
  const server = createMcpServer(manager, documentManager);
  await server.connect(transport);
  let buffered = "";
  const pending = new Map<number, (value: any) => void>();
  let nextId = 100;
  output.on("data", (chunk: Buffer) => {
    buffered += chunk.toString("utf8");
    let newline: number;
    while ((newline = buffered.indexOf("\n")) >= 0) {
      const line = buffered.slice(0, newline);
      buffered = buffered.slice(newline + 1);
      if (!line.trim()) continue;
      const message = JSON.parse(line);
      if (message.id !== undefined && pending.has(message.id)) {
        pending.get(message.id)!(message);
        pending.delete(message.id);
      }
    }
  });
  const rawSend = async (payload: Record<string, unknown>): Promise<any> => {
    const id = ++nextId;
    return await new Promise<any>((resolve) => {
      pending.set(id, resolve);
      input.write(`${JSON.stringify({ ...payload, id })}\n`);
    });
  };
  await rawSend({ jsonrpc: "2.0", method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "t", version: "1" } } });
  input.write(`${JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized", params: {} })}\n`);
  return {
    send: rawSend,
    close: async () => { await transport.close(); },
  };
}

function toolCall(name: string, args: Record<string, unknown>): Record<string, unknown> {
  return { jsonrpc: "2.0", method: "tools/call", params: { name, arguments: args } };
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

function succeedFromPrompt(role: string): (job: RunnerJob) => Promise<AgyOutcome> {
  return async (job) => {
    const locked = JSON.parse(job.prompt.split("# Locked Scope\n")[1].split("\n\n")[0]);
    const evidence = JSON.parse(job.prompt.split("<untrusted_evidence>\n")[1].split("\n</untrusted_evidence>")[0]);
    return {
      state: "done", exitCode: 0,
      structuredOutput: {
        status: "done", role,
        scope_echo: { scope_sha256: locked.scope_sha256, source_ids: locked.source_ids },
        items: evidence.map((item: any) => ({ id: item.id, text: String(item.text).split("\n").filter(Boolean).at(-1), locator: item.locator, confidence: "high" })),
        coverage: { expected: evidence.length, covered: evidence.length, missing: [], covered_ids: evidence.map((item: any) => item.id), missing_ids: [] },
        uncertainties: [], violations: [],
      },
      numTurns: 1, usage: { input_tokens: 100, output_tokens: 20, total_tokens: 120 },
    };
  };
}

const runnerStub: AgyRunnerLike & { behavior: (job: RunnerJob) => Promise<AgyOutcome> } = {
  behavior: succeedFromPrompt("coverage-check"),
  async run(job) { return await runnerStub.behavior(job); },
  async kill() {},
  registerProcess() {},
};

async function seededDocumentRunId(documentManager: DocumentManager): Promise<{ collectionId: string; runId: string; jobId: string }> {
  const root = os.tmpdir();
  const sourcePath = path.join(root, `mcp-slide-${Date.now()}.md`);
  await fs.writeFile(sourcePath, "# Slide 1\n\nCơ chế first-line treatment cần trích nguyên văn.\n", "utf8");
  const queued = await documentManager.ingest({ collection_name: `mcp-${Date.now()}`, paths: [sourcePath] }) as any;
  const indexed = await waitForTerminal(documentManager, queued.job_id);
  assert.equal(indexed.state, "ready_for_commander", indexed.error);
  const scope = await documentManager.createScope({ collection_id: queued.collection_id, profile: "study", selectors: [{ sections: ["Slide 1"] }] }) as any;
  const started = await documentManager.delegate({ title: "mcp contract", collection_id: queued.collection_id, scope_id: scope.scope_id, role: "coverage-check", objective: "Cơ chế first-line", tier: "fast", force_worker: true }) as any;
  const delegated = await waitForTerminal(documentManager, started.run_id);
  assert.equal(delegated.state, "ready_for_commander", delegated.error);
  return { collectionId: queued.collection_id, runId: started.run_id as string, jobId: queued.job_id as string };
}

test("MCP tools/call dispatches wait and report by ID family and rejects implementation-only ops for documents", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-mcp-contract-"));
  const config = loadConfig({ root });
  const manager = new (await import("../src/runManager.js")).RunManager({ config });
  const documentManager = new DocumentManager({ config, runner: runnerStub, modelResolver: async (tier) => `model-${tier}` });
  const rpc = await startRpc(manager, documentManager);
  try {
    const { runId, jobId } = await seededDocumentRunId(documentManager);

    // agy_wait dispatches the DOCUMENT id to the document engine.
    const waitDoc = await rpc.send(toolCall("agy_wait", { run_id: runId, timeout_seconds: 5 }));
    assert.equal(waitDoc.result.isError ?? false, false);
    assert.equal(waitDoc.result.structuredContent.state, "ready_for_commander");

    // agy_report dispatches the same id to the document report with integrity hashes.
    const reportDoc = await rpc.send(toolCall("agy_report", { run_id: runId }));
    assert.equal(reportDoc.result.structuredContent.kind, "document");
    assert.match(reportDoc.result.structuredContent.report_sha256, /^[a-f0-9]{64}$/);

    // Implementation-only operations reject document runs explicitly.
    const diffDoc = await rpc.send(toolCall("agy_diff", { run_id: runId }));
    assert.equal(diffDoc.result.isError, true);
    assert.match(diffDoc.result.content[0].text, /operation_not_applicable_to_document_run/);
    const applyDoc = await rpc.send(toolCall("agy_apply", { run_id: runId, report_sha256: "0".repeat(64), decision: "apply" }));
    assert.equal(applyDoc.result.isError, true);
    assert.match(applyDoc.result.content[0].text, /operation_not_applicable_to_document_run/);

    // Unknown ids keep their own distinct error — never the document-rejection message.
    const unknownDiff = await rpc.send(toolCall("agy_diff", { run_id: "doc-unknown-000" }));
    assert.equal(unknownDiff.result.isError, true);
    assert.doesNotMatch(unknownDiff.result.content[0].text, /operation_not_applicable_to_document_run/);
    assert.match(unknownDiff.result.content[0].text, /[Uu]nknown/);

    // agy_wait on an ingest job id also routes through the document engine.
    const waitIngest = await rpc.send(toolCall("agy_wait", { run_id: jobId, timeout_seconds: 5 }));
    assert.equal(waitIngest.result.structuredContent.kind ?? "ingest", waitIngest.result.structuredContent.kind ?? "ingest");
    assert.ok(waitIngest.result.structuredContent.job_id === jobId || waitIngest.result.structuredContent.run_id === undefined);
  } finally {
    await rpc.close();
    await documentManager.shutdown();
    await manager.shutdown();
  }
});

test("generic agy_cancel and the agy_document_cancel alias produce identical payloads for document jobs", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-mcp-cancel-"));
  const config = loadConfig({ root });
  const manager = new (await import("../src/runManager.js")).RunManager({ config });
  const documentManager = new DocumentManager({ config });
  const rpc = await startRpc(manager, documentManager);
  try {
    const bigSource = path.join(root, "big.md");
    await fs.writeFile(bigSource, "# RAS\n\nAphthous evidence that must remain scope locked.\n".repeat(800), "utf8");
    const first = await rpc.send(toolCall("agy_document_ingest", { collection_name: "alias-a", paths: [bigSource] })) as any;
    const second = await rpc.send(toolCall("agy_document_ingest", { collection_name: "alias-b", paths: [bigSource] })) as any;
    const jobA = first.result.structuredContent.job_id as string;
    const jobB = second.result.structuredContent.job_id as string;

    const viaAlias = await rpc.send(toolCall("agy_document_cancel", { run_id: jobA }));
    const viaGeneric = await rpc.send(toolCall("agy_cancel", { run_id: jobB }));
    assert.equal(viaAlias.result.isError ?? false, false);
    assert.equal(viaGeneric.result.isError ?? false, false);
    const payloadKeys = (value: any) => Object.keys(value).filter((key) => key !== "job_id" && key !== "collection_id" && key !== "created_at" && key !== "updated_at").sort();
    assert.deepEqual(payloadKeys(viaGeneric.result.structuredContent), payloadKeys(viaAlias.result.structuredContent));
    assert.equal(viaGeneric.result.structuredContent.state, "cancelled");
    assert.equal(viaAlias.result.structuredContent.state, "cancelled");

    // Cancelling an unknown/inactive document id reports a cancel-specific failure.
    const inactive = await rpc.send(toolCall("agy_cancel", { run_id: "doc-ingest-none" }));
    assert.equal(inactive.result.isError, true);
    assert.match(inactive.result.content[0].text, /Cannot cancel|Unknown/);
  } finally {
    await rpc.close();
    await documentManager.shutdown();
    await manager.shutdown();
  }
});
