#!/usr/bin/env node
// End-to-end health check for AGY Control across Claude Code, Codex, OpenCode and Hermes.
// For each client it verifies the config entry, then performs a real MCP initialize + tools/list
// handshake through the launcher. Exit code is non-zero if any check fails.
import { spawn } from "node:child_process";
import { existsSync, readFileSync, statSync, readdirSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const launcher = path.join(repo, "scripts", "agy-control-mcp");
const clients = (process.env.DOCTOR_CLIENTS || "claude,codex,opencode,hermes").split(",");
const requiredTools = ["agy_status", "agy_capabilities", "agy_delegate", "agy_workflow_start", "agy_workflow_wait", "agy_apply"];
const configFiles = {
  claude: undefined, // checked through `claude mcp get`, not a file
  codex: path.join(os.homedir(), ".codex", "config.toml"),
  opencode: path.join(os.homedir(), ".config", "opencode", "opencode.json"),
  hermes: path.join(os.homedir(), ".hermes", "config.yaml"),
};
let failures = 0;
const report = (ok, label, detail = "") => { if (!ok) failures += 1; console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? `  (${detail})` : ""}`); };

report(existsSync(launcher), "launcher exists", launcher);

const server = path.join(repo, "dist", "index.js");
report(existsSync(server), "dist/index.js built");
if (existsSync(server)) {
  const newestSource = readdirSync(path.join(repo, "src")).filter((name) => name.endsWith(".ts"))
    .map((name) => statSync(path.join(repo, "src", name)).mtimeMs).reduce((a, b) => Math.max(a, b), 0);
  report(statSync(server).mtimeMs >= newestSource, "dist is not older than src", newestSource > statSync(server).mtimeMs ? "run npm run build" : "");
}
const buildInfo = path.join(repo, "dist", "build-info.json");
if (existsSync(buildInfo)) {
  const info = JSON.parse(readFileSync(buildInfo, "utf8"));
  console.log(`INFO  build ${info.commit?.slice(0, 7)}${info.dirty ? " (working tree had uncommitted changes)" : ""}`);
}

function configMentionsLauncher(client) {
  const file = configFiles[client];
  if (!file) return true;
  return existsSync(file) && readFileSync(file, "utf8").includes(launcher);
}

function handshake(client) {
  return new Promise((resolve) => {
    const child = spawn(launcher, ["--client", client], { cwd: repo, stdio: ["pipe", "pipe", "pipe"] });
    let buffer = "";
    const replies = new Map();
    let stderr = "";
    child.stderr.on("data", (chunk) => { stderr += chunk.toString("utf8"); });
    child.stdout.on("data", (chunk) => {
      buffer += chunk.toString("utf8");
      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (!line) continue;
        try { const message = JSON.parse(line); if (message.id !== undefined) replies.set(message.id, message); } catch { /* ignore non-JSON */ }
      }
    });
    const send = (message) => child.stdin.write(`${JSON.stringify(message)}\n`);
    const waitFor = async (id) => { for (let i = 0; i < 300 && !replies.has(id); i += 1) await new Promise((r) => setTimeout(r, 100)); return replies.get(id); };
    (async () => {
      send({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "doctor", version: "1" } } });
      const init = await waitFor(1);
      send({ jsonrpc: "2.0", method: "notifications/initialized" });
      send({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
      const list = await waitFor(2);
      child.kill();
      resolve({ init, list, stderr });
    })();
  });
}

for (const client of clients) {
  console.log(`\n== ${client}`);
  report(configMentionsLauncher(client), `${client} config points at the shared launcher`, configFiles[client] ? path.relative(os.homedir(), configFiles[client]) : "claude mcp registry");
  if (!existsSync(server)) continue;
  const { init, list, stderr } = await handshake(client);
  report(Boolean(init?.result?.serverInfo?.name), "MCP initialize succeeds", init?.error?.message || "");
  const names = new Set((list?.result?.tools || []).map((tool) => tool.name));
  const missing = requiredTools.filter((name) => !names.has(name));
  report(missing.length === 0, `tools/list exposes ${requiredTools.length} core tools`, missing.length ? `missing: ${missing.join(", ")}` : `${names.size} tools total`);
  if (stderr.trim()) console.log(`INFO  launcher stderr: ${stderr.trim().split("\n")[0]}`);
}

console.log(`\n${failures ? `${failures} check(s) failed` : "All checks passed"}`);
process.exitCode = failures ? 1 : 0;
