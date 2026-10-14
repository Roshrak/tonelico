$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { throw "Node.js 22 or later is required" }

$probe = Join-Path $PSScriptRoot "mcp-probe.mjs"
$server = Join-Path $root "dist/index.js"
if (-not (Test-Path $server)) { throw "Build the MCP server before running doctor" }

$result = node $probe $server | Select-Object -Last 1 | ConvertFrom-Json
if ($result.status -ne "ok") { throw "MCP probe failed" }
if (-not $result.model_policy) { throw "MCP probe did not report model routing policy" }

[pscustomobject]@{
  status = "ok"
  server = $result.server
  model_policy = $result.model_policy
} | ConvertTo-Json -Depth 8
