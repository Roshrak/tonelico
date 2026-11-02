---
name: nixos-binary-deployment
description: "Use when deploying precompiled binaries or apps on NixOS."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [nixos, deployment, binaries, appimage, steam-run, nix-ld]
    related_skills: [desktop-reliability]
---

# Precompiled Binary & App Deployment on NixOS

Instructions for deploying standalone upstream binaries, tarballs, and AppImages cleanly on NixOS.

## 1. Dynamic Linking & Subprocess Browser Engines
- **Orchestrator vs. Subprocess Execution:** Go, Rust, or statically oriented CLI tools generally run directly via `nix-ld`. However, embedded browser engines (Camoufox, Firefox, Electron, Chromium) require complete FHS desktop libraries (`libgtk-3.so.0`, `libnss3.so`, etc.).
- **Avoid Wrapping Parent Orchestrator in `steam-run`:** Running a parent tool under `steam-run` from within subshells or agent sessions can fail due to user namespace nesting limits (`bwrap: ENOSPC`).
- **In-Place Browser Wrapper:** Keep the parent orchestrator native (under `nix-ld`) and wrap ONLY the spawned browser executable in-place:
  ```bash
  mv browser-bin browser-bin.real
  cat << 'EOF' > browser-bin
  #!/usr/bin/env bash
  DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  exec /run/current-system/sw/bin/steam-run "$DIR/browser-bin.real" "$@"
  EOF
  chmod +x browser-bin
  ```
  *Why:* Preserves directory-relative metadata (such as `application.ini` or config manifests) while granting FHS library access exclusively to the GUI engine.

## 2. Symlink Truncation Guard
- When creating launcher scripts in `~/.local/bin/<cmd>`:
  - Verify whether `~/.local/bin/<cmd>` already exists as a symlink pointing to the target binary.
  - Redirecting shell output (`cat > ~/.local/bin/<cmd>`) follows existing symlinks and will overwrite/truncate the target binary itself.
  - Always unlink first: `rm -f ~/.local/bin/<cmd>` before creating a wrapper or updating a symlink.

## 3. Desktop Application Integration
- **Icon Installation:** Extract `.DirIcon` or application icon from AppImage (`--appimage-extract`) and install to `~/.local/share/icons/hicolor/256x256/apps/<app>.png`.
- **Desktop Entry:** Write a standard specification to `~/.local/share/applications/<app>.desktop`:
  ```ini
  [Desktop Entry]
  Version=1.0
  Name=<AppName>
  Exec=/home/aesc/.local/bin/<app>
  Icon=<app>
  Terminal=false
  Type=Application
  Categories=Network;Development;
  ```
- **Cleanup:** Always delete temporary `squashfs-root` extraction folders and downloaded archive files immediately after verification.

## 4. Persistent `systemd --user` Services & Nix GC Root Pinning
- **Pin Store Dependencies & Active Service Environments Before Referencing Them:** Never hardcode raw `/nix/store/<hash>-...` paths (such as `xvfb`, Python environments, or service packages) inside wrapper scripts or `systemd --user` units without first registering a permanent GC root — otherwise `nix-collect-garbage --delete-older-than 7d` deletes paths from older Home Manager/system generations and breaks active services:
  ```bash
  mkdir -p ~/.local/share/nix-roots
  nix-store --add-root ~/.local/share/nix-roots/<service-dep> -r /nix/store/<hash>-<pkg>
  ```
  Keep permanent roots under `~/.local/share/nix-roots/` for all active user-service store paths (`aistudio2api-xvfb`, `hermes-agent-env`, `hermes-agent-pkg`, `agy-python-env`, `mc-python`) and reference `~/.local/share/nix-roots/<service-dep>/bin` in `PATH` where applicable.
- **Survive Single-Worker OOM Events (`OOMPolicy=continue`):** For daemons that manage a pool of headless browser workers (e.g., `aistudio2api` spawning Camoufox/Xvfb), set `OOMPolicy=continue` in `[Service]` and `StartLimitIntervalSec=0` in `[Unit]`. With the default `OOMPolicy=stop`, the kernel OOM-killing a single heavy browser tab causes systemd to tear down the entire service and all healthy workers.
- **Boot Network Readiness & Worker Watchdog:** Because `network-online.target` does not exist in `systemd --user` on NixOS, wait briefly for DNS resolution in the launcher before warming up authenticated workers at boot (`for i in {1..25}; do getent hosts <host> >/dev/null 2>&1 && break; sleep 1; done`), and pair services whose internal worker pool can stop independently of the HTTP listener with a 30s `systemd --user` watchdog timer that checks `/api/status` and triggers `/api/control/start` when needed.

## 5. Scheduled Maintenance, Memory Vault & `no_agent` Cron Scripts on NixOS
- **Write `no_agent: true` Cron Scripts in Python (`.py`):** Hermes's cron scheduler executes `.sh`/`.bash` scripts via `shutil.which("bash")`, which fails when `/run/current-system/sw/bin` is absent from the service environment. Place Python scripts in `~/.hermes/scripts/<name>.py` and explicitly prepend `/run/current-system/sw/bin` to `env["PATH"]` before invoking NixOS tools (`nix-collect-garbage`, `docker`, etc.).
- **Use Fixed Cron Expressions Instead of Intervals for Twice-Daily Jobs:** Schedule recurring daily/12h jobs with cron expressions (e.g., `0 9,21 * * *` for 12 hours apart) rather than interval strings (`every 720m`), which drift across the clock whenever the laptop sleeps or reboots.
- **Unconditional Nix Garbage Collection After Root Pinning:** Run `/run/current-system/sw/bin/nix-collect-garbage --delete-older-than 7d` unconditionally in the 12-hour disk cleanup rather than gating on low-disk thresholds; active store dependencies remain safe once pinned under `~/.local/share/nix-roots/`.
- **Self-Healing Memory Vault (`hermes-memory-guard`):** Protect `~/.hermes/memories/{MEMORY.md,USER.md}`, `SOUL.md`, `AGENTS.md`, `config.yaml`, `cron/jobs.json`, `skills/`, and `state.db` via `~/.local/bin/hermes-memory-guard` (driven by `hermes-memory-guard.path` + `hermes-memory-guard.timer` and called with `--backup-db` at the start of `clean-system.py`). Verify SQLite health with `PRAGMA quick_check(1)` before updating `~/.local/share/hermes-memory-vault/state.db.bak`, and automatically restore from the Git vault (`~/.local/share/hermes-memory-vault/repo`) if a critical memory file is missing, truncated below 50% size, or tainted by prompt-injection patterns.
- **Avoid Literal `&` in Foreground `terminal` Commands:** Do not include `&` inside shell comments or strings in foreground `terminal` tool calls — the foreground backgrounding guard scans for `&` and rejects the command before execution.


