---
name: hyprland-wayland-computer-use
description: "Control NixOS Hyprland/Wayland desktop, windows, and GUI."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [computer-use, hyprland, wayland, nixos, desktop, gui, screenshot, wtype, grim, cua-driver]
    category: desktop
    related_skills: [computer-use, cua-driver, browser-use, desktop-reliability]
---

# Hyprland & Wayland Computer Use on NixOS (tonelico-nix)

## When to Use
Use whenever controlling or inspecting the NixOS Hyprland/Wayland desktop, native GUI windows, screenshots, clipboard, or synthetic input.

Complete guide for controlling the desktop, native GUI apps, windows, screenshots, and media on this NixOS + Hyprland (`wayland-1`) laptop.

## 1. Choose the Right Tool Layer

1. **Web pages & DOM interaction** -> Use `browser_exec` (Browser Use CLI) or `playwright` skill. Never drive the user's foreground browser with synthetic clicks when `browser_exec` can do it directly via CDP.
2. **Background GUI App Control (no focus steal)** -> Use `computer_use` (`cua-driver 0.38.0` at `/home/aesc/.local/bin/cua-driver`, configured with `CUA_DRIVER_RS_ENABLE_WAYLAND=1` and NixOS X11/Wayland libs).
3. **Window Management, Workspaces, & Fast Wayland Captures** -> Use `hyprctl`, `grim`, `wtype`, and `wl-copy`/`wl-paste` via `terminal`.

## 2. Environment Setup for Hyprland / Wayland Commands

When running `hyprctl`, `grim`, or `wl-copy` from a terminal or background service, ensure `WAYLAND_DISPLAY` and `HYPRLAND_INSTANCE_SIGNATURE` are set:

```bash
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY=wayland-1
export HYPRLAND_INSTANCE_SIGNATURE=$(ls -t "$XDG_RUNTIME_DIR/hypr/" 2>/dev/null | head -n 1)
```

## 3. Background Desktop Control (`computer_use` + `cua-driver`)

- `cua-driver 0.38.0` is installed at `/home/aesc/.local/bin/cua-driver` with native Wayland (`zwlr_screencopy_manager_v1`, `virtual-pointer`, `foreign-toplevel`) and AT-SPI enabled.
- Verify health anytime with:
  ```bash
  hermes computer-use doctor
  ```
- Follow the 3-step `computer_use` workflow:
  1. `computer_use(action="capture", mode="som", app="<AppName>")`
  2. `computer_use(action="click", element=N, capture_after=True)`
  3. Escalate from `element` -> `coordinate=[x,y]` -> `delivery_mode="foreground"` only when `effect` / `escalation` signals it.

## 4. Native Hyprland Window & Workspace Control (`hyprctl`)

- **List all open windows (JSON):**
  ```bash
  hyprctl clients -j | jq -r '.[] | "\(.address) [\(.workspace.name)] \(.class): \(.title)"'
  ```
- **Get active window:**
  ```bash
  hyprctl activewindow -j
  ```
- **Focus a window by class or title:**
  ```bash
  hyprctl dispatch focuswindow "class:^(chromium)$"
  ```
- **Close a window cleanly:**
  ```bash
  hyprctl dispatch closewindow "class:^(chromium)$"
  ```
- **Launch a command visibly on the desktop monitor in Kitty:**
  ```bash
  nohup kitty --hold -e <command> >/dev/null 2>&1 &
  ```

## 5. Screenshots & Visual Inspection (`grim` + `vision_analyze`)

- **Full-screen Wayland screenshot:**
  ```bash
  OUT="/home/aesc/.hermes/cache/scratch/screen_$(date +%s).png"
  WAYLAND_DISPLAY=wayland-1 grim "$OUT"
  ```
- **Active window crop screenshot:**
  ```bash
  GEOM=$(hyprctl activewindow -j | jq -r '"\(.at[0]),\(.at[1]) \(.size[0])x\(.size[1])"')
  WAYLAND_DISPLAY=wayland-1 grim -g "$GEOM" "$OUT"
  ```
- Inspect with `vision_analyze(image_url=OUT, question="...")` or send to Telegram via `/home/aesc/.local/bin/telegram_send.py --photo "$OUT"`.

## 6. Wayland Keystroke Injection (`wtype`) & Clipboard (`wl-clipboard`)

- Locate or run `wtype`:
  ```bash
  WTYPE=$(find /nix/store -maxdepth 3 -name wtype -type f 2>/dev/null | head -n 1)
  "$WTYPE" "text to type"
  "$WTYPE" -k Return
  ```
- Read/write Wayland clipboard:
  ```bash
  WAYLAND_DISPLAY=wayland-1 wl-copy "copied text"
  WAYLAND_DISPLAY=wayland-1 wl-paste
  ```
