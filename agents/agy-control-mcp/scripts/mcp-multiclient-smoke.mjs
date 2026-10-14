import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { once } from "node:events";

const serverPath = path.resolve("dist", "index.js");
const root = await fs.mkdtemp(path.join(os.tmpdir(), "agy-multiclient-"));
const roundCount = Math.max(1, Math.min(20, Number(process.env.AGY_MULTICLIENT_ROUNDS || 20)));

async function client(index) {
  const child = spawn(process.execPath, [serverPath], {
    cwd: path.dirname(serverPath), windowsHide: true,
    env: { ...process.env, AGY_CONTROL_ROOT: root, AGY_CONTROL_LIVE: "0", AGY_CONTROL_STATUS_SKIP_DISCOVERY: "1" },
  });
  let buffer = "";
  let stderr = "";
  const responses = new Map();
  const wait = (id) => new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`client ${index} timed out: ${stderr.slice(-500)}`)), 30_000);
    const poll = () => {
      if (responses.has(id)) { clearTimeout(timer); resolve(responses.get(id)); }
      else setTimeout(poll, 10);
    };
    poll();
  });
  child.stdout.on("data", (chunk) => {
    buffer += chunk.toString("utf8");
    let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) { const message = JSON.parse(line); if (message.id !== undefined) responses.set(message.id, message); }
    }
  });
  child.stderr.on("data", (chunk) => { stderr += chunk.toString("utf8"); });
  child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: `multi-${index}`, version: "1" } } })}\n`);
  child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized", params: {} })}\n`);
  child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} })}\n`);
  child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "agy_status", arguments: {} } })}\n`);
  try {
    const [init, tools, status] = await Promise.all([wait(1), wait(2), wait(3)]);
    return { version: init.result.serverInfo.version, tools: tools.result.tools.length, server: status.result.structuredContent.server, sqlite: status.result.structuredContent.document.document_engine.sqlite_version };
  } finally {
    child.stdin.end();
    child.kill();
    await Promise.race([once(child, "close"), new Promise((resolve) => setTimeout(resolve, 5_000))]);
  }
}

const rounds = [];
for (let round = 0; round < roundCount; round += 1) {
  const results = await Promise.all([0, 1, 2, 3].map(client));
  const commits = new Set(results.map((result) => result.server.build.commit));
  if (commits.size !== 1 || results.some((result) => result.tools < 20 || !result.sqlite)) throw new Error(`multiclient round ${round} failed consistency checks`);
  rounds.push({ round, commit: results[0].server.build.commit, instance_ids: results.map((result) => result.server.instance_id) });
}
process.stdout.write(`${JSON.stringify({ status: "ok", root, rounds, configured_rounds: roundCount }, null, 2)}\n`);
