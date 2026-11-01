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
