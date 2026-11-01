#!/usr/bin/env node
// Points every supported MCP client at the shared AGY Control launcher.
//
//   node scripts/install-agent-clients.mjs                 # dry run: prints what would change
//   node scripts/install-agent-clients.mjs --apply         # writes configs (backs up each file first)
//   node scripts/install-agent-clients.mjs --apply --only claude,codex
//
// Each client gets `scripts/agy-control-mcp --client <name>`, so state stays per client while the AGY
// capacity locks are shared. Existing per-server settings (timeouts, required, enabled_tools) are kept.
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { parseDocument } from "yaml";

const run = promisify(execFile);
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const launcher = path.join(repo, "scripts", "agy-control-mcp");
const serverName = "agy-control";
const args = process.argv.slice(2);
const apply = args.includes("--apply");
const onlyIndex = args.indexOf("--only");
const only = onlyIndex >= 0 ? new Set(String(args[onlyIndex + 1] || "").split(",").filter(Boolean)) : undefined;
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const log = (client, message) => console.log(`[${client}] ${message}`);

async function backup(file) {
  const target = `${file}.bak-${stamp}`;
  await fs.copyFile(file, target);
  return target;
}

async function readIfExists(file) {
  return existsSync(file) ? fs.readFile(file, "utf8") : undefined;
}

// Replaces only the command/args lines inside the [mcp_servers.agy-control] table, keeping its other keys.
function updateCodexToml(text) {
  const header = `[mcp_servers.${serverName}]`;
  const lines = (text ?? "").split("\n");
  const start = lines.findIndex((line) => line.trim() === header);
  const block = [`command = ${JSON.stringify(launcher)}`, `args = ["--client", "codex"]`];
  if (start < 0) {
    const prefix = text && !text.endsWith("\n") ? "\n" : "";
    return `${text ?? ""}${prefix}\n${header}\n${block.join("\n")}\nrequired = true\nstartup_timeout_sec = 60.0\n`;
  }
  let end = start + 1;
  while (end < lines.length && !lines[end].trim().startsWith("[")) end += 1;
  const kept = lines.slice(start + 1, end).filter((line) => !/^\s*(command|args)\s*=/.test(line));
  return [...lines.slice(0, start + 1), ...block, ...kept, ...lines.slice(end)].join("\n");
}

const clients = {
  async claude() {
    const scope = ["--scope", "user"];
    const command = [launcher, "--client", "claude"];
    if (!apply) return log("claude", `would run: claude mcp remove ${serverName} -s user; claude mcp add ${scope.join(" ")} ${serverName} -- ${command.join(" ")}`);
    await run("claude", ["mcp", "remove", serverName, ...scope]).catch(() => undefined);
    await run("claude", ["mcp", "add", ...scope, serverName, "--", ...command]);
    log("claude", "registered at user scope");
  },

  async agy() {
    const file = path.join(os.homedir(), ".gemini", "config", "mcp_config.json");
    const current = await readIfExists(file);
    const config = current ? JSON.parse(current) : { mcpServers: {} };
    config.mcpServers = {
      ...(config.mcpServers || {}),
      [serverName]: {
        args: ["--client", "agy"],
        command: launcher,
      },
    };
    await write("agy", file, current, `${JSON.stringify(config, null, 2)}\n`);
  },

  async codex() {
    const file = path.join(os.homedir(), ".codex", "config.toml");
    const current = await readIfExists(file);
    const next = updateCodexToml(current);
    await write("codex", file, current, next);
  },

  async opencode() {
    const file = path.join(os.homedir(), ".config", "opencode", "opencode.json");
    const current = await readIfExists(file);
    const config = current ? JSON.parse(current) : { $schema: "https://opencode.ai/config.json" };
    const previous = config.mcp?.[serverName] || {};
    config.mcp = { ...(config.mcp || {}), [serverName]: { ...previous, type: "local", command: [launcher, "--client", "opencode"], enabled: previous.enabled ?? true, timeout: previous.timeout ?? 60000 } };
    delete config.mcp[serverName].environment;
    await write("opencode", file, current, `${JSON.stringify(config, null, 2)}\n`);
  },

  async hermes() {
    const file = path.join(os.homedir(), ".hermes", "config.yaml");
    const current = await readIfExists(file);
    if (current === undefined) return log("hermes", `skipped: ${file} not found`);
    const doc = parseDocument(current);
    const existing = doc.getIn(["mcp_servers", serverName])?.toJSON?.() || {};
    const entry = { ...existing, command: launcher, args: ["--client", "hermes"], enabled: existing.enabled ?? true, timeout: existing.timeout ?? 3600 };
    delete entry.env;
    doc.setIn(["mcp_servers", serverName], entry);
    await write("hermes", file, current, doc.toString());
  },
};

async function write(client, file, current, next) {
  if (current === next) return log(client, `already up to date (${file})`);
  if (!apply) return log(client, `would update ${file}`);
  if (current !== undefined) log(client, `backup: ${await backup(file)}`);
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, next, { mode: 0o600 });
  log(client, `updated ${file}`);
}

if (!existsSync(launcher)) throw new Error(`launcher missing: ${launcher}`);
console.log(apply ? "Applying changes." : "Dry run. Re-run with --apply to write changes.");
for (const [name, install] of Object.entries(clients)) {
  if (only && !only.has(name)) continue;
  try { await install(); }
  catch (error) { console.error(`[${name}] failed: ${error instanceof Error ? error.message : error}`); process.exitCode = 1; }
}
