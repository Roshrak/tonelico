# AGY Control MCP

An MCP server that lets a commander agent (Claude Code, Codex, OpenCode, or Hermes) delegate bounded
work to Antigravity (`agy`) workers: read-only analysis and research workflows, and isolated,
patch-only implementation runs that need explicit approval before they are applied.

## Setup

Requirements: Node.js 22+, and `agy` on `PATH` (or set `AGY_BIN`).

```sh
npm ci && npm run build
npm run install:clients            # dry run: shows the config change for each client
npm run install:clients -- --apply # writes the configs, backing up each file first
npm run doctor:agy                 # handshakes with the server for every client
```

Every client runs the same launcher, `scripts/agy-control-mcp --client <name>`:

| Client      | Config                                 | Persisted state root                    |
|-------------|----------------------------------------|-----------------------------------------|
| Claude Code | `claude mcp` (user scope)              | `~/.local/state/agy-control-mcp-claude` |
| Codex       | `~/.codex/config.toml`                 | `~/.local/state/agy-control-mcp`        |
| OpenCode    | `~/.config/opencode/opencode.json`     | `~/.local/state/agy-control-mcp-opencode` |
| Hermes      | `~/.hermes/config.yaml`                | `~/.local/state/agy-control-mcp-hermes` |

Each client has its own state root, so one client never recovers another's workflows. All clients
share the capacity locks in `~/.local/state/agy-control-mcp/locks`, because they drive the same AGY
backend.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `AGY_CONTROL_CLIENT` | `default` | Client name, normally set by `--client` |
| `AGY_CONTROL_ROOT` | per client (above) | Override the persisted state root |
| `AGY_CONTROL_LOCK_ROOT` | shared `locks` dir | Override the shared capacity lock root |
| `AGY_CONTROL_LIVE` | `1` (launcher) | Run against the real `agy` binary |
| `AGY_BIN` | `agy` on `PATH` | Path to the `agy` executable |
| `PHOWHISPER_APP_HOME` | unset | Enables audio/video transcription when set to an installed `phowhisper_app` |

Transcription is disabled unless `PHOWHISPER_APP_HOME` points at a real install; the server reports
the reason through `agy_status` instead of assuming a machine-specific path.

## Development

```sh
npm test          # build + full test suite
npm run doctor:agy
```

The original PowerShell scripts (`scripts/install-codex.ps1`, `scripts/doctor.ps1`) are kept for
Windows Codex installs. The Node scripts above are tested on Linux only.
