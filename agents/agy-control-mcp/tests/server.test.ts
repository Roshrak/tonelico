import assert from "node:assert/strict";
import { PassThrough } from "node:stream";
import test from "node:test";
import { StdioServerTransport } from "@modelcontextprotocol/server/stdio";
import { createMcpServer } from "../src/server.js";

test("MCP server negotiates through the SDK and exposes implement-only tools", async () => {
  const input = new PassThrough();
  const output = new PassThrough();
  let buffered = "";
  const responses: any[] = [];
  output.on("data", (chunk: Buffer) => {
    buffered += chunk.toString("utf8");
    let newline: number;
    while ((newline = buffered.indexOf("\n")) >= 0) {
      const line = buffered.slice(0, newline);
      buffered = buffered.slice(newline + 1);
      if (line.trim()) responses.push(JSON.parse(line));
    }
  });
  const transport = new StdioServerTransport(input, output);
  const server = createMcpServer();
  await server.connect(transport);
  input.write(`${JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "1" } } })}\n`);
  input.write(`${JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized", params: {} })}\n`);
  input.write(`${JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} })}\n`);
  await new Promise((resolve) => setTimeout(resolve, 50));
  const initialized = responses.find((item) => item.id === 1);
  const toolList = responses.find((item) => item.id === 2);
  assert.equal(initialized.result.serverInfo.name, "agy-control-mcp");
  const delegate = toolList.result.tools.find((tool: any) => tool.name === "agy_delegate");
  assert.ok(delegate);
  assert.equal("mode" in delegate.inputSchema.properties, false);
  assert.ok("workspace_mode" in delegate.inputSchema.properties);
  assert.deepEqual(delegate.inputSchema.properties.workspace_mode.enum, ["auto", "git", "snapshot"]);
  assert.ok(toolList.result.tools.some((tool: any) => tool.name === "agy_diff"));
  for (const name of ["agy_capabilities", "agy_workflow_start", "agy_workflow_wait", "agy_workflow_status", "agy_workflow_report", "agy_workflow_add_tasks", "agy_workflow_reprioritize", "agy_workflow_cancel", "agy_workflow_cancel_task", "agy_workflow_retry_task"]) {
    assert.ok(toolList.result.tools.some((tool: any) => tool.name === name), `${name} is missing`);
  }
  await transport.close();
});
