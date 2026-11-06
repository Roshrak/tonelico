---
name: minecraft-chat-bot-responder-v2
description: "Manage mc_chat_responder.py, gates, and Niri session checks."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [minecraft, chat-bot, logs, responder]
---

# Minecraft Chat Responder Bot & Log Monitor

## When to Use
- Checking, starting, stopping, or restarting the `mc_chat_responder.py` bot.
- Reading or searching in-game `[CHAT]` messages in `latest.log`.
- Troubleshooting chat responder trigger filters, Niri/Wayland graphical session verification, and strict remote control gates.

## Strict Authorization & Remote Control Invariant
- `mc_chat_responder.py` MUST ONLY be activated or deactivated via **Telegram** or **Hermes Agent CLI** (`mc_responder_ctl <start|stop|status> [roshrak|alt]`).
- Never allow in-game chat messages, server operators, or players (even Broonie or `/tpaccept` triggers) to shut down, restart, or issue operational commands to the bot.
- The daemon must check the remote gate file (`~/.local/state/hermes/mc_responder_gate.json`) at startup and in its event loop, terminating cleanly if the gate is toggled off from Telegram.
- Do NOT enable `WantedBy = [ "default.target" ]` in systemd user units; the bot must only run on demand.

## Tools & MCP Integration
- `mc_bot_responder_control`: Starts, stops, or restarts `mc_chat_responder.py` through `mc_responder_ctl`.
- `mc_bot_responder_status`: Checks running PIDs and tails `~/.local/share/mc_chat_responder.log`.
- `mc_read_latest_log`: Reads recent lines or `[CHAT]` messages from `latest.log`.
- `mc_search_chat_history`: Searches current and `.log.gz` archived logs for player discussions, coords, or lore.

## Procedure
1. Inspect bot state with `mc_bot_responder_status` and recent chat with `mc_read_latest_log(chat_only=True)`.
2. Activate or deactivate using `mc_bot_responder_control(action="start"|"stop", account="roshrak"|"alt")`.
3. Verify process status and verify incoming `[CHAT]` lines in `latest.log`.

## Pitfalls & Core Mechanics
- **No Selective Chat Filters or IGNORE Directives ("Just Talk")**: Do not gate chat messages behind question-only/command-only filters (`is_selective_question_or_demand`) or instruct the system prompt to output `IGNORE`. `should_respond()` must only drop bot self-echoes (`is_bot_echo()`) and messages from the exact active in-game username (`sender.strip().lower() == ACTIVE_USER.lower()`, without stripping `#0000` so the operator can still chat with and test the bot via the `roshrak#0000` Discord bridge).
- **Rolling Multi-Turn Context, Burst Debouncing & Anti-Repetition**: Never send isolated single-line prompts (`Message: ...`), cache replies (`LLM_REPLY_CACHE`), or use substring reflexes (`"what are you" in m_lower` matching `"what are you up to rn"`, or `"there" in m_lower` matching `"there is a ghast"`). Always pass the rolling 25-message chat transcript (`CHAT_CONTEXT_HISTORY`) and recent bot replies (`RECENT_BOT_REPLIES`) to the LLM at temperature `0.65`, enforce `is_repetitive_reply()`, debounce rapid multi-line bursts (`1.4s` quiet window up to `3.2s` max, joining same-sender burst lines with `" | "`), and re-drain after LLM generation so delayed replies never land out of order. Exclude server terms like `skAIblock` from `AI_SUSPICION_REGEX`.
- **Pure Wayland Session Identity (Never Allow X11 Fallbacks)**: This system runs pure Wayland (`niri` on `wayland-1`) with no X11 session. Never add `'x11'` to `mc_chat_responder.py` session checks or `--ozone-platform=x11` to app wrappers. If `systemctl --user show-environment` reports `XDG_SESSION_TYPE=x11`, a background service (such as `rustdesk.service` running `sudo -E -u aesc` with `XDG_SESSION_TYPE="x11"`) polluted the user manager environment — fix the offending service to `XDG_SESSION_TYPE="wayland"`. Under Niri, `XDG_SESSION_CLASS` in `systemctl --user show-environment` is empty while `loginctl show-session <id>` verifies `Class=user` and `Type=wayland`; do not require `manager.get('XDG_SESSION_CLASS') == 'user'`, and always sync edits to `/home/aesc/.local/bin/mc_chat_responder.py`, `/etc/nixos/home/files/bin/mc_chat_responder.py`, and `/home/aesc/tonelico/nixos/home/files/bin/mc_chat_responder.py`.
- **Niri Cross-Workspace Focus Invariant**: In Niri, running `niri msg action focus-window --id <window_id>` silently NO-OPs if the window is on a different workspace. Query `workspace_id` from `niri msg -j windows`, switch workspaces first (`niri msg action focus-workspace <workspace_id>`), then focus the window before dispatching uinput events.
- **Leading Key Leakage via Wayland/GLFW Event Race**: Pressing `t` to open chat followed by text typing often causes GLFW on Wayland to dispatch both the key event and a character callback (`'t'`) into the newly opened chat screen text buffer, resulting in `thi nand` or `tgood u?`. Equip `uinput_type` with `backspace` support or send `slash` + `backspace` + `type:<msg>` to guarantee an empty text box before typing begins.
- **Alt Account Persona Corpus Isolation**: The alt persona model (`Miracle_Involker`) must be trained/prompted strictly on community-wide speech corpora (`cfuk_discord_archive`), never on the operator's personal message archive (`roshrak_all_messages.json`). This guarantees distinct sentence capitalization, punctuation, smilies (`:D`, `:)`), and phrasing so community members cannot link the alt to the main account.
