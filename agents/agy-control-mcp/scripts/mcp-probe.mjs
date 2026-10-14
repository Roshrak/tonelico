import { spawn } from "node:child_process";
import path from "node:path";

const serverPath = process.argv[2] ? path.resolve(process.argv[2]) : undefined;
if (!serverPath) throw new Error("Usage: node scripts/mcp-probe.mjs <dist/index.js>");

const child = spawn(process.execPath, [serverPath], { cwd: path.dirname(serverPath), windowsHide: true, env: { ...process.env, AGY_CONTROL_LIVE: process.env.AGY_PROBE_LIVE || "0" } });
let stdout = "";
let stderr = "";
const responses = [];

const completed = new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error(`MCP probe timed out. stderr=${stderr.slice(-2000)}`)), 30000);
  child.stdout.on("data", (chunk) => {
    stdout += chunk.toString("utf8");
    let newline;
    while ((newline = stdout.indexOf("\n")) >= 0) {
      const line = stdout.slice(0, newline).trim();
      stdout = stdout.slice(newline + 1);
      if (!line) continue;
      try { responses.push(JSON.parse(line)); } catch (error) { reject(new Error(`Invalid MCP stdout: ${line}\n${error}`)); }
    }
    if (responses.some((message) => message.id === 3)) {
      clearTimeout(timer);
      resolve();
    }
  });
  child.stderr.on("data", (chunk) => { stderr += chunk.toString("utf8"); });
  child.on("error", reject);
  child.on("close", (code) => {
    if (!responses.some((message) => message.id === 3)) reject(new Error(`MCP server exited ${code}. stderr=${stderr.slice(-2000)}`));
  });
});

child.stdin.write([
  JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "doctor", version: "1" } } }),
  JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized", params: {} }),
  JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }),
  JSON.stringify({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "agy_status", arguments: {} } })
].join("\n") + "\n");

try {
  await completed;
  const initialized = responses.find((message) => message.id === 1);
  const listed = responses.find((message) => message.id === 2);
  const status = responses.find((message) => message.id === 3)?.result?.structuredContent;
  const tools = listed?.result?.tools || [];
  const delegate = tools.find((tool) => tool.name === "agy_delegate");
  if (initialized?.result?.serverInfo?.version !== "0.3.0") throw new Error("Unexpected MCP server version");
  if (!delegate || "mode" in (delegate.inputSchema?.properties || {})) throw new Error("Delegate schema is not implement-only");
  if (!tools.some((tool) => tool.name === "agy_diff")) throw new Error("agy_diff is missing");
  for (const tool of ["agy_capabilities", "agy_workflow_start", "agy_workflow_wait", "agy_workflow_status", "agy_workflow_report", "agy_workflow_add_tasks", "agy_workflow_reprioritize", "agy_workflow_cancel", "agy_workflow_cancel_task", "agy_workflow_retry_task", "agy_document_ingest", "agy_scope_create", "agy_evidence_search", "agy_document_delegate", "agy_artifact", "agy_study_progress"]) {
    if (!tools.some((item) => item.name === tool)) throw new Error(`${tool} is missing`);
  }
  if (!status?.document?.document_engine?.fts5) throw new Error("Document FTS5 status is unavailable");
  process.stdout.write(`${JSON.stringify({ status: "ok", version: initialized.result.serverInfo.version, live: status.live, tools: tools.length, server: status.server, model_policy: status.model_policy, document: status.document })}\n`);
} finally {
  child.kill();
}
