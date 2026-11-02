---
name: hermes-cron-and-memory-resilience
description: "Use for Hermes cronjobs, Nix GC safety, and memory guard."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [nixos, cronjob, disk-cleanup, memory-vault, aistudio2api, telegram, gc-roots, systemd]
    category: devops
---

# Hermes Cron, Service & Memory Vault Resilience on NixOS

## When to Use
Use when configuring or troubleshooting:
1. Hermes scheduled cronjobs (`cronjob_manage`) and automated disk/Nix-store cleanup scripts on NixOS.
2. Persistent startup and self-healing for `aistudio2api` (`127.0.0.1:2048`) across reboots and Nix garbage collection.
3. Ephemeral live tool-progress bubbles on Telegram (`cleanup_progress: true`).
4. Tamper-resistant backup and self-healing protection for Hermes persistent memory (`MEMORY.md`, `USER.md`, `SOUL.md`, `AGENTS.md`, `state.db`, and `skills/`).

## Procedure

### 1. Twice-Daily (12h Apart) Disk & Nix Store Cleanup (`clean-system.py`)
1. Schedule recurring twice-daily maintenance with an exact cron expression (`0 9,21 * * *`) rather than an interval (`every 720m`) so run times never drift across laptop suspend/resume cycles:
   ```python
   cronjob_manage(
       action="update",
       job_id="a163a46f3187",
       name="Hermes & System 12h Cleanup",
       schedule="0 9,21 * * *",
       script="clean-system.py",
       no_agent=True,
   )
   ```
2. Write Hermes cron scripts in Python (`.py`) inside `/home/aesc/.hermes/scripts/` and prepend `/run/current-system/sw/bin:/etc/profiles/per-user/aesc/bin:/home/aesc/.local/bin` to `os.environ["PATH"]` inside the script.
3. Clean the following targets on every 12h run without gating behind an artificial low-disk threshold:
   - Run `/home/aesc/.local/bin/hermes-memory-guard --backup-db` first so memory files and `state.db` are verified and backed up before any deletion.
   - Empty FreeDesktop Trash (`~/.local/share/Trash/{files,info,expunged}`).
   - Delete desktop thumbnails older than 7 days (`~/.cache/thumbnails`).
   - Purge Chromium caches (`~/.cache/chromium/*/{Cache,Code Cache,GPUCache}`).
   - Clean user-owned `/tmp` items older than 2 days (and orphaned `/tmp/aistudio-camoufox-*` profiles older than 6 hours that are not referenced in any active `/proc/<pid>/cmdline`).
   - Run `/run/current-system/sw/bin/nix-collect-garbage --delete-older-than 7d`.
   - Clean Hermes temporary caches (`~/.hermes/{audio_cache,image_cache}`, `sandboxes` >2d, `cron/output` >3d, `cache/{scratch,terminal-output}` >1d).

### 2. Pin Nix Store Dependencies & Harden `aistudio2api` Startup
1. Pin all `/nix/store/...` environments and binaries referenced directly by user systemd units or wrapper scripts (`hermes-agent-env`, `hermes-agent-pkg`, `agy-python-env`, `mc-python`, and `aistudio2api-xvfb`) with permanent Nix GC roots so `nix-collect-garbage` never deletes them:
   ```bash
   mkdir -p /home/aesc/.local/share/nix-roots /home/aesc/.local/bin
   nix-store --add-root /home/aesc/.local/share/nix-roots/aistudio2api-xvfb -r /nix/store/<hash>-xvfb-<ver>
   nix-store --add-root /home/aesc/.local/share/nix-roots/hermes-agent-env -r /nix/store/<hash>-hermes-agent-env
   nix-store --add-root /home/aesc/.local/share/nix-roots/hermes-agent-pkg -r /nix/store/<hash>-hermes-agent-<ver>
   ln -sfn /home/aesc/.local/share/nix-roots/aistudio2api-xvfb/bin/Xvfb /home/aesc/.local/bin/Xvfb
   ```
2. In `/home/aesc/aistudio2api/aistudio2api`, wait up to 25 seconds for network/DNS readiness (`getent hosts aistudio.google.com`) before launching `./aistudio2api-core`, and export `AUTO_START=true`.
3. Keep `aistudio2api-watchdog.timer` (`OnBootSec=15s`, `OnUnitActiveSec=30s`) enabled so `/home/aesc/.local/bin/aistudio2api-watchdog` queries `http://127.0.0.1:2048/api/status` and sends `POST http://127.0.0.1:2048/api/control/start` (with Basic Auth from `/home/aesc/aistudio2api/.env`) whenever `state == "STOPPED"`.

### 3. Protect Persistent Memory (`hermes-memory-guard`)
1. Maintain the Git-versioned memory vault at `/home/aesc/.local/share/hermes-memory-vault/repo` and atomic SQLite backup at `/home/aesc/.local/share/hermes-memory-vault/state.db.bak` via `/home/aesc/.local/bin/hermes-memory-guard`.
2. Ensure both `hermes-memory-guard.path` (`PathChanged=` on `MEMORY.md`, `USER.md`, `SOUL.md`, `AGENTS.md`) and `hermes-memory-guard.timer` (`OnUnitActiveSec=5m`) remain enabled:
   ```bash
   systemctl --user enable --now hermes-memory-guard.path hermes-memory-guard.timer
   ```
3. If `MEMORY.md`, `USER.md`, `SOUL.md`, or `AGENTS.md` is intentionally shortened by more than 50%, run `/home/aesc/.local/bin/hermes-memory-guard --accept-shrink` immediately afterward so the anti-truncation guard commits the smaller file instead of reverting it.

### 4. Ephemeral Live Progress Window on Telegram
1. Configure `/home/aesc/.hermes/config.yaml` under both `display:` and `display.platforms.telegram:` so progress updates accumulate in a single message bubble and auto-delete once the final reply is delivered:
   ```yaml
   display:
     tool_progress: all
     tool_progress_grouping: accumulate
     thinking_progress: true
     interim_assistant_messages: false
     cleanup_progress: true
   ```
2. When the user sends `"Screenshot"`, reply with ONLY `MEDIA:/path/to/screenshot.png` and zero explanatory text. Only include status text when the user asks a specific question alongside the screenshot request.
3. Wrap file paths containing spaces in double quotes (`MEDIA:"/path/with spaces.jpeg"`) when emitting `MEDIA:` tags so `MEDIA_TAG_CLEANUP_RE` matches the full filename.

## Pitfalls
- Never reference a `/nix/store/...` path in a systemd unit or wrapper script without registering a symlink root via `nix-store --add-root` — `nix-collect-garbage` deletes unrooted store paths and breaks the service on its next restart.
- Avoid literal `&` characters inside `#` comments in foreground `terminal` tool calls — the backgrounding guard scans the raw command string and rejects foreground execution when `&` is present.
- Use `.py` scripts (not `.sh` scripts) for `no_agent=True` Hermes cronjobs on NixOS — the gateway scheduler invokes `.sh` via `shutil.which("bash")`, which fails when `/run/current-system/sw/bin` is absent from the service environment's default `PATH`.
- Check `/proc/<pid>/cmdline` for active `-profile /tmp/aistudio-camoufox-*` arguments before deleting `/tmp/aistudio-camoufox-*` directories — deleting an active Camoufox profile crashes the running `aistudio2api` browser worker.
- Run `PRAGMA quick_check(1)` on `state.db` before backing it up to `state.db.bak` — blindly copying `state.db` without an integrity check overwrites a healthy backup if the live database is ever corrupted.
