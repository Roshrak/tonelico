import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { clientName, loadConfig } from "../src/config.js";

async function withEnv(values: Record<string, string | undefined>, run: () => Promise<void> | void): Promise<void> {
  const previous = Object.fromEntries(Object.keys(values).map((name) => [name, process.env[name]]));
  for (const [name, value] of Object.entries(values)) {
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
  try {
    await run();
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
}

test("each MCP client gets its own persisted-state root while sharing the AGY capacity locks", async () => {
  await withEnv({ AGY_CONTROL_CLIENT: "claude", AGY_CONTROL_ROOT: undefined, AGY_CONTROL_LOCK_ROOT: undefined, XDG_STATE_HOME: "/state" }, () => {
    const claude = loadConfig();
    assert.equal(claude.client, "claude");
    assert.equal(claude.root, path.join("/state", "agy-control-mcp-claude"));
    assert.equal(claude.lockRoot, path.join("/state", "agy-control-mcp", "locks"));
  });
  await withEnv({ AGY_CONTROL_CLIENT: "codex", AGY_CONTROL_ROOT: undefined, AGY_CONTROL_LOCK_ROOT: undefined, XDG_STATE_HOME: "/state" }, () => {
    assert.equal(loadConfig().root, path.join("/state", "agy-control-mcp"), "codex keeps the original root that holds its existing state");
    assert.equal(loadConfig().lockRoot, path.join("/state", "agy-control-mcp", "locks"));
  });
  await withEnv({ AGY_CONTROL_CLIENT: undefined, AGY_CONTROL_ROOT: undefined, AGY_CONTROL_LOCK_ROOT: undefined, XDG_STATE_HOME: "/state" }, () => {
    assert.equal(loadConfig().client, "default");
    assert.equal(loadConfig().root, path.join("/state", "agy-control-mcp"));
  });
});

test("an explicit root keeps its own lock directory so isolated runs never contend with the live backend", () => {
  const config = loadConfig({ root: "/tmp/isolated-root" });
  assert.equal(config.lockRoot, path.join("/tmp/isolated-root", "locks"));
});

test("client names are normalised and unsafe values fall back to the default root", () => {
  assert.equal(clientName(" OpenCode "), "opencode");
  assert.equal(clientName("../escape"), "default");
  assert.equal(clientName("a/b"), "default");
  assert.equal(clientName(""), "default");
});

test("the server instructions are client-neutral and do not name a single host", async () => {
  const source = await fs.readFile(path.resolve("src", "server.ts"), "utf8");
  assert.doesNotMatch(source, /this Codex session|so Codex can route|Codex remains/);
  assert.match(source, /commander session/);
});

test("the launcher resolves its repository from its own location and answers MCP initialize", { skip: process.platform === "win32" }, async () => {
  const launcher = path.resolve("scripts", "agy-control-mcp");
  const mode = (await fs.stat(launcher)).mode;
  assert.ok(mode & 0o100, "launcher must be executable");
  const script = await fs.readFile(launcher, "utf8");
  assert.doesNotMatch(script, /\/home\/aesc/);
  assert.match(script, /dist\/index\.js|"\$server"/);
  assert.match(script, /--client/);
  const child = spawn(launcher, ["--client", "contract-test"], { env: { ...process.env, AGY_CONTROL_ROOT: path.resolve("dist-test", "launcher-root") }, stdio: ["pipe", "pipe", "pipe"] });
  let stdout = "";
  child.stdout.on("data", (chunk: Buffer) => { stdout += chunk.toString("utf8"); });
  child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "contract", version: "1" } } })}\n`);
  const deadline = Date.now() + 20_000;
  while (!stdout.includes("\n") && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 50));
  child.kill();
  assert.match(stdout, /"serverInfo"/);
});
