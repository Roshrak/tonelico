$ErrorActionPreference = "Stop"

function Invoke-Checked([string]$command) {
  Invoke-Expression $command
  if ($LASTEXITCODE -ne 0) { throw "Command failed: $command" }
}

$root = Split-Path -Parent $PSScriptRoot
$existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match "agy-control-mcp|dist[/\\]index\.js" }
if ($existing) { throw "Active agy-control MCP process detected; stop it before modifying node_modules." }

$package = Get-Content (Join-Path $root "package.json") -Raw | ConvertFrom-Json
$buildCommit = (git -C $root rev-parse HEAD 2>$null)
if (-not $buildCommit) { $buildCommit = "unknown" }
$env:AGY_CONTROL_BUILD_COMMIT = $buildCommit

Set-Location $root
Invoke-Checked "npm ci"
Invoke-Checked "npm run build"

$configRoot = Join-Path $HOME ".codex"
New-Item -ItemType Directory -Force -Path $configRoot | Out-Null
$configPath = Join-Path $configRoot "config.toml"
[string]$existingGuidance = ""
if (Test-Path $configPath) { $existingGuidance = Get-Content $configPath -Raw }
$entry = @"

[mcp_servers.agy-control]
command = "node"
args = ["$($root.Replace('\\', '/'))/dist/index.js"]
env = { AGY_CONTROL_LIVE = "1" }
enabled_tools = ["agy_status", "list_models", "agy_capabilities", "agy_delegate", "agy_follow_up", "agy_wait", "agy_report", "agy_diff", "agy_cancel", "agy_apply", "agy_cleanup", "agy_workflow_start", "agy_workflow_wait", "agy_workflow_status", "agy_workflow_report", "agy_workflow_add_tasks", "agy_workflow_reprioritize", "agy_workflow_cancel", "agy_workflow_cancel_task", "agy_workflow_retry_task", "agy_document_ingest", "agy_document_wait", "agy_scope_create", "agy_evidence_search", "agy_evidence_read", "agy_document_delegate", "agy_document_report", "agy_artifact", "agy_study_session_start", "agy_study_session_resume", "agy_study_preflight", "agy_study_record_attempt", "agy_study_progress", "agy_document_cancel", "agy_document_cleanup"]
required = true
model = "gemini-3.8-flash-high"
"@
if ($existingGuidance -notmatch "\[mcp_servers\.agy-control\]") { Add-Content -Path $configPath -Value $entry -Encoding utf8 }

& (Join-Path $PSScriptRoot "doctor.ps1")
