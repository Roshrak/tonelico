---
name: parallel-order-orchestration
description: Use when running multiple user orders in parallel, steering active tasks, avoiding lock contention, or managing bottom-anchored live progress bubbles.
---

# Parallel Order Orchestration & Multi-Task Execution

## Overview
Hermes Gateway on `tonelico-nix` runs the enhanced **`parallel-orders`** plugin (`~/.hermes/plugins/parallel-orders/__init__.py`) paired with the **`parallel-ops-mcp`** stdio MCP server (`~/.local/lib/parallel_ops_mcp.py`).

## 1. How Incoming Messages Route While a Task is Running
When one or more turns (`primary` or `par_<HHMMSS>_<hex>`) are active in a chat:
1. **Tier-0 Instant Reflex Fast-Path (`<0.15s`, Zero LLM Wait)**:
   - `"fastfetch"` immediately launches `kitty --hold -e fastfetch` on the Wayland monitor and returns the `fastfetch --pipe` output without waiting for an LLM worker.
   - `"jobs"` / `"ps"` / `"running orders"` immediately lists all active tasks, elapsed times, and current tools.
2. **Smart Steer-vs-Parallel Router**:
   - **Append / Steer into Running Process**:
     - Replying on Telegram (`reply_to_message_id`) directly to a task's original message or its live progress bubble injects the new instruction into **that exact running process** via `agent.steer(...)`.
     - Starting a message with `+ `, `steer:`, `add:`, or natural continuation phrases (`"also ..."`, `"and ..."`, `"make sure ..."`, `"don't forget ..."`, `"instead ..."`, `"actually ..."`, `"wait ..."`, `"add ..."`, `"include ..."`) automatically steers into the latest active process and updates its live progress bubble (`⏩ Added to task: ...`).
   - **Spawn Concurrent Parallel Worker**:
     - Any independent command or question spawns an isolated background `AIAgent` worker (`par_<HHMMSS>_<hex>`).
     - Prefixing with `// ` or `parallel:` forces a new parallel worker even if the message starts with `"also"`.
3. **Bottom-Anchored Live Progress Bubbles**:
   - Every permanent message (user message or completed result from any process) updates `_LATEST_PERMANENT_MSG_ID[chat_id]`.
   - Any still-running progress bubble with `message_id < _LATEST_PERMANENT_MSG_ID[chat_id]` is automatically deleted from above the completed result and re-posted at the **very bottom** of the chat within `0.15s`.

## 2. Eliminating Parallel Bottlenecks
- **No Shared Bash Session Contention**:
  - When executing multiple independent shell checks inside a single turn, batch them in one call or use `mcp__parallel_ops_mcp__parallel_batch_shell` (runs up to 16 isolated subprocesses concurrently without touching the shared persistent bash session lock).
- **Strict Gemini 4 Argon Lock + Cooldown Auto-Resume**:
  - `fallback_providers: []` in `~/.hermes/config.yaml` and `fallback_model=None` in `parallel-orders` guarantee Hermes never falls back away from `gemini-4-argon`.
  - `agent.reasoning_effort: low` keeps per-call latency fast (~2–4s instead of 16s) and preserves daily Argon quota across all 9 Google AI Pro worker accounts in `aistudio2api` (`127.0.0.1:2048`).
  - If all 9 Argon accounts enter cooldown, `parallel-orders` updates the bottom progress bubble (`⏸️ Argon accounts cooling down — auto-retrying...`) and automatically resumes as soon as an Argon slot frees up.

## 3. MCP Tools (`parallel-ops-mcp`)
- `parallel_list_active_orders`: Inspect live running primary/parallel orders (`/home/aesc/.hermes/cache/scratch/parallel_orders_state.json`) and recent `par_*` history in `state.db`.
- `parallel_steer_order`: Programmatically append instructions into any running order (`task_id="latest"` or specific `par_...`).
- `parallel_cancel_order`: Stop a specific parallel worker without interrupting other active orders.
- `parallel_batch_shell`: Execute up to 16 shell commands in parallel with isolated subprocesses and per-command timeouts.
- `parallel_argon_pool_status`: Check real-time `gemini-4-argon` worker readiness across all 9 accounts on `127.0.0.1:2048`.
