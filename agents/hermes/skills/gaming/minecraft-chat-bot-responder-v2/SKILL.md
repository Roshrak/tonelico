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
- **Direct Address Filter Bypass**: Do not gate direct mentions behind question-only or command-only filters (`is_selective_question_or_demand`). When another player greets or talks directly to the character (e.g. `<Player> hola Mr Roshrak this is a test...`), requiring an ending question mark (`?`) or question starter will silently drop the message as `not a question or action demand`. Any message containing the character's name (`Roshrak`, `Mr Roshrak`, `Rosh`, `Morgan`) or sent via private `/msg` must trigger LLM response evaluation 100% of the time, allowing the system prompt to decide between banter or `IGNORE`.
- **Niri Graphical Identity Check**: Do not check `manager.get('XDG_SESSION_CLASS') == 'user'` against `systemctl --user show-environment`. Under Niri, `systemctl --user show-environment` does not export `XDG_SESSION_CLASS` (it is empty), falsely throwing `InputRefused: user-manager graphical identity is stale or incomplete`. Verify session ownership against logind session properties (`loginctl show-session <id> -p Class`) instead.
- **Leading Key Leakage via Wayland/GLFW Event Race**: Pressing `t` to open chat followed by text typing often causes GLFW on Wayland to dispatch both the key event and a character callback (`'t'`) into the newly opened chat screen text buffer, resulting in `thi nand` or `tgood u?`. Equip `uinput_type` with `backspace` support or send `slash` + `backspace` + `type:<msg>` to guarantee an empty text box before typing begins.
