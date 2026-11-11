---
name: nixos-wayland-session-management
description: "Use when configuring or debugging NixOS Wayland sessions."
version: 1.1.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [nixos, wayland, niri, umbriel, sway, hyprland, mango, noctalia, xdg-desktop-portal, bluetooth, libinput, uhid]
---

# NixOS Wayland Session & Compositor Management

## When to Use
- Installing, configuring, theming, or troubleshooting Wayland compositor sessions (`niri`, `umbriel`, `mango`, `sway`, `hyprland`, `plasma`) on this Tonelico NixOS machine.
- Editing compositor configs (`~/.config/niri/config.kdl`, `~/.config/umbriel/config.toml`, `~/.config/sway/config`, `~/.config/mango/config.conf`, `~/.config/hypr/hyprland.lua`) or syncing `/home/aesc/tonelico/nixos` with `/etc/nixos`.

## Procedure

### 1. Flake Inputs & Binary Caches (`flake.nix` & `modules/system/base.nix`)
1. Check upstream branches with `git ls-remote <repo_url>` before pinning a flake input.
   - **Pitfall**: Track the upstream `cachix` branch (e.g. `github:noctalia-dev/umbriel/cachix`, `github:noctalia-dev/noctalia/cachix`) without `inputs.nixpkgs.follows = "nixpkgs"` when a project publishes a Cachix binary cache — overriding `nixpkgs` changes the input closure hash and forces a full local C++/Rust build instead of fetching prebuilt store paths.
2. Add the substituter URL and public key to both `nixConfig` in `flake.nix` and `nix.settings` in `modules/system/base.nix`.
3. Pass `--option extra-substituters "..." --option extra-trusted-public-keys "..."` explicitly on the first `nixos-rebuild switch` before the new cache is active in `/etc/nix/nix.conf`.

### 2. Multi-Compositor NixOS Module Wiring
When adding or modifying a Wayland session, update all coordinated modules together:
1. **Session module (`modules/desktop/sessions/<name>.nix`)**:
   - Import the upstream NixOS module if provided and enable the compositor (`programs.<name>.enable = true`).
   - **Pitfall**: Disable the upstream module's default portal wiring (`portalPackage = null` or `enableDefaultPortal = false`) — `modules/desktop/shared/portals.nix` uses `lib.mkForce` on `xdg.portal.extraPortals` to deduplicate portals across compositors, so portal packages and `xdg.portal.config.<name>` must be declared centrally in `portals.nix`.
2. **Desktop aggregate (`modules/aggregates/desktop.nix`)**:
   - Add `"<name>"` to the `sessions` list.
3. **Curated Greeter catalog (`modules/desktop/shared/session-catalog.nix`)**:
   - Add `"<name>"` to `waylandNames`, add the session package to `packagePaths`, rewrite `Exec=` in the generated `.desktop` entry to `/run/current-system/sw/bin/<name>-session-guarded`, and update the `builtins.length waylandNames` assertion count.
4. **Session lifecycle & Kanshi (`modules/desktop/shared/session-lifecycle.nix` & `monitor-layout.nix`)**:
   - Add `environment.etc."kanshi/<name>.conf".source = mkKanshiConfig "<name>";` in `monitor-layout.nix`.
   - Add the compositor's output-focus IPC command to `desktop-main-pointer` in `session-lifecycle.nix` (e.g. `niri msg action focus-monitor "$target"` for Niri, `umbriel msg output-focus "$target"` for Umbriel).
   - Include any compositor-specific environment variables (`NIRI_SOCKET`, `UMBRIEL_SOCKET`, `WAYLAND_SOCKET`, `LIBEI_SOCKET`, `SWAYSOCK`, `HYPRLAND_INSTANCE_SIGNATURE`) in the session cleanup unset lists.
5. **Isolated Theme Profiles (`modules/desktop/shared/theme-profiles.nix`, `modules/home/desktop/configuration.nix`, `home/files/bin/save-theme-profile`)**:
   - Register the profile name in `noctalia-profile`, `theme-profile-activate`, `theme-profile-sync`, `theme-session-cleanup`, `save-theme-profile`, and `<name>-session-guarded`.
   - Seed `~/.config/theme-profiles/<name>`, `~/.local/state/theme-profiles/<name>`, and `~/.config/kitty/profiles/<name>` so GTK/Qt/Kitty/Noctalia themes stay isolated per compositor.
   - In `modules/home/desktop/configuration.nix`, link the static compositor config via `xdg.configFile` and rewrite relative dynamic color includes (`colors.kdl` or `noctalia.toml`) to mutable paths under `${config.xdg.configHome}` seeded by `home.activation.tonelicoMutableThemeOutputs`.

### 3. Validating Compositor Configurations & Scrolling Parity
1. Always inspect the installed binary's built-in schema and validator before writing or patching compositor configs:
   - **Umbriel**:
     ```bash
     umbriel config schema --json | jq '.options[] | select(.path | startswith("layout."))'
     umbriel config validate -c /home/aesc/tonelico/nixos/home/files/config/umbriel/config.toml --json
     ```
   - **Niri**:
     ```bash
     niri validate -c /home/aesc/tonelico/nixos/home/files/config/niri/config.kdl
     ```
   - **Pitfall**: Never rely on web-scraped READMEs or subagent summaries for config syntax or keybind action names — upstream docs frequently lag behind the binary schema (e.g. Umbriel uses `[include] files = [...]` as a table, `default_floating = true` / `default_pinned = true` on `[[window_rule]]` rather than `state`/`floating`/`pin`, built-in `general.mod_key` left/right mouse drag rather than `[mousebinds]`, and hyphenated actions like `window-focus-left`, `column-move-left`, `window-consume-or-expel-left`, `window-cycle-primary-extent`, `config-reload`, which `umbriel config validate --json` verifies with zero guesswork).
2. Read `/home/aesc/tonelico/nixos/home/files/config/niri/config.kdl` and `docs/KEYBINDINGS.md` directly when matching look-and-feel and muscle-memory parity across compositors:
   - **Tonelico Niri / Umbriel visual baseline**: DWM-like minimal scrollable tiling strip, square corners (`corner_radius = 0`), tiny gaps (`gap = 2`), thin borders (`border_width = 1`, `outer_border_width = 0`), no shadows (`[appearance.shadow] enabled = false`), `default_extent_fraction = 0.62`, `extent_presets = [0.33333, 0.5, 0.62, 0.66667]`, `center_focused = "never"`, `center_underfull_strip = false`, title bars disabled (`mode = "off"`), `prefer_no_csd = true`, `HDMI-A-1` at `[0, 60]` (left) and `eDP-1` at `[1920, 0]` (right, `focus_at_startup = true`, `direct_scanout = false`).
   - **Pitfall (Cursor Follows Focus vs. Scrolling Flicker & Hover-Focus Lockout)**: In Umbriel, navigating columns via shortcuts or wheel (`window-focus-right`/`left`, `Mod+Shift+WheelDown`/`Up`) moves focus while leaving the pointer behind in the departing column, and calls `invalidateHoverFocus()`. If `[input.cursor] follows_focus = false` (default), subsequent pointer motion inside the old column immediately triggers `PointerHover`, snapping the scrolling strip back and causing a 1-frame strobe flicker. **Do NOT fix this with `follows_mouse_max_scroll = 0.0`**: setting `max_scroll = 0.0` rejects hover-focus on any partially visible window (e.g. neighboring columns), breaking mouse focus navigation. Instead, set `follows_focus = true` under `[input.cursor]` so keyboard and wheel navigation warps the cursor to the newly focused window, and keep `follows_mouse_max_scroll` omitted/null in `[input.focus]` with `hover_raises = false` so moving the mouse cursor freely focuses any visible window instantly.
   - **Pitfall (Physical Springs vs. Bezier Reset on Scroll Retarget)**: Always configure `[animation]` with `curve = "spring"` and define true physical springs under `[animation.springs.spring]` (`damping = 1.0, stiffness = 800.0` for `windows_move`, `windows_resize`, `overview`) and `[animation.springs.workspace_spring]` (`damping = 1.0, stiffness = 1000.0` for `workspaces`) — in Umbriel's `AnimatedValue::retarget` and `LayoutMotion::retarget`, live velocity continuation across mid-flight scroll steps only activates when `curve.easing == Easing::Spring`; omitting `[animation]` (which falls back to `Easing::Snappy` overshooting cubic bezier) or defining 4-number bezier strings resets `m_startMsec = 0` and `m_velocity = 0.0` on every scroll tick, causing 1-frame pauses during rapid scrolling.
   - **Wheelbind Cooldowns & Scroll Direction Parity**: Unify wheel-scroll cooldowns to 10 ms across all scrollable compositors so rapid scrolling switches workspaces and columns immediately without dropping ticks: `binds = { scroll_event_delay = 10 }` (with `workspaces` slide animation `speed = 1.5`) in Hyprland, `axis_bind_apply_timeout = 10` in Mango, `cooldown_ms = 10` on both workspace (`Mod+WheelUp`/`Down`, `Mod+Ctrl+WheelUp`/`Down`) and column (`Mod+Shift+WheelUp`/`Down`, `Mod+WheelLeft`/`Right`) binds in Umbriel, `cooldown-ms=10` on `Mod+WheelScrollUp`/`Down` and `Mod+Shift+WheelScrollUp`/`Down` in Niri, and `bindsym --whole-window $mod+button4 workspace prev_on_output` / `$mod+button5 workspace next_on_output` in Sway.
   - **Pitfall (Hyprland `mouse_up` / `mouse_down` Axis Inversion)**: Hyprland's axis bind names invert physical scroll direction relative to `WheelUp`/`WheelDown` in other compositors; bind `SUPER + mouse_up` to `workspace = "e+1"` (`SUPER + SHIFT + mouse_up` to `direction = "right"`) and `SUPER + mouse_down` to `workspace = "e-1"` (`SUPER + SHIFT + mouse_down` to `direction = "left"`), and when replacing existing binds live via `hyprctl eval`, call `hl.unbind(...)` before `hl.bind(...)` so old dispatchers do not remain active alongside the new ones.
   - **Window-Close Hold-Repeat Parity (`Super+Q`)**: Keep `repeat = true` on `"Mod+Q"` (`window-close`) in `umbriel/config.toml` (leaving `"Mod+Shift+Q"` and `"Alt+F4"` at `repeat = false`), `repeat=true` on `Mod+Q` (`close-window`) in `niri/config.kdl`, `{ repeating = true }` in `hyprland.lua`, and `bind=SUPER,q,killclient,` in `mango/config.conf` so holding `Super+Q` continuously closes focused windows in sequence like KDE.
   - **Pitfall (Scope Keybind Edits Strictly to the Requested Chord)**: Modify only the exact key chord requested by the user — never add or alter secondary/shifted variants (`Mod+Shift+Q`, `Alt+F4`) across compositors unless explicitly asked.
   - **Pitfall (Umbriel Built-In `Mod+Q` Non-Repeat & Mango Seeded Config)**: Umbriel's built-in default and upstream example set `repeat = false` on `Mod+Q`, stopping held window-close after one window; explicitly set `repeat = true`. For Mango, patch both `/home/aesc/tonelico/nixos/home/files/config/mango/config.conf` and `~/.config/mango/config.conf` — `seedDesktopDefaults` in `modules/home/desktop/configuration.nix` only copies `mango/config.conf` when `~/.config/mango/config.conf` does not exist.
3. To apply and verify Umbriel config changes immediately into a live session before running `nixos-rebuild switch`:
   - Ensure `xdg.configFile."umbriel/config.toml"` in `modules/home/desktop/configuration.nix` sets `force = true;` so Home Manager can cleanly replace the symlink on the next rebuild.
   - Point `~/.config/umbriel/config.toml` to `/home/aesc/tonelico/nixos/home/files/config/umbriel/config.toml`, run `umbriel config validate --json`, and reload live via `umbriel msg config-reload`.
4. To configure and hot-apply Hyprland 0.55+ Lua (`modules/desktop/sessions/hyprland/hyprland.lua`):
   - Inspect the installed Lua API type definitions at `$(dirname $(dirname $(readlink -f $(command -v hyprctl))))/share/hypr/stubs/hl.meta.lua` before editing `hyprland.lua`.
   - For 9 always-open workspaces matching Mango's 9 tags (rendered by Noctalia when `widget.workspaces.show_empty = true`), declare `hl.workspace_rule({ workspace = tostring(i), persistent = true })` inside `for i = 1, 9 do` — `workspace` in `hl.workspace_rule` must be a string (`tostring(i)`), as `hlWorkspaceRule` checks `lua_type(L, -1) == LUA_TSTRING`.
   - **Pitfall (`hyprctl reload` Pins Canonical `/nix/store` Path When Started With `--config`)**: When Hyprland starts with `--config ~/.config/hypr/hyprland.lua` pointing to a Home Manager symlink, `getMainConfigPath()` calls `std::filesystem::canonical()` at startup and overwrites `g_pCompositor->m_explicitConfigPath` in memory with the resolved `/nix/store/...-hm_hyprhyprland.lua` path. Updating `~/.config/hypr/hyprland.lua` mid-session is ignored by both `hyprctl reload` and `hyprctl reload full-reset` (which reload the old store path and clear runtime rules). To apply Lua config changes immediately to a running session before re-login, execute them via `hyprctl eval '<lua_code>'` and verify with `hyprctl workspacerules -j` and `hyprctl workspaces -j`.

### 4. Staging in `/home/aesc/tonelico/nixos`, Syncing to `/etc/nixos`, and Exporting
1. **Pitfall**: Direct `write_file`/`patch` calls to `/etc/nixos/*` are blocked by the tool sandbox (`Refusing to write to sensitive system path`). Always edit files under `/home/aesc/tonelico/nixos` first.
2. Update the flake lock if inputs changed:
   ```bash
   nix flake lock --update-input <input_name> /home/aesc/tonelico/nixos
   ```
   - **Pitfall (Flake Lock NAR Hash Mismatch on Dirty/External Inputs)**: If `nixos-rebuild switch` fails with `NAR hash mismatch in input ... expected '...' but got '...'` (e.g. `zalo-for-linux`), run `nix flake update <input_name> --flake /etc/nixos` and copy the resolved `flake.lock` back to `/home/aesc/tonelico/nixos/flake.lock`.
3. Sync `/home/aesc/tonelico/nixos` to `/etc/nixos` without overwriting machine-local hardware and host files (use `/run/wrappers/bin/sudo` because `/run/current-system/sw/bin/sudo` lacks the setuid bit in non-login shells):
   ```bash
   /run/wrappers/bin/sudo rsync -a --delete \
     --exclude='.git' \
     --exclude='hosts/tonelico/host.nix' \
     --exclude='hardware-configuration.nix' \
     --exclude='hosts/tonelico/hardware-configuration.nix' \
     --exclude='modules/features/tonelico-restore.nix' \
     /home/aesc/tonelico/nixos/ /etc/nixos/
   ```
   - **Pitfall**: `/home/aesc/tonelico/nixos/hosts/tonelico/host.nix` is the portable export variant (includes `tonelico-restore`), whereas `/etc/nixos/hosts/tonelico/host.nix` is the live host definition (`retainLocalRecovery = true; features = [ "virtualization" ];`) and `/etc/nixos` tracks `hardware-configuration.nix` locally. Overwriting those breaks the live host evaluation.
   - **Pitfall (Home Manager File Clobbering on Activation)**: If a target file under `~/.config/...` was modified as a regular file or switched from a direct file to a Home Manager managed path, HM activation fails with `Existing file '...' would be clobbered`. Set `force = true;` on the target `xdg.configFile."<path>"` entry in `modules/home/desktop/configuration.nix`.
4. Stage any newly added files in `/etc/nixos` so Nix flake evaluation sees them:
   ```bash
   /run/wrappers/bin/sudo git -C /etc/nixos add -N <new_paths>
   ```
5. Activate and verify:
   ```bash
   /run/wrappers/bin/sudo nixos-rebuild switch --flake /etc/nixos#tonelico
   ```
6. Add any new `~/.config/<compositor>` directory to `/home/aesc/tonelico/manifest/home.list` and run `/home/aesc/tonelico/export.sh` so the portable export repository stays in sync and passes secret/gitleaks checks.

### 5. Desktop Browser Declarative Policies (`modules/home/packages/browsers.nix`)
LibreWolf is the sole declarative browser across NixOS, Home Manager (`BROWSER = "librewolf"`), XDG MIME defaults (`~/.config/mimeapps.list` -> `librewolf.desktop`), KDE global shortcuts (`[services][librewolf.desktop]` in `~/.config/kglobalshortcutsrc`), and `Super+Z`/`Mod+Z` across all Wayland compositors (`chromium` and Chrome PWAs are removed).
1. Always preserve all user settings in `modules/home/packages/browsers.nix`:
   - Keep `SearchEngines` (`Default = "Google"` with search suggestions), `ManagedBookmarks` (all 10 Gmail accounts), `SanitizeOnShutdown` (all `false`, `Locked = true`), `privacy.sanitize.sanitizeOnShutdown = false`, `privacy.clearOnShutdown.* = false`, `privacy.resistFingerprinting = false`, `privacy.fingerprintingProtection = true` (`+AllTargets,-CSSPrefersColorScheme,-JSDateTimeUTC,-FrameRate`), dark theme (`ui.systemUsesDarkTheme = 1`, `layout.css.prefers-color-scheme.content-override = 0` with `Status = "default"`), `@testpilot-containers`, and `uBlock0@raymondhill.net` with its 31 filter lists.
   - Keep `widget.use-xdg-desktop-portal.mime-handler = 0` and `browser.shell.checkDefaultBrowser = false` for fast startup, but never set `widget.use-xdg-desktop-portal.settings = 0` or lock `browser.theme.toolbar-theme` (which breaks Firefox's dark theme detection).
2. Avoid the three Wayland/fontconfig startup stalls and crashes:
   - **Pitfall (`dbus-daemon --systemd-activation` & `WAYLAND_SOCKET=""`)**: Calling `dbus-update-activation-environment WAYLAND_SOCKET=` sets `WAYLAND_SOCKET=""` in D-Bus and forwards it to `systemd --user`. In `libwayland-client`, `getenv("WAYLAND_SOCKET")` being non-NULL (`""`) causes `wl_display_connect(NULL)` to fail before checking `WAYLAND_DISPLAY`, breaking `xdg-desktop-portal-hyprland.service` and stalling GTK/Firefox startup on D-Bus portal timeouts (25–75s). Always run `systemctl --user unset-environment` after `dbus-update-activation-environment` in `theme-session-cleanup` and `hypr-session-ready`, and never pass `WAYLAND_SOCKET=` to `dbus-update-activation-environment`.
   - **Pitfall (Cross-version `~/.cache/fontconfig` symlinks)**: Symlinking `.cache-9 -> .cache-12` in `~/.cache/fontconfig` causes `libfontconfig.so.1` (`FcNameUnparseLangSet -> FcStrBufString`) to `SIGSEGV` inside `gfxFcPlatformFontList::InitSharedFontListForPlatform()` on LibreWolf startup, triggering repeated crash-recovery restarts into Troubleshoot Mode. Fix by wiping `~/.cache/fontconfig/*` and running `fc-cache -f`.
   - **Pitfall (`clean-stray-sessions` process `comm` matching)**: The Nix wrapper for `librewolf` executes `.librewolf-wrapped`, which the Linux kernel truncates to 15 characters (`.librewolf-wrap`) in `/proc/<pid>/comm`. Match both `librewolf` and `.librewolf-wrap` in `clean-stray-sessions` (`pgrep -u "$uid" -x 'librewolf|\.librewolf-wrap'`).

### 6. Troubleshooting Bluetooth LE Mice/Keyboards (HoG / `uhid`) in Wayland Sessions
When a Bluetooth LE mouse or keyboard shows `Connected: yes` in `bluetoothctl` or the Noctalia bar but does not move the cursor or send keys in a Wayland session:
1. Check `/proc/bus/input/devices` and `/dev/input/event*` for a `uhid` kernel input node (`Sysfs=/devices/virtual/misc/uhid/...`) before inspecting the compositor:
   ```bash
   cat /proc/bus/input/devices | grep -A 8 -i "uhid"
   ```
   - **Pitfall**: Do not debug the Wayland compositor's `libinput` backend when `/proc/bus/input/devices` has no `uhid` entry for the Bluetooth device — Wayland compositors only consume kernel `/dev/input/event*` nodes created by BlueZ's `uhid` driver.
2. Inspect `journalctl -u bluetooth -n 50 --no-pager` for HoG errors:
   - `profiles/input/hog-lib.c:report_map_read_cb() Report Map read failed: Attribute requires authentication before read/write`
   - `profiles/input/hog-lib.c:proto_mode_read_cb() ATT protocol error`
   - **Pitfall (BlueZ 5.86 `bt_hog` In-Memory Wedge)**: In BlueZ `profiles/input/hog-lib.c`, if `report_map_read_cb()` fails once on an unauthenticated connection before SMP pairing finishes, `hog->get_rep_id` remains non-zero in memory and `hog->reports` is already populated. On subsequent reconnects (even after pairing completes), `remove_gatt_req()` skips reading the GATT `Report Map` (`0x2A4B`) and never calls `uhid_create()`, leaving the mouse `Connected: yes` with no `/dev/input/event*` node for the rest of `bluetoothd`'s lifetime.
3. Recover the device without re-pairing:
   - Confirm the bond and `[LongTermKey]` exist (`bluetoothctl info <MAC>` shows `Paired: yes`, `Bonded: yes`, `Trusted: yes`; redact any raw LTK/IRK values as `[REDACTED]` if inspecting `/var/lib/bluetooth`).
   - Restart `bluetooth.service` to clear the wedged in-memory `bt_hog` state in `bluetoothd`:
     ```bash
     sudo systemctl restart bluetooth.service
     ```
   - Wake the BLE mouse/keyboard (move/click it so it advertises, or run `bluetoothctl connect <MAC>`) and verify the new `/devices/virtual/misc/uhid/...` node appears in `/proc/bus/input/devices` and `sudo dmesg | tail -n 20`.
   - **Pitfall**: If capturing HCI packets with `btmon`, stop it with `sudo pkill -x btmon` (exact process name) rather than `sudo pkill -f btmon` — `-f` matches the parent shell command line and kills the subshell with `SIGTERM`.

### 7. Configuring Custom Keyboards via VIA & Raw HID on NixOS Wayland
When configuring custom QMK/VIA keyboards (e.g. Wave 75 RGB `36b0:3009`, Keychron, Womier) in pure Wayland (Niri/Hyprland/Sway):
1. **Wayland Flags for Electron VIA (`via-nativia`)**:
   - The packaged Electron binary defaults to X11 ozone and crashes with `Missing X server or $DISPLAY` in pure Wayland without XWayland.
   - Wrap or launch with `--ozone-platform-hint=auto --enable-features=UseOzonePlatform --no-sandbox` (e.g. in `~/.local/bin/via`).
   - Ensure `~/.config/gtk-3.0/noctalia-extensions.css` exists (even if empty) to prevent GTK theme parsing errors from spamming the logs.
2. **NixOS udev Permissions for Raw HID**:
   - Ensure the keyboard's vendor/product IDs have a udev rule exposing `hidraw*` to user sessions:
     ```nix
     KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="<VID>", ATTRS{idProduct}=="<PID>", MODE="0660", GROUP="users", TAG+="uaccess"
     ```
   - Verify access with `test -r /dev/hidrawX && test -w /dev/hidrawX`.
3. **Resolving VIA "Searching for devices..." Hangs**:
   - **V2 Definitions Toggle**: Custom keyboards whose JSON files lack the `v3` `$schema` are V2 definitions. Loading them on the **Design** tab while `Use V2 definitions (deprecated)` is **OFF** will preview the keymap but will fail to pair in the **Configure** tab. Always toggle `Use V2 definitions (deprecated)` to **ON** before clicking **Load Draft Definition**.
   - **Physical Wired Mode Requirement**: Tri-mode keyboards (Wired / 2.4G / Bluetooth) must be in active USB wired mode (e.g. `Fn + 5` on Wave 75; `Fn + 4` is 2.4G wireless). QMK/VIA configuration packets are ignored over wireless modes.
   - **Dongle Endpoint Interference**: If the wireless 2.4G USB dongle (`36b0:3002`) is plugged into the laptop alongside the USB cable, unplug it temporarily. Electron VIA's `select-hid-device` picks `deviceList[0]` automatically; if the dongle or the boot keyboard endpoint (`hidraw1`) sits before the raw HID endpoint (`hidraw2`, usagePage `0xFF60`), VIA sends probe packets to the wrong interface, receives `[Errno 11] Resource temporarily unavailable`, and hangs indefinitely.

