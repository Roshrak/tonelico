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
1. Hermes scheduled cronjobs (`cronjob_manage`), automated disk/Nix-store cleanup (`clean-system.py`), and OOM-safe NixOS system updates (`tonelico-safe-update`).
2. Concurrent multi-order execution on busy Gateway sessions (`parallel-orders` plugin) and ephemeral live tool-progress bubbles on Telegram (`cleanup_progress: true`).
3. Persistent startup and self-healing for `aistudio2api` (`127.0.0.1:2048`) across reboots and Nix garbage collection.
4. Tamper-resistant backup, secret hygiene (`~/tonelico/export.sh`), and self-healing protection for Hermes persistent memory (`MEMORY.md`, `USER.md`, `SOUL.md`, `AGENTS.md`, `state.db`, `plugins/`, and `skills/`).

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
2. Write Hermes cron scripts in Python (`.py`) inside `/home/aesc/.hermes/scripts/` and prepend `/run/wrappers/bin:/run/current-system/sw/bin:/etc/profiles/per-user/aesc/bin:/home/aesc/.nix-profile/bin:/home/aesc/.local/bin` to `os.environ["PATH"]` inside the script.
3. Clean the following targets on every 12h run without gating behind an artificial low-disk threshold:
   - Run `/home/aesc/.local/bin/hermes-memory-guard --backup-db` first so memory files, `plugins/`, `skills/`, and `state.db` are verified and backed up before any deletion.
   - Clean FreeDesktop Trash items (`~/.local/share/Trash/{files,info,expunged}`) that have been in the Trash for **at least 12 hours** (`TRASH_MAX_AGE = 12 * 3600`), reading `DeletionDate=` (or `st_mtime`) from `~/.local/share/Trash/info/<item>.trashinfo` rather than the original file's `st_mtime`.
   - Delete desktop thumbnails older than 7 days (`~/.cache/thumbnails`).
   - Purge Chromium caches (`~/.cache/chromium/*/{Cache,Code Cache,GPUCache}`).
   - Clean user-owned `/tmp` items older than 2 days (and orphaned `/tmp/aistudio-camoufox-*` profiles older than 6 hours that are not referenced in any active `/proc/<pid>/cmdline`).
   - Check `/proc/<pid>/cmdline` for any active Nix build (`nixos-rebuild`, `update-system.sh`, `nix build`, `nix flake update`); if none is running, execute `/run/current-system/sw/bin/nix-collect-garbage --delete-older-than 7d`.
   - Clean Hermes temporary caches (`~/.hermes/{audio_cache,image_cache}`, `sandboxes` >2d, `cron/output` >3d, `cache/{scratch,terminal-output}` >1d).

### 2. Fast Binary-Cached & OOM-Safe NixOS Updates (`~/tonelico`)
1. Keep `max-jobs = 2; cores = 4;` set in `/etc/nixos/modules/system/base.nix` and pass `--max-jobs 2 --cores 4` to `nixos-rebuild build` / `nix build` in `/home/aesc/vivian/update-system.sh` and `/home/aesc/vivian/rebuild-system.sh` so any source build cannot spawn unbounded `cc1plus` jobs and trigger kernel OOM.
2. Eliminate local C++/C source rebuilds so updates and fresh installs pull pre-built binaries from `cache.nixos.org`:
   - **KDE/KWin (`overview.nix`)**: Never patch `kwin` via `kdePackages.overrideScope` — modifying `kwin` invalidates the binary cache for 10 KDE C++ packages (`kwin`, `kwin-x11`, `plasma-workspace`, `plasma-desktop`, `kdeplasma-addons`, `powerdevil`, `plasma-pa`, `plasma-browser-integration`, `xdg-desktop-portal-kde`, `kinfocenter`). Instead, bind pointer chords via a lightweight systemd user service (`tonelico-plasma-overview-chord`) that invokes `dbus-send --session --type=method_call --dest=org.kde.kglobalaccel /component/kwin org.kde.kglobalaccel.Component.invokeShortcut string:Overview`.
   - **GVFS (`services.nix`)**: Use `services.gvfs.package = pkgs.gnome.gvfs;` (pre-built with `gnomeSupport = true` on `cache.nixos.org`) and `systemd.user.services.gvfs-daemon.path = [ pkgs.wsdd ];` instead of `gvfs.overrideAttrs`.
   - **Xwayland (`services.nix`)**: Pin `programs.xwayland.package = pkgs.xwayland;` when `services.flatpak.enable = true` — Flatpak enables `fonts.fontDir.enable = true`, which otherwise causes NixOS to override `xwayland` with a custom `-Ddefault_font_path` meson flag and compile it from source.
   - **Flake Inputs (`flake.nix`)**: Never point flake inputs at `github:NixOS/nixpkgs/master` (use `nixos-unstable` or `nixos-26.05` so Hydra binaries are already cached), and set `inputs.nixpkgs.follows = "nixpkgs";` on third-party inputs (`mango`, `lotus`, `claude-code-nix`) so they reuse the system `nixpkgs` store paths.
   - **Audit Source Builds Before Switching**: Verify zero unexpected source compiles remain by inspecting `.drv` files in `nix-store --realise --dry-run <toplevel.drv>` that do not contain `preferLocalBuild`.
3. For background NixOS updates (`/home/aesc/.local/bin/tonelico-safe-update.py`), launch inside an isolated, memory-bounded systemd user unit (`systemd-run --user --unit=tonelico-safe-update.service -p MemoryHigh=8G -p MemoryMax=10G -p CPUWeight=50 -p Nice=10`), pin the evaluated `.drv` and `--out-link` under `/home/aesc/.local/share/nix-roots/` until `switch` completes, and send progress updates every 10 minutes via `/home/aesc/.local/bin/telegram_send.py`.
4. Never hardcode API keys or fallback secrets inside `/etc/nixos/home/files/bin/*`, `~/.local/lib/*.py`, `~/.local/bin/*`, or `~/.hermes/config.yaml`. Store keys in `/home/aesc/.hermes/.env` (`0600`), reference `key_env:` in `~/.hermes/config.yaml`, and refresh `/home/aesc/tonelico` exclusively via `/home/aesc/tonelico/export.sh` (which runs `scripts/check-secrets.sh` with `gitleaks` and local canary secret checks).
5. After running any `sudo nix` command in `/etc/nixos`, verify `/etc/nixos/.git/index` and `/etc/nixos/flake.lock` are owned by `aesc:users` (`sudo chown -R aesc:users /etc/nixos/.git /etc/nixos/flake.lock`).

### 3. Concurrent Multi-Order Execution (`parallel-orders` Plugin)
1. Keep `parallel-orders` enabled under `plugins.enabled` in `/home/aesc/.hermes/config.yaml` (`/home/aesc/.hermes/plugins/parallel-orders/__init__.py`).
2. In `register(ctx)`, patch `GatewayBusySessionMixin._handle_active_session_busy_message` (from `gateway.run_busy`) and `GatewayInboundMixin._hm_handle_running_session_message` (from `gateway.run_inbound`) so follow-up messages sent while a turn is already running spawn an isolated concurrent `AIAgent` task (`asyncio.create_task`) with its own ephemeral progress bubble rather than interrupting or steering the active turn.
3. Only pass through to interrupt/steer when the user sends an explicit stop keyword (`stop`, `cancel`, `abort`, `dừng`, `thôi`, `/stop`) or prefixes the message with `steer:` / `/steer`.

### 4. Pin Nix Store Dependencies & Harden `aistudio2api` Startup
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

### 5. Protect Persistent Memory (`hermes-memory-guard`)
1. Maintain the Git-versioned memory vault at `/home/aesc/.local/share/hermes-memory-vault/repo` and atomic SQLite backup at `/home/aesc/.local/share/hermes-memory-vault/state.db.bak` via `/home/aesc/.local/bin/hermes-memory-guard`.
2. Ensure both `hermes-memory-guard.path` (`PathChanged=` on `MEMORY.md`, `USER.md`, `SOUL.md`, `AGENTS.md`) and `hermes-memory-guard.timer` (`OnUnitActiveSec=5m`) remain enabled:
   ```bash
   systemctl --user enable --now hermes-memory-guard.path hermes-memory-guard.timer
   ```
3. If `MEMORY.md`, `USER.md`, `SOUL.md`, or `AGENTS.md` is intentionally shortened by more than 50%, run `/home/aesc/.local/bin/hermes-memory-guard --accept-shrink` immediately afterward so the anti-truncation guard commits the smaller file instead of reverting it.

### 6. Ephemeral Live Progress Window on Telegram
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
