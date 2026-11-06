---
name: minecraft-auto-chat
description: "Manage Minecraft chat responder: gates, personas, logs."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [minecraft, chat-bot, logs, tpa, responder, niri, uinput]
---

# Minecraft Auto Chat Responder

## When to Use
- Activating, deactivating, restarting, or inspecting `mc_chat_responder.py` across main (`Roshrak`) and alt (`Miracle_Involker`) accounts.
- Diagnosing in-game chat triggers, persona styling, and Wayland/Niri keystroke injection.

## Core Rules & Invariants
1. **Strict Gate Control (Telegram / Hermes CLI Only)**:
   - `mc_chat_responder` must NEVER auto-start at boot or be controllable by in-game players.
   - It can ONLY be started or stopped via `/home/aesc/.local/bin/mc_responder_ctl <start|stop|restart|status> [roshrak|alt]`.
   - The responder process enforces `HERMES_MC_AUTHORIZED=1` and checks `/home/aesc/.local/state/hermes/mc_responder_gate.json` every second.
2. **Free-Flowing Chat (Zero Over-Filtering)**:
   - Do NOT restrict chat triggers to question marks (`?`) or commands ("just talk"). When active, it talks freely with players in the room.
   - The ONLY messages to drop are:
     * Bot's own echo (`is_bot_echo()`).
     * Messages sent by the exact in-game character (`sender.strip().lower() == ACTIVE_USER.lower()`); do NOT strip `#0000` in `should_respond()`, so Discord-bridged messages (`roshrak#0000`) can still talk to the in-game bot.
   - Coalesce rapid multi-line player bursts (`1.4s` quiet debounce up to `3.2s` max, joining lines with `" | "`) and re-drain after LLM generation so the responder never lags behind real-time chat or sends duplicate out-of-order replies.
3. **Persona Isolation (Main vs. Alt)**:
   - **Main Account (`Roshrak`)**: Follows Roshrak's empirical speech (all lowercase, no trailing period, no `!`, deadpan slang: `yo`, `wb`, `ty`, `cya`, `alr`, `ye`, `nah`, `welp`, `bruh`, `af`, verb-drop).
   - **Alt Account (`Miracle_Involker`)**: Follows CFUK community speech (proper sentence capitalization, normal punctuation `!`, `?`, `.`, friendly smilies `:p`, `:D`, `:)`, `haha`, `gg`, cheerful tone). Never sound like Roshrak or mention AI/Morgan.
4. **Niri / Wayland Session Verification (Pure Wayland Only)**:
   - This laptop runs pure Wayland (`niri` on `wayland-1`) with no X11 session. Never add `'x11'` to `mc_chat_responder.py` session checks or `--ozone-platform=x11` to app wrappers.
   - If `systemctl --user show-environment` reports `XDG_SESSION_TYPE=x11`, a background service (such as `rustdesk.service` running `sudo -E -u aesc` with `XDG_SESSION_TYPE="x11"`) polluted the user manager environment — fix the offending service to `XDG_SESSION_TYPE="wayland"`.
   - Under Niri, `XDG_SESSION_CLASS` in `systemctl --user show-environment` is empty while `loginctl show-session <id>` verifies `Class=user` and `Type=wayland`; do not require `manager.get('XDG_SESSION_CLASS') == 'user'`, and always sync edits across `/home/aesc/.local/bin/mc_chat_responder.py`, `/etc/nixos/home/files/bin/mc_chat_responder.py`, and `/home/aesc/tonelico/nixos/home/files/bin/mc_chat_responder.py`.
5. **Tier-0 Telegram Fast-Path Matching**:
   - Match both `(?:mc|minecraft)\s*(?:auto\s*)?(?:chat\s*)?(?:responder|respond|reply)` and bare `auto\s*(?:respond|reply|responder)` in `parallel-orders` Tier-0 fast-path (on both idle and busy gateway paths) so phrases like `"Mc auto respond on"` or `"auto reply on"` execute `mc_responder_ctl` in `<0.1s` without spawning an LLM turn.

## Commands & Tools
- **Start Main**: `/home/aesc/.local/bin/mc_responder_ctl start roshrak`
- **Start Alt**: `/home/aesc/.local/bin/mc_responder_ctl start alt`
- **Stop**: `/home/aesc/.local/bin/mc_responder_ctl stop`
- **Status**: `/home/aesc/.local/bin/mc_responder_ctl status`
- **MCP Control**: `mcp_minecraft_ops_mcp_mc_bot_responder_control(action="start"|"stop"|"status", account="roshrak"|"alt")`

## Verification
- Check PID and gate state via `mc_responder_ctl status`.
- Check live responses in `/home/aesc/.local/share/mc_chat_responder.log` and game logs at `~/.local/share/PrismLauncher/instances/<instance>/minecraft/logs/latest.log`.
